# -*- coding: utf-8 -*-
"""Cyzen連携APIの/usersからアカウント作成日を取得し、在籍期間(新人/中堅/ベテラン)の
判定用JSONを生成する(2026-08-31追加)。

2026/8/31の辻さん×小宮山さんの打ち合わせで「新人(3ヶ月以内)と中堅・ベテランを区別し、
成長ポテンシャルを検知したい」との要望があった。Cyzenの/usersにはcreated_at(アカウント
作成日時)はあるが、「クローザー昇格日」に相当するフィールドは無いため、今回は
「Cyzenアカウント登録日」だけを在籍期間の基準にする(昇格日は将来的な別途検討事項。
実装するなら、そのユーザーの最初のクローザー系報告書(獲得/敗戦/提案中)提出日を
代理指標にする案が考えられる)。

新人/中堅の境界(90日)は打ち合わせでの明言どおり。中堅/ベテランの境界(365日)は
このスクリプトの暫定値(要調整ならNEW_HIRE_DAYS/MID_DAYSを変更するだけでよい)。

使い方:
  python3 build_tenure_api.py --as-of 2026-08-31 --out data/tenure.json
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cyzen_api_client import CyzenAPIClient  # noqa: E402
from company_resolver import canon_name, resolve_company  # noqa: E402

NEW_HIRE_DAYS = 90
MID_DAYS = 365


def bucket_of(days):
    if days <= NEW_HIRE_DAYS:
        return "new"
    if days <= MID_DAYS:
        return "mid"
    return "veteran"


def build(as_of):
    client = CyzenAPIClient()
    users = client.get_all("users", key="users", field="all")
    people = {}
    skipped_no_created = 0
    for u in users:
        name = (u.get("user_name") or "").strip()
        if not name:
            continue
        created = u.get("created_at")
        if not created:
            skipped_no_created += 1
            continue
        try:
            created_date = datetime.datetime.fromisoformat(created).date()
        except ValueError:
            skipped_no_created += 1
            continue
        days = (as_of - created_date).days
        if days < 0:
            continue
        roles = [t["user_tag_name"] for t in (u.get("user_tags") or [])
                 if t.get("user_tag_category_name") == "役割"
                 and t.get("user_tag_name") in ("アポインター", "クローザー")]
        people[canon_name(name)] = {
            "company": resolve_company(name) or "（不明）",
            "roles": roles,
            "created_at": created_date.isoformat(),
            "tenure_days": days,
            "bucket": bucket_of(days),
            "account_status": u.get("account_status"),
        }
    return people, skipped_no_created, client.request_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD（省略時は今日）")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    as_of = datetime.date.fromisoformat(args.as_of) if args.as_of else datetime.date.today()

    people, skipped, req_count = build(as_of)
    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "new_hire_days": NEW_HIRE_DAYS,
        "mid_days": MID_DAYS,
        "people": people,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    counts = {"new": 0, "mid": 0, "veteran": 0}
    for p in people.values():
        counts[p["bucket"]] += 1
    print(f"{len(people)}名 -> {args.out}"
          f"（新人{counts['new']}/中堅{counts['mid']}/ベテラン{counts['veteran']}、"
          f"created_at欠落で除外{skipped}名）")
    print(f"APIリクエスト数: {req_count}")


if __name__ == "__main__":
    main()
