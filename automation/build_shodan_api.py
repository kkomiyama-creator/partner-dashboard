# -*- coding: utf-8 -*-
"""Cyzen連携APIの /schedules から商談パイプラインデータを生成する（2026-08-17）。

これまで `data/cyzen_shodan.json` はChromeで予定一覧をスクレイプして作っていたが、
(1) 仮想スクロールによる重複計上 (2) クローザー名に「予定作成者」を入れていたため
実際にはアポインターを表示していた、という2つの問題があった。
本スクリプトはAPIから正確に取得し、クローザーを実データで確定させて置き換える。

【クローザー確定の優先順位】（2026-08-17に実データ338件で検証済み）
  1. その予定に紐づく「クローザー：〜」報告書の提出者   … 一次情報。最優先
  2. 参加者のうち役割タグにクローザーを持つ人が1名だけ … 一意に決まる
     （参加者が本人1名だけの自アポ自クローズもここに含まれる）
  3. いずれでも決まらない                              … 不明（"#不明"として集計から除外）

検証結果: 報告閲覧CSV（正解データ）と突合し、25名全員でAPI件数<=CSV件数・超過ゼロ。
          帰属できたのは全商談の約87%。残りは報告書ゼロ＝成果未発生のため実績値に影響しない。

出力は既存の `data/cyzen_shodan.json` と同じ形状なので、build_data.py は変更不要。

使い方:
  python3 build_shodan_api.py --start 2026-07-01 --end 2026-08-16 \
      --out ../../../data/cyzen_shodan.json
"""
import argparse
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cyzen_api_client import (  # noqa: E402
    CyzenAPIClient, CyzenAPIError, build_role_map, ROLE_CLOSER,
)

# 商談として数える予定カテゴリ（休み・キャンセル・その他は除外）
SHODAN_CATS = {"仮予定", "後確後（事務確認OK）", "確定"}
CHUNK_DAYS = 7  # /schedules は from-to が7日以内でないと 40000 エラー


def _daterange_chunks(start, end, days=CHUNK_DAYS):
    d1 = datetime.date.fromisoformat(start)
    d2 = datetime.date.fromisoformat(end)
    while d1 <= d2:
        d3 = min(d1 + datetime.timedelta(days=days - 1), d2)
        yield d1.isoformat(), d3.isoformat()
        d1 = d3 + datetime.timedelta(days=1)


def fetch_schedules(client, start, end):
    """期間内の予定を取得。チャンクが500で落ちた場合は日単位に切り替え、
    それでも落ちる日はスキップして記録する（Cyzen側のデータ起因の既知不具合）。"""
    out, skipped = [], []
    for d1, d2 in _daterange_chunks(start, end):
        try:
            data = client.get("schedules", from_date=f"{d1}T00:00:00",
                              to_date=f"{d2}T23:59:59", with_actual=1)
            out.extend(data.get("schedules") or [])
            continue
        except CyzenAPIError as e:
            if "500" not in str(e):
                raise
            print(f"  ! {d1}〜{d2} が500エラー。日単位で再取得します。", file=sys.stderr)

        d = datetime.date.fromisoformat(d1)
        last = datetime.date.fromisoformat(d2)
        while d <= last:
            ds = d.isoformat()
            try:
                data = client.get("schedules", from_date=f"{ds}T00:00:00",
                                  to_date=f"{ds}T23:59:59", with_actual=1)
                out.extend(data.get("schedules") or [])
            except CyzenAPIError as e:
                if "500" not in str(e):
                    raise
                skipped.append(ds)
                print(f"  ! {ds} は単日でも500エラー。スキップします。", file=sys.stderr)
            d += datetime.timedelta(days=1)
    return out, skipped


def resolve_closer(sched, role_map):
    """(クローザー名 or None, 判定方法) を返す。"""
    uids = [u.get("user_id") for u in (sched.get("users") or [])]
    cands = [u for u in uids if u in role_map and ROLE_CLOSER in role_map[u]["roles"]]

    reps = [r for r in ((sched.get("schedule_actual") or {}).get("schedule_reports") or [])
            if "クローザー" in (r.get("report_definition_name") or "")]
    reporters = {r.get("user_id") for r in reps}
    hit = [u for u in cands if u in reporters]

    if len(set(hit)) == 1:
        return role_map[hit[0]]["name"], "報告書"
    if len(cands) == 1:
        # 参加者が本人1名だけ（兼務者の自アポ自クローズ）もここに含まれる
        return role_map[cands[0]]["name"], "役割タグ"
    return None, "不明"


def build(start, end, today=None):
    today = today or datetime.date.today().isoformat()
    client = CyzenAPIClient()
    role_map, _, _ = build_role_map(client)
    scheds, skipped = fetch_schedules(client, start, end)

    seen = set()
    deals = []
    how_counter = collections.Counter()
    gap_reported = gap_missing = 0
    for s in scheds:
        sid = s.get("schedule_id")
        if sid in seen:          # チャンク境界での重複を除去
            continue
        seen.add(sid)

        cat = (s.get("schedule_category") or {}).get("schedule_category_name")
        if cat not in SHODAN_CATS:
            continue
        raw = (s.get("start_date") or "")
        if not raw:
            continue
        utc = datetime.datetime.fromisoformat(raw)
        jst = utc + datetime.timedelta(hours=9)
        jst_date = jst.date().isoformat()
        if not (start <= jst_date <= end):
            continue

        closer, how = resolve_closer(s, role_map)
        how_counter[how] += 1
        has_report = bool((s.get("schedule_actual") or {}).get("schedule_reports"))
        if cat == "確定" and jst_date < today:
            if has_report:
                gap_reported += 1
            else:
                gap_missing += 1
        deals.append({
            "m": jst.strftime("%Y-%m"),
            "c": cat,
            "t": (s.get("title") or "").strip(),
            "s": int(utc.replace(tzinfo=datetime.timezone.utc).timestamp()),
            "u": "",
            "n": closer if closer else "#不明",
            "sid": sid,
            "how": how,
        })

    named = {d["n"] for d in deals if not d["n"].startswith("#")}
    totals = collections.Counter(d["c"] for d in deals)
    gap_bunbo = gap_reported + gap_missing
    return {
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "Cyzen連携API /schedules（2026-08-17よりスクレイプから移行）",
        "period": {"start": start, "end": end},
        "mappedNames": len(named),
        "id2name": {},
        "totals": dict(totals),
        "attribution": dict(how_counter),
        "skipped_dates": skipped,
        "deals": deals,
        "report_gap": {
            "today": today,
            "kakutei_reported": gap_reported,
            "kakutei_missing": gap_missing,
            "kakutei_missing_rate": round(gap_missing / gap_bunbo * 100, 1) if gap_bunbo else None,
            "note": "「確定」カテゴリの過去日予定のみが対象（仮予定・後確後は実施前の可能性が高いため除外）",
        },
        "note": (
            "クローザーは「予定に紐づくクローザー報告書の提出者」を最優先に確定し、"
            "無い場合は参加者の役割タグ（クローザー候補が1名のときのみ）で補完している。"
            "旧版はスクレイプした予定一覧の『作成者』列をクローザーとしていたが、"
            "作成者は業務ルール上アポインターであり誤りだったため本版で是正した。"
            "確定できなかった予定は #不明 として担当者別集計から除外している。"
        ),
        "api_request_count": client.request_count,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    res = build(args.start, args.end)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    total = len(res["deals"])
    print(f"商談 {total}件 / クローザー確定 {res['mappedNames']}名 -> {args.out}")
    print("■ カテゴリ別"),
    for k, v in sorted(res["totals"].items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}件")
    print("■ クローザー確定方法")
    for k, v in sorted(res["attribution"].items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}件 ({v/max(total,1)*100:.1f}%)")
    if res["skipped_dates"]:
        print(f"■ 取得できなかった日（Cyzen側500エラー）: {res['skipped_dates']}")
    print(f"■ APIリクエスト数: {res['api_request_count']}")


if __name__ == "__main__":
    main()
