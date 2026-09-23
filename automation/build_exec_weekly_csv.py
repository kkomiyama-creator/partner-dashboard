# -*- coding: utf-8 -*-
"""役員（辻さん）向け週次実績CSV一式を生成する（2026-08-10追加・2026-08-10改訂）。
辻さんへの過去送付ファイル（Slack #経営会議 2026-08-03、7/1~7/31,8/1~8/2実績CSV.zip）と
完全に同じファイル構成・列名で、6ファイルを出力する:
  企業別実績_<start>_<end>.csv       会社名,アポ獲得数,アポ成約数,クロ成約数,売上(円),成約率(%)
  アポインター別実績_<start>_<end>.csv  順位,氏名,所属会社,アポ成約数,アポ獲得数
  クローザー別実績_<start>_<end>.csv   順位,氏名,所属会社,クロ成約数,売上(円)
  稼働人員数_3指標_<start>_<end>.csv   会社名,マスタ登録人数,出勤打刻あり,スポット作成あり,ルート自動記録あり
  稼働人員数_会社別_<start>_<end>.csv  会社名,マスタ登録人数,稼働人員数(出勤打刻あり),稼働率(%)
  未稼働者一覧_<start>_<end>.csv      氏名,所属会社（マスタ登録済みだが期間内に出勤打刻が一度も無い人）
完工数は含めない（辻さんが別ルートで取得するため）。

使い方:
  python3 build_exec_weekly_csv.py \
    --roster-csv <アポインター獲得履歴CSV> \
    --closing-csv <獲得報告データCSV> \
    --attendance-csv data/attendance_merged.csv \
    --spot-csv data/spot_merged.csv \
    --route-history-json data/route_history.json \
    --start 2026-08-03 --end 2026-08-09 \
    --outdir <出力先ディレクトリ>
"""
import argparse
import csv
import json
import os
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ranking_core import aggregate  # noqa: E402
from company_resolver import canon_name, resolve_company, MASTER, canon  # noqa: E402


def _names_by_company_from_csv(csv_path, start, end, name_col_candidates, date_col_candidates):
    """出勤報告/勤務終了報告/スポット台帳CSVから、期間内(start<=date<=end, YYYY-MM-DD)に
    活動記録がある氏名(canon_name済み)の集合を返す。"""
    names = set()
    with open(csv_path, encoding="cp932", errors="replace") as f:
        r = csv.DictReader(f)
        for row in r:
            name = ""
            for c in name_col_candidates:
                if row.get(c):
                    name = row[c].strip()
                    break
            date = ""
            for c in date_col_candidates:
                if row.get(c):
                    date = row[c].strip()[:10]
                    break
            if not name or not date:
                continue
            if start <= date <= end:
                names.add(canon_name(name))
    return names


def _route_names(route_history_json, start, end):
    names = set()
    if not route_history_json or not os.path.exists(route_history_json):
        return names
    with open(route_history_json, encoding="utf-8") as f:
        data = json.load(f)
    for date, users in data.items():
        if not (start <= date <= end):
            continue
        for name, rec in users.items():
            if rec.get("route_count", 0) > 0:
                names.add(canon_name(name))
    return names


def master_by_company():
    """{会社名: [表示名, ...]} を返す。2026-08-24: company_resolver.master_by_company()
    （Cyzen連携API直接取得・有効アカウントのみ）に委譲するよう変更。以前はここでCYZEN_MASTER
    ファイルを直接読んでいたため、company_resolver.MASTERをAPI化した後もこちらだけ古いデータを
    見続けてしまい、稼働人員数・未稼働者一覧の「マスタ登録人数」が新規登録者を反映しない不整合が
    起きていた（小宮山さんからの指摘で発覚）。"""
    from company_resolver import master_by_company as _mbc
    return _mbc()


def build(roster_csv, closing_csv, start, end, attendance_csv, spot_csv, route_history_json):
    data = aggregate(roster_csv, closing_csv, start.replace("-", "/"), end.replace("-", "/"))

    attendance_names = _names_by_company_from_csv(
        attendance_csv, start, end, ["ユーザー名"], ["日付"]) if attendance_csv else set()
    spot_names = _names_by_company_from_csv(
        spot_csv, start, end, ["作成者"], ["作成日"]) if spot_csv else set()
    route_names = _route_names(route_history_json, start, end)

    master = master_by_company()
    master_count = {co: len(names) for co, names in master.items()}
    all_master_names = {n for names in master.values() for n in names}

    # ---- ①企業別実績 ----
    company_rows = []
    for c in data["companies"]:
        company_rows.append([c["company"], c["apo_kakutoku"], c["apo_seiyaku"], c["clo_seiyaku"],
                              c["uriage"], c["rate"] if c["rate"] is not None else ""])

    # ---- ②アポインター別実績 ----
    apo_rows = [[r[0], r[1], r[2], r[3], r[4]] for r in data["apo_ranking"]]

    # ---- ③クローザー別実績 ----
    clo_rows = [[r[0], r[1], r[2], r[3], r[4]] for r in data["closer_ranking"]]

    # ---- ④稼働人員数_3指標／⑤稼働人員数_会社別 ----
    companies_all = sorted(master_count.keys(), key=lambda co: -master_count[co])
    hc3_rows = []
    hc_rows = []
    for co in companies_all:
        mc = master_count[co]
        att = len({n for n in master[co] if n in attendance_names})
        spot = len({n for n in master[co] if n in spot_names})
        route = len({n for n in master[co] if n in route_names})
        hc3_rows.append([co, mc, att, spot, route])
        rate = round(att / mc * 100, 1) if mc else ""
        hc_rows.append([co, mc, att, rate])

    # ---- ⑥未稼働者一覧（マスタ登録済みだが期間内に出勤打刻が一度も無い人） ----
    unworked_rows = []
    for co in companies_all:
        for n in sorted(master[co]):
            if n not in attendance_names:
                unworked_rows.append([n, co])

    return {
        "company": company_rows,
        "apo": apo_rows,
        "closer": clo_rows,
        "hc3": hc3_rows,
        "hc": hc_rows,
        "unworked": unworked_rows,
    }


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv", required=True)
    ap.add_argument("--attendance-csv", required=True)
    ap.add_argument("--spot-csv", required=True)
    ap.add_argument("--route-history-json", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--zip-name", default=None)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    result = build(args.roster_csv, args.closing_csv, args.start, args.end,
                    args.attendance_csv, args.spot_csv, args.route_history_json)

    suffix = f"{args.start}_{args.end}"
    files = {
        f"企業別実績_{suffix}.csv": (["会社名", "アポ獲得数", "アポ成約数", "クロ成約数", "売上(円)", "成約率(%)"], result["company"]),
        f"アポインター別実績_{suffix}.csv": (["順位", "氏名", "所属会社", "アポ成約数", "アポ獲得数"], result["apo"]),
        f"クローザー別実績_{suffix}.csv": (["順位", "氏名", "所属会社", "クロ成約数", "売上(円)"], result["closer"]),
        f"稼働人員数_3指標_{suffix}.csv": (["会社名", "マスタ登録人数", "出勤打刻あり", "スポット作成あり", "ルート自動記録あり"], result["hc3"]),
        f"稼働人員数_会社別_{suffix}.csv": (["会社名", "マスタ登録人数", "稼働人員数(出勤打刻あり)", "稼働率(%)"], result["hc"]),
        f"未稼働者一覧_{suffix}.csv": (["氏名", "所属会社"], result["unworked"]),
    }
    paths = []
    for fname, (header, rows) in files.items():
        path = os.path.join(args.outdir, fname)
        _write_csv(path, header, rows)
        paths.append(path)
        print(f"wrote {len(rows)} rows -> {path}")

    zip_name = args.zip_name or f"{suffix}実績CSV.zip"
    zip_path = os.path.join(args.outdir, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, arcname=os.path.basename(p))
    print(f"zipped -> {zip_path}")


if __name__ == "__main__":
    main()
