#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cyzen出退勤スプレッドシート（リアルタイム「本日の状況」テーブル）の生テキストから、
会社別「本日の実働者数」を計算する。

小宮山さん指定の出退勤スプレッドシート:
  https://docs.google.com/spreadsheets/d/1ZiSTHOQiAFGk_eN1q6UADB652IHu1EbTHH6sioYFhJ4/edit
（このスクリプト自体はGoogle Sheetsへ直接アクセスしない。呼び出し側が
  mcp__adc266a1...__read_file_content等で取得した生テキストをファイルに保存し、
  そのパスを本スクリプトに渡す想定）

「本日の状況」テーブルは以下の形式（Markdown表・日付列なし）:
  | 氏名 | ユーザーコード | 状態 | 出勤時刻 | 退勤時刻 |
  | 長谷川拓耶 | 00-0106 | 稼働中 | 08:21:21 |  |
  ...
このテーブルの直後に「日付」列付きの履歴テーブルが続くので、そこで読み込みを止める。

会社の判定は、氏名を kintone スタッフマスタ（data/staff_master_*.csv）の
「氏名」列と突き合わせて「会社名」列を引く（出退勤シート自体には会社名列が無いため）。
氏名が完全一致しない場合はカウントしない（表記ゆれの可能性はログに出す）。

使い方:
  python3 build_today_attendance.py path/to/raw_dump.txt > data/today_attendance.json
"""
import csv
import glob
import json
import re
import sys

STAFF_MASTER_GLOB = "/Users/fitfounderkomiyamakyousuke/Documents/claude-cyzen-ppt/data/staff_master_*.csv"
SELF_COMPANY_NAMES = {"小宮山 京介", "小宮山京介"}


def load_name_to_company():
    files = sorted(glob.glob(STAFF_MASTER_GLOB))
    if not files:
        sys.exit("kintoneスタッフマスタ(data/staff_master_*.csv)が見つかりません")
    with open(files[-1], encoding="cp932") as f:
        rows = list(csv.DictReader(f))
    return {r["氏名"].strip(): r["会社名"].strip() for r in rows if r.get("氏名")}


def parse_today_table(text):
    """「本日の状況」テーブル（日付列が無い方）の行だけを取り出す。"""
    lines = text.splitlines()
    rows = []
    started = False
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[:1] == ["氏名"] and "日付" not in cells:
            started = True
            continue
        if not started:
            continue
        if cells[:1] == ["日付"]:
            # 履歴テーブルのヘッダーに到達したら終了
            break
        if len(cells) < 3:
            continue
        if cells[0] in ("氏名",):
            continue
        name = cells[0]
        if not name:
            continue
        rows.append(name)
    return rows


def main():
    if len(sys.argv) != 2:
        sys.exit("使い方: python3 build_today_attendance.py path/to/raw_dump.txt")
    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()

    names = parse_today_table(text)
    name_to_company = load_name_to_company()

    counts = {}
    unmatched = []
    for name in names:
        if name in SELF_COMPANY_NAMES:
            continue
        co = name_to_company.get(name)
        if not co:
            unmatched.append(name)
            continue
        counts[co] = counts.get(co, 0) + 1

    out = {"counts": counts, "unmatched_names": unmatched, "total_people": len(names)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if unmatched:
        print(f"[警告] 会社が特定できなかった氏名: {unmatched}", file=sys.stderr)


if __name__ == "__main__":
    main()
