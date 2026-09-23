# -*- coding: utf-8 -*-
"""Cyzen連携APIの /reports から「アポ獲得報告」（report_definition_id=
3823e34f92343221313c33a08c9dbed6）の記載内容を取得し、傾向分析タブ用の
軽量レコード（1件1行）として data/apo_report_records.json に永続マージする
（2026-09-16追加）。

出勤報告等と違い列固定のCSVではなく構造化フォームの report_items を都度パースする必要があるため、
既存の attendance_merged.csv 方式ではなくJSON配列で持つ。マージ方式は同じ
（--start以降の既存レコードを削除してから新規取得分を追加＝完全上書き、日付境界の重複は発生しない）。

使い方:
  python3 build_apo_report_content_api.py --start 2026-09-07 --end 2026-09-15 \
      --out ../data/apo_report_records.json
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cyzen_api_client import CyzenAPIClient  # noqa: E402

DEF_ID = "3823e34f92343221313c33a08c9dbed6"
CHUNK_DAYS = 7


def _daterange_chunks(start, end, days=CHUNK_DAYS):
    d1 = datetime.date.fromisoformat(start)
    d2 = datetime.date.fromisoformat(end)
    while d1 <= d2:
        d3 = min(d1 + datetime.timedelta(days=days - 1), d2)
        yield d1.isoformat(), d3.isoformat()
        d1 = d3 + datetime.timedelta(days=1)


def fetch_reports_page(client, from_date, to_date):
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


def _items(r):
    return {it.get("item_name"): it.get("item_value") for it in (r.get("report_items") or [])}


def _age(v):
    try:
        a = int(v)
        return a if 10 <= a <= 100 else None
    except (TypeError, ValueError):
        return None


def _hour(hhmm):
    if not hhmm:
        return None
    try:
        return int(str(hhmm).split(":")[0])
    except (TypeError, ValueError, IndexError):
        return None


def build_records(start, end):
    client = CyzenAPIClient()
    reports = fetch_reports(client, start, end)
    seen = set()
    records = []
    for r in reports:
        rid = r.get("report_id")
        if rid in seen or r.get("report_definition_id") != DEF_ID:
            continue
        seen.add(rid)
        it = _items(r)
        created = r.get("created_at") or ""
        try:
            utc = datetime.datetime.fromisoformat(created)
            jst = utc + datetime.timedelta(hours=9)
            date = jst.date().isoformat()
        except ValueError:
            continue

        aite = it.get("会話相手")
        maker = it.get("名乗りメーカー")
        records.append({
            "report_id": rid,
            "date": date,
            "hour": _hour(it.get("訪問時の対面時刻")),
            "aite": aite[0] if isinstance(aite, list) and aite else None,
            "kazoku": (it.get("家族構成") or "").strip() or None,
            "all_electric": it.get("オール電化かどうか") or None,
            "denkidai": it.get("月の電気代（目安・聞き取り）") or None,
            "maker": maker[0] if isinstance(maker, list) and maker else None,
            "age": _age(it.get("対面者の年齢")),
        })
    return records, client.request_count


def merge(out_path, start, new_records):
    existing = []
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)
    kept = [r for r in existing if r["date"] < start]
    merged = kept + new_records
    merged.sort(key=lambda r: r["date"])
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    return len(existing), len(kept), len(merged)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    records, req_count = build_records(args.start, args.end)
    n_existing, n_kept, n_merged = merge(args.out, args.start, records)
    print(f"アポ獲得報告 {len(records)}件取得 -> {args.out}")
    print(f"既存{n_existing}件のうち{args.start}未満{n_kept}件を保持 + 新規{len(records)}件 = 計{n_merged}件")
    print(f"APIリクエスト数: {req_count}")


if __name__ == "__main__":
    main()
