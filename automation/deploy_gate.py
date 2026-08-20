# -*- coding: utf-8 -*-
"""パスワードゲートHTML注入ロジック(2026-08-19新設・2026-08-20にci_refresh.py用に切り出し)。
deploy.py(ローカル手動実行用)とci_refresh.py(GitHub Actions用)の両方から使う共通処理。
"""
import os

# パスワードはハッシュのみ保持(平文はこのファイルにも埋め込まない)
PW_HASH = "b79e55db91e640b42d1ed5a8c31788ca2b89ae39687933a15d6489169f1b3b19"

GATE_HTML = """
<div id="__gate" style="position:fixed;inset:0;background:#0F1F3D;color:#fff;display:flex;
    align-items:center;justify-content:center;z-index:999999;font-family:'Hiragino Sans','Yu Gothic',sans-serif;">
  <form id="__gateForm" style="text-align:center;padding:32px;background:#16264A;border-radius:12px;
      box-shadow:0 10px 40px rgba(0,0,0,.4);">
    <div style="font-size:18px;font-weight:700;margin-bottom:6px;">🔒 パートナー実績ダッシュボード</div>
    <div style="font-size:12px;color:#94A3B8;margin-bottom:16px;">社内限定・パスワードを入力してください</div>
    <input id="__gatePw" type="password" placeholder="パスワード" autofocus
        style="padding:10px 12px;border-radius:6px;border:1px solid #334155;font-size:15px;
        background:#0F1F3D;color:#fff;width:180px;">
    <button type="submit" style="padding:10px 18px;border-radius:6px;border:none;margin-left:8px;
        background:#1A56DB;color:#fff;font-size:15px;cursor:pointer;">入る</button>
    <div id="__gateErr" style="color:#f87171;margin-top:10px;font-size:12px;min-height:14px;"></div>
  </form>
</div>
<style>body:not(.__unlocked) > *:not(#__gate){display:none !important;}</style>
<script>
(function(){
  var KEY = 'ff_partner_dash_auth_v1';
  var HASH = '%s';
  async function sha256(text){
    var enc = new TextEncoder().encode(text);
    var buf = await crypto.subtle.digest('SHA-256', enc);
    return Array.prototype.map.call(new Uint8Array(buf), function(b){
      return ('00' + b.toString(16)).slice(-2);
    }).join('');
  }
  function unlock(){
    document.body.classList.add('__unlocked');
    var g = document.getElementById('__gate');
    if (g) g.remove();
  }
  if (sessionStorage.getItem(KEY) === '1') { unlock(); }
  document.getElementById('__gateForm').addEventListener('submit', async function(e){
    e.preventDefault();
    var pw = document.getElementById('__gatePw').value;
    var h = await sha256(pw);
    if (h === HASH) {
      sessionStorage.setItem(KEY, '1');
      unlock();
    } else {
      document.getElementById('__gateErr').textContent = 'パスワードが違います';
    }
  });
})();
</script>
""" % PW_HASH


def inject_gate(src_path, out_path):
    with open(src_path, encoding="utf-8") as f:
        html = f.read()
    marker = "<body>"
    idx = html.find(marker)
    if idx == -1:
        raise SystemExit("<body> タグが見つかりません")
    insert_at = idx + len(marker)
    html = html[:insert_at] + GATE_HTML + html[insert_at:]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
