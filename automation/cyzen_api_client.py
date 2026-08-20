# -*- coding: utf-8 -*-
"""Cyzen連携API（レッドフォックス社 REST API）の共通クライアント。

設計方針（2026-08-15・Cyzen社下村さんの回答を反映）:

1. **GET専用**。このダッシュボードは読み取りしか行わない。トークンには書き込み権限も
   含まれるため、POST/PUT/DELETEを構造的に発行できないようにガードしている
   （`_request()`がGET以外を受け付けない）。

2. **レート制限の順守**。「1アクセストークンあたり秒間5回まで」。さらにこのトークンは
   Medurance社の別ダッシュボードと**仕様上共用**されている（1契約1トークンで複数サービスへの
   流用可能、とCyzen社より正式回答済み）ため、こちらだけで枠を使い切らないよう
   `MIN_INTERVAL_SEC`（既定0.25秒＝秒間4回相当）に抑えている。Cyzen社からも
   「秒間5リクエストを超えそうなら1リクエストごとに0.1〜0.2秒の遅延を入れれば回避可能」と
   案内を受けている。

3. **差分取得が前提**。Cyzen社より「差分でデータを取得する想定であれば特に懸念なし」との回答。
   全件取得は原則行わず、updated_from/updated_to等で差分だけを取る運用にする。

4. **トークンは絶対にログ・例外メッセージに出さない**。環境変数からのみ読み、値を保持する
   属性はprivate扱いとし、`__repr__`にも含めない。

使い方:
    from cyzen_api_client import CyzenAPIClient
    c = CyzenAPIClient()                      # 環境変数からトークン・company_idを取得
    groups = c.get_all("groups", key="groups")
"""
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://ext.cyzen.cloud/webapi/v0"

# 本番環境のcompany_id（2026-08-11に疎通確認済み。検証環境40c48760…は空テナントのため使わない）
DEFAULT_COMPANY_ID = "794a32fe1dee9f8dcfb0206d9ee554c1"

# 既定のトークン環境変数名。Medurance社と共用のトークンだが、Cyzen社の回答により仕様上問題なし。
DEFAULT_TOKEN_ENV = "CYZEN_DASHBOARD_TOKEN"
FALLBACK_TOKEN_ENVS = ("CYZEN_PROD_ACCESS_TOKEN",)

# 秒間5回制限に対する安全マージン（0.25秒間隔＝秒間4回相当）
MIN_INTERVAL_SEC = 0.25

# リトライ設定（資料推奨: ランダム1,2,4,8,16秒）
MAX_RETRIES = 5
RETRY_STATUS = {429, 500, 502, 503, 504}

# 1リクエストあたりの最大取得件数（API仕様の上限）
PAGE_SIZE = 200

# 暴走防止。1回のget_all()でこの回数を超えたら例外にする（差分取得なら通常数回で終わる）
MAX_PAGES = 500


class CyzenAPIError(RuntimeError):
    """Cyzen APIの呼び出しに失敗した。メッセージにトークンは含めない。"""


class CyzenAPIClient:
    def __init__(self, token_env=None, company_id=None, min_interval=MIN_INTERVAL_SEC,
                 verbose=False):
        self._token = self._resolve_token(token_env)
        self.company_id = company_id or os.environ.get("CYZEN_COMPANY_ID") or DEFAULT_COMPANY_ID
        self.min_interval = min_interval
        self.verbose = verbose
        self._last_call_at = 0.0
        self.request_count = 0

    # ------------------------------------------------------------------ 認証

    @staticmethod
    def _resolve_token(token_env=None):
        names = [token_env] if token_env else [DEFAULT_TOKEN_ENV, *FALLBACK_TOKEN_ENVS]
        for name in names:
            if not name:
                continue
            value = os.environ.get(name)
            if value:
                return value
        raise CyzenAPIError(
            "アクセストークンが環境変数に見つかりません（探した変数名: "
            + ", ".join(n for n in names if n)
            + "）。~/.zshrc等でexportし、非対話シェルから実行する場合は"
            " `zsh -ic 'python3 ...'` のように対話シェル経由で起動してください。"
        )

    def __repr__(self):  # トークンを絶対に露出させない
        return f"<CyzenAPIClient company_id={self.company_id[:8]}… requests={self.request_count}>"

    # ------------------------------------------------------------ 低レベル呼び出し

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call_at = time.monotonic()

    def _request(self, method, endpoint, params):
        if method != "GET":
            # このクライアントは読み取り専用。書き込み系は構造的に発行できないようにする。
            raise CyzenAPIError(
                f"このクライアントはGET専用です（要求されたメソッド: {method}）。"
                "ダッシュボード用途では書き込みを行いません。"
            )
        query = dict(params or {})
        query.setdefault("company_id", self.company_id)
        # None の値は送らない
        query = {k: v for k, v in query.items() if v is not None}
        url = f"{BASE_URL}/{endpoint.lstrip('/')}?{urllib.parse.urlencode(query)}"

        last_error = None
        for attempt in range(MAX_RETRIES):
            self._throttle()
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", f"bearer {self._token}")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    self.request_count += 1
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                self.request_count += 1
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                if e.code in RETRY_STATUS and attempt < MAX_RETRIES - 1:
                    wait = (2 ** attempt) + random.random()
                    if self.verbose:
                        print(f"  [retry {attempt+1}/{MAX_RETRIES}] HTTP {e.code} -> {wait:.1f}秒待機")
                    time.sleep(wait)
                    last_error = f"HTTP {e.code}: {body}"
                    continue
                raise CyzenAPIError(f"{endpoint} でHTTP {e.code}: {body}") from None
            except urllib.error.URLError as e:
                if attempt < MAX_RETRIES - 1:
                    wait = (2 ** attempt) + random.random()
                    if self.verbose:
                        print(f"  [retry {attempt+1}/{MAX_RETRIES}] 接続エラー -> {wait:.1f}秒待機")
                    time.sleep(wait)
                    last_error = f"URLError: {e.reason}"
                    continue
                raise CyzenAPIError(f"{endpoint} への接続に失敗: {e.reason}") from None
        raise CyzenAPIError(f"{endpoint} がリトライ上限に到達: {last_error}")

    # ------------------------------------------------------------ 公開メソッド

    def get(self, endpoint, **params):
        """1ページだけ取得する（ページングしない）。"""
        return self._request("GET", endpoint, params)

    def get_all(self, endpoint, key=None, next_key=None, **params):
        """`next_XXX_id` を辿って全ページを取得し、リストを返す。

        key:      レスポンス中のデータ配列のキー（省略時はendpoint名を使う）
        next_key: 次ページIDのキー（省略時は "next_" + 単数形id を推測）
        """
        key = key or endpoint.strip("/")
        items = []
        cursor = None
        for page in range(MAX_PAGES):
            page_params = dict(params)
            if cursor:
                page_params[self._cursor_param(key, next_key)] = cursor
            data = self._request("GET", endpoint, page_params)
            chunk = data.get(key) or []
            items.extend(chunk)
            cursor = self._extract_cursor(data, key, next_key)
            if self.verbose:
                print(f"  {endpoint} page{page+1}: +{len(chunk)}件 (累計{len(items)}件)")
            if not cursor or not chunk:
                return items
        raise CyzenAPIError(
            f"{endpoint} のページングが{MAX_PAGES}回を超えました。"
            "差分取得の条件（期間指定など）が広すぎる可能性があります。"
        )

    @staticmethod
    def _cursor_param(key, next_key):
        if next_key:
            return next_key
        singular = key[:-1] if key.endswith("s") else key
        return f"next_{singular}_id"

    def _extract_cursor(self, data, key, next_key):
        name = self._cursor_param(key, next_key)
        cursor = data.get(name)
        if cursor:
            return cursor
        # 想定外のキー名でも "next_" で始まる値があれば拾う（仕様差異への保険）
        for k, v in data.items():
            if k.startswith("next_") and v:
                return v
        return None


# ---------------------------------------------------------------- 役割マスタ

# 「役割」タグカテゴリ名（/user_tags の user_tag_category_name）
ROLE_CATEGORY = "役割"
ROLE_APPOINTER = "アポインター"
ROLE_CLOSER = "クローザー"


def build_role_map(client):
    """user_id → {name, code, roles(set), companies(list), groups(list)} のマップを作る。

    「予定作成者＝アポインター／予定参加者＝クローザー及びアポインター」という業務ルールを、
    APIに作成者フィールドが無い制約下で再現するために使う（要件定義9章）。
    """
    tags = client.get_all("user_tags", key="user_tags")
    tag_by_id = {t["user_tag_id"]: t for t in tags}
    role_tag_ids = {
        t["user_tag_id"]: t["user_tag_name"]
        for t in tags
        if t.get("user_tag_category_name") == ROLE_CATEGORY
    }

    users = client.get_all("users", key="users", field="all")  # field は小文字 all（大文字ALLは400）
    role_map = {}
    for u in users:
        roles, others = set(), []
        for ut in u.get("user_tags") or []:
            tid = ut.get("user_tag_id")
            if tid in role_tag_ids:
                roles.add(role_tag_ids[tid])
            elif tid in tag_by_id:
                others.append(tag_by_id[tid]["user_tag_name"])
        role_map[u["user_id"]] = {
            "name": (u.get("user_name") or "").strip(),
            "code": u.get("user_code") or "",
            "roles": roles,
            "other_tags": others,
            "groups": [g.get("group_id") for g in (u.get("groups") or [])],
            "account_status": u.get("account_status"),
        }
    return role_map, tag_by_id, role_tag_ids
