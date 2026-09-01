# -*- coding: utf-8 -*-
"""GitHub Actions用の5分おき自動更新スクリプト(2026-08-20新設)。

小宮山さんのローカルセッション(Claude Codeアプリ)に依存しない、本当の意味での無人自動更新を
実現するために作成。Claude Codeのスケジュールタスク機能が実際には発火しないバグを踏まえ、
GitHub Actionsのcronで完全に独立して動かす。

対象は data/partner_dashboard_latest.html (パートナー実績ダッシュボード) のみ。
Cyzen 営業実績ダッシュボード(dashboard.html)側は対象外(スポット台帳・行動履歴などブラウザ
手動エクスポート依存のデータが多く、API化されていないため)。

スポット作成数・ルート自動記録数(稼働人員数の別指標)・対面率は、このCI版では意図的に省略する
(--spot-csv/--route-history-jsonを渡さない)。理由: これらはブラウザ手動エクスポート由来の
静的スナップショットで、5分おき自動化の対象外にしても実害が小さい一方、CIにこれらの大きい
バイナリ的データを持ち込むと運用が複雑になるため。この2指標はローカルの
refresh_shodan_and_dashboards.py(引き続きこちらが正)を小宮山さんが手動/セッション内で
実行した時だけ埋まる。

使い方: python3 ci_refresh.py
"""
import datetime
import os
import subprocess
import sys

AUTOMATION_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(AUTOMATION_DIR)
DATA_DIR = os.path.join(AUTOMATION_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

sys.path.insert(0, AUTOMATION_DIR)


def jst_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)


def in_business_window(now):
    # 平日8:00-20:59 JST のみ実行する(小宮山さんの運用方針に合わせる)。
    return now.weekday() < 5 and 8 <= now.hour <= 20


def run(cmd, cwd=None):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    print(r.stdout[-3000:])
    if r.returncode != 0:
        print(r.stderr[-3000:], file=sys.stderr)
        raise SystemExit(f"failed: {' '.join(cmd)}")


def month_add(d, delta):
    y, m = d.year, d.month + delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return datetime.date(y, m, 1)


def main():
    now = jst_now()
    print(f"JST now: {now.isoformat()}")
    if not in_business_window(now):
        print("平日8-20時の対象時間外のためスキップします。")
        return

    today = now.date()
    start = month_add(today, -1)
    end_month = month_add(today, 1)
    import calendar
    end = datetime.date(end_month.year, end_month.month,
                         calendar.monthrange(end_month.year, end_month.month)[1])

    shodan_json = os.path.join(DATA_DIR, "cyzen_shodan.json")
    attendance_csv = os.path.join(DATA_DIR, "attendance_merged.csv")
    clockout_csv = os.path.join(DATA_DIR, "clockout_merged.csv")

    print("--- build_shodan_api.py ---")
    run(["python3", os.path.join(AUTOMATION_DIR, "build_shodan_api.py"),
         "--start", start.isoformat(), "--end", end.isoformat(), "--out", shodan_json])

    print("--- build_attendance_api.py ---")
    run(["python3", os.path.join(AUTOMATION_DIR, "build_attendance_api.py"),
         "--start", start.isoformat(), "--end", today.isoformat(),
         "--attendance-out", attendance_csv, "--clockout-out", clockout_csv])

    print("--- Google Sheets API (roster/closing/status/shift) ---")
    from gsheets_client_ci import fetch_all
    sheet_paths = fetch_all(DATA_DIR)

    print("--- build_shift_status.py ---")
    shift_status_json = os.path.join(DATA_DIR, "shift_status.json")
    run(["python3", os.path.join(AUTOMATION_DIR, "build_shift_status.py"),
         "--shift-csv", sheet_paths["shift"], "--attendance-csv", attendance_csv,
         "--clockout-csv", clockout_csv, "--today", today.isoformat(), "--out", shift_status_json])

    print("--- build_attendance_alert.py ---")
    attendance_alert_csv = os.path.join(DATA_DIR, "cyzen_dashboard_master.csv")
    run(["python3", os.path.join(AUTOMATION_DIR, "build_attendance_alert.py"),
         "--clock-in-csv", attendance_csv, "--clock-out-csv", clockout_csv,
         "--now", now.strftime("%Y-%m-%d %H:%M:%S"), "--out", attendance_alert_csv])

    print("--- build_tenure_api.py ---")
    tenure_json = os.path.join(DATA_DIR, "tenure.json")
    run(["python3", os.path.join(AUTOMATION_DIR, "build_tenure_api.py"),
         "--as-of", today.isoformat(), "--out", tenure_json])

    # 企業別の月次目標値(2026-08-31追加)。人手で編集する小さいファイルで、CIが生成するもの
    # ではない(automation/data/company_targets.json としてgit管理・毎回チェックアウトされる)。
    company_targets_json = os.path.join(AUTOMATION_DIR, "data", "company_targets.json")

    # 法人開拓・折衝ログ(2026-09-01追加)。gsheets_client_ci.fetch_allが取得したCSVを
    # build_houjin_crm.pyで会社別に集計する。除外リスト・名寄せエイリアスも人手編集ファイル
    # (company_targets.jsonと同じくgit管理・毎回チェックアウトされる)。
    print("--- build_houjin_crm.py ---")
    houjin_crm_json = os.path.join(DATA_DIR, "houjin_crm.json")
    run(["python3", os.path.join(AUTOMATION_DIR, "build_houjin_crm.py"),
         "--csv", sheet_paths["houjin_crm"],
         "--exclude-json", os.path.join(AUTOMATION_DIR, "data", "houjin_crm_exclude.json"),
         "--alias-json", os.path.join(AUTOMATION_DIR, "data", "houjin_company_alias.json"),
         "--today", today.isoformat(), "--out", houjin_crm_json])

    print("--- build_dashboard.py ---")
    out_html = os.path.join(DATA_DIR, "partner_dashboard_latest_raw.html")
    run(["python3", os.path.join(AUTOMATION_DIR, "build_dashboard.py"),
         "--roster-csv", sheet_paths["roster"], "--closing-csv", sheet_paths["closing"],
         "--status-csv", sheet_paths["status"], "--shift-status-json", shift_status_json,
         "--clockout-csv", clockout_csv, "--attendance-csv", attendance_csv,
         "--attendance-alert-csv", attendance_alert_csv, "--shodan-json", shodan_json,
         "--tenure-json", tenure_json, "--company-targets-json", company_targets_json,
         "--houjin-crm-json", houjin_crm_json,
         "--out", out_html], cwd=AUTOMATION_DIR)

    print("--- パスワードゲート付与 -> index.html ---")
    from deploy_gate import inject_gate
    index_path = os.path.join(REPO_DIR, "index.html")
    inject_gate(out_html, index_path)
    print(f"wrote {index_path}")


if __name__ == "__main__":
    main()
