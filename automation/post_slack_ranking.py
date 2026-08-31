# -*- coding: utf-8 -*-
"""アポ獲得数ランキング・成約数ランキング・企業別アポ獲得数ランキングをSlackへ日次自動投稿する（2026-08-31追加）。

背景: 社長が佐久間さんへ依頼した「kintone×Slack アポ獲得ランキング連携」要件書
（文書ID FF-KS-APPOINT-RANK-001・v1.0・2026-08-30）を、佐久間さん×小宮山さんの
2026-08-31ハドルミーティングで「小宮山さんの既存ダッシュボード（Google Sheets/Cyzen
API集計・ranking_core.py）をデータソースに使うのが最も正しい」と合意した内容の実装。
Render+Node.js新規構築ではなく、既存のGitHub Actions(Python)基盤を拡張する形にした
（実行基盤の選定は小宮山さんに確認済み・2026-08-31）。

要件書からの主な簡略化・差し替え点（小宮山さんに確認済み）:
- 要件書の「後確通過」（kintoneのpost_check_status=通過による当日獲得コホートの
  事後承認）は、Cyzen側に同等のステータス管理が無いため、既存の「アポ成約」
  （獲得報告データ＝Slackクロージング報告ワークフロー由来）と同じ意味として扱う。
  つまり「後確通過ランキング」は「本日アポ成約報告があった件数のランキング」になる
  （要件書の厳密なコホート定義＝獲得日基準ではなく、成約報告日基準という違いがある）。
- kintone REST API/Cursor取得は使わず、ranking_core.aggregate()（roster/closing CSV
  ベース）をそのまま再利用する。
- 投稿先チャンネル・SLACK_BOT_TOKENは2026-08-31時点で未確定。未設定の間はドライラン
  （Slackへ実際には投稿せず、生成したBlock Kit JSONを標準出力するだけ）で動作する。

使い方:
  # ドライラン（SLACK_BOT_TOKEN未設定でも実行可能・実際には投稿しない）
  python3 post_slack_ranking.py --roster-csv <CSV> --closing-csv <CSV> \
      --target-date 2026-08-31 --state-json data/slack_ranking_state.json

  # 本番投稿（環境変数 SLACK_BOT_TOKEN・SLACK_CHANNEL_ID が両方揃っている場合のみ実際に投稿する）
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranking_core import aggregate, aggregate_attendance  # noqa: E402

TOP_N = 10
COMPANY_TOP_N = 10
ATTENDANCE_TOP_N = 10


def pct(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else None


def fmt_pct(v):
    return "—" if v is None else f"{v}%"


def yen(n):
    return f"{n:,}"


def ranked_by_apo(month_ranking):
    """月間アポ獲得数ランキング（アポ獲得 降順→成約 降順→氏名昇順）。
    month_ranking の行は [順位, 氏名, 会社, 成約数, アポ数] （ranking_core.aggregate()の既存出力、
    集計期間は月初〜対象日）。ダッシュボード本体の既定ソート（成約優先）とは目的が違うため、
    ここで独自に並べ替える。"""
    rows = sorted(month_ranking, key=lambda r: (-r[4], -r[3], r[1]))
    return rows[:TOP_N]


def ranked_by_seiyaku(month_ranking):
    """月間成約(後確通過扱い)ランキング。aggregate()側の既定ソート(成約降順→アポ数降順)がそのまま使える。"""
    return month_ranking[:TOP_N]


def build_attendance_ranking(attendance_csv, target_date):
    """月次合計の稼働日数ランキング（2026-08-31追加・小宮山さんの依頼）。
    Cyzenの出勤報告CSV（report-v2の出勤報告エクスポート、またはCyzen連携APIの
    build_attendance_api.py出力＝attendance_merged.csvと同じ列構成）を使い、
    ranking_core.aggregate_attendance()の既存ロジック（同日複数回打刻の重複排除込み）を
    そのまま再利用する。roster/closing（Google Sheets）とは別系統のデータソース。"""
    d = datetime.date.fromisoformat(target_date)
    month_start = d.replace(day=1).strftime("%Y-%m-%d")
    att = aggregate_attendance(attendance_csv, month_start, target_date)
    # person_rows: [表示名, 会社, 稼働日数] （aggregate_attendance側で稼働日数降順ソート済み）
    return att["person_rows"][:ATTENDANCE_TOP_N]


def build_summary(roster_csv, closing_csv, target_date, attendance_csv=None):
    """target_date: 'YYYY-MM-DD'。
    2026-08-31の小宮山さんの依頼により、ランキング本体は「その日時点での当月累計」を毎日
    更新する形式にした（1日分の新規件数ランキングではない）。本日の伸びは各行に補足表示する。
    企業別総計は当日/累計を廃止し、当月のアポ獲得数ランキングのみに変更（2026-08-31改訂）。
    attendance_csvを渡すと、Cyzen出勤記録ベースの月次稼働日数ランキングも追加する。"""
    d = datetime.date.fromisoformat(target_date)
    day_s = d.strftime("%Y/%m/%d")
    month_start = d.replace(day=1).strftime("%Y/%m/%d")

    day = aggregate(roster_csv, closing_csv, day_s, day_s)
    month = aggregate(roster_csv, closing_csv, month_start, day_s)

    # 氏名 -> (本日アポ数, 本日成約数) のルックアップ（ランキング各行に「本日+N件」を添えるため）
    day_by_name = {r[1]: (r[4], r[3]) for r in day["apo_ranking"]}

    company_rows = [{"company": c["company"], "month": c["apo_kakutoku"]} for c in month["companies"]]
    company_rows.sort(key=lambda r: -r["month"])

    total_apo_month = sum(c["apo_kakutoku"] for c in month["companies"])
    total_seiyaku_month = sum(c["apo_seiyaku"] for c in month["companies"])
    total_apo_day = sum(c["apo_kakutoku"] for c in day["companies"])
    unassigned = len(month["unresolved_apo"]) + len(month["unresolved_clo"])
    cancelled = sum(month.get("apo_cancel_by_name", {}).values())

    attendance_ranking = build_attendance_ranking(attendance_csv, target_date) if attendance_csv else None

    return {
        "target_date": target_date,
        "month_label": d.strftime("%Y年%m月度"),
        "apo_ranking_by_apo": ranked_by_apo(month["apo_ranking"]),
        "apo_ranking_by_seiyaku": ranked_by_seiyaku(month["apo_ranking"]),
        "attendance_ranking": attendance_ranking,
        "day_by_name": day_by_name,
        "company_rows": company_rows[:COMPANY_TOP_N],
        "n_companies_total": len(company_rows),
        "total_apo_month": total_apo_month,
        "total_seiyaku_month": total_seiyaku_month,
        "total_apo_day": total_apo_day,
        "unassigned": unassigned,
        "cancelled": cancelled,
        "n_companies": len(month["companies"]),
    }


def build_blocks(summary, dashboard_url):
    d = summary["target_date"]
    month_label = summary["month_label"]

    def today_delta_txt(name):
        day_apo, day_seiyaku = summary["day_by_name"].get(name, (0, 0))
        parts = []
        if day_apo:
            parts.append(f"本日+{day_apo}件")
        if day_seiyaku:
            parts.append(f"本日成約+{day_seiyaku}件")
        return "・" + "・".join(parts) if parts else ""

    lines_apo = []
    for i, r in enumerate(summary["apo_ranking_by_apo"], 1):
        name, co, seiyaku, apo = r[1], r[2], r[3], r[4]
        lines_apo.append(
            f"{i}. {name}（{co}） 月間{apo}件（成約{seiyaku}件／成約率{fmt_pct(pct(seiyaku, apo))}）{today_delta_txt(name)}"
        )

    lines_seiyaku = []
    for i, r in enumerate(summary["apo_ranking_by_seiyaku"], 1):
        name, co, seiyaku, apo = r[1], r[2], r[3], r[4]
        lines_seiyaku.append(f"{i}. {name}（{co}） 月間成約{seiyaku}件（アポ{apo}件）{today_delta_txt(name)}")

    lines_company = []
    for i, c in enumerate(summary["company_rows"], 1):
        lines_company.append(f"{i}. {c['company']}　{c['month']}件")

    lines_attendance = None
    if summary["attendance_ranking"] is not None:
        lines_attendance = []
        for i, (name, co, days) in enumerate(summary["attendance_ranking"], 1):
            lines_attendance.append(f"{i}. {name}（{co}） {days}日")

    note_parts = []
    if summary["unassigned"]:
        note_parts.append(f"未紐付け{summary['unassigned']}件")
    if summary["cancelled"]:
        note_parts.append(f"キャンセル{summary['cancelled']}件")
    if summary["n_companies_total"] > COMPANY_TOP_N:
        note_parts.append(f"企業別ランキングは上位{COMPANY_TOP_N}社のみ表示（全{summary['n_companies_total']}社）")
    note = "　|　".join(note_parts) if note_parts else "特になし"

    now_jst = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M JST")

    text_fallback = (
        f"{month_label}（{d}時点） アポ獲得数ランキング：月間アポ{summary['total_apo_month']}件"
        f"（本日+{summary['total_apo_day']}件）｜月間成約{summary['total_seiyaku_month']}件"
    )

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 月間アポ獲得数ランキング｜{month_label}（{d}時点）"}},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"*月間アポ獲得* {summary['total_apo_month']}件（本日+{summary['total_apo_day']}件）"
                 f"　|　*月間成約* {summary['total_seiyaku_month']}件　|　*集計対象* {summary['n_companies']}社"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": "*🏆 アポ獲得数ランキング（当月累計）*\n" + ("\n".join(lines_apo) if lines_apo else "対象データなし")}},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": "*✅ 成約数ランキング（当月累計）*\n" + ("\n".join(lines_seiyaku) if lines_seiyaku else "対象データなし")}},
    ]
    if lines_attendance is not None:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": "*🚶 稼働日数ランキング（当月累計・Cyzen出退勤記録ベース）*\n"
                    + ("\n".join(lines_attendance) if lines_attendance else "対象データなし")}})
    blocks += [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": "*🏢 企業別アポ獲得数ランキング（当月）*\n" + ("\n".join(lines_company) if lines_company else "対象データなし")}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"注意: {note}"}]},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"最終更新 {now_jst}　|　<{dashboard_url}|ダッシュボードで詳細を見る>"}
        ]},
    ]
    return blocks, text_fallback


def load_state(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(path, state):
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def post_or_update_slack(token, channel, blocks, text, existing_ts):
    import requests
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    if existing_ts:
        payload = {"channel": channel, "ts": existing_ts, "text": text, "blocks": blocks}
        resp = requests.post("https://slack.com/api/chat.update", headers=headers, json=payload, timeout=30)
    else:
        payload = {"channel": channel, "text": text, "blocks": blocks}
        resp = requests.post("https://slack.com/api/chat.postMessage", headers=headers, json=payload, timeout=30)
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"Slack API error: {body.get('error')}")
    return body["ts"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv", required=True)
    ap.add_argument("--target-date", default=None, help="YYYY-MM-DD（省略時はJSTの今日）")
    ap.add_argument("--state-json", default=None,
                     help="business_date -> slack_ts の永続状態ファイル（再実行時の重複投稿防止用）")
    ap.add_argument("--attendance-csv", default=None,
                     help="Cyzen出勤報告CSV（attendance_merged.csvと同じ列構成）。"
                          "省略時は稼働日数ランキングのセクションが非表示になる")
    ap.add_argument("--dashboard-url", default="https://kkomiyama-creator.github.io/partner-dashboard/")
    args = ap.parse_args()

    target_date = args.target_date or (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")

    summary = build_summary(args.roster_csv, args.closing_csv, target_date, attendance_csv=args.attendance_csv)
    blocks, text = build_blocks(summary, args.dashboard_url)

    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")

    if not token or not channel:
        print("[DRY RUN] SLACK_BOT_TOKEN/SLACK_CHANNEL_IDが未設定のため実際には投稿しません。")
        print(json.dumps({"text": text, "blocks": blocks}, ensure_ascii=False, indent=2))
        return

    state = load_state(args.state_json)
    existing_ts = state.get(target_date)
    ts = post_or_update_slack(token, channel, blocks, text, existing_ts)
    state[target_date] = ts
    save_state(args.state_json, state)
    print(f"投稿完了 ({'更新' if existing_ts else '新規'}): ts={ts}")


if __name__ == "__main__":
    main()
