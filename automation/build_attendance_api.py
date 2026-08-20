# -*- coding: utf-8 -*-
"""Cyzen連携APIの /reports から出勤報告・勤務終了報告を取得し、既存の
attendance_merged.csv / clockout_merged.csv と同じ列構成のCSVを生成する（2026-08-18）。

これまでreport-v2画面のブラウザ操作でCSV出力していた部分をAPI直接取得に置き換える
（要件定義フェーズ3）。report_definition_idは事前に GET /report_definitions で
特定済み（テスト項目「クローザー：獲得（6/10テスト）」等と紛れないよう名称完全一致で確認）。

  出勤報告:     b5c50316e56e70b7f2924db3cb6f4fbd
  勤務終了報告: 4bbaf66d5f64e22a7d7081e16ce091a1

【重要な実測事実】 /reports は report_definition_id を渡しても実際にはフィルタされず、
期間内の全報告書種別が返ってくる（2026-08-18実測）。そのため取得後にPython側で
report_definition_id / report_definition_name によるクライアントサイド絞り込みを行う
（要件定義が期待していた「サーバー側の厳格指定」ではなく「取得後のフィルタ」に変更）。

出力列は既存の attendance_merged.csv と完全一致させ、ranking_core.py 側のロジックは
一切変更しない（要件定義4.4のアダプタ層方針）。

使い方:
  python3 build_attendance_api.py --start 2026-08-01 --end 2026-08-18 \
      --attendance-out ../data/attendance_merged.csv \
      --clockout-out ../data/clockout_merged.csv
"""
import argparse
import collections
import csv
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cyzen_api_client import CyzenAPIClient, build_role_map  # noqa: E402

CHUNK_DAYS = 7  # 要件定義4.2の一般則に合わせ保守的に7日区切りにする（/reportsの実際の上限は未確認のため）

REPORT_DEFS = {
    "b5c50316e56e70b7f2924db3cb6f4fbd": ("出勤報告", "出勤"),
    "4bbaf66d5f64e22a7d7081e16ce091a1": ("勤務終了報告", "勤務終了"),
}

HEADER = ["報告書名", "グループコード", "グループ名", "ステータス名", "行動種別名",
          "スポットコード", "スポット名", "スポット所在地", "スポットタグ",
          "スポット作成者顧客コード", "スポット作成者名", "ユーザーコード", "ユーザー名",
          "訪問日時", "手書きサイン", "報告日時", "日付", "時間", "本日の予定"]


def _daterange_chunks(start, end, days=CHUNK_DAYS):
    d1 = datetime.date.fromisoformat(start)
    d2 = datetime.date.fromisoformat(end)
    while d1 <= d2:
        d3 = min(d1 + datetime.timedelta(days=days - 1), d2)
        yield d1.isoformat(), d3.isoformat()
        d1 = d3 + datetime.timedelta(days=1)


def fetch_reports_page(client, from_date, to_date):
    """/reports は next_report_id と next_report_updated_at を両方指定しないと
    40000エラーになる複合カーソル方式のため、get_all()を使わず専用ページングする。

    【実測事実・2026-08-18】/schedulesと違い、/reportsの期間指定パラメータ名は
    from_date/to_date ではなく updated_from/updated_to（更新日時ベース）。
    from_date/to_dateを渡しても無視され「現在時刻から7日前まで」がデフォルトで
    返ってきてしまう（ドキュメントに明記が無く実機検証で判明）。"""
    out = []
    cursor_id, cursor_updated = None, None
    for _ in range(500):
        params = {"updated_from": from_date, "updated_to": to_date}
        if cursor_id:
            params["next_report_id"] = cursor_id
            params["next_report_updated_at"] = cursor_updated
        data = client.get("reports", **params)
        chunk = data.get("reports") or []
        out.extend(chunk)
        cursor_id = data.get("next_report_id")
        cursor_updated = data.get("next_report_updated_at")
        if not cursor_id or not chunk:
            return out
    raise RuntimeError("reports のページングが500回を超えました")


def fetch_reports(client, start, end):
    out = []
    for d1, d2 in _daterange_chunks(start, end):
        out.extend(fetch_reports_page(client, f"{d1}T00:00:00", f"{d2}T23:59:59"))
    return out


def build(start, end):
    client = CyzenAPIClient()
    role_map, _, _ = build_role_map(client)
    groups = client.get_all("groups", key="groups")
    group_map = {g["group_id"]: g for g in groups}

    reports = fetch_reports(client, start, end)

    seen = set()
    rows = {"attendance_merged.csv": [], "clockout_merged.csv": []}
    skipped_users = collections.Counter()
    for r in reports:
        rid = r.get("report_id")
        if rid in seen:
            continue
        seen.add(rid)
        def_id = r.get("report_definition_id")
        if def_id not in REPORT_DEFS:
            continue
        report_name, status_name = REPORT_DEFS[def_id]

        items = {it["item_name"]: it.get("item_value", "") for it in (r.get("report_items") or [])}
        user = role_map.get(r.get("user_id"))
        if not user:
            skipped_users[r.get("user_id")] += 1
            continue
        group = group_map.get(r.get("group_id"), {})

        created = r.get("created_at") or ""
        try:
            utc = datetime.datetime.fromisoformat(created)
            jst = utc + datetime.timedelta(hours=9)
            houkoku_nichiji = jst.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            houkoku_nichiji = created

        row = [
            report_name, group.get("group_code", ""), group.get("group_name", ""),
            status_name, "",
            "", "", "", "", "", "",
            user["code"], user["name"],
            "", "－", houkoku_nichiji,
            items.get("日付", ""), items.get("時間", ""), items.get("本日の予定", ""),
        ]
        target = "attendance_merged.csv" if report_name == "出勤報告" else "clockout_merged.csv"
        rows[target].append(row)

    return rows, skipped_users, client.request_count


def write_csv(path, rows):
    with open(path, "w", encoding="cp932", errors="replace", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--attendance-out", required=True)
    ap.add_argument("--clockout-out", required=True)
    args = ap.parse_args()

    rows, skipped_users, req_count = build(args.start, args.end)
    write_csv(args.attendance_out, rows["attendance_merged.csv"])
    write_csv(args.clockout_out, rows["clockout_merged.csv"])

    print(f"出勤報告 {len(rows['attendance_merged.csv'])}件 -> {args.attendance_out}")
    print(f"勤務終了報告 {len(rows['clockout_merged.csv'])}件 -> {args.clockout_out}")
    if skipped_users:
        print(f"user_idがロールマップに無く除外: {sum(skipped_users.values())}件（{len(skipped_users)}ユニークID）")
    print(f"APIリクエスト数: {req_count}")


if __name__ == "__main__":
    main()
