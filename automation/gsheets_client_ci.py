# -*- coding: utf-8 -*-
"""Google Sheets APIクライアント(GitHub Actions用・2026-08-20新設)。
ローカル版(gsheets_client.py)と違い、認証情報をファイルではなく環境変数
(GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REFRESH_TOKEN)
から読む。ブラウザでの初回許可は不要(refresh_tokenで無人更新)。
"""
import csv
import io
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def get_credentials():
    client_id = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
    refresh_token = os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"]
    creds = Credentials(
        None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret, scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def _sheet_title_by_gid(service, spreadsheet_id, gid):
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    for sh in meta.get("sheets", []):
        props = sh["properties"]
        if str(props["sheetId"]) == str(gid):
            return props["title"]
    raise RuntimeError(f"gid={gid} に一致するシートが見つかりません(spreadsheet_id={spreadsheet_id})")


def fetch_sheet_rows(service, spreadsheet_id, gid):
    title = _sheet_title_by_gid(service, spreadsheet_id, gid)
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{title}'").execute()
    return resp.get("values", [])


def fetch_sheet_as_csv(service, spreadsheet_id, gid, out_path):
    rows = fetch_sheet_rows(service, spreadsheet_id, gid)
    max_cols = max((len(r) for r in rows), default=0)
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r + [""] * (max_cols - len(r)))
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
    return out_path, len(rows)


SHEETS = [
    ("roster", "kintone↔アポ集計(後確通過ベース)", "1VycVDBMXVNT95Jc6tzG9VmZgVB_I9Pvtj95xySrS4PY", "2140126988"),
    ("closing", "獲得報告データ", "1CaKmNuU5AufrJ8MnAfu7sz8pZoGK1N3g6xRqjQMpLSU", "651960695"),
    ("status", "運用列Sheet", "1MSiV9lYS2gzLN3JKHW2fYdgp6j4XMqnXyV84ENx04oI", "1247766737"),
    ("shift", "シフト表", "1HX7xFXvIYFapWyWmDOsrTXubgjYiWlQ1_ybFIhBMQpM", "353470606"),
]


def fetch_all(out_dir):
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)
    out_paths = {}
    for key, label, spreadsheet_id, gid in SHEETS:
        out_path = os.path.join(out_dir, f"{key}_live.csv")
        _, n = fetch_sheet_as_csv(service, spreadsheet_id, gid, out_path)
        print(f"{label}: {n}行 -> {out_path}")
        out_paths[key] = out_path
    return out_paths
