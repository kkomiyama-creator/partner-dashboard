# -*- coding: utf-8 -*-
"""Cyzen連携APIの /spots からスポット台帳を取得し、既存の spot_merged.csv と
同じ列構成のCSVを生成する（2026-08-18・要件定義フェーズ4）。

これまでspot-list-v2画面のブラウザ操作（月単位の絞り込み→ファイル出力→出力履歴から
ダウンロード、出力上限エラーとの戦い）でCSV取得していた部分をAPI直接取得に置き換える。

【実測事実】/reportsと同じく、期間指定パラメータは updated_from/updated_to
（更新日時ベース）。ページングは next_spot_id の単純カーソル方式（/reportsのような
複合カーソルではない）でcyzen_api_client.get_all()がそのまま使える。

エリア列（東北エリア等）は spot_tags[] から group_id→エリア名を解決し、
そのエリア列にspot_tag_nameを入れる（1スポットは通常1タグのみ持つ想定）。

使い方:
  python3 build_spots_api.py --start 2026-08-01 --end 2026-08-18 \
      --out ../data/spot_merged.csv
"""
import argparse
import datetime
import os
import sys
import csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cyzen_api_client import CyzenAPIClient, build_role_map  # noqa: E402

CHUNK_DAYS = 7

AREA_COLS = ['東北エリア', '関東エリア', '東海エリア', '関西エリア', '中国エリア', '四国エリア', '九州エリア',
             'cyzenユーザー説明会', '予定管理用', 'Fit Founder', '用地開発', '北海道エリア']
HEADER = (['スポットコード更新キー', 'スポットコード', 'スポット名称', 'スポット名称（カナ）', '郵便番号', '所在地',
           '電話番号', 'FAX', 'Webサイト', 'コメント', '更新日', '有効開始日', '有効終了日', '作成日', '作成者']
          + AREA_COLS)


def _daterange_chunks(start, end, days=CHUNK_DAYS):
    d1 = datetime.date.fromisoformat(start)
    d2 = datetime.date.fromisoformat(end)
    while d1 <= d2:
        d3 = min(d1 + datetime.timedelta(days=days - 1), d2)
        yield d1.isoformat(), d3.isoformat()
        d1 = d3 + datetime.timedelta(days=1)


def fetch_spots(client, start, end):
    out = []
    for d1, d2 in _daterange_chunks(start, end):
        chunk = client.get_all("spots", key="spots",
                                updated_from=f"{d1}T00:00:00", updated_to=f"{d2}T23:59:59")
        out.extend(chunk)
    return out


def _jst(iso_str):
    if not iso_str:
        return ""
    try:
        utc = datetime.datetime.fromisoformat(iso_str)
        return (utc + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso_str


def build(start, end):
    client = CyzenAPIClient()
    role_map, _, _ = build_role_map(client)
    groups = client.get_all("groups", key="groups")
    group_name = {g["group_id"]: g["group_name"] for g in groups}

    spots = fetch_spots(client, start, end)

    seen = set()
    rows = []
    for s in spots:
        sid = s.get("spot_id")
        if sid in seen:
            continue
        seen.add(sid)

        creator = role_map.get(s.get("create_user_id"), {})
        area_values = {c: "" for c in AREA_COLS}
        for tag in (s.get("spot_tags") or []):
            gname = group_name.get(tag.get("group_id"))
            if gname in area_values:
                area_values[gname] = tag.get("spot_tag_name", "")

        row = [
            "spot" + sid, s.get("spot_code", ""), s.get("spot_name", ""), s.get("spot_name_kana", ""),
            s.get("zip_code", ""), s.get("address", ""), s.get("tel", ""), s.get("fax", ""),
            s.get("url", ""), s.get("comment", ""),
            _jst(s.get("updated_at")), s.get("valid_from", ""), s.get("valid_to", ""),
            _jst(s.get("created_at")), creator.get("name", ""),
        ] + [area_values[c] for c in AREA_COLS]
        rows.append(row)

    return rows, client.request_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows, req_count = build(args.start, args.end)
    with open(args.out, "w", encoding="cp932", errors="replace", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)

    print(f"スポット {len(rows)}件 -> {args.out}")
    print(f"APIリクエスト数: {req_count}")


if __name__ == "__main__":
    main()
