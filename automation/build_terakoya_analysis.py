# -*- coding: utf-8 -*-
"""FF寺子屋（隔週アポインター向け研修）累計参加者の月次実績推移（2026-09-24追加）。

小宮山さんの依頼「過去の寺子屋参加者全員の実績の推移を一覧で見て、研修効果を確認したい」を受けて
作成。参加者名簿は terakoya-outreach スキルの参加者履歴（data/参加者リスト.md 相当の実データ）を
このスキル側に静的コピーした `data/terakoya_roster.json`（山中湖合宿の `camp_20260914_roster.json`
と同じ設計＝CI側が terakoya-outreach ディレクトリに依存しないよう自己完結させるための複製）。
新しい回の参加者が確定したら、このJSONの `members` に追記して再生成する。

【集計方法】
月次の「1営業日あたりアポ数」（月〜金・祝日考慮なしの簡易カレンダー。dashboard_gross分析の
terakoya-outreach/build_target_list.py と同じ定義）と、アポ成約数・クロ成約数・売上を月ごとに
積み上げる。対象月は「参加者の最初のセッション月の前月（研修前ベースライン）」〜「asofの月」。

【正直さルール】研修は隔週で人によって参加開始月が違うため、全員一律の「研修前/後」比較はできない。
個人ごとに『初回参加月の前月』を自分のベースラインとして扱い、そこから直近月までの変化を見る設計に
した（画面側にその旨を明記する）。ロースターに実績が全く無い人（会社名不明・他事業部の直販等）は
月次値がすべて0のまま出る——「実績が伸びていない」のではなく「データソースにそもそも存在しない」
ケースがあるため、画面側で「データなし」の可能性を注記する。
"""
import csv
import datetime
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from company_resolver import canon_name, norm_name  # noqa: E402
from ranking_core import parse_price  # noqa: E402
from build_camp_analysis import _scheduled_workdays  # noqa: E402  所定稼働日数(火曜非稼働)の定義を再利用


def business_days(start, end):
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += datetime.timedelta(days=1)
    return n


def month_bounds(year, month, as_of=None):
    start = datetime.date(year, month, 1)
    if month == 12:
        end = datetime.date(year, 12, 31)
    else:
        end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    if as_of and as_of.year == year and as_of.month == month and as_of < end:
        end = as_of
    return start, end


def _month_seq(start_ym, end_ym):
    """(yyyy,mm) start/end（両端含む）を古い順のリストで返す。"""
    y, m = start_ym
    out = []
    while (y, m) <= end_ym:
        out.append((y, m))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def _load_monthly(roster_csv, closing_csv):
    """{norm_name: {"YYYY-MM": {"apo":n,"apo_seiyaku":n,"clo_seiyaku":n,"uriage":n}}}"""
    per_person = defaultdict(lambda: defaultdict(lambda: {"apo": 0, "apo_seiyaku": 0, "clo_seiyaku": 0, "uriage": 0}))

    with open(roster_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            name = row[idx["アポインター"]].strip()
            d = row[idx["獲得日"]].strip()
            if not name or not d:
                continue
            try:
                ym = d[:7].replace("/", "-")
                datetime.datetime.strptime(d, "%Y/%m/%d")
            except ValueError:
                continue
            key = norm_name(canon_name(name))
            per_person[key][ym]["apo"] += 1

    with open(closing_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            ts = row[idx["タイムスタンプ"]].strip()
            if not ts:
                continue
            ym = ts[:7].replace("/", "-")
            price = parse_price(row[idx["販売価格"]])
            apo_name = row[idx["アポインター名"]].strip()
            clo_name = row[idx["クローザー名"]].strip()
            if apo_name:
                per_person[norm_name(canon_name(apo_name))][ym]["apo_seiyaku"] += 1
            if clo_name:
                per_person[norm_name(canon_name(clo_name))][ym]["clo_seiyaku"] += 1
                per_person[norm_name(canon_name(clo_name))][ym]["uriage"] += price

    return per_person


def _load_daily(roster_csv, closing_csv):
    """{norm_name: {"YYYY-MM-DD": {"apo":n,"apo_seiyaku":n,"clo_seiyaku":n,"uriage":n}}}"""
    per_person = defaultdict(lambda: defaultdict(lambda: {"apo": 0, "apo_seiyaku": 0, "clo_seiyaku": 0, "uriage": 0}))

    with open(roster_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            name = row[idx["アポインター"]].strip()
            d = row[idx["獲得日"]].strip()
            if not name or not d:
                continue
            try:
                datetime.datetime.strptime(d, "%Y/%m/%d")
            except ValueError:
                continue
            key = norm_name(canon_name(name))
            per_person[key][d.replace("/", "-")]["apo"] += 1

    with open(closing_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            ts = row[idx["タイムスタンプ"]].strip()
            if not ts:
                continue
            d = ts.split(" ")[0].replace("/", "-")
            price = parse_price(row[idx["販売価格"]])
            apo_name = row[idx["アポインター名"]].strip()
            clo_name = row[idx["クローザー名"]].strip()
            if apo_name:
                per_person[norm_name(canon_name(apo_name))][d]["apo_seiyaku"] += 1
            if clo_name:
                per_person[norm_name(canon_name(clo_name))][d]["clo_seiyaku"] += 1
                per_person[norm_name(canon_name(clo_name))][d]["uriage"] += price

    return per_person


def _sum_range(daily_by_date, start_str, end_str):
    """daily_by_date: {"YYYY-MM-DD": {...}}。start/end: 'YYYY-MM-DD'（両端含む）。"""
    apo = apo_seiyaku = clo_seiyaku = uriage = 0
    for d, v in daily_by_date.items():
        if start_str <= d <= end_str:
            apo += v["apo"]
            apo_seiyaku += v["apo_seiyaku"]
            clo_seiyaku += v["clo_seiyaku"]
            uriage += v["uriage"]
    return {"apo": apo, "apo_seiyaku": apo_seiyaku, "clo_seiyaku": clo_seiyaku, "uriage": uriage}


def _session_breakdown(roster, daily_data, asof_date):
    """開催回ごとに、その回の参加者だけを対象にした前後比較（前7日間 vs 開催日〜次回前日 or asof）を返す。"""
    sessions_sorted = sorted(roster["sessions"], key=lambda s: s["date"])
    out = []
    for i, s in enumerate(sessions_sorted):
        session_date = datetime.date.fromisoformat(s["date"])
        before_end = session_date - datetime.timedelta(days=1)
        before_start = session_date - datetime.timedelta(days=7)
        next_dates = [datetime.date.fromisoformat(s2["date"]) for s2 in sessions_sorted[i + 1:]]
        is_latest = not next_dates
        after_end = (min(next_dates) - datetime.timedelta(days=1)) if next_dates else asof_date
        after_end = min(after_end, asof_date)
        after_start = session_date

        before_start_s, before_end_s = before_start.isoformat(), before_end.isoformat()
        after_start_s, after_end_s = after_start.isoformat(), after_end.isoformat()
        elapsed_days = max((after_end - after_start).days + 1, 0)

        before_workdays = _scheduled_workdays(before_start.strftime("%Y/%m/%d"), before_end.strftime("%Y/%m/%d")) \
            if before_end >= before_start else 0
        after_workdays = _scheduled_workdays(after_start.strftime("%Y/%m/%d"), after_end.strftime("%Y/%m/%d")) \
            if after_end >= after_start else 0

        attendees = []
        for m in roster["members"]:
            if s["label"] not in m["sessions"]:
                continue
            key = norm_name(canon_name(m["name"]))
            person_daily = daily_data.get(key, {})
            before = _sum_range(person_daily, before_start_s, before_end_s)
            after = _sum_range(person_daily, after_start_s, after_end_s) if elapsed_days > 0 else \
                {"apo": 0, "apo_seiyaku": 0, "clo_seiyaku": 0, "uriage": 0}
            avg_before = round(before["apo"] / before_workdays, 3) if before_workdays else None
            avg_after = round(after["apo"] / after_workdays, 3) if after_workdays else None
            if avg_before is not None and avg_after is not None:
                if avg_before == 0 and avg_after == 0:
                    trend = "flat"
                elif avg_before == 0:
                    trend = "up"
                else:
                    delta_pct = (avg_after - avg_before) / avg_before * 100
                    trend = "up" if delta_pct > 10 else ("down" if delta_pct < -10 else "flat")
            else:
                trend = None
            attendees.append({
                "name": m["name"], "company": m["company"] or "（不明）",
                "other_sessions": [x for x in m["sessions"] if x != s["label"]],
                "before": before, "after": after,
                "avg_apo_before": avg_before, "avg_apo_after": avg_after,
                "trend": trend,
            })

        attendees.sort(key=lambda a: (a["trend"] is None,
                                       {"down": 0, "flat": 1, "up": 2, None: 3}.get(a["trend"], 3), a["name"]))
        with_trend = [a for a in attendees if a["trend"] is not None]
        out.append({
            "label": s["label"], "date": s["date"],
            "before_window": {"start": before_start_s, "end": before_end_s, "workdays": before_workdays},
            "after_window": {"start": after_start_s, "end": after_end_s, "workdays": after_workdays,
                              "elapsed_days": elapsed_days, "in_progress": is_latest},
            "n_attendees": len(attendees),
            "improved_count": sum(1 for a in with_trend if a["trend"] == "up"),
            "declined_count": sum(1 for a in with_trend if a["trend"] == "down"),
            "flat_count": sum(1 for a in with_trend if a["trend"] == "flat"),
            "attendees": attendees,
        })
    return out


def build_terakoya_analysis(roster_csv, closing_csv, roster_json, asof):
    """asof: 'YYYY/MM/DD'。"""
    with open(roster_json, encoding="utf-8") as f:
        roster = json.load(f)

    asof_date = datetime.datetime.strptime(asof, "%Y/%m/%d").date()
    sessions = roster["sessions"]
    session_date_by_label = {s["label"]: s["date"] for s in sessions}

    first_session_date = min(datetime.date.fromisoformat(s["date"]) for s in sessions)
    baseline_month = (first_session_date.year, first_session_date.month - 1) if first_session_date.month > 1 \
        else (first_session_date.year - 1, 12)
    end_month = (asof_date.year, asof_date.month)
    months = _month_seq(baseline_month, end_month)
    month_labels = [f"{y}-{m:02d}" for y, m in months]

    monthly_data = _load_monthly(roster_csv, closing_csv)
    daily_data = _load_daily(roster_csv, closing_csv)

    # 月ごとの営業日数（当月はasofまで）
    biz_days_by_month = {}
    for (y, m) in months:
        start, end = month_bounds(y, m, as_of=asof_date)
        biz_days_by_month[f"{y}-{m:02d}"] = business_days(start, end)

    # 個人詳細ドリルダウン用の全期間日別カレンダー（baseline_month初日〜asof、ゼロ埋め）。
    range_start = datetime.date(months[0][0], months[0][1], 1)
    all_dates = []
    d = range_start
    while d <= asof_date:
        all_dates.append(d.isoformat())
        d += datetime.timedelta(days=1)

    members_out = []
    for m in roster["members"]:
        key = norm_name(canon_name(m["name"]))
        data = monthly_data.get(key, {})
        monthly = {}
        for lbl in month_labels:
            v = data.get(lbl, {"apo": 0, "apo_seiyaku": 0, "clo_seiyaku": 0, "uriage": 0})
            bd = biz_days_by_month[lbl]
            monthly[lbl] = {
                "apo": v["apo"],
                "apo_avg_per_bizday": round(v["apo"] / bd, 3) if bd else None,
                "apo_seiyaku": v["apo_seiyaku"],
                "clo_seiyaku": v["clo_seiyaku"],
                "uriage": v["uriage"],
            }
        has_any_data = any(monthly[lbl]["apo"] or monthly[lbl]["apo_seiyaku"] or monthly[lbl]["clo_seiyaku"]
                            for lbl in month_labels)

        # 個人のベースライン = 初回参加セッションの前月（無ければ全体ベースライン月）
        first_label = min(m["sessions"], key=lambda s: session_date_by_label.get(s, "9999-99-99"))
        first_date = datetime.date.fromisoformat(session_date_by_label[first_label])
        personal_baseline = (first_date.year, first_date.month - 1) if first_date.month > 1 \
            else (first_date.year - 1, 12)
        pb_label = f"{personal_baseline[0]}-{personal_baseline[1]:02d}"
        latest_label = month_labels[-1]

        baseline_avg = monthly.get(pb_label, {}).get("apo_avg_per_bizday")
        latest_avg = monthly.get(latest_label, {}).get("apo_avg_per_bizday")
        if baseline_avg is not None and latest_avg is not None:
            if baseline_avg == 0 and latest_avg == 0:
                trend = "flat"
            elif baseline_avg == 0:
                trend = "up"
            else:
                delta_pct = (latest_avg - baseline_avg) / baseline_avg * 100
                trend = "up" if delta_pct > 10 else ("down" if delta_pct < -10 else "flat")
        else:
            trend = None

        seiyaku_baseline = None
        seiyaku_latest = None
        if pb_label in monthly:
            seiyaku_baseline = monthly[pb_label]["apo_seiyaku"] + monthly[pb_label]["clo_seiyaku"]
        if latest_label in monthly:
            seiyaku_latest = monthly[latest_label]["apo_seiyaku"] + monthly[latest_label]["clo_seiyaku"]

        person_daily = daily_data.get(key, {})
        daily_list = []
        for date_str in all_dates:
            v = person_daily.get(date_str, {"apo": 0, "apo_seiyaku": 0, "clo_seiyaku": 0, "uriage": 0})
            daily_list.append([date_str, v["apo"], v["apo_seiyaku"], v["clo_seiyaku"], v["uriage"]])

        members_out.append({
            "name": m["name"],
            "company": m["company"] or "（不明）",
            "sessions": m["sessions"],
            "monthly": monthly,
            "daily": daily_list,
            "has_any_data": has_any_data,
            "personal_baseline_month": pb_label,
            "baseline_apo_avg": baseline_avg,
            "latest_apo_avg": latest_avg,
            "trend": trend,
            "seiyaku_baseline": seiyaku_baseline,
            "seiyaku_latest": seiyaku_latest,
        })

    members_out.sort(key=lambda r: (r["trend"] is None, {"down": 0, "flat": 1, "up": 2, None: 3}.get(r["trend"], 3),
                                     r["name"]))

    with_data = [m for m in members_out if m["has_any_data"]]
    with_trend = [m for m in with_data if m["trend"] is not None]
    improved = sum(1 for m in with_trend if m["trend"] == "up")
    declined = sum(1 for m in with_trend if m["trend"] == "down")
    flat = sum(1 for m in with_trend if m["trend"] == "flat")

    overall_by_month = {}
    for lbl in month_labels:
        vals = [members_out_m["monthly"][lbl]["apo_avg_per_bizday"] for members_out_m in with_data
                if members_out_m["monthly"][lbl]["apo_avg_per_bizday"] is not None]
        overall_by_month[lbl] = round(sum(vals) / len(vals), 3) if vals else None

    sessions_breakdown = _session_breakdown(roster, daily_data, asof_date)

    return {
        "asof": asof,
        "sessions": sessions,
        "months": month_labels,
        "note": roster.get("note", ""),
        "n_total": len(members_out),
        "n_with_data": len(with_data),
        "n_no_data": len(members_out) - len(with_data),
        "n_with_trend": len(with_trend),
        "improved_count": improved,
        "declined_count": declined,
        "flat_count": flat,
        "overall_avg_apo_by_month": overall_by_month,
        "members": members_out,
        "sessions_breakdown": sessions_breakdown,
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
    result = build_terakoya_analysis(args.roster_csv, args.closing_csv, args.roster_json, args.asof)
    out = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out)
