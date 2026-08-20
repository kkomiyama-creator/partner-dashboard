# -*- coding: utf-8 -*-
"""パートナーごとの「本日稼働者」シフト提出状況を、Cyzen出退勤打刻の実績データと突き合わせて
data/shift_status.json を生成する（2026-08-09 小宮山さんの依頼）。

入力の「※新：本日稼働者確認用元データ」Google Sheet（本日稼働者確認用タブ）は、各パートナー企業が
「今日は誰が稼働するか」を自己申告するシフト提出シート。A列=稼働者(本日)・B列=会社名 が
本日分の申告者リスト（1行1人）。このスクリプトは、その申告者のうち、実際にCyzenで
出勤報告／勤務終了報告のいずれの打刻も無い人を「シフト提出しているのに打刻が見られない人」として
会社別・全体でまとめる。

使い方:
  python3 build_shift_status.py \
    --shift-csv "<本日稼働者確認用シートのCSV>" \
    --attendance-csv data/attendance_merged.csv \
    --clockout-csv data/clockout_merged.csv \
    --today 2026-08-09 \
    --out data/shift_status.json
"""
import argparse
import csv
import json
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from company_resolver import canon_name, resolve_company  # noqa: E402


def _read_shift(shift_csv):
    """本日稼働者確認用シートのA列(稼働者)/B列(会社名)を読む。同シートには右側に別集計
    （会社名+本日稼働数、昨日稼働者リスト等）が横に並んでいるが、それらは使わない。"""
    people = []
    with open(shift_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        header = next(r)
        for row in r:
            if len(row) < 2:
                continue
            name = row[0].strip()
            company = row[1].strip()
            if not name:
                continue
            people.append({"name": name, "shift_company": company})
    return people


def _attendance_dates(paths):
    """出勤報告/勤務終了報告CSVから、ユーザーごとの打刻日(YYYY-MM-DD)集合を返す。"""
    dates = defaultdict(set)
    for path in paths:
        with open(path, encoding="cp932", errors="replace") as f:
            for row in csv.DictReader(f):
                name = canon_name((row.get("ユーザー名") or "").strip())
                date = (row.get("日付") or "").strip()
                if name and date:
                    dates[name].add(date)
    return dates


def build(shift_csv, attendance_csv, clockout_csv, today):
    shift_people = _read_shift(shift_csv)
    att_dates = _attendance_dates([attendance_csv, clockout_csv])

    by_company = defaultdict(lambda: {"submitted": 0, "attended_today": 0, "missing": []})
    missing_all = []
    for p in shift_people:
        name = p["name"]
        company = resolve_company(name) or p["shift_company"] or "（不明）"
        cname = canon_name(name)
        attended_today = today in att_dates.get(cname, set())
        by_company[company]["submitted"] += 1
        if attended_today:
            by_company[company]["attended_today"] += 1
        else:
            entry = {"name": name, "company": company}
            by_company[company]["missing"].append(entry)
            missing_all.append(entry)

    companies_out = []
    for company, rec in sorted(by_company.items(), key=lambda kv: -kv[1]["submitted"]):
        companies_out.append({
            "company": company,
            "submitted": rec["submitted"],
            "attended_today": rec["attended_today"],
            "missing_count": len(rec["missing"]),
            "missing": rec["missing"],
        })

    return {
        "today": today,
        "total_submitted": len(shift_people),
        "total_attended_today": sum(c["attended_today"] for c in companies_out),
        "total_missing": len(missing_all),
        "companies": companies_out,
        "missing_all": missing_all,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shift-csv", required=True)
    ap.add_argument("--attendance-csv", required=True)
    ap.add_argument("--clockout-csv", required=True)
    ap.add_argument("--today", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    result = build(args.shift_csv, args.attendance_csv, args.clockout_csv, args.today)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"wrote {args.out}: シフト提出{result['total_submitted']}名 / 本日打刻あり{result['total_attended_today']}名 / "
          f"シフト提出だが打刻なし{result['total_missing']}名（{len(result['companies'])}社）")


if __name__ == "__main__":
    main()
