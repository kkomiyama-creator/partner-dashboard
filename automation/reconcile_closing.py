# -*- coding: utf-8 -*-
"""Cyzen「クローザー：獲得（成約）」報告と、獲得報告データ(Googleフォーム回答シート)の突合チェック(2026-10-08新設)。

【なぜ作ったか】
ダッシュボードの成約数は、クローザーが入力する獲得報告データ(シート)から数えている。一方、Cyzenには
正式な成約報告が別に出る。2026-10-08に「Cyzenは6件・ダッシュボードは4件」というずれが起き、原因は
①フォーム入力漏れ(大城斉)と、②未成約のまま入力された行(伊禮廣児・9/16「不出、再指定まち」)だった。
同じずれを毎日見つけられるように、Cyzen報告とシートを突き合わせて差分を出す。

【出力】
- 「Cyzenにあるがシートに無い」＝入力漏れの疑い → data/closing_supplement.csv に行を足せば自動で補完される
- 「シートにあるがCyzenに成約報告が無い」＝未成約のまま入力された/報告漏れの疑い → 不要なら data/closing_exclude.csv に書いて除外
※ ci_refresh.py は取得後に補完/除外を適用済みのCSVを書き出すので、このチェックは「未対応の差分」だけを出す。

【シートの鮮度(2026-10-14修正)】
data/closing_live.csv はGitHub Actions(ci_refresh)が使う作業ファイルで、手元では自動更新されない。
2026-10-14に10/11時点の古いコピーと突合してしまい、シートに入力済みの6件を「入力漏れ」と誤検知した。
そのため ①Google認証情報(GOOGLE_OAUTH_*)があれば獲得報告シートを毎回取得して突合(補完/除外も適用)、
②無ければ --closing-csv で渡された/既定のCSVを使うが、CSV内の最新タイムスタンプが突合期間の
終端より古い場合は「判定不可(STALE)」とし、差分を出さない(誤検知防止)。

使い方:
  python3 reconcile_closing.py --days 3            # 直近3日(当日含む)の成約を突合
  python3 reconcile_closing.py --days 3 --md       # Slack/ログ向けの文面も出力
"""
import argparse
import csv
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA_DIR = os.path.join(HERE, "data")
DEF_NAME = "クローザー：獲得（成約）"
LOOKBACK_EXTRA = 14  # 報告日とシート入力日が数日ずれる事例(再報告など)を拾うための余白


def norm(x):
    x = (x or "")
    for ch in (" ", "　", "様", "邸", "さん", "(", ")", "（", "）"):
        x = x.replace(ch, "")
    return x


def same_person(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def jst(created_at):
    # Cyzen APIのcreated_atはUTC(例: 2026-10-08T08:48:27 → JST 17:48)
    return datetime.datetime.fromisoformat(created_at[:19]) + datetime.timedelta(hours=9)


def fetch_cyzen_closings(start, end):
    from cyzen_api_client import CyzenAPIClient
    from build_attendance_api import fetch_reports_page
    client = CyzenAPIClient()
    out, d = [], start
    while d <= end:
        d2 = min(d + datetime.timedelta(days=6), end)
        for r in fetch_reports_page(client, f"{d}T00:00:00", f"{d2}T23:59:59"):
            if r.get("report_definition_name") != DEF_NAME:
                continue
            it = {i["item_name"]: i["item_value"] for i in r["report_items"]}
            out.append({
                "report_id": r["report_id"],
                "at": jst(r["created_at"]),
                "customer": str(it.get("契約者(漢字＋カタカナを記載)") or "").strip(),
                "apo": str(it.get("アポインター氏名") or "").strip(),
                "closer": str(it.get("クローザー氏名") or "").strip(),
                "case": (it.get("お客様（スポット）") or {}).get("spot_name") if isinstance(it.get("お客様（スポット）"), dict) else it.get("お客様（スポット）"),
            })
        d = d2 + datetime.timedelta(days=1)
    # 同一report_idの重複除去
    seen, uniq = set(), []
    for r in out:
        if r["report_id"] not in seen:
            seen.add(r["report_id"])
            uniq.append(r)
    return uniq


def read_sheet(closing_csv):
    with open(closing_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    out = []
    for r in rows[1:]:
        if len(r) < 9 or not r[0].strip():
            continue
        try:
            at = datetime.datetime.strptime(r[8].strip(), "%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue
        out.append({"customer": r[0].strip(), "apo": r[1].strip(), "closer": r[2].strip(), "at": at, "note": (r[12] if len(r) > 12 else "")})
    return out


def fetch_live_closing_csv(out_path):
    """獲得報告シートを最新で取得してCSVに書き出す(補完/除外も適用)。認証情報が無い/失敗時はNone。"""
    if not all(os.environ.get(k) for k in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN")):
        return None
    try:
        from googleapiclient.discovery import build
        import gsheets_client_ci as g
        service = build("sheets", "v4", credentials=g.get_credentials())
        sid, gid = next((i, d) for k, _, i, d in g.SHEETS if k == "closing")
        g.fetch_sheet_as_csv(service, sid, out_path, gid=gid)
        from ci_refresh import apply_closing_supplement
        apply_closing_supplement(out_path)
        return out_path
    except Exception as e:  # noqa: BLE001
        print(f"[warn] シートのライブ取得に失敗: {e}", file=sys.stderr)
        return None


def latest_sheet_timestamp(rows):
    return max((r["at"] for r in rows), default=None)


def reconcile(days, closing_csv):
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()
    win_start = today - datetime.timedelta(days=days - 1)
    cy = fetch_cyzen_closings(win_start - datetime.timedelta(days=LOOKBACK_EXTRA), today)
    sheet = read_sheet(closing_csv)
    last = latest_sheet_timestamp(sheet)
    # シートの最新入力が突合期間の開始より前＝コピーが古い。古いコピーでの突合は誤検知になるため判定しない。
    if last is None or last.date() < win_start:
        return {"window": [win_start.isoformat(), today.isoformat()], "stale": True,
                "sheet_latest": last.strftime("%Y/%m/%d %H:%M:%S") if last else None,
                "counts_by_day": {}, "missing_in_sheet": [], "sheet_only": []}
    in_win = lambda dt: win_start <= dt.date() <= today
    missing = [c for c in cy if in_win(c["at"]) and not any(same_person(c["customer"], s["customer"]) for s in sheet)]
    sheet_only = [s for s in sheet if in_win(s["at"]) and not any(same_person(s["customer"], c["customer"]) for c in cy)]
    counts = {}
    for d in (win_start + datetime.timedelta(days=i) for i in range((today - win_start).days + 1)):
        counts[d.isoformat()] = {
            "cyzen": sum(1 for c in cy if c["at"].date() == d),
            "sheet": sum(1 for s in sheet if s["at"].date() == d),
        }
    return {
        "window": [win_start.isoformat(), today.isoformat()],
        "stale": False,
        "sheet_latest": last.strftime("%Y/%m/%d %H:%M:%S"),
        "counts_by_day": counts,
        "missing_in_sheet": [{**m, "at": m["at"].strftime("%Y/%m/%d %H:%M:%S")} for m in missing],
        "sheet_only": [{**s, "at": s["at"].strftime("%Y/%m/%d %H:%M:%S")} for s in sheet_only],
    }


def to_markdown(res):
    if res.get("stale"):
        return (f"獲得報告の突合：判定不可（STALE）。参照したシートのコピーの最新入力が {res['sheet_latest']} で、"
                f"突合期間({res['window'][0]}〜)より古いため、差分は出していません。"
                "シートを最新化して再実行するか、獲得報告シート本体を直接確認してください。")
    lines = [f"獲得報告の突合（{res['window'][0]}〜{res['window'][1]}）",
             "※日別の件数は、Cyzen報告日とシート入力日が数日ずれることがあるため参考値。判定はお客様単位の突合結果で見る"]
    for d, c in res["counts_by_day"].items():
        lines.append(f"・{d[5:].replace('-', '/')}: Cyzen成約報告 {c['cyzen']}件／ダッシュボード(シート) {c['sheet']}件")
    if res["missing_in_sheet"]:
        lines.append("【Cyzenにあるがシートに無い（入力漏れの疑い）】")
        for m in res["missing_in_sheet"]:
            lines.append(f"・{m['customer']}（アポ:{m['apo']}／クローザー:{m['closer']}／{m['at'][5:16]}）")
    if res["sheet_only"]:
        lines.append("【シートにあるがCyzenに成約報告が無い（未成約のまま入力の疑い）】")
        for s in res["sheet_only"]:
            lines.append(f"・{s['customer']}（アポ:{s['apo']}／クローザー:{s['closer']}／{s['at'][5:16]}）{('備考:' + s['note']) if s['note'] else ''}")
    if not res["missing_in_sheet"] and not res["sheet_only"]:
        lines.append("差分なし。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--closing-csv", default=os.path.join(DATA_DIR, "closing_live.csv"))
    ap.add_argument("--out", default=os.path.join(DATA_DIR, "closing_reconcile.json"))
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    live = fetch_live_closing_csv(os.path.join(DATA_DIR, "closing_reconcile_src.csv"))
    if live:
        print("[info] 獲得報告シートを最新で取得して突合します")
        a.closing_csv = live
    res = reconcile(a.days, a.closing_csv)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    if res.get("stale"):
        print(f"STALE=1 sheet_latest={res['sheet_latest']} -> 判定不可 ({a.out})")
    print(f"missing_in_sheet={len(res['missing_in_sheet'])} sheet_only={len(res['sheet_only'])} -> {a.out}")
    if a.md:
        print(to_markdown(res))


if __name__ == "__main__":
    main()
