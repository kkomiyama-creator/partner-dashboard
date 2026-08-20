# -*- coding: utf-8 -*-
"""8月も続けて数値が落ちている人の抽出＋寺子屋対象者の要因分析（2026-08-10追加・2026-08-10改訂・
小宮山さんKPIオーナータスク「②代理店の稼働」「③パートナー稼働人員数・適正化」用）。

canvas記載の判定方針:
  「5日間アポゼロ9名」「研修欠席16名」は7月末〜8月初の断面で、その後戻っている人も含まれるため
  単体では判断材料にならない。見るべきは「8月に入っても落ち続けている人が何人いるか」＝
  戻った人（直近週にはアポ/成約が回復している人）は対象外とする。

【2026-08-10改訂: 役割ごとに評価軸を分離】
当初はアポ獲得数・成約数(アポ側)・成約数(クロ側)の3指標のうちどれか1つでも低下していれば
「低下継続中」としていたが、小宮山さんから「アポインターはアポ数で、クローザーはクロージング数で
それぞれ見てほしい」との指摘。役割（Cyzenユーザーマスタの「メンバー属性」）で評価軸を分ける:
  - 役割=アポインター（クローザー属性なし）: アポ獲得数の低下のみで判定
  - 役割=クローザー（アポインター属性なし）: クロ成約数の低下のみで判定
  - 役割=どちらも: アポ獲得数・クロ成約数それぞれ独立に判定（どちらか一方でも低下していれば対象）
  - 役割不明（マスタに属性が無い/未登録）: 実際に持っているデータ（アポ獲得履歴 or 獲得報告データ）
    がある方の軸で判定するフォールバック
成約数(アポ側)＝「自分が獲得したアポの成約率」は、アポインターの評価軸としては採用しない
（本人の行動よりクローザーの実力に左右されるため。参考値として列には残す）。

判定ロジック:
  1. 既存の ranking_core.aggregate() を 基準期間（デフォルト7月全体）と 直近週（比較期間）の
     2回呼び、人別のアポ獲得数・成約数（アポ側/クロ側）を得る。
  2. 基準期間を週平均に正規化（÷日数×7）して直近週と同じ単位で比較する。
  3. 「低下継続中」＝ 基準期間の週平均が--min-baseline-weekly以上（＝基準期間に実績があった人に
     限定）かつ 直近週がその--decline-ratio以下（デフォルト50%）。直近週に回復していれば対象外。
  4. 上記を役割に応じてアポ獲得数・クロ成約数のどちらか一方または両方に適用する。
  5. 「寺子屋対象者」は上記の低下継続中のうち、直近週(recent-start〜recent-end)に出勤・退勤・
     GPSルートのいずれかがあった人＝Cyzen上でまだ稼働している人に絞る（完全に離脱した人は
     3日連続打刻放置リストの管轄であり、寺子屋の対象ではないため）。

使い方:
  python3 build_declining_performers.py \
    --roster-csv <アポインター獲得履歴CSV・全期間> \
    --closing-csv <獲得報告データCSV> \
    --attendance-csv data/attendance_merged.csv \
    --clockout-csv data/clockout_merged.csv \
    --route-history-json data/route_history.json \
    --july-start 2026/07/01 --july-end 2026/07/31 \
    --recent-start 2026/08/03 --recent-end 2026/08/09 \
    --min-july-weekly-apo 1.0 --decline-ratio 0.5 \
    --out-decline data/declining_performers_202608.csv \
    --out-terakoya data/terakoya_targets_202608.csv
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ranking_core import aggregate  # noqa: E402
from company_resolver import canon_name, norm_name, CYZEN_MASTER  # noqa: E402


def _role_by_name():
    """Cyzenユーザーマスタの「メンバー属性」からアポインター/クローザー/どちらもを判定。
    {norm_name: 役割区分} を返す。"""
    roles = {}
    if not os.path.exists(CYZEN_MASTER):
        return roles
    with open(CYZEN_MASTER, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            name = row[idx["名前"]].strip()
            if not name:
                continue
            attrs = [a.strip() for a in row[idx["メンバー属性"]].split("\n") if a.strip()]
            has_apo = "アポインター" in attrs
            has_clo = "クローザー" in attrs
            if has_apo and has_clo:
                role = "どちらも"
            elif has_apo:
                role = "アポインター"
            elif has_clo:
                role = "クローザー"
            else:
                role = ""
            roles[norm_name(name)] = role
    return roles


def _month_days(start, end):
    from datetime import date
    y1, m1, d1 = (int(x) for x in start.split("/"))
    y2, m2, d2 = (int(x) for x in end.split("/"))
    return (date(y2, m2, d2) - date(y1, m1, d1)).days + 1


def _recent_active_names(attendance_csv, clockout_csv, route_history_json, recent_start, recent_end):
    """recent_start〜recent_end（YYYY-MM-DD）に出退勤・GPSのいずれかがあった人の集合。"""
    active = set()
    for path in (attendance_csv, clockout_csv):
        if not (path and os.path.exists(path)):
            continue
        with open(path, encoding="cp932", errors="replace") as f:
            for row in csv.DictReader(f):
                name = canon_name((row.get("ユーザー名") or "").strip())
                date = (row.get("日付") or "").strip()
                if name and recent_start <= date <= recent_end:
                    active.add(norm_name(name))
    if route_history_json and os.path.exists(route_history_json):
        with open(route_history_json, encoding="utf-8") as f:
            rh = json.load(f)
        for date, users in rh.items():
            if not (recent_start <= date <= recent_end):
                continue
            for uname, rec in users.items():
                if rec.get("route_count", 0) > 0:
                    active.add(norm_name(canon_name(uname)))
    return active


def build(roster_csv, closing_csv, attendance_csv, clockout_csv, route_history_json,
          july_start, july_end, recent_start, recent_end,
          min_july_weekly_apo, decline_ratio):
    baseline = aggregate(roster_csv, closing_csv, july_start, july_end)
    recent = aggregate(roster_csv, closing_csv, recent_start, recent_end)

    baseline_days = _month_days(july_start, july_end)
    recent_days = _month_days(recent_start, recent_end)

    def index_apo(agg):
        return {norm_name(r[1]): {"company": r[2], "apo_seiyaku": r[3], "apo_kakutoku": r[4]} for r in agg["apo_ranking"]}

    def index_clo(agg):
        return {norm_name(r[1]): {"company": r[2], "clo_seiyaku": r[3]} for r in agg["closer_ranking"]}

    baseline_apo = index_apo(baseline)
    recent_apo = index_apo(recent)
    baseline_clo = index_clo(baseline)
    recent_clo = index_clo(recent)

    recent_active = _recent_active_names(
        attendance_csv, clockout_csv, route_history_json,
        recent_start.replace("/", "-"), recent_end.replace("/", "-"))
    roles = _role_by_name()

    all_people = set(baseline_apo) | set(recent_apo) | set(baseline_clo) | set(recent_clo)

    rows = []
    for n in all_people:
        b_apo = baseline_apo.get(n, {})
        r_apo = recent_apo.get(n, {})
        b_clo = baseline_clo.get(n, {})
        r_clo = recent_clo.get(n, {})

        b_apo_kakutoku_wk = b_apo.get("apo_kakutoku", 0) / baseline_days * 7
        r_apo_kakutoku_wk = r_apo.get("apo_kakutoku", 0) / recent_days * 7
        b_apo_seiyaku_wk = b_apo.get("apo_seiyaku", 0) / baseline_days * 7
        r_apo_seiyaku_wk = r_apo.get("apo_seiyaku", 0) / recent_days * 7
        b_clo_seiyaku_wk = b_clo.get("clo_seiyaku", 0) / baseline_days * 7
        r_clo_seiyaku_wk = r_clo.get("clo_seiyaku", 0) / recent_days * 7

        role = roles.get(n, "")
        has_apo_data = n in baseline_apo or n in recent_apo
        has_clo_data = n in baseline_clo or n in recent_clo

        # 役割ごとに評価軸を決める。役割不明の場合は実データの有無でフォールバック。
        if role == "アポインター":
            apply_apo, apply_clo = True, False
        elif role == "クローザー":
            apply_apo, apply_clo = False, True
        elif role == "どちらも":
            apply_apo, apply_clo = True, True
        else:
            apply_apo, apply_clo = has_apo_data, has_clo_data

        decline_apo = apply_apo and b_apo_kakutoku_wk >= min_july_weekly_apo and r_apo_kakutoku_wk <= b_apo_kakutoku_wk * decline_ratio
        decline_clo = apply_clo and b_clo_seiyaku_wk >= min_july_weekly_apo and r_clo_seiyaku_wk <= b_clo_seiyaku_wk * decline_ratio

        if not (decline_apo or decline_clo):
            continue

        # 表示名は apo_ranking/closer_ranking の元データから拾う（インデックス構築時に落ちているので再取得）
        display_name = None
        for r in baseline["apo_ranking"] + recent["apo_ranking"]:
            if norm_name(r[1]) == n:
                display_name = r[1]
                break
        if not display_name:
            for r in baseline["closer_ranking"] + recent["closer_ranking"]:
                if norm_name(r[1]) == n:
                    display_name = r[1]
                    break
        company = r_apo.get("company") or b_apo.get("company") or r_clo.get("company") or b_clo.get("company") or "（不明）"

        reasons = []
        if decline_apo:
            reasons.append("アポ低下")
        if decline_clo:
            reasons.append("クロ成約低下")

        is_active = n in recent_active

        rows.append({
            "氏名": display_name or n,
            "所属会社": company,
            "役割区分": role or "(マスタ未確認)",
            "評価軸": "・".join([x for x in ["アポ獲得数" if apply_apo else "", "クロ成約数" if apply_clo else ""] if x]),
            "要因分類": "・".join(reasons),
            "アポ低下フラグ": decline_apo,
            "クロ成約低下フラグ": decline_clo,
            "基準週平均アポ獲得数": round(b_apo_kakutoku_wk, 1),
            "直近週アポ獲得数": r_apo.get("apo_kakutoku", 0),
            "基準週平均成約数(アポ側・参考)": round(b_apo_seiyaku_wk, 1),
            "直近週成約数(アポ側・参考)": r_apo.get("apo_seiyaku", 0),
            "基準週平均成約数(クロ側)": round(b_clo_seiyaku_wk, 1),
            "直近週成約数(クロ側)": r_clo.get("clo_seiyaku", 0),
            "直近週稼働(出退勤/GPS)": "○" if is_active else "×",
        })

    rows.sort(key=lambda r: (r["所属会社"], -r["基準週平均アポ獲得数"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv", required=True)
    ap.add_argument("--attendance-csv", required=True)
    ap.add_argument("--clockout-csv", required=True)
    ap.add_argument("--route-history-json", required=True)
    ap.add_argument("--july-start", required=True)
    ap.add_argument("--july-end", required=True)
    ap.add_argument("--recent-start", required=True)
    ap.add_argument("--recent-end", required=True)
    ap.add_argument("--min-july-weekly-apo", type=float, default=1.0)
    ap.add_argument("--decline-ratio", type=float, default=0.5)
    ap.add_argument("--out-decline", required=True)
    ap.add_argument("--out-terakoya", required=True)
    args = ap.parse_args()

    rows = build(args.roster_csv, args.closing_csv, args.attendance_csv, args.clockout_csv,
                 args.route_history_json, args.july_start, args.july_end,
                 args.recent_start, args.recent_end,
                 args.min_july_weekly_apo, args.decline_ratio)

    header = ["氏名", "所属会社", "役割区分", "評価軸", "要因分類",
              "基準週平均アポ獲得数", "直近週アポ獲得数",
              "基準週平均成約数(アポ側・参考)", "直近週成約数(アポ側・参考)",
              "基準週平均成約数(クロ側)", "直近週成約数(クロ側)", "直近週稼働(出退勤/GPS)"]

    def _write(path, out_rows):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
            w.writeheader()
            w.writerows(out_rows)

    _write(args.out_decline, rows)
    apo_n = sum(1 for r in rows if r["アポ低下フラグ"])
    clo_n = sum(1 for r in rows if r["クロ成約低下フラグ"])
    print(f"8月も続けて数値が落ちている人: {len(rows)}名（アポ低下{apo_n}名／クロ成約低下{clo_n}名） -> {args.out_decline}")

    terakoya_rows = [r for r in rows if r["直近週稼働(出退勤/GPS)"] == "○"]
    _write(args.out_terakoya, terakoya_rows)
    print(f"寺子屋対象者(稼働中に限定): {len(terakoya_rows)}名 -> {args.out_terakoya}")


if __name__ == "__main__":
    main()
