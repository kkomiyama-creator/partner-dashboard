# -*- coding: utf-8 -*-
"""法人開拓・折衝ログ（Googleフォーム回答蓄積）を集計し、開拓先パートナータブに埋め込む
JSONを生成する（2026-09-01追加）。

対象は辻さんチームが日々入力している「法人開拓 折衝ログ」フォーム
（スプレッドシートID: 1uYH7E8vNqcJrMmZyULd6c7ox5IVZFlVlIhZufj5ITz4）。
列名の通り「法人名（新規接触法人）」＝まだCyzenで稼働していない新規開拓先が対象で、
既存の企業別タブに出てくる稼働中パートナーとは別の母集団（[[houjin-kaitaku-form-crm-integration]]
参照）。既存の「開拓先パートナー」タブ（SNS経由のNotion CRM候補者リスト）の"次のステージ"
＝実際に接触が始まった後の折衝ログとして、同タブ内に追加する。

名寄せは company_resolver.py の COMPANY_CANON と同じ「静的マッピングファイル参照」方式
（--alias-json）。5分おきCIの中でリアルタイムLLM判定はしない。新規の法人名はそのまま
（別表記の統一が必要になった時点で人手＝Claudeがalias-jsonに追記する運用、
build_partner_map.pyの人手レビューと同じ思想）。

使い方:
  python3 build_houjin_crm.py --csv data/houjin_crm_live.csv \
      --exclude-json data/houjin_crm_exclude.json --alias-json data/houjin_company_alias.json \
      --today 2026-09-01 --out data/houjin_crm.json
"""
import argparse
import csv
import datetime
import json
import os


COLUMNS = [
    "timestamp", "company_raw", "contact_date", "inflow_channel", "referrer",
    "area", "channel_business", "category", "contact_kind", "deal_status",
    "content", "next_action", "due_date", "contact_person", "proposal", "note", "link",
    "email", "resolved",
]


def parse_date(s):
    """フォームのタイムスタンプ/日付セルは"8/31/2026"や"8/31/2026 20:28:42"のような
    米国式M/D/YYYY表記でシートに保存されている(Googleフォームのデフォルトロケール由来)。
    どちらの形でも日付部分だけを取り出す。"""
    s = (s or "").strip()
    if not s:
        return None
    date_part = s.split(" ")[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(date_part, fmt).date()
        except ValueError:
            continue
    return None


def load_rows(csv_path):
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    out = []
    # row_numberは実際のスプレッドシート上の行番号(1始まり・ヘッダー=1行目)。
    # gsheets_client_ci.pyがシートの値をそのままCSVへ書き出しており、行の並び替え・
    # 欠落が無いため、CSVのインデックスから直接計算できる。ダッシュボード上の「対応済」
    # チェック操作(Apps ScriptのdoPost)で、どの行を更新するか特定する一意な識別子として使う
    # （タイムスタンプの文字列/日付表現をPython側とApps Script側で突き合わせるより、
    # 行番号を直接渡す方が書式・タイムゾーンの差異による不一致のリスクが無く確実）。
    for idx, r in enumerate(rows[1:], start=2):
        if not any((v or "").strip() for v in r):
            continue
        r = r + [""] * (len(COLUMNS) - len(r))
        rec = dict(zip(COLUMNS, r))
        rec["row_number"] = idx
        out.append(rec)
    return out


def canon_company(raw, alias_map):
    n = (raw or "").strip()
    return alias_map.get(n, n)


def build(csv_path, exclude_json, alias_json, today, out_path):
    exclude_names = set()
    if exclude_json and os.path.exists(exclude_json):
        with open(exclude_json, encoding="utf-8") as f:
            exclude_names = {n.strip() for n in json.load(f).get("exclude_names", [])}

    alias_map = {}
    if alias_json and os.path.exists(alias_json):
        with open(alias_json, encoding="utf-8") as f:
            alias_map = json.load(f)

    records = load_rows(csv_path) if csv_path and os.path.exists(csv_path) else []

    by_company = {}
    for rec in records:
        raw_name = (rec["company_raw"] or "").strip()
        if not raw_name or raw_name in exclude_names:
            continue
        company = canon_company(raw_name, alias_map)
        contact_dt = parse_date(rec["contact_date"]) or parse_date(rec["timestamp"])
        due_dt = parse_date(rec["due_date"])
        resolved = (rec.get("resolved") or "").strip().upper() == "TRUE"
        entry = {
            "timestamp": rec["timestamp"],
            # row_numberが行の一意識別子。ダッシュボード上の「対応済」チェック操作
            # （Apps ScriptのdoPost）で、どの行を更新するか特定するのに使う。
            "row_number": rec["row_number"],
            "contact_date": contact_dt.isoformat() if contact_dt else None,
            "category": rec["category"],
            "contact_kind": rec["contact_kind"],
            "deal_status": rec["deal_status"],
            "content": rec["content"],
            "next_action": rec["next_action"],
            "due_date": due_dt.isoformat() if due_dt else None,
            "contact_person": rec["contact_person"],
            "inflow_channel": rec["inflow_channel"],
            "referrer": rec["referrer"],
            "area": rec["area"],
            "channel_business": rec["channel_business"],
            "proposal": rec["proposal"],
            "note": rec["note"],
            "link": rec["link"],
            "email": rec.get("email"),
            "resolved": resolved,
            "_sort_key": (contact_dt or datetime.date.min, rec["timestamp"]),
        }
        by_company.setdefault(company, []).append(entry)

    companies = []
    for company, entries in by_company.items():
        entries.sort(key=lambda e: e["_sort_key"], reverse=True)
        latest = entries[0]
        due_dt = datetime.date.fromisoformat(latest["due_date"]) if latest["due_date"] else None
        # 「対応済」チェックが入っている行は、期限が過去でも超過扱いにしない
        # （2026-09-01追加：スプレッドシートに対応済列ができたことで、以前は
        # 「対応完了かどうか分からない」という限界があったが、これで判定できるようになった）。
        is_overdue = bool(due_dt and due_dt < today and not latest["resolved"])
        is_due_soon = bool(due_dt and today <= due_dt <= today + datetime.timedelta(days=3) and not latest["resolved"])
        for e in entries:
            e.pop("_sort_key", None)
        companies.append({
            "company": company,
            "contact_count": len(entries),
            "latest_contact_date": latest["contact_date"],
            "category": latest["category"],
            "contact_kind": latest["contact_kind"],
            "deal_status": latest["deal_status"],
            "next_action": latest["next_action"],
            "due_date": latest["due_date"],
            "is_overdue": is_overdue,
            "is_due_soon": is_due_soon,
            "contact_person": latest["contact_person"],
            "area": latest["area"],
            "channel_business": latest["channel_business"],
            "resolved": latest["resolved"],
            "timestamp": latest["timestamp"],
            "row_number": latest["row_number"],
            "email": latest["email"],
            "history": entries,
        })

    def sort_key(c):
        # 期限超過→期限が近い順→期限未設定、の順（該当なしは最後）
        if c["is_overdue"]:
            return (0, c["due_date"] or "")
        if c["due_date"]:
            return (1, c["due_date"])
        return (2, "")

    companies.sort(key=sort_key)

    summary = {
        "total_companies": len(companies),
        "overdue_count": sum(1 for c in companies if c["is_overdue"]),
        "due_soon_count": sum(1 for c in companies if c["is_due_soon"]),
        "no_next_action_count": sum(1 for c in companies if not c["next_action"] and not c["due_date"]),
        "total_contacts": sum(c["contact_count"] for c in companies),
    }

    out = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "as_of": today.isoformat(),
        "summary": summary,
        "companies": companies,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{summary['total_companies']}社（延べ{summary['total_contacts']}件・期限超過{summary['overdue_count']}社）"
          f" -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="法人開拓・折衝ログのCSV（gsheets_client_ci.fetch_allのhoujin_crm）")
    ap.add_argument("--exclude-json", default=None)
    ap.add_argument("--alias-json", default=None)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD。省略時は実行日")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    build(args.csv, args.exclude_json, args.alias_json, today, args.out)


if __name__ == "__main__":
    main()
