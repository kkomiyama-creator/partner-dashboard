# -*- coding: utf-8 -*-
"""kintone「アポ後確」(app 406) の後確結果「完了」案件（＝後確通過）を、Cyzenのスポットコードを
キーに「商談予定 → 結果報告」までつなぎ、担当者（アポインター）ごとの通過案件一覧を作る
（2026-11-06新設・小宮山さん指示）。

■ 個人情報の扱い（重要）
  - 406の電話番号は、Cyzenの「アポ後確依頼」報告にある電話番号と照合するためだけにメモリ上で使う。
    出力JSON・ログ・標準出力には電話番号もお客様名も一切出さない（件数だけ出す）。
  - 画面に出すスポットの目印は、Cyzenのスポットコード（FF-SH-FS-yyyymmdd-n 形式）のみ。
    形式が合わないコードは出さずに「—」にする（スポット名はお客様名などの自由記述が多いため使わない）。

■ 流れ
  406(完了) --電話番号--> Cyzen アポ後確依頼報告 --spot_id--> スポット(コード)
                                             └--spot_id--> 商談予定(確定/後確後/仮予定) ・ クローザー結果報告

使い方（環境変数 KINTONE_406_API_TOKEN と CYZEN_DASHBOARD_TOKEN が必要）:
  python3 build_kakuho_cases.py --since 2026-10-01 --out data/kakuho_cases.json
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cyzen_api_client import CyzenAPIClient, build_role_map  # noqa: E402
from build_shodan_api import fetch_schedules  # noqa: E402
from company_resolver import canon_name  # noqa: E402
import csv  # noqa: E402

KINTONE_BASE = "https://fit-founder.cybozu.com/k/v1"
APP_ID = 406
CODE_RE = re.compile(r"FF-SH-FS-\d{8}-\d+")
REQ_DEF = "アポ後確依頼"
RESULT_KIND = {"クローザー：獲得（成約）": "成約", "クローザー：敗戦": "敗戦", "クローザー：提案中": "提案中"}
SCHED_PRIORITY = {"確定": 3, "後確後（事務確認OK）": 2, "仮予定": 1}
SCHED_LABEL = {"確定": "確定", "後確後（事務確認OK）": "後確後", "仮予定": "仮予定"}
CLOSING_DEF = "クローザー：獲得（成約）"


def cn(n):
    """ダッシュボード側の集計と同じ表記ゆれ吸収（別名→正式名）。画面の担当者名と突き合わせるため。"""
    return canon_name((n or "").strip())


def same_person(a, b):
    """お客様名の緩い一致（様・邸・空白を除いた前方一致）。reconcile_closing.pyと同じ考え方。名前はメモリ内だけで使う。"""
    def nm(x):
        x = x or ""
        for ch in (" ", "\u3000", "様", "邸", "さん", "(", ")", "（", "）"):
            x = x.replace(ch, "")
        return x
    a, b = nm(a), nm(b)
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def jst(iso_utc):
    return datetime.datetime.fromisoformat(iso_utc[:19]) + datetime.timedelta(hours=9)


def norm_name(n):
    return re.sub(r"[\s\u3000]+", "", n or "").replace("髙", "高").replace("濵", "濱")


def digits(s):
    return re.sub(r"\D", "", s or "")


def fetch_kintone_done(since):
    """後確結果=完了 の 406 レコード。必要な項目だけ取得する（電話番号は突合専用）。"""
    token = os.environ.get("KINTONE_406_API_TOKEN")
    if not token:
        raise SystemExit("KINTONE_406_API_TOKEN が未設定です")
    fields = ["獲得日", "電話番号", "キャンセル有無", "アポインター", "会社名"]
    recs, offset = [], 0
    while True:
        query = f'獲得日 >= "{since}" and 後確結果 in ("完了") order by $id asc limit 500 offset {offset}'
        params = [("app", APP_ID), ("query", query)] + [("fields[]", f) for f in fields]
        req = urllib.request.Request(f"{KINTONE_BASE}/records.json?" + urllib.parse.urlencode(params),
                                     headers={"X-Cybozu-API-Token": token})
        with urllib.request.urlopen(req, timeout=60) as r:
            chunk = json.load(r)["records"]
        recs.extend(chunk)
        if len(chunk) < 500:
            return recs
        offset += 500


def fetch_reports(client, start, end):
    """updated範囲は7日以内の制限があるので、6日区切りで取得する。start/endは YYYY-MM-DD。"""
    out = []
    d1 = datetime.date.fromisoformat(start)
    d2 = datetime.date.fromisoformat(end)
    while d1 <= d2:
        d3 = min(d1 + datetime.timedelta(days=5), d2)
        cid, cupd = None, None
        for _ in range(500):
            params = {"updated_from": f"{d1}T00:00:00", "updated_to": f"{d3}T23:59:59"}
            if cid:
                params["next_report_id"] = cid
                params["next_report_updated_at"] = cupd
            data = client.get("reports", **params)
            chunk = data.get("reports") or []
            out.extend(chunk)
            cid, cupd = data.get("next_report_id"), data.get("next_report_updated_at")
            if not cid or not chunk:
                break
        d1 = d3 + datetime.timedelta(days=1)
    return out


def item(rep, name):
    for i in rep.get("report_items") or []:
        if i.get("item_name") == name:
            return i.get("item_value")
    return None


def fetch_spot_codes(client, spot_ids, start, end):
    """スポットID → スポットコード。更新日ベースの全件取得から必要分だけ拾う。"""
    want, out = set(spot_ids), {}
    d1 = datetime.date.fromisoformat(start)
    d2 = datetime.date.fromisoformat(end)
    while d1 <= d2 and len(out) < len(want):
        d3 = min(d1 + datetime.timedelta(days=6), d2)
        for s in client.get_all("spots", key="spots", updated_from=f"{d1}T00:00:00", updated_to=f"{d3}T23:59:59"):
            if s.get("spot_id") in want:
                out[s["spot_id"]] = (s.get("spot_code") or "").strip()
        d1 = d3 + datetime.timedelta(days=1)
    # 期間走査で見つからなかったスポット（作成後に更新されていない古いスポットなど）は個別に引く
    for sid in want - set(out):
        try:
            for sp in (client.get("spots", spot_id=sid).get("spots") or []):
                if sp.get("spot_id") == sid:
                    out[sid] = (sp.get("spot_code") or "").strip()
        except Exception:  # noqa: BLE001
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="獲得日の下限 YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    ap.add_argument("--today", default=None)
    ap.add_argument("--closing-csv", default=None, help="獲得報告シート(成約)のCSV。あればアポ成約/クロ成約をスポットに紐づける")
    args = ap.parse_args()
    today = (datetime.date.fromisoformat(args.today) if args.today
             else (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date())
    since = datetime.date.fromisoformat(args.since)

    recs = fetch_kintone_done(args.since)
    print(f"406 完了(獲得日>={args.since}): {len(recs)}件")

    client = CyzenAPIClient()
    role_map, _, _ = build_role_map(client)
    win_start = (since - datetime.timedelta(days=5)).isoformat()
    win_end = (today + datetime.timedelta(days=1)).isoformat()
    reports = fetch_reports(client, win_start, win_end)
    print(f"Cyzen reports: {len(reports)}件")

    # 電話番号 -> アポ後確依頼（spot_id と依頼日）。電話番号はこの辞書の中だけで使う
    by_phone = collections.defaultdict(list)
    closing_reports = []
    results_by_spot = collections.defaultdict(list)
    for r in reports:
        name = r.get("report_definition_name")
        sid = r.get("spot_id")
        if name == REQ_DEF:
            p = digits(item(r, "電話番号"))
            if len(p) >= 9 and sid:
                by_phone[p].append((sid, jst(r["created_at"]).date()))
        elif name in RESULT_KIND and sid:
            results_by_spot[sid].append((jst(r["created_at"]).date(), RESULT_KIND[name], r.get("user_id")))
        if name == CLOSING_DEF and sid:
            cust = item(r, "契約者(漢字＋カタカナを記載)")
            closing_reports.append({"sid": sid, "at": jst(r["created_at"]).date(),
                                    "customer": str(cust or "").strip(),
                                    "apo": cn(str(item(r, "アポインター氏名") or "")),
                                    "closer": cn(str(item(r, "クローザー氏名") or ""))})

    scheds = fetch_schedules(client, (since - datetime.timedelta(days=5)).isoformat(),
                             (today + datetime.timedelta(days=30)).isoformat())[0]
    sched_by_spot = collections.defaultdict(list)
    for s in scheds:
        sid = (s.get("place") or {}).get("spot_id")
        cat = (s.get("schedule_category") or {}).get("schedule_category_name")
        if sid and cat in SCHED_PRIORITY and "テスト" not in (s.get("title") or ""):
            sched_by_spot[sid].append(s)
            for rep in ((s.get("schedule_actual") or {}).get("schedule_reports") or []):
                k = RESULT_KIND.get(rep.get("report_definition_name"))
                if k:
                    results_by_spot[sid].append((jst(s["start_date"]).date(), k, rep.get("user_id")))

    matched = []  # (record, spot_id)
    unmatched = 0
    for r in recs:
        p = digits(r["電話番号"]["value"])
        d0 = datetime.date.fromisoformat(r["獲得日"]["value"])
        cands = by_phone.get(p) or []
        if not cands:
            unmatched += 1
            matched.append((r, None))  # スポット未特定。画面の件数と一覧の件数を合わせるため行は残す（電話番号は出さない）
            continue
        sid = min(cands, key=lambda c: abs((c[1] - d0).days))[0]
        matched.append((r, sid))
    print(f"電話番号で突合: 一致{len(matched) - unmatched} / 不一致{unmatched}")

    spot_ids = {sid for _, sid in matched if sid} | {c["sid"] for c in closing_reports}
    codes = fetch_spot_codes(client, spot_ids, (since - datetime.timedelta(days=5)).isoformat(), win_end)
    print(f"スポットコード取得: {sum(1 for c in codes.values() if CODE_RE.fullmatch(c))}/{len(spot_ids)}")

    cases = []
    for r, sid in matched:
        code = codes.get(sid, "") if sid else ""
        code = code if CODE_RE.fullmatch(code) else ""
        ss = sorted(sched_by_spot.get(sid, []),
                    key=lambda s: (SCHED_PRIORITY[s["schedule_category"]["schedule_category_name"]],
                                   s["start_date"]), reverse=True)
        sched = ss[0] if ss else None
        sched_label, sched_date, closer = ("なし" if sid else "不明"), "", ""
        if sched:
            sched_label = SCHED_LABEL[sched["schedule_category"]["schedule_category_name"]]
            sched_date = jst(sched["start_date"]).strftime("%Y-%m-%d")
            uids = [u.get("user_id") for u in (sched.get("users") or [])]
            # 役割タグが取れない環境でも動くよう、予定の参加者のうちアポインター本人以外をクローザーとみなす
            # （「予定作成者＝アポインター／参加者＝クローザー及びアポインター」という業務ルールによる）
            me = norm_name(r["アポインター"]["value"])
            others = [role_map[u]["name"] for u in uids if u in role_map and norm_name(role_map[u]["name"]) != me]
            closer = "・".join(others[:2])
        res = sorted(results_by_spot.get(sid, []))
        result = res[-1][1] if res else ""
        if not result and sched_date:
            result = "予定" if sched_date >= today.isoformat() else "未報告"
        cases.append({
            "apo_date": r["獲得日"]["value"],
            "apointer": cn(r["アポインター"]["value"]),
            "company": (r["会社名"]["value"] or "").strip(),
            "code": code,
            "cancel": bool(r["キャンセル有無"]["value"]),
            "sched": sched_label, "sched_date": sched_date, "closer": closer, "result": result,
        })
    cases.sort(key=lambda c: (c["apo_date"], c["apointer"]), reverse=True)

    # 成約（獲得報告シートの1行＝1成約）→ Cyzenの成約報告と照合してスポットコードを付ける。
    # お客様名の一致はメモリ内だけで使い、出力にはスポットコードと担当者名だけを残す。
    sei, sei_unmatched = [], 0
    if args.closing_csv and os.path.exists(args.closing_csv):
        used = set()
        with open(args.closing_csv, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))[1:]
        for row in rows:
            if len(row) < 9 or not row[0].strip():
                continue
            try:
                at = datetime.datetime.strptime(row[8].strip(), "%Y/%m/%d %H:%M:%S").date()
            except ValueError:
                continue
            if at < since:
                continue
            apo, clo = cn(row[1]), cn(row[2])
            cands = [(i, c) for i, c in enumerate(closing_reports)
                     if i not in used and same_person(row[0], c["customer"]) and abs((c["at"] - at).days) <= 14]
            # 担当者も合うものを優先し、同点なら日付が近いもの
            cands.sort(key=lambda ic: (not (norm_name(ic[1]["closer"]) == norm_name(clo)), abs((ic[1]["at"] - at).days)))
            code = ""
            if cands:
                i, c = cands[0]
                used.add(i)
                code = codes.get(c["sid"], "")
                code = code if CODE_RE.fullmatch(code) else ""
            else:
                sei_unmatched += 1
            sei.append({"date": at.isoformat(), "apointer": apo, "closer": clo, "code": code})
        print(f"成約: シート{len(sei)}件 / Cyzen成約報告と未照合{sei_unmatched}件 / コード付き{sum(1 for x in sei if x['code'])}件")

    stats = {"done": len(recs), "matched": len(matched), "unmatched": unmatched,
             "with_code": sum(1 for c in cases if c["code"]),
             "sei": len(sei), "sei_with_code": sum(1 for x in sei if x["code"]),
             "sched": collections.Counter(c["sched"] for c in cases),
             "result": collections.Counter(c["result"] or "-" for c in cases)}
    out = {"generated": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M"),
           "since": args.since, "stats": {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in stats.items()},
           "cases": cases, "sei": sei}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("stats:", json.dumps(out["stats"], ensure_ascii=False))
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
