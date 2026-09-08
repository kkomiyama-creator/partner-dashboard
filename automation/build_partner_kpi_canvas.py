#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
パートナーKPI進捗（Canvas用一覧表）を、デプロイ済みindex.htmlの
COMPANY_TARGETS_DEFAULT（目標値・Googleフォーム集計）とPERIODS.month（Cyzen当月実績）
から再計算する。

前提（2026-09-08 小宮山さん確認済み）:
  - パートナーの稼働日は月・火が休み（祝日は考慮しない、単純なカレンダー曜日ベース）
  - 標準進捗率 = 経過稼働日数 ÷ 当月稼働日数
  - 着地予想 = 実績 ÷ 経過稼働日数 × 当月稼働日数
  - 信号: 🔵標準以上 / 🟡標準の半分以上・標準未満 / 🔴標準の半分未満 / ⚪目標値未受領

「稼働予定者数(フォーム)」列はGoogleフォーム回答（company_targets.json内のmembers）。
「実稼働者数」列は2026-09-08 小宮山さん確認済みの仕様変更により「本日」の人数を表示する
（月間累計ではない）。本日データは build_today_attendance.py で別途生成した
data/today_attendance.json を読み込む。無い場合は「ー」表示にフォールバックする
（間違って月間累計を出さないようにするため、フォールバック先はPERIODS.month.headcountにはしない）。

使い方:
  python3 build_partner_kpi_canvas.py                  # 今日の日付で計算
  python3 build_partner_kpi_canvas.py --date 2026-09-08 # 日付を指定して計算（過去の再現用）
  python3 build_partner_kpi_canvas.py --attendance-json data/today_attendance.json

出力:
  標準進捗率・着地予想などを計算した上で、Canvas用Markdownテーブルと
  Slack通知用サマリーテキストを標準出力に表示する（そのままslack_update_canvas /
  slack_send_message の引数に使う想定）。
"""
import argparse
import calendar
import datetime
import json
import re
import sys

INDEX_HTML = "index.html"
# 目標値がまだ届いていないが対象であることが分かっている会社
# （まだ最新のindex.htmlに載っていない場合の保険。company_targets.jsonへの反映が
#   完了していれば自然とtargetsに含まれるので、その場合はここに書かなくてよい）
KNOWN_PENDING_EXTRA = ["井上推進", "株式会社ALL CONNECT"]
EXCLUDE = {"株式会社Fit Founder"}


def workdays_in_month(year, month):
    """月・火を除いた日数（祝日は考慮しない単純カレンダー計算）。"""
    last_day = calendar.monthrange(year, month)[1]
    count = 0
    for d in range(1, last_day + 1):
        wd = datetime.date(year, month, d).weekday()  # Mon=0, Tue=1
        if wd not in (0, 1):
            count += 1
    return count


def workdays_elapsed(year, month, today_day):
    count = 0
    for d in range(1, today_day + 1):
        wd = datetime.date(year, month, d).weekday()
        if wd not in (0, 1):
            count += 1
    return count


def load_html():
    with open(INDEX_HTML, encoding="utf-8") as f:
        return f.read()


def extract_balanced_json(text, start_marker):
    m = re.search(re.escape(start_marker) + r"(\{.*)", text, re.S)
    if not m:
        sys.exit(f"{start_marker} が見つかりません")
    txt = m.group(1)
    depth = 0
    for i, ch in enumerate(txt):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(txt[: i + 1])
    sys.exit(f"{start_marker} のJSONが閉じていません")


def signal(ratio, std):
    if ratio is None:
        return None
    if ratio >= std:
        return "🔵"
    if ratio >= std / 2:
        return "🟡"
    return "🔴"


def metric(actual, target, std, factor):
    if target is None or target == 0:
        return {"actual": actual, "target": target, "ratio": None, "sig": None, "landing": None}
    ratio = actual / target
    return {
        "actual": actual,
        "target": target,
        "ratio": ratio,
        "sig": signal(ratio, std),
        "landing": round(actual * factor, 1),
    }


def cell(m):
    if m is None or m["target"] is None or m["target"] == 0:
        return "ー", "ー", "ー", "ー"
    return (
        f"{m['actual']}/{m['target']}件",
        f"{m['ratio']*100:.1f}%",
        m["sig"],
        f"{m['landing']}件",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD（省略時は今日）")
    ap.add_argument(
        "--attendance-json",
        default=None,
        help="build_today_attendance.pyの出力JSON（本日の会社別実働者数）。"
        "指定が無い場合、実稼働者数は全社ー表示になる（月間累計にフォールバックしない）。",
    )
    args = ap.parse_args()

    today = (
        datetime.date.fromisoformat(args.date)
        if args.date
        else datetime.date.today()
    )
    year, month, day = today.year, today.month, today.day

    wd_month = workdays_in_month(year, month)
    wd_elapsed = workdays_elapsed(year, month, day)
    std = wd_elapsed / wd_month
    factor = wd_month / wd_elapsed if wd_elapsed else 0

    html = load_html()
    periods = extract_balanced_json(html, "const PERIODS = ")
    targets = extract_balanced_json(html, "const COMPANY_TARGETS_DEFAULT = ")
    month_data = periods["month"]
    actual_by_co = {c["company"]: c for c in month_data["companies"]}

    today_attendance_counts = {}
    if args.attendance_json:
        with open(args.attendance_json, encoding="utf-8") as f:
            today_attendance_counts = json.load(f).get("counts", {})

    for co in KNOWN_PENDING_EXTRA:
        targets.setdefault(co, {})

    rows = []
    for co, t in targets.items():
        if co in EXCLUDE:
            continue
        apo_seiyaku_t = t.get("apo_seiyaku")
        clo_seiyaku_t = t.get("clo_seiyaku")
        apo_num_t = t.get("apo")
        members = t.get("members")
        headcount_plan = len(members) if members else None

        a = actual_by_co.get(co, {})
        headcount_actual = today_attendance_counts.get(co)

        has_any = any(v is not None for v in [apo_seiyaku_t, clo_seiyaku_t, apo_num_t])
        if not has_any:
            rows.append(
                {
                    "co": co,
                    "pending": True,
                    "headcount_plan": headcount_plan,
                    "headcount_actual": headcount_actual,
                }
            )
            continue

        apo_seiyaku_a = a.get("apo_seiyaku", 0) or 0
        clo_seiyaku_a = a.get("clo_seiyaku", 0) or 0
        apo_num_a = a.get("apo_kakutoku", 0) or 0

        rows.append(
            {
                "co": co,
                "pending": False,
                "headcount_plan": headcount_plan,
                "headcount_actual": headcount_actual,
                "apo_seiyaku": metric(apo_seiyaku_a, apo_seiyaku_t, std, factor),
                "clo_seiyaku": metric(clo_seiyaku_a, clo_seiyaku_t, std, factor),
                "apo_num": metric(apo_num_a, apo_num_t, std, factor),
            }
        )

    def sort_key(r):
        if r["pending"]:
            return -1
        vals = [
            m["ratio"]
            for m in [r["apo_seiyaku"], r["clo_seiyaku"], r["apo_num"]]
            if m["ratio"] is not None
        ]
        return min(vals) if vals else -1

    rows.sort(key=sort_key, reverse=True)

    lines = []
    lines.append(
        "|会社名|"
        "アポ成約実績/目標|進捗率|信号|着地予想|"
        "クロ成約実績/目標|進捗率|信号|着地予想|"
        "(参考)アポ数実績/目標|進捗率|信号|着地予想|"
        "稼働予定者数(フォーム)|本日の実稼働者数(Cyzen出退勤)|"
    )
    lines.append("|" + "---|" * 15)

    counts = {"🔵": 0, "🟡": 0, "🔴": 0, "⚪": 0}

    for r in rows:
        hc_plan = f"{r['headcount_plan']}名" if r["headcount_plan"] else "ー"
        hc_actual = f"{r['headcount_actual']}名" if r["headcount_actual"] else "ー"
        if r["pending"]:
            lines.append(
                f"|{r['co']}|未受領|ー|⚪|ー|未受領|ー|⚪|ー|未受領|ー|⚪|ー|{hc_plan}|{hc_actual}|"
            )
            counts["⚪"] += 1
            continue
        a1, p1, s1, l1 = cell(r["apo_seiyaku"])
        a2, p2, s2, l2 = cell(r["clo_seiyaku"])
        a3, p3, s3, l3 = cell(r["apo_num"])
        lines.append(
            f"|{r['co']}|{a1}|{p1}|{s1}|{l1}|{a2}|{p2}|{s2}|{l2}|{a3}|{p3}|{s3}|{l3}|{hc_plan}|{hc_actual}|"
        )
        # ワースト信号でサマリーカウント（最も悪い1つを代表として数える）
        sigs = [s for s in [s1, s2, s3] if s]
        if "🔴" in sigs:
            counts["🔴"] += 1
        elif "🟡" in sigs:
            counts["🟡"] += 1
        elif "🔵" in sigs:
            counts["🔵"] += 1

    print(f"# STD_RATE={std*100:.1f}% WD_MONTH={wd_month} WD_ELAPSED={wd_elapsed} DATE={today.isoformat()}")
    print(f"# SUMMARY 🔵{counts['🔵']}社 🟡{counts['🟡']}社 🔴{counts['🔴']}社 ⚪{counts['⚪']}社")
    print()
    print("\n".join(lines))


if __name__ == "__main__":
    main()
