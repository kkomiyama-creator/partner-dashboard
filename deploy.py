# -*- coding: utf-8 -*-
"""パートナー実績ダッシュボードをGitHub Pages用にパスワードゲート付きで書き出し、
git commit & push する(2026-08-19新設)。

自動更新パイプライン(shodan-realtime-refresh等)の最後にこのスクリプトを呼ぶだけで、
GitHub Pagesが自動的に再デプロイされる。

使い方:
  python3 deploy.py
"""
import os
import subprocess
import sys

SRC = "/Users/fitfounderkomiyamakyousuke/Documents/claude-cyzen-ppt/.claude/skills/weekly-partner-ranking/data/partner_dashboard_latest.html"
DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DEPLOY_DIR, "index.html")

sys.path.insert(0, os.path.join(DEPLOY_DIR, "automation"))
from deploy_gate import inject_gate  # noqa: E402


def run(cmd, cwd=None, check=True):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout[-2000:])
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        if check:
            raise SystemExit(f"failed: {' '.join(cmd)}")
    return r


def main():
    inject_gate(SRC, OUT)
    print(f"wrote {OUT} ({os.path.getsize(OUT):,} bytes)")

    run(["git", "add", "-A"], cwd=DEPLOY_DIR)
    diff = run(["git", "diff", "--cached", "--quiet"], cwd=DEPLOY_DIR, check=False)
    if diff.returncode == 0:
        print("変更なし。コミットをスキップします。")
        return
    run(["git", "-c", "user.email=dashboard-bot@fit-founder.net", "-c", "user.name=Dashboard Bot",
         "commit", "-m", "auto-update dashboard"], cwd=DEPLOY_DIR)
    run(["git", "push"], cwd=DEPLOY_DIR)
    print("pushed. GitHub Pagesが数十秒〜数分で再デプロイされます。")


if __name__ == "__main__":
    main()
