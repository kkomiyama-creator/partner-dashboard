# パートナー実績ダッシュボード（社内公開用）

`index.html` は自動生成物です。手編集しないでください。

- 元データ: Cyzen連携API + kintone/Googleスプレッドシート
- 生成元: `claude-cyzen-ppt/.claude/skills/weekly-partner-ranking/scripts/build_dashboard.py`
- 更新方法: `python3 deploy.py`（`partner_dashboard_latest.html` を読み込み、パスワードゲートを付与して
  `index.html` に書き出し、commit & push する。GitHub Pagesが自動で再デプロイする）
- 自動更新: `shodan-realtime-refresh`（平日8-20時・30分おき）スケジュールタスクの末尾から呼ばれる想定
- アクセス制限: 簡易パスワードゲート（本物のセキュリティではなく抑止力。ソースを見れば回避可能）
