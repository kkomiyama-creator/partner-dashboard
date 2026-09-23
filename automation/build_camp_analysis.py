# -*- coding: utf-8 -*-
"""山中湖合宿（2026/09/14開催・38名）の前後実績比較（2026-09-22追加）。

役員会議事録（2026-09-16定例）で「参加者の行動量・KPI・成約数の変化を追跡して役員会へ報告する」
と決定されたことを受けて作成。参加者名簿・生産性グループ（ロットワイラー組/柴犬組/ちわわ組）は
`data/camp_20260914_roster.json`（濵西さん提供のPDF「FF営業研修合宿_生産性グループ分け_38名」を
そのまま転記したもの）。

【比較の設計】
合宿当日(9/14)を境に、前後で同じ日数の窓を取って比較する（月次生産性のような長期平均ではなく、
直後の行動変化を見たいため）。
  合宿前 = 9/6 〜 9/13（8暦日）
  合宿後 = 9/15 〜 asof（可変長。日次実行のたびに1日ずつ伸びる）
公平な比較のため、後窓と同じ暦日数になるよう前窓を後ろから遡って再計算する
（例: asofが9/22なら後窓8日→前窓も8日=9/6〜9/13、asofが9/25なら後窓11日→前窓は9/3〜9/13）。

「所定稼働日数」は build_forecast.day_type() の区分（火曜非稼働・祝日は出勤扱い）を再利用し、
窓ごとに実際の日付構成から計算する（固定の月22日換算ではなく、この短い窓の実態に合わせる）。

【正直さルール】合宿からの経過日数が浅いうちは個人の生産性（円/日）は入金1件の有無で大きく振れる
ノイズの多い指標。個人テーブルには経過日数を明示し、グループ単位の平均・改善者数割合も併記して
「まだ判断できる段階か」を利用者が自分で判断できるようにする。
"""
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from company_resolver import canon_name, norm_name  # noqa: E402
from ranking_core import parse_price  # noqa: E402
from build_forecast import day_type  # noqa: E402  火曜非稼働・祝日出勤扱いの判定を合宿分析でも再利用

CAMP_DATE = "2026/09/14"
BEFORE_WINDOW_END = "2026/09/13"  # 合宿前日


def _scheduled_workdays(start, end):
    """'YYYY/MM/DD'区間（両端含む）の所定稼働日数（火曜非稼働・祝日出勤扱い）。"""
    s = datetime.datetime.strptime(start, "%Y/%m/%d").date()
    e = datetime.datetime.strptime(end, "%Y/%m/%d").date()
    n = 0
    d = s
    while d <= e:
        if day_type(d.year, d.month, d.day) != "火":
            n += 1
        d += datetime.timedelta(days=1)
    return n


def _load_daily(roster_csv, closing_csv):
    """{norm_name: {date: {'apo': n, 'seiyaku': n, 'uriage': n}}}"""
    per_person = {}

    def bucket(name):
        n = norm_name(canon_name(name))
        return per_person.setdefault(n, {})

    with open(roster_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            name = row[idx["アポインター"]].strip()
            d = row[idx["獲得日"]].strip()
            if not name or not d:
                continue
            day = bucket(name).setdefault(d, {"apo": 0, "seiyaku": 0, "uriage": 0})
            day["apo"] += 1

    with open(closing_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            name = row[idx["クローザー名"]].strip()
            ts = row[idx["タイムスタンプ"]].strip()
            if not name or not ts:
                continue
            d = ts.split(" ")[0]
            price = parse_price(row[idx["販売価格"]])
            day = bucket(name).setdefault(d, {"apo": 0, "seiyaku": 0, "uriage": 0})
            day["seiyaku"] += 1
            day["uriage"] += price

    return per_person


def _sum_window(daily, start, end):
    apo = seiyaku = uriage = 0
    for d, v in daily.items():
        if start <= d <= end:
            apo += v["apo"]
            seiyaku += v["seiyaku"]
            uriage += v["uriage"]
    return {"apo": apo, "seiyaku": seiyaku, "uriage": uriage}


def build_camp_analysis(roster_csv, closing_csv, roster_json, asof):
    """asof: 'YYYY/MM/DD'。合宿ロースターJSONを読み、前後比較を返す。"""
    with open(roster_json, encoding="utf-8") as f:
        camp = json.load(f)

    after_start = "2026/09/15"
    after_days = (datetime.datetime.strptime(asof, "%Y/%m/%d").date()
                  - datetime.datetime.strptime(after_start, "%Y/%m/%d").date()).days + 1
    after_days = max(after_days, 0)
    before_end_dt = datetime.datetime.strptime(BEFORE_WINDOW_END, "%Y/%m/%d").date()
    before_start_dt = before_end_dt - datetime.timedelta(days=after_days - 1) if after_days > 0 else before_end_dt
    before_start = before_start_dt.strftime("%Y/%m/%d")
    before_end = BEFORE_WINDOW_END
    after_end = asof if after_days > 0 else after_start

    daily = _load_daily(roster_csv, closing_csv)

    before_workdays = _scheduled_workdays(before_start, before_end) if after_days > 0 else 0
    after_workdays = _scheduled_workdays(after_start, after_end) if after_days > 0 else 0

    members = []
    for m in camp["members"]:
        n = norm_name(canon_name(m["name"]))
        d = daily.get(n, {})
        before = _sum_window(d, before_start, before_end) if after_days > 0 else {"apo": 0, "seiyaku": 0, "uriage": 0}
        after = _sum_window(d, after_start, after_end) if after_days > 0 else {"apo": 0, "seiyaku": 0, "uriage": 0}
        prod_before = round(before["uriage"] / before_workdays) if before_workdays else None
        prod_after = round(after["uriage"] / after_workdays) if after_workdays else None
        members.append({
            "name": m["name"], "company": m["company"], "group": m["group"],
            "baseline_productivity": m["baseline_productivity"],
            "before": before, "after": after,
            "productivity_before": prod_before, "productivity_after": prod_after,
            "productivity_delta": (prod_after - prod_before) if (prod_before is not None and prod_after is not None) else None,
        })

    # グループ別サマリー
    groups = {}
    for g in ("ロットワイラー組", "柴犬組", "ちわわ組"):
        rows = [m for m in members if m["group"] == g]
        n = len(rows)
        improved = sum(1 for m in rows if m["productivity_delta"] is not None and m["productivity_delta"] > 0)
        has_delta = [m for m in rows if m["productivity_delta"] is not None]
        groups[g] = {
            "n": n,
            "apo_before": sum(m["before"]["apo"] for m in rows),
            "apo_after": sum(m["after"]["apo"] for m in rows),
            "seiyaku_before": sum(m["before"]["seiyaku"] for m in rows),
            "seiyaku_after": sum(m["after"]["seiyaku"] for m in rows),
            "uriage_before": sum(m["before"]["uriage"] for m in rows),
            "uriage_after": sum(m["after"]["uriage"] for m in rows),
            "avg_productivity_before": round(sum(m["productivity_before"] or 0 for m in rows) / n) if n else None,
            "avg_productivity_after": round(sum(m["productivity_after"] or 0 for m in rows) / n) if n else None,
            "improved_count": improved,
            "improved_rate": round(improved / len(has_delta) * 100, 1) if has_delta else None,
            "n_with_delta": len(has_delta),
        }

    return {
        "camp_date": camp["camp_date"],
        "title": camp["title"],
        "grouping_method": camp["grouping_method"],
        "note": camp.get("note", ""),
        "asof": asof,
        "elapsed_days_since_camp": after_days,
        "before_window": {"start": before_start, "end": before_end, "scheduled_workdays": before_workdays},
        "after_window": {"start": after_start, "end": after_end, "scheduled_workdays": after_workdays},
        "groups": groups,
        "members": members,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv", required=True)
    ap.add_argument("--roster-json", required=True)
    ap.add_argument("--asof", required=True, help="YYYY/MM/DD")
    ap.add_argument("--out")
    args = ap.parse_args()
    result = build_camp_analysis(args.roster_csv, args.closing_csv, args.roster_json, args.asof)
    out = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out)
