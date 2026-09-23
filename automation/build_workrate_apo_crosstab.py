# -*- coding: utf-8 -*-
"""稼働×アポ クロス分析CSVを生成する（2026-08-10追加）。
辻さんがSlackで共有した「稼働×アポ クロス分析（7月実測）」画像と同じ考え方で、
週次期間(7日間)版を作る。稼働はルート自動記録（route_history.json）基準
（出退勤打刻は押し忘れ・つけっぱなしが混在するため不採用、というのが辻さんの元資料の方針）。

対象母集団: 期間内に①ルート自動記録が1日でもある人 または ②アポ獲得が1件でもある人（roster_csv基準）
のいずれかに該当する人（両方0件の人は対象外＝元資料と同じ考え方）。

月次版の5バケット(20日以上/15〜19/10〜14/5〜9/1〜4/記録なし・アポあり)を、
7日間の週次版として 6〜7日/4〜5日/2〜3日/1日/記録なし・アポあり に比例縮小した。

使い方:
  python3 build_workrate_apo_crosstab.py \
    --roster-csv <アポインター獲得履歴CSV> \
    --closing-csv <獲得報告データCSV> \
    --route-history-json data/route_history.json \
    --start 2026-08-03 --end 2026-08-09 \
    --out <出力CSVパス>
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ranking_core import aggregate  # noqa: E402
from company_resolver import canon_name  # noqa: E402

BUCKETS = [
    ("6〜7日", lambda d: d >= 6),
    ("4〜5日", lambda d: 4 <= d <= 5),
    ("2〜3日", lambda d: 2 <= d <= 3),
    ("1日", lambda d: d == 1),
    ("記録なし・アポあり", lambda d: d == 0),
]


def _route_days(route_history_json, start, end):
    """{canon_name: 稼働日数(route_count>0の日数)}"""
    days = defaultdict(int)
    if not route_history_json or not os.path.exists(route_history_json):
        return days
    with open(route_history_json, encoding="utf-8") as f:
        data = json.load(f)
    for date, users in data.items():
        if not (start <= date <= end):
            continue
        for name, rec in users.items():
            if rec.get("route_count", 0) > 0:
                days[canon_name(name)] += 1
    return days


def build(roster_csv, closing_csv, start, end, route_history_json):
    data = aggregate(roster_csv, closing_csv, start.replace("-", "/"), end.replace("-", "/"))
    apo_count = {canon_name(r[1]): r[4] for r in data["apo_ranking"]}
    route_days = _route_days(route_history_json, start, end)

    population = set(apo_count) | set(route_days)
    rows = []
    for name in population:
        rows.append({
            "name": name,
            "days": route_days.get(name, 0),
            "apo": apo_count.get(name, 0),
        })

    bucket_rows = []
    for label, pred in BUCKETS:
        members = [r for r in rows if pred(r["days"])]
        if label == "記録なし・アポあり":
            members = [r for r in members if r["apo"] > 0]
        n = len(members)
        apo_getter = sum(1 for r in members if r["apo"] > 0)
        apo_zero = n - apo_getter
        apo_total = sum(r["apo"] for r in members)
        avg = round(apo_total / n, 2) if n else ""
        bucket_rows.append([label, n, apo_getter, apo_zero, apo_total, avg])

    total_n = len(rows)
    total_apo = sum(r["apo"] for r in rows)
    total_getter = sum(1 for r in rows if r["apo"] > 0)
    total_zero = total_n - total_getter
    total_avg = round(total_apo / total_n, 2) if total_n else ""
    bucket_rows.append(["合計", total_n, total_getter, total_zero, total_apo, total_avg])

    return bucket_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv", required=True)
    ap.add_argument("--route-history-json", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = build(args.roster_csv, args.closing_csv, args.start, args.end, args.route_history_json)
    header = ["稼働日数（ルート自動記録・7日間中）", "人数", "アポ獲得者数", "アポゼロ人数", "アポ獲得合計", "1人あたり平均"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
