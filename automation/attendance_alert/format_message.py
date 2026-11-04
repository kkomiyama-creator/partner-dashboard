# -*- coding: utf-8 -*-
"""build_alert.pyの出力JSONを、2026-08-20 23時台に実際に投稿したのと同じ体裁のSlack本文に整形する。

使い方:
  python3 format_message.py --in ../data/alert_latest.json
"""
import argparse
import collections
import json
import os
import re


def _norm(n):
    return re.sub(r"[\s\u3000]+", "", n or "").replace("髙", "高").replace("濵", "濱")


def load_mention_map(path):
    """氏名(正規化) -> Slack UID。mention_map.json は2形式に対応:
    ① slack-mention-map の {"entries": {uid: {bare_name, display_name, additional_display_names}}}
    ② クラウド用の軽量版 {"names": {正規化氏名: uid}}
    同じ氏名が複数UIDに当たる場合（同姓同名など）は曖昧なのでメンションにしない。
    """
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "names" in data:
        return dict(data["names"])
    seen = collections.defaultdict(set)
    for uid, e in (data.get("entries") or {}).items():
        for n in [e.get("bare_name")] + list(e.get("additional_display_names") or []):
            if n:
                seen[_norm(n)].add(uid)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def _label(e, date_mode, mention_map=None):
    name = e["name"]
    uid = (mention_map or {}).get(_norm(name))
    if uid:
        name = f"<@{uid}>"
    if not date_mode:
        return name
    last_in = e.get("last_clock_in")
    if not last_in:
        return f"{name}(直近の出勤打刻なし)"
    m, day = last_in[5:7], last_in[8:10]
    date_part = f"{int(m)}/{int(day)}"
    if date_mode == "carried_over":
        return f"{name}({date_part}出勤打刻のまま)"
    if date_mode == "last_seen":
        return f"{name}(最後の出勤打刻:{date_part})"
    return name


def group_by_company(entries, date_mode=None, mention_map=None):
    by_co = collections.defaultdict(list)
    for e in entries:
        by_co[e["company"] or "所属確認中"].append(_label(e, date_mode, mention_map))
    return by_co


def render_group(entries, date_mode=None, mention_map=None):
    if not entries:
        return "（該当者なし）"
    by_co = group_by_company(entries, date_mode=date_mode, mention_map=mention_map)
    unresolved = by_co.pop("所属確認中", [])
    lines = [f"{co}：{'、'.join(names)}" for co, names in sorted(by_co.items())]
    if unresolved:
        lines.append(f"所属確認中：{'、'.join(unresolved)}")
    return "\n".join(lines)


def render_message(d, mention_map=None):
    """build_alert.pyの出力dict -> Slack本文（先頭に<!channel>）。"""
    g1, g2, g3 = (d["group1_report_no_attendance"], d["group2_carried_over_checkin"],
                  d["group3_today_checkin_no_checkout"])

    date_label = d["generated_at"][:10].replace("-", "年", 1).replace("-", "月", 1) + "日"
    time_label = d["generated_at"][11:16]

    msg = f"""<!channel>
🚨 cyzenの出退勤打刻・報告データ突合のご確認およびご対応のお願い（{date_label} {time_label}時点集計）🚨

夜分遅くに失礼致します。
Fit Founder 営業推進統括本部パートナー推進課の小宮山です。
日頃より営業活動のほど、誠にありがとうございます。

本日のCyzenシステムデータ集計におきまして、下記3点でCyzen上の出退勤打刻と実際の活動記録にズレが確認された方への確認・更新をお願いしたく存じます。
明日で問題ございませんので、下記ご対象の方はご対応のほどよろしくお願いいたします。

▼① アポ後確依頼・クローザー報告は提出されているが、本日の出退勤打刻が見当たらない方
該当者：{len(g1)}名（敬称略）
{render_group(g1, date_mode="last_seen", mention_map=mention_map)}

▼② 出勤状態が前日以前から継続してしまっている方（退勤打刻漏れ）
該当者：{len(g2)}名（敬称略）
{render_group(g2, date_mode="carried_over", mention_map=mention_map)}

▼③ 本日出勤打刻はあるが、まだ退勤打刻がされていない方
該当者：{len(g3)}名（敬称略）
{render_group(g3, mention_map=mention_map)}
"""
    return msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--mention-map", default=None, help="メンション用マッピング（省略時は同フォルダのmention_map.json）")
    args = ap.parse_args()
    with open(args.infile, encoding="utf-8") as f:
        d = json.load(f)
    mp = args.mention_map or os.path.join(os.path.dirname(os.path.abspath(__file__)), "mention_map.json")
    print(render_message(d, load_mention_map(mp)))


if __name__ == "__main__":
    main()
