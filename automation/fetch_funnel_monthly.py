# -*- coding: utf-8 -*-
"""hamakomi数値まとめGoogleシートの「ファネルまとめ」タブから月次アポ数→商談数→成約数→完工数を
取得し、data/funnel_monthly.json を再生成する（2026-09-15追加）。

ダッシュボードの「辻さん向け週次」タブがこのJSONを読む。build_dashboard.py自体はSheets APIを
直接叩かず静的JSONだけを読む設計を保つため、この取得ステップは日次更新フローの中で
build_dashboard.py実行前に単独で走らせる（fetch_sheets_live.pyと同じ位置づけ）。

使い方:
  python3 fetch_funnel_monthly.py --out ../data/funnel_monthly.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gsheets_client import fetch_sheet_rows  # noqa: E402

SPREADSHEET_ID = "18fKNw_5CSozkqIawlBWcGI-HwYtKU5NO8VlYqDptI3s"
GID_FUNNEL = "1506560494"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = fetch_sheet_rows(SPREADSHEET_ID, GID_FUNNEL)
    months = []
    note = ""
    in_table = False
    for row in rows:
        cells = row + [""] * (10 - len(row))
        if cells[1] == "年月":
            in_table = True
            continue
        if not in_table:
            continue
        label = cells[1].strip()
        if not label:
            continue
        if label.startswith("注記"):
            note = cells[1].strip()
            break
        try:
            months.append({
                "label": label,
                "apo": int(cells[2]),
                "shodan": int(cells[3]),
                "seiyaku": int(cells[4]),
                "kanko": int(cells[5]),
            })
        except ValueError:
            continue

    out = {"updated_at": None, "months": months, "note": note}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"取得: {len(months)}ヶ月分 -> {args.out}")


if __name__ == "__main__":
    main()
