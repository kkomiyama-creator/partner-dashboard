#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日次パートナー実績ダッシュボード（HTML生成）。
自動取得可能なデータ（アポインター獲得履歴・獲得報告データ）のみを使い、月初〜当日で集計する。
KITONE(CO/キャンセル/否決)は現時点でMVPスコープ外（成約率の分母が粗い点に注意）。

使い方:
    python3 build_dashboard.py [--out /path/to/dashboard.html] [--downloads ~/Downloads]

--start/--end を省略すると「当月1日〜当日」を自動計算する。
標準出力に集計サマリー(JSON)を出す。
"""
import argparse
import html
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranking_core import (aggregate, find_latest, aggregate_attendance, resolve_attendance_source,
                           prev_range, merge_diff, suggest_reinforcement, load_company_notes,
                           annotate_rankings, flag_attendance_mismatch,
                           aggregate_completion, aggregate_dow_hour,
                           load_attendance_alert_master, augment_with_alert_master,
                           company_attendance_alert_counts, aggregate_visits, aggregate_closer_shodan)
from company_resolver import resolve_company, norm_name
from build_declining_performers import build as build_declining_performers
import config

TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>パートナー実績ダッシュボード</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{
  --navy:#0F1F3D; --ink:#0F1F3D; --blue:#1A56DB; --blue-light:#3B82F6; --blue-pale:#EFF4FF; --blue-border:#C7D7FD;
  --slate:#F8FAFF; --white:#FFFFFF; --text:#1E293B; --text-sub:#64748B; --text-xs:#94A3B8;
  --success:#059669; --success-bg:#ECFDF5; --warn:#D97706; --warn-bg:#FFFBEB;
  --danger:#DC2626; --danger-bg:#FEF2F2; --border:#E2E8F0;
  --radius:12px; --radius-sm:8px;
  --shadow:0 1px 3px rgba(15,31,61,.06), 0 4px 16px rgba(15,31,61,.09);
}
@media (prefers-color-scheme: dark){
  :root{
    --navy:#0B1730; --ink:#EAF0FF; --blue:#5B8CFF; --blue-light:#7AA2FF; --blue-pale:#152244; --blue-border:#25396B;
    --slate:#0B1220; --white:#121A2B; --text:#E7ECF7; --text-sub:#9FB0CE; --text-xs:#7488AC;
    --success:#34D399; --success-bg:#0E2A22; --warn:#FBBF24; --warn-bg:#332208;
    --danger:#F87171; --danger-bg:#33161A; --border:#22304C;
    --shadow:0 1px 3px rgba(0,0,0,.35), 0 4px 20px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  --navy:#0B1730; --ink:#EAF0FF; --blue:#5B8CFF; --blue-light:#7AA2FF; --blue-pale:#152244; --blue-border:#25396B;
  --slate:#0B1220; --white:#121A2B; --text:#E7ECF7; --text-sub:#9FB0CE; --text-xs:#7488AC;
  --success:#34D399; --success-bg:#0E2A22; --warn:#FBBF24; --warn-bg:#332208;
  --danger:#F87171; --danger-bg:#33161A; --border:#22304C;
}
:root[data-theme="light"]{
  --navy:#0F1F3D; --ink:#0F1F3D; --blue:#1A56DB; --blue-light:#3B82F6; --blue-pale:#EFF4FF; --blue-border:#C7D7FD;
  --slate:#F8FAFF; --white:#FFFFFF; --text:#1E293B; --text-sub:#64748B; --text-xs:#94A3B8;
  --success:#059669; --success-bg:#ECFDF5; --warn:#D97706; --warn-bg:#FFFBEB;
  --danger:#DC2626; --danger-bg:#FEF2F2; --border:#E2E8F0;
}
*{box-sizing:border-box;}
body{
  margin:0; background:var(--slate); color:var(--text);
  font-family:'Inter','Hiragino Sans','Yu Gothic UI',sans-serif;
  font-feature-settings:"tnum" 1; font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px; margin:0 auto; padding:28px 20px 64px;}
header.top{
  display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:12px;
  padding-bottom:18px; margin-bottom:22px; border-bottom:1px solid var(--border);
}
header.top h1{font-size:21px; font-weight:800; color:var(--ink); margin:0; letter-spacing:.01em;}
header.top .meta{font-size:12.5px; color:var(--text-sub); text-align:right; line-height:1.6;}
header.top .meta b{color:var(--text);}

.tiles{display:grid; grid-template-columns:repeat(7,1fr); gap:14px; margin-bottom:26px;}
@media (max-width:1300px){ .tiles{grid-template-columns:repeat(4,1fr);} }
@media (max-width:980px){ .tiles{grid-template-columns:repeat(3,1fr);} }
@media (max-width:760px){ .tiles{grid-template-columns:repeat(2,1fr);} }
.tile{
  background:var(--white); border:1px solid var(--border); border-radius:var(--radius);
  padding:16px 18px; box-shadow:var(--shadow); position:relative; overflow:hidden;
  transition:transform .15s, box-shadow .15s;
}
.tile::before{content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--blue);}
.tile.t-warn::before{background:var(--warn);}
.tile.t-danger::before{background:var(--danger);}
.tile.t-success::before{background:var(--success);}
.tile .label{font-size:11.5px; color:var(--text-sub); font-weight:600; letter-spacing:.03em; text-transform:uppercase;}
.tile .value{font-size:26px; font-weight:800; color:var(--ink); margin-top:6px; letter-spacing:-.01em;}
.tile .unit{font-size:13px; font-weight:600; color:var(--text-sub); margin-left:3px;}
.tile .sub{font-size:11.5px; color:var(--text-xs); margin-top:4px;}
.tile.clickable{cursor:pointer;}
.tile.clickable:hover{box-shadow:0 4px 20px rgba(15,31,61,.13); transform:translateY(-2px);}

/* ============================================================
   BIコンポーネント用スタイル（2026-08-11・小宮山さんとの検討を経て「ロードマップ風ファネル
   （丸ノード＋点線の道＋各地点に実数バッジ）」＋「稼働人員数のみ人型ピクトグラム」の方向で確定）
   参照: dashboard.html の .quad-label（散布図の隅ラベル）は踏襲。ファネルは道のり表現に刷新。
   ============================================================ */
.bi-journey{display:flex; align-items:flex-start; padding:6px 0 0;}
.bi-journey-step{flex:0 0 auto; width:74px; display:flex; flex-direction:column; align-items:center; gap:2px;}
.bi-journey-node{
  width:50px; height:50px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-size:21px; color:#fff; box-shadow:0 0 0 4px var(--white); transition:transform .15s;
}
.bi-journey-node:hover{transform:scale(1.06);}
.bi-journey-num{font-size:17px; font-weight:900; color:var(--ink); margin-top:7px; letter-spacing:-.02em;}
.bi-journey-name{font-size:11px; color:var(--text-sub); font-weight:600;}
.bi-journey-link{flex:1; min-width:28px; display:flex; flex-direction:column; align-items:center; padding-top:25px;}
.bi-journey-track{
  width:100%; height:2px;
  background-image:linear-gradient(to right, var(--border-strong) 55%, transparent 0%);
  background-size:8px 2px; background-repeat:repeat-x;
}
.bi-journey-cvr{
  margin-top:-11px; font-size:10px; font-weight:700; color:var(--blue); background:var(--white);
  border:1px solid var(--blue-border); border-radius:20px; padding:2px 8px; white-space:nowrap;
}
.bi-journey-cvr.bad{color:var(--danger); border-color:#FECACA;}
.bi-progress-bar{height:6px; border-radius:3px; background:var(--border); overflow:hidden;}
.bi-progress-fill{height:100%; border-radius:3px; background:var(--blue);}
.bi-progress-fill.success{background:var(--success);}
.bi-progress-fill.warn{background:var(--warn);}
.bi-progress-fill.danger{background:var(--danger);}
.bi-quad-label{font-size:9px; font-weight:700; fill:var(--text-xs);}
.bi-pictogram{display:flex; align-items:center; gap:1px; margin-top:6px; flex-wrap:wrap;}
.bi-pictogram-icon{font-size:13px; line-height:1;}
.bi-pictogram-note{font-size:9.5px; color:var(--text-xs); margin-left:4px;}

.kpi-gauge-row{display:flex; gap:28px; flex-wrap:wrap; justify-content:flex-start;}
.kpi-gauge{display:flex; flex-direction:column; align-items:center; gap:6px; min-width:132px;}
.kpi-gauge-label{font-size:12px; font-weight:700; color:var(--text-sub);}
.kpi-gauge-target{font-size:11.5px; color:var(--text-xs); font-weight:600;}
@media (max-width:640px){
  .kpi-gauge-row{gap:16px; justify-content:space-around;}
  .kpi-gauge{min-width:104px;}
  .kpi-gauge svg{width:104px; height:104px;}
}

.tabbar{display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-bottom:14px; border-bottom:1px solid var(--border); flex-wrap:wrap;}
.tabs{
  display:flex; gap:6px; flex-wrap:nowrap; overflow-x:auto; overflow-y:hidden; -webkit-overflow-scrolling:touch;
  scrollbar-width:thin; padding-bottom:2px; max-width:100%;
}
.tab{
  display:flex; align-items:center; gap:5px; flex:none; white-space:nowrap;
  padding:8px 14px; font-size:13px; font-weight:600; color:var(--text-sub); cursor:pointer;
  border:1px solid transparent; border-radius:999px; background:transparent;
  user-select:none; transition:color .12s, background-color .12s, border-color .12s;
}
.tab .tab-ico{font-size:14px; line-height:1;}
.tab:hover{color:var(--text); background:var(--border);}
.tab.active{color:var(--blue); background:var(--blue-pale); border-color:var(--blue-border);}
.printbtn{
  display:flex; align-items:center; gap:6px; margin-bottom:8px; padding:7px 13px;
  font-size:12.5px; font-weight:700; color:var(--blue); background:var(--blue-pale);
  border:1px solid var(--blue-border); border-radius:999px; cursor:pointer; white-space:nowrap;
  font-family:inherit; transition:filter .12s;
}
.printbtn:hover{filter:brightness(0.96);}
.printbtn svg{width:13px; height:13px; flex:none;}
.actionbar{display:flex; gap:8px; margin-bottom:8px;}
.csvbtn{
  display:flex; align-items:center; gap:6px; padding:7px 13px;
  font-size:12.5px; font-weight:700; color:var(--success); background:var(--success-bg);
  border:1px solid var(--success); border-radius:999px; cursor:pointer; white-space:nowrap;
  font-family:inherit; transition:filter .12s;
}
.csvbtn:hover{filter:brightness(0.96);}
.csvbtn svg{width:13px; height:13px; flex:none;}
.csvbtn:disabled{opacity:.5; cursor:default;}

tbody tr.clickable{cursor:pointer;}
tbody tr.clickable:hover{background:var(--blue-pale);}

.modal-overlay{
  display:none; position:fixed; inset:0; background:rgba(15,23,42,.45);
  align-items:center; justify-content:center; z-index:100; padding:24px;
}
.modal-overlay.show{display:flex;}
.modal-box{
  background:var(--white); border-radius:var(--radius); box-shadow:var(--shadow);
  max-width:720px; width:100%; max-height:80vh; display:flex; flex-direction:column; overflow:hidden;
}
.modal-header{
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:16px 20px; border-bottom:1px solid var(--border);
}
.modal-title{font-size:15px; font-weight:800; color:var(--ink);}
.modal-sub{font-size:11.5px; color:var(--text-sub); margin-top:2px; font-weight:400;}
.modal-close{
  border:none; background:none; font-size:16px; color:var(--text-sub); cursor:pointer;
  width:28px; height:28px; border-radius:8px; flex:none;
}
.modal-close:hover{background:var(--blue-pale); color:var(--text);}
.modal-body{overflow:auto; padding:0;}

.panel{display:none;}
.panel.active{display:block;}

.card{
  background:var(--white); border:1px solid var(--border); border-radius:var(--radius);
  box-shadow:var(--shadow); overflow:hidden;
}
.tablewrap{overflow-x:auto;}
table{width:100%; border-collapse:collapse; font-size:13px; min-width:560px;}
thead th{
  background:var(--blue-pale); color:var(--ink); font-weight:700; font-size:11.5px;
  text-align:left; padding:10px 14px; white-space:nowrap; letter-spacing:.02em;
  border-bottom:1px solid var(--blue-border); cursor:pointer; position:sticky; top:0;
}
thead th.num, td.num{text-align:right;}
thead th .arrow{opacity:.35; font-size:10px; margin-left:3px;}
thead th.sorted .arrow{opacity:1; color:var(--blue);}
tbody td{padding:9px 14px; border-bottom:1px solid var(--border); white-space:nowrap;}
tbody tr:last-child td{border-bottom:none;}
tbody tr:hover{background:var(--blue-pale);}
tbody tr.direct{background:var(--warn-bg);}
tbody tr.direct:hover{background:var(--warn-bg);}
td.rank{color:var(--text-sub); font-weight:700; width:40px;}
td.name{font-weight:600; color:var(--text);}
td.company{color:var(--text-sub);}
.pill{
  display:inline-block; padding:2px 9px; border-radius:999px; font-size:11px; font-weight:700;
}
.pill.good{background:var(--success-bg); color:var(--success);}
.pill.mid{background:var(--warn-bg); color:var(--warn);}
.pill.low{background:var(--danger-bg); color:var(--danger);}
.pill.flat{background:var(--border); color:var(--text-sub);}
.pill.candidate{background:transparent; color:var(--warn); border:1px dashed var(--warn);}
.pill.interview{background:transparent; color:var(--blue); border:1px dashed var(--blue);}
.pill.mismatch{background:var(--danger-bg); color:var(--danger); border:1px solid var(--danger);}
.pill.attendance-abandoned{background:var(--danger-bg); color:var(--danger); border:1px solid var(--danger);}
.pill.attendance-noclock{background:var(--border); color:var(--text-sub);}
.pill.attendance-ok{background:var(--success-bg); color:var(--success);}
.attfilter{
  font-family:inherit; font-size:12.5px; padding:6px 10px; border-radius:8px;
  border:1px solid var(--border); background:var(--white); color:var(--text); cursor:pointer;
}
.attfilter-bar{display:flex; align-items:center; gap:8px; margin-bottom:10px; font-size:12px; color:var(--text-sub);}
.reason-text{font-size:10.5px; color:var(--text-sub); margin-top:3px; max-width:230px; white-space:normal; line-height:1.4;}
.day-picker{
  font-family:inherit; font-size:12.5px; padding:6px 10px; border-radius:999px;
  border:1px solid var(--border); background:var(--white); color:var(--text); cursor:pointer;
}
.delta-up{color:var(--success); font-weight:700;}
.delta-down{color:var(--danger); font-weight:700;}
.hide-diff .diffcol{display:none;}
.diffToggle{display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-sub); cursor:pointer; user-select:none; margin-left:auto; white-space:nowrap; flex:none;}
.diffToggle input{cursor:pointer;}
.hide-target .targetcol{display:none;}

.topic-filters{display:flex; gap:10px; margin-bottom:14px; flex-wrap:wrap;}
.topic-filters select{
  font-family:inherit; font-size:12.5px; padding:6px 10px; border-radius:8px;
  border:1px solid var(--border); background:var(--white); color:var(--text);
}
.topic-card{
  background:var(--white); border:1px solid var(--border); border-radius:var(--radius-sm);
  padding:14px 16px; margin-bottom:10px;
}
.topic-card .topic-head{display:flex; justify-content:space-between; gap:10px; font-size:11.5px; color:var(--text-sub); margin-bottom:6px; flex-wrap:wrap;}
.topic-card .topic-head b{color:var(--text);}
.topic-card .topic-kind{
  display:inline-block; padding:1px 8px; border-radius:999px; font-size:10.5px; font-weight:700;
  background:var(--blue-pale); color:var(--blue);
}
.topic-card .topic-text{font-size:13px; line-height:1.7; white-space:pre-wrap; color:var(--text);}
.topic-card .topic-text.clamped{max-height:4.8em; overflow:hidden; position:relative; cursor:pointer;}
.topic-card .topic-text.clamped::after{
  content:'…続きを読む'; position:absolute; bottom:0; right:0; background:var(--white);
  color:var(--blue); font-size:11.5px; padding-left:6px;
}
.topic-card .topic-foot{display:flex; justify-content:space-between; margin-top:8px; font-size:11.5px;}
.topic-card .topic-foot a{color:var(--blue); text-decoration:none; font-weight:700;}
.topic-card .topic-foot a:hover{text-decoration:underline;}
.topic-empty{text-align:center; color:var(--text-sub); font-size:13px; padding:40px 0;}

.breakdown{display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px;}
.breakdown-item{
  background:var(--white); border:1px solid var(--border); border-radius:999px;
  padding:5px 13px; font-size:12px; color:var(--text-sub);
}
.breakdown-item b{color:var(--text); font-weight:700;}
.breakdown-item.clickable-chip{cursor:pointer; user-select:none; transition:background .12s, color .12s;}
.breakdown-item.clickable-chip:hover{background:var(--blue-pale);}
.breakdown-item.clickable-chip.active{background:var(--blue); border-color:var(--blue); color:#fff;}
.breakdown-item.clickable-chip.active b{color:#fff;}
.table-caption{font-size:12px; color:var(--text-sub); margin-bottom:8px; font-weight:600;}

.ai-summary{
  background:linear-gradient(135deg, var(--blue-pale), var(--white));
  border:1px solid var(--blue-border); border-radius:var(--radius);
  padding:16px 20px; margin-bottom:22px; box-shadow:var(--shadow);
}
.ai-summary-head{display:flex; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap;}
.ai-summary-badge{
  display:inline-flex; align-items:center; gap:5px; background:var(--blue); color:#fff;
  font-size:11px; font-weight:800; letter-spacing:.03em; padding:3px 11px; border-radius:999px;
}
.ai-summary-meta{font-size:11.5px; color:var(--text-sub);}
.ai-summary-grid{display:grid; grid-template-columns:repeat(3,1fr); gap:18px;}
@media (max-width:980px){ .ai-summary-grid{grid-template-columns:1fr;} }
.ai-summary-label{font-size:11px; font-weight:700; color:var(--blue); text-transform:uppercase; letter-spacing:.03em; margin-bottom:6px;}
.ai-summary ul{margin:0; padding-left:18px; font-size:12.5px; line-height:1.6; color:var(--text);}
.ai-summary li{margin:3px 0;}
.ai-summary-note{margin-top:12px; padding-top:10px; border-top:1px solid var(--blue-border); font-size:11px; color:var(--text-xs); line-height:1.6;}
.clickable-name{cursor:pointer; color:var(--blue); text-decoration:underline dotted; text-underline-offset:2px;}
.clickable-name:hover{color:var(--blue-light);}

.note{
  margin-top:18px; font-size:11.5px; color:var(--text-xs); line-height:1.8;
  background:var(--white); border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px 16px;
}
.note b{color:var(--text-sub);}
.footer-links{margin-top:10px; font-size:11.5px; color:var(--text-xs);}

.periodbar{display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:18px;}
.periodbar .label{font-size:11.5px; color:var(--text-sub); font-weight:600; white-space:nowrap;}
.period-switch{display:flex; flex:none; gap:2px; background:var(--slate); border:1px solid var(--border); border-radius:999px; padding:3px; max-width:100%; overflow-x:auto;}
.period-btn{
  padding:6px 16px; font-size:12.5px; font-weight:700; color:var(--text-sub); background:transparent;
  border:none; border-radius:999px; cursor:pointer; font-family:inherit; transition:background .12s, color .12s;
  white-space:nowrap; flex:none;
}
.period-btn:hover{color:var(--text);}
.period-btn.active{background:var(--blue); color:#fff;}

#alertBanner{
  display:none; margin-bottom:18px; padding:12px 16px; border-radius:var(--radius-sm);
  background:var(--warn-bg); border:1px solid var(--warn); font-size:12.5px; color:var(--text);
}
#alertBanner.show{display:block;}
#alertBanner .title{font-weight:700; color:var(--warn); margin-bottom:6px;}
#alertBanner ul{margin:0; padding-left:18px;}
#alertBanner li{margin:2px 0;}

/* ============================================================
   モバイル対応（2026-08-31追加・小宮山さん依頼）
   ============================================================ */
@media (max-width:640px){
  .wrap{padding:18px 12px 48px;}
  header.top{flex-direction:column; align-items:flex-start; gap:6px;}
  header.top h1{font-size:18px;}
  header.top .meta{text-align:left; font-size:11.5px;}
  .actionbar{flex-wrap:wrap;}
  .actionbar .csvbtn, .actionbar .printbtn{flex:1 1 auto; justify-content:center;}
  .tile{padding:12px 14px;}
  .tile .value{font-size:21px;}
  .card{padding:14px !important;}
  .modal-box{max-width:none;}
  .ai-summary-grid{grid-template-columns:1fr;}
  .bi-journey{overflow-x:auto; -webkit-overflow-scrolling:touch;}
  .companyKpiGaugeCard, #companyKpiGaugeCard{padding:14px !important;}
  table{font-size:12px;}
}
@media (max-width:420px){
  .tiles{grid-template-columns:1fr 1fr;}
  .tile .value{font-size:19px;}
}

@page{ size:A4 landscape; margin:12mm; }
@media print{
  body{ background:#fff; color:#111; }
  .tiles .sub{ display:none; }
  .periodbar{ display:none; }
  .wrap{ max-width:none; padding:0; }
  header.top{ border-bottom-color:#ccc; }
  header.top h1, .tile .value, thead th{ color:#0F1F3D !important; }
  .card, .tile{ box-shadow:none; border:1px solid #ccc; break-inside:avoid; }
  thead th{ background:#EFF4FF !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; position:static; }
  tbody tr.direct{ background:#FFFBEB !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .pill{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .tabbar{ display:none; }
  .panel{ display:none !important; }
  .panel.active{ display:block !important; }
  table{ font-size:10.5px; }
  .note{ box-shadow:none; }
}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>パートナー実績ダッシュボード</h1>
    <div class="meta">
      集計期間: <b id="periodLabel">—</b>　|　前期間比較: <b id="prevPeriodLabel">—</b>　|　最終更新: <b>__UPDATED__</b><br>
      データ出典: アポインター獲得履歴／獲得報告データ／Cyzen出勤報告／Slack(#02_sh*)（いずれも日次自動更新）
    </div>
  </header>

  <div id="aiSummaryCard" class="ai-summary" style="display:none;">
    <div class="ai-summary-head">
      <span class="ai-summary-badge">AI分析サマリー</span>
      <span class="ai-summary-meta" id="aiSummaryMeta"></span>
    </div>
    <div class="ai-summary-grid">
      <div>
        <div class="ai-summary-label">今週の重点施策</div>
        <ul id="aiSummaryFocus"></ul>
      </div>
      <div>
        <div class="ai-summary-label">重要アラート</div>
        <ul id="aiSummaryAlerts"></ul>
      </div>
      <div>
        <div class="ai-summary-label">直近アクション</div>
        <ul id="aiSummaryActions"></ul>
      </div>
    </div>
    <div class="ai-summary-note" id="aiSummaryNote"></div>
  </div>

  <div class="periodbar">
    <span class="label">表示期間</span>
    <div class="period-switch">
      <button class="period-btn" data-period="day">日次</button>
      <button class="period-btn" data-period="week" title="毎週水曜〜日曜を1タームとして集計">週次(水〜日)</button>
      <button class="period-btn active" data-period="month">月次</button>
      <button class="period-btn" data-period="custom" title="開始日〜終了日を自由入力">カスタム期間</button>
    </div>
    <select class="day-picker" id="dayPicker" style="display:none;"></select>
    <select class="day-picker" id="weekPicker" style="display:none;"></select>
    <select class="day-picker" id="monthPicker" style="display:none;"></select>
    <span id="customRangeBar" style="display:none; align-items:center; gap:6px;">
      <input type="date" id="customStart"> 〜 <input type="date" id="customEnd">
      <button class="csvbtn" id="customApplyBtn" type="button" style="padding:4px 10px;">適用</button>
    </span>
    <label class="diffToggle"><input type="checkbox" id="diffToggle" checked> 前期間比を表示</label>
    <label class="diffToggle"><input type="checkbox" id="targetColToggle" checked> 🎯目標比を表示</label>
  </div>
  <div class="note" id="customRangeNote" style="display:none; margin-top:-6px; margin-bottom:10px;">
    ⑤ カスタム期間は、当月＋前月の日次事前集計（<code>DAILY_PERIODS</code>）をブラウザ側で合算して表示しています（企業別・アポ・成約・クローザーが対象）。稼働人員数・対面率は、その期間に対応する出勤報告・スポット台帳データを取得済みの日のみ表示されます（未取得の日は空欄）。それより前の月を選んだ場合はデータが無いため空表示になります。
    <b>完工数・出退勤放置アラートは日別データを持たない最新スナップショットのため、カスタム期間を選んでも値は変わりません。</b>
    前期間比・取材候補・強化対象候補（個人）は日次データの単純合算では正確に再現できないため、この表示では「—」になります。
  </div>

  <div id="alertBanner"></div>

  <details class="card" id="shiftStatusCard" style="display:none; margin-bottom:22px; padding:14px 18px;">
    <summary style="cursor:pointer; font-weight:700; font-size:13px; color:var(--ink);">
      🗓 パートナー別シフト提出状況（<span id="shiftStatusDate">—</span>）<span id="shiftStatusSummary" style="font-weight:400; color:var(--text-sub); margin-left:8px;"></span>
    </summary>
    <div class="note" style="margin-top:10px;">
      パートナー企業が「本日稼働する」と申告したシフト提出シート（Googleスプレッドシート）と、Cyzenの実出退勤打刻を突き合わせています。表示期間ピッカーとは連動しない、常に「本日」時点の独立スナップショットです。
      <b>シフト提出だが打刻なし</b>＝申告した本人がCyzenで出勤・勤務終了のいずれの打刻もしていない人（実際に稼働していない可能性、または打刻漏れの可能性の両方が考えられます）。
    </div>
    <div class="tablewrap"><table id="t-shift-status"></table></div>
  </details>

  <details class="card" id="shodanCard" style="display:none; margin-bottom:22px; padding:14px 18px;" open>
    <summary style="cursor:pointer; font-weight:700; font-size:13px; color:var(--ink);">
      💼 商談パイプライン（Cyzen予定・<span id="shodanUpdated">—</span>時点）<span id="shodanSummary" style="font-weight:400; color:var(--text-sub); margin-left:8px;"></span>
    </summary>
    <div class="note" style="margin-top:10px;">
      Cyzen連携APIの「予定」から抽出。表示期間ピッカーとは連動しない独立スナップショットです（対象は直近2ヶ月分）。<b>確定商談の欠測率</b>＝過去日の「確定」カテゴリの予定のうち、実施結果の報告が1件も無いものの割合（仮予定・後確後はまだ実施前の可能性が高いため分母に含めていません）。
    </div>
    <div class="tiles" id="shodanTiles" style="margin-top:10px; grid-template-columns:repeat(4,1fr);"></div>
  </details>

  <div class="tiles">
    <div class="tile clickable" data-tile="apo"><div class="label">アポ獲得数</div><div class="value" id="tileApo">—<span class="unit">件</span></div><div class="sub">直販含む全社・キャンセル込み</div></div>
    <div class="tile clickable" data-tile="sei"><div class="label">成約数</div><div class="value" id="tileSei">—<span class="unit">件</span></div><div class="sub" id="tileSeiSub">—</div></div>
    <div class="tile clickable" data-tile="uri"><div class="label">売上</div><div class="value" id="tileUri">—<span class="unit">円</span></div><div class="sub">クローザー基準・契約書記載価格</div></div>
    <div class="tile" data-tile="rate"><div class="label">全社成約率</div><div class="value" id="tileRate">—<span class="unit">%</span></div><div class="sub">成約数 ÷ アポ獲得数（参考値）</div></div>
    <div class="tile clickable" data-tile="headcount"><div class="label" id="tileHeadcountLabel">稼働人員数（出勤打刻あり）</div><div class="value" id="tileHeadcount">—<span class="unit">名</span></div><div class="sub" id="tileHeadcountSub">Cyzen出勤報告・直販含む延べ社数計</div><div id="tileHeadcountPictogram"></div></div>
    <div class="tile clickable" id="tileDailyHeadcountWrap" data-tile="dailyHeadcount"><div class="label">稼働人員数・詳細（<span id="tileDailyHeadcountDate">—</span>）</div><div class="value" id="tileDailyHeadcount">—<span class="unit">名</span></div><div class="sub" id="tileDailyHeadcountSub">選択中の期間の値（出勤打刻あり基準）・クリックで個人別内訳</div></div>
    <div class="tile clickable" data-tile="apoAchievers"><div class="label">アポ獲得達成者</div><div class="value" id="tileApoAchievers">—<span class="unit">名</span></div><div class="sub">1件以上アポ獲得した人数</div></div>
    <div class="tile clickable" data-tile="seiyakuAchievers"><div class="label">成約達成者</div><div class="value" id="tileSeiyakuAchievers">—<span class="unit">名</span></div><div class="sub">アポ/クロいずれかで1件以上成約</div></div>
    <div class="tile clickable" id="tileSpotActiveWrap" data-tile="spotActive" style="display:none;"><div class="label">稼働人員数（スポット作成）</div><div class="value" id="tileSpotActive">—<span class="unit">名</span></div><div class="sub" id="tileSpotActiveSub">—</div></div>
    <div class="tile clickable" id="tileRouteActiveWrap" data-tile="routeActive" style="display:none;"><div class="label">稼働人員数（ルート自動記録あり）</div><div class="value" id="tileRouteActive">—<span class="unit">名</span></div><div class="sub" id="tileRouteActiveSub">—</div></div>
    <div class="tile clickable" id="tileResetAlertWrap" data-tile="resetAlert" style="display:none; background:var(--danger-bg);"><div class="label">要リセット（出勤放置）</div><div class="value" id="tileResetAlert" style="color:var(--danger);">—<span class="unit">名</span></div><div class="sub">要代理退勤／出勤中フラグ放置者</div></div>
    <div class="tile clickable" id="tileTaimenWrap" data-tile="taimen" style="display:none;"><div class="label">総対面数</div><div class="value" id="tileTaimen">—<span class="unit">件</span></div><div class="sub" id="tileTaimenSub">—</div></div>
    <div class="tile" id="tileTaimenRateWrap" data-tile="taimenRate" style="display:none;"><div class="label">全社対面率</div><div class="value" id="tileTaimenRate">—<span class="unit">%</span></div><div class="sub">対面数 ÷ 全スポット数（新規+再訪問問わず）</div></div>
    <div class="tile clickable" id="tileSpotTotalWrap" data-tile="spotTags" style="display:none;"><div class="label">スポット更新数</div><div class="value" id="tileSpotTotal">—<span class="unit">件</span></div><div class="sub">クリックでタグ別内訳を表示</div></div>
  </div>

  <div class="card" id="companyKpiGaugeTopCard" style="display:none; margin-bottom:22px;">
    <div style="font-size:13px; font-weight:700; margin-bottom:14px;">🎯 <span id="companyKpiGaugeTopTitle"></span> 目標に対する進捗（当期間・目標未設定の項目は表示されません）</div>
    <div class="kpi-gauge-row" id="companyKpiGaugeTopWrap"></div>
  </div>

  <div class="tabbar">
    <div class="tabs">
      <div class="tab active" data-panel="p-company"><span class="tab-ico">🏢</span><span class="tab-txt">企業別</span></div>
      <div class="tab" data-panel="p-apo"><span class="tab-ico">📇</span><span class="tab-txt">アポインター</span></div>
      <div class="tab" data-panel="p-soutiku"><span class="tab-ico">🔋</span><span class="tab-txt">創蓄アポインター</span></div>
      <div class="tab" data-panel="p-closer"><span class="tab-ico">🤝</span><span class="tab-txt">クローザー</span></div>
      <div class="tab" data-panel="p-naihan"><span class="tab-ico">🎯</span><span class="tab-txt">直販メンバー</span></div>
      <div class="tab" data-panel="p-topics"><span class="tab-ico">💬</span><span class="tab-txt">トピックス/現況(Slack)</span></div>
      <div class="tab" data-panel="p-outreach"><span class="tab-ico">🔭</span><span class="tab-txt">開拓先パートナー</span></div>
      <div class="tab" data-panel="p-route"><span class="tab-ico">🗺️</span><span class="tab-txt">行動分析</span></div>
      <div class="tab" data-panel="p-trend"><span class="tab-ico">📈</span><span class="tab-txt">傾向分析</span></div>
      <div class="tab" data-panel="p-decline"><span class="tab-ico">📉</span><span class="tab-txt">下落メンバー</span></div>
      <div class="tab" data-panel="p-exec"><span class="tab-ico">📋</span><span class="tab-txt">責任者会議</span></div>
    </div>
    <div class="actionbar">
      <button class="csvbtn" id="csvBtn" title="今表示中のタブをCSVで保存（役員会資料等への連携用）">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
        このタブをCSV出力
      </button>
      <button class="printbtn" id="printBtn" title="今表示中のタブを印刷用PDFとして保存">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
        このタブをPDF保存
      </button>
      <button class="csvbtn" id="csvAllBtn" title="全タブをまとめて1つのCSVに出力（役員会資料等への連携用）">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
        全タブCSV一括出力
      </button>
      <button class="printbtn" id="materialExportBtn" title="ダウンロードしたファイルをClaudeに渡すと資料を更新できます">
        資料作成用データを書き出す
      </button>
    </div>
  </div>
  <div class="note" style="margin-top:6px; margin-bottom:0;">「資料作成用データを書き出す」でダウンロードしたJSONファイルをClaudeに渡すと、責任者会議資料（A-1全体サマリー/A-2週次/B系直販/C系パートナー/D系エリア等）を更新できます。どちらのボタンも、カスタム期間ピッカーで選んだ期間があればそれを、無ければ現在表示中の期間を対象にします。</div>

  <div id="p-company" class="panel active">
    <div class="periodbar" style="margin-bottom:10px;">
      <span class="label">パートナー企業で絞り込み</span>
      <input type="text" id="companyScopeInput" list="companyScopeList" placeholder="会社名で検索…" style="padding:6px 10px; border:1px solid var(--border); border-radius:6px; font-family:inherit; min-width:240px;">
      <datalist id="companyScopeList"></datalist>
      <button class="csvbtn" id="companyScopeApplyBtn" type="button" style="padding:4px 10px;">この会社で表示</button>
      <button class="printbtn" id="companyScopeResetBtn" type="button" style="padding:4px 10px; display:none;">全社表示に戻す</button>
      <span id="companyScopeStatus" style="font-size:12px; color:var(--text-sub);"></span>
    </div>

    <div id="companyAllView">
      <details class="card" id="companyTargetCard" style="margin-bottom:16px; padding:14px 18px;">
        <summary style="cursor:pointer; font-weight:700; font-size:13px; color:var(--ink);">🎯 企業別目標を編集（ブラウザに保存・次回アクセス時も復元）</summary>
        <div class="note" style="margin-top:10px;">
          パートナー企業ごとの月次目標（アポ獲得数・成約数・売上・稼働人員数）を入力すると、下の企業別実績表に達成率が表示されます。実データが未回収の会社は空欄のままでOKです（表では「未設定」と表示されます）。2026/8/31時点、各社の目標値は9月分を回収中で、判明した会社から順次このフォームに入力していく運用を想定しています。<br>
          <b>保存範囲について</b>　「保存して再計算」はご利用のブラウザにのみ保存されます（他の人のブラウザや別端末には反映されません）。<b>全社共通・恒久的な値にしたい場合は「JSONで書き出す」でファイルを保存し、そのファイルをClaudeに渡して「data/company_targets.jsonを更新して」と伝えてください</b>（deploy側・skill側の両方に反映され、以後は誰が見ても・ブラウザを変えてもこの値が初期表示されます）。
        </div>
        <div class="tablewrap" style="margin-top:14px;"><table id="companyTargetForm"></table></div>
        <div style="margin-top:10px; display:flex; gap:8px; align-items:center;">
          <button class="csvbtn" id="companyTargetSaveBtn" type="button">保存して再計算</button>
          <button class="printbtn" id="companyTargetResetBtn" type="button">初期値に戻す</button>
          <button class="printbtn" id="companyTargetExportBtn" type="button">JSONで書き出す（恒久反映用）</button>
          <span id="companyTargetSavedMsg" style="font-size:12px; color:var(--success); display:none;">✓ 保存しました</span>
        </div>
      </details>
      <details class="card" style="margin-bottom:16px; padding:14px 18px;" open>
        <summary style="cursor:pointer; font-weight:700; font-size:13px; color:var(--ink);">📍 ポジション分析マトリックス（パートナー各社の立ち位置）</summary>
        <div class="note" style="margin-top:10px;">2軸でパートナー各社をプロットし、どの象限に位置するかで打ち手の方向性を見立てるための図です。点をクリックすると企業別の担当者内訳（既存のドリルダウン）が開きます。円が大きい点は株式会社Fit Founder（直販）です。</div>
        <div style="display:flex; gap:24px; flex-wrap:wrap; margin-top:14px;">
          <div style="flex:1; min-width:320px;">
            <div style="font-size:12.5px; font-weight:700; color:var(--ink); margin-bottom:6px;">稼働人員数 × アポ数（投入量→産出量）</div>
            <div id="posmxHeadcountApo"></div>
          </div>
          <div style="flex:1; min-width:320px;">
            <div style="font-size:12.5px; font-weight:700; color:var(--ink); margin-bottom:6px;">アポ数 × 成約率（アポ→成約の質）</div>
            <div id="posmxApoRate"></div>
          </div>
        </div>
      </details>
      <div class="card"><div class="tablewrap"><table id="t-company"></table></div></div>
      <div class="note" style="margin-top:10px;">企業名をクリックすると、その企業の目標進捗ゲージがページ上部に表示され、メンバー別内訳の表示に切り替わります（ダッシュボード上部のKPIタイルもその会社の値に切り替わります。他のランキングタブは全社表示のまま変わりません）。</div>
    </div>

    <div id="companyScopedView" style="display:none;">
      <div class="card" style="margin-bottom:16px;">
        <div style="font-size:12.5px; font-weight:700; color:var(--text-sub); margin-bottom:10px;">担当者別の内訳を見る指標を選んでください</div>
        <div id="companyMemberChips" style="display:flex; gap:8px; flex-wrap:wrap;"></div>
      </div>
      <div class="card" id="companyMemberTableCard" style="display:none;">
        <div class="tablewrap"><table id="t-company-scoped"></table></div>
      </div>
      <div class="note" style="margin-top:10px; display:none;" id="companyScopedNote"></div>
    </div>
  </div>
  <div id="p-apo" class="panel">
    <div class="attfilter-bar"><span>出退勤状態で絞り込み:</span><select class="attfilter" id="attFilterApo">
      <option value="">すべて表示</option>
      <option value="要対応">🚨 要対応（出勤放置・退勤漏れ）</option>
      <option value="未打刻">⚪️ 出勤打刻なし</option>
      <option value="正常">✅ 正常退勤完了</option>
      <option value="stale_today">🗓 出退勤が本日でない（Slack報告が必要）</option>
    </select><span id="attFilterApoCount"></span>
      <input type="text" class="attfilter" id="tableSearchApo" placeholder="氏名・会社名で絞り込み…" style="margin-left:12px; min-width:200px;"></div>
    <div class="card"><div class="tablewrap"><table id="t-apo"></table></div></div>
    <div class="note" style="margin-top:10px;">名前をクリックすると、その担当者の日別実績（アポ数・アポ成約・クロ成約・売上）を表示します。</div>
  </div>
  <div id="p-soutiku" class="panel">
    <div class="attfilter-bar"><span>出退勤状態で絞り込み:</span><select class="attfilter" id="attFilterSoutiku">
      <option value="">すべて表示</option>
      <option value="要対応">🚨 要対応（出勤放置・退勤漏れ）</option>
      <option value="未打刻">⚪️ 出勤打刻なし</option>
      <option value="正常">✅ 正常退勤完了</option>
      <option value="stale_today">🗓 出退勤が本日でない（Slack報告が必要）</option>
    </select><span id="attFilterSoutikuCount"></span>
      <input type="text" class="attfilter" id="tableSearchSoutiku" placeholder="氏名・会社名で絞り込み…" style="margin-left:12px; min-width:200px;"></div>
    <div class="card"><div class="tablewrap"><table id="t-soutiku"></table></div></div>
    <div class="note" style="margin-top:10px;">名前をクリックすると、その担当者の日別実績を表示します。</div>
  </div>
  <div id="p-closer" class="panel">
    <div class="attfilter-bar"><span>出退勤状態で絞り込み:</span><select class="attfilter" id="attFilterCloser">
      <option value="">すべて表示</option>
      <option value="要対応">🚨 要対応（出勤放置・退勤漏れ）</option>
      <option value="未打刻">⚪️ 出勤打刻なし</option>
      <option value="正常">✅ 正常退勤完了</option>
      <option value="stale_today">🗓 出退勤が本日でない（Slack報告が必要）</option>
    </select><span id="attFilterCloserCount"></span>
      <input type="text" class="attfilter" id="tableSearchCloser" placeholder="氏名・会社名で絞り込み…" style="margin-left:12px; min-width:200px;"></div>
    <div class="card"><div class="tablewrap"><table id="t-closer"></table></div></div>
    <div class="note" style="margin-top:10px;">名前をクリックすると、その担当者の日別実績を表示します。クローザー個人の「アポ数」はデータ上追跡していない（アポはアポインター側の実績としてのみ集計）ため、このタブに「アポ→成約率」列はありません。</div>
  </div>
  <div id="p-naihan" class="panel">
    <div class="note" style="margin-bottom:14px;">直販メンバー（株式会社Fit Founder）に絞った実績です。表示期間（日次/週次/月次）は画面上部のピッカーと連動します。会社の特定は他のタブと同じ会社名解決ロジック（Cyzenユーザーマスタ等）によるため、固定の名簿は使っていません（メンバーの入退社があっても自動で追従します）。</div>
    <div class="tiles" id="naihanTiles" style="margin-bottom:16px;"></div>
    <div class="table-caption">メンバー別実績</div>
    <div class="card"><div class="tablewrap"><table id="t-naihan"></table></div></div>
    <div class="note" style="margin-top:10px;">
      <b>アポ数（後確通過）</b>＝総獲得数−キャンセル数。<b>成約数（アポ側/クロ側）</b>は他タブと同じ「※新獲得報告データ」由来（直販は自社アポ＝アポインター・クローザーが同一人物のケースを含みます）。<b>クローザー商談数</b>＝Cyzen報告書（報告書=「クローザー：獲得（成約）」「クローザー：提案中」「クローザー：敗戦」）の報告日ベース件数合計（Cyzen報告書基準・Slackチャンネル内報告での集計とは別基準で、両者は一致しない場合があります）。<b>成約率（商談数ベース）</b>＝成約数（クロ側）÷クローザー商談数（商談数0件の人は「—」）。<b>平均売価</b>＝クロ側の売上合計÷クロ側成約数（成約0件の人は「—」）。<br>
      <b>未実装の指標</b>　商談化数・商談化率（Cyzenに登録された予定数が必要）、クローザー商談数のSlackチャンネル内報告基準での集計は、新しいデータ取得の仕組みが必要なため未実装です。実装が決まり次第このタブに追加します。
    </div>
  </div>
  <div id="p-topics" class="panel">
    <h3 style="font-size:14px; margin:0 0 8px;">📋 川上さんの日報タイムライン（直近2週間・実データ件数分のみ表示）</h3>
    <div id="kawakamiTimeline" style="margin-bottom:20px;"></div>
    <div class="topic-filters">
      <select id="topicChannelFilter"><option value="">チャンネル: すべて</option></select>
      <select id="topicKindFilter">
        <option value="">種別: すべて</option>
        <option value="日報">日報</option>
        <option value="実績報告">実績報告</option>
        <option value="所感・分析">所感・分析</option>
        <option value="意思決定">意思決定</option>
        <option value="その他">その他</option>
      </select>
    </div>
    <div id="topicList"></div>
    <div class="note" style="margin-top:10px;">Slackの #02_sh を含む全チャンネルから抽出（表示期間と連動）。種別（日報/実績報告/所感・分析/意思決定）はキーワードによる簡易分類のため、判定が不正確な場合があります。本文は引用のみ・Slackリンクから元投稿を確認できます。</div>
  </div>

  <div id="p-outreach" class="panel">
    <div class="tiles" style="margin-bottom:16px;">
      <div class="tile"><div class="label">総候補数</div><div class="value" id="outTotal">—</div></div>
      <div class="tile"><div class="label">積極アプローチ対象</div><div class="value" id="outActive">—</div></div>
      <div class="tile"><div class="label">未コンタクト(要アクション)</div><div class="value" id="outUncontacted">—</div></div>
      <div class="tile"><div class="label">直近7日DM送信</div><div class="value" id="outDm7d">—</div></div>
      <div class="tile"><div class="label">直近7日反応更新</div><div class="value" id="outResp7d">—</div></div>
    </div>
    <div id="outResponseBreakdown" class="breakdown"></div>
    <div class="table-caption" id="outreachListTitle"></div>
    <div class="card"><div class="tablewrap"><table id="t-outreach"></table></div></div>
    <div class="note" style="margin-top:10px;">
      <b>データ出典</b>　partner-outreachスキルのNotion CRM（新規パートナー候補管理）のスナップショットです。他のタブ（Cyzen実績）とはデータソースが別で、表示期間（日次/週次/月次）とは連動しません。<br>
      <b>優先順位について</b>　積極アプローチ対象=YES かつ 未コンタクトの候補を、優先度(S→A→B→C)→フォロワー数→リスト追加日の古い順、で並べています（partner-outreachスキルSKILL.mdフェーズ②「開拓先パートナーの選定」と同じロジック）。存在しない指標でのスコア付けはしていません。<br>
      <b>データ更新日時</b>　<span id="outUpdated">—</span>
    </div>
  </div>

  <div id="p-route" class="panel">
    <div class="note" style="margin-bottom:14px; border-left:4px solid var(--warn); background:var(--warn-bg);">
      <b>⚠ このタブを読む前に</b>　Cyzenの「ルート自動記録」はアプリがバックグラウンドで位置情報を取得できている時だけ打刻されます。<b>打刻が少ない・移動範囲が狭い＝サボっている、とは限りません</b>（GPS権限オフ・アプリ終了・電波状況・出勤/退勤の打刻漏れなどでも同様に少なくなります）。逆に打刻が多くても訪問件数やアポ獲得に結びついていない担当者もいます。実移動の正確な軌跡ではなく、<b>あくまで参考情報</b>として、成果（アポ獲得・成約）の良い担当者の動き方のパターンを探る目的で使ってください。
    </div>
    <div class="tiles" style="margin-bottom:16px;">
      <div class="tile"><div class="label">選択日の稼働人数</div><div class="value" id="routeDayUsers">—</div><div class="sub">ルート自動記録が1件以上ある人数</div></div>
      <div class="tile"><div class="label">選択日のルート打刻数</div><div class="value" id="routeDayTotal">—</div></div>
      <div class="tile"><div class="label">選択日の訪問イベント数</div><div class="value" id="routeDayVisits">—</div><div class="sub">訪問（アポインター）+訪問結果（クローザー）</div></div>
      <div class="tile"><div class="label">選択日のアポ獲得数</div><div class="value" id="routeDayApo">—</div></div>
    </div>
    <div class="card" style="padding:14px 18px; margin-bottom:16px;">
      <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
        <div>
          <label style="font-size:12px; color:var(--text-sub); display:block; margin-bottom:4px;">日付</label>
          <select id="routeDaySelect" style="padding:6px 10px; border-radius:6px; border:1px solid var(--blue-border);"></select>
        </div>
        <div>
          <label style="font-size:12px; color:var(--text-sub); display:block; margin-bottom:4px;">担当者</label>
          <select id="routePersonSelect" style="padding:6px 10px; border-radius:6px; border:1px solid var(--blue-border); min-width:220px;"></select>
        </div>
        <div id="routePersonMeta" style="font-size:12px; color:var(--text-sub);"></div>
      </div>
      <div id="routeMapWrap" style="margin-top:14px; border:1px solid var(--blue-border); border-radius:10px; overflow:hidden; background:#F8FAFF;">
        <svg id="routeMap" viewBox="0 0 900 560" style="width:100%; height:auto; display:block;"></svg>
      </div>
      <div class="note" style="margin-top:10px;">地図は実際の地図画像ではなく、GPS座標を選択日の移動範囲に合わせて拡大したイメージ図です（外部の地図タイルを読み込まない自己完結型ダッシュボードのため）。淡い線＝ルート自動記録を結んだ移動の目安、丸マーカー＝訪問等の業務イベント（クリックで詳細）、緑＝当日最初の打刻、赤＝当日最後の打刻。</div>
    </div>
    <div class="table-caption">選択日の担当者別サマリー（行クリックで上の地図に反映）</div>
    <div class="card"><div class="tablewrap"><table id="t-route"></table></div></div>
  </div>

  <div id="p-trend" class="panel">
    <div class="note" style="margin-bottom:14px;">このタブは表示期間（日次/週次/月次）とは連動しない独立集計です（開拓先パートナー・行動分析タブと同じ設計）。件数がまだ少ない切り口もあるため、断定的な結論ではなく「次に何を試すか」の仮説出しの材料として使ってください。</div>

    <div class="table-caption">① 月初の土日（最初の土曜日曜2日間）実績の月次比較</div>
    <div class="card"><div class="tablewrap"><table id="t-trend-weekend"></table></div></div>
    <div class="note" id="trendWeekendNote" style="margin-top:10px;">獲得報告データのシートが2026/07/01より前を持たないため、それ以前の月は成約数・売上を「—」表示にしています（実績ゼロではなく比較対象データが無いだけです）。</div>

    <div class="table-caption" style="margin-top:24px;">② エリア×時間帯のアポ獲得傾向（行動履歴の実訪問イベントより）</div>
    <div id="trendAreaMeta" class="note" style="margin-bottom:10px;"></div>
    <div class="card"><div class="tablewrap"><table id="t-trend-area"></table></div></div>
    <div class="note" style="margin-top:10px;">セルは「訪問件数（うちアポ獲得件数・アポ率）」。アポ率が空欄のセルは訪問イベント自体が0件です。母数が小さいセル（訪問1〜2件など）は参考程度に見てください。集計対象は蓄積済みの行動履歴データ全期間です。</div>

    <div class="table-caption" style="margin-top:24px;">③ 好成績者の動き方傾向</div>
    <div id="trendTopWrap"></div>

    <div class="table-caption" style="margin-top:24px;">④ 研修効果モニタリング</div>
    <div id="trainingEffectWrap"></div>

    <div class="table-caption" style="margin-top:24px;">⑤ 在籍期間別の成績分析（2026-08-31追加）</div>
    <div class="note" style="margin-bottom:10px;">
      Cyzen連携APIのアカウント作成日を「登録日」の代理指標として、新人（登録から<span id="tenureNewDays">—</span>日以内）／中堅（〜<span id="tenureMidDays">—</span>日）／ベテラン（それ以上）の3区分で当月実績を比較します。
      <b>クローザー昇格日に相当するデータはCyzen側に存在しないため未搭載</b>です（アポインター・クローザーどちらの実績も、同じ「Cyzenアカウント登録日」基準の区分で見ています）。中堅/ベテランの境界（1年）は暫定値です。
    </div>
    <div id="tenureAnalysisWrap"></div>

    <div class="note" style="margin-top:24px; border-left:4px solid var(--warn); background:var(--warn-bg);">
      <b>⚠ 天気・住宅密集度との相関分析について</b>　外部データ（気象・人口密度統計）との組み合わせ分析は現時点では未実装です。実装する場合はClaude Codeが日次更新時に外部データを取得して埋め込む形になります（このダッシュボード自体は外部通信をしない自己完結型のため）。着手が決まり次第このタブに追加します。
    </div>
  </div>

  <div id="p-decline" class="panel">
    <div class="note" id="declineMeta" style="margin-bottom:14px;">このタブは表示期間（日次/週次/月次）とは連動しない独立集計です（開拓先パートナー・行動分析・傾向分析タブと同じ設計）。日次のダッシュボード更新のたびに自動で再検知されます。</div>

    <div id="declineRoleFilter" style="margin-bottom:14px; display:flex; gap:8px; flex-wrap:wrap;"></div>

    <div class="tiles" id="declineTiles" style="margin-bottom:16px;"></div>

    <div class="table-caption">会社別内訳</div>
    <div id="declineChart" style="margin-bottom:20px;"></div>

    <div class="table-caption">対象者一覧</div>
    <div class="note" style="margin-bottom:10px;">列ヘッダーをクリックすると並べ替えできます。「直近週稼働」が○の人は寺子屋招集の対象候補、×の人はCyzen上で活動が止まっているため先に本人確認が必要です。</div>
    <div class="card"><div class="tablewrap"><table id="t-decline"></table></div></div>
  </div>

  <div id="p-exec" class="panel">
    <details class="card" style="margin-bottom:16px; padding:14px 18px;">
      <summary style="cursor:pointer; font-weight:700; font-size:13px; color:var(--ink);">🎯 月間目標を編集（ブラウザに保存・次回アクセス時も復元）</summary>
      <div id="targetForm" style="margin-top:14px;"></div>
      <div style="margin-top:10px; display:flex; gap:8px; align-items:center;">
        <button class="csvbtn" id="targetSaveBtn" type="button">保存して再計算</button>
        <button class="printbtn" id="targetResetBtn" type="button">初期値に戻す</button>
        <span id="targetSavedMsg" style="font-size:12px; color:var(--success); display:none;">✓ 保存しました</span>
      </div>
    </details>

    <div class="note" style="margin-bottom:16px;">
      <b>このタブについて</b>　責任者会議（他部門共有）資料フォーマットに合わせ、主要KPI・完工数・エリア目標・ファネル分析を表示します。目標値は上のフォームで編集でき、進捗率・オンペース比・着地予測はすべてブラウザ側でその場で再計算されます（既定は「今月」。上部の日次/週次/月次切替とは独立して、下の「集計期間」で任意の開始日〜終了日を選べます）。主要KPI（成約・完工・売上・稼働人員数）はCyzen/実データに基づき色判定（緑=オンペース比100%以上／黄=85〜100%／赤=85%未満）、参考KPI（アポ・商談）はグレー表示（速報値のため判定なし）です。
    </div>

    <div class="periodbar" style="margin-bottom:6px;">
      <span class="label">集計期間</span>
      <span style="display:inline-flex; align-items:center; gap:6px;">
        <input type="date" id="execCustomStart"> 〜 <input type="date" id="execCustomEnd">
        <button class="csvbtn" id="execCustomApplyBtn" type="button" style="padding:4px 10px;">適用</button>
        <button class="printbtn" id="execCustomResetBtn" type="button" style="padding:4px 10px;">今月に戻す</button>
      </span>
      <span id="execCustomRangeLabel" style="font-size:12px; color:var(--text-sub);"></span>
    </div>
    <div class="note" style="margin-top:-6px; margin-bottom:16px;">
      集計期間は当月＋前月の日次事前集計（<code>DAILY_PERIODS</code>）を合算して再計算します。完工数は当月＋前月分の日次内訳に対応（それより前の期間は「—」表示）、エリア別実績・出退勤放置アラートは最新スナップショットのため引き続き期間に関わらず同じ値です。月をまたぐ期間を選んだ場合、進捗率（オンペース比）は終了日が属する月の日数を基準に計算するため参考値としてご覧ください。前期間比・取材候補／強化対象候補（個人）は日次データの単純合算では正確に再現できないためこのタブでは対象外です。
    </div>

    <h3 style="font-size:14px; margin:0 0 8px;">① 全体サマリー（目標→実績）</h3>
    <div class="card" style="margin-bottom:12px;"><div class="tablewrap"><table id="t-exec-summary"></table></div></div>
    <div class="card" style="margin-bottom:20px; padding:14px 18px;">
      <div style="font-size:13px; font-weight:700; margin-bottom:8px;">稼働人員数（目標<span id="hcRateTarget"></span>名を稼働率100%とした場合・集計方法別）</div>
      <div class="tablewrap"><table id="t-exec-hcrate"></table></div>
      <div class="note" style="margin-top:8px;">稼働人員数はアポ数・売上のように月内で積み上がり続ける値ではなく「その期間に1回でも稼働した人数（重複排除）」のため、経過日数で目標を按分する「オンペース比」を当てはめると実態と合いません（月初の数日でほぼ全員分が出揃うため）。ここでは目標人数を稼働率100%の基準とし、前日・前週・前月同日数の同条件と比較した推移のみで判断します。<br>
      <b>出勤打刻あり</b>＝Cyzenで明示的に「出勤」ボタンを押した人（押し忘れがあり最も過小カウントになりやすい）。<b>スポット作成あり</b>＝訪問先レコードを1件でも作成した人（実働に近い）。<b>ルート自動記録あり</b>＝アプリがバックグラウンドGPSを記録した人（出勤ボタン不要のため最も緩い基準）。3指標は独立集計のため合算や単純比較はできません（詳しくはSKILL.md参照）。</div>
    </div>

    <h3 style="font-size:14px; margin:0 0 8px;">② 週次サマリー（直近4週間推移）</h3>
    <div class="card" style="margin-bottom:10px;"><div class="tablewrap"><table id="t-exec-weekly"></table></div></div>
    <div id="kawakamiWeeklyCard" style="margin-bottom:20px;"></div>

    <h3 style="font-size:14px; margin:0 0 8px;">③ 月末着地予測</h3>
    <div class="tiles" id="execForecastTiles" style="margin-bottom:20px;"></div>

    <h3 style="font-size:14px; margin:0 0 8px;">④ 月内推移グラフ（成約数・完工数 日次累積）</h3>
    <div class="card" style="margin-bottom:20px; padding:16px;"><div id="execTrendChart"></div></div>

    <h3 style="font-size:14px; margin:0 0 8px;">⑤ KPIファネル（週次の転換率推移: アポ→商談→成約）</h3>
    <div class="card" style="margin-bottom:12px; padding:14px 18px;" id="execFunnelWeeklyTrend"></div>
    <div class="card" style="margin-bottom:20px;"><div class="tablewrap"><table id="t-exec-funnelweekly"></table></div></div>

    <h3 style="font-size:14px; margin:0 0 8px;">⑥ エリア別 目標×実績</h3>
    <div class="card" style="margin-bottom:20px;"><div class="tablewrap"><table id="t-exec-area"></table></div></div>
    <div class="note" style="margin-bottom:20px;">
      本ダッシュボード（パートナー実績集計）は会社別データのみを保持しエリア別の実績内訳データソースを持たないため、実績列は現時点では表示できません（目標値のみ表示）。エリア別の実績は本体Cyzenダッシュボード（dashboard.html／エリア比較ビュー）を参照してください。
    </div>

    <h3 style="font-size:14px; margin:0 0 8px;">⑦ KGI要因分析（ファネル比較: 目標転換率 vs 実績転換率）</h3>
    <div class="card" style="margin-bottom:12px; padding:20px 22px 8px;" id="execFunnelDiagram"></div>
    <div class="card" style="margin-bottom:20px;"><div class="tablewrap"><table id="t-exec-funnelcompare"></table></div></div>

    <h3 style="font-size:14px; margin:0 0 8px;">⑧ 曜日別×時間帯別ヒートマップ（アポ獲得件数）</h3>
    <div class="card" style="margin-bottom:20px; padding:16px;"><div id="execHeatmap"></div></div>

    <h3 style="font-size:14px; margin:0 0 8px;">⑨ 課題×打ち手（AI分析サマリー欄）</h3>
    <div class="card" style="margin-bottom:8px;"><div class="tablewrap"><table id="t-exec-gap"></table></div></div>
    <div class="note">課題の要因分析・打ち手の効果見込みは定性判断を伴うため、ここでは目標とのギャップ数値のみ機械集計しています。文章での分析は data/ai_summary.json（AI分析サマリー）または手動での追記を想定した器です。</div>
  </div>

  <div class="note">
    <b>集計方法</b>　アポ獲得数=「アポインター獲得履歴」の獲得日ベース行数（キャンセル含む）。成約数・売上=「獲得報告データ」のタイムスタンプ日ベース（アポインター名／クローザー名それぞれの所属会社に集計）。稼働人員数=Cyzen出勤報告（対象期間内に1回でも出勤打刻をした人数、同日複数回打刻は1名として重複排除・行動履歴の実移動確認は未実施の簡易集計）。会社名はCyzenユーザーマスタを一次ソースに解決。直販（株式会社Fit Founder）を含む全社版。<br>
    <b>達成者数について</b>　アポ達成者数=期間内に1件以上アポを獲得した人数（重複なし）。成約達成者数=アポインター視点・クローザー視点いずれかで1件以上成約した人数（重複なし・和集合）。稼働人員数（Cyzen出勤打刻）より達成者数の方が多くなるのは通常です——2026-07-28に実データで確認したところ、当月アポ獲得達成者のうち約4割（16社に分散、直販含む）がCyzenの「出勤」打刻を一度もしていませんでした。つまり稼働人員数はCyzen打刻ベースの過小カウントで、実際の稼働人数把握には達成者数の方が実態に近いと考えられます。<br>
    <b>期間切替について</b>　日次＝プルダウンで選んだ任意の日（当月1日〜本日の範囲・既定は本日）、週次＝直近の水曜日〜本日を1タームとした集計（水〜日の実行タームに合わせたもの）、月次＝今月1日〜本日、のそれぞれ期間内累計です。前期間比は、日次・月次は「集計期間と同じ日数の直前期間」、週次のみ「前週の同じ水〜日ターム（正確に7日前）」との比較です。<br>
    <b>強化対象の候補について</b>　役員会資料(2026/07/22)準拠で、測れる指標（アポ数・成約率の前期間比、成約率の絶対水準）だけから「強化対象」の候補理由を自動表示します。状態タグ／主因／次アクションはパートナー推進課が別途Google Sheetで手動運用する列で、自動判定を上書きするものではありません。<br>
    <b>取材候補の候補について</b>　アポインター／創蓄アポインター／クローザーの各ランキングに、成約数ランキング上位・前期間比の成長率が高い、の2点から「取材候補」を自動表示します。「稼働開始3ヶ月以内の新人」基準は入社日データが無いため未実装です（分かる範囲の指標のみで判定・断定はしません）。<br>
    <b>Slackトピックスについて</b>　#02_sh を含む全チャンネルから、日報フォーマットを最優先に、キーワードで定性的な投稿を抽出しています。種別分類は簡易ヒューリスティックのため誤分類の可能性があります。<br>
    <b>現時点の制約</b>　KINTONE契約実績（クーリングオフ・キャンセル・否決の内訳）は本ダッシュボードには未搭載（ログイン必須のためMVPでは対象外）。「成約率」はアポ獲得数を分母にした参考値で、クロージング精度を示す正味成約率ではない点に注意。<br>
    <b>更新頻度</b>　毎朝7時に自動更新（月初〜前日の実績を反映）。今すぐ最新化したい場合はClaude（チャットまたはSlack）に「ダッシュボード更新して」と伝えてください。<br>
    <b>CSV出力・PDF保存について</b>　ブラウザの許可設定によりCSVが直接保存できない場合はtxt形式で保存されます（拡張子をcsvに変更してご利用ください）。印刷ダイアログが開かない環境では、Claudeに「PDFを作って」と伝えれば同内容の正式なPDFを作成できます。
  </div>
</div>

<div class="modal-overlay" id="drillModal">
  <div class="modal-box">
    <div class="modal-header">
      <div>
        <div class="modal-title" id="drillTitle"></div>
        <div class="modal-sub" id="drillSub"></div>
      </div>
      <button class="modal-close" id="drillClose" aria-label="閉じる">✕</button>
    </div>
    <div class="modal-body"><div class="tablewrap"><table id="drillTable"></table></div></div>
  </div>
</div>

<script>
const PERIODS = __PERIODS_JSON__;
const DAILY_PERIODS = __DAILY_PERIODS_JSON__;
const WEEKLY_PERIODS = __WEEKLY_PERIODS_JSON__;
const WEEKLY_PERIOD_LIST = __WEEKLY_PERIOD_LIST_JSON__;
const MONTHLY_PERIODS = __MONTHLY_PERIODS_JSON__;
const MONTHLY_PERIOD_LIST = __MONTHLY_PERIOD_LIST_JSON__;
const CONFIG = __CONFIG_JSON__;
const ATTENDANCE_ALERT = __ATTENDANCE_ALERT_JSON__;
const SHIFT_STATUS = __SHIFT_STATUS_JSON__;
const SHODAN_PIPELINE = __SHODAN_JSON__;
const DECLINING = __DECLINING_JSON__;
// 氏名(canon)→ATTENDANCE_ALERT.records の1レコード、を引けるルックアップ（人物詳細モーダル・
// 「出退勤が本日でない」フィルタで使う）。
const ATTENDANCE_BY_NAME = new Map(
  (ATTENDANCE_ALERT && ATTENDANCE_ALERT.records || []).map(r => [normNameJs(r.name), r])
);
const SLACK_TOPICS = __SLACK_TOPICS_JSON__;
const OUTREACH = __OUTREACH_JSON__;
const ROUTE_HISTORY = __ROUTE_HISTORY_JSON__;
const TREND = __TREND_JSON__;
const AI_SUMMARY = __AI_SUMMARY_JSON__;
const COMPLETION = __COMPLETION_JSON__;
const URGENT_TARGETS = __URGENT_TARGETS_JSON__;
const TRAINING = __TRAINING_JSON__;
// 役員会（SH役職者定例）で正式決定した急落・下降ターゲット32名（2026-08-04追加）。氏名の表記ゆれを
// 吸収するため normNameJs()（Pythonのcompany_resolver.norm_name()相当）で正規化してキー化する。
const URGENT_TARGETS_BY_NAME = new Map(
  (URGENT_TARGETS.targets || []).map(t => [normNameJs(t.name), t])
);
const DOW_HOUR = __DOWHOUR_JSON__;
const TENURE = __TENURE_JSON__;
const TENURE_BY_NAME = new Map(
  Object.entries(TENURE.people || {}).map(([name, t]) => [normNameJs(name), t])
);
function tenureBucketLabel(bucket){
  return bucket === 'new' ? '🌱新人' : (bucket === 'mid' ? '中堅' : (bucket === 'veteran' ? 'ベテラン' : '—'));
}
function tenureCell(name){
  const t = TENURE_BY_NAME.get(normNameJs(name));
  if(!t) return '<span class="pill flat">不明</span>';
  return `<span title="Cyzenアカウント登録日を初稼働日の代理指標として使用">${tenureBucketLabel(t.bucket)}　${t.created_at}（${t.tenure_days}日）</span>`;
}
const COMPANY_TARGETS_DEFAULT = __COMPANY_TARGETS_JSON__;
const COMPANY_TARGETS_STORAGE_KEY = 'partnerDashboardCompanyTargets_v1';
function loadCompanyTargets(){
  let t = null;
  try{ const raw = localStorage.getItem(COMPANY_TARGETS_STORAGE_KEY); if(raw) t = JSON.parse(raw); }catch(e){}
  return Object.assign({}, COMPANY_TARGETS_DEFAULT, t);
}
function saveCompanyTargets(t){
  localStorage.setItem(COMPANY_TARGETS_STORAGE_KEY, JSON.stringify(t));
}
let COMPANY_TARGETS = loadCompanyTargets();
function targetAchieveCell(actual, target){
  if(target === null || target === undefined || target === '') return '<span class="pill flat">未設定</span>';
  const a = actual || 0;
  const rate = target > 0 ? Math.round(a/target*1000)/10 : null;
  const cls = rate === null ? 'flat' : (rate >= 100 ? 'good' : (rate >= 85 ? 'mid' : 'low'));
  return `<span class="pill ${cls}" title="実績${a} / 目標${target}">${rate===null?'—':rate+'%'}</span>`;
}
const TARGETS_DEFAULT = __TARGETS_DEFAULT_JSON__;
const TARGETS_STORAGE_KEY = 'partnerDashboardTargets_v1';
function loadTargets(){
  let t = null;
  try{ const raw = localStorage.getItem(TARGETS_STORAGE_KEY); if(raw) t = JSON.parse(raw); }catch(e){}
  const base = TARGETS_DEFAULT || {monthly:{}, area:{}, funnel_rate:{}};
  return {
    monthly: Object.assign({}, base.monthly, t && t.monthly),
    area: Object.assign({}, base.area, t && t.area),
    funnel_rate: Object.assign({}, base.funnel_rate, t && t.funnel_rate),
  };
}
function saveTargets(t){
  localStorage.setItem(TARGETS_STORAGE_KEY, JSON.stringify(t));
}
let TARGETS = loadTargets();
let CURRENT_PERIOD = 'month';
const DAILY_DATES = Object.keys(DAILY_PERIODS).sort().reverse();
let CURRENT_DAY_DATE = DAILY_DATES[0];
let CURRENT_WEEK_KEY = WEEKLY_PERIOD_LIST[WEEKLY_PERIOD_LIST.length - 1].key;
let CURRENT_MONTH_KEY = MONTHLY_PERIOD_LIST[MONTHLY_PERIOD_LIST.length - 1].key;
let CUSTOM_DATA = null; // ⑤ カスタム期間: 適用ボタンが押されるまではnull（月次にフォールバック）
// 企業別タブの会社スコープ（2026-08-04追加）: null=全社、会社名文字列=その会社に絞り込み中。
// 影響範囲は企業別タブの表示とダッシュボード上部のKPIタイルのみ（他のランキングタブは全社表示のまま）。
let COMPANY_SCOPE = null;

function currentData(){
  if(CURRENT_PERIOD === 'day') return DAILY_PERIODS[CURRENT_DAY_DATE];
  if(CURRENT_PERIOD === 'week') return WEEKLY_PERIODS[CURRENT_WEEK_KEY];
  if(CURRENT_PERIOD === 'custom') return CUSTOM_DATA || PERIODS.month;
  if(CURRENT_PERIOD === 'month') return MONTHLY_PERIODS[CURRENT_MONTH_KEY];
  return PERIODS[CURRENT_PERIOD];
}

// ⑤ カスタム期間: DAILY_PERIODS（当月＋前月・DAILY_LOOKBACK_MONTHS分の日次事前集計）をブラウザ側で合算する。
// 完工数・出退勤放置アラートは日別データを持たない最新スナップショットのため合算せず、
// alert関連の列（要対応/未打刻/正常・スポット作成数・最終出退勤）は「その期間に含まれる最新日の値」を
// そのまま使う（元々日付非依存の同じスナップショット値のため、合算しても矛盾は生じない）。
// 前期間比・個人の取材候補/強化対象候補は日次の単純合算からは正確に再現できないため空にする。
function buildCustomRangeData(startYMD, endYMD){
  const start = startYMD.replaceAll('-', '/');
  const end = endYMD.replaceAll('-', '/');
  const dates = Object.keys(DAILY_PERIODS).filter(d => d >= start && d <= end).sort();
  if(!dates.length) return null;

  const companyMap = new Map();
  const apoMap = new Map();
  const closerMap = new Map();
  const soutikuNames = new Set();
  const headcountByCompany = new Map();
  const totalHeadcountNames = new Set();
  const nameToCompany = new Map();
  let n_closing_in_period = 0;
  let visitsAvailable = false;
  const visitsTotal = {total_spots:0, new_visit_count:0, revisit_count:0, taimen_count:0, taimen_new_count:0, taimen_revisit_count:0};

  const ensureCompany = (c) => {
    if(!companyMap.has(c.company)){
      companyMap.set(c.company, {
        company: c.company, apo_kakutoku: 0, apo_seiyaku: 0, clo_seiyaku: 0, uriage: 0,
        headcount: null, apo_achiever_count: 0, seiyaku_achiever_count: 0,
        status_tag: c.status_tag, cause: c.cause, next_action: c.next_action,
        attendance_alert_needsaction: c.attendance_alert_needsaction,
        attendance_alert_noclockin: c.attendance_alert_noclockin, attendance_alert_ok: c.attendance_alert_ok,
        rank: 0, rank_change: null, delta_apo_kakutoku: null, delta_apo_pct: null,
        delta_clo_seiyaku: null, delta_clo_pct: null, delta_uriage: null, delta_uriage_pct: null, delta_rate: null,
        suggested_reasons: [],
      });
    }
    return companyMap.get(c.company);
  };

  dates.forEach(date => {
    const dp = DAILY_PERIODS[date];
    n_closing_in_period += dp.n_closing_in_period;
    if(dp.visits){
      visitsAvailable = true;
      visitsTotal.total_spots += dp.visits.total_spots;
      visitsTotal.new_visit_count += dp.visits.new_visit_count;
      visitsTotal.revisit_count += dp.visits.revisit_count;
      visitsTotal.taimen_count += dp.visits.taimen_count;
      visitsTotal.taimen_new_count += dp.visits.taimen_new_count;
      visitsTotal.taimen_revisit_count += dp.visits.taimen_revisit_count;
    }
    dp.companies.forEach(c => {
      const acc = ensureCompany(c);
      acc.apo_kakutoku += c.apo_kakutoku;
      acc.apo_seiyaku += c.apo_seiyaku;
      acc.clo_seiyaku += c.clo_seiyaku;
      acc.uriage += c.uriage;
    });
    (dp.attendance_person_rows || []).forEach(r => {
      const [name, company] = r;
      totalHeadcountNames.add(name);
      if(company) nameToCompany.set(name, company);
      if(!headcountByCompany.has(company)) headcountByCompany.set(company, new Set());
      headcountByCompany.get(company).add(name);
    });
    dp.apo_ranking.forEach(r => {
      const name = r[1];
      if(!apoMap.has(name)) apoMap.set(name, {name, company: r[2], apo_seiyaku: 0, apo_count: 0, spot: r[8], last_in: r[9], last_out: r[10], rec: r[11]});
      const a = apoMap.get(name);
      a.apo_seiyaku += r[3]; a.apo_count += r[4];
      a.spot = r[8]; a.last_in = r[9]; a.last_out = r[10]; a.rec = r[11];
    });
    dp.soutiku_ranking.forEach(r => soutikuNames.add(r[1]));
    dp.closer_ranking.forEach(r => {
      const name = r[1];
      if(!closerMap.has(name)) closerMap.set(name, {name, company: r[2], clo_seiyaku: 0, uriage: 0, spot: r[8], last_in: r[9], last_out: r[10], rec: r[11]});
      const c = closerMap.get(name);
      c.clo_seiyaku += r[3]; c.uriage += r[4];
      c.spot = r[8]; c.last_in = r[9]; c.last_out = r[10]; c.rec = r[11];
    });
  });

  headcountByCompany.forEach((set, company) => {
    const c = ensureCompany({company, status_tag:'', cause:'', next_action:'',
      attendance_alert_needsaction:null, attendance_alert_noclockin:null, attendance_alert_ok:null});
    c.headcount = set.size;
  });

  const apoAchieversByCo = new Map(), seiyakuAchieversByCo = new Map();
  apoMap.forEach(a => {
    if(a.apo_count > 0){ if(!apoAchieversByCo.has(a.company)) apoAchieversByCo.set(a.company, new Set()); apoAchieversByCo.get(a.company).add(a.name); }
    if(a.apo_seiyaku > 0){ if(!seiyakuAchieversByCo.has(a.company)) seiyakuAchieversByCo.set(a.company, new Set()); seiyakuAchieversByCo.get(a.company).add(a.name); }
  });
  closerMap.forEach(c => {
    if(c.clo_seiyaku > 0){ if(!seiyakuAchieversByCo.has(c.company)) seiyakuAchieversByCo.set(c.company, new Set()); seiyakuAchieversByCo.get(c.company).add(c.name); }
  });

  const companies = [...companyMap.values()];
  companies.forEach(c => {
    c.rate = c.apo_kakutoku ? Math.round(c.clo_seiyaku / c.apo_kakutoku * 1000) / 10 : null;
    c.apo_achiever_count = apoAchieversByCo.has(c.company) ? apoAchieversByCo.get(c.company).size : 0;
    c.seiyaku_achiever_count = seiyakuAchieversByCo.has(c.company) ? seiyakuAchieversByCo.get(c.company).size : 0;
  });
  companies.sort((a,b) => b.apo_kakutoku - a.apo_kakutoku);
  companies.forEach((c,i) => { c.rank = i+1; });

  const mkRanking = (map, fields) => {
    const rows = [...map.values()];
    rows.sort((a,b) => (b[fields.sortKey] - a[fields.sortKey]) || ((b.apo_count||0) - (a.apo_count||0)));
    return rows.map((r,i) => fields.toRow(r, i+1));
  };
  const apo_ranking = mkRanking(apoMap, {sortKey:'apo_seiyaku', toRow:(a,rank)=>[rank, a.name, a.company, a.apo_seiyaku, a.apo_count, [], [], false, a.spot, a.last_in, a.last_out, a.rec]});
  const soutiku_ranking = apo_ranking.filter(r => soutikuNames.has(r[1]));
  const closer_ranking = mkRanking(closerMap, {sortKey:'clo_seiyaku', toRow:(c,rank)=>[rank, c.name, c.company, c.clo_seiyaku, c.uriage, [], [], false, c.spot, c.last_in, c.last_out, c.rec]});

  const totals = {
    apo_kakutoku: companies.reduce((s,c)=>s+c.apo_kakutoku,0),
    apo_seiyaku: companies.reduce((s,c)=>s+c.apo_seiyaku,0),
    clo_seiyaku: companies.reduce((s,c)=>s+c.clo_seiyaku,0),
    uriage: companies.reduce((s,c)=>s+c.uriage,0),
    apo_achiever_count: new Set([...apoMap.values()].filter(a=>a.apo_count>0).map(a=>a.name)).size,
    seiyaku_achiever_count: new Set([
      ...[...apoMap.values()].filter(a=>a.apo_seiyaku>0).map(a=>a.name),
      ...[...closerMap.values()].filter(c=>c.clo_seiyaku>0).map(c=>c.name),
    ]).size,
  };

  const visits = visitsAvailable ? Object.assign({}, visitsTotal, {
    taimen_rate: visitsTotal.total_spots ? round1(visitsTotal.taimen_count / visitsTotal.total_spots * 100) : null,
  }) : null;

  return {
    start, end, n_closing_in_period, companies, apo_ranking, soutiku_ranking, closer_ranking,
    unresolved_apo: [], unresolved_clo: [], name_alerts: [], totals,
    attendance_person_rows: [...totalHeadcountNames].map(n=>[n, nameToCompany.get(n) || '', 1]),
    attendance_unresolved: [], total_headcount: totalHeadcountNames.size,
    prev_start: null, prev_end: null, prev_data_available: false,
    attendance_mismatch_people: null, visits,
  };
}

function yen(n){ return n.toLocaleString('ja-JP'); }
function round1(n){ return Math.round(n*10)/10; }
function pct(n){ return (n===null||n===undefined) ? '—' : n.toFixed(1)+'%'; }
function ratePill(v){
  if(v===null||v===undefined) return '<span class="pill flat">—</span>';
  const cls = v>=30 ? 'good' : v>=15 ? 'mid' : 'low';
  return `<span class="pill ${cls}">${v.toFixed(1)}%</span>`;
}
function headcountCell(v){ return (v===null||v===undefined) ? '—' : String(v); }

function rankChangeCell(v){
  if(v===null||v===undefined) return '<span class="pill flat">NEW</span>';
  if(v>0) return `<span class="delta-up">▲${v}</span>`;
  if(v<0) return `<span class="delta-down">▼${Math.abs(v)}</span>`;
  return `<span class="pill flat">→</span>`;
}
function deltaCell(v, pctV){
  if(v===null||v===undefined) return '—';
  const sign = v>0?'+':'';
  const pctTxt = (pctV===null||pctV===undefined) ? '' : ` (${pctV>0?'+':''}${pctV.toFixed(1)}%)`;
  const cls = (pctV!==null && pctV!==undefined) ? (pctV<=CONFIG.diff_drop_pct?'delta-down':pctV>=CONFIG.diff_rise_pct?'delta-up':'') : '';
  return `<span class="${cls}">${sign}${v.toLocaleString('ja-JP')}${pctTxt}</span>`;
}
function deltaRateCell(v){
  if(v===null||v===undefined) return '—';
  const sign = v>0?'+':'';
  const cls = v<=CONFIG.rate_drop_pt ? 'delta-down' : v>=Math.abs(CONFIG.rate_drop_pt) ? 'delta-up' : '';
  return `<span class="${cls}">${sign}${v.toFixed(1)}pt</span>`;
}
const STATUS_PILL_CLASS = {'強化対象':'mid','要テコ入れ':'low','安定':'good','要フォロー':'mid','取材候補':'flat'};
function statusCell(c){
  if(c.status_tag){
    const cls = STATUS_PILL_CLASS[c.status_tag] || 'flat';
    return `<span class="pill ${cls}">${c.status_tag}</span>`;
  }
  if(c.suggested_reasons && c.suggested_reasons.length){
    return `<span class="pill candidate">強化対象(候補)</span><div class="reason-text">${escapeHtml(c.suggested_reasons.join(' / '))}</div>`;
  }
  return '<span class="pill flat">—</span>';
}
function interviewCell(reasons){
  if(!reasons || !reasons.length) return '<span class="pill flat">—</span>';
  return `<span class="pill interview">取材候補</span><div class="reason-text">${escapeHtml(reasons.join(' / '))}</div>`;
}
function reinforcementCell(reasons){
  if(!reasons || !reasons.length) return '<span class="pill flat">—</span>';
  return `<span class="pill candidate">強化対象(候補)</span><div class="reason-text">${escapeHtml(reasons.join(' / '))}</div>`;
}
// ============================================================
// BIチャート部品（2026-08-11追加・BIダッシュボード化フェーズ0）
// 外部ライブラリ非依存（Claude ArtifactのCSP制約のため）。各関数はデータ→SVG/HTML文字列を返す純粋関数。
// 色は既存のCSSデザイントークン（--success/--warn/--danger等）を再利用し、既存のratePill等と統一する。
// 詳細は .claude/skills/weekly-partner-ranking/BIダッシュボード化_仕様書.md 参照。
// ============================================================

// DAILY_PERIODSから直近N日分の値を日付昇順で取り出す（フェーズ2: KPIタイルのスパークライン用）。
// getterは DAILY_PERIODS[date] を受け取り数値を返す関数。日付キーはYYYY/MM/DD形式のため文字列ソートで昇順になる。
function dailyTrendSeries(getter, n=14){
  const dates = Object.keys(DAILY_PERIODS).sort().slice(-n);
  return dates.map(dt=>{
    try { const v = getter(DAILY_PERIODS[dt]); return (v===undefined) ? null : v; }
    catch(e){ return null; }
  });
}
// スパークライン: KPIカード脇の推移ミニグラフ
function sparkline(values, opts={}){
  const w = opts.width || 88, h = opts.height || 26, pad = 2;
  const vals = (values||[]).filter(v=>v!==null && v!==undefined);
  if(vals.length < 2) return `<svg width="${w}" height="${h}"></svg>`;
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = (max - min) || 1;
  const stepX = (w - 2*pad) / (vals.length - 1);
  const yOf = v => h - pad - ((v - min) / range) * (h - 2*pad);
  const pts = vals.map((v,i)=>`${(pad + i*stepX).toFixed(1)},${yOf(v).toFixed(1)}`);
  const color = opts.color || 'var(--blue)';
  const lastX = pad + (vals.length-1)*stepX, lastY = yOf(vals[vals.length-1]);
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block; overflow:visible;">
    <polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="2.3" fill="${color}"/>
  </svg>`;
}

// バレットチャート: 実績値を目標値と1本の帯で比較（予実比較の省スペース表現）
// バレットチャート（2026-08-11・メインdashboard.html の showRep() 内 bar() ヘルパーに合わせて再設計）:
// 実績値を「目標に対する達成率(%)」の単一バーで表現する（旧: 実績と目標の2軸バーだったが、
// メインダッシュボードのシンプルな%塗りバー方式に統一）。
function bulletChart(actual, target, opts={}){
  const hasActual = actual !== null && actual !== undefined;
  const hasTarget = target !== null && target !== undefined;
  if(!hasActual) return `<span style="color:var(--text-xs); font-size:11px;">データなし</span>`;
  const fmt = v => opts.fmt ? opts.fmt(v) : v.toFixed(1);
  const unit = opts.unit || '';
  const pct = (hasTarget && target) ? Math.min(100, actual/target*100) : null;
  const ok = hasTarget ? actual >= target : true;
  const cls = !hasTarget ? '' : (ok ? 'success' : 'danger');
  const barW = pct===null ? 100 : pct;
  const pctColor = !hasTarget ? 'var(--text-sub)' : (ok ? 'var(--success)' : 'var(--danger)');
  return `<div style="min-width:150px;">
    <div style="display:flex; justify-content:space-between; font-size:10px; margin-bottom:3px;">
      <span style="color:var(--text-sub);">実${fmt(actual)}${unit} / 目標${hasTarget?fmt(target)+unit:'未設定'}</span>
      <span style="font-weight:700; color:${pctColor};">${pct===null?'—':pct.toFixed(0)+'%'}</span>
    </div>
    <div class="bi-progress-bar"><div class="bi-progress-fill ${cls}" style="width:${barW}%"></div></div>
  </div>`;
}

// ファネルチャート（2026-08-11・「ロードマップ風」で確定: 丸ノード＋点線の道＋各地点に実数バッジ）:
// 小宮山さんとの検討で、A案（道のりのイラスト表現）をベースにC案（数字を隠さず明示）を組み合わせる方針に確定。
// 抽象化した目安表現（ピクトグラム=B案）はこのファネルには使わず、実数をそのままバッジ表示する
// （このダッシュボードの「正確な数字をそのまま見せる」正直さの方針を優先）。
const FUNNEL_COLORS = ['#1A56DB','#2563EB','#3B82F6','#059669','#7C3AED'];
function funnelChart(stages, opts={}){
  const valid = (stages||[]).filter(s=>s.value!==null && s.value!==undefined);
  if(valid.length < 2) return `<div class="topic-empty">ファネルを描画するデータが不足しています。</div>`;
  const badBelow = opts.badBelow!==undefined ? opts.badBelow : 10;
  let html = '<div class="bi-journey">';
  valid.forEach((s,i)=>{
    const color = s.color || FUNNEL_COLORS[Math.min(i, FUNNEL_COLORS.length-1)];
    html += `<div class="bi-journey-step">
      <div class="bi-journey-node" style="background:${color};">${s.icon?escapeHtml(s.icon):''}</div>
      <div class="bi-journey-num">${s.value.toLocaleString('ja-JP')}</div>
      <div class="bi-journey-name">${escapeHtml(s.label)}</div>
    </div>`;
    if(i < valid.length-1){
      const cvr = valid[i].value ? (valid[i+1].value/valid[i].value*100) : 0;
      const bad = cvr < badBelow;
      html += `<div class="bi-journey-link">
        <div class="bi-journey-track"></div>
        <div class="bi-journey-cvr ${bad?'bad':''}">${cvr.toFixed(1)}%</div>
      </div>`;
    }
  });
  html += '</div>';
  return html;
}

// 人型ピクトグラム（2026-08-11追加・稼働人員数タイル専用）: 実数を隠さず併記した上で、
// 「実際に1人1人を数えている」指標（人数）だけに絵での量感表現を添える。
// アイコン1個＝端数を切り上げたunit人（既定10人）。数が多い場合はアイコン数を上限cap（既定12個）に丸める。
function personPictogram(count, opts={}){
  if(count===null || count===undefined || count<=0) return '';
  const unit = opts.unit || 10;
  const cap = opts.cap || 12;
  let n = Math.ceil(count/unit);
  n = Math.min(n, cap);
  const icons = '👤'.repeat(Math.max(1,n));
  const note = unit>1 ? `1人=約${unit}名` : '';
  return `<div class="bi-pictogram"><span class="bi-pictogram-icon">${icons}</span>${note?`<span class="bi-pictogram-note">${escapeHtml(note)}</span>`:''}</div>`;
}

// ヒートマップ: 2軸グリッドを角丸セル＋カラースケール＋凡例で表現（旧: セル背景色のみのプレーンテーブル）
function heatmapGrid(rowLabels, colLabels, matrix, opts={}){
  const cell = opts.cell || 27, labelW = opts.labelW || 56;
  const max = Math.max(1, ...rowLabels.flatMap(r => colLabels.map(c => (matrix[r] && matrix[r][c]) || 0)));
  const w = labelW + colLabels.length*cell + 10, headH = 20, h = headH + rowLabels.length*cell;
  const legendH = 30;
  const colorFor = v => `rgba(26,86,219,${(0.06 + Math.max(0,Math.min(1,v/max))*0.86).toFixed(2)})`;
  let svg = `<svg viewBox="0 0 ${w} ${h+legendH}" style="width:100%; max-width:${w+30}px; height:auto; font-family:inherit;">`;
  colLabels.forEach((c,ci)=>{
    svg += `<text x="${(labelW+ci*cell+cell/2).toFixed(1)}" y="12" text-anchor="middle" font-size="10" fill="var(--text-sub)">${escapeHtml(c)}</text>`;
  });
  rowLabels.forEach((r,ri)=>{
    const y = headH + ri*cell;
    svg += `<text x="${labelW-8}" y="${(y+cell/2+4).toFixed(1)}" text-anchor="end" font-size="11" font-weight="700" fill="var(--text)">${escapeHtml(r)}</text>`;
    colLabels.forEach((c,ci)=>{
      const v = (matrix[r] && matrix[r][c]) || 0;
      const x = labelW + ci*cell;
      const isHigh = v/max > 0.55;
      svg += `<rect x="${(x+1.5).toFixed(1)}" y="${(y+1.5).toFixed(1)}" width="${cell-3}" height="${cell-3}" rx="5" fill="${colorFor(v)}"/>`;
      if(v) svg += `<text x="${(x+cell/2).toFixed(1)}" y="${(y+cell/2+3.5).toFixed(1)}" text-anchor="middle" font-size="10" fill="${isHigh?'#fff':'var(--text)'}">${v}</text>`;
    });
  });
  const legendY = h + 18, legendX0 = labelW;
  svg += `<text x="${legendX0}" y="${legendY}" font-size="10" fill="var(--text-sub)">少ない</text>`;
  for(let i=0;i<12;i++){
    svg += `<rect x="${legendX0+38+i*9}" y="${legendY-9}" width="8" height="8" fill="${colorFor(max*i/11)}"/>`;
  }
  svg += `<text x="${legendX0+38+12*9+4}" y="${legendY}" font-size="10" fill="var(--text-sub)">多い</text>`;
  svg += `</svg>`;
  return svg;
}

// ポジション分析マトリックス（2026-08-11・メインdashboard.html の renderScatter()/.quad-label に合わせて再設計）:
// 象限の背景塗りをやめ、中央値の点線1本＋隅の注記ラベルのみに簡素化（メインダッシュボードの「量×質」散布図と同じ思想）。
// opts.sizeBy を渡すとバブルサイズを第3指標（p.size）でスケールする。
// points: [{name, x, y, size, highlight, tip}]。opts: {xLabel, yLabel, xMid, badCornerLabel, sizeBy, labelTopN}
function positionMatrix(points, opts={}){
  const w = opts.width || 460, h = opts.height || 300, padL = 40, padR = 18, padT = 22, padB = 32;
  const valid = (points||[]).filter(p=>p.x!==null && p.x!==undefined && p.y!==null && p.y!==undefined);
  if(!valid.length) return `<div class="topic-empty">プロットするデータがありません。</div>`;
  const xMax = opts.xMax || (Math.max(...valid.map(p=>p.x)) * 1.15) || 1;
  const yMax = opts.yMax || (Math.max(...valid.map(p=>p.y)) * 1.15) || 1;
  const xMid = opts.xMid !== undefined ? opts.xMid : median(valid.map(p=>p.x).filter(v=>v>0));
  const x0 = padL, x1 = w-padR, y0 = padT, y1 = h-padB;
  const X = v => x0 + (Math.max(0,Math.min(v,xMax))/xMax)*(x1-x0);
  const Y = v => y1 - (Math.max(0,Math.min(v,yMax))/yMax)*(y1-y0);
  const xm = X(xMid);
  const radiusFor = p => {
    if(!opts.sizeBy) return p.highlight ? 7 : 5;
    return Math.max(4, Math.min(14, Math.sqrt(Math.max(0,p.size||0)+1) * (opts.sizeScale||2.2)));
  };
  let svg = `<svg viewBox="0 0 ${w} ${h}" style="width:100%; max-width:${w}px; height:auto; overflow:visible;">`;
  for(let i=0;i<=4;i++){
    const yy = y1 - i/4*(y1-y0);
    svg += `<line x1="${x0}" y1="${yy.toFixed(1)}" x2="${x1}" y2="${yy.toFixed(1)}" stroke="#EEF2F7"/>`;
    svg += `<text x="${(x0-6).toFixed(1)}" y="${(yy+3).toFixed(1)}" font-size="9" fill="var(--text-xs)" text-anchor="end">${Math.round(yMax*i/4).toLocaleString('ja-JP')}</text>`;
  }
  if(xMid){
    svg += `<line x1="${xm.toFixed(1)}" y1="${y0}" x2="${xm.toFixed(1)}" y2="${y1}" stroke="#CBD5E1" stroke-dasharray="4,3"/>`;
  }
  svg += `<text x="${(x0+4).toFixed(1)}" y="${y0-8}" class="bi-quad-label">↑ ${escapeHtml(opts.yLabel||'')}</text>`;
  svg += `<text x="${(x1).toFixed(1)}" y="${h-6}" class="bi-quad-label" text-anchor="end">${escapeHtml(opts.xLabel||'')} →</text>`;
  if(opts.badCornerLabel){
    svg += `<text x="${(x1-4).toFixed(1)}" y="${(y1-8).toFixed(1)}" class="bi-quad-label" text-anchor="end" fill="var(--danger)">→ ${escapeHtml(opts.badCornerLabel)}</text>`;
  }
  valid.forEach(p=>{
    const cx = X(p.x), cy = Y(p.y);
    const r = radiusFor(p);
    const fill = p.highlight ? 'var(--blue)' : 'var(--blue-light)';
    svg += `<circle class="posmx-pt" data-company="${escapeHtml(p.name)}" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${r.toFixed(1)}" fill="${fill}" fill-opacity="${p.highlight?1:0.62}" stroke="#fff" stroke-width="1.2" style="cursor:pointer;"><title>${escapeHtml(p.name)}: ${escapeHtml(p.tip||'')}</title></circle>`;
  });
  const toLabel = valid.filter(p=>p.highlight);
  if(opts.labelTopN){
    valid.slice().sort((a,b)=>b.x-a.x).slice(0,opts.labelTopN).forEach(p=>{ if(!toLabel.includes(p)) toLabel.push(p); });
  }
  toLabel.forEach(p=>{
    const cx = X(p.x), cy = Y(p.y);
    svg += `<text x="${cx.toFixed(1)}" y="${(cy-radiusFor(p)-4).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="700" fill="var(--text)">${escapeHtml(p.name)}</text>`;
  });
  svg += `</svg>`;
  return svg;
}

// 円形ゲージ: 達成率をドーナツ型プログレスで表現
function gaugeRing(pctVal, opts={}){
  const size = opts.size || 56, stroke = opts.stroke || 6;
  const r = (size-stroke)/2, c = 2*Math.PI*r;
  const has = pctVal !== null && pctVal !== undefined;
  const p = Math.max(0, Math.min(100, has ? pctVal : 0));
  const color = !has ? 'var(--border)' : p>=100 ? 'var(--success)' : p>=85 ? 'var(--warn)' : 'var(--danger)';
  const offset = c*(1-p/100);
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${stroke}"/>
    <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}" stroke-linecap="round"
      transform="rotate(-90 ${size/2} ${size/2})"/>
    <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" font-size="${(size*0.24).toFixed(1)}" font-weight="800" fill="var(--ink)">${has?Math.round(p)+'%':'—'}</text>
  </svg>`;
}

// 企業別ページのKPI進捗ゲージ（2026-08-31追加・小宮山さん依頼）。実績値を大きく見せつつ、
// リングの塗り具合と色（緑=達成/黄=あと一歩/赤=遅れ）で目標に対する進捗を直感的に示す。
// gaugeRing()（%だけを表示する小型版）とは別に、実績値そのものを主役にした大型カードとして作る。
function kpiGaugeCard(label, actual, target, fmt){
  if(target === null || target === undefined || target === '') return '';
  fmt = fmt || (v => (v===null||v===undefined) ? '—' : String(v));
  const size = 132, stroke = 12;
  const r = (size-stroke)/2, c = 2*Math.PI*r;
  const rate = target > 0 ? Math.round((actual||0)/target*1000)/10 : null;
  const p = Math.max(0, Math.min(100, rate===null?0:rate));
  const color = rate===null ? 'var(--border)' : rate>=100 ? 'var(--success)' : rate>=85 ? 'var(--warn)' : 'var(--danger)';
  const offset = c*(1-p/100);
  return `<div class="kpi-gauge">
    <div class="kpi-gauge-label">${escapeHtml(label)}</div>
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--border)" stroke-width="${stroke}"/>
      <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}"
        stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}" stroke-linecap="round"
        transform="rotate(-90 ${size/2} ${size/2})"/>
      <text x="50%" y="45%" text-anchor="middle" dominant-baseline="central" font-size="19" font-weight="800" fill="var(--ink)">${fmt(actual)}</text>
      <text x="50%" y="65%" text-anchor="middle" dominant-baseline="central" font-size="12" font-weight="700" fill="${color}">${rate===null?'—':rate+'%'}</text>
    </svg>
    <div class="kpi-gauge-target">目標 ${fmt(target)}</div>
  </div>`;
}

// 役員会（SH役職者定例）で正式決定した急落・下降ターゲット32名バッジ（2026-08-04追加）。
// 上のreinforcementCell（自動判定の「候補」）とは別枠——こちらは会議で正式に決定済みの確定リストであることを
// 明示するため、ラベルも「候補」ではなく「役員会ターゲット」にしている。
function urgentTargetCell(name){
  const t = URGENT_TARGETS_BY_NAME.get(normNameJs(name));
  if(!t) return '<span class="pill flat">—</span>';
  const catCls = t.category === '急落' ? 'low' : 'mid';
  const trained = t.training_20260730_attended ? '✅7/30研修参加' : '❌7/30研修欠席';
  const prio = t.priority_followup ? '<span class="pill attendance-abandoned" style="margin-left:4px;">🚨最優先フォロー</span>' : '';
  const companyTxt = t.company_confirmed ? '' : `（会社名未確認・自動推定:${escapeHtml(t.company_auto_resolved||'—')}）`;
  return `<span class="pill ${catCls}">🎯役員会ターゲット:${t.category}(#${t.rank_in_category})</span>${prio}` +
    `<div class="reason-text">6月${t.june_apo}件→8月目標${t.august_target}件・${trained}${companyTxt}</div>`;
}
function attendanceCell(v){
  // v = {legacy: bool, rec: {attendance_status, note, alert} | null}
  const rec = v && v.rec;
  if(rec){
    const status = rec.attendance_status || '';
    if(status.indexOf('出勤放置中')>=0){
      return `<span class="pill attendance-abandoned">🚨 出勤放置中</span><div class="reason-text">${escapeHtml(rec.note||'')}</div>`;
    }
    if(status.indexOf('完全退勤漏れ')>=0){
      return `<span class="pill attendance-abandoned">🚨 完全退勤漏れ</span><div class="reason-text">1〜7月の中で一度も退勤打刻が行われていません</div>`;
    }
    if(status.indexOf('出勤打刻なし')>=0){
      return `<span class="pill attendance-noclock">⚪️ 出勤打刻なし</span><div class="reason-text">アプリでの出勤打刻履歴なし（スポット作成のみ等）</div>`;
    }
    if(status.indexOf('正常')>=0){
      return `<span class="pill attendance-ok">✅ 正常</span><div class="reason-text">退勤完了済み</div>`;
    }
    return '<span class="pill flat">—</span>';
  }
  if(v && v.legacy){
    return `<span class="pill mismatch">⚠ 出勤打刻なし</span><div class="reason-text">実績はあるが、この期間中に一度もCyzen出勤打刻がありません</div>`;
  }
  return '<span class="pill flat">データなし</span>';
}
function spotCountCell(v){
  return (v===null||v===undefined) ? '—' : String(v)+'件';
}
function lastInOutCell(v){
  if(!v || (!v.last_in && !v.last_out)) return '—';
  const inS = v.last_in || '—', outS = v.last_out || '—';
  return `<span title="${escapeHtml('出勤: '+inS+' / 退勤: '+outS)}">${escapeHtml(outS)}</span>`;
}
function attendanceAlertOf(v){
  // フィルタ用: rec.alert('要対応'/'未打刻'/'正常')を返す。recが無ければnull。
  return (v && v.rec) ? v.rec.alert : null;
}
// 人物詳細モーダル（openPersonDetail）用: ATTENDANCE_ALERT.recordsから該当者の出退勤情報・
// 報告日ズレ有無を1行のHTMLにまとめる（2026-08-10・小宮山さんの依頼＝全員の最新出退勤日時を
// 記録し、クリックで見られるようにする、に対応）。
function attendanceDetailHtml(name){
  const rec = ATTENDANCE_BY_NAME.get(normNameJs(name));
  if(!rec) return '<div style="margin-top:6px; color:var(--text-sub);">出退勤データなし（Cyzen出勤/勤務終了報告の対象期間に記録がありません）</div>';
  const alertCls = rec.alert==='要対応' ? 'attendance-abandoned' : rec.alert==='未打刻' ? 'attendance-noclock' : 'attendance-ok';
  const alertIcon = rec.alert==='要対応' ? '🚨' : rec.alert==='未打刻' ? '⚪️' : '✅';
  const stale = isStaleToday({last_in: rec.last_in, last_out: rec.last_out});
  const staleBadge = stale ? '<span class="pill mismatch" style="margin-left:6px;">🗓 本日出退勤なし</span>' : '';
  const mismatchBadge = rec.report_mismatch
    ? `<span class="pill mismatch" style="margin-left:6px;">⚠ ${escapeHtml(rec.report_kind||'報告')}提出日(${escapeHtml((rec.last_report||'').slice(0,10))})に出退勤記録なし</span>` : '';
  return `<div style="margin-top:8px; padding-top:8px; border-top:1px solid var(--border); font-size:12.5px;">
    <span class="pill ${alertCls}">${alertIcon} ${escapeHtml(rec.attendance_status||rec.alert||'—')}</span>${staleBadge}${mismatchBadge}
    <div style="margin-top:4px; color:var(--text-sub);">最新出勤: ${escapeHtml(rec.last_in||'—')}／最新退勤: ${escapeHtml(rec.last_out||'—')}${rec.note?'／'+escapeHtml(rec.note):''}</div>
  </div>`;
}
const attFilterState = {apo:'', soutiku:'', closer:''};
const tableSearchState = {apo:'', soutiku:'', closer:''};
// 出退勤の最新打刻日が「本日」でない（＝Slackで出退勤の確認・報告を促すべき）かどうかを判定する。
// lastInOut: {last_in, last_out}（'YYYY-MM-DD HH:MM:SS'形式の生文字列 or ''）。
function isStaleToday(lastInOut){
  const today = DAILY_DATES[0]; // 'YYYY/MM/DD'
  if(!today) return false;
  const todayHyphen = today.replaceAll('/','-');
  const inDate = lastInOut && lastInOut.last_in ? lastInOut.last_in.slice(0,10) : '';
  const outDate = lastInOut && lastInOut.last_out ? lastInOut.last_out.slice(0,10) : '';
  if(!inDate && !outDate) return true; // 出退勤記録が一件も無い＝当然「本日ではない」
  return inDate !== todayHyphen && outDate !== todayHyphen;
}
function searchMatches(name, company, term){
  if(!term) return true;
  const t = term.trim().toLowerCase();
  if(!t) return true;
  return (String(name||'').toLowerCase().includes(t)) || (String(company||'').toLowerCase().includes(t));
}

function renderTable(tableId, columns, rows, opts={}){
  const table = document.getElementById(tableId);
  let sortCol = opts.defaultSort ?? 0;
  let sortDir = -1;
  function draw(){
    const sorted = [...rows].sort((a,b)=>{
      const av=a[sortCol], bv=b[sortCol];
      if(typeof av === 'number' && typeof bv === 'number') return (av-bv)*sortDir;
      return String(av).localeCompare(String(bv),'ja')*sortDir;
    });
    let thead = '<thead><tr>' + columns.map((c,i)=>
      `<th class="${c.num?'num':''} ${i===sortCol?'sorted':''}" data-i="${i}">${c.label}<span class="arrow">${i===sortCol?(sortDir>0?'▲':'▼'):'▲▼'}</span></th>`
    ).join('') + '</tr></thead>';
    let tbody = '<tbody>' + sorted.map(r=>{
      const isDirect = opts.directCheck ? opts.directCheck(r) : false;
      const clickable = opts.rowClick ? 'clickable' : '';
      return `<tr class="${isDirect?'direct':''} ${clickable}">` + columns.map((c,i)=>{
        const v = r[i];
        let out = v;
        if(c.fmt) out = c.fmt(v, r);
        return `<td class="${c.num?'num':''} ${c.cls||''}">${out}</td>`;
      }).join('') + '</tr>';
    }).join('') + '</tbody>';
    table.innerHTML = thead + tbody;
    table.querySelectorAll('thead th').forEach(th=>{
      th.addEventListener('click', ()=>{
        const i = parseInt(th.dataset.i);
        if(i===sortCol) sortDir *= -1; else { sortCol=i; sortDir=-1; }
        draw();
      });
    });
    if(opts.rowClick){
      table.querySelectorAll('tbody tr').forEach((tr,i)=>{
        tr.addEventListener('click', ()=> opts.rowClick(sorted[i]));
      });
    }
  }
  draw();
}

function currentTableExport(panelId){
  const table = document.querySelector('#' + panelId + ' table');
  if(!table) return null;
  const headCells = [...table.querySelectorAll('thead th')].map(th => th.textContent.replace(/[▲▼]/g,'').trim());
  const rows = [...table.querySelectorAll('tbody tr')].map(tr =>
    [...tr.querySelectorAll('td')].map(td => td.textContent.trim())
  );
  return {header: headCells, rows};
}

function toCSV(header, rows){
  const esc = v => {
    const s = String(v ?? '');
    const needsQuote = s.includes('"') || s.includes(',') || s.includes(String.fromCharCode(10)) || s.includes(String.fromCharCode(13));
    return needsQuote ? '"' + s.replace(/"/g,'""') + '"' : s;
  };
  const lines = [header, ...rows].map(r => r.map(esc).join(','));
  const CRLF = String.fromCharCode(13) + String.fromCharCode(10);
  return '﻿' + lines.join(CRLF);
}

// ポジション分析マトリックス2種の描画（BIダッシュボード化フェーズ3・2026-08-11追加）。
// 稼働人員数×アポ数＝投入量→産出量の診断、アポ数×成約率＝アポ→成約(後工程)の質の診断。
// 対面率×アポ率のマトリックスは--spot-csvの取得がまだ安定しておらず正しい数字が取れていないため、
// データ精度が改善するまで実装を見送っている（BIダッシュボード化_仕様書.md 4.1節参照）。
function median(nums){
  const s = nums.slice().sort((a,b)=>a-b);
  if(!s.length) return 0;
  const mid = Math.floor(s.length/2);
  return s.length%2 ? s[mid] : (s[mid-1]+s[mid])/2;
}
function wirePositionMatrixClicks(elId){
  const el = document.getElementById(elId);
  if(!el) return;
  el.querySelectorAll('.posmx-pt').forEach(pt=>{
    pt.addEventListener('click', ()=> openDrilldown(pt.getAttribute('data-company')));
  });
}
function renderPositionMatrices(d){
  const companies = (d.companies||[]).filter(c=>c.apo_kakutoku>0 || c.headcount>0);
  if(!companies.length){
    ['posmxHeadcountApo','posmxApoRate'].forEach(id=>{
      const el = document.getElementById(id);
      if(el) el.innerHTML = '<div class="topic-empty">プロットする企業データがありません。</div>';
    });
    return;
  }

  // ① 稼働人員数 × アポ数
  const hcPoints = companies.map(c=>({
    name: c.company, x: c.headcount || 0, y: c.apo_kakutoku || 0,
    highlight: c.company.includes('Fit Founder'),
    tip: `稼働${c.headcount||0}名／アポ${c.apo_kakutoku||0}件`,
  }));
  const elHc = document.getElementById('posmxHeadcountApo');
  if(elHc){
    elHc.innerHTML = positionMatrix(hcPoints, {
      xLabel:'稼働人員数（名）', yLabel:'アポ数（件）',
      badCornerLabel:'人数はいるがアポが出ていない', labelTopN:4,
    });
    wirePositionMatrixClicks('posmxHeadcountApo');
  }

  // ② アポ数 × 成約率（中央値=median、bad象限の目安は既存の「強化対象」判定基準=RATE_BASELINE_PCTを参考値として点線表示はせず、隅ラベルのみで示す）
  const rtPoints = companies.filter(c=>c.apo_kakutoku>0).map(c=>({
    name: c.company, x: c.apo_kakutoku || 0, y: c.rate===null||c.rate===undefined ? 0 : c.rate,
    highlight: c.company.includes('Fit Founder'),
    tip: `アポ${c.apo_kakutoku||0}件／成約率${(c.rate||0).toFixed(1)}%`,
  }));
  const elRt = document.getElementById('posmxApoRate');
  if(elRt){
    elRt.innerHTML = positionMatrix(rtPoints, {
      xLabel:'アポ数（件）', yLabel:'成約率（%）',
      badCornerLabel:'量はあるが質が低い', labelTopN:4,
      yMax: Math.max(50, ...rtPoints.map(p=>p.y))*1.1,
    });
    wirePositionMatrixClicks('posmxApoRate');
  }
}

function renderAllTables(){
  const d = currentData();
  populateCompanyScopeList(d);
  document.getElementById('companyAllView').style.display = COMPANY_SCOPE ? 'none' : '';
  document.getElementById('companyScopedView').style.display = COMPANY_SCOPE ? '' : 'none';
  if(COMPANY_SCOPE){
    renderCompanyScopedView(d);
  } else {
  const companyByName = new Map(d.companies.map(c=>[c.company, c]));
  const ctRate = (actual, target) => (target ? Math.round((actual||0)/target*1000)/10 : null);
  renderTable('t-company', [
    {label:'順位', num:true},
    {label:'順位変動', num:true, cls:'diffcol', fmt:v=>rankChangeCell(v)},
    {label:'企業名'},
    {label:'アポ獲得数', num:true},
    {label:'アポ数Δ', num:true, cls:'diffcol', fmt:(v,r)=>deltaCell(v, companyByName.get(r[2]).delta_apo_pct)},
    {label:'目標比(アポ)', num:true, cls:'targetcol', fmt:(v,r)=>targetAchieveCell(companyByName.get(r[2]).apo_kakutoku, (COMPANY_TARGETS[r[2]]||{}).apo)},
    {label:'アポ成約', num:true},
    {label:'クロ成約', num:true},
    {label:'成約数Δ', num:true, cls:'diffcol', fmt:(v,r)=>deltaCell(v, companyByName.get(r[2]).delta_clo_pct)},
    {label:'目標比(成約)', num:true, cls:'targetcol', fmt:(v,r)=>targetAchieveCell(companyByName.get(r[2]).clo_seiyaku, (COMPANY_TARGETS[r[2]]||{}).seiyaku)},
    {label:'売上', num:true, fmt:v=>yen(v)},
    {label:'売上Δ', num:true, cls:'diffcol', fmt:(v,r)=>deltaCell(v, companyByName.get(r[2]).delta_uriage_pct)},
    {label:'目標比(売上)', num:true, cls:'targetcol', fmt:(v,r)=>targetAchieveCell(companyByName.get(r[2]).uriage, (COMPANY_TARGETS[r[2]]||{}).uriage)},
    {label:'成約率', num:true, fmt:v=>ratePill(v)},
    {label:'成約率Δ', num:true, cls:'diffcol', fmt:v=>deltaRateCell(v)},
    {label:'稼働人員数', num:true, fmt:v=>headcountCell(v)},
    {label:'目標比(稼働)', num:true, cls:'targetcol', fmt:(v,r)=>targetAchieveCell(companyByName.get(r[2]).headcount, (COMPANY_TARGETS[r[2]]||{}).chinin)},
    {label:'アポ達成者数', num:true, fmt:v=>headcountCell(v)},
    {label:'成約達成者数', num:true, fmt:v=>headcountCell(v)},
    {label:'要対応', num:true, cls:'attn-needsaction', fmt:v=>headcountCell(v)},
    {label:'未打刻', num:true, fmt:v=>headcountCell(v)},
    {label:'正常', num:true, fmt:v=>headcountCell(v)},
    {label:'状態タグ', fmt:(v,r)=>statusCell(companyByName.get(r[2]))},
    {label:'主因', cls:'diffcol'},
    {label:'次アクション', cls:'diffcol'},
  ], d.companies.map(c=>[
      c.rank, c.rank_change, c.company,
      c.apo_kakutoku, c.delta_apo_kakutoku,
      ctRate(c.apo_kakutoku, (COMPANY_TARGETS[c.company]||{}).apo),
      c.apo_seiyaku, c.clo_seiyaku, c.delta_clo_seiyaku,
      ctRate(c.clo_seiyaku, (COMPANY_TARGETS[c.company]||{}).seiyaku),
      c.uriage, c.delta_uriage,
      ctRate(c.uriage, (COMPANY_TARGETS[c.company]||{}).uriage),
      c.rate, c.delta_rate,
      c.headcount,
      ctRate(c.headcount, (COMPANY_TARGETS[c.company]||{}).chinin),
      c.apo_achiever_count, c.seiyaku_achiever_count,
      c.attendance_alert_needsaction, c.attendance_alert_noclockin, c.attendance_alert_ok,
      c.status_tag, c.cause, c.next_action,
    ]),
     {defaultSort:3, directCheck:r=>r[2].includes('Fit Founder'), rowClick:r=>openDrilldown(r[2])});
    renderPositionMatrices(d);
    renderCompanyTargetForm(d.companies.map(c=>c.company));
  }

  function attMatches(v, lastInOut, filterVal){
    if(!filterVal) return true;
    if(filterVal === 'stale_today') return isStaleToday(lastInOut);
    return attendanceAlertOf(v) === filterVal;
  }

  function visitTooltip(newRate, revisitRate){
    const f = v => (v===null||v===undefined) ? '—' : v.toFixed(1)+'%';
    return `新規対面率${f(newRate)}／再訪問対面率${f(revisitRate)}`;
  }

  const apoAll = d.apo_ranking.map(r=>[r[0], r[1], r[2], r[3], r[4], r[4]?round1(r[3]/r[4]*100):null, r[5], r[6],
    r[8], {last_in:r[9], last_out:r[10]}, {legacy:r[7], rec:r[11]},
    r[12], r[13], r[14], r[15], visitTooltip(r[16], r[17])]);
  const apoFiltered = apoAll.filter(r=>attMatches(r[10], r[9], attFilterState.apo) && searchMatches(r[1], r[2], tableSearchState.apo));
  document.getElementById('attFilterApoCount').textContent = `該当 ${apoFiltered.length}/${apoAll.length}名`;
  renderTable('t-apo', [
    {label:'順位', num:true}, {label:'名前'}, {label:'会社名', cls:'company'},
    {label:'成約数', num:true}, {label:'アポ数', num:true}, {label:'成約率', num:true, fmt:v=>ratePill(v)},
    {label:'取材候補', fmt:v=>interviewCell(v)}, {label:'強化対象', fmt:v=>reinforcementCell(v)},
    {label:'スポット作成数', num:true, fmt:v=>spotCountCell(v)}, {label:'最終出退勤', fmt:v=>lastInOutCell(v)},
    {label:'出勤打刻', fmt:v=>attendanceCell(v)},
    {label:'新規訪問数', num:true, fmt:v=>v===null||v===undefined?'—':v},
    {label:'再訪問数', num:true, fmt:v=>v===null||v===undefined?'—':v},
    {label:'対面数', num:true, fmt:v=>v===null||v===undefined?'—':v},
    {label:'対面率', num:true, fmt:(v,r)=>`<span title="${escapeHtml(r[15])}">${v===null||v===undefined?'—':v.toFixed(1)+'%'}</span>`},
    {label:'在籍', fmt:(v,r)=>tenureCell(r[1])},
    {label:'役員会ターゲット', fmt:(v,r)=>urgentTargetCell(r[1])},
  ], apoFiltered,
     {defaultSort:3, directCheck:r=>r[2].includes('Fit Founder'), rowClick:r=>openPersonDetail(r[1])});

  const soutikuAll = d.soutiku_ranking.map(r=>[r[0], r[1], r[2], r[3], r[4], r[4]?round1(r[3]/r[4]*100):null, r[5], r[6],
    r[8], {last_in:r[9], last_out:r[10]}, {legacy:r[7], rec:r[11]},
    r[12], r[13], r[14], r[15], visitTooltip(r[16], r[17])]);
  const soutikuFiltered = soutikuAll.filter(r=>attMatches(r[10], r[9], attFilterState.soutiku) && searchMatches(r[1], r[2], tableSearchState.soutiku));
  document.getElementById('attFilterSoutikuCount').textContent = `該当 ${soutikuFiltered.length}/${soutikuAll.length}名`;
  renderTable('t-soutiku', [
    {label:'順位', num:true}, {label:'名前'}, {label:'会社名', cls:'company'},
    {label:'成約数', num:true}, {label:'アポ数', num:true}, {label:'成約率', num:true, fmt:v=>ratePill(v)},
    {label:'取材候補', fmt:v=>interviewCell(v)}, {label:'強化対象', fmt:v=>reinforcementCell(v)},
    {label:'スポット作成数', num:true, fmt:v=>spotCountCell(v)}, {label:'最終出退勤', fmt:v=>lastInOutCell(v)},
    {label:'出勤打刻', fmt:v=>attendanceCell(v)},
    {label:'新規訪問数', num:true, fmt:v=>v===null||v===undefined?'—':v},
    {label:'再訪問数', num:true, fmt:v=>v===null||v===undefined?'—':v},
    {label:'対面数', num:true, fmt:v=>v===null||v===undefined?'—':v},
    {label:'対面率', num:true, fmt:(v,r)=>`<span title="${escapeHtml(r[15])}">${v===null||v===undefined?'—':v.toFixed(1)+'%'}</span>`},
    {label:'在籍', fmt:(v,r)=>tenureCell(r[1])},
    {label:'役員会ターゲット', fmt:(v,r)=>urgentTargetCell(r[1])},
  ], soutikuFiltered,
     {defaultSort:3, directCheck:r=>r[2].includes('Fit Founder'), rowClick:r=>openPersonDetail(r[1])});

  const closerAll = d.closer_ranking.map(r=>[r[0], r[1], r[2], r[3], r[4], r[5], r[6],
    r[8], {last_in:r[9], last_out:r[10]}, {legacy:r[7], rec:r[11]}, r[1]]);
  const closerFiltered = closerAll.filter(r=>attMatches(r[9], r[8], attFilterState.closer) && searchMatches(r[1], r[2], tableSearchState.closer));
  document.getElementById('attFilterCloserCount').textContent = `該当 ${closerFiltered.length}/${closerAll.length}名`;
  renderTable('t-closer', [
    {label:'順位', num:true}, {label:'名前'}, {label:'会社名', cls:'company'},
    {label:'成約数', num:true}, {label:'売上', num:true, fmt:v=>yen(v)},
    {label:'取材候補', fmt:v=>interviewCell(v)}, {label:'強化対象', fmt:v=>reinforcementCell(v)},
    {label:'スポット作成数', num:true, fmt:v=>spotCountCell(v)}, {label:'最終出退勤', fmt:v=>lastInOutCell(v)},
    {label:'出勤打刻', fmt:v=>attendanceCell(v)},
    {label:'在籍', fmt:(v,r)=>tenureCell(r[1])},
    {label:'役員会ターゲット', fmt:(v,r)=>urgentTargetCell(r[1])},
  ], closerFiltered,
     {defaultSort:3, directCheck:r=>r[2].includes('Fit Founder'), rowClick:r=>openPersonDetail(r[1])});

  renderNaihan(d);
}

function renderNaihan(d){
  const cancelMap = d.apo_cancel_by_name || {};
  const shodanMap = d.closer_shodan_by_name || {};
  const people = new Map();
  function ensure(name, co){
    if(!people.has(name)) people.set(name, {name, co,
      apoTotal:0, apoCancel:0, apoSeiyaku:0, cloSeiyaku:0, cloUriage:0, shodan:0});
    return people.get(name);
  }
  d.apo_ranking.filter(r=>r[2].includes('Fit Founder')).forEach(r=>{
    const p = ensure(r[1], r[2]);
    p.apoTotal = r[4];
    p.apoCancel = cancelMap[r[1]] || 0;
    p.apoSeiyaku = r[3];
  });
  d.closer_ranking.filter(r=>r[2].includes('Fit Founder')).forEach(r=>{
    const p = ensure(r[1], r[2]);
    p.cloSeiyaku = r[3];
    p.cloUriage = r[4];
    p.shodan = shodanMap[r[1]] || 0;
  });
  const rows = [...people.values()].map(p=>{
    const apoValid = p.apoTotal - p.apoCancel;
    const avgPrice = p.cloSeiyaku ? Math.round(p.cloUriage / p.cloSeiyaku / 1000) * 1000 : null;
    const shodanRate = p.shodan ? round1(p.cloSeiyaku / p.shodan * 100) : null;
    return [p.name, p.co, apoValid, p.apoTotal, p.apoCancel, p.apoSeiyaku, p.shodan, p.cloSeiyaku, shodanRate, p.cloUriage, avgPrice];
  }).sort((a,b)=> b[2]-a[2]);

  const totalApoValid = rows.reduce((s,r)=>s+r[2], 0);
  const totalApoSeiyaku = rows.reduce((s,r)=>s+r[5], 0);
  const totalShodan = rows.reduce((s,r)=>s+r[6], 0);
  const totalCloSeiyaku = rows.reduce((s,r)=>s+r[7], 0);
  const totalUriage = rows.reduce((s,r)=>s+r[9], 0);
  const teamAvgPrice = totalCloSeiyaku ? Math.round(totalUriage / totalCloSeiyaku / 1000) * 1000 : null;
  const teamShodanRate = totalShodan ? round1(totalCloSeiyaku / totalShodan * 100) : null;
  document.getElementById('naihanTiles').innerHTML = `
    <div class="tile"><div class="label">メンバー数</div><div class="value">${rows.length}<span class="unit">名</span></div></div>
    <div class="tile"><div class="label">アポ数（後確通過）</div><div class="value">${totalApoValid}<span class="unit">件</span></div><div class="sub">総獲得数−キャンセル数</div></div>
    <div class="tile"><div class="label">成約数（アポ側）</div><div class="value">${totalApoSeiyaku}<span class="unit">件</span></div></div>
    <div class="tile"><div class="label">クローザー商談数</div><div class="value">${totalShodan}<span class="unit">件</span></div><div class="sub">Cyzen報告書（獲得+提案中+敗戦）基準</div></div>
    <div class="tile"><div class="label">成約数（クロ側）</div><div class="value">${totalCloSeiyaku}<span class="unit">件</span></div></div>
    <div class="tile"><div class="label">成約率（商談数ベース）</div><div class="value">${teamShodanRate===null?'—':teamShodanRate}<span class="unit">${teamShodanRate===null?'':'%'}</span></div></div>
    <div class="tile"><div class="label">売上（クロ側）</div><div class="value">${yen(totalUriage)}<span class="unit">円</span></div></div>
    <div class="tile"><div class="label">平均売価</div><div class="value">${teamAvgPrice===null?'—':yen(teamAvgPrice)}<span class="unit">${teamAvgPrice===null?'':'円'}</span></div></div>
  `;

  renderTable('t-naihan', [
    {label:'名前'}, {label:'会社名', cls:'company'},
    {label:'アポ数（後確通過）', num:true},
    {label:'総獲得数', num:true},
    {label:'キャンセル数', num:true},
    {label:'成約数（アポ側）', num:true},
    {label:'クローザー商談数', num:true, fmt:v=>v===0?'—':v},
    {label:'成約数（クロ側）', num:true},
    {label:'成約率（商談数ベース）', num:true, fmt:v=>v===null?'—':v+'%'},
    {label:'売上（クロ側）', num:true, fmt:v=>yen(v)},
    {label:'平均売価', num:true, fmt:v=>v===null?'—':yen(v)},
  ], rows, {defaultSort:2, rowClick:r=>openPersonDetail(r[0])});
}

function renderAlertBanner(){
  const d = currentData();
  const el = document.getElementById('alertBanner');
  let html = '';
  if (d.prev_data_available === false){
    html += `<div class="title">ℹ 前期間（${d.prev_start}〜${d.prev_end}）の成約データがありません</div>` +
      `<div>獲得報告データのシートが2026/07/01より前を持っていないため、この期間の前期間比較・強化対象候補・取材候補（成約数ベースの判定）は正しく機能しません（実績がゼロなのではなく、比較対象データが無いだけです）。週次で第2週以降を選ぶか、7月以降のみの期間であれば正しく判定されます。</div>`;
  }
  if (d.name_alerts && d.name_alerts.length){
    const items = d.name_alerts.map(a =>
      `<li><b>${a.company}</b>: 「${a.name_a}」 / 「${a.name_b}」 — ${a.reason}</li>`
    ).join('');
    html += `<div class="title" style="margin-top:${html?'10px':'0'};">⚠ 表記ゆれ・重複入力の疑いあり（${d.name_alerts.length}件・要確認）</div><ul>${items}</ul>`;
  }
  if (d.attendance_mismatch_people && d.attendance_mismatch_people.length){
    const items = d.attendance_mismatch_people
      .slice().sort((a,b)=>b.count-a.count)
      .map(p => `<li><b>${escapeHtml(p.name)}</b>（${escapeHtml(p.company)}・${p.role}）— ${p.role==='クローザー'?'成約':'アポ'}${p.count}件、出勤打刻なし</li>`)
      .join('');
    html += `<details style="margin-top:${html?'10px':'0'};"><summary class="title" style="cursor:pointer;">⚠ 出勤打刻なしで実績のある担当者（${d.attendance_mismatch_people.length}名・クリックで一覧）</summary><ul>${items}</ul></details>`;
  }
  if (ATTENDANCE_ALERT && ATTENDANCE_ALERT.report_mismatch_count){
    const items = ATTENDANCE_ALERT.records.filter(r=>r.report_mismatch)
      .slice().sort((a,b)=>(b.last_report||'').localeCompare(a.last_report||''))
      .map(r => `<li><b>${escapeHtml(r.name)}</b>（${escapeHtml(r.company)}）— ${escapeHtml(r.report_kind||'報告')}提出: ${escapeHtml(r.last_report||'')}／出退勤: ${escapeHtml(r.last_in||'—')}〜${escapeHtml(r.last_out||'—')}</li>`)
      .join('');
    html += `<details style="margin-top:${html?'10px':'0'};"><summary class="title" style="cursor:pointer;">🚨 報告提出日に出退勤打刻が無い担当者（${ATTENDANCE_ALERT.report_mismatch_count}名・必ず確認・クリックで一覧）</summary><ul>${items}</ul></details>`;
  }
  if (ATTENDANCE_ALERT && ATTENDANCE_ALERT.chronic_stuck_count){
    const items = ATTENDANCE_ALERT.records.filter(r=>r.chronic_stuck)
      .slice().sort((a,b)=>(b.chronic_days||0)-(a.chronic_days||0))
      .map(r => `<li><b>${escapeHtml(r.name)}</b>（${escapeHtml(r.company)}）— 最終出勤${escapeHtml(r.last_in||'')}のまま${r.chronic_days}日間出退勤ボタン操作なし。本日もルート自動記録あり＝実際は稼働中と見られる</li>`)
      .join('');
    html += `<details style="margin-top:${html?'10px':'0'};"><summary class="title" style="cursor:pointer;">🔋 勤怠つけっぱなし疑い（出退勤ボタンが数日以上止まったまま稼働中の担当者・${ATTENDANCE_ALERT.chronic_stuck_count}名・クリックで一覧）</summary><ul>${items}</ul></details>`;
  }
  if (html){
    el.innerHTML = html;
    el.classList.add('show');
  } else {
    el.classList.remove('show');
    el.innerHTML = '';
  }
}

// ---------- パートナー別シフト提出状況（2026-08-10追加） ----------
// 表示期間ピッカーとは連動しない独立スナップショット（開拓先パートナー・行動分析タブと同じ設計）。
function renderShiftStatus(){
  const card = document.getElementById('shiftStatusCard');
  if(!SHIFT_STATUS){ card.style.display = 'none'; return; }
  card.style.display = '';
  document.getElementById('shiftStatusDate').textContent = SHIFT_STATUS.today;
  document.getElementById('shiftStatusSummary').textContent =
    `シフト提出${SHIFT_STATUS.total_submitted}名／本日打刻あり${SHIFT_STATUS.total_attended_today}名／シフト提出だが打刻なし${SHIFT_STATUS.total_missing}名`;

  const rows = SHIFT_STATUS.companies.map(c=>[c.company, c.submitted, c.attended_today, c.missing_count, c.missing]);
  renderTable('t-shift-status', [
    {label:'会社名'},
    {label:'シフト提出人数', num:true},
    {label:'本日打刻あり', num:true},
    {label:'シフト提出だが打刻なし', num:true, fmt:(v,r)=> v>0
      ? `<span class="pill attendance-abandoned">${v}名</span><div class="reason-text">${r[4].map(m=>escapeHtml(m.name)).join('・')}</div>`
      : `<span class="pill attendance-ok">0名</span>`},
  ], rows, {defaultSort:3});
}

// ---------- 商談パイプライン（2026-08-17追加・Cyzen連携API /schedules） ----------
// 表示期間ピッカーとは連動しない独立スナップショット（開拓先パートナー・行動分析タブと同じ設計）。
function renderShodanPipeline(){
  const card = document.getElementById('shodanCard');
  if(!SHODAN_PIPELINE){ card.style.display = 'none'; return; }
  card.style.display = '';
  const t = SHODAN_PIPELINE.totals || {};
  const gap = SHODAN_PIPELINE.report_gap || {};
  const kakutei = t['確定']||0, kari = t['仮予定']||0, atokaku = t['後確後（事務確認OK）']||0;
  document.getElementById('shodanUpdated').textContent = SHODAN_PIPELINE.generated || '—';
  document.getElementById('shodanSummary').textContent =
    `${SHODAN_PIPELINE.period?.start||''}〜${SHODAN_PIPELINE.period?.end||''}`;
  const gapTxt = gap.kakutei_missing_rate===null||gap.kakutei_missing_rate===undefined ? '—' : gap.kakutei_missing_rate+'%';
  document.getElementById('shodanTiles').innerHTML = [
    {l:'商談予定合計', v:(kakutei+kari+atokaku), u:'件'},
    {l:'うち確定', v:kakutei, u:'件'},
    {l:'うち仮予定+後確後', v:(kari+atokaku), u:'件'},
    {l:'確定商談の欠測率', v:gapTxt, u:'', sub:`実施報告あり${gap.kakutei_reported||0}件／欠測${gap.kakutei_missing||0}件`},
  ].map(c=>`<div class="tile"><div class="label">${c.l}</div><div class="value">${c.v}<span class="unit">${c.u}</span></div>${c.sub?`<div class="sub">${c.sub}</div>`:''}</div>`).join('');
}

// ---------- 企業別タブの会社スコープ（検索して1社に絞り込み・2026-08-04追加） ----------
function populateCompanyScopeList(d){
  const list = document.getElementById('companyScopeList');
  if(!list) return;
  const names = [...new Set(d.companies.map(c=>c.company))].sort((a,b)=>a.localeCompare(b,'ja'));
  list.innerHTML = names.map(n=>`<option value="${escapeHtml(n)}"></option>`).join('');
}
function computeCompanyMembers(d, company){
  const byName = new Map();
  const get = n => {
    if(!byName.has(n)) byName.set(n, {name:n, apoCount:0, apoSeiyaku:0, cloSeiyaku:0, uriage:0, activeDays:null});
    return byName.get(n);
  };
  d.apo_ranking.filter(r=>r[2]===company).forEach(r=>{
    const rec = get(r[1]); rec.apoSeiyaku = r[3]; rec.apoCount = r[4];
  });
  d.closer_ranking.filter(r=>r[2]===company).forEach(r=>{
    const rec = get(r[1]); rec.cloSeiyaku = r[3]; rec.uriage = r[4];
  });
  (d.attendance_person_rows || []).filter(r=>r[1]===company).forEach(r=>{
    const rec = get(r[0]); rec.activeDays = r[2];
  });
  return [...byName.values()].sort((a,b)=> (b.uriage - a.uriage) || (b.apoCount - a.apoCount));
}
// 担当者別内訳テーブルで選べる指標（2026-08-31改訂・小宮山さん依頼）。クリックするまで
// テーブル自体を表示しない。colIdxはrenderTable()に渡す行配列（[名前,アポ獲得数,アポ成約,
// クロ成約,売上,稼働日数]）でのインデックス＝defaultSortにそのまま使う。
const COMPANY_MEMBER_METRICS = [
  {label:'アポ獲得数', colIdx:1},
  {label:'アポ成約', colIdx:2},
  {label:'クロ成約', colIdx:3},
  {label:'売上', colIdx:4},
  {label:'稼働日数', colIdx:5},
];
function renderCompanyScopedView(d){
  const company = COMPANY_SCOPE;
  const people = computeCompanyMembers(d, company);
  const rows = people.map(p => [p.name, p.apoCount, p.apoSeiyaku, p.cloSeiyaku, p.uriage, p.activeDays]);

  function drawMemberTable(sortColIdx){
    renderTable('t-company-scoped', [
      {label:'名前'},
      {label:'アポ獲得数', num:true},
      {label:'アポ成約', num:true},
      {label:'クロ成約', num:true},
      {label:'売上', num:true, fmt:v=>yen(v)},
      {label:'稼働日数', num:true, fmt:v=>(v===null||v===undefined)?'—':v},
    ], rows, {defaultSort: sortColIdx, rowClick: r=>openPersonDetail(r[0])});
  }

  document.getElementById('companyMemberTableCard').style.display = 'none';
  document.getElementById('companyScopedNote').style.display = 'none';
  const chipsWrap = document.getElementById('companyMemberChips');
  chipsWrap.innerHTML = COMPANY_MEMBER_METRICS.map(m =>
    `<button class="printbtn" type="button" data-metric-col="${m.colIdx}">${escapeHtml(m.label)}</button>`
  ).join('');
  chipsWrap.querySelectorAll('button[data-metric-col]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      drawMemberTable(Number(btn.dataset.metricCol));
      const card = document.getElementById('companyMemberTableCard');
      card.style.display = '';
      document.getElementById('companyScopedNote').style.display = '';
      card.scrollIntoView({behavior:'smooth', block:'start'});
    });
  });

  document.getElementById('companyScopedNote').textContent =
    `${company} の担当者 ${people.length}名／期間: ${d.start}〜${d.end}。行をクリックすると個人の日別実績を表示します。上部のKPIタイルもこの会社の値に切り替わっています（他のランキングタブは全社表示のままです）。`;
}
function setCompanyScope(company){
  COMPANY_SCOPE = company || null;
  document.getElementById('companyScopeResetBtn').style.display = COMPANY_SCOPE ? '' : 'none';
  document.getElementById('companyScopeStatus').textContent = COMPANY_SCOPE ? `「${COMPANY_SCOPE}」で表示中` : '';
  document.getElementById('companyScopeInput').value = COMPANY_SCOPE || '';
  renderPeriodMeta();
  renderTiles();
  renderAlertBanner();
  renderAllTables();
  updateTitleForActiveTab();
}

// KPIタイルのスパークライン部分だけを組み立てる（フェーズ2・2026-08-11追加）。
// DAILY_PERIODSの直近14日推移。データが1日分しか無い（新規導入直後等）場合はsparkline()側で空SVGを返す。
function tileSparkHtml(getter, color){
  const series = dailyTrendSeries(getter, 14);
  if(series.filter(v=>v!==null && v!==undefined).length < 2) return '';
  return `<div style="margin-top:6px;">${sparkline(series, {color, width:84, height:24})}</div>`;
}
// リアルタイム稼働中人数（2026-08-19追加・小宮山さん依頼）。表示期間ピッカーで「日次×本日」を
// 選んでいる時だけ、「稼働人員数（出勤打刻あり）」タイルの意味を「その日出勤した実績（延べ）」から
// 「今まさに出勤中＝退勤打刻がまだの人」に切り替える。ATTENDANCE_ALERTは自動更新タスク（平日8-20時・
// 5分おき）のスナップショットなので、ここでの「リアルタイム」は直近の自動更新時点（最大5分程度の
// ラグ）を意味する（本当の意味での秒単位リアルタイムではない点に注意）。
function isTodayDaySelected(){
  return CURRENT_PERIOD === 'day' && CURRENT_DAY_DATE === DAILY_DATES[0];
}
function realtimeActiveRecords(company){
  if(!ATTENDANCE_ALERT) return [];
  const today = DAILY_DATES[0]; // 'YYYY/MM/DD'形式
  // 出退勤区分は「退勤済み／出勤中（3時間未満）／出勤放置中（3時間以上・要対応アラート）／未打刻」の
  // 4種類。「今まさに稼働中」は経過時間に関わらずこの2つを両方含む必要がある（2026-08-20修正：
  // 「出勤放置中」だけで絞っていたため、直近3時間以内にチェックインした大多数を取りこぼしていた）。
  // last_inは'YYYY-MM-DD HH:MM:SS'形式（ハイフン区切り）なので、DAILY_DATES（スラッシュ区切り）と
  // 比較する前に区切り文字を揃える（2026-08-20修正：区切り文字の不一致で常に0件になっていたバグ）。
  return ATTENDANCE_ALERT.records.filter(r =>
    (r.attendance_status === '出勤中' || r.attendance_status === '出勤放置中') &&
    r.last_in && r.last_in.slice(0,10).replaceAll('-','/') === today &&
    (!company || r.company === company));
}
function renderTiles(){
  const d = currentData();
  renderDailyHeadcountTile();
  if(COMPANY_SCOPE){ renderTilesForCompany(d, COMPANY_SCOPE); return; }
  document.getElementById('companyKpiGaugeTopCard').style.display = 'none';
  const tot = d.totals;
  const rate = tot.apo_kakutoku ? (tot.clo_seiyaku/tot.apo_kakutoku*100) : 0;
  document.getElementById('tileApo').innerHTML = `${yen(tot.apo_kakutoku)}<span class="unit">件</span>` +
    tileSparkHtml(dp=>dp.totals.apo_kakutoku, 'var(--blue)');
  document.getElementById('tileSei').innerHTML = `${yen(tot.clo_seiyaku)}<span class="unit">件</span>` +
    tileSparkHtml(dp=>dp.totals.clo_seiyaku, 'var(--success)');
  document.getElementById('tileSeiSub').textContent = `獲得報告データ ${yen(d.n_closing_in_period)} 件が母数`;
  document.getElementById('tileUri').innerHTML = `${yen(tot.uriage)}<span class="unit">円</span>` +
    tileSparkHtml(dp=>dp.totals.uriage, 'var(--success)');
  document.getElementById('tileRate').innerHTML = `${rate.toFixed(1)}<span class="unit">%</span>`;
  if(isTodayDaySelected() && ATTENDANCE_ALERT){
    const active = realtimeActiveRecords();
    document.getElementById('tileHeadcountLabel').textContent = 'リアルタイム稼働中人数';
    document.getElementById('tileHeadcountSub').textContent =
      '直近の自動更新時点で出勤打刻あり・退勤未打刻の人数（最大5分ラグ）・クリックで内訳';
    document.getElementById('tileHeadcount').innerHTML = `${yen(active.length)}<span class="unit">名</span>`;
    document.getElementById('tileHeadcountPictogram').innerHTML = personPictogram(active.length);
  } else {
    document.getElementById('tileHeadcountLabel').textContent = '稼働人員数（出勤打刻あり）';
    document.getElementById('tileHeadcountSub').textContent = 'Cyzen出勤報告・直販含む延べ社数計';
    document.getElementById('tileHeadcount').innerHTML = `${yen(d.total_headcount || 0)}<span class="unit">名</span>` +
      tileSparkHtml(dp=>dp.total_headcount, 'var(--blue-light)');
    document.getElementById('tileHeadcountPictogram').innerHTML = personPictogram(d.total_headcount);
  }
  document.getElementById('tileApoAchievers').innerHTML = `${yen(tot.apo_achiever_count || 0)}<span class="unit">名</span>`;
  document.getElementById('tileSeiyakuAchievers').innerHTML = `${yen(tot.seiyaku_achiever_count || 0)}<span class="unit">名</span>`;
  if(ATTENDANCE_ALERT){
    document.getElementById('tileSpotActiveWrap').style.display = '';
    document.getElementById('tileRouteActiveWrap').style.display = '';
    document.getElementById('tileResetAlertWrap').style.display = '';
    document.getElementById('tileSpotActive').innerHTML = `${yen(ATTENDANCE_ALERT.spot_active_count)}<span class="unit">名</span>`;
    const rate = ATTENDANCE_ALERT.spot_active_rate;
    document.getElementById('tileSpotActiveSub').textContent =
      `稼働率${rate===null||rate===undefined?'—':rate.toFixed(1)+'%'}（${ATTENDANCE_ALERT.spot_active_count}/${ATTENDANCE_ALERT.total}名）・スポット作成・更新実績あり`;
    document.getElementById('tileRouteActive').innerHTML = `${yen(ATTENDANCE_ALERT.route_active_count)}<span class="unit">名</span>`;
    const rrate = ATTENDANCE_ALERT.route_active_rate;
    document.getElementById('tileRouteActiveSub').textContent =
      `稼働率${rrate===null||rrate===undefined?'—':rrate.toFixed(1)+'%'}（${ATTENDANCE_ALERT.route_active_count}/${ATTENDANCE_ALERT.total}名）・Cyzenルート自動記録あり`;
    document.getElementById('tileResetAlert').innerHTML = `${yen(ATTENDANCE_ALERT.by_alert['要対応'] || 0)}<span class="unit">名</span>`;
  }
  if(d.visits){
    document.getElementById('tileTaimenWrap').style.display = '';
    document.getElementById('tileTaimenRateWrap').style.display = '';
    document.getElementById('tileSpotTotalWrap').style.display = '';
    document.getElementById('tileTaimen').innerHTML = `${yen(d.visits.taimen_count)}<span class="unit">件</span>`;
    document.getElementById('tileTaimenSub').textContent =
      `新規由来${yen(d.visits.taimen_new_count)}件・再訪由来${yen(d.visits.taimen_revisit_count)}件`;
    document.getElementById('tileTaimenRate').innerHTML =
      `${d.visits.taimen_rate===null||d.visits.taimen_rate===undefined?'—':d.visits.taimen_rate.toFixed(1)}<span class="unit">%</span>`;
    document.getElementById('tileSpotTotal').innerHTML = `${yen(d.visits.total_spots)}<span class="unit">件</span>`;
  } else {
    document.getElementById('tileTaimenWrap').style.display = 'none';
    document.getElementById('tileTaimenRateWrap').style.display = 'none';
    document.getElementById('tileSpotTotalWrap').style.display = 'none';
  }
}

// 会社スコープ中（企業別タブで1社を選択中）のKPIタイル。ATTENDANCE_ALERT.recordsは
// 個人ごとにresolve_company()済みの会社名が既に付いているため、そのままJS側でフィルタするだけで
// 稼働人員数（スポット作成／ルート自動記録あり）の会社別集計ができる（Python側の追加実装は不要）。
function renderTilesForCompany(d, company){
  const c = d.companies.find(x => x.company === company);
  const cSafe = c || {};
  const t = COMPANY_TARGETS[company] || {};
  const gauges = [
    kpiGaugeCard('アポ獲得数', cSafe.apo_kakutoku, t.apo, v => (v===null||v===undefined)?'—':v+'件'),
    kpiGaugeCard('成約数', cSafe.clo_seiyaku, t.seiyaku, v => (v===null||v===undefined)?'—':v+'件'),
    kpiGaugeCard('売上', cSafe.uriage, t.uriage, v => (v===null||v===undefined)?'—':yen(v)+'円'),
    kpiGaugeCard('稼働人員数', cSafe.headcount, t.chinin, v => (v===null||v===undefined)?'—':v+'名'),
  ].filter(Boolean);
  document.getElementById('companyKpiGaugeTopTitle').textContent = company;
  document.getElementById('companyKpiGaugeTopCard').style.display = gauges.length ? '' : 'none';
  document.getElementById('companyKpiGaugeTopWrap').innerHTML = gauges.join('');
  const rate = (c && c.apo_kakutoku) ? (c.clo_seiyaku/c.apo_kakutoku*100) : 0;
  document.getElementById('tileApo').innerHTML = `${yen(c?c.apo_kakutoku:0)}<span class="unit">件</span>`;
  document.getElementById('tileSei').innerHTML = `${yen(c?c.clo_seiyaku:0)}<span class="unit">件</span>`;
  document.getElementById('tileSeiSub').textContent = `「${company}」に絞り込み中（全社集計ではありません）`;
  document.getElementById('tileUri').innerHTML = `${yen(c?c.uriage:0)}<span class="unit">円</span>`;
  document.getElementById('tileRate').innerHTML = `${rate.toFixed(1)}<span class="unit">%</span>`;
  if(isTodayDaySelected() && ATTENDANCE_ALERT){
    const active = realtimeActiveRecords(company);
    document.getElementById('tileHeadcountLabel').textContent = 'リアルタイム稼働中人数';
    document.getElementById('tileHeadcountSub').textContent =
      '直近の自動更新時点で出勤打刻あり・退勤未打刻の人数（最大5分ラグ）・クリックで内訳';
    document.getElementById('tileHeadcount').innerHTML = `${yen(active.length)}<span class="unit">名</span>`;
    document.getElementById('tileHeadcountPictogram').innerHTML = personPictogram(active.length, {unit:1, cap:20});
  } else {
    document.getElementById('tileHeadcountLabel').textContent = '稼働人員数（出勤打刻あり）';
    document.getElementById('tileHeadcountSub').textContent = 'Cyzen出勤報告・直販含む延べ社数計';
    document.getElementById('tileHeadcount').innerHTML = `${yen(c&&c.headcount!=null?c.headcount:0)}<span class="unit">名</span>`;
    document.getElementById('tileHeadcountPictogram').innerHTML = personPictogram(c&&c.headcount!=null?c.headcount:0, {unit:1, cap:20});
  }
  document.getElementById('tileApoAchievers').innerHTML = `${yen(c?(c.apo_achiever_count||0):0)}<span class="unit">名</span>`;
  document.getElementById('tileSeiyakuAchievers').innerHTML = `${yen(c?(c.seiyaku_achiever_count||0):0)}<span class="unit">名</span>`;
  if(ATTENDANCE_ALERT){
    document.getElementById('tileSpotActiveWrap').style.display = '';
    document.getElementById('tileRouteActiveWrap').style.display = '';
    document.getElementById('tileResetAlertWrap').style.display = '';
    const recs = ATTENDANCE_ALERT.records.filter(r=>r.company===company);
    const spotN = recs.filter(r=>r.spot_count>0).length;
    const routeN = recs.filter(r=>r.route_count>0).length;
    const total = recs.length;
    const spotRate = total ? round1(spotN/total*100) : null;
    const routeRate = total ? round1(routeN/total*100) : null;
    document.getElementById('tileSpotActive').innerHTML = `${yen(spotN)}<span class="unit">名</span>`;
    document.getElementById('tileSpotActiveSub').textContent =
      `稼働率${spotRate===null?'—':spotRate.toFixed(1)+'%'}（${spotN}/${total}名）・スポット作成・更新実績あり（${company}のみ）`;
    document.getElementById('tileRouteActive').innerHTML = `${yen(routeN)}<span class="unit">名</span>`;
    document.getElementById('tileRouteActiveSub').textContent =
      `稼働率${routeRate===null?'—':routeRate.toFixed(1)+'%'}（${routeN}/${total}名）・Cyzenルート自動記録あり（${company}のみ）`;
    document.getElementById('tileResetAlert').innerHTML = `${yen(c && c.attendance_alert_needsaction!=null ? c.attendance_alert_needsaction : 0)}<span class="unit">名</span>`;
  }
  if(d.visits && c){
    document.getElementById('tileTaimenWrap').style.display = '';
    document.getElementById('tileTaimenRateWrap').style.display = '';
    document.getElementById('tileSpotTotalWrap').style.display = '';
    document.getElementById('tileTaimen').innerHTML = `${yen(c.taimen_count||0)}<span class="unit">件</span>`;
    document.getElementById('tileTaimenSub').textContent = `「${company}」の対面数（新規/再訪の内訳は全社タイルのみ対応）`;
    document.getElementById('tileTaimenRate').innerHTML =
      `${c.taimen_rate===null||c.taimen_rate===undefined?'—':c.taimen_rate.toFixed(1)}<span class="unit">%</span>`;
    document.getElementById('tileSpotTotal').innerHTML = `${yen((c.new_visit_count||0)+(c.revisit_count||0))}<span class="unit">件</span>`;
  } else {
    document.getElementById('tileTaimenWrap').style.display = 'none';
    document.getElementById('tileTaimenRateWrap').style.display = 'none';
    document.getElementById('tileSpotTotalWrap').style.display = 'none';
  }
}

function renderPeriodMeta(){
  const d = currentData();
  document.getElementById('periodLabel').textContent = `${d.start}〜${d.end}`;
  document.getElementById('prevPeriodLabel').textContent = (d.prev_start && d.prev_end) ? `${d.prev_start}〜${d.prev_end}` : '—';
}

function escapeHtml(s){
  return String(s??'').replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function populateTopicChannelFilter(){
  const sel = document.getElementById('topicChannelFilter');
  const channels = [...new Set(SLACK_TOPICS.map(t=>t.channel))].sort((a,b)=>a.localeCompare(b,'ja'));
  channels.forEach(ch=>{
    const opt = document.createElement('option');
    opt.value = ch; opt.textContent = ch;
    sel.appendChild(opt);
  });
}

function renderTopics(){
  renderKawakamiTimeline();
  const d = currentData();
  const chFilter = document.getElementById('topicChannelFilter').value;
  const kindFilter = document.getElementById('topicKindFilter').value;
  const items = SLACK_TOPICS.filter(t=>
    t.date >= d.start && t.date <= d.end &&
    (!chFilter || t.channel===chFilter) &&
    (!kindFilter || t.kind===kindFilter)
  ).slice().sort((a,b)=> String(b.ts).localeCompare(String(a.ts)));
  const list = document.getElementById('topicList');
  if(!items.length){
    list.innerHTML = '<div class="topic-empty">この期間・条件に該当するトピックスはありません。</div>';
    return;
  }
  list.innerHTML = items.map(t=>{
    const body = escapeHtml(t.text);
    const clamp = body.length > 200 ? 'clamped' : '';
    return `<div class="topic-card">
      <div class="topic-head"><span><span class="topic-kind">${escapeHtml(t.kind)}</span> <b>${escapeHtml(t.channel)}</b>　${escapeHtml(t.author)}　${t.date}</span></div>
      <div class="topic-text ${clamp}" onclick="this.classList.remove('clamped')">${body}</div>
      <div class="topic-foot"><span>${t.thread_replies ? 'スレッド返信 '+t.thread_replies+'件' : ''}</span><a href="${t.permalink}" target="_blank" rel="noopener">Slackで見る →</a></div>
    </div>`;
  }).join('');
}

// ==================== ② 川上さん日報タイムライン・週次抽出サマリー ====================
function kawakamiReports(){
  return SLACK_TOPICS.filter(t=> t.kind==='日報' && (t.author||'').includes('川上'));
}
function fmtDateSlash(dt){
  return `${dt.getFullYear()}/${String(dt.getMonth()+1).padStart(2,'0')}/${String(dt.getDate()).padStart(2,'0')}`;
}
// 日報テキストは書式不定のため、典型パターン（例:「クロージング：成約26/28件・売上6,154.9万」）に
// マッチすれば抽出して見せ、マッチしなければ元テキストをそのまま見せる程度の簡易パーサー。
function extractReportMetrics(text){
  const out = {};
  let m;
  m = text.match(/成約\s*(\d+)\s*[\/／]\s*(\d+)\s*件/);
  if(m) out['成約'] = `${m[1]}/${m[2]}件`;
  else { m = text.match(/成約\s*(\d+)\s*件/); if(m) out['成約'] = `${m[1]}件`; }
  m = text.match(/売上\s*([\d,]+(?:\.\d+)?)\s*万/);
  if(m) out['売上'] = `${m[1]}万円`;
  m = text.match(/成約率\s*([\d.]+)\s*%/);
  if(m) out['成約率'] = `${m[1]}%`;
  return out;
}
function renderKawakamiTimeline(){
  const el = document.getElementById('kawakamiTimeline');
  if(!el) return;
  const cutoff = new Date(); cutoff.setDate(cutoff.getDate()-14);
  const cutoffStr = fmtDateSlash(cutoff);
  const items = kawakamiReports().filter(t=>t.date >= cutoffStr).sort((a,b)=> a.date.localeCompare(b.date));
  if(!items.length){
    el.innerHTML = '<div class="topic-empty">直近2週間分の川上さんの日報データはまだありません（日次運用で slack_topics.json に蓄積され次第、ここに時系列表示されます）。</div>';
    return;
  }
  el.innerHTML = items.map(t=>{
    const metrics = extractReportMetrics(t.text);
    const metricHtml = Object.keys(metrics).length
      ? Object.entries(metrics).map(([k,v])=>`<span class="pill flat">${escapeHtml(k)}: ${escapeHtml(v)}</span>`).join(' ')
      : '';
    return `<div class="topic-card">
      <div class="topic-head"><span><span class="topic-kind">日報</span> <b>${escapeHtml(t.channel)}</b>　${escapeHtml(t.author)}　${t.date}</span></div>
      <div class="topic-text">${escapeHtml(t.text)}</div>
      <div class="topic-foot"><span>${metricHtml}</span><a href="${t.permalink}" target="_blank" rel="noopener">Slackで見る →</a></div>
    </div>`;
  }).join('');
}
function renderKawakamiWeeklyCard(){
  const el = document.getElementById('kawakamiWeeklyCard');
  if(!el) return;
  const weeks = last4Weeks();
  const w = weeks[weeks.length-1];
  if(!w){ el.innerHTML=''; return; }
  const items = kawakamiReports().filter(t=> t.date >= w.start && t.date <= w.end).sort((a,b)=>a.date.localeCompare(b.date));
  if(!items.length){
    el.innerHTML = `<div class="note"><b>${escapeHtml(w.label)}</b>: 川上さんの日報データがまだありません（該当週の日報が蓄積され次第、成約/売上/成約率をここに自動抽出表示します）。</div>`;
    return;
  }
  const cards = items.map(t=>{
    const metrics = extractReportMetrics(t.text);
    const body = Object.keys(metrics).length
      ? Object.entries(metrics).map(([k,v])=>`<span class="pill flat">${escapeHtml(k)}: ${escapeHtml(v)}</span>`).join(' ')
      : escapeHtml(t.text.length>150 ? t.text.slice(0,150)+'…' : t.text);
    return `<div style="margin-bottom:6px;">${t.date}　${body}</div>`;
  }).join('');
  el.innerHTML = `<div class="note"><b>${escapeHtml(w.label)} 川上さん日報からの抽出サマリー</b><div style="margin-top:6px;">${cards}</div></div>`;
}

const TAB_LABELS = {'p-company':'企業別ランキング','p-apo':'アポインターランキング','p-soutiku':'創蓄アポインターランキング','p-closer':'クローザーランキング','p-naihan':'直販メンバー','p-topics':'Slackトピックス','p-outreach':'開拓先パートナー','p-route':'行動分析','p-trend':'傾向分析','p-exec':'責任者会議'};

function priorityPill(p){
  const cls = {'S':'good','A':'mid','B':'flat','C':'low'}[p] || 'flat';
  return `<span class="pill ${cls}">${escapeHtml(p)}</span>`;
}

let OUTREACH_FILTER = null; // 反応ステータス名。null=デフォルト（優先順位付けリスト）

function outreachRows(){
  if(!OUTREACH) return [];
  return OUTREACH_FILTER ? OUTREACH.all_candidates.filter(c=>c.response===OUTREACH_FILTER) : OUTREACH.priority_candidates;
}

function renderOutreachTable(){
  const rows = outreachRows();
  document.getElementById('outreachListTitle').textContent = OUTREACH_FILTER
    ? `反応「${OUTREACH_FILTER}」の候補（${rows.length}件・全候補対象）`
    : `優先順位付けリスト（積極アプローチ対象×未コンタクト・${rows.length}件）— 会社名クリックで詳細`;
  const cols = ['優先度','会社名','エリア','フォロワー','事業内容','該当キーワード','追加日','SNS'];
  const thead = '<thead><tr>' + cols.map(c=>`<th>${c}</th>`).join('') + '</tr></thead>';
  const tbody = '<tbody>' + (rows.length ? rows.map((c,i)=>
    `<tr><td>${priorityPill(c.priority)}</td><td class="name clickable-name" data-idx="${i}">${escapeHtml(c.company)}</td><td class="company">${escapeHtml(c.area)}</td>` +
    `<td class="num">${escapeHtml(c.followers)}</td><td>${escapeHtml(c.business)}</td><td>${escapeHtml(c.keyword)}</td>` +
    `<td>${escapeHtml(c.added)}</td><td>${c.sns ? `<a href="${c.sns.replace(/"/g,'&quot;')}" target="_blank" rel="noopener">開く</a>` : '—'}</td></tr>`
  ).join('') : '<tr><td colspan="8" style="text-align:center;color:var(--text-sub);">該当候補なし</td></tr>') + '</tbody>';
  const table = document.getElementById('t-outreach');
  table.innerHTML = thead + tbody;
  table.querySelectorAll('.clickable-name').forEach(td=>{
    td.addEventListener('click', ()=> openOutreachDetail(rows[parseInt(td.dataset.idx)]));
  });
}

function renderAiSummary(){
  const card = document.getElementById('aiSummaryCard');
  if(!AI_SUMMARY){ card.style.display = 'none'; return; }
  card.style.display = 'block';
  document.getElementById('aiSummaryMeta').textContent = `対象: ${AI_SUMMARY.period_label || '—'}　|　生成: ${AI_SUMMARY.generated_at || '—'}`;
  const fill = (id, items) => {
    const el = document.getElementById(id);
    el.innerHTML = (items && items.length) ? items.map(t=>`<li>${escapeHtml(t)}</li>`).join('') : '<li style="color:var(--text-sub);">該当なし</li>';
  };
  fill('aiSummaryFocus', AI_SUMMARY.focus_points);
  fill('aiSummaryAlerts', AI_SUMMARY.alerts);
  fill('aiSummaryActions', AI_SUMMARY.next_actions);
  document.getElementById('aiSummaryNote').textContent = AI_SUMMARY.note || '';
}

// ==================== ⑩ 責任者会議タブ ====================
let EXEC_CUSTOM_RANGE = null; // {start:'YYYY-MM-DD', end:'YYYY-MM-DD'} | null（null=既定の今月）
function execMonthData(){
  if(EXEC_CUSTOM_RANGE){
    const d = buildCustomRangeData(EXEC_CUSTOM_RANGE.start, EXEC_CUSTOM_RANGE.end);
    if(d) return d;
  }
  return PERIODS.month;
}
// 完工数は日別データを当月分（COMPLETION.daily_cumulative）しか持たないため、この範囲でのみ差分計算できる。
// 前月にまたがる期間や範囲外の日を選んだ場合はnull（呼び出し側で「—」表示にフォールバック）。
function completionForRange(startYMD, endYMD){
  if(!COMPLETION.available) return null;
  const arr = COMPLETION.daily_cumulative;
  if(!arr || !arr.length) return null;
  const start = startYMD.replaceAll('-', '/'), end = endYMD.replaceAll('-', '/');
  const startIdx = arr.findIndex(a=>a.date===start);
  const endIdx = arr.findIndex(a=>a.date===end);
  if(startIdx<0 || endIdx<0) return null;
  const prevCount = startIdx>0 ? arr[startIdx-1].count : 0;
  const prevUriage = startIdx>0 ? arr[startIdx-1].uriage : 0;
  return {count: arr[endIdx].count - prevCount, uriage: arr[endIdx].uriage - prevUriage};
}

function daysInMonthOf(dateStr){
  const parts = dateStr.split('/').map(Number);
  return new Date(parts[0], parts[1], 0).getDate();
}
function dayOfMonthOf(dateStr){ return Number(dateStr.split('/')[2]); }

// ---------- 稼働人員数（目標を稼働率100%の基準とし、前日/前週/前月比で推移を見る。2026-08-03追加。
// 2026-08-04追加: 出勤打刻あり・スポット作成あり・ルート自動記録あり の3集計方法で並べて見られるように拡張） ----------
// アポ数・売上のような「月内で積み上がり続けるフロー型」の値ではなく「その期間に1回でも稼働した人数（重複排除）」
// というストック型の値のため、経過日数で目標を按分する「オンペース比」を当てはめると実態と合わない
// （月初の数日でほぼ全員分が出揃ってしまい、680%のような非現実的な数字になる）。ここでは目標人数をそのまま
// 稼働率100%の基準とし、同じ粒度（日/週/月）・同じ集計方法同士の前回比較でしか判断しない。
// 出勤打刻(Cyzen「出勤」ボタン)は押し忘れが多く最も過小カウントになりやすい実態が既知（SKILL.md参照）ため、
// スポット作成(訪問先レコード作成)・ルート自動記録(バックグラウンドGPS)の2つも同じ目標基準で並べて見せることで、
// 打刻ベースの数字がどれだけ実態より低く出ているかを可視化する。
function dateFromYMD(s){ const [y,m,d] = s.split('/').map(Number); return new Date(y, m-1, d); }
function fmtYMD(dt){
  const y = dt.getFullYear(), m = String(dt.getMonth()+1).padStart(2,'0'), d = String(dt.getDate()).padStart(2,'0');
  return `${y}/${m}/${d}`;
}
function normNameJs(n){
  return (n||'').trim().replaceAll(' ','').replaceAll('　','').replaceAll('髙','高').replaceAll('濵','濱');
}
// startYMD/endYMD: 'YYYY/MM/DD'（DAILY_PERIODSのキーと同じ書式）。戻り値の各カウントは、対象範囲に
// その集計方法のデータが1日も無ければnull（＝UI側で「—」表示）、データはあるが0名ならそのまま0。
function headcountByMethod(startYMD, endYMD){
  const dates = Object.keys(DAILY_PERIODS).filter(d => d >= startYMD && d <= endYMD);
  const attendanceNames = new Set(), spotNames = new Set();
  let spotAvailable = false;
  dates.forEach(date=>{
    const dp = DAILY_PERIODS[date];
    (dp.attendance_person_rows || []).forEach(r => attendanceNames.add(normNameJs(r[0])));
    if(dp.visits && dp.visits.person){
      spotAvailable = true;
      Object.keys(dp.visits.person).forEach(n => spotNames.add(normNameJs(n)));
    }
  });
  const startHyphen = startYMD.replaceAll('/','-'), endHyphen = endYMD.replaceAll('/','-');
  const routeDates = Object.keys(ROUTE_HISTORY || {}).filter(d => d >= startHyphen && d <= endHyphen);
  const routeNames = new Set();
  routeDates.forEach(date=>{
    const dayData = ROUTE_HISTORY[date];
    Object.keys(dayData).forEach(name=>{
      if((dayData[name].route_count || 0) > 0) routeNames.add(normNameJs(name));
    });
  });
  return {
    attendance: dates.length ? attendanceNames.size : null,
    spot: spotAvailable ? spotNames.size : null,
    route: routeDates.length ? routeNames.size : null,
  };
}
function headcountRateOf(hc, target){
  return (target && hc!==null && hc!==undefined) ? round1(hc/target*100) : null;
}
// トップ画面の「稼働人員数・詳細」タイル。上部の表示期間ピッカー（日次/週次/月次/カスタム）で
// 選択中の期間に連動し、その期間固有の実人数（出勤打刻あり基準・重複排除済み）を出す
// （2026-08-25修正・小宮山さんの指摘＝日付を変えても「本日」の値に固定されたままだったのを解消）。
function renderDailyHeadcountTile(){
  const wrap = document.getElementById('tileDailyHeadcountWrap');
  const d = currentData();
  if(!d || !d.start){ wrap.style.display = 'none'; return; }
  const hc = headcountByMethod(d.start, d.end);
  const periodLabel = d.start === d.end ? d.start : `${d.start}〜${d.end}`;
  document.getElementById('tileDailyHeadcountDate').textContent = periodLabel;
  document.getElementById('tileDailyHeadcount').innerHTML =
    `${hc.attendance===null||hc.attendance===undefined?'—':hc.attendance}<span class="unit">名</span>`;
  const spotTxt = hc.spot===null||hc.spot===undefined ? '—' : hc.spot;
  const routeTxt = hc.route===null||hc.route===undefined ? '—' : hc.route;
  document.getElementById('tileDailyHeadcountSub').textContent =
    `出勤打刻あり基準（参考: スポット作成あり${spotTxt}名／ルート自動記録あり${routeTxt}名）`;
}
function trendPtCell(deltaPt, prevHc, prevLabel){
  const prevTxt = (prevHc===null||prevHc===undefined) ? `${prevLabel}データなし` : `${prevLabel}${prevHc}名`;
  if(deltaPt===null||deltaPt===undefined) return `<span class="pill flat">—</span> <span class="sub" style="font-size:11px;">（${prevTxt}）</span>`;
  const cls = deltaPt>0 ? 'delta-up' : deltaPt<0 ? 'delta-down' : '';
  const arrow = deltaPt>0 ? '▲' : deltaPt<0 ? '▼' : '→';
  return `<span class="${cls}">${arrow}${Math.abs(deltaPt).toFixed(1)}pt</span> <span class="sub" style="font-size:11px;">（${prevTxt}）</span>`;
}
function hcRateCell(hc, prevHc, target, prevLabel){
  const rate = headcountRateOf(hc, target);
  const prevRate = headcountRateOf(prevHc, target);
  const deltaPt = (rate!==null && prevRate!==null) ? round1(rate-prevRate) : null;
  return `<div style="display:flex; flex-direction:column; gap:4px; align-items:flex-start;">
    <div style="display:flex; align-items:center; gap:6px;">${onPacePill(rate, true)}<span style="font-size:12px; color:var(--text-sub);">実績${hc===null||hc===undefined?'—':hc}名</span></div>
    <div>${trendPtCell(deltaPt, prevHc, prevLabel)}</div>
  </div>`;
}
function renderExecHeadcountRate(){
  const target = TARGETS.monthly.chinin;
  document.getElementById('hcRateTarget').textContent = (target===null||target===undefined) ? '未設定（上のフォームで設定してください）' : target;

  const todayDate = DAILY_DATES[0], yestDate = DAILY_DATES[1];
  const emptyM = {attendance:null, spot:null, route:null};
  const todayHcM = todayDate ? headcountByMethod(todayDate, todayDate) : emptyM;
  const yestHcM = yestDate ? headcountByMethod(yestDate, yestDate) : emptyM;

  const curWeekMeta = WEEKLY_PERIOD_LIST[WEEKLY_PERIOD_LIST.length-1];
  const curWeekData = WEEKLY_PERIODS[curWeekMeta.key];
  const weekHcM = headcountByMethod(curWeekData.start, curWeekData.end);
  const prevWeekHcM = (curWeekData.prev_start && curWeekData.prev_end)
    ? headcountByMethod(curWeekData.prev_start, curWeekData.prev_end) : emptyM;

  const curMonthData = MONTHLY_PERIODS[CURRENT_MONTH_KEY] || PERIODS.month;
  const monthHcM = headcountByMethod(curMonthData.start, curMonthData.end);
  const elapsedDays = dayOfMonthOf(curMonthData.end);
  const curStart = dateFromYMD(curMonthData.start);
  const prevMonthStartDt = new Date(curStart.getFullYear(), curStart.getMonth()-1, 1);
  const daysInPrevMonth = new Date(prevMonthStartDt.getFullYear(), prevMonthStartDt.getMonth()+1, 0).getDate();
  const prevMonthEndDt = new Date(prevMonthStartDt.getFullYear(), prevMonthStartDt.getMonth(), Math.min(elapsedDays, daysInPrevMonth));
  const prevMonthHcM = headcountByMethod(fmtYMD(prevMonthStartDt), fmtYMD(prevMonthEndDt));

  const methods = [
    {key:'attendance', label:'出勤打刻あり'},
    {key:'spot', label:'スポット作成あり'},
    {key:'route', label:'ルート自動記録あり'},
  ];

  const table = document.getElementById('t-exec-hcrate');
  const thead = `<thead><tr><th>集計方法</th>` +
    `<th>当日（${todayDate||'—'}）</th>` +
    `<th>直近週（${escapeHtml(curWeekMeta.label)}）</th>` +
    `<th>当月（${curMonthData.start}〜${curMonthData.end}）</th></tr></thead>`;
  const tbody = '<tbody>' + methods.map(m => {
    return `<tr><td class="name">${m.label}</td>` +
      `<td>${hcRateCell(todayHcM[m.key], yestHcM[m.key], target, '前日')}</td>` +
      `<td>${hcRateCell(weekHcM[m.key], prevWeekHcM[m.key], target, '前週')}</td>` +
      `<td>${hcRateCell(monthHcM[m.key], prevMonthHcM[m.key], target, '前月同日数')}</td></tr>`;
  }).join('') + '</tbody>';
  table.innerHTML = thead + tbody;
}

function onPaceRatio(actual, target, elapsed, total){
  if(!target || !elapsed || !total) return null;
  const idealSoFar = target * (elapsed/total);
  if(!idealSoFar) return null;
  return actual / idealSoFar * 100;
}
function onPaceClass(ratio){
  if(ratio===null||ratio===undefined) return 'flat';
  if(ratio>=100) return 'good';
  if(ratio>=85) return 'mid';
  return 'low';
}
function onPacePill(ratio, isPrimary){
  if(!isPrimary) return `<span class="pill flat">${ratio===null?'—':ratio.toFixed(0)+'%'}（参考）</span>`;
  if(ratio===null||ratio===undefined) return '<span class="pill flat">—</span>';
  return `<span class="pill ${onPaceClass(ratio)}">${ratio.toFixed(0)}%</span>`;
}
function progressBar(ratio, isPrimary){
  const pct = ratio===null||ratio===undefined ? 0 : Math.max(0, Math.min(140, ratio));
  const color = !isPrimary ? 'var(--text-xs)' : (onPaceClass(ratio)==='good'?'var(--success)':onPaceClass(ratio)==='mid'?'var(--warn)':'var(--danger)');
  return `<div style="position:relative; background:var(--border); border-radius:6px; height:10px; width:160px; overflow:hidden;">
    <div style="position:absolute; left:0; top:0; bottom:0; width:${Math.min(100,pct/1.4)}%; background:${color};"></div>
    <div style="position:absolute; left:${100/1.4}%; top:-2px; bottom:-2px; width:1px; background:var(--text-sub);" title="理想進捗ライン(100%)"></div>
  </div>`;
}

function execKpiRows(){
  const d = execMonthData();
  const tot = d.totals;
  const elapsed = dayOfMonthOf(d.end);
  const total = daysInMonthOf(d.end);
  const comp = EXEC_CUSTOM_RANGE ? completionForRange(EXEC_CUSTOM_RANGE.start, EXEC_CUSTOM_RANGE.end)
    : (COMPLETION.available ? COMPLETION.month : null);
  const compNote = comp ? '' : (COMPLETION.available
    ? (EXEC_CUSTOM_RANGE ? 'この期間の完工数データは未取得（当月＋前月の日次内訳のみ対応）' : '')
    : '完工数データ未取得（--completion-dir未指定）');
  return [
    {label:'成約数', unit:'件', target:TARGETS.monthly.seiyaku, actual:tot.clo_seiyaku, primary:true},
    {label:'完工数', unit:'件', target:TARGETS.monthly.kanko, actual:comp?comp.count:null, primary:true, note: compNote},
    {label:'売上', unit:'円', target:TARGETS.monthly.uriage, actual:tot.uriage, primary:true, fmt:yen},
    {label:'アポ数', unit:'件', target:TARGETS.monthly.apo, actual:tot.apo_kakutoku, primary:false},
    {label:'商談数', unit:'件', target:TARGETS.monthly.shodan, actual:null, primary:false, note:'商談パイプラインデータ未取得のため空欄'},
  ].map(r=>{
    const ratio = (r.actual!==null && r.actual!==undefined) ? onPaceRatio(r.actual, r.target, elapsed, total) : null;
    return Object.assign(r, {elapsed, total, ratio});
  });
}

function renderExecSummary(){
  const rows = execKpiRows();
  const table = document.getElementById('t-exec-summary');
  const fmt = v => v===null||v===undefined ? '—' : (typeof v==='number' ? v.toLocaleString('ja-JP') : v);
  const thead = '<thead><tr><th>KPI</th><th class="num">目標</th><th class="num">実績</th><th>進捗(オンペース比)</th><th></th></tr></thead>';
  const tbody = '<tbody>' + rows.map(r=>{
    const targetTxt = r.target===null||r.target===undefined ? '未設定' : (r.fmt?r.fmt(r.target):fmt(r.target))+r.unit;
    const actualTxt = (r.actual===null||r.actual===undefined) ? '—' : (r.fmt?r.fmt(r.actual):fmt(r.actual))+r.unit;
    return `<tr><td class="name">${r.label}${r.note?`<div class="reason-text">${escapeHtml(r.note)}</div>`:''}</td>` +
      `<td class="num">${targetTxt}</td><td class="num">${actualTxt}</td>` +
      `<td>${progressBar(r.ratio, r.primary)}</td><td>${onPacePill(r.ratio, r.primary)}</td></tr>`;
  }).join('') + '</tbody>';
  table.innerHTML = thead + tbody;
}

function last4Weeks(){
  return WEEKLY_PERIOD_LIST.slice(-4);
}

function renderExecWeekly(){
  const weeks = last4Weeks();
  const table = document.getElementById('t-exec-weekly');
  const thead = '<thead><tr><th>週</th><th class="num">成約数</th><th class="num">前週比</th>' +
    '<th class="num">完工数</th><th class="num">前週比</th><th class="num">アポ数</th><th class="num">前週比</th>' +
    '<th class="num">稼働人員数</th></tr></thead>';
  const rowsData = weeks.map(w=>{
    const wd = WEEKLY_PERIODS[w.key];
    const comp = (COMPLETION.available && COMPLETION.weekly[w.key]) ? COMPLETION.weekly[w.key] : null;
    return {label: w.label, seiyaku: wd.totals.clo_seiyaku, apo: wd.totals.apo_kakutoku,
             kanko: comp ? comp.count : null, headcount: wd.total_headcount};
  });
  const arrow = (cur, prev) => {
    if(prev===null||prev===undefined||cur===null||cur===undefined) return '—';
    if(prev===0) return '—';
    const pct = (cur-prev)/prev*100;
    const cls = pct>=0 ? 'delta-up' : 'delta-down';
    const ar = pct>=0 ? '↑' : '↓';
    return `<span class="${cls}">${ar}${Math.abs(pct).toFixed(0)}%</span>`;
  };
  const tbody = '<tbody>' + rowsData.map((r,i)=>{
    const prev = i>0 ? rowsData[i-1] : null;
    const isLast = i === rowsData.length-1;
    return `<tr style="${isLast?'background:var(--blue-pale);':''}">` +
      `<td class="name">${escapeHtml(r.label)}</td>` +
      `<td class="num">${r.seiyaku}</td><td class="num">${prev?arrow(r.seiyaku,prev.seiyaku):'—'}</td>` +
      `<td class="num">${r.kanko===null?'—':r.kanko}</td><td class="num">${(prev&&prev.kanko!==null&&r.kanko!==null)?arrow(r.kanko,prev.kanko):'—'}</td>` +
      `<td class="num">${r.apo}</td><td class="num">${prev?arrow(r.apo,prev.apo):'—'}</td>` +
      `<td class="num">${r.headcount===null||r.headcount===undefined?'—':r.headcount}</td></tr>`;
  }).join('') + '</tbody>';
  table.innerHTML = thead + tbody;
}

function renderExecForecast(){
  const rows = execKpiRows().filter(r=>r.primary);
  const el = document.getElementById('execForecastTiles');
  el.innerHTML = rows.map(r=>{
    if(r.actual===null||r.actual===undefined){
      return `<div class="tile"><div class="label">${escapeHtml(r.label)}</div><div class="value">—</div><div class="sub">データ未取得</div></div>`;
    }
    const forecast = Math.round(r.actual / r.elapsed * r.total);
    const hasTarget = r.target!==null && r.target!==undefined;
    const diff = hasTarget ? forecast - r.target : null;
    const fmt = v => r.fmt ? r.fmt(v) : v.toLocaleString('ja-JP');
    const diffTxt = diff===null ? '—' : `${diff>=0?'+':''}${fmt(diff)}${r.unit}`;
    const diffCls = diff===null ? '' : (diff>=0?'delta-up':'delta-down');
    const gaugePct = hasTarget && r.target ? (forecast/r.target*100) : null;
    return `<div class="tile" style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
      <div>
        <div class="label">${escapeHtml(r.label)} 着地予測</div>
        <div class="value">${fmt(forecast)}<span class="unit">${r.unit}</span></div>
        <div class="sub">目標 ${hasTarget?fmt(r.target)+r.unit:'未設定'}　差分 <span class="${diffCls}">${diffTxt}</span></div>
      </div>
      ${gaugePct!==null?gaugeRing(gaugePct, {size:52, stroke:5}):''}
    </div>`;
  }).join('');
}

function renderExecTrendChart(){
  const el = document.getElementById('execTrendChart');
  const d = execMonthData();
  const dates = [...DAILY_DATES].filter(dt=>dt>=d.start && dt<=d.end).sort();
  if(!dates.length){ el.innerHTML = '<div class="topic-empty">データがありません</div>'; return; }
  let running = 0;
  const seiyakuCum = dates.map(dt=>{ running += DAILY_PERIODS[dt].totals.clo_seiyaku; return running; });
  const total = daysInMonthOf(d.end);
  const target = TARGETS.monthly.seiyaku || 0;
  const w = 760, h = 220, pad = 30;
  const maxY = Math.max(target, ...seiyakuCum, 1) * 1.1;
  const xAt = i => pad + i/(total-1||1) * (w-2*pad);
  const yAt = v => h-pad - v/maxY*(h-2*pad);
  const linePts = seiyakuCum.map((v,i)=>`${xAt(i)},${yAt(v)}`).join(' ');
  const idealPts = `${xAt(0)},${yAt(0)} ${xAt(total-1)},${yAt(target)}`;
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" style="width:100%; max-width:${w}px; height:auto;">
    <line x1="${pad}" y1="${h-pad}" x2="${w-pad}" y2="${h-pad}" stroke="var(--border)" />
    <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h-pad}" stroke="var(--border)" />
    <polyline points="${idealPts}" fill="none" stroke="var(--text-xs)" stroke-dasharray="4,4" stroke-width="1.5" />
    <polyline points="${linePts}" fill="none" stroke="var(--blue)" stroke-width="2.5" />
    <text x="${pad}" y="${pad-8}" font-size="11" fill="var(--text-sub)">成約数累計（実線）／理想進捗（点線・目標${target}件）</text>
  </svg>`;
}

function renderExecFunnelWeekly(){
  const weeks = last4Weeks();
  const table = document.getElementById('t-exec-funnelweekly');
  const apoSeries = weeks.map(w => WEEKLY_PERIODS[w.key].totals.apo_kakutoku);
  const seiSeries = weeks.map(w => WEEKLY_PERIODS[w.key].totals.clo_seiyaku);
  const trendEl = document.getElementById('execFunnelWeeklyTrend');
  if(trendEl){
    trendEl.innerHTML = `<div style="display:flex; gap:28px; align-items:center; flex-wrap:wrap;">
      <div><div style="font-size:11px; color:var(--text-sub); font-weight:600; margin-bottom:3px;">アポ数（直近4週）</div>${sparkline(apoSeries, {color:'var(--blue)'})}</div>
      <div><div style="font-size:11px; color:var(--text-sub); font-weight:600; margin-bottom:3px;">成約数（直近4週）</div>${sparkline(seiSeries, {color:'var(--success)'})}</div>
      <div style="font-size:11px; color:var(--text-xs);">商談数・アポ→商談・商談→成約は商談パイプラインデータ未取得のため「—」表示（Cyzen API連携フェーズ1で取得予定）</div>
    </div>`;
  }
  const thead = '<thead><tr><th>週</th><th class="num">アポ数</th><th class="num">商談数</th><th class="num">成約数</th>' +
    '<th class="num">アポ→商談</th><th class="num">商談→成約</th></tr></thead>';
  const tbody = '<tbody>' + weeks.map(w=>{
    const wd = WEEKLY_PERIODS[w.key];
    const apo = wd.totals.apo_kakutoku, sei = wd.totals.clo_seiyaku;
    return `<tr><td class="name">${escapeHtml(w.label)}</td><td class="num">${apo}</td>` +
      `<td class="num">—</td><td class="num">${sei}</td><td class="num">—</td><td class="num">—</td></tr>`;
  }).join('') + '</tbody>';
  table.innerHTML = thead + tbody;
}

function renderExecArea(){
  const table = document.getElementById('t-exec-area');
  const areas = Object.keys(TARGETS.area || {});
  const thead = '<thead><tr><th>エリア</th><th class="num">目標件数</th><th class="num">成約件数</th><th class="num">進捗率</th></tr></thead>';
  const rows = areas.map(a => `<tr><td class="name">${escapeHtml(a)}</td><td class="num">${TARGETS.area[a]}</td><td class="num">—</td><td class="num">—</td></tr>`);
  const targetSum = areas.reduce((s,a)=>s+(TARGETS.area[a]||0),0);
  rows.push(`<tr style="font-weight:700;"><td class="name">合計</td><td class="num">${targetSum}</td><td class="num">—</td><td class="num">—</td></tr>`);
  table.innerHTML = thead + '<tbody>' + rows.join('') + '</tbody>';
}

function renderExecFunnelDiagram(d, tot){
  const el = document.getElementById('execFunnelDiagram');
  if(!el) return;
  const stages = [];
  if(d.visits){
    stages.push({label:'訪問', icon:'📍', value:d.visits.total_spots});
    stages.push({label:'対面', icon:'🤝', value:d.visits.taimen_count});
  }
  stages.push({label:'アポ獲得', icon:'📞', value:tot.apo_kakutoku});
  stages.push({label:'成約', icon:'🏆', value:tot.clo_seiyaku});
  el.innerHTML = funnelChart(stages);
}

function renderExecFunnelCompare(){
  const table = document.getElementById('t-exec-funnelcompare');
  const d = execMonthData();
  const tot = d.totals;
  renderExecFunnelDiagram(d, tot);
  const fr = TARGETS.funnel_rate || {};
  const apoShodanActual = null; // 商談データ未取得
  const shodanSeiyakuActual = null;
  // 訪問→対面・対面→アポの実績転換率（2026-07-29追加）: スポット台帳(--spot-csv)由来。
  // 訪問→対面 = 対面数 ÷ 全スポット数（aggregate_visits()と同じ分母定義）。
  // 対面→アポ = アポ獲得数(既存aggregate()のapo_kakutoku合計) ÷ 対面数。
  const houmonTaimenActual = d.visits ? d.visits.taimen_rate : null;
  const taimenApoActual = (d.visits && d.visits.taimen_count) ? round1(tot.apo_kakutoku / d.visits.taimen_count * 100) : null;
  const rows = [
    {label:'訪問→対面', target: fr.houmon_taimen, actual: houmonTaimenActual,
      note: d.visits ? '' : 'スポット別集計データ未取得（--spot-csv未指定）'},
    {label:'対面→アポ', target: fr.taimen_apo, actual: taimenApoActual,
      note: d.visits ? '' : 'スポット別集計データ未取得（--spot-csv未指定）'},
    {label:'アポ→商談', target: fr.apo_shodan, actual: apoShodanActual, note:'商談パイプラインデータ未取得'},
    {label:'商談→成約', target: fr.shodan_seiyaku, actual: shodanSeiyakuActual, note:'商談パイプラインデータ未取得'},
  ];
  const thead = '<thead><tr><th>段階</th><th>目標比（バレットチャート）</th><th class="num">目標転換率</th><th class="num">実績転換率</th><th class="num">乖離(pt)</th></tr></thead>';
  const tbody = '<tbody>' + rows.map(r=>{
    const gap = (r.actual!==null && r.target!==null && r.target!==undefined) ? (r.actual - r.target) : null;
    return `<tr><td class="name">${r.label}</td>` +
      `<td>${bulletChart(r.actual, r.target, {unit:'%', fmt:v=>v.toFixed(1)})}</td>` +
      `<td class="num">${r.target===undefined||r.target===null?'—':r.target+'%'}</td>` +
      `<td class="num">${r.actual===null?'—':r.actual.toFixed(1)+'%'}${r.actual===null?`<div class="reason-text">${escapeHtml(r.note)}</div>`:''}</td>` +
      `<td class="num">${gap===null?'—':(gap>=0?'+':'')+gap.toFixed(1)+'pt'}</td></tr>`;
  }).join('') + '</tbody>';
  table.innerHTML = thead + tbody;
}

function renderExecHeatmap(){
  const el = document.getElementById('execHeatmap');
  if(!DOW_HOUR || !DOW_HOUR.available){
    el.innerHTML = `<div class="topic-empty">アポ獲得履歴に時刻列が無いため、曜日×時間帯ヒートマップは集計できません（データ未取得）。</div>`;
    return;
  }
  el.innerHTML = heatmapGrid(DOW_HOUR.dow_labels, DOW_HOUR.hour_labels, DOW_HOUR.grid, {cell:27});
}

function renderExecGap(){
  const rows = execKpiRows().filter(r=>r.primary && r.actual!==null && r.actual!==undefined && r.target);
  const table = document.getElementById('t-exec-gap');
  const thead = '<thead><tr><th>KPI</th><th class="num">目標</th><th class="num">実績</th><th class="num">ギャップ</th><th>打ち手（AI分析サマリー欄）</th></tr></thead>';
  const tbody = '<tbody>' + rows.map(r=>{
    const gap = r.actual - r.target;
    const fmt = v => r.fmt ? r.fmt(v) : v.toLocaleString('ja-JP');
    return `<tr><td class="name">${r.label}</td><td class="num">${fmt(r.target)}${r.unit}</td><td class="num">${fmt(r.actual)}${r.unit}</td>` +
      `<td class="num ${gap<0?'delta-down':'delta-up'}">${gap>=0?'+':''}${fmt(gap)}${r.unit}</td>` +
      `<td style="color:var(--text-sub); font-size:12px;">${AI_SUMMARY && AI_SUMMARY.next_actions && AI_SUMMARY.next_actions.length ? escapeHtml(AI_SUMMARY.next_actions[0]) : '（AI分析サマリー未取得・手動記入欄）'}</td></tr>`;
  }).join('') + '</tbody>';
  table.innerHTML = thead + tbody;
}

function renderTargetForm(){
  const el = document.getElementById('targetForm');
  const monthlyFields = [['seiyaku','成約数(件)'],['kanko','完工数(件)'],['uriage','売上(円)'],['chinin','稼働人員数(名)'],['apo','アポ数(件)'],['shodan','商談数(件)']];
  const areaFields = Object.keys(TARGETS.area || {});
  const funnelFields = [['houmon_taimen','訪問→対面(%)'],['taimen_apo','対面→アポ(%)'],['apo_shodan','アポ→商談(%)'],['shodan_seiyaku','商談→成約(%)']];
  const inputRow = (id, label, val) => `<label style="display:flex; flex-direction:column; gap:3px; font-size:11.5px; color:var(--text-sub);">${escapeHtml(label)}
    <input type="number" data-target-id="${id}" value="${val===undefined||val===null?'':val}" style="padding:6px 8px; border:1px solid var(--border); border-radius:6px; font-family:inherit; width:120px;"></label>`;
  el.innerHTML = `
    <div style="font-size:12px; font-weight:700; margin-bottom:6px;">月間目標</div>
    <div style="display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px;">${monthlyFields.map(([k,l])=>inputRow('monthly.'+k, l, TARGETS.monthly[k])).join('')}</div>
    <div style="font-size:12px; font-weight:700; margin-bottom:6px;">エリア別目標件数</div>
    <div style="display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px;">${areaFields.map(a=>inputRow('area.'+a, a, TARGETS.area[a])).join('')}</div>
    <div style="font-size:12px; font-weight:700; margin-bottom:6px;">ファネル目標転換率</div>
    <div style="display:flex; gap:14px; flex-wrap:wrap;">${funnelFields.map(([k,l])=>inputRow('funnel_rate.'+k, l, TARGETS.funnel_rate[k])).join('')}</div>
  `;
}

function readTargetForm(){
  const t = {monthly:{}, area:{}, funnel_rate:{}};
  document.querySelectorAll('#targetForm input[data-target-id]').forEach(inp=>{
    const [group, key] = inp.dataset.targetId.split('.');
    const v = inp.value === '' ? null : Number(inp.value);
    t[group][key] = v;
  });
  return t;
}

// ---------- 企業別目標の編集フォーム（2026-08-31追加） ----------
const COMPANY_TARGET_FIELDS = [['apo','目標アポ数'], ['seiyaku','目標成約数'], ['uriage','目標売上(円)'], ['chinin','目標稼働人員数']];
function renderCompanyTargetForm(companies){
  const el = document.getElementById('companyTargetForm');
  const inputCell = (company, key, val) => `<td><input type="number" data-ct-company="${escapeHtml(company)}" data-ct-key="${key}"
    value="${val===undefined||val===null?'':val}" style="width:100px; padding:5px 6px; border:1px solid var(--border); border-radius:6px; font-family:inherit;"></td>`;
  const rows = companies.map(company => {
    const t = COMPANY_TARGETS[company] || {};
    return `<tr><td class="name">${escapeHtml(company)}</td>${COMPANY_TARGET_FIELDS.map(([k])=>inputCell(company, k, t[k])).join('')}</tr>`;
  }).join('');
  el.innerHTML = `<thead><tr><th>会社名</th>${COMPANY_TARGET_FIELDS.map(([,l])=>`<th>${l}</th>`).join('')}</tr></thead><tbody>${rows}</tbody>`;
}
function readCompanyTargetForm(){
  const t = {};
  document.querySelectorAll('#companyTargetForm input[data-ct-company]').forEach(inp=>{
    const company = inp.dataset.ctCompany, key = inp.dataset.ctKey;
    const v = inp.value === '' ? null : Number(inp.value);
    t[company] = t[company] || {};
    t[company][key] = v;
  });
  return t;
}

// ---------- 行動分析タブ（Cyzen行動履歴＝ルート自動記録+訪問等イベントのGPS集計） ----------
let ROUTE_SELECTED_DAY = null;
let ROUTE_SELECTED_PERSON = null;

function routeDates(){
  return Object.keys(ROUTE_HISTORY || {}).sort().reverse();
}

function routeEventCounts(u){
  let visitCount = 0, apoCount = 0;
  (u.events || []).forEach(e=>{
    if(e.status && e.status.indexOf('訪問') === 0) visitCount++;
    if(e.status === 'アポ獲得') apoCount++;
  });
  return {visitCount, apoCount};
}

function renderRoute(){
  const dates = routeDates();
  if(!dates.length){
    document.getElementById('routeDaySelect').innerHTML = '<option>データなし</option>';
    document.getElementById('routePersonSelect').innerHTML = '';
    document.getElementById('routePersonMeta').textContent = '';
    document.getElementById('t-route').innerHTML = '';
    ['routeDayUsers','routeDayTotal','routeDayVisits','routeDayApo'].forEach(id=>{ document.getElementById(id).textContent = '—'; });
    const svg = document.getElementById('routeMap');
    svg.innerHTML = '';
    const t = document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x','450'); t.setAttribute('y','280'); t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#94A3B8'); t.setAttribute('font-size','14');
    t.textContent = '行動履歴データが未取得です（取得手順はSKILL.md参照）';
    svg.appendChild(t);
    return;
  }
  if(!ROUTE_SELECTED_DAY || !ROUTE_HISTORY[ROUTE_SELECTED_DAY]) ROUTE_SELECTED_DAY = dates[0];

  const daySelect = document.getElementById('routeDaySelect');
  daySelect.innerHTML = dates.map(d=>`<option value="${d}" ${d===ROUTE_SELECTED_DAY?'selected':''}>${d}</option>`).join('');
  daySelect.onchange = ()=>{ ROUTE_SELECTED_DAY = daySelect.value; ROUTE_SELECTED_PERSON = null; renderRoute(); };

  const dayData = ROUTE_HISTORY[ROUTE_SELECTED_DAY] || {};
  const names = Object.keys(dayData).sort((a,b)=>
    (dayData[a].company||'').localeCompare(dayData[b].company||'','ja') || a.localeCompare(b,'ja'));

  if(!names.length){
    document.getElementById('routePersonSelect').innerHTML = '<option>この日のデータなし</option>';
    ROUTE_SELECTED_PERSON = null;
  } else {
    if(!ROUTE_SELECTED_PERSON || !dayData[ROUTE_SELECTED_PERSON]) ROUTE_SELECTED_PERSON = names[0];
    const personSelect = document.getElementById('routePersonSelect');
    personSelect.innerHTML = names.map(n=>
      `<option value="${n}" ${n===ROUTE_SELECTED_PERSON?'selected':''}>${dayData[n].company} - ${n}</option>`).join('');
    personSelect.onchange = ()=>{ ROUTE_SELECTED_PERSON = personSelect.value; drawRouteMap(); updateRoutePersonMeta(); };
  }

  let totalRoute = 0, totalVisit = 0, totalApo = 0;
  names.forEach(n=>{
    const u = dayData[n];
    totalRoute += u.route_count || 0;
    const c = routeEventCounts(u);
    totalVisit += c.visitCount;
    totalApo += c.apoCount;
  });
  document.getElementById('routeDayUsers').textContent = yen(names.length);
  document.getElementById('routeDayTotal').textContent = yen(totalRoute);
  document.getElementById('routeDayVisits').textContent = yen(totalVisit);
  document.getElementById('routeDayApo').textContent = yen(totalApo);

  drawRouteMap();
  updateRoutePersonMeta();
  renderRouteTable(dayData, names);
}

function updateRoutePersonMeta(){
  const dayData = ROUTE_HISTORY[ROUTE_SELECTED_DAY] || {};
  const u = dayData[ROUTE_SELECTED_PERSON];
  const meta = document.getElementById('routePersonMeta');
  if(!u){ meta.textContent = ''; return; }
  const span = u.span_minutes != null ? Math.floor(u.span_minutes/60) + '時間' + (u.span_minutes%60) + '分' : '—';
  meta.textContent = '会社: ' + u.company + ' ｜ 稼働時間目安: ' + span + ' ｜ ルート打刻: ' + yen(u.route_count) + '件 ｜ 移動範囲目安: ' + (u.range_km != null ? u.range_km + 'km' : '—');
}

function drawRouteMap(){
  const svg = document.getElementById('routeMap');
  svg.innerHTML = '';
  const dayData = ROUTE_HISTORY[ROUTE_SELECTED_DAY] || {};
  const u = dayData[ROUTE_SELECTED_PERSON];
  const ns = 'http://www.w3.org/2000/svg';
  if(!u){
    const t = document.createElementNS(ns,'text');
    t.setAttribute('x','450'); t.setAttribute('y','280'); t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#94A3B8'); t.setAttribute('font-size','14');
    t.textContent = '担当者を選択してください';
    svg.appendChild(t);
    return;
  }
  const path = u.path || [];
  const events = u.events || [];
  const pts = [];
  path.forEach(p=> pts.push([p[0], p[1]]));
  events.forEach(e=>{ if(e.lat != null && e.lng != null) pts.push([e.lat, e.lng]); });
  if(!pts.length){
    const t = document.createElementNS(ns,'text');
    t.setAttribute('x','450'); t.setAttribute('y','280'); t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#94A3B8'); t.setAttribute('font-size','14');
    t.textContent = 'この担当者の当日分の位置情報がありません（出退勤打刻のみ・GPS権限オフ等の可能性）';
    svg.appendChild(t);
    return;
  }
  const lats = pts.map(p=>p[0]), lngs = pts.map(p=>p[1]);
  let minLat = Math.min(...lats), maxLat = Math.max(...lats), minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const padLat = Math.max((maxLat-minLat)*0.15, 0.004);
  const padLng = Math.max((maxLng-minLng)*0.15, 0.004);
  minLat -= padLat; maxLat += padLat; minLng -= padLng; maxLng += padLng;
  const W = 900, H = 560, M = 32;
  function project(lat, lng){
    const x = M + (lng-minLng)/(maxLng-minLng) * (W-2*M);
    const y = (H-M) - (lat-minLat)/(maxLat-minLat) * (H-2*M);
    return [x, y];
  }
  if(path.length > 1){
    const linePts = path.map(p=>project(p[0],p[1]).join(',')).join(' ');
    const poly = document.createElementNS(ns,'polyline');
    poly.setAttribute('points', linePts);
    poly.setAttribute('fill','none');
    poly.setAttribute('stroke','#93C5FD');
    poly.setAttribute('stroke-width','2');
    poly.setAttribute('stroke-linejoin','round');
    poly.setAttribute('opacity','0.85');
    svg.appendChild(poly);
    path.forEach((p,i)=>{
      const [x,y] = project(p[0], p[1]);
      const c = document.createElementNS(ns,'circle');
      c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', '2.5');
      c.setAttribute('fill', i===0 ? '#059669' : (i===path.length-1 ? '#DC2626' : '#60A5FA'));
      const title = document.createElementNS(ns,'title');
      title.textContent = p[2] + ' ルート自動記録';
      c.appendChild(title);
      svg.appendChild(c);
    });
  }
  const statusColor = (s)=>{
    if(s === 'アポ獲得') return '#059669';
    if(s && s.indexOf('訪問') === 0) return '#1A56DB';
    if(s === '出勤' || s === '勤務終了') return '#94A3B8';
    return '#D97706';
  };
  events.forEach(e=>{
    if(e.lat == null || e.lng == null) return;
    const [x,y] = project(e.lat, e.lng);
    const c = document.createElementNS(ns,'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', '6');
    c.setAttribute('fill', statusColor(e.status));
    c.setAttribute('stroke', '#fff'); c.setAttribute('stroke-width', '1.5');
    const title = document.createElementNS(ns,'title');
    title.textContent = e.t + ' ' + e.status + (e.spot ? (' / ' + e.spot) : '') + (e.loc ? (' / ' + e.loc) : '');
    c.appendChild(title);
    svg.appendChild(c);
  });
}

function renderRouteTable(dayData, names){
  const rows = names.map(n=>{
    const u = dayData[n];
    const c = routeEventCounts(u);
    return [u.company, n, u.route_count || 0, u.span_minutes, u.range_km, c.visitCount, c.apoCount];
  });
  renderTable('t-route', [
    {label:'会社'},
    {label:'担当者', cls:'clickable-name'},
    {label:'ルート打刻数', num:true},
    {label:'稼働時間目安', num:true, fmt:v=> v==null ? '—' : (Math.floor(v/60) + '時間' + (v%60) + '分')},
    {label:'移動範囲目安(km)', num:true, fmt:v=> v==null ? '—' : v},
    {label:'訪問イベント数', num:true},
    {label:'アポ獲得数', num:true},
  ], rows, {defaultSort:2, rowClick:(r)=>{
    ROUTE_SELECTED_PERSON = r[1];
    const sel = document.getElementById('routePersonSelect');
    if(sel) sel.value = r[1];
    drawRouteMap();
    updateRoutePersonMeta();
  }});
}

// ---------- 傾向分析タブ ----------
function renderTrend(){
  renderTrendWeekend();
  renderTrendArea();
  renderTrendTop();
  renderTrainingEffect();
  renderTenureAnalysis();
}

// ---------- ⑤ 在籍期間別の成績分析（2026-08-31追加） ----------
// 当月実績(PERIODS.month)を対象に、アポインター/クローザーそれぞれ本人の役割の指標(アポ数/クロ成約数)で
// 在籍区分(新人/中堅/ベテラン/不明)ごとに合算する。表示期間ピッカーとは連動しない独立集計。
function tenureBucketOf(name){
  const t = TENURE_BY_NAME.get(normNameJs(name));
  return t ? t.bucket : 'unknown';
}
function summarizeByTenure(rows, countIdx){
  const buckets = {new:{n:0, total:0}, mid:{n:0, total:0}, veteran:{n:0, total:0}, unknown:{n:0, total:0}};
  rows.forEach(r=>{
    const b = tenureBucketOf(r[1]);
    buckets[b].n++;
    buckets[b].total += r[countIdx] || 0;
  });
  return buckets;
}
function renderTenureAnalysis(){
  document.getElementById('tenureNewDays').textContent = TENURE.new_hire_days ?? '90';
  document.getElementById('tenureMidDays').textContent = TENURE.mid_days ?? '365';
  const wrap = document.getElementById('tenureAnalysisWrap');
  if(!TENURE.people || !Object.keys(TENURE.people).length){
    wrap.innerHTML = '<div class="note">在籍期間データが未取得です（--tenure-json未指定）。</div>';
    return;
  }
  const m = PERIODS.month;
  const apoBuckets = summarizeByTenure(m.apo_ranking, 4);      // r[4] = アポ数
  const closerBuckets = summarizeByTenure(m.closer_ranking, 3); // r[3] = クロ成約数
  const labels = [['new','🌱新人'], ['mid','中堅'], ['veteran','ベテラン'], ['unknown','不明（未取得）']];
  const row = (label, key) => {
    const a = apoBuckets[key], c = closerBuckets[key];
    const avgApo = a.n ? round1(a.total/a.n) : '—';
    const avgClo = c.n ? round1(c.total/c.n) : '—';
    return `<tr><td class="name">${label}</td>
      <td class="num">${a.n}名</td><td class="num">${a.total}件</td><td class="num">${avgApo}</td>
      <td class="num">${c.n}名</td><td class="num">${c.total}件</td><td class="num">${avgClo}</td></tr>`;
  };
  wrap.innerHTML = `<div class="card"><div class="tablewrap"><table>
    <thead><tr><th>在籍区分</th>
      <th class="num">アポインター人数</th><th class="num">アポ数合計</th><th class="num">1人あたり平均</th>
      <th class="num">クローザー人数</th><th class="num">クロ成約数合計</th><th class="num">1人あたり平均</th>
    </tr></thead>
    <tbody>${labels.map(([k,l])=>row(l,k)).join('')}</tbody>
  </table></div></div>
  <div class="note" style="margin-top:8px;">「不明（未取得）」はCyzenアカウント名がロースター/獲得報告データの表記と一致しなかった人、またはCyzenアカウント作成日が取得できなかった人です。名前の表記ゆれが原因の場合があります。</div>`;
}

// ---------- ④ 研修効果モニタリング（2026-08-04追加） ----------
// 研修実施日の前後1週間で、対象者の アポ数・スポット作成数・ルート自動記録数・出退勤打刻日数 を
// DAILY_PERIODS/ROUTE_HISTORYから日別に積み上げて比較する。研修後が「進行中」（1週間経っていない）
// 場合は取得できている日数分だけで集計し、その旨を明示する（黙って7日分と偽らない）。
function dateRangeAround(centerYMD, daysBefore, daysAfter){
  const center = dateFromYMD(centerYMD);
  const before = [];
  for(let i=daysBefore; i>=1; i--){
    const d = new Date(center.getFullYear(), center.getMonth(), center.getDate()-i);
    before.push(fmtYMD(d));
  }
  // 「後」は研修実施当日を含む（当日〜daysAfter-1日後）。「前」は実施日を含まない直近daysBefore日間。
  const after = [];
  for(let i=0; i<daysAfter; i++){
    const d = new Date(center.getFullYear(), center.getMonth(), center.getDate()+i);
    after.push(fmtYMD(d));
  }
  return {before, after};
}
// dates: 'YYYY/MM/DD'配列, normNames: normNameJs済みの氏名配列 → Map(normName -> {apo,spot,route,attendedDays})
function trainingWindowStats(dates, normNames){
  const acc = new Map(normNames.map(n=>[n, {apo:0, spot:0, route:0, attendedDays:0}]));
  dates.forEach(date=>{
    const dp = DAILY_PERIODS[date];
    if(!dp) return;
    const apoByNorm = new Map((dp.apo_ranking||[]).map(r=>[normNameJs(r[1]), r]));
    const attendedSet = new Set((dp.attendance_person_rows||[]).map(r=>normNameJs(r[0])));
    const routeDay = (ROUTE_HISTORY||{})[date.replaceAll('/','-')] || {};
    const routeByNorm = new Map(Object.keys(routeDay).map(n=>[normNameJs(n), routeDay[n]]));
    normNames.forEach(n=>{
      const rec = acc.get(n);
      const apoRow = apoByNorm.get(n);
      if(apoRow) rec.apo += apoRow[4] || 0;
      const pv = (dp.visits && dp.visits.person) ? dp.visits.person[n] : null;
      if(pv) rec.spot += (pv.new_visit_count||0) + (pv.revisit_count||0);
      const rt = routeByNorm.get(n);
      if(rt) rec.route += rt.route_count || 0;
      if(attendedSet.has(n)) rec.attendedDays++;
    });
  });
  return acc;
}
function pctDeltaTxt(before, after){
  if(!before) return after>0 ? '<span class="delta-up">新規発生</span>' : '<span class="pill flat">—</span>';
  const pct = round1((after-before)/before*100);
  const cls = pct>=0 ? 'delta-up' : 'delta-down';
  return `<span class="${cls}">${pct>=0?'+':''}${pct}%</span>`;
}
function groupTrainingSummary(names, beforeDates, afterDates){
  const normNames = names.map(normNameJs);
  const b = trainingWindowStats(beforeDates, normNames);
  const a = trainingWindowStats(afterDates, normNames);
  const sum = {n: names.length, apoB:0, apoA:0, spotB:0, spotA:0, routeB:0, routeA:0, attB:0, attA:0};
  normNames.forEach(n=>{
    const bb=b.get(n), aa=a.get(n);
    sum.apoB+=bb.apo; sum.apoA+=aa.apo; sum.spotB+=bb.spot; sum.spotA+=aa.spot;
    sum.routeB+=bb.route; sum.routeA+=aa.route; sum.attB+=bb.attendedDays; sum.attA+=aa.attendedDays;
  });
  return sum;
}
function renderOneTrainingEffect(tr){
  const allTargets = URGENT_TARGETS.targets || [];
  if(!allTargets.length){
    return `<div class="note">役員会ターゲットデータが未取得のため、研修効果の参加/欠席グループ比較は表示できません。</div>`;
  }
  const attendedNormSet = new Set((tr.participants||[]).map(normNameJs));
  const attendedTargets = allTargets.filter(t=>attendedNormSet.has(normNameJs(t.name)));
  const absentTargets = allTargets.filter(t=>!attendedNormSet.has(normNameJs(t.name)));

  const {before, after} = dateRangeAround(tr.date, 7, 7);
  const todayStr = DAILY_DATES[0] || null;
  const afterAvailable = todayStr ? after.filter(d => d <= todayStr) : [];
  const isPartial = afterAvailable.length < after.length;

  const gAttended = groupTrainingSummary(attendedTargets.map(t=>t.name), before, afterAvailable);
  const gAbsent = groupTrainingSummary(absentTargets.map(t=>t.name), before, afterAvailable);

  const groupRow = (label, g) => `<tr><td class="name">${label}（${g.n}名）</td>` +
    `<td class="num">${g.apoB}件</td><td class="num">${g.apoA}件</td><td class="num">${pctDeltaTxt(g.apoB, g.apoA)}</td>` +
    `<td class="num">${g.spotB}件</td><td class="num">${g.spotA}件</td><td class="num">${pctDeltaTxt(g.spotB, g.spotA)}</td>` +
    `<td class="num">${g.routeB}件</td><td class="num">${g.routeA}件</td><td class="num">${pctDeltaTxt(g.routeB, g.routeA)}</td>` +
    `<td class="num">${g.attB}日</td><td class="num">${g.attA}日</td></tr>`;

  const summaryTable = `<div class="tablewrap"><table>
    <thead><tr><th>グループ</th>
      <th class="num">アポ数(前)</th><th class="num">アポ数(後)</th><th class="num">増減</th>
      <th class="num">スポット作成(前)</th><th class="num">スポット作成(後)</th><th class="num">増減</th>
      <th class="num">ルート記録(前)</th><th class="num">ルート記録(後)</th><th class="num">増減</th>
      <th class="num">出勤日数(前・合計)</th><th class="num">出勤日数(後・合計)</th>
    </tr></thead>
    <tbody>${groupRow('研修参加', gAttended)}${groupRow('研修欠席', gAbsent)}</tbody>
  </table></div>`;

  const normNamesAttended = attendedTargets.map(t=>normNameJs(t.name));
  const bStats = trainingWindowStats(before, normNamesAttended);
  const aStats = trainingWindowStats(afterAvailable, normNamesAttended);
  const personRows = attendedTargets.map(t=>{
    const n = normNameJs(t.name);
    const b = bStats.get(n), a = aStats.get(n);
    return `<tr>
      <td class="name">${escapeHtml(t.name)}</td>
      <td>${escapeHtml(t.company || t.company_auto_resolved || '（不明）')}${t.company_confirmed?'':'<span class="sub" style="font-size:11px;">(自動推定)</span>'}</td>
      <td>${t.category}(#${t.rank_in_category})</td>
      <td class="num">${b.apo}件</td><td class="num">${a.apo}件</td><td class="num">${pctDeltaTxt(b.apo, a.apo)}</td>
      <td class="num">${b.spot}件</td><td class="num">${a.spot}件</td>
      <td class="num">${b.route}件</td><td class="num">${a.route}件</td>
      <td class="num">${b.attendedDays}/7日</td><td class="num">${a.attendedDays}/${afterAvailable.length}日</td>
    </tr>`;
  }).join('');
  const personTable = `<div class="tablewrap"><table>
    <thead><tr><th>氏名</th><th>会社</th><th>カテゴリ</th>
      <th class="num">アポ数(前)</th><th class="num">アポ数(後)</th><th class="num">増減</th>
      <th class="num">スポット作成(前)</th><th class="num">スポット作成(後)</th>
      <th class="num">ルート記録(前)</th><th class="num">ルート記録(後)</th>
      <th class="num">出勤日数(前)</th><th class="num">出勤日数(後)</th>
    </tr></thead>
    <tbody>${personRows}</tbody>
  </table></div>`;

  return `
    <div class="note" style="margin-bottom:10px;">
      <b>${escapeHtml(tr.label)}</b>（${tr.date}実施）— 前後1週間比較（前: ${before[0]}〜${before[before.length-1]}／
      後: ${afterAvailable.length?afterAvailable[0]+'〜'+afterAvailable[afterAvailable.length-1]:'データなし'}
      ${isPartial?`・研修後は${afterAvailable.length}/7日分のみ取得済み＝進行中）`:'）'}
      対象は役員会急落・下降ターゲット32名（研修参加${attendedTargets.length}名／欠席${absentTargets.length}名）。
      一般参加者がいた場合はこのデータに含まれません。
    </div>
    <div class="card" style="margin-bottom:12px;">${summaryTable}</div>
    <div class="table-caption">研修参加者${attendedTargets.length}名の個人別内訳</div>
    <div class="card" style="margin-bottom:16px;">${personTable}</div>
  `;
}
function renderTrainingEffect(){
  const wrap = document.getElementById('trainingEffectWrap');
  const trainings = TRAINING.trainings || [];
  if(!trainings.length){
    wrap.innerHTML = '<div class="note">研修参加者データが未取得です（--training-json未指定）。</div>';
    return;
  }
  wrap.innerHTML = trainings.map(tr => renderOneTrainingEffect(tr)).join('');
}

function renderTrendWeekend(){
  const rows = (TREND.weekend_comparison || []).map(w=>[
    w.month, w.start + '〜' + w.end + (w.partial ? '（進行中）' : ''),
    w.apo_kakutoku,
    w.seiyaku_data_available ? w.apo_seiyaku : null,
    w.seiyaku_data_available ? w.clo_seiyaku : null,
    w.seiyaku_data_available ? w.uriage : null,
    w.seiyaku_data_available ? w.rate : null,
  ]);
  renderTable('t-trend-weekend', [
    {label:'月'},
    {label:'対象期間'},
    {label:'アポ獲得', num:true},
    {label:'アポ成約', num:true, fmt:v=> v==null ? '—' : yen(v)},
    {label:'クロ成約', num:true, fmt:v=> v==null ? '—' : yen(v)},
    {label:'売上', num:true, fmt:v=> v==null ? '—' : yen(v) + '円'},
    {label:'成約率', num:true, fmt:v=> v==null ? '—' : v + '%'},
  ], rows, {defaultSort:0});
}

function renderTrendArea(){
  const g = TREND.area_time_grid;
  const meta = document.getElementById('trendAreaMeta');
  if(!g || !g.areas || !g.areas.length){
    meta.textContent = '行動履歴データがまだありません。';
    document.getElementById('t-trend-area').innerHTML = '';
    return;
  }
  meta.textContent = `集計対象: ${g.dates_covered[0]}〜${g.dates_covered[g.dates_covered.length-1]}（延べ訪問${yen(g.total_visit)}件・アポ獲得${yen(g.total_apo)}件）`;
  const cellMap = new Map();
  g.grid.forEach(c=> cellMap.set(c.area + '|' + c.hour, c));
  const table = document.getElementById('t-trend-area');
  let thead = '<thead><tr><th>エリア</th>' + g.hours.map(h=>`<th>${h}</th>`).join('') + '</tr></thead>';
  let tbody = '<tbody>' + g.areas.map(area=>{
    const cells = g.hours.map(h=>{
      const c = cellMap.get(area + '|' + h) || {visit:0, apo:0, rate:null};
      if(c.visit === 0) return '<td class="num" style="color:var(--text-xs);">—</td>';
      const rateTxt = c.rate==null ? '' : ` (${c.rate}%)`;
      const bg = c.rate==null ? '' : `background:rgba(26,86,219,${Math.min(c.rate/40,1)*0.35});`;
      return `<td class="num" style="${bg}">${c.visit}${c.apo?'（'+c.apo+'件'+rateTxt+'）':''}</td>`;
    }).join('');
    return `<tr><td>${escapeHtml(area)}</td>${cells}</tr>`;
  }).join('') + '</tbody>';
  table.innerHTML = thead + tbody;
}

function renderTrendTop(){
  const t = TREND.top_performer_patterns;
  const wrap = document.getElementById('trendTopWrap');
  if(!t || !t.available || !t.top_stats || !t.all_stats){
    wrap.innerHTML = '<div class="note">行動履歴と獲得実績の両方が揃っている月がまだありません。</div>';
    return;
  }
  const rows = [
    ['対象人日数', t.top_stats.n_people_days, t.all_stats.n_people_days],
    ['ルート自動記録数/日', t.top_stats.avg_route_count, t.all_stats.avg_route_count],
    ['稼働時間目安（分）/日', t.top_stats.avg_span_minutes, t.all_stats.avg_span_minutes],
    ['移動範囲目安（km）/日', t.top_stats.avg_range_km, t.all_stats.avg_range_km],
    ['訪問イベント数/日', t.top_stats.avg_visit_count, t.all_stats.avg_visit_count],
    ['アポ獲得数/日', t.top_stats.avg_apo_count, t.all_stats.avg_apo_count],
    ['アポ獲得が多い時間帯', t.top_stats.common_apo_hour ?? '—', t.all_stats.common_apo_hour ?? '—'],
  ];
  const tableRows = rows.map(([label, topV, allV])=>{
    let diffTxt = '';
    if(typeof topV === 'number' && typeof allV === 'number' && allV !== 0){
      const diffPct = Math.round((topV - allV) / allV * 100);
      diffTxt = diffPct === 0 ? '±0%' : (diffPct > 0 ? `+${diffPct}%` : `${diffPct}%`);
    }
    return `<tr><td>${label}</td><td class="num">${topV}</td><td class="num">${allV}</td><td class="num">${diffTxt}</td></tr>`;
  }).join('');
  wrap.innerHTML = `
    <div class="note" style="margin-bottom:10px;">対象月: ${t.month}（行動履歴データが蓄積されている最新月）。好成績者＝この月のアポ成約 or クロ成約が多い上位${t.top_n_requested}名（${t.top_names.length}名該当）。</div>
    <div class="card"><div class="tablewrap"><table>
      <thead><tr><th>指標</th><th>好成績者平均</th><th>全体平均</th><th>差分</th></tr></thead>
      <tbody>${tableRows}</tbody>
    </table></div></div>
    <div class="note" style="margin-top:10px;">好成績者: ${t.top_names.map(escapeHtml).join('、')}</div>
  `;
}

let DECLINE_ROLE_FILTER = 'all'; // 'all' | 'apo' | 'clo'

function renderDecline(){
  const meta = document.getElementById('declineMeta');
  const roleFilterWrap = document.getElementById('declineRoleFilter');
  const tiles = document.getElementById('declineTiles');
  const chartWrap = document.getElementById('declineChart');
  if(!DECLINING || !DECLINING.rows){
    meta.textContent = '出退勤/GPSデータが未取得のため、下落メンバー検知は実行されていません。';
    roleFilterWrap.innerHTML = ''; tiles.innerHTML = ''; chartWrap.innerHTML = '';
    renderTable('t-decline', [{label:'氏名'}], [], {});
    return;
  }
  const allRows = DECLINING.rows;
  meta.textContent = `基準期間: ${DECLINING.baseline_start}〜${DECLINING.baseline_end}（週平均に正規化） / 比較期間: ${DECLINING.recent_start}〜${DECLINING.recent_end}（直近週）。基準期間の週平均が1件以上あった人のうち、直近週がその50%以下のまま戻っていない人を検知しています。アポインターはアポ獲得数、クローザーはクロ成約数、それぞれ本人の役割に応じた指標だけで判定しています（どちらも兼務の人は両方独立に判定）。日次のダッシュボード更新のたびに自動で再計算されます。`;

  const roleFilterDefs = [
    {key:'all', label:'すべて', filter: r=>true},
    {key:'apo', label:'アポインター視点（アポ獲得数で判定）', filter: r=> r['アポ低下フラグ']},
    {key:'clo', label:'クローザー視点（クロ成約数で判定）', filter: r=> r['クロ成約低下フラグ']},
  ];
  roleFilterWrap.innerHTML = roleFilterDefs.map(d=>
    `<span class="breakdown-item clickable-chip${DECLINE_ROLE_FILTER===d.key?' active':''}" data-role="${d.key}">${escapeHtml(d.label)}</span>`
  ).join('');
  roleFilterWrap.querySelectorAll('.clickable-chip').forEach(chip=>{
    chip.addEventListener('click', ()=>{
      DECLINE_ROLE_FILTER = chip.dataset.role;
      renderDecline();
    });
  });

  const activeDef = roleFilterDefs.find(d=>d.key===DECLINE_ROLE_FILTER);
  const rows = allRows.filter(activeDef.filter);

  const active = rows.filter(r=> r['直近週稼働(出退勤/GPS)']==='○');
  const inactive = rows.filter(r=> r['直近週稼働(出退勤/GPS)']==='×');
  const apoDecline = allRows.filter(r=> r['アポ低下フラグ']).length;
  const cloDecline = allRows.filter(r=> r['クロ成約低下フラグ']).length;

  tiles.innerHTML = `
    <div class="tile clickable" data-decline-tile="filtered"><div class="label">${DECLINE_ROLE_FILTER==='all'?'下落メンバー該当数':activeDef.label}</div><div class="value">${rows.length}<span class="unit">名</span></div><div class="sub">基準期間比50%以下のまま未回復</div></div>
    <div class="tile clickable" data-decline-tile="active" style="background:var(--warn-bg);"><div class="label">寺子屋対象（直近週も稼働中）</div><div class="value" style="color:var(--warn);">${active.length}<span class="unit">名</span></div><div class="sub">稼働中だが数値が戻っていない人（現在の絞り込み内）</div></div>
    <div class="tile clickable" data-decline-tile="inactive"><div class="label">要本人確認（Cyzen上活動停止）</div><div class="value">${inactive.length}<span class="unit">名</span></div><div class="sub">寺子屋より先に稼働実態の確認が必要（現在の絞り込み内）</div></div>
    <div class="tile clickable" data-decline-tile="apoAll"><div class="label">アポ低下（全体）</div><div class="value">${apoDecline}<span class="unit">名</span></div><div class="sub">役割がアポインター/どちらもで、アポ獲得数が基準の50%以下</div></div>
    <div class="tile clickable" data-decline-tile="cloAll"><div class="label">クロ成約低下（全体）</div><div class="value">${cloDecline}<span class="unit">名</span></div><div class="sub">役割がクローザー/どちらもで、クロ成約数が基準の50%以下</div></div>
  `;
  const declineTileDefs = {
    filtered: {title: DECLINE_ROLE_FILTER==='all'?'下落メンバー該当数':activeDef.label, rows: rows},
    active: {title: '寺子屋対象（直近週も稼働中）', rows: active},
    inactive: {title: '要本人確認（Cyzen上活動停止）', rows: inactive},
    apoAll: {title: 'アポ低下（全体）', rows: allRows.filter(r=> r['アポ低下フラグ'])},
    cloAll: {title: 'クロ成約低下（全体）', rows: allRows.filter(r=> r['クロ成約低下フラグ'])},
  };
  tiles.querySelectorAll('[data-decline-tile]').forEach(tile=>{
    tile.style.cursor = 'pointer';
    tile.addEventListener('click', ()=>{
      const def = declineTileDefs[tile.dataset.declineTile];
      openDeclinePeopleDrilldown(def.title, def.rows);
    });
  });

  const byCompany = new Map();
  rows.forEach(r=>{
    const co = r['所属会社'] || '（不明）';
    byCompany.set(co, (byCompany.get(co)||0) + 1);
  });
  const companyRows = [...byCompany.entries()].sort((a,b)=> b[1]-a[1]);
  const maxCount = Math.max(...companyRows.map(r=>r[1]), 1);
  chartWrap.innerHTML = companyRows.length ? (`<div class="card" style="padding:14px 18px;">` + companyRows.map(([co, n])=>{
    const pct = Math.round(n / maxCount * 100);
    return `<div class="decline-bar-row" data-company="${escapeHtml(co)}" style="display:flex; align-items:center; gap:10px; margin:6px 0; font-size:12px; cursor:pointer;">
      <div style="width:180px; flex-shrink:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(co)}</div>
      <div style="flex:1; background:var(--slate); border-radius:4px; height:16px; position:relative;">
        <div style="width:${pct}%; background:var(--blue); height:100%; border-radius:4px;"></div>
      </div>
      <div style="width:28px; text-align:right; flex-shrink:0;">${n}</div>
    </div>`;
  }).join('') + `</div>`) : '<div class="note">該当者なし</div>';
  chartWrap.querySelectorAll('.decline-bar-row').forEach(row=>{
    row.addEventListener('mouseenter', ()=> row.style.opacity = '0.75');
    row.addEventListener('mouseleave', ()=> row.style.opacity = '1');
    row.addEventListener('click', ()=> openDeclineCompanyDrilldown(row.dataset.company, rows));
  });

  const tableRows = rows.map(r=>[
    r['氏名'], r['所属会社'], r['役割区分'], r['評価軸'], r['要因分類'],
    r['基準週平均アポ獲得数'], r['直近週アポ獲得数'],
    r['基準週平均成約数(クロ側)'], r['直近週成約数(クロ側)'],
    r['基準週平均成約数(アポ側・参考)'], r['直近週成約数(アポ側・参考)'],
    r['直近週稼働(出退勤/GPS)'],
  ]);
  renderTable('t-decline', [
    {label:'氏名'}, {label:'所属会社'}, {label:'役割区分'}, {label:'評価軸'}, {label:'要因分類'},
    {label:'基準週平均アポ', num:true}, {label:'直近週アポ', num:true},
    {label:'基準週平均クロ成約', num:true}, {label:'直近週クロ成約', num:true},
    {label:'基準週平均成約(アポ側・参考)', num:true}, {label:'直近週成約(アポ側・参考)', num:true},
    {label:'直近週稼働', cls:'', fmt:v=> v==='○' ? '<span style="color:var(--success);">○</span>' : '<span style="color:var(--text-xs);">×</span>'},
  ], tableRows, {defaultSort:5});
}

// ---------- 下落メンバー：会社別バークリック→対象者内訳（既存drillModalを流用） ----------
function _fillDeclineDrillTable(people, includeCompanyCol){
  const table = document.getElementById('drillTable');
  const cols = ['名前'];
  if(includeCompanyCol) cols.push('所属会社');
  cols.push('役割区分','評価軸','要因分類','基準週平均アポ','直近週アポ','基準週平均クロ成約','直近週クロ成約','基準週平均成約(アポ側・参考)','直近週成約(アポ側・参考)','直近週稼働');
  const numCols = new Set(['基準週平均アポ','直近週アポ','基準週平均クロ成約','直近週クロ成約','基準週平均成約(アポ側・参考)','直近週成約(アポ側・参考)']);
  const thead = '<thead><tr>' + cols.map(c=>`<th class="${numCols.has(c)?'num':''}">${c}</th>`).join('') + '</tr></thead>';
  const tbody = '<tbody>' + (people.length ? people.map(p=>{
    const active = p['直近週稼働(出退勤/GPS)'] === '○';
    let row = `<tr><td class="name clickable-name" data-name="${escapeHtml(p['氏名'])}">${escapeHtml(p['氏名'])}</td>`;
    if(includeCompanyCol) row += `<td>${escapeHtml(p['所属会社']||'')}</td>`;
    row += `<td>${escapeHtml(p['役割区分']||'')}</td><td>${escapeHtml(p['評価軸']||'')}</td><td>${escapeHtml(p['要因分類']||'')}</td>` +
      `<td class="num">${p['基準週平均アポ獲得数']}</td><td class="num">${p['直近週アポ獲得数']}</td>` +
      `<td class="num">${p['基準週平均成約数(クロ側)']}</td><td class="num">${p['直近週成約数(クロ側)']}</td>` +
      `<td class="num">${p['基準週平均成約数(アポ側・参考)']}</td><td class="num">${p['直近週成約数(アポ側・参考)']}</td>` +
      `<td>${active ? '<span style="color:var(--success);">○</span>' : '<span style="color:var(--text-xs);">×</span>'}</td></tr>`;
    return row;
  }).join('') : `<tr><td colspan="${cols.length}" style="text-align:center;color:var(--text-sub);">対象者なし</td></tr>`) + '</tbody>';
  table.innerHTML = thead + tbody;
  table.querySelectorAll('.clickable-name').forEach(td=>{
    td.addEventListener('click', ()=> openPersonDetail(td.dataset.name));
  });
  document.getElementById('drillModal').classList.add('show');
}

function openDeclineCompanyDrilldown(company, rows){
  const people = rows.filter(r=> (r['所属会社']||'（不明）') === company);
  document.getElementById('drillTitle').textContent = company;
  document.getElementById('drillSub').textContent =
    `下落メンバー ${people.length}名／基準期間: ${DECLINING.baseline_start}〜${DECLINING.baseline_end}（週平均） vs 直近週: ${DECLINING.recent_start}〜${DECLINING.recent_end}`;
  _fillDeclineDrillTable(people, false);
}

function openDeclinePeopleDrilldown(title, people){
  document.getElementById('drillTitle').textContent = title;
  document.getElementById('drillSub').textContent =
    `${people.length}名／基準期間: ${DECLINING.baseline_start}〜${DECLINING.baseline_end}（週平均） vs 直近週: ${DECLINING.recent_start}〜${DECLINING.recent_end}`;
  _fillDeclineDrillTable(people, true);
}

function renderExecTab(){
  renderExecSummary();
  renderExecHeadcountRate();
  renderExecWeekly();
  renderKawakamiWeeklyCard();
  renderExecForecast();
  renderExecTrendChart();
  renderExecFunnelWeekly();
  renderExecArea();
  renderExecFunnelCompare();
  renderExecHeatmap();
  renderExecGap();
}

renderTargetForm();
document.getElementById('targetSaveBtn').addEventListener('click', ()=>{
  TARGETS = readTargetForm();
  saveTargets(TARGETS);
  renderExecTab();
  const msg = document.getElementById('targetSavedMsg');
  msg.style.display = 'inline';
  setTimeout(()=>{ msg.style.display = 'none'; }, 2500);
});
document.getElementById('targetResetBtn').addEventListener('click', ()=>{
  localStorage.removeItem(TARGETS_STORAGE_KEY);
  TARGETS = loadTargets();
  renderTargetForm();
  renderExecTab();
});

document.getElementById('companyTargetSaveBtn').addEventListener('click', ()=>{
  COMPANY_TARGETS = readCompanyTargetForm();
  saveCompanyTargets(COMPANY_TARGETS);
  renderAllTables();
  const msg = document.getElementById('companyTargetSavedMsg');
  msg.style.display = 'inline';
  setTimeout(()=>{ msg.style.display = 'none'; }, 2500);
});
document.getElementById('companyTargetResetBtn').addEventListener('click', ()=>{
  localStorage.removeItem(COMPANY_TARGETS_STORAGE_KEY);
  COMPANY_TARGETS = loadCompanyTargets();
  renderAllTables();
});
document.getElementById('companyTargetExportBtn').addEventListener('click', async ()=>{
  const btn = document.getElementById('companyTargetExportBtn');
  COMPANY_TARGETS = readCompanyTargetForm();
  await saveWithFallback(btn, 'company_targets.json', JSON.stringify(COMPANY_TARGETS, null, 1));
});

function renderOutreach(){
  if(!OUTREACH){
    document.getElementById('p-outreach').innerHTML = '<div class="note">開拓先パートナーのデータが未取得です。</div>';
    return;
  }
  const s = OUTREACH.summary;
  document.getElementById('outTotal').textContent = yen(s.total);
  document.getElementById('outActive').textContent = yen(s.active_target_count);
  document.getElementById('outUncontacted').textContent = yen(s.uncontacted_active_count);
  document.getElementById('outDm7d').textContent = yen(s.dm_sent_last_7d);
  document.getElementById('outResp7d').textContent = yen(s.response_updated_last_7d);
  document.getElementById('outUpdated').textContent = s.updated;

  const respRows = Object.entries(s.by_response).sort((a,b)=>b[1]-a[1]);
  const chipsHtml = respRows.map(([k,v])=>
    `<span class="breakdown-item clickable-chip" data-status="${escapeHtml(k)}">${escapeHtml(k)}: <b>${v}</b></span>`
  ).join('') + `<span class="breakdown-item clickable-chip" data-status="">すべて解除（優先順位付けリストに戻す）</span>`;
  document.getElementById('outResponseBreakdown').innerHTML = chipsHtml;
  document.querySelectorAll('#outResponseBreakdown .clickable-chip').forEach(chip=>{
    chip.addEventListener('click', ()=>{
      OUTREACH_FILTER = chip.dataset.status || null;
      document.querySelectorAll('#outResponseBreakdown .clickable-chip').forEach(c=>c.classList.remove('active'));
      chip.classList.add('active');
      renderOutreachTable();
    });
  });

  renderOutreachTable();
}

function escapeHtmlBr(s){ return escapeHtml(s).split(String.fromCharCode(10)).join('<br>'); }

function openOutreachDetail(c){
  document.getElementById('drillTitle').textContent = c.company;
  document.getElementById('drillSub').textContent = c.url ? '' : '';
  const table = document.getElementById('drillTable');
  const rows = [
    ['優先度', c.priority], ['反応', c.response], ['積極アプローチ対象', c.active_target ? 'YES' : 'NO'],
    ['送付パターン', c.send_pattern], ['エリア', c.area], ['事業内容', c.business],
    ['フォロワー', c.followers], ['フォローバック有無', c.followback], ['発見経路', c.discovery],
    ['該当キーワード', c.keyword], ['リスト追加日', c.added || '—'],
    ['DM送付日時', c.dm_sent_at || '—'], ['反応更新日', c.response_updated_at || '—'],
    ['返信内容', c.reply_summary ? escapeHtmlBr(c.reply_summary) : '—'],
    ['備考', c.note ? escapeHtmlBr(c.note) : '—'],
  ];
  let bodyRows = rows.map(([k,v])=>{
    const val = (k==='返信内容'||k==='備考') ? v : escapeHtml(v);
    return `<tr><td class="name">${escapeHtml(k)}</td><td>${val}</td></tr>`;
  }).join('');
  if(c.sns){
    bodyRows += `<tr><td class="name">SNS(Instagram等)</td><td><a href="${c.sns.replace(/"/g,'&quot;')}" target="_blank" rel="noopener">${escapeHtml(c.sns)} →</a></td></tr>`;
  }
  if(c.url){
    bodyRows += `<tr><td class="name">Notion</td><td><a href="${c.url.replace(/"/g,'&quot;')}" target="_blank" rel="noopener">Notionで開く →</a></td></tr>`;
  }
  table.innerHTML = '<thead><tr><th>項目</th><th>内容</th></tr></thead><tbody>' + bodyRows + '</tbody>';
  document.getElementById('drillModal').classList.add('show');
}
const ORIGINAL_TITLE = document.title;

function updateTitleForActiveTab(){
  const active = document.querySelector('.tab.active');
  const label = active ? TAB_LABELS[active.dataset.panel] : '';
  const d = currentData();
  const period = (d.start + '_' + d.end).replaceAll('/', '-');
  document.title = `パートナー_${label}_${period}`;
}

function switchPeriod(period){
  CURRENT_PERIOD = period;
  document.querySelectorAll('.period-btn').forEach(b=> b.classList.toggle('active', b.dataset.period===period));
  document.getElementById('dayPicker').style.display = (period === 'day') ? 'inline-block' : 'none';
  document.getElementById('weekPicker').style.display = (period === 'week') ? 'inline-block' : 'none';
  document.getElementById('monthPicker').style.display = (period === 'month') ? 'inline-block' : 'none';
  document.getElementById('customRangeBar').style.display = (period === 'custom') ? 'inline-flex' : 'none';
  document.getElementById('customRangeNote').style.display = (period === 'custom') ? 'block' : 'none';
  renderPeriodMeta();
  renderTiles();
  renderAlertBanner();
  renderAllTables();
  renderTopics();
  updateTitleForActiveTab();
}

document.querySelectorAll('.period-btn').forEach(btn=>{
  btn.addEventListener('click', ()=> switchPeriod(btn.dataset.period));
});

(function initDayPicker(){
  const picker = document.getElementById('dayPicker');
  picker.innerHTML = DAILY_DATES.map(d=> `<option value="${d}">${d}</option>`).join('');
  picker.value = CURRENT_DAY_DATE;
  picker.addEventListener('change', ()=>{
    CURRENT_DAY_DATE = picker.value;
    renderPeriodMeta();
    renderTiles();
    renderAlertBanner();
    renderAllTables();
    renderTopics();
    updateTitleForActiveTab();
  });
})();

(function initWeekPicker(){
  const picker = document.getElementById('weekPicker');
  picker.innerHTML = [...WEEKLY_PERIOD_LIST].reverse().map(w=> `<option value="${w.key}">${w.label}</option>`).join('');
  picker.value = CURRENT_WEEK_KEY;
  picker.addEventListener('change', ()=>{
    CURRENT_WEEK_KEY = picker.value;
    renderPeriodMeta();
    renderTiles();
    renderAlertBanner();
    renderAllTables();
    renderTopics();
    updateTitleForActiveTab();
  });
})();

(function initMonthPicker(){
  const picker = document.getElementById('monthPicker');
  picker.innerHTML = [...MONTHLY_PERIOD_LIST].reverse().map(m=> `<option value="${m.key}">${m.label}</option>`).join('');
  picker.value = CURRENT_MONTH_KEY;
  picker.addEventListener('change', ()=>{
    CURRENT_MONTH_KEY = picker.value;
    renderPeriodMeta();
    renderTiles();
    renderAlertBanner();
    renderAllTables();
    renderTopics();
    updateTitleForActiveTab();
  });
})();

(function initCustomRange(){
  const dates = Object.keys(DAILY_PERIODS).sort();
  if(!dates.length) return;
  const minD = dates[0].replaceAll('/', '-'), maxD = dates[dates.length-1].replaceAll('/', '-');
  const sEl = document.getElementById('customStart'), eEl = document.getElementById('customEnd');
  sEl.min = minD; sEl.max = maxD; eEl.min = minD; eEl.max = maxD;
  sEl.value = minD; eEl.value = maxD;
  document.getElementById('customApplyBtn').addEventListener('click', ()=>{
    if(!sEl.value || !eEl.value || sEl.value > eEl.value){
      alert('開始日は終了日以前の日付にしてください。');
      return;
    }
    CUSTOM_DATA = buildCustomRangeData(sEl.value, eEl.value);
    renderPeriodMeta();
    renderTiles();
    renderAlertBanner();
    renderAllTables();
    renderTopics();
    updateTitleForActiveTab();
  });
})();

(function initExecCustomRange(){
  const dates = Object.keys(DAILY_PERIODS).sort();
  if(!dates.length) return;
  const minD = dates[0].replaceAll('/', '-'), maxD = dates[dates.length-1].replaceAll('/', '-');
  const sEl = document.getElementById('execCustomStart'), eEl = document.getElementById('execCustomEnd');
  const label = document.getElementById('execCustomRangeLabel');
  sEl.min = minD; sEl.max = maxD; eEl.min = minD; eEl.max = maxD;
  sEl.value = PERIODS.month.start.replaceAll('/', '-');
  eEl.value = PERIODS.month.end.replaceAll('/', '-');
  const updateLabel = () => {
    label.textContent = EXEC_CUSTOM_RANGE ? '' : `既定: 今月（${PERIODS.month.start}〜${PERIODS.month.end}）`;
  };
  updateLabel();
  document.getElementById('execCustomApplyBtn').addEventListener('click', ()=>{
    if(!sEl.value || !eEl.value || sEl.value > eEl.value){
      alert('開始日は終了日以前の日付にしてください。');
      return;
    }
    EXEC_CUSTOM_RANGE = {start: sEl.value, end: eEl.value};
    updateLabel();
    renderExecTab();
  });
  document.getElementById('execCustomResetBtn').addEventListener('click', ()=>{
    EXEC_CUSTOM_RANGE = null;
    sEl.value = PERIODS.month.start.replaceAll('/', '-');
    eEl.value = PERIODS.month.end.replaceAll('/', '-');
    updateLabel();
    renderExecTab();
  });
})();

document.getElementById('diffToggle').addEventListener('change', (e)=>{
  document.body.classList.toggle('hide-diff', !e.target.checked);
});
document.getElementById('targetColToggle').addEventListener('change', (e)=>{
  document.body.classList.toggle('hide-target', !e.target.checked);
});

(function initCompanyScope(){
  const input = document.getElementById('companyScopeInput');
  const applyBtn = document.getElementById('companyScopeApplyBtn');
  const resetBtn = document.getElementById('companyScopeResetBtn');
  const apply = () => {
    const v = input.value.trim();
    const names = [...new Set(currentData().companies.map(c=>c.company))];
    if(!v){ alert('会社名を入力または選択してください。'); return; }
    if(!names.includes(v)){ alert('この期間に該当する会社が見つかりません。候補から選択してください。'); return; }
    setCompanyScope(v);
  };
  applyBtn.addEventListener('click', apply);
  input.addEventListener('keydown', (e)=>{ if(e.key === 'Enter'){ e.preventDefault(); apply(); } });
  resetBtn.addEventListener('click', ()=> setCompanyScope(null));
})();

populateTopicChannelFilter();
document.getElementById('topicChannelFilter').addEventListener('change', renderTopics);
document.getElementById('topicKindFilter').addEventListener('change', renderTopics);

document.getElementById('attFilterApo').addEventListener('change', e=>{ attFilterState.apo = e.target.value; renderAllTables(); });
document.getElementById('attFilterSoutiku').addEventListener('change', e=>{ attFilterState.soutiku = e.target.value; renderAllTables(); });
document.getElementById('attFilterCloser').addEventListener('change', e=>{ attFilterState.closer = e.target.value; renderAllTables(); });
document.getElementById('tableSearchApo').addEventListener('input', e=>{ tableSearchState.apo = e.target.value; renderAllTables(); });
document.getElementById('tableSearchSoutiku').addEventListener('input', e=>{ tableSearchState.soutiku = e.target.value; renderAllTables(); });
document.getElementById('tableSearchCloser').addEventListener('input', e=>{ tableSearchState.closer = e.target.value; renderAllTables(); });

document.querySelectorAll('.tab').forEach(tab=>{
  tab.addEventListener('click', ()=>{
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.panel).classList.add('active');
    if(tab.dataset.panel === 'p-exec') renderExecTab();
    if(tab.dataset.panel === 'p-route') renderRoute();
    if(tab.dataset.panel === 'p-trend') renderTrend();
    if(tab.dataset.panel === 'p-decline') renderDecline();
    updateTitleForActiveTab();
  });
});

document.getElementById('printBtn').addEventListener('click', ()=>{
  const btn = document.getElementById('printBtn');
  const originalText = btn.innerHTML;
  let printed = false;
  window.addEventListener('afterprint', function onAfterPrint(){
    printed = true;
    document.title = ORIGINAL_TITLE;
    window.removeEventListener('afterprint', onAfterPrint);
  });
  try{
    window.print();
  } catch(e){
    printed = false;
  }
  // 一部の環境（埋め込み表示など）では印刷ダイアログがブロックされ、
  // window.print()がエラーも投げず何も起きないことがある。afterprintが一定時間内に
  // 発火しなければ、その旨を表示してチャットでの代替手段を案内する。
  setTimeout(()=>{
    if(!printed){
      btn.textContent = '⚠ 印刷が開けません。Claudeに「PDFを作って」と伝えてください';
      setTimeout(()=>{ btn.innerHTML = originalText; }, 5000);
    }
  }, 800);
});

// ---------- 企業名クリック→企業スコープに切り替え(2026-08-31改訂) ----------
// 以前はモーダルで担当者別内訳を表示していたが、小宮山さんの依頼で「検索欄から絞り込んだ時と
// 同じ挙動」に統一。setCompanyScope()を呼びページ上部のKPI進捗ゲージ（companyKpiGaugeTopCard）
// までスクロールする。担当者別の内訳は企業別タブ側の「指標チップ」をクリックした時に見る形になった
// （renderCompanyScopedView参照）。
function openDrilldown(company){
  setCompanyScope(company);
  document.querySelector('[data-panel="p-company"]').click();
  const target = document.getElementById('companyKpiGaugeTopCard');
  (target.style.display !== 'none' ? target : document.querySelector('.tiles')).scrollIntoView({behavior:'smooth', block:'start'});
}

// ---------- 個人名クリック→日別実績 ----------
function openPersonDetail(name){
  let company = '';
  const dates = [...DAILY_DATES].sort();
  const nameKey = normNameJs(name);
  const rows = dates.map(date=>{
    const dp = DAILY_PERIODS[date];
    const apoRow = dp.apo_ranking.find(r=>normNameJs(r[1])===nameKey);
    const cloRow = dp.closer_ranking.find(r=>normNameJs(r[1])===nameKey);
    if(apoRow) company = apoRow[2];
    else if(cloRow) company = cloRow[2];
    return [date, apoRow ? apoRow[4] : 0, apoRow ? apoRow[3] : 0, cloRow ? cloRow[3] : 0, cloRow ? cloRow[4] : 0];
  });
  const totalApo = rows.reduce((s,r)=>s+r[1], 0);
  const totalApoSeiyaku = rows.reduce((s,r)=>s+r[2], 0);
  const totalCloSeiyaku = rows.reduce((s,r)=>s+r[3], 0);

  document.getElementById('drillTitle').textContent = name;
  const summaryLine =
    `${company || '会社不明'}／${dates[0]}〜${dates[dates.length-1]} 日別実績（累計: アポ${totalApo}件・アポ成約${totalApoSeiyaku}件・クロ成約${totalCloSeiyaku}件）`;
  document.getElementById('drillSub').innerHTML = escapeHtml(summaryLine) + attendanceDetailHtml(name);

  const table = document.getElementById('drillTable');
  const cols = ['日付','アポ数','アポ成約','クロ成約','売上'];
  const thead = '<thead><tr>' + cols.map(c=>`<th class="${c==='日付'?'':'num'}">${c}</th>`).join('') + '</tr></thead>';
  const tbody = '<tbody>' + rows.map(r=>
    `<tr><td>${r[0]}</td><td class="num">${r[1]}</td><td class="num">${r[2]}</td><td class="num">${r[3]}</td><td class="num">${yen(r[4])}</td></tr>`
  ).join('') + '</tbody>';
  table.innerHTML = thead + tbody;

  document.getElementById('drillModal').classList.add('show');
}
// 「稼働人員数・詳細」タイル用のドリルダウン定義（2026-08-11・小宮山さんの依頼＝出勤打刻がある人を
// クリックで一覧表示し、各人の出勤/退勤時刻（記録があれば）とアポ獲得数・成約数を見たい、に対応）。
// 2026-08-25修正：上部の表示期間ピッカーで選択中の期間（日次/週次/月次/カスタム）に連動するよう変更
// （それまでは常に「本日」固定だった）。
function dailyHeadcountTileDef(){
  const d = currentData();
  if(!d || !d.start){
    return {title:'稼働人員数の内訳（個人別）', cols:['氏名'], rows: [], subLabel:'この期間の出勤データがありません'};
  }
  const startHyphen = d.start.replaceAll('/','-'), endHyphen = d.end.replaceAll('/','-');
  const timeOf = ts => (ts && ts.slice(0,10) >= startHyphen && ts.slice(0,10) <= endHyphen) ? ts.slice(11,16) : '—';
  const rows = (d.attendance_person_rows || []).map(r=>{
    const name = r[0], company = r[1] || '（不明）';
    const nameKey = normNameJs(name);
    const rec = ATTENDANCE_BY_NAME.get(nameKey);
    const apoRow = (d.apo_ranking || []).find(x=>normNameJs(x[1])===nameKey);
    const cloRow = (d.closer_ranking || []).find(x=>normNameJs(x[1])===nameKey);
    return [name, company, rec ? timeOf(rec.last_in) : '—', rec ? timeOf(rec.last_out) : '—',
            apoRow ? apoRow[4] : 0, apoRow ? apoRow[3] : 0, cloRow ? cloRow[3] : 0];
  }).sort((a,b)=> (b[4]-a[4]) || (b[5]-a[5]) || (b[6]-a[6]) || String(a[0]).localeCompare(String(b[0]),'ja'));
  const periodLabel = d.start === d.end ? d.start : `${d.start}〜${d.end}`;
  return {
    title: '稼働人員数の内訳（個人別・出勤打刻あり）',
    cols: ['氏名','会社名','出勤時刻','退勤時刻','アポ獲得','アポ成約','クロ成約'],
    rows,
    subLabel: `${periodLabel}時点／${rows.length}名（出勤打刻あり基準・出退勤時刻は選択期間内の打刻がある場合のみ表示）`,
  };
}
// ---------- ③ KPIタイルクリック→内訳ドリルダウン（既存drillModalを流用） ----------
function openTileDrill(kind){
  const d = currentData();
  const alertRecords = (ATTENDANCE_ALERT && ATTENDANCE_ALERT.records) || [];
  const headcountDrill = (isTodayDaySelected() && ATTENDANCE_ALERT) ? (() => {
    const active = realtimeActiveRecords();
    const byCompany = new Map();
    active.forEach(r => {
      const co = r.company || '（不明）';
      byCompany.set(co, (byCompany.get(co) || 0) + 1);
    });
    return {title:'リアルタイム稼働中人数の内訳（会社別）', cols:['会社名','人数'],
      rows: [...byCompany.entries()].sort((a,b)=>b[1]-a[1]),
      subLabel: '直近の自動更新時点で出勤打刻あり・退勤未打刻の人数（最大5分ラグ）'};
  })() : {title:'稼働人員数（出勤打刻あり）の内訳（会社別）', cols:['会社名','稼働人員数'],
      rows: d.companies.filter(c=>c.headcount).slice().sort((a,b)=>b.headcount-a.headcount).map(c=>[c.company, c.headcount])};
  const TILE_DEFS = {
    apo: {title:'アポ獲得数の内訳（会社別）', cols:['会社名','アポ獲得数'],
      rows: d.companies.slice().sort((a,b)=>b.apo_kakutoku-a.apo_kakutoku).map(c=>[c.company, c.apo_kakutoku])},
    sei: {title:'成約数の内訳（会社別・クロ成約基準）', cols:['会社名','クロ成約'],
      rows: d.companies.slice().sort((a,b)=>b.clo_seiyaku-a.clo_seiyaku).map(c=>[c.company, c.clo_seiyaku])},
    uri: {title:'売上の内訳（会社別）', cols:['会社名','売上'],
      rows: d.companies.slice().sort((a,b)=>b.uriage-a.uriage).map(c=>[c.company, yen(c.uriage)])},
    headcount: headcountDrill,
    apoAchievers: {title:'アポ獲得達成者の内訳（会社別）', cols:['会社名','達成者数'],
      rows: d.companies.filter(c=>c.apo_achiever_count).slice().sort((a,b)=>b.apo_achiever_count-a.apo_achiever_count).map(c=>[c.company, c.apo_achiever_count])},
    seiyakuAchievers: {title:'成約達成者の内訳（会社別）', cols:['会社名','達成者数'],
      rows: d.companies.filter(c=>c.seiyaku_achiever_count).slice().sort((a,b)=>b.seiyaku_achiever_count-a.seiyaku_achiever_count).map(c=>[c.company, c.seiyaku_achiever_count])},
    spotActive: {title:'稼働人員数（スポット作成）の内訳（個人別）', cols:['氏名','会社名','スポット作成数'],
      rows: alertRecords.filter(r=>r.spot_count>0).sort((a,b)=>b.spot_count-a.spot_count).map(r=>[r.name, r.company, r.spot_count])},
    routeActive: {title:'稼働人員数（ルート自動記録あり）の内訳（個人別）', cols:['氏名','会社名','ルート自動記録数'],
      rows: alertRecords.filter(r=>r.route_count>0).sort((a,b)=>b.route_count-a.route_count).map(r=>[r.name, r.company, r.route_count])},
    resetAlert: {title:'要リセット（出勤放置）の内訳（個人別）', cols:['氏名','会社名','アラート判定'],
      rows: alertRecords.filter(r=>r.alert==='要対応').map(r=>[r.name, r.company, r.alert])},
    taimen: {title:'対面数の内訳（会社別・新規/再訪問問わず）', cols:['会社名','対面数','対面率(%)'],
      rows: d.companies.filter(c=>c.taimen_count).slice().sort((a,b)=>b.taimen_count-a.taimen_count)
        .map(c=>[c.company, c.taimen_count, c.taimen_rate===null||c.taimen_rate===undefined?'—':c.taimen_rate.toFixed(1)])},
    spotTags: {title:'スポット更新数の内訳（スポットタグ別）', cols:['スポットタグ','件数','割合(%)'],
      rows: d.visits && d.visits.by_status ? Object.entries(d.visits.by_status)
        .sort((a,b)=>b[1]-a[1])
        .map(([tag,count])=>[tag, count, d.visits.total_spots ? (count/d.visits.total_spots*100).toFixed(1) : '—']) : []},
    dailyHeadcount: dailyHeadcountTileDef(),
  };
  const def = TILE_DEFS[kind];
  if(!def) return;
  document.getElementById('drillTitle').textContent = def.title;
  document.getElementById('drillSub').textContent = def.subLabel || `期間: ${d.start}〜${d.end}／${def.rows.length}件`;
  const table = document.getElementById('drillTable');
  const thead = '<thead><tr>' + def.cols.map((c,i)=>`<th class="${i===0?'':'num'}">${escapeHtml(c)}</th>`).join('') + '</tr></thead>';
  const tbody = '<tbody>' + (def.rows.length ? def.rows.map(r=>
    '<tr>' + r.map((v,i)=>`<td class="${i===0?'':'num'}">${escapeHtml(v)}</td>`).join('') + '</tr>'
  ).join('') : `<tr><td colspan="${def.cols.length}" style="text-align:center;color:var(--text-sub);">該当データなし</td></tr>`) + '</tbody>';
  table.innerHTML = thead + tbody;
  document.getElementById('drillModal').classList.add('show');
}
document.querySelectorAll('.tile.clickable').forEach(tile=>{
  tile.addEventListener('click', ()=> openTileDrill(tile.dataset.tile));
});

document.getElementById('drillClose').addEventListener('click', ()=>{
  document.getElementById('drillModal').classList.remove('show');
});
document.getElementById('drillModal').addEventListener('click', (e)=>{
  if(e.target.id === 'drillModal') e.currentTarget.classList.remove('show');
});
document.addEventListener('keydown', (e)=>{
  if(e.key === 'Escape') document.getElementById('drillModal').classList.remove('show');
});

// ---------- CSV出力（役員会資料等への連携用） ----------
document.getElementById('csvBtn').addEventListener('click', async ()=>{
  const active = document.querySelector('.tab.active');
  const label = active ? TAB_LABELS[active.dataset.panel] : 'データ';
  const d = currentData();
  const period = (d.start + '_' + d.end).replaceAll('/', '-');
  const exp = currentTableExport(active.dataset.panel);
  const btn = document.getElementById('csvBtn');
  const originalText = btn.innerHTML;
  if(!exp){
    btn.textContent = 'このタブはCSV出力非対応です';
    setTimeout(()=>{ btn.innerHTML = originalText; }, 2500);
    return;
  }
  const csv = toCSV(exp.header, exp.rows);
  if(!window.claude || !window.claude.downloads){
    btn.textContent = '⚠ このビューでは出力できません';
    setTimeout(()=>{ btn.innerHTML = originalText; }, 2500);
    return;
  }
  try{
    await window.claude.downloads.save({filename: `パートナー_${label}_${period}.csv`, data: csv});
  } catch(err){
    const code = err && err.code;
    if(code === 'declined'){
      // ユーザーがキャンセルしただけなので何もしない
    } else if(code === 'extension_not_enabled' || code === 'rejected_extension'){
      // CSV(拡張形式)がこのビューでは無効。txt(基本形式)は常に許可されるのでフォールバックする
      try{
        await window.claude.downloads.save({filename: `パートナー_${label}_${period}.txt`, data: csv});
        btn.textContent = '✓ txt形式で保存しました（拡張子をcsvに変更してご利用ください）';
        setTimeout(()=>{ btn.innerHTML = originalText; }, 4000);
      } catch(err2){
        if(err2 && err2.code === 'declined'){
          // キャンセルのみ
        } else {
          btn.textContent = '⚠ 出力に失敗しました';
          setTimeout(()=>{ btn.innerHTML = originalText; }, 3000);
        }
      }
    } else {
      btn.textContent = '⚠ 出力に失敗しました';
      setTimeout(()=>{ btn.innerHTML = originalText; }, 3000);
    }
  }
});

// ---------- ⑥ 全タブCSV一括出力 ----------
async function saveWithFallback(btn, filename, csv){
  const originalText = btn.innerHTML;
  if(!window.claude || !window.claude.downloads){
    btn.textContent = '⚠ このビューでは出力できません';
    setTimeout(()=>{ btn.innerHTML = originalText; }, 2500);
    return;
  }
  try{
    await window.claude.downloads.save({filename, data: csv});
    btn.textContent = '✓ 保存しました';
    setTimeout(()=>{ btn.innerHTML = originalText; }, 2500);
  } catch(err){
    const code = err && err.code;
    if(code === 'declined'){
      // キャンセルのみ
    } else if(code === 'extension_not_enabled' || code === 'rejected_extension'){
      const txtName = filename.replace(/\.(csv|json)$/i, '.txt');
      try{
        await window.claude.downloads.save({filename: txtName, data: csv});
        btn.textContent = `✓ txt形式で保存しました（拡張子を${filename.endsWith('.json')?'json':'csv'}に変更してご利用ください）`;
        setTimeout(()=>{ btn.innerHTML = originalText; }, 4000);
      } catch(err2){
        if(!(err2 && err2.code === 'declined')){
          btn.textContent = '⚠ 出力に失敗しました';
          setTimeout(()=>{ btn.innerHTML = originalText; }, 3000);
        }
      }
    } else {
      btn.textContent = '⚠ 出力に失敗しました';
      setTimeout(()=>{ btn.innerHTML = originalText; }, 3000);
    }
  }
}

document.getElementById('csvAllBtn').addEventListener('click', async ()=>{
  const btn = document.getElementById('csvAllBtn');
  const d = currentData();
  const period = (d.start + '_' + d.end).replaceAll('/', '-');
  const sections = [];
  const panelOrder = ['p-company','p-apo','p-soutiku','p-closer','p-naihan','p-topics','p-outreach','p-route','p-trend','p-exec'];
  panelOrder.forEach(panelId=>{
    const exp = currentTableExport(panelId);
    if(!exp || !exp.header.length) return;
    sections.push(`### ${TAB_LABELS[panelId]}`);
    sections.push(...toCSV(exp.header, exp.rows).replace(/^﻿/, '').split(String.fromCharCode(13)+String.fromCharCode(10)));
    sections.push('');
  });
  const CRLF = String.fromCharCode(13) + String.fromCharCode(10);
  const csv = '﻿' + sections.join(CRLF);
  await saveWithFallback(btn, `パートナー_全タブ_${period}.csv`, csv);
});

// ---------- ⑥ 資料作成用データを書き出す（責任者会議pptxスライド構成に対応したJSON） ----------
document.getElementById('materialExportBtn').addEventListener('click', async ()=>{
  const btn = document.getElementById('materialExportBtn');
  const d = currentData();
  const period = (d.start + '_' + d.end).replaceAll('/', '-');
  const payload = {
    generated_at: new Date().toISOString(),
    period: {start: d.start, end: d.end},
    "A-1_全体サマリー": {
      totals: d.totals,
      n_closing_in_period: d.n_closing_in_period,
      total_headcount: d.total_headcount,
      attendance_alert_summary: ATTENDANCE_ALERT,
      completion: COMPLETION.available ? COMPLETION.month : null,
    },
    "A-2_週次": last4Weeks().map(w=>{
      const wd = WEEKLY_PERIODS[w.key];
      return {label: w.label, start: w.start, end: w.end, totals: wd.totals, total_headcount: wd.total_headcount};
    }),
    "B系_直販": d.companies.filter(c=>c.company.includes('Fit Founder')),
    "C系_パートナー": d.companies.filter(c=>!c.company.includes('Fit Founder')).sort((a,b)=>b.apo_kakutoku-a.apo_kakutoku),
    "D系_エリア": (DOW_HOUR && DOW_HOUR.available) ? DOW_HOUR : {available:false},
    apo_ranking_top20: d.apo_ranking.slice(0,20).map(r=>({rank:r[0], name:r[1], company:r[2], apo_seiyaku:r[3], apo_count:r[4]})),
    closer_ranking_top20: d.closer_ranking.slice(0,20).map(r=>({rank:r[0], name:r[1], company:r[2], clo_seiyaku:r[3], uriage:r[4]})),
    targets: (typeof TARGETS !== 'undefined') ? TARGETS : null,
    note: "このJSONをClaudeに渡すと責任者会議資料（役員会pptx）のA-1/A-2/B系/C系/D系構成に沿って更新できます。",
  };
  await saveWithFallback(btn, `資料作成用データ_${period}.json`, JSON.stringify(payload, null, 2));
});

switchPeriod('month');
renderOutreach();
renderRoute();
renderTrend();
renderAiSummary();
renderExecTab();
renderShiftStatus();
renderShodanPipeline();
renderDecline();
</script>
</body>
</html>
"""


HOUR_BUCKETS = [(6, 9), (9, 12), (12, 14), (14, 16), (16, 18), (18, 20), (20, 23)]


def _hour_bucket_label(hour):
    for lo, hi in HOUR_BUCKETS:
        if lo <= hour < hi:
            return f"{lo}-{hi}時"
    return None


def _first_weekend_of_month(year, month):
    """月初（1〜7日）で最初の土曜日と、その翌日（日曜日）を返す。月は必ず7日以上あるので月をまたがない。"""
    for d in range(1, 8):
        dt = datetime(year, month, d)
        if dt.weekday() == 5:  # 0=月, 5=土
            return dt, dt + timedelta(days=1)
    raise AssertionError("first week has no Saturday (should not happen)")


def _weekend_comparison(roster_csv, closing_csv, end_dt, lookback_months):
    """月初の土日（最初の土曜+日曜の2日間）の実績を、直近Nヶ月について並べる（③）。
    当月分の週末がまだ来ていなければ省く（未来の期間を集計してゼロ件と誤解させないため）。"""
    out = []
    cursor = end_dt.replace(day=1)
    months = []
    for _ in range(lookback_months):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
    for m_start_dt in months:
        sat, sun = _first_weekend_of_month(m_start_dt.year, m_start_dt.month)
        if sat > end_dt:
            continue
        w_end_dt = min(sun, end_dt)
        wd = aggregate(roster_csv, closing_csv, sat.strftime("%Y/%m/%d"), w_end_dt.strftime("%Y/%m/%d"))
        # aggregate()はcompaniesの合計をtotalsとして持たないため、月次_period_data同様に自前で合算する
        apo_kakutoku = sum(c["apo_kakutoku"] for c in wd["companies"])
        apo_seiyaku = sum(c["apo_seiyaku"] for c in wd["companies"])
        clo_seiyaku = sum(c["clo_seiyaku"] for c in wd["companies"])
        uriage = sum(c["uriage"] for c in wd["companies"])
        out.append({
            "month": m_start_dt.strftime("%Y年%m月"),
            "start": sat.strftime("%Y/%m/%d"), "end": w_end_dt.strftime("%Y/%m/%d"),
            "partial": w_end_dt < sun,
            # 獲得報告データのシートが2026/07/01より前を持たないため、それ以前の週末は成約/売上が
            # 実質ゼロではなく「比較対象データが無いだけ」（UI側で「—」表示に使う）。
            "seiyaku_data_available": sat >= datetime(2026, 7, 1),
            "apo_kakutoku": apo_kakutoku, "apo_seiyaku": apo_seiyaku,
            "clo_seiyaku": clo_seiyaku, "uriage": uriage,
            "rate": round(clo_seiyaku / apo_kakutoku * 100, 1) if apo_kakutoku else 0,
        })
    return out


def _route_area_time_grid(route_history):
    """行動履歴の実イベント（訪問・アポ獲得）から、エリア×時間帯のアポ獲得傾向を集計する（②）。
    ロースターCSVは獲得日のみで時刻を持たないため、実際にGPS+時刻が付いている行動履歴イベントを使う
    （route_historyは既にbuild_route_history.pyで日別・担当者別に間引き済みの軽量データ）。
    全蓄積期間（表示中の月次期間とは連動しない独立集計＝開拓先パートナー・行動分析タブと同じ設計）を対象にする。"""
    areas = {}
    total_visit = total_apo = 0
    for date, users in route_history.items():
        for name, rec in users.items():
            area = rec.get("group") or "（不明）"
            for e in rec.get("events", []):
                t = e.get("t")
                status = e.get("status", "")
                if not t or len(t) < 2:
                    continue
                try:
                    hour = int(t[:2])
                except ValueError:
                    continue
                bucket = _hour_bucket_label(hour)
                if not bucket:
                    continue
                is_visit = status.startswith("訪問")
                is_apo = status == "アポ獲得"
                if not (is_visit or is_apo):
                    continue
                cell = areas.setdefault(area, {}).setdefault(bucket, {"visit": 0, "apo": 0})
                if is_visit:
                    cell["visit"] += 1
                    total_visit += 1
                if is_apo:
                    cell["apo"] += 1
                    total_apo += 1
    hour_labels = [f"{lo}-{hi}時" for lo, hi in HOUR_BUCKETS]
    area_labels = sorted(areas.keys())
    grid = []
    for area in area_labels:
        for bucket in hour_labels:
            cell = areas.get(area, {}).get(bucket, {"visit": 0, "apo": 0})
            rate = round(cell["apo"] / cell["visit"] * 100, 1) if cell["visit"] else None
            grid.append({"area": area, "hour": bucket, "visit": cell["visit"], "apo": cell["apo"], "rate": rate})
    return {
        "areas": area_labels, "hours": hour_labels, "grid": grid,
        "total_visit": total_visit, "total_apo": total_apo,
        "dates_covered": sorted(route_history.keys()),
    }


def _top_performer_patterns(roster_csv, closing_csv, route_history, top_n=10):
    """行動履歴データが存在する最新月について、成約上位者（好成績者）の動き方統計を全体平均と比べる（④）。
    表示中の期間とは独立に、route_historyがカバーする最新の月を対象にする
    （行動履歴と獲得実績の両方が揃っている月でないと意味のある比較にならないため）。"""
    dates = sorted(route_history.keys())
    if not dates:
        return {"available": False, "reason": "行動履歴データがまだありません"}
    latest_date = dates[-1]
    y, m = int(latest_date[:4]), int(latest_date[5:7])
    m_start_dt = datetime(y, m, 1)
    next_month_first = (m_start_dt.replace(day=28) + timedelta(days=4)).replace(day=1)
    m_end_dt = next_month_first - timedelta(days=1)
    m_start, m_end = m_start_dt.strftime("%Y/%m/%d"), m_end_dt.strftime("%Y/%m/%d")

    data = aggregate(roster_csv, closing_csv, m_start, m_end)
    # apo_ranking/closer_ranking は with_rank() 済み ＝ [rank, name, company, seiyaku数, ...] の形（rankが先頭に入る）
    top_names = set()
    for r in sorted(data["apo_ranking"], key=lambda r: -r[3])[:top_n]:
        if r[3] > 0:
            top_names.add(r[1])
    for r in sorted(data["closer_ranking"], key=lambda r: -r[3])[:top_n]:
        if r[3] > 0:
            top_names.add(r[1])

    def _stats_for(names_filter):
        route_counts, spans, ranges, visit_counts, apo_counts, hours = [], [], [], [], [], []
        for date, users in route_history.items():
            if date < m_start.replace("/", "-") or date > m_end.replace("/", "-"):
                continue
            for name, rec in users.items():
                if names_filter is not None and name not in names_filter:
                    continue
                if rec.get("route_count", 0) == 0 and not rec.get("events"):
                    continue
                route_counts.append(rec.get("route_count", 0))
                if rec.get("span_minutes") is not None:
                    spans.append(rec["span_minutes"])
                if rec.get("range_km") is not None:
                    ranges.append(rec["range_km"])
                v = sum(1 for e in rec.get("events", []) if e.get("status", "").startswith("訪問"))
                a = sum(1 for e in rec.get("events", []) if e.get("status") == "アポ獲得")
                visit_counts.append(v)
                apo_counts.append(a)
                for e in rec.get("events", []):
                    if e.get("status") == "アポ獲得" and e.get("t") and len(e["t"]) >= 2:
                        try:
                            hours.append(int(e["t"][:2]))
                        except ValueError:
                            pass
        n = len(route_counts)
        if n == 0:
            return None

        def avg(lst):
            return round(sum(lst) / len(lst), 1) if lst else None

        common_hour = None
        if hours:
            counts = {}
            for h in hours:
                counts[h] = counts.get(h, 0) + 1
            common_hour = max(counts, key=counts.get)
        return {
            "n_people_days": n,
            "avg_route_count": avg(route_counts),
            "avg_span_minutes": avg(spans),
            "avg_range_km": avg(ranges),
            "avg_visit_count": avg(visit_counts),
            "avg_apo_count": avg(apo_counts),
            "common_apo_hour": (f"{common_hour}時台" if common_hour is not None else None),
        }

    top_stats = _stats_for(top_names) if top_names else None
    all_stats = _stats_for(None)
    return {
        "available": True, "month": m_start_dt.strftime("%Y年%m月"),
        "top_names": sorted(top_names), "top_n_requested": top_n,
        "top_stats": top_stats, "all_stats": all_stats,
    }


def _trend_analysis(roster_csv, closing_csv, route_history, end_dt, lookback_months=6):
    return {
        "weekend_comparison": _weekend_comparison(roster_csv, closing_csv, end_dt, lookback_months),
        "area_time_grid": _route_area_time_grid(route_history),
        "top_performer_patterns": _top_performer_patterns(roster_csv, closing_csv, route_history),
    }


def _period_data(roster_csv, closing_csv, start, end, attendance_csv=None, status_notes=None,
                  prev_start=None, prev_end=None, alert_master=None, company_alert_counts=None,
                  spot_csv=None, closer_shodan_dir=None):
    """1期間分の集計結果に、稼働人員数（attendance_csvがあれば）・前期間比・状態タグ等の運用列・取材候補をマージして返す。
    start/end は 'YYYY/MM/DD'（roster/closing用）。attendance側は内部で 'YYYY-MM-DD' に変換する。
    prev_start/prev_end を明示的に渡すと、それを前期間として使う（週次＝水〜日ターム用。前週の同じ水〜日と比較したいため、
    「同日数の直前期間」という汎用ルールではなく正確に7日前を使う）。省略時は prev_range()の汎用ルール。"""
    data = aggregate(roster_csv, closing_csv, start, end)
    data["closer_shodan_by_name"] = aggregate_closer_shodan(closer_shodan_dir, start, end) if closer_shodan_dir else {}
    attended_names = None
    if attendance_csv:
        a_start = start.replace("/", "-")
        a_end = end.replace("/", "-")
        att = aggregate_attendance(attendance_csv, a_start, a_end)
        attended_names = {p[0] for p in att["person_rows"]} | set(att["unresolved"])
        for c in data["companies"]:
            c["headcount"] = att["company_counts"].get(c["company"])
        # 表に出ていない（アポ/成約実績ゼロだが出勤打刻はある）会社も拾う
        existing = {c["company"] for c in data["companies"]}
        for co, cnt in att["company_counts"].items():
            if co not in existing:
                data["companies"].append({
                    "company": co, "apo_kakutoku": 0, "apo_seiyaku": 0, "clo_seiyaku": 0,
                    "uriage": 0, "rate": None, "headcount": cnt,
                    "apo_achiever_count": 0, "seiyaku_achiever_count": 0,
                })
        data["companies"].sort(key=lambda r: -r["apo_kakutoku"])
        data["attendance_person_rows"] = att["person_rows"]
        data["attendance_unresolved"] = att["unresolved"]
        data["total_headcount"] = sum(att["company_counts"].values())
    else:
        for c in data["companies"]:
            c["headcount"] = None
        data["attendance_person_rows"] = []
        data["attendance_unresolved"] = []
        data["total_headcount"] = None

    if prev_start is None or prev_end is None:
        prev_start, prev_end = prev_range(start, end)
    prev_data = aggregate(roster_csv, closing_csv, prev_start, prev_end)
    merge_diff(data["companies"], prev_data["companies"])
    data["prev_start"], data["prev_end"] = prev_start, prev_end
    # 獲得報告データのシートが2026/07/01より前を持たないため、前期間が7/1以前にかかる期間（月次・第1週など）は
    # 前期間の成約実績が実質ゼロになり、強化対象・取材候補（成約数ベースの判定）が正しく機能しない。
    # UIで注記を出すためのフラグ（値そのものを作り変えるのではなく、事実として空だったことを伝える）。
    data["prev_data_available"] = prev_data["totals"]["clo_seiyaku"] > 0

    for c in data["companies"]:
        c["suggested_reasons"] = suggest_reinforcement(c)
        notes = (status_notes or {}).get(c["company"], {})
        c["status_tag"] = notes.get("status_tag", "")
        c["cause"] = notes.get("cause", "")
        c["next_action"] = notes.get("next_action", "")
        # 出退勤放置アラートマスター（④・2026-07-28夜追加）: cyzen_dashboard_master.csvは期間フィルタを
        # 持たない最新スナップショットのため、どの表示期間でも同じ内訳（要対応/未打刻/正常の人数）を返す。
        if company_alert_counts:
            alert_counts = company_alert_counts.get(c["company"], {})
            c["attendance_alert_needsaction"] = alert_counts.get("要対応", 0)
            c["attendance_alert_noclockin"] = alert_counts.get("未打刻", 0)
            c["attendance_alert_ok"] = alert_counts.get("正常", 0)
        else:
            c["attendance_alert_needsaction"] = None
            c["attendance_alert_noclockin"] = None
            c["attendance_alert_ok"] = None

    data["apo_ranking"] = annotate_rankings(data["apo_ranking"], prev_data["apo_ranking"])
    data["soutiku_ranking"] = annotate_rankings(data["soutiku_ranking"], prev_data["soutiku_ranking"])
    data["closer_ranking"] = annotate_rankings(data["closer_ranking"], prev_data["closer_ranking"])

    # 出勤打刻なしで実績あり（2026-07-28調査で判明した実データの乖離。バグではなく運用上の実態）。
    # attendance_csvが無い期間ではNone扱い（未取得のだけであり「打刻なし」と混同しないようフラグ自体を立てない）。
    if attended_names is not None:
        data["apo_ranking"] = flag_attendance_mismatch(data["apo_ranking"], attended_names, count_idx=4)
        data["soutiku_ranking"] = flag_attendance_mismatch(data["soutiku_ranking"], attended_names, count_idx=4)
        data["closer_ranking"] = flag_attendance_mismatch(data["closer_ranking"], attended_names, count_idx=3)
        mismatch = []
        for r in data["apo_ranking"]:
            if r[-1]:
                mismatch.append({"name": r[1], "company": r[2], "role": "アポインター", "count": r[4]})
        for r in data["closer_ranking"]:
            if r[-1]:
                mismatch.append({"name": r[1], "company": r[2], "role": "クローザー", "count": r[3]})
        data["attendance_mismatch_people"] = mismatch
    else:
        data["apo_ranking"] = [list(r) + [False] for r in data["apo_ranking"]]
        data["soutiku_ranking"] = [list(r) + [False] for r in data["soutiku_ranking"]]
        data["closer_ranking"] = [list(r) + [False] for r in data["closer_ranking"]]
        data["attendance_mismatch_people"] = None

    # 出退勤放置アラートマスター（2026-07-28追加）: 「出勤打刻なし」を単一の注意表示にしていたのを、
    # ①稼働の実態=7月のスポット作成数 ②出退勤の打刻放置=別軸のアラート、に分けて可視化する。
    # このCSV自体が期間フィルタを持たない最新スナップショットのため、どの表示期間でも同じ値を返す
    # （alert_masterが無い場合は全員 [None,None,None,None] が付き、JS側は既存のlegacy flagにフォールバックする）。
    data["apo_ranking"] = augment_with_alert_master(data["apo_ranking"], alert_master)
    data["soutiku_ranking"] = augment_with_alert_master(data["soutiku_ranking"], alert_master)
    data["closer_ranking"] = augment_with_alert_master(data["closer_ranking"], alert_master)

    # 訪問種別（新規/再訪問）・対面率（2026-07-29追加）: --spot-csv 省略時は全て空欄扱い。
    # スポット台帳の '作成日' は 'YYYY-MM-DD' 表記のため、roster/closing用の 'YYYY/MM/DD' から変換する。
    if spot_csv:
        v_start = start.replace("/", "-")
        v_end = end.replace("/", "-")
        visits = aggregate_visits(spot_csv, v_start, v_end)
        data["visits"] = visits
        for c in data["companies"]:
            vc = visits["company"].get(c["company"])
            c["new_visit_count"] = vc["new_visit_count"] if vc else 0
            c["revisit_count"] = vc["revisit_count"] if vc else 0
            c["taimen_count"] = vc["taimen_count"] if vc else 0
            c["taimen_rate"] = vc["taimen_rate"] if vc else None
        # 表に出ていない（アポ/成約実績ゼロだがスポット実績はある）会社も拾う
        existing_co = {c["company"] for c in data["companies"]}
        for co, vc in visits["company"].items():
            if co not in existing_co and co != "（不明）":
                data["companies"].append({
                    "company": co, "apo_kakutoku": 0, "apo_seiyaku": 0, "clo_seiyaku": 0,
                    "uriage": 0, "rate": None, "headcount": None,
                    "apo_achiever_count": 0, "seiyaku_achiever_count": 0,
                    "rank": len(data["companies"]) + 1, "rank_change": None,
                    "prev_apo_kakutoku": None, "prev_clo_seiyaku": None, "prev_uriage": None, "prev_rate": None,
                    "delta_apo_kakutoku": None, "delta_apo_pct": None, "delta_clo_seiyaku": None, "delta_clo_pct": None,
                    "delta_uriage": None, "delta_uriage_pct": None, "delta_rate": None, "rank_prev": None,
                    "suggested_reasons": [], "status_tag": "", "cause": "", "next_action": "",
                    "attendance_alert_needsaction": None, "attendance_alert_noclockin": None, "attendance_alert_ok": None,
                    "new_visit_count": vc["new_visit_count"], "revisit_count": vc["revisit_count"],
                    "taimen_count": vc["taimen_count"], "taimen_rate": vc["taimen_rate"],
                })

        def _augment_person_visits(ranking_rows):
            out = []
            for r in ranking_rows:
                name = r[1]
                pv = visits["person"].get(norm_name(name))
                if pv:
                    out.append(list(r) + [pv["new_visit_count"], pv["revisit_count"], pv["taimen_count"],
                                           pv["taimen_rate"], pv["taimen_rate_new"], pv["taimen_rate_revisit"]])
                else:
                    out.append(list(r) + [0, 0, 0, None, None, None])
            return out

        data["apo_ranking"] = _augment_person_visits(data["apo_ranking"])
        data["soutiku_ranking"] = _augment_person_visits(data["soutiku_ranking"])
    else:
        data["visits"] = None
        for c in data["companies"]:
            c["new_visit_count"] = None
            c["revisit_count"] = None
            c["taimen_count"] = None
            c["taimen_rate"] = None
        data["apo_ranking"] = [list(r) + [None, None, None, None, None, None] for r in data["apo_ranking"]]
        data["soutiku_ranking"] = [list(r) + [None, None, None, None, None, None] for r in data["soutiku_ranking"]]

    return data


def build(roster_csv, closing_csv, start, end, out_path, attendance_csv=None, status_csv=None,
          slack_topics_json=None, outreach_json=None, ai_summary_json=None,
          targets_json=None, completion_dir=None, attendance_alert_csv=None, spot_csv=None,
          route_history_json=None, closer_shodan_dir=None,
          urgent_targets_json=None, training_json=None, shift_status_json=None,
          clockout_csv=None, shodan_json=None, tenure_json=None, company_targets_json=None):
    end_dt = datetime.strptime(end, "%Y/%m/%d")
    start_dt = datetime.strptime(start, "%Y/%m/%d")
    day_start = end_dt.strftime("%Y/%m/%d")

    # 週次＝水曜〜日曜を1タームとする。weekday(): 月=0,火=1,水=2,木=3,金=4,土=5,日=6。
    # 月初を含む最初の水曜日（月初より前の日付になることもある）から7日刻みで、当日を超えない範囲で
    # ターム（第1週、第2週…）を列挙する。各タームは「水曜日始まり・終端は次の火曜前日(日曜)まで」だが、
    # 当日がターム内（進行中）ならそのタームだけ終端を当日に短縮する（他の期間と同じ「頭から今日まで」の考え方）。
    month_first_wed_dt = start_dt - timedelta(days=(start_dt.weekday() - 2) % 7)
    week_terms = []  # [(week_no, start_dt, end_dt), ...]
    w = month_first_wed_dt
    week_no = 1
    while w <= end_dt:
        term_end_dt = min(w + timedelta(days=4), end_dt)
        week_terms.append((week_no, w, term_end_dt))
        w += timedelta(days=7)
        week_no += 1

    status_notes = load_company_notes(status_csv) if status_csv else {}

    # 出退勤放置アラートマスター（省略可）: 稼働の実態=スポット作成数 / 出退勤放置=別軸アラート、を分けて出す。
    alert_master = load_attendance_alert_master(attendance_alert_csv) if attendance_alert_csv else None
    # ④ 企業別タブの出退勤状態内訳列（要対応/未打刻/正常）用: 氏名→会社名解決を介した会社別集計。
    # alert_master同様スナップショットのため期間に関わらず同じ値になる。
    company_alert_counts = company_attendance_alert_counts(alert_master) if alert_master else {}

    # 日次の日付ピッカー用: 当月1日〜当日に加え、カスタム期間ピッカー（buildCustomRangeData、JS側）が
    # 月をまたいだ範囲を選べるよう、過去DAILY_LOOKBACK_MONTHSヶ月分もさかのぼって日次集計する
    # （2026-08-03・パートナー推進課から「7月分の通しの情報がカスタム期間/月次で見れない」との指摘を受けて追加）。
    # roster/closingは元々全期間データを持つため件数自体は過去月も正しく出るが、attendance_csv/spot_csvに
    # その月のデータが無ければ稼働人員数・対面率はその日だけ空欄になる（存在しないものを捏造しない）。
    # 6ヶ月全部を日次展開すると計算コストが大きい割に大半の月はattendance/spotデータが無く実利が薄いため、
    # 当月＋前月の2ヶ月分に絞る（必要になれば増やせる）。
    DAILY_LOOKBACK_MONTHS = 2
    daily_start_dt = start_dt.replace(day=1)
    for _ in range(DAILY_LOOKBACK_MONTHS - 1):
        daily_start_dt = (daily_start_dt - timedelta(days=1)).replace(day=1)

    daily_periods = {}
    d = daily_start_dt
    while d <= end_dt:
        ds = d.strftime("%Y/%m/%d")
        daily_periods[ds] = _period_data(roster_csv, closing_csv, ds, ds, attendance_csv, status_notes,
                                          alert_master=alert_master, company_alert_counts=company_alert_counts,
                                          spot_csv=spot_csv, closer_shodan_dir=closer_shodan_dir)
        d += timedelta(days=1)

    # 週次ピッカー用: 各タームを個別に集計（前週比較は同日数の直前期間ではなく、正確に7日前の同タームと比較）
    weekly_periods = {}
    weekly_period_list = []  # [{key, label, start, end}, ...] 新しい週が先頭に来るようJS側で並び替える
    for week_no, w_start_dt, w_end_dt in week_terms:
        key = w_start_dt.strftime("%Y/%m/%d")
        prev_w_start = (w_start_dt - timedelta(days=7)).strftime("%Y/%m/%d")
        prev_w_end = (w_end_dt - timedelta(days=7)).strftime("%Y/%m/%d")
        weekly_periods[key] = _period_data(roster_csv, closing_csv, key, w_end_dt.strftime("%Y/%m/%d"),
                                            attendance_csv, status_notes,
                                            prev_start=prev_w_start, prev_end=prev_w_end,
                                            alert_master=alert_master, company_alert_counts=company_alert_counts,
                                            spot_csv=spot_csv, closer_shodan_dir=closer_shodan_dir)
        weekly_period_list.append({
            "key": key, "start": key, "end": w_end_dt.strftime("%Y/%m/%d"),
            "label": f"第{week_no}週 ({w_start_dt.strftime('%m/%d')}〜{w_end_dt.strftime('%m/%d')})",
        })

    latest_week_key = weekly_period_list[-1]["key"]
    week_start, week_end = weekly_period_list[-1]["start"], weekly_period_list[-1]["end"]

    # 月次ピッカー用（2026-08-02追加）: 「月次」が常に当月だけを指す仕様だと、月が変わった瞬間に前月の
    # 実績が見れなくなる（パートナー推進課からの指摘）。過去数ヶ月分を個別に集計し、月次タブでも
    # 日次/週次と同じように過去の月を選べるようにする。
    # 2026-08-03更新: 稼働人員数・スポット関連は、attendance_csv/spot_csvに過去月のデータが含まれていれば
    # （複数月をまたいで出力したCSVを渡していれば）過去月でも表示される――is_currentによる無条件封鎖はやめた
    # （aggregate_attendance/aggregate_visits は渡されたCSVを start/end で内部フィルタするだけなので、
    # 該当月の行が無ければ結果が0/空になるだけで、存在しないデータを捏造することにはならない）。
    # 出退勤放置アラート（alert_master）・運用列（status_notes）は「今この瞬間の状態」を表す一時スナップショットで
    # 過去月という概念自体がそぐわないため、これらは引き続き当月のみに限定する。
    # 前期間比は明示指定せず、既存の月次と同じ prev_range() の「同日数の直前期間」ルールに任せる。
    MONTHLY_LOOKBACK = 6
    monthly_periods = {}
    monthly_period_list = []
    months = []
    cursor = start_dt.replace(day=1)
    for _ in range(MONTHLY_LOOKBACK):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
    for m_start_dt in months:
        is_current = (m_start_dt.year == end_dt.year and m_start_dt.month == end_dt.month)
        if is_current:
            m_end_dt = end_dt
        else:
            next_month_first = (m_start_dt.replace(day=28) + timedelta(days=4)).replace(day=1)
            m_end_dt = next_month_first - timedelta(days=1)
        key = m_start_dt.strftime("%Y/%m")
        m_start = m_start_dt.strftime("%Y/%m/%d")
        m_end = m_end_dt.strftime("%Y/%m/%d")
        monthly_periods[key] = _period_data(
            roster_csv, closing_csv, m_start, m_end,
            attendance_csv, status_notes if is_current else {},
            alert_master=alert_master if is_current else None,
            company_alert_counts=company_alert_counts if is_current else None,
            spot_csv=spot_csv,
            closer_shodan_dir=closer_shodan_dir,
        )
        monthly_period_list.append({
            "key": key, "start": m_start, "end": m_end,
            "label": m_start_dt.strftime("%Y年%m月") + ("（進行中）" if is_current else ""),
        })
    latest_month_key = monthly_period_list[-1]["key"]

    # 完工数（責任者会議資料フォーマット用）: 月次合計・週次内訳・日次累積（月内推移グラフ用）。
    # --completion-dir 省略時は全て空（"available": False）にして、UI側で欄を空欄表示する。
    if completion_dir and os.path.isdir(completion_dir):
        completion_month = aggregate_completion(completion_dir, start, end)
        completion_month["available"] = True
        completion_weekly = {}
        for week_no, w_start_dt, w_end_dt in week_terms:
            key = w_start_dt.strftime("%Y/%m/%d")
            completion_weekly[key] = aggregate_completion(
                completion_dir, key, w_end_dt.strftime("%Y/%m/%d"))
        # 2026-08-04: 責任者会議タブのカスタム期間ピッカー（completionForRange()、JS側）が前月にも
        # またがれるよう、daily_periodsと同じ当月＋前月（daily_start_dt）まで遡って日次累積を持たせる。
        # 差分計算にしか使わないため月境界でリセットする必要はなく、単純に連続で積み上げてよい。
        completion_daily_cum = []
        d = daily_start_dt
        running_count = running_uriage = 0
        while d <= end_dt:
            ds = d.strftime("%Y/%m/%d")
            day_agg = aggregate_completion(completion_dir, ds, ds)
            running_count += day_agg["count"]
            running_uriage += day_agg["uriage"]
            completion_daily_cum.append({"date": ds, "count": running_count, "uriage": running_uriage})
            d += timedelta(days=1)
        completion = {"available": True, "month": completion_month,
                      "weekly": completion_weekly, "daily_cumulative": completion_daily_cum}
    else:
        completion = {"available": False, "month": None, "weekly": {}, "daily_cumulative": []}

    # 曜日×時間帯ヒートマップ（アポ獲得件数）。ロースターCSVに時刻列が無ければ available=False。
    dow_hour = aggregate_dow_hour(roster_csv, start, end)

    # 責任者会議フォーマットの目標値デフォルト（targets.json）。ユーザーがUIで編集した値は
    # localStorageに保存され、そちらが優先される（JS側の実装。ここではデフォルト値のみ埋め込む）。
    targets_default = None
    if targets_json and os.path.exists(targets_json):
        with open(targets_json, encoding="utf-8") as f:
            targets_default = json.load(f)

    periods = {
        "day": daily_periods[day_start],
        "week": weekly_periods[latest_week_key],
        "month": _period_data(roster_csv, closing_csv, start, end, attendance_csv, status_notes,
                               alert_master=alert_master, company_alert_counts=company_alert_counts,
                               spot_csv=spot_csv, closer_shodan_dir=closer_shodan_dir),
    }

    slack_topics = []
    if slack_topics_json and os.path.exists(slack_topics_json):
        with open(slack_topics_json, encoding="utf-8") as f:
            slack_topics = json.load(f)

    outreach = None
    if outreach_json and os.path.exists(outreach_json):
        with open(outreach_json, encoding="utf-8") as f:
            outreach = json.load(f)

    # 行動分析タブ用（Cyzen行動履歴の日別・担当者別集計＝build_route_history.pyの出力）。
    # 表示期間（日次/週次/月次）とは連動しない独立ビュー（開拓先パートナータブと同じ設計）で、
    # 蓄積済みの全日付をそのまま埋め込み、タブ内の日付ピッカーで選ばせる。
    route_history = {}
    if route_history_json and os.path.exists(route_history_json):
        with open(route_history_json, encoding="utf-8") as f:
            route_history = json.load(f)

    # 傾向分析タブ用（2026-08-02追加）: 月初土日の月次比較・エリア×時間帯のアポ獲得傾向・好成績者の動き方傾向。
    # いずれも表示期間（日次/週次/月次）とは連動しない独立集計（開拓先パートナー・行動分析タブと同じ設計）。
    trend = _trend_analysis(roster_csv, closing_csv, route_history, end_dt)

    ai_summary = None
    if ai_summary_json and os.path.exists(ai_summary_json):
        with open(ai_summary_json, encoding="utf-8") as f:
            ai_summary = json.load(f)

    # 役員会（SH役職者定例）で正式決定した急落・下降ターゲット一覧（2026-08-04追加）。表示期間とは
    # 連動しない独立ビュー（開拓先パートナー・行動分析タブと同じ設計）。個人別ランキングにバッジ表示する。
    urgent_targets = {"targets": []}
    if urgent_targets_json and os.path.exists(urgent_targets_json):
        with open(urgent_targets_json, encoding="utf-8") as f:
            urgent_targets = json.load(f)

    # 研修参加者名簿（2026-08-04追加）。研修前後のアポ数・行動量モニタリングに使う。
    training = {"trainings": []}
    if training_json and os.path.exists(training_json):
        with open(training_json, encoding="utf-8") as f:
            training = json.load(f)

    # 在籍期間データ（2026-08-31追加・build_tenure_api.pyの出力）。Cyzen連携API /users の
    # created_at（アカウント作成日時）を登録日の代理指標として使う。クローザー昇格日に相当する
    # フィールドはCyzen側に無いため未搭載（2026/8/31の辻さん×小宮山さん打ち合わせで要望が出たが、
    # 今回は「新人(3ヶ月以内)/中堅/ベテラン」の区分のみ実装）。
    tenure = {"people": {}, "new_hire_days": None, "mid_days": None}
    if tenure_json and os.path.exists(tenure_json):
        with open(tenure_json, encoding="utf-8") as f:
            tenure = json.load(f)

    # 企業別の月次目標値（2026-08-31追加）。2026/8/31の打ち合わせで「パートナー企業単位でまず実装」と
    # 合意。実際の目標値は各パートナーから9月分を回収中（未回収の会社はnullのまま＝「未設定」表示）。
    # data/company_targets.json は人手で編集するファイル（CIが自動生成するものではない）。
    company_targets_default = {}
    if company_targets_json and os.path.exists(company_targets_json):
        with open(company_targets_json, encoding="utf-8") as f:
            company_targets_default = json.load(f)

    # パートナーごとのシフト提出状況（2026-08-09追加・build_shift_status.pyの出力）。
    # 表示期間とは連動しない独立スナップショット（開拓先パートナー・行動分析タブと同じ設計）。
    shift_status = None
    if shift_status_json and os.path.exists(shift_status_json):
        with open(shift_status_json, encoding="utf-8") as f:
            shift_status = json.load(f)

    # 商談パイプライン（2026-08-17追加・Cyzen連携API /schedules）。表示期間とは連動しない独立
    # スナップショット。build_shodan_api.pyの出力(cyzen_shodan.json)をそのまま読む。
    shodan_pipeline = None
    if shodan_json and os.path.exists(shodan_json):
        with open(shodan_json, encoding="utf-8") as f:
            sj = json.load(f)
        shodan_pipeline = {
            "generated": sj.get("generated"), "period": sj.get("period"),
            "totals": sj.get("totals", {}), "mappedNames": sj.get("mappedNames"),
            "report_gap": sj.get("report_gap"),
        }

    # 下落メンバー検知（2026-08-10追加・小宮山さんKPIオーナータスク「8月も続けて数値が落ちている人の
    # 抽出」「寺子屋対象者の抽出と要因分析」）。build_declining_performers.pyのロジックをそのまま
    # 毎日のダッシュボード生成に組み込み、日次で自動検知されるようにする。
    # 基準期間＝当月の前月まるごと、比較期間＝直近週（他タブと同じ週次ターム・week_start〜week_end）。
    baseline_end_dt = start_dt.replace(day=1) - timedelta(days=1)
    baseline_start_dt = baseline_end_dt.replace(day=1)
    declining_performers = []
    if attendance_csv and clockout_csv and route_history_json:
        try:
            declining_performers = build_declining_performers(
                roster_csv, closing_csv, attendance_csv, clockout_csv, route_history_json,
                baseline_start_dt.strftime("%Y/%m/%d"), baseline_end_dt.strftime("%Y/%m/%d"),
                week_start, week_end, min_july_weekly_apo=1.0, decline_ratio=0.5)
        except Exception as e:
            print(f"[warn] 下落メンバー検知に失敗: {e}", file=sys.stderr)
            declining_performers = []

    config_for_js = {
        "diff_drop_pct": config.DIFF_HIGHLIGHT_DROP_PCT,
        "diff_rise_pct": config.DIFF_HIGHLIGHT_RISE_PCT,
        "rate_drop_pt": config.RATE_DROP_PT,
        "rate_baseline_pct": config.RATE_BASELINE_PCT,
    }

    # GitHub Actionsのランナーはシステム時刻がUTCのため、datetime.now()をそのまま使うと
    # 「最終更新」表示が9時間ズレる。常にJSTへ明示変換する(2026-08-20・CI対応)。
    updated_label = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")

    attendance_alert_for_js = None
    if alert_master:
        attendance_alert_for_js = {
            "total": alert_master["total"],
            "spot_active_count": alert_master["spot_active_count"],
            "spot_active_rate": alert_master["spot_active_rate"],
            # ① 稼働人員数（ルート自動記録あり）: cyzen_dashboard_master.csvの「ルート自動記録」列>0の人数。
            "route_active_count": alert_master["route_active_count"],
            "route_active_rate": alert_master["route_active_rate"],
            # ③ KPIタイルのドリルダウン用: 会社別の要対応/未打刻/正常人数・個人別記録一式を埋め込む
            # （143名程度の小さいマスターなので、そのまま埋め込んで良い）。
            "company_counts": company_alert_counts,
            "records": [
                {"name": r["name"], "company": resolve_company(r["name"]) or "（不明）",
                 "alert": r["alert"], "spot_count": r["spot_count"], "route_count": r["route_count"],
                 "last_in": r["last_in"], "last_out": r["last_out"], "note": r["note"],
                 "attendance_status": r["attendance_status"],
                 "report_kind": r.get("report_kind", ""), "last_report": r.get("last_report", ""),
                 "report_mismatch": r.get("report_mismatch", False),
                 "chronic_days": r.get("chronic_days", 0), "chronic_stuck": r.get("chronic_stuck", False)}
                for r in alert_master["records"]
            ],
            "report_mismatch_count": sum(1 for r in alert_master["records"] if r.get("report_mismatch")),
            "chronic_stuck_count": sum(1 for r in alert_master["records"] if r.get("chronic_stuck")),
            "by_alert": alert_master["by_alert"],
        }

    html_out = TEMPLATE
    html_out = html_out.replace("__UPDATED__", html.escape(updated_label))
    html_out = html_out.replace("__PERIODS_JSON__", json.dumps(periods, ensure_ascii=False))
    html_out = html_out.replace("__DAILY_PERIODS_JSON__", json.dumps(daily_periods, ensure_ascii=False))
    html_out = html_out.replace("__WEEKLY_PERIODS_JSON__", json.dumps(weekly_periods, ensure_ascii=False))
    html_out = html_out.replace("__WEEKLY_PERIOD_LIST_JSON__", json.dumps(weekly_period_list, ensure_ascii=False))
    html_out = html_out.replace("__MONTHLY_PERIODS_JSON__", json.dumps(monthly_periods, ensure_ascii=False))
    html_out = html_out.replace("__MONTHLY_PERIOD_LIST_JSON__", json.dumps(monthly_period_list, ensure_ascii=False))
    html_out = html_out.replace("__TREND_JSON__", json.dumps(trend, ensure_ascii=False))
    html_out = html_out.replace("__CONFIG_JSON__", json.dumps(config_for_js, ensure_ascii=False))
    html_out = html_out.replace("__SLACK_TOPICS_JSON__", json.dumps(slack_topics, ensure_ascii=False))
    html_out = html_out.replace("__OUTREACH_JSON__", json.dumps(outreach, ensure_ascii=False))
    html_out = html_out.replace("__ROUTE_HISTORY_JSON__", json.dumps(route_history, ensure_ascii=False, separators=(",", ":")))
    html_out = html_out.replace("__AI_SUMMARY_JSON__", json.dumps(ai_summary, ensure_ascii=False))
    html_out = html_out.replace("__COMPLETION_JSON__", json.dumps(completion, ensure_ascii=False))
    html_out = html_out.replace("__URGENT_TARGETS_JSON__", json.dumps(urgent_targets, ensure_ascii=False))
    html_out = html_out.replace("__TRAINING_JSON__", json.dumps(training, ensure_ascii=False))
    html_out = html_out.replace("__DOWHOUR_JSON__", json.dumps(dow_hour, ensure_ascii=False))
    html_out = html_out.replace("__TARGETS_DEFAULT_JSON__", json.dumps(targets_default, ensure_ascii=False))
    html_out = html_out.replace("__ATTENDANCE_ALERT_JSON__", json.dumps(attendance_alert_for_js, ensure_ascii=False))
    html_out = html_out.replace("__SHIFT_STATUS_JSON__", json.dumps(shift_status, ensure_ascii=False))
    html_out = html_out.replace("__SHODAN_JSON__", json.dumps(shodan_pipeline, ensure_ascii=False))
    html_out = html_out.replace("__DECLINING_JSON__", json.dumps(
        {"baseline_start": baseline_start_dt.strftime("%Y-%m-%d"), "baseline_end": baseline_end_dt.strftime("%Y-%m-%d"),
         "recent_start": week_start.replace("/", "-"), "recent_end": week_end.replace("/", "-"),
         "rows": declining_performers}, ensure_ascii=False))
    html_out = html_out.replace("__TENURE_JSON__", json.dumps(tenure, ensure_ascii=False))
    html_out = html_out.replace("__COMPANY_TARGETS_JSON__", json.dumps(company_targets_default, ensure_ascii=False))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    month_data = periods["month"]
    tot = month_data["totals"]
    rate = round(tot["clo_seiyaku"] / tot["apo_kakutoku"] * 100, 1) if tot["apo_kakutoku"] else 0
    reinforcement_candidates = [c["company"] for c in month_data["companies"] if c["suggested_reasons"]]
    interview_candidates = {
        "apo": [r[1] for r in month_data["apo_ranking"] if r[5]],
        "closer": [r[1] for r in month_data["closer_ranking"] if r[5]],
    }
    person_reinforcement_candidates = {
        "apo": [r[1] for r in month_data["apo_ranking"] if r[6]],
        "closer": [r[1] for r in month_data["closer_ranking"] if r[6]],
    }
    summary = {
        "period": [start, end], "out_path": out_path, "totals": tot, "rate": rate,
        "n_companies": len(month_data["companies"]), "n_apo_people": len(month_data["apo_ranking"]),
        "n_closers": len(month_data["closer_ranking"]), "n_soutiku": len(month_data["soutiku_ranking"]),
        "unresolved_apo": month_data["unresolved_apo"], "unresolved_clo": month_data["unresolved_clo"],
        "name_alerts": month_data["name_alerts"],
        "total_headcount": month_data["total_headcount"],
        "attendance_unresolved": month_data["attendance_unresolved"],
        "reinforcement_candidates": reinforcement_candidates,
        "interview_candidates": interview_candidates,
        "person_reinforcement_candidates": person_reinforcement_candidates,
        "week_range": [week_start, week_end],
        "n_slack_topics": len(slack_topics),
        "outreach_summary": outreach["summary"] if outreach else None,
        "roster_csv": roster_csv, "closing_csv": closing_csv, "attendance_csv": attendance_csv,
        "status_csv": status_csv, "slack_topics_json": slack_topics_json, "outreach_json": outreach_json,
        "completion": completion["month"] if completion["available"] else None,
        "dow_hour_available": dow_hour["available"],
        "targets_json": targets_json,
        "attendance_alert_csv": attendance_alert_csv,
        "attendance_alert_summary": attendance_alert_for_js,
        "spot_csv": spot_csv,
        "visits": month_data.get("visits"),
        "route_history_json": route_history_json,
        "route_history_dates": len(route_history),
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--downloads", default=os.path.expanduser("~/Downloads"))
    ap.add_argument("--roster-csv", default=None)
    ap.add_argument("--closing-csv", default=None)
    ap.add_argument("--attendance-csv", default=None,
                     help="Cyzen「報告閲覧」出勤報告のエクスポート（zipまたはcsv）。省略時は稼働人員数を出さない")
    ap.add_argument("--status-csv", default=None,
                     help="運用列（状態タグ/主因/次アクション）管理用Google SheetのCSVエクスポート。省略時は空欄で運用開始")
    ap.add_argument("--slack-topics-json", default=None,
                     help="Slack定性トピックス抽出結果のJSON（data/slack_topics.json）。省略時はSlackセクションが空になる")
    ap.add_argument("--outreach-json", default=None,
                     help="partner-outreachスキルのNotion CRMスナップショットJSON（data/outreach_candidates.json）。省略時は開拓先パートナータブが空になる")
    ap.add_argument("--ai-summary-json", default=None,
                     help="日次自動生成のAI分析サマリーJSON（data/ai_summary.json）。省略時はAI分析欄が空になる")
    ap.add_argument("--targets-json", default=None,
                     help="責任者会議フォーマットの月間目標デフォルト値JSON（data/targets.json）。省略時は目標欄が空欄になる")
    ap.add_argument("--completion-dir", default=None,
                     help="完工数実データCSV群のディレクトリ（data/completion_2607等）。省略時は完工数関連セクションが空になる")
    ap.add_argument("--attendance-alert-csv", default=None,
                     help="出退勤放置アラートのマスターCSV（data/cyzen_dashboard_master.csv）。"
                          "省略時は稼働人員数(スポット作成)・出退勤放置アラート関連の表示が全て空欄・非表示になる")
    ap.add_argument("--spot-csv", default=None,
                     help="スポット台帳CSV（cp932・例: data/spot_YYYYMMDD/spot_*.csv）。"
                          "省略時は訪問種別(新規/再訪問)・対面数・対面率関連の表示が全て空欄になる")
    ap.add_argument("--route-history-json", default=None,
                     help="Cyzen行動履歴の日別・担当者別集計JSON（data/route_history.json・build_route_history.pyの出力）。"
                          "省略時は行動分析タブが空になる")
    ap.add_argument("--closer-shodan-dir", default=None,
                     help="report-v2で報告書=クローザー：獲得（成約）/提案中/敗戦を複数選択エクスポートしたzipの展開先"
                          "（data/closer_shodan/・list_クローザー：*.csvの3ファイル）。"
                          "直販メンバータブのクローザー商談数（Cyzen報告書基準）に使う。省略時は「—」表示")
    ap.add_argument("--urgent-targets-json", default=None,
                     help="役員会（SH役職者定例）で正式決定した急落・下降ターゲット一覧JSON"
                          "（data/urgent_decline_targets.json）。省略時は🎯ターゲットバッジが非表示")
    ap.add_argument("--training-json", default=None,
                     help="研修参加者名簿JSON（data/training_participants.json）。"
                          "省略時は研修効果モニタリングが空になる")
    ap.add_argument("--shift-status-json", default=None,
                     help="パートナーごとのシフト提出状況JSON（data/shift_status.json・build_shift_status.pyの出力）。"
                          "省略時はシフト提出状況セクションが非表示")
    ap.add_argument("--shodan-json", default=None,
                     help="商談パイプラインJSON（build_shodan_api.pyの出力）。省略時は商談パイプラインセクションが非表示")
    ap.add_argument("--clockout-csv", default=None,
                     help="Cyzen「報告閲覧」勤務終了報告のマージ済みCSV（data/clockout_merged.csv）。"
                          "省略時は下落メンバータブが空になる")
    ap.add_argument("--tenure-json", default=None,
                     help="在籍期間データJSON（data/tenure.json・build_tenure_api.pyの出力）。"
                          "省略時は在籍区分列・傾向分析タブの在籍期間セクションが空になる")
    ap.add_argument("--company-targets-json", default=None,
                     help="企業別の月次目標値JSON（data/company_targets.json・人手で編集）。"
                          "省略時は企業別タブの目標/達成率列が「未設定」表示になる")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=os.path.expanduser("~/Desktop/partner_dashboard.html"))
    args = ap.parse_args()

    roster = args.roster_csv or find_latest(args.downloads, "※新：アポインターの獲得履歴*.csv")
    closing = args.closing_csv or find_latest(args.downloads, "※新獲得報告データ*.csv")
    if not roster or not closing:
        print("ERROR: roster/closing CSV が見つかりません", file=sys.stderr)
        sys.exit(1)

    attendance = resolve_attendance_source(args.attendance_csv) if args.attendance_csv else None

    # GitHub Actionsのランナーはシステム時刻がUTCのため、datetime.now()をそのまま使うと
    # JST早朝(8-9時台等、UTCではまだ前日)に「今日」の判定がずれる。常にJSTへ明示変換する
    # (2026-08-20・CI対応)。
    now = datetime.utcnow() + timedelta(hours=9)
    start = args.start or now.strftime("%Y/%m/01")
    end = args.end or now.strftime("%Y/%m/%d")

    summary = build(roster, closing, start, end, args.out, attendance_csv=attendance,
                     status_csv=args.status_csv, slack_topics_json=args.slack_topics_json,
                     outreach_json=args.outreach_json, ai_summary_json=args.ai_summary_json,
                     targets_json=args.targets_json, completion_dir=args.completion_dir,
                     attendance_alert_csv=args.attendance_alert_csv, spot_csv=args.spot_csv,
                     route_history_json=args.route_history_json,
                     closer_shodan_dir=args.closer_shodan_dir,
                     urgent_targets_json=args.urgent_targets_json,
                     training_json=args.training_json,
                     shift_status_json=args.shift_status_json,
                     shodan_json=args.shodan_json,
                     clockout_csv=args.clockout_csv,
                     tenure_json=args.tenure_json,
                     company_targets_json=args.company_targets_json)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
