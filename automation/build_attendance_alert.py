# -*- coding: utf-8 -*-
"""出退勤放置アラート・最終出退勤・スポット作成数・ルート自動記録数のマスターCSV
（data/cyzen_dashboard_master.csv形式）を、Cyzenの生データ（出勤報告/勤務終了報告のreport-v2エクスポート・
スポット台帳エクスポート・行動履歴の集計＝data/route_history.json）から機械的に生成する。

旧版のcyzen_dashboard_master.csvは「アラート判定」「状況解説」等が人手で作文された固定スナップショット
（2026-07-28時点）で、日次自動更新の中で再生成する手段が無かった（SKILL.mdにも取得手順の記載が無かった）。
このスクリプトはranking_core.load_attendance_alert_master()が読む26列ヘッダーのうち実際に使われる列
（ユーザーコード/ユーザー名/グループ名/アラート判定/アイコン/出退勤区分/状況解説/最新出勤日時/最新退勤日時/
スポット作成数/ルート自動記録）を、report-v2から取得した出勤報告CSVと勤務終了報告CSVの実データだけで
機械的に埋める。ルート自動記録数は2026-08-01からdata/route_history.json（build_route_history.pyが行動履歴
CSVから集計）を参照して実データを入れる（--route-history-jsonを省略した場合のみ0固定＝旧仕様と同じ）。

使い方:
  python3 build_attendance_alert.py \
    --clock-in-csv <出勤報告CSV> \
    --clock-out-csv <勤務終了報告CSV> \
    --spot-csv <スポット台帳CSV（省略可・スポット作成数の集計に使う）> \
    --spot-start 2026-08-01 --spot-end 2026-08-01 \
    --route-history-json ../data/route_history.json \
    --now "2026-08-01 20:30:00" \
    --out data/cyzen_dashboard_master.csv
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from company_resolver import canon_name, norm_name  # noqa: E402

HEADER = [
    "ユーザーコード", "ユーザー名", "グループ名", "アラート判定", "アイコン", "出退勤区分", "状況解説",
    "最新出勤日時", "最新退勤日時", "スポット作成数", "総打刻数", "出勤", "勤務終了", "ルート自動記録",
    "アポ獲得", "訪問（アポインター）", "訪問結果（クローザー）", "アポ後確依頼", "シミュレーション依頼",
    "アポインターメモ", "東京都補助金 事前申請", "新規商談（クローザー：6/24～直販テスト）",
    "訪問結果（クローザー：6/24～直販テスト）", "再商談（クローザー：6/24～直販テスト）",
    "再商談結果（クローザー：6/24～直販テスト）", "東京都補助金 事前申請変更依頼",
    "報告種別（最新）", "最新報告日時", "報告日に出退勤記録なし",
    "長期放置日数", "勤怠つけっぱなし疑い",
]

ALERT_THRESHOLD_HOURS = 3  # 出勤したまま退勤なしでこの時間を超えたら「放置」とみなす暫定値


def _read_report_csv(path):
    """report-v2エクスポート（出勤報告/勤務終了報告）を読み、ユーザーごとの最新報告日時を返す。
    戻り値: {(user_code, user_name): (最新報告日時 datetime, 最新報告日時 raw str)}"""
    latest = {}
    with open(path, encoding="cp932", errors="replace") as f:
        for row in csv.DictReader(f):
            code = (row.get("ユーザーコード") or "").strip()
            name = canon_name((row.get("ユーザー名") or "").strip())
            ts_raw = (row.get("報告日時") or "").strip()
            if not name or not ts_raw:
                continue
            try:
                ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            key = (code, name)
            if key not in latest or ts > latest[key][0]:
                latest[key] = (ts, ts_raw)
    return latest


def _read_group(path):
    """report-v2エクスポートからユーザーごとのグループ名（最初に見つかった値）を取る。"""
    group = {}
    with open(path, encoding="cp932", errors="replace") as f:
        for row in csv.DictReader(f):
            name = canon_name((row.get("ユーザー名") or "").strip())
            g = (row.get("グループ名") or "").strip()
            if name and g and name not in group:
                group[name] = g
    return group


def _read_dates(path):
    """report-v2エクスポート（出勤報告/勤務終了報告）を読み、ユーザーごとの報告日（YYYY-MM-DD）の
    集合を返す。最新報告日時だけでなく「その日に打刻があったか」を判定するために全件を見る。
    戻り値: {canon_name: set(date_str)}"""
    dates = defaultdict(set)
    with open(path, encoding="cp932", errors="replace") as f:
        for row in csv.DictReader(f):
            name = canon_name((row.get("ユーザー名") or "").strip())
            date = (row.get("日付") or "").strip()
            if not name or not date:
                continue
            dates[name].add(date)
    return dates


def _read_report_latest_multi(paths_with_kind):
    """アポ後確依頼／クローザー獲得（成約）等のreport-v2エクスポート（複数可）を読み、
    ユーザーごとに一番新しい報告（日時・種別）を返す。
    paths_with_kind: [(csv_path, 種別ラベル), ...]
    戻り値: {canon_name: (datetime, raw_str, kind)}"""
    latest = {}
    for path, kind in paths_with_kind:
        if not path:
            continue
        with open(path, encoding="cp932", errors="replace") as f:
            for row in csv.DictReader(f):
                name = canon_name((row.get("ユーザー名") or "").strip())
                ts_raw = (row.get("報告日時") or "").strip()
                if not name or not ts_raw:
                    continue
                try:
                    ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if name not in latest or ts > latest[name][0]:
                    latest[name] = (ts, ts_raw, kind)
    return latest


def _spot_counts(spot_csv, start, end):
    """スポット台帳CSVから作成者ごとの作成数（作成日がstart~endの範囲）を集計する。"""
    counts = defaultdict(int)
    if not spot_csv:
        return counts
    with open(spot_csv, encoding="cp932", errors="replace") as f:
        r = csv.reader(f)
        header = next(r)
        idx = {h: i for i, h in enumerate(header)}
        for row in r:
            created = row[idx["作成日"]].strip()[:10] if idx.get("作成日") is not None and len(row) > idx["作成日"] else ""
            creator = row[idx["作成者"]].strip() if idx.get("作成者") is not None and len(row) > idx["作成者"] else ""
            if not created or not creator:
                continue
            if start and created < start:
                continue
            if end and created > end:
                continue
            counts[canon_name(creator)] += 1
    return counts


def _route_counts(route_history_json, start, end):
    """data/route_history.json（build_route_history.pyの出力）からユーザーごとのルート自動記録数を
    start~end（YYYY-MM-DD・両端含む）の範囲で合算する。"""
    counts = defaultdict(int)
    if not route_history_json:
        return counts
    try:
        with open(route_history_json, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return counts
    for date, users in data.items():
        if start and date < start:
            continue
        if end and date > end:
            continue
        for name, rec in users.items():
            counts[canon_name(name)] += rec.get("route_count", 0)
    return counts


def _route_active_on(route_history_json, date_str):
    """data/route_history.jsonから、指定日（YYYY-MM-DD）にルート自動記録が1件以上あった
    ユーザー名（canon_name）の集合を返す。「出退勤ボタンは数日〜数週間前から止まったままだが、
    実際にはその日も稼働している（＝勤怠つけっぱなし）」の判定に使う。"""
    names = set()
    if not route_history_json or not date_str:
        return names
    try:
        with open(route_history_json, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return names
    for name, rec in data.get(date_str, {}).items():
        if rec.get("route_count", 0) > 0:
            names.add(canon_name(name))
    return names


def build(clock_in_csv, clock_out_csv, spot_csv=None, spot_start=None, spot_end=None,
          route_history_json=None, now=None, apo_confirm_csv=None, closer_getoku_csv=None):
    now = now or datetime.now()
    route_active_today = _route_active_on(route_history_json, now.strftime("%Y-%m-%d"))
    clock_in = _read_report_csv(clock_in_csv)
    clock_out = _read_report_csv(clock_out_csv)
    group_in = _read_group(clock_in_csv)
    group_out = _read_group(clock_out_csv)
    spot_counts = _spot_counts(spot_csv, spot_start, spot_end)
    route_counts = _route_counts(route_history_json, spot_start, spot_end)

    # 「アポ後確依頼／クローザー獲得報告を出しているのに、その報告日に出退勤打刻が無い人」の判定用。
    # 必ずアラートしたい指標（2026-08-09 小宮山さんの要望）: 出退勤の「放置」判定（最新出勤>最新退勤で
    # N時間超）だけでは、報告書はきちんと出しているのに出退勤打刻の習慣が無い人を拾いきれないため、
    # 実際の営業活動（報告提出）の日付と出退勤打刻の日付を突き合わせる別軸のチェックを加える。
    attendance_dates = defaultdict(set)
    for name, dset in _read_dates(clock_in_csv).items():
        attendance_dates[name] |= dset
    for name, dset in _read_dates(clock_out_csv).items():
        attendance_dates[name] |= dset
    report_latest = _read_report_latest_multi([
        (apo_confirm_csv, "アポ後確依頼"), (closer_getoku_csv, "クローザー獲得"),
    ])

    users = {}
    for (code, name), (ts, raw) in clock_in.items():
        users.setdefault(name, {"user_code": code, "name": name})["last_in"] = (ts, raw)
    for (code, name), (ts, raw) in clock_out.items():
        users.setdefault(name, {"user_code": code, "name": name})["last_out"] = (ts, raw)
    for name, (ts, raw, kind) in report_latest.items():
        users.setdefault(name, {"user_code": "", "name": name})["last_report"] = (ts, raw, kind)

    rows = []
    for name, rec in sorted(users.items()):
        last_in = rec.get("last_in")
        last_out = rec.get("last_out")
        group = group_in.get(name) or group_out.get(name) or ""
        spot_count = spot_counts.get(name, 0)

        chronic_days = ""
        chronic_stuck = "FALSE"
        if last_in and (not last_out or last_in[0] > last_out[0]):
            elapsed_h = (now - last_in[0]).total_seconds() / 3600
            if elapsed_h >= ALERT_THRESHOLD_HOURS:
                alert, icon, status = "要対応", "🚨", "出勤放置中"
                note = f"{last_in[1]}に出勤後、{elapsed_h:.1f}時間経過しても退勤報告なし"
                # 最終出勤が「今日」以外＝ボタン自体が数日〜数週間前から止まったまま、という
                # 慢性放置ケース。当日のルート自動記録（GPS）があれば、実際には稼働しているのに
                # 出退勤ボタンだけ押していない「勤怠つけっぱなし」と判定できる（2026-08-12追加、
                # 小宮山さんの指摘: 報告形跡は無いがルート自動記録は立っている人を見分けたい）。
                if last_in[0].date() != now.date():
                    chronic_days = str((now.date() - last_in[0].date()).days)
                    if canon_name(name) in route_active_today:
                        chronic_stuck = "TRUE"
            else:
                alert, icon, status = "正常", "", "出勤中"
                note = f"{last_in[1]}に出勤（退勤報告待ち）"
        elif last_in and last_out:
            alert, icon, status = "正常", "", "退勤済み"
            note = f"{last_out[1]}に退勤"
        elif not last_in:
            alert, icon, status = "未打刻", "", "未打刻"
            note = "対象期間内に出勤報告なし"
        else:
            alert, icon, status = "正常", "", "退勤済み"
            note = ""

        last_report = rec.get("last_report")
        report_kind = last_report[2] if last_report else ""
        report_ts_raw = last_report[1] if last_report else ""
        report_mismatch = ""
        if last_report:
            report_date = last_report[1][:10]
            report_mismatch = "TRUE" if report_date not in attendance_dates.get(name, set()) else "FALSE"

        row = {h: "" for h in HEADER}
        row.update({
            "ユーザーコード": rec.get("user_code", ""),
            "ユーザー名": name,
            "グループ名": group,
            "アラート判定": alert,
            "アイコン": icon,
            "出退勤区分": status,
            "状況解説": note,
            "最新出勤日時": last_in[1] if last_in else "",
            "最新退勤日時": last_out[1] if last_out else "",
            "スポット作成数": str(spot_count),
            "ルート自動記録": str(route_counts.get(name, 0)),
            "報告種別（最新）": report_kind,
            "最新報告日時": report_ts_raw,
            "報告日に出退勤記録なし": report_mismatch,
            "長期放置日数": chronic_days,
            "勤怠つけっぱなし疑い": chronic_stuck,
        })
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clock-in-csv", required=True)
    ap.add_argument("--clock-out-csv", required=True)
    ap.add_argument("--spot-csv")
    ap.add_argument("--spot-start")
    ap.add_argument("--spot-end")
    ap.add_argument("--route-history-json", help="data/route_history.json（build_route_history.pyの出力）。省略時はルート自動記録数が0固定になる")
    ap.add_argument("--apo-confirm-csv", help="report-v2の「アポ後確依頼」エクスポート（省略可・報告日と出退勤打刻日のズレ判定に使う）")
    ap.add_argument("--closer-getoku-csv", help="report-v2の「クローザー：獲得（成約）」エクスポート（省略可・同上）")
    ap.add_argument("--now", help="YYYY-MM-DD HH:MM:SS（省略時は実行時刻）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    now = datetime.strptime(args.now, "%Y-%m-%d %H:%M:%S") if args.now else None
    rows = build(args.clock_in_csv, args.clock_out_csv, args.spot_csv, args.spot_start, args.spot_end,
                 args.route_history_json, now, args.apo_confirm_csv, args.closer_getoku_csv)

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)

    n_alert = sum(1 for r in rows if r["アラート判定"] == "要対応")
    n_unmarked = sum(1 for r in rows if r["アラート判定"] == "未打刻")
    print(f"wrote {len(rows)} users -> {args.out} (要対応={n_alert}, 未打刻={n_unmarked})")


if __name__ == "__main__":
    main()
