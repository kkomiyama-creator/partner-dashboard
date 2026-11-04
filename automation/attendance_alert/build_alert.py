# -*- coding: utf-8 -*-
"""出退勤打刻・報告データ突合アラート（2026-08-21 スキル化）。

2026-08-20/21のセッションで実際にSlack投稿した「cyzenの出退勤打刻・報告データ突合の
ご確認およびご対応のお願い」と同じ3カテゴリを、Cyzen連携APIの /reports エンドポイントだけで
再現する。ブラウザでのreport-v2手動エクスポート（過去に自動操作が不安定だった経緯あり・
memory: cyzen-report-v2-automation-issue参照）には依存しない。

/reports は report_definition_name に「出勤報告」「勤務終了報告」「アポ後確依頼」
「クローザー：〜」がすべて含まれるので、これ1本で3カテゴリを計算できる（2026-08-21に
実データで確認済み: 直近1日で 出勤報告48件・勤務終了報告84件・アポ後確依頼53件などが
取得できた）。

3カテゴリの定義（2026-08-20 23時台に実際に使った定義を踏襲）:
  ① アポ後確依頼・クローザー報告は本日提出されているが、本日の出退勤打刻（出勤報告）が
     見当たらない方（報告日と出退勤打刻日が一致しない＝入力漏れの疑い）
  ② 出勤状態が前日以前から継続してしまっている方（退勤打刻漏れ・つけっぱなし）
  ③ 本日は出勤打刻があるが、実行時点でまだ退勤打刻がされていない方
     （毎晩23時台に実行する前提。日中に実行すると③に過検知が出るので注意）

「出勤中」の判定は、その人の直近の出勤報告と直近の勤務終了報告を比べ、出勤報告の方が
新しければ「まだ退勤していない」とみなすシンプルな方式。Cyzenは状態そのものを持たないので、
打刻の新しい方＝現在の状態、という前提に立っている（build_attendance_alert.pyの
出退勤区分ロジックと同じ考え方）。

使い方:
  python3 build_alert.py --lookback-days 5 --out ../data/alert_latest.json
  （--lookback-daysは②の「前日以前から継続」をどこまで遡って検知するかの上限。
    長期間チェックインしっぱなしの人を拾うため、既定は5日）
"""
import argparse
import collections
import datetime
import json
import os
import sys

# GitHub Actions版（2026-11-04）: automation/ 直下の cyzen_api_client.py / company_resolver.py を使う
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cyzen_api_client import CyzenAPIClient, build_role_map  # noqa: E402
from company_resolver import canon_name, norm_name, MASTER  # noqa: E402

CLOCK_IN = "出勤報告"
CLOCK_OUT = "勤務終了報告"
WORK_REPORT_DEFS = {"アポ後確依頼"}  # これに加え「クローザー：」で始まるものも対象


def jst(iso_utc):
    return datetime.datetime.fromisoformat(iso_utc) + datetime.timedelta(hours=9)


def fetch_reports(client, since_iso, until_iso):
    out, cursor_id, cursor_updated = [], None, None
    for _ in range(500):
        params = {"updated_from": since_iso, "updated_to": until_iso}
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
    raise RuntimeError("reports pagination exceeded 500 pages")


DEEP_SEARCH_CHUNK_DAYS = 6
DEEP_SEARCH_MAX_DAYS = 540


def find_last_clock_in_deep(client, now, uids, since_boundary):
    """①で直近lookback_days以内に出勤報告が見つからなかった人だけ、6日区切りで
    最大540日前まで遡って最後の出勤報告日時を探す（2026-09-05に手動で行った調査を自動化）。
    since_boundary: 既に探索済みの直近側の境界（＝通常のlookback_daysのsince）。
    ここから540日前まで再探索するので、通常探索分と多少重複するが冪等なので問題ない。"""
    remaining = set(uids)
    found = {}
    hard_limit = now - datetime.timedelta(days=DEEP_SEARCH_MAX_DAYS)
    cur_end = since_boundary
    while cur_end > hard_limit and remaining:
        cur_start = max(cur_end - datetime.timedelta(days=DEEP_SEARCH_CHUNK_DAYS), hard_limit)
        since_iso, until_iso = cur_start.isoformat(), cur_end.isoformat()
        cursor_id, cursor_updated = None, None
        for _ in range(200):
            params = {"updated_from": since_iso, "updated_to": until_iso}
            if cursor_id:
                params["next_report_id"] = cursor_id
                params["next_report_updated_at"] = cursor_updated
            data = client.get("reports", **params)
            chunk = data.get("reports") or []
            for rep in chunk:
                if rep.get("report_definition_name") != CLOCK_IN:
                    continue
                uid = rep.get("user_id")
                if uid not in remaining:
                    continue
                t = jst(rep.get("created_at"))
                if uid not in found or t > found[uid]:
                    found[uid] = t
            cursor_id = data.get("next_report_id")
            cursor_updated = data.get("next_report_updated_at")
            if not cursor_id or not chunk:
                break
        # 見つかった人はこのchunk内が最新出現なので、これ以上は探さなくてよい
        remaining -= set(found)
        cur_end = cur_start
    return found


def build(now, lookback_days, exclude_names=None):
    exclude_keys = {norm_name(n) for n in (exclude_names or [])}
    client = CyzenAPIClient()
    role_map, _, _ = build_role_map(client)
    since = (now - datetime.timedelta(days=lookback_days)).isoformat()
    reports = fetch_reports(client, since, now.isoformat())

    clock_in_at = {}   # user_id -> latest 出勤報告 jst datetime
    clock_out_at = {}  # user_id -> latest 勤務終了報告 jst datetime
    work_report_today = {}  # user_id -> [(kind, jst_datetime), ...] 本日提出分

    today = now.date()  # NOTE: nowはJSTで渡す前提
    for rep in reports:
        uid = rep.get("user_id")
        name_def = rep.get("report_definition_name") or ""
        created = rep.get("created_at") or ""
        if not uid or not created:
            continue
        t = jst(created)

        if name_def == CLOCK_IN:
            if uid not in clock_in_at or t > clock_in_at[uid]:
                clock_in_at[uid] = t
        elif name_def == CLOCK_OUT:
            if uid not in clock_out_at or t > clock_out_at[uid]:
                clock_out_at[uid] = t
        elif name_def in WORK_REPORT_DEFS or name_def.startswith("クローザー："):
            if t.date() == today:
                work_report_today.setdefault(uid, []).append((name_def, t))

    def user_label(uid):
        info = role_map.get(uid) or {}
        name = canon_name(info.get("name") or "")
        # build_role_map()はグループ(エリア)しか持たず会社名を持たないので、
        # weekly-partner-rankingスキルと同じ現役ユーザーマスタ(MASTER)から会社名を引く。
        company = MASTER.get(norm_name(name), "")
        return name, company

    group1, group2, group3 = [], [], []

    for uid, entries in work_report_today.items():
        name, company = user_label(uid)
        if norm_name(name) in exclude_keys:
            continue
        checked_in_today = uid in clock_in_at and clock_in_at[uid].date() == today
        if not checked_in_today:
            kinds = "・".join(sorted({k for k, _ in entries}))
            last_in = clock_in_at.get(uid)
            group1.append({
                "user_id": uid, "name": name, "company": company, "report_kind": kinds,
                "last_clock_in": last_in.strftime("%Y-%m-%d %H:%M:%S") if last_in else None,
            })

    all_checked_in_uids = set(clock_in_at)
    for uid in all_checked_in_uids:
        last_in = clock_in_at[uid]
        last_out = clock_out_at.get(uid)
        still_checked_in = last_out is None or last_in > last_out
        if not still_checked_in:
            continue
        name, company = user_label(uid)
        if norm_name(name) in exclude_keys:
            continue
        entry = {"user_id": uid, "name": name, "company": company,
                  "last_clock_in": last_in.strftime("%Y-%m-%d %H:%M:%S")}
        if last_in.date() < today:
            group2.append(entry)
        elif last_in.date() == today:
            group3.append(entry)

    # ①で直近lookback_days以内に出勤報告が見つからなかった人は、見つかるまで
    # 過去へ遡って検索する（2026-09-05に手動で行った調査の自動化・恒久対応）。
    missing_uids = [e["user_id"] for e in group1 if e["last_clock_in"] is None]
    if missing_uids:
        since_boundary = now - datetime.timedelta(days=lookback_days)
        deep_found = find_last_clock_in_deep(client, now, missing_uids, since_boundary)
        for e in group1:
            if e["user_id"] in deep_found:
                e["last_clock_in"] = deep_found[e["user_id"]].strftime("%Y-%m-%d %H:%M:%S")

    for g in (group1, group2, group3):
        g.sort(key=lambda x: (x["company"], x["name"]))

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "group1_report_no_attendance": group1,
        "group2_carried_over_checkin": group2,
        "group3_today_checkin_no_checkout": group3,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", default=None,
                     help="集計基準時刻(JST・YYYY-MM-DD HH:MM:SS)。省略時は実行時刻をJSTとみなす")
    ap.add_argument("--lookback-days", type=int, default=5)
    ap.add_argument("--exclude-names-file", default=None,
                     help="集計から除外する人名リストJSON（{'exclude_names': [...]})。"
                          "小宮山さんご自身など、アラート対象にすべきでない人を入れる")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    now = (datetime.datetime.strptime(args.now, "%Y-%m-%d %H:%M:%S") if args.now
           else datetime.datetime.now())

    exclude_names = []
    if args.exclude_names_file and os.path.exists(args.exclude_names_file):
        with open(args.exclude_names_file, encoding="utf-8") as f:
            exclude_names = json.load(f).get("exclude_names", [])

    result = build(now, args.lookback_days, exclude_names=exclude_names)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"① 報告あり・本日出退勤打刻なし: {len(result['group1_report_no_attendance'])}名")
    print(f"② 出勤状態が前日以前から継続: {len(result['group2_carried_over_checkin'])}名")
    print(f"③ 本日出勤・退勤未打刻: {len(result['group3_today_checkin_no_checkout'])}名")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
