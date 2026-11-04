# -*- coding: utf-8 -*-
"""出退勤打刻・報告データ突合アラートの「PC不要」自動周知（GitHub Actions・2026-11-04新設）。

毎晩22:10(JST)に attendance-alert.yml から実行される。build_alert.py（Cyzen /reports から
①②③を計算）→ format_message.render_message（周知文）→ Slackへ投稿、までを1本で行う。

投稿の安全装置:
  - SLACK_BOT_TOKEN が未設定の間は「ドライラン」（投稿せず、周知文をログとアーティファクトに残すだけ）。
    この間は小宮山さんのMac側のスケジュールタスク（下書き＋DM）が代わりに動く運用。
  - 21:00〜23:59(JST)以外は投稿しない（③は「まだ退勤していない」を見るので夜でないと過検知になる）。
    GitHub Actionsのscheduleは遅延することがあり、日付をまたいで走った場合に誤投稿しないための装置。
  - ①②③が全員0名なら投稿しない。
  - 件数が異常に多い（合計 > 80名）場合はデータ取得の異常とみなして投稿せず、失敗終了（GitHubから通知が出る）。
  - 同じ日に2回投稿しない（automation/data/attendance_alert_state.json）。
使い方: python3 automation/attendance_alert/post_alert.py [--dry-run] [--force-time]
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import build_alert  # noqa: E402
from format_message import render_message, load_mention_map  # noqa: E402

STATE = os.path.join(HERE, "..", "data", "attendance_alert_state.json")
MESSAGE_OUT = os.path.join(HERE, "..", "data", "attendance_alert_message.txt")
DEFAULT_CHANNEL = "C0BA1FA2FHC"  # #02_sh_パートナー様周知用（Slack Connect）
MAX_TOTAL = 80


def jst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="トークンがあっても投稿しない")
    ap.add_argument("--force-time", action="store_true", help="21時台〜23時台のガードを無視する（手動テスト用）")
    args = ap.parse_args()

    now = jst_now()
    today = now.strftime("%Y-%m-%d")
    print(f"JST now: {now.isoformat()}")

    if not args.force_time and not (21 <= now.hour <= 23):
        print("21:00〜23:59(JST)以外のため投稿しません（③の過検知・日付またぎの誤投稿を防ぐ）。")
        return

    state = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
    if state.get("last_posted_date") == today and not args.dry_run:
        print(f"{today} は投稿済みのためスキップします。")
        return

    exclude = []
    ex_path = os.path.join(HERE, "exclude_names.json")
    if os.path.exists(ex_path):
        with open(ex_path, encoding="utf-8") as f:
            exclude = json.load(f).get("exclude_names", [])

    d = build_alert.build(now, 5, exclude_names=exclude)
    g1, g2, g3 = (d["group1_report_no_attendance"], d["group2_carried_over_checkin"],
                  d["group3_today_checkin_no_checkout"])
    total = len(g1) + len(g2) + len(g3)
    print(f"① {len(g1)}名 / ② {len(g2)}名 / ③ {len(g3)}名（合計 {total}）")

    msg = render_message(d, load_mention_map(os.path.join(HERE, "mention_map.json")))
    os.makedirs(os.path.dirname(MESSAGE_OUT), exist_ok=True)
    with open(MESSAGE_OUT, "w", encoding="utf-8") as f:
        f.write(msg)

    if total == 0:
        print("該当者が0名のため投稿しません。")
        return
    if total > MAX_TOTAL:
        print(f"合計{total}名が上限{MAX_TOTAL}名を超えました。データ取得の異常の可能性があるため投稿せず失敗終了します。", file=sys.stderr)
        raise SystemExit(1)

    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_ATTENDANCE_CHANNEL_ID") or DEFAULT_CHANNEL
    if args.dry_run or not token:
        why = "--dry-run" if args.dry_run else "SLACK_BOT_TOKEN未設定"
        print(f"[DRY RUN]（{why}）実際には投稿しません。周知文は次のとおりです:\n")
        print(msg)
        return

    import requests
    r = requests.post("https://slack.com/api/chat.postMessage",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                      json={"channel": channel, "text": msg, "link_names": False}, timeout=30)
    resp = r.json()
    if not resp.get("ok"):
        print(f"Slack投稿に失敗: {resp.get('error')}", file=sys.stderr)
        raise SystemExit(1)
    state = {"last_posted_date": today, "last_ts": resp.get("ts"), "channel": channel}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    print(f"投稿しました（ts={resp.get('ts')}）")


if __name__ == "__main__":
    main()
