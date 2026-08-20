# -*- coding: utf-8 -*-
"""共通集計ロジック（企業別・アポインター・創蓄アポインター・クローザー）。
週次PDF（aggregate_and_render.py後継）と日次ダッシュボードの両方から import して使う。

データソース:
  - roster_csv:  ※新：アポインターの獲得履歴（Googleスプレッドシート export）… アポ数(獲得日ベース・キャンセル含む)
  - closing_csv: ※新獲得報告データ - マスターデータ（Googleスプレッドシート export）… 成約数・売上(タイムスタンプ日ベース)
  - kitone_csv:  KINTONE案件管理エクスポート（任意）… CO/キャンセル/否決の内訳のみに使用
会社名解決: company_resolver.py（Cyzenユーザーマスタを一次ソースに、ロースター多数決/Slack送信者パース/直販スタッフ判定でフォールバック）
"""
import csv
import glob
import os
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta

from company_resolver import resolve_company, canon, norm_name, canon_name
import config

DIRECT = "株式会社Fit Founder"
DIRECT_STAFF = {"鈴木隆輔", "川上留以", "川上 留以", "横山豪", "伊藤蓮", "百瀬遥輝", "木村瞭太", "吉田龍吾",
                "橋口航大", "平山沙羅", "恩田哉人", "小野龍一", "上野滉己"}

COMPANY_MAP = {
    "JINNOVA": "株式会社JINNOVA", "Ambitious株式会社": "Ambitious株式会社",
    "forme works": "株式会社ForMe works", "LeadMore": "株式会社LeadMore", "Lead More": "株式会社LeadMore",
    "スマートハウス推進統括本部": "株式会社Fit Founder", "LIVIONpartners": "株式会社LIVION partners",
    "ゼニソ": "株式会社ゼニソ", "G.WORTH": "G.WORTH株式会社", "GWORTH": "G.WORTH株式会社",
    "アフターホーム": "アフターホーム株式会社", "STORIA": "株式会社STORIA", "GUIDANCE": "株式会社guidance",
    "一興商事": "一興商事株式会社", "Corest home": "株式会社Corest home", "D-MAK": "D-MAK株式会社",
    "ベスティブロ": "株式会社ベスティブロ", "HY": "HY株式会社",
}


def find_latest(downloads_dir, pattern):
    candidates = glob.glob(os.path.join(downloads_dir, pattern))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def parse_price(raw):
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else 0


def parse_sender_company(sender):
    s = (sender or "").strip().lstrip("@")
    if s.startswith("（株）") or s.startswith("(株)"):
        parts = s.split("　", 1)
        comp_raw = parts[0] if len(parts) == 2 else s
        for k, v in COMPANY_MAP.items():
            if k in comp_raw:
                return v, None
    m = re.search(r"\(株\)([A-Za-z.]+)", s)
    if m:
        frag = m.group(1)
        for k, v in COMPANY_MAP.items():
            if k.upper() == frag.upper():
                return v, None
    if "_" in s:
        name_part, comp_raw = s.split("_", 1)
        for k, v in COMPANY_MAP.items():
            if k in comp_raw:
                return v, norm_name(name_part)
    if "　" in s:
        name_part, comp_raw = s.split("　", 1)
        for k, v in COMPANY_MAP.items():
            if k in comp_raw:
                return v, norm_name(name_part)
    if " " in s:
        name_part, comp_raw = s.rsplit(" ", 1)
        for k, v in COMPANY_MAP.items():
            if k in comp_raw:
                return v, norm_name(name_part)
    return None, norm_name(s)


def ts_date(ts):
    return ts.split(" ")[0] if ts else None


def with_rank(rows, key_idx):
    out, prev_val, rank = [], None, 0
    for i, r in enumerate(rows, start=1):
        if r[key_idx] != prev_val:
            rank = i
            prev_val = r[key_idx]
        out.append([rank] + r)
    return out


def aggregate(roster_csv, closing_csv, start, end, kitone_csv=None):
    """start/end: 'YYYY/MM/DD' 文字列（両端含む）。kitone_csv を渡すとCO/キャンセル/否決も集計する。"""
    def in_range(d):
        return d and start <= d <= end

    with open(roster_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        ridx = {h: i for i, h in enumerate(next(r))}
        rrows = list(r)

    person_company_votes = defaultdict(lambda: defaultdict(int))
    person_display = {}
    for row in rrows:
        name = canon_name(row[ridx["アポインター"]].strip())
        if not name:
            continue
        n = norm_name(name)
        person_display.setdefault(n, name)
        co = canon(row[ridx["会社名"]].strip())
        if co:
            person_company_votes[n][co] += 1

    apo_kakutoku_co = defaultdict(int)
    person_apo_count = defaultdict(int)
    person_apo_cancel_count = defaultdict(int)
    soutiku_people = set()
    for row in rrows:
        name = canon_name(row[ridx["アポインター"]].strip())
        if not name:
            continue
        n = norm_name(name)
        co = canon(row[ridx["会社名"]].strip())
        if in_range(row[ridx["獲得日"]]):
            person_apo_count[n] += 1
            if row[ridx["キャンセル有無"]].strip():
                person_apo_cancel_count[n] += 1
            if co:
                apo_kakutoku_co[co] += 1
            if row[ridx["創蓄"]].strip() and not row[ridx["キャンセル有無"]].strip():
                soutiku_people.add(n)

    with open(closing_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        cidx = {h: i for i, h in enumerate(next(r))}
        crows = list(r)

    sender_company_by_name = {}
    for row in crows:
        comp, name = parse_sender_company(row[cidx["送信者"]])
        if comp:
            if name:
                sender_company_by_name[name] = comp
            clo_n = norm_name(canon_name(row[cidx["クローザー名"]].strip()))
            if clo_n:
                sender_company_by_name[clo_n] = comp

    def company_of(raw_name):
        return resolve_company(raw_name, roster_votes=person_company_votes,
                                sender_map=sender_company_by_name, direct_staff=DIRECT_STAFF)

    apo_seiyaku_co = defaultdict(int)
    clo_seiyaku_co = defaultdict(int)
    clo_uriage_co = defaultdict(int)
    apo_seiyaku_person = defaultdict(int)
    clo_seiyaku_person = defaultdict(int)
    clo_uriage_person = defaultdict(int)
    display_apo, display_clo = {}, {}
    unresolved_apo, unresolved_clo = [], []
    n_closing_in_period = 0

    for row in crows:
        ts = row[cidx["タイムスタンプ"]]
        if not in_range(ts_date(ts)):
            continue
        n_closing_in_period += 1
        apo_name = canon_name(row[cidx["アポインター名"]].strip())
        clo_name = canon_name(row[cidx["クローザー名"]].strip())
        price = parse_price(row[cidx["販売価格"]])
        if apo_name:
            n = norm_name(apo_name)
            co = company_of(apo_name)
            apo_seiyaku_person[n] += 1
            display_apo.setdefault(n, apo_name)
            if co:
                apo_seiyaku_co[co] += 1
            else:
                unresolved_apo.append(apo_name)
        if clo_name:
            n = norm_name(clo_name)
            co = company_of(clo_name)
            clo_seiyaku_person[n] += 1
            clo_uriage_person[n] += price
            display_clo.setdefault(n, clo_name)
            if co:
                clo_seiyaku_co[co] += 1
                clo_uriage_co[co] += price
            else:
                unresolved_clo.append(clo_name)

    company_cooling = company_cancel = company_hiketsu = None
    if kitone_csv:
        company_cooling, company_cancel, company_hiketsu = _kitone_status(kitone_csv, start, end)

    companies = (set(apo_kakutoku_co) | set(apo_seiyaku_co) | set(clo_seiyaku_co)) - {"", "不明"}
    if company_cooling:
        companies |= set(company_cooling) | set(company_cancel) | set(company_hiketsu)

    company_rows = []
    for co in companies:
        ak = apo_kakutoku_co.get(co, 0)
        ase = apo_seiyaku_co.get(co, 0)
        cse = clo_seiyaku_co.get(co, 0)
        cu = clo_uriage_co.get(co, 0)
        row = {"company": co, "apo_kakutoku": ak, "apo_seiyaku": ase, "clo_seiyaku": cse,
               "uriage": cu, "rate": round(cse / ak * 100, 1) if ak else None}
        if company_cooling is not None:
            cool = company_cooling.get(co, 0)
            canc = company_cancel.get(co, 0)
            hik = company_hiketsu.get(co, 0)
            net = cse - cool - canc - hik
            row.update(cooling=cool, cancel=canc, hiketsu=hik, net=net,
                       net_rate=round(net / cse * 100) if cse else None)
        company_rows.append(row)
    company_rows.sort(key=lambda r: -r["apo_kakutoku"])

    people = (set(person_apo_count) | set(apo_seiyaku_person)) - {""}
    apo_rows = []
    for n in people:
        # person_display はroster全件から毎回同じ順序で構築されるため表記が安定する。display_apo は
        # closing_csvのその日の行から拾うだけなので、日によって表記ゆれ（例:髙橋/高橋）が混入しうる。
        # 表示名が日によって割れるとフロント側の文字列完全一致マッチ（ドリルダウン等）が崩れるため、
        # person_displayを優先する（2026-08-19修正）。
        name = person_display.get(n) or display_apo.get(n, n)
        co = company_of(name) or "（不明）"
        apo_rows.append([name, co, apo_seiyaku_person.get(n, 0), person_apo_count.get(n, 0)])
    apo_rows.sort(key=lambda r: (-r[2], -r[3]))
    apo_ranked = with_rank(apo_rows, key_idx=3)

    soutiku_rows = [r for r in apo_rows if r[0] and norm_name(r[0]) in soutiku_people]
    soutiku_rows.sort(key=lambda r: (-r[2], -r[3]))
    soutiku_ranked = with_rank(soutiku_rows, key_idx=3)

    closers = set(clo_seiyaku_person) - {""}
    clo_rows = []
    for n in closers:
        name = display_clo.get(n, n)
        co = company_of(name) or "（不明）"
        clo_rows.append([name, co, clo_seiyaku_person.get(n, 0), clo_uriage_person.get(n, 0)])
    clo_rows.sort(key=lambda r: -r[2])
    clo_ranked = with_rank(clo_rows, key_idx=2)

    person_company_map = {}
    for r in apo_rows:
        person_company_map[r[0]] = r[1]
    for r in clo_rows:
        person_company_map.setdefault(r[0], r[1])
    name_alerts = find_name_alerts(person_company_map)

    # アポ獲得達成者数・成約達成者数（会社ごと・全社）: 「実際に1件でも成果を出した人数」を可視化する。
    # 稼働人員数（Cyzen出勤打刻）とは別物（打刻はしたが成果ゼロの人もいるため、両方見比べられるようにする）。
    apo_achievers_by_co = defaultdict(set)
    apo_seiyaku_achievers_by_co = defaultdict(set)
    clo_seiyaku_achievers_by_co = defaultdict(set)
    for name, co, ase_p, acount_p in apo_rows:
        if acount_p > 0:
            apo_achievers_by_co[co].add(name)
        if ase_p > 0:
            apo_seiyaku_achievers_by_co[co].add(name)
    for name, co, cse_p, _cu_p in clo_rows:
        if cse_p > 0:
            clo_seiyaku_achievers_by_co[co].add(name)
    for c in company_rows:
        co = c["company"]
        seiyaku_achievers_co = apo_seiyaku_achievers_by_co.get(co, set()) | clo_seiyaku_achievers_by_co.get(co, set())
        c["apo_achiever_count"] = len(apo_achievers_by_co.get(co, set()))
        c["seiyaku_achiever_count"] = len(seiyaku_achievers_co)

    all_apo_achievers = {r[0] for r in apo_rows if r[3] > 0}
    all_seiyaku_achievers = {r[0] for r in apo_rows if r[2] > 0} | {r[0] for r in clo_rows if r[2] > 0}

    # 直販メンバータブ用: アポ数(後確通過)=総獲得数−キャンセル数 を出すためのキャンセル数（表示名キー）。
    # apo_ranking の行配列に混ぜず別キーで持つのは、既存の行インデックス(r[5],r[6]…)を壊さないため。
    apo_cancel_by_name = {}
    for n, cnt in person_apo_cancel_count.items():
        disp = display_apo.get(n) or person_display.get(n, n)
        apo_cancel_by_name[disp] = cnt

    return {
        "start": start, "end": end,
        "n_closing_in_period": n_closing_in_period,
        "companies": company_rows,
        "apo_ranking": apo_ranked,
        "soutiku_ranking": soutiku_ranked,
        "closer_ranking": clo_ranked,
        "unresolved_apo": sorted(set(unresolved_apo)),
        "unresolved_clo": sorted(set(unresolved_clo)),
        "name_alerts": name_alerts,
        "apo_cancel_by_name": apo_cancel_by_name,
        "totals": {
            "apo_kakutoku": sum(r["apo_kakutoku"] for r in company_rows),
            "apo_seiyaku": sum(r["apo_seiyaku"] for r in company_rows),
            "clo_seiyaku": sum(r["clo_seiyaku"] for r in company_rows),
            "uriage": sum(r["uriage"] for r in company_rows),
            "apo_achiever_count": len(all_apo_achievers),
            "seiyaku_achiever_count": len(all_seiyaku_achievers),
        },
    }


def _edit_distance_le(a, b, maxd):
    """レーベンシュタイン距離が maxd 以下かどうか（短い人名向けの簡易DP）"""
    if abs(len(a) - len(b)) > maxd:
        return False
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, lb + 1):
            cur = dp[j]
            dp[j] = prev if a[i - 1] == b[j - 1] else 1 + min(prev, dp[j], dp[j - 1])
            prev = cur
    return dp[lb] <= maxd


def _is_katakana(s):
    return bool(s) and all(("゠" <= ch <= "ヿ") or ch == "ー" for ch in s)


def _strip_affix_noise(s):
    """比較専用: 括弧書き・英字混じりの付記（例: "(wiz)"「wiz 」）を取り除く。表示名そのものは変えない。"""
    s = re.sub(r"[\(（][^)）]*[\)）]", "", s)
    s = re.sub(r"[A-Za-z]+", "", s)
    return s.strip()


def find_name_alerts(person_company_map):
    """会社ごとに人名をグルーピングし、表記ゆれ・重複入力の疑いがあるペアを検出する。
    person_company_map: {表示名: 会社名}。既にNAME_CANONで統合済みの名前同士は対象外（norm_nameが一致するため）。
    自動では統合しない。検出結果は人間の確認・NAME_CANONへの追記判断に使う。
    """
    by_company = defaultdict(list)
    for name, co in person_company_map.items():
        if name:
            by_company[co].append(name)

    alerts = []
    for co, names in by_company.items():
        names = sorted(set(names))
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                na, nb = norm_name(a), norm_name(b)
                if na == nb:
                    continue
                reason = None
                if min(len(na), len(nb)) >= 2 and _edit_distance_le(na, nb, 1):
                    reason = "1文字違い（誤字の可能性）"
                elif len(na) != len(nb) and (na in nb or nb in na):
                    reason = "略称・部分一致の可能性"
                elif len(na) == len(nb) and sorted(na) == sorted(nb):
                    reason = "文字の並び順違いの可能性"
                else:
                    sa, sb = _strip_affix_noise(na), _strip_affix_noise(nb)
                    if sa and sb and sa == sb and (na != sa or nb != sb):
                        reason = "所属会社等の付記位置違いの可能性"
                if reason:
                    alerts.append({"company": co, "name_a": a, "name_b": b, "reason": reason})
        katakana_names = [n for n in names if _is_katakana(norm_name(n))]
        kanji_names = [n for n in names if n not in katakana_names]
        for kn in katakana_names:
            alerts.append({
                "company": co, "name_a": kn,
                "name_b": "、".join(kanji_names[:5]) if kanji_names else "（同社に他の氏名なし）",
                "reason": "カタカナ単独表記（漢字表記との重複の可能性）",
            })
    return alerts


def _kitone_status(kitone_csv, start, end):
    def in_range(d):
        return d and start <= d <= end

    with open(kitone_csv, encoding="cp932", errors="replace") as f:
        r = csv.reader(f)
        kidx = {h: i for i, h in enumerate(next(r))}
        krows = list(r)
    kstarts = [row for row in krows if row[kidx["レコードの開始行"]] == "*"]
    ktarget = [row for row in kstarts if in_range(row[kidx["契約日"]])]
    cooling = defaultdict(int)
    cancel = defaultdict(int)
    hiketsu = defaultdict(int)
    for row in ktarget:
        cco = canon(row[kidx["クローザー会社名"]].strip())
        if not cco:
            continue
        status = row[kidx["進捗状況"]]
        if status == "クーリングオフ":
            cooling[cco] += 1
        elif status == "キャンセル":
            cancel[cco] += 1
        elif status == "審査否決":
            hiketsu[cco] += 1
    return cooling, cancel, hiketsu


def aggregate_attendance(attendance_csv, start, end):
    """出勤報告CSV（Cyzen「報告閲覧」画面: 報告書=出勤報告でエクスポートしたCSV）から、
    会社別の稼働人員数を集計する。

    start/end: 'YYYY-MM-DD' 文字列（両端含む。attendance CSVの「日付」列がこの書式のため、
    roster/closing側の 'YYYY/MM/DD' とは異なる点に注意）。

    KPI定義（2026-07-23 データ集計の定義について、より）: Cyzenの出勤ステータス打刻を押した人を
    稼働1名とみなす。同一人物が同じ日に複数回出勤打刻しても1稼働として重複排除する。
    ここでは対象期間内に1回でも出勤打刻があった人数を「稼働人員数」として会社ごとに集計する
    （行動履歴のルート自動記録による実移動確認までは行っていない簡易版）。
    """
    def in_range(d):
        return d and start <= d <= end

    with open(attendance_csv, encoding="cp932", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        rows = list(r)

    seen = set()
    company_people = defaultdict(set)
    person_company = {}
    person_display = {}
    person_days = defaultdict(set)
    unresolved = set()

    for row in rows:
        name = row[idx["ユーザー名"]].strip()
        date = row[idx["日付"]].strip()
        if not name or not in_range(date):
            continue
        n = norm_name(name)
        key = (n, date)
        if key in seen:
            continue
        seen.add(key)
        person_days[n].add(date)
        person_display.setdefault(n, name)
        co = resolve_company(name)
        if co:
            company_people[co].add(n)
            person_company[n] = co
        else:
            unresolved.add(name)

    company_counts = {co: len(people) for co, people in company_people.items()}
    person_rows = []
    for n, days in person_days.items():
        person_rows.append([person_display.get(n, n), person_company.get(n, "（不明）"), len(days)])
    person_rows.sort(key=lambda r: -r[2])

    return {
        "company_counts": company_counts,
        "person_rows": person_rows,
        "unresolved": sorted(unresolved),
        "start": start, "end": end,
    }


def aggregate_closer_shodan(csv_dir, start, end):
    """クローザー商談数（Cyzen報告書ベース）を集計する。
    csv_dir配下の `list_クローザー：*.csv`（獲得（成約）／提案中／敗戦の3種、report-v2の「報告書」
    複数選択エクスポートをそのまま展開したもの）を全部読み、報告日時ベースで
    start<=date<=end に該当する行数を「ユーザー名」（＝報告者＝クローザー本人）ごとに合算する。
    3種の合計＝直販メンバータブの「クローザー商談数」（Slack基準とは別の、Cyzen報告書基準の値）。
    start/end: 'YYYY/MM/DD'（roster/closingと同じ書式。CSV側は'YYYY-MM-DD HH:MM:SS'なので変換して比較）。
    戻り値: {表示名(canon_name後): 件数} の辞書（apo_cancel_by_nameと同じ設計思想＝行配列には混ぜない）。
    """
    files = sorted(glob.glob(os.path.join(csv_dir, "list_クローザー：*.csv")))
    person_count = defaultdict(int)
    display = {}
    for fn in files:
        with open(fn, encoding="cp932", errors="replace") as f:
            r = csv.reader(f)
            idx = {h: i for i, h in enumerate(next(r))}
            for row in r:
                raw_name = row[idx["ユーザー名"]].strip()
                ts = row[idx["報告日時"]].strip()
                if not raw_name or not ts:
                    continue
                date = ts.split(" ")[0].replace("-", "/")
                if not (start <= date <= end):
                    continue
                name = canon_name(raw_name)
                n = norm_name(name)
                display.setdefault(n, name)
                person_count[n] += 1
    return {display[n]: cnt for n, cnt in person_count.items()}


def _norm_date_slash(raw):
    """'2026/7/19' 'YYYY-MM-DD' 'YYYY/MM/DD'(ゼロパディング有無混在) を 'YYYY/MM/DD' に正規化する。"""
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("-", "/")
    parts = s.split("/")
    if len(parts) != 3:
        return None
    y, m, d = parts
    try:
        return f"{int(y):04d}/{int(m):02d}/{int(d):02d}"
    except ValueError:
        return None


def aggregate_completion(completion_dir, start, end):
    """完工数実データ（data/completion_2607/ のような、ポジション別に分かれた完工CSV群）を集計する。
    start/end: 'YYYY/MM/DD'（両端含む）。CSVはcp932、日付列は '完工日'（表記ゆれ: 2026/7/19 と 2026-07-09 が混在）。
    ポジション列: '入金済' はそのまま、'入金前'・'納品前' はどちらも未入金として合算する。
    """
    def in_range(d):
        return d and start <= d <= end

    count = uriage = 0
    paid_count = paid_uriage = 0
    unpaid_count = unpaid_uriage = 0
    by_company = defaultdict(lambda: {"count": 0, "uriage": 0, "paid_count": 0, "paid_uriage": 0,
                                       "unpaid_count": 0, "unpaid_uriage": 0})
    rows_out = []

    for path in sorted(glob.glob(os.path.join(completion_dir, "*.csv"))):
        with open(path, encoding="cp932", errors="replace") as f:
            r = csv.reader(f)
            header = next(r)
            idx = {h: i for i, h in enumerate(header)}
            for row in r:
                if not row or len(row) <= idx.get("完工日", -1):
                    continue
                d = _norm_date_slash(row[idx["完工日"]])
                if not in_range(d):
                    continue
                position = row[idx["ポジション"]].strip()
                price = parse_price(row[idx["販売価格（税込）"]])
                company = row[idx["クローザー会社名"]].strip() or "（不明）"
                is_paid = (position == "入金済")

                count += 1
                uriage += price
                by_company[company]["count"] += 1
                by_company[company]["uriage"] += price
                if is_paid:
                    paid_count += 1
                    paid_uriage += price
                    by_company[company]["paid_count"] += 1
                    by_company[company]["paid_uriage"] += price
                else:
                    unpaid_count += 1
                    unpaid_uriage += price
                    by_company[company]["unpaid_count"] += 1
                    by_company[company]["unpaid_uriage"] += price
                rows_out.append({
                    "position": position, "completion_date": d, "company": company,
                    "closer": row[idx["クローザー担当名"]].strip(), "price": price,
                })

    return {
        "start": start, "end": end,
        "count": count, "uriage": uriage,
        "paid_count": paid_count, "paid_uriage": paid_uriage,
        "unpaid_count": unpaid_count, "unpaid_uriage": unpaid_uriage,
        "by_company": dict(by_company),
        "rows": rows_out,
    }


def aggregate_dow_hour(roster_csv, start, end):
    """曜日×時間帯 ヒートマップ用: アポインター獲得履歴の獲得日+時刻から、曜日×時間帯のアポ獲得件数を集計する。
    start/end: 'YYYY/MM/DD'（両端含む・獲得日ベース）。ロースターCSVに時刻列（'獲得時刻' or '獲得日時' 等）が
    無い場合は集計不能（呼び出し側で空表示にする）。列名はCSVヘッダーを実際に見て解決する。
    """
    def in_range(d):
        return d and start <= d <= end

    with open(roster_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        header = next(r)
        idx = {h: i for i, h in enumerate(header)}
        rows = list(r)

    time_col = None
    for cand in ("獲得時刻", "獲得日時", "タイムスタンプ", "登録日時"):
        if cand in idx:
            time_col = cand
            break

    dow_labels = ["月", "火", "水", "木", "金", "土", "日"]
    hour_buckets = [(10, 12), (12, 14), (14, 16), (16, 18), (18, 20), (20, 22)]

    def bucket_label(h):
        for lo, hi in hour_buckets:
            if lo <= h < hi:
                return f"{lo}-{hi}時"
        return None

    grid = {dow: {f"{lo}-{hi}時": 0 for lo, hi in hour_buckets} for dow in dow_labels}
    total = 0
    matched_time = 0

    if time_col is None:
        return {"available": False, "reason": f"時刻列が見つかりません（列: {list(idx.keys())}）",
                "dow_labels": dow_labels, "hour_labels": [f"{lo}-{hi}時" for lo, hi in hour_buckets],
                "grid": grid, "total": 0}

    for row in rows:
        d = row[idx["獲得日"]].strip()
        if not in_range(d):
            continue
        total += 1
        raw_time = row[idx[time_col]].strip()
        if not raw_time:
            continue
        try:
            dt = datetime.strptime(d.replace("-", "/"), "%Y/%m/%d")
            time_part = raw_time.split(" ")[-1]
            hh = int(time_part.split(":")[0])
        except (ValueError, IndexError):
            continue
        dow = dow_labels[dt.weekday()]
        hb = bucket_label(hh)
        if hb:
            grid[dow][hb] += 1
            matched_time += 1

    return {"available": matched_time > 0, "dow_labels": dow_labels,
            "hour_labels": [f"{lo}-{hi}時" for lo, hi in hour_buckets],
            "grid": grid, "total": total, "matched_time": matched_time}


def prev_range(start, end):
    """start/end: 'YYYY/MM/DD'。同日数の直前期間（前期間比較用）を返す。
    例: start/end が7/1〜7/26（26日間）なら、6/5〜6/30（26日間）を返す。"""
    s = datetime.strptime(start, "%Y/%m/%d")
    e = datetime.strptime(end, "%Y/%m/%d")
    days = (e - s).days + 1
    prev_e = s - timedelta(days=1)
    prev_s = prev_e - timedelta(days=days - 1)
    return prev_s.strftime("%Y/%m/%d"), prev_e.strftime("%Y/%m/%d")


def merge_diff(companies, prev_companies):
    """companies（当期のcompany_rows）に、prev_companies（前期間の同形式リスト）との差分を書き込む。
    順位はアポ獲得数の多い順（company_rowsの既定ソート順）を基準にする。
    前期間に存在しなかった会社は prev_* が None・rank_change も None（新規扱い）になる。"""
    prev_by_co = {r["company"]: r for r in prev_companies}
    prev_sorted = sorted(prev_companies, key=lambda r: -r["apo_kakutoku"])
    prev_rank = {r["company"]: i + 1 for i, r in enumerate(prev_sorted)}

    for i, c in enumerate(companies):
        co = c["company"]
        c["rank"] = i + 1
        prev = prev_by_co.get(co)
        if prev is None:
            c["prev_apo_kakutoku"] = c["prev_clo_seiyaku"] = c["prev_uriage"] = c["prev_rate"] = None
            c["delta_apo_kakutoku"] = c["delta_apo_pct"] = None
            c["delta_clo_seiyaku"] = c["delta_clo_pct"] = None
            c["delta_uriage"] = c["delta_uriage_pct"] = None
            c["delta_rate"] = None
            c["rank_prev"] = None
            c["rank_change"] = None
            continue
        c["prev_apo_kakutoku"] = prev["apo_kakutoku"]
        c["prev_clo_seiyaku"] = prev["clo_seiyaku"]
        c["prev_uriage"] = prev["uriage"]
        c["prev_rate"] = prev["rate"]
        c["delta_apo_kakutoku"] = c["apo_kakutoku"] - prev["apo_kakutoku"]
        c["delta_apo_pct"] = round(c["delta_apo_kakutoku"] / prev["apo_kakutoku"] * 100, 1) if prev["apo_kakutoku"] else None
        c["delta_clo_seiyaku"] = c["clo_seiyaku"] - prev["clo_seiyaku"]
        c["delta_clo_pct"] = round(c["delta_clo_seiyaku"] / prev["clo_seiyaku"] * 100, 1) if prev["clo_seiyaku"] else None
        c["delta_uriage"] = c["uriage"] - prev["uriage"]
        c["delta_uriage_pct"] = round(c["delta_uriage"] / prev["uriage"] * 100, 1) if prev["uriage"] else None
        c["delta_rate"] = round(c["rate"] - prev["rate"], 1) if (c["rate"] is not None and prev["rate"] is not None) else None
        pr = prev_rank.get(co)
        c["rank_prev"] = pr
        c["rank_change"] = (pr - c["rank"]) if pr is not None else None
    return companies


def suggest_reinforcement(row):
    """役員会資料(2026/07/22)準拠: 測れる指標（アポ数・成約率）だけで「強化対象」候補の理由を返す。
    複数該当しうるため理由のリストを返す（空リスト＝候補なし）。運用列（状態タグ）を自動で上書きするものではなく、
    Google Sheet側で人が判断する際の参考候補として提示するだけに留める。"""
    reasons = []
    ak = row.get("apo_kakutoku", 0)
    rate = row.get("rate")
    prev_ak = row.get("prev_apo_kakutoku")
    prev_rate = row.get("prev_rate")

    if prev_ak:
        apo_change_pct = (ak - prev_ak) / prev_ak * 100
        if apo_change_pct <= config.APO_DROP_PCT:
            reasons.append(f"量が落ちている（アポ数 前期比{apo_change_pct:.0f}%）")

    if prev_rate is not None and rate is not None:
        rate_change_pt = rate - prev_rate
        if rate_change_pt <= config.RATE_DROP_PT:
            reasons.append(f"質が落ちている（成約率 前期比{rate_change_pt:+.1f}pt）")

    if ak >= config.QUALITY_CHECK_MIN_APO and rate is not None and rate < config.RATE_BASELINE_PCT:
        reasons.append(f"量はあるが質が低い（成約率{rate:.1f}% < 基準{config.RATE_BASELINE_PCT}%）")

    if ak <= config.STRUCTURAL_GAP_MAX_APO:
        reasons.append("構造的な穴（期間中の成果がほぼゼロ）")

    return reasons


def annotate_rankings(ranking_rows, prev_ranking_rows):
    """個人別ランキング行（with_rank後: [rank, name, company, 成約数, 量]）に、取材候補・強化対象候補それぞれの
    理由リストを付加した新しいリストを返す（各行の末尾に [取材候補理由リスト, 強化対象候補理由リスト] を追加。
    空リスト＝候補なし）。

    取材候補: 「パートナーへの取材について」Notion準拠。①成約数ランキング上位 ②成約数の前期間比成長率が高い、
    の2点を測れる範囲で判定する。「稼働開始3ヶ月以内で顕著な実績の新人」基準は、入社日データが現状どの
    データソースにも無いため判定できない（既知の制約。将来Cyzenユーザーマスタ等に入社日が載れば拡張可能）。

    強化対象候補（個人）: 会社単位の強化対象候補（suggest_reinforcement）と同じ考え方を個人に適用したもの。
    ①前期間比で成約数が大きく減少 ②直近の成果がゼロ（前期は実績があった）、を検知する。"""
    prev_by_name = {r[1]: r[3] for r in prev_ranking_rows}
    out = []
    for r in ranking_rows:
        rank, name, seiyaku = r[0], r[1], r[3]
        prev_seiyaku = prev_by_name.get(name)

        interview_reasons = []
        if rank <= config.INTERVIEW_TOP_RANK:
            interview_reasons.append(f"獲得数上位（{rank}位）")
        if prev_seiyaku:
            growth_pct = (seiyaku - prev_seiyaku) / prev_seiyaku * 100
            if growth_pct >= config.INTERVIEW_GROWTH_PCT:
                interview_reasons.append(f"成長率が高い（前期比+{growth_pct:.0f}%）")

        reinforcement_reasons = []
        if prev_seiyaku and seiyaku == 0:
            reinforcement_reasons.append("直近の成果がゼロ（稼働状況の確認推奨）")
        elif prev_seiyaku:
            change_pct = (seiyaku - prev_seiyaku) / prev_seiyaku * 100
            if change_pct <= config.PERSON_REINFORCEMENT_DROP_PCT:
                reinforcement_reasons.append(f"成約数が落ちている（前期比{change_pct:.0f}%）")

        out.append(list(r) + [interview_reasons, reinforcement_reasons])
    return out


def flag_attendance_mismatch(ranking_rows, attended_names, count_idx):
    """成果（アポ/成約）はあるのに、Cyzenの出勤打刻記録が無い人をフラグする（2026-07-28調査で判明した実データの乖離）。
    ranking_rows: annotate_rankings()後の行（[rank,name,co,成約数,量,取材候補理由,強化対象理由]）。
    attended_names: その期間にCyzen出勤打刻をした生の氏名の集合（resolved/unresolved問わず全員）。
    count_idx: 「実績あり」とみなす列のインデックス（アポインター/創蓄アポインターは4=アポ数、クローザーは3=成約数。
    クローザーには「アポ数」列が無いため）。
    各行の末尾にbool（True=打刻なしで実績あり）を1つ追加した新しいリストを返す。"""
    attended_norm = {norm_name(n) for n in attended_names}
    out = []
    for r in ranking_rows:
        name, count = r[1], r[count_idx]
        flagged = count > 0 and norm_name(name) not in attended_norm
        out.append(list(r) + [flagged])
    return out


def load_company_notes(status_csv):
    """運用列（状態タグ／主因／次アクション）を手動編集するGoogle SheetのCSVエクスポートを読み込む。
    列: 会社名, 状態タグ, 主因, 次アクション。会社名はcanon()で表記ゆれを吸収する。
    見つからない会社は空文字のまま（＝候補提示のみで運用開始できる）。"""
    notes = {}
    with open(status_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        header = next(r)
        idx = {h: i for i, h in enumerate(header)}
        for row in r:
            if not row or not row[0].strip():
                continue
            co = canon(row[idx["会社名"]].strip())
            notes[co] = {
                "status_tag": row[idx["状態タグ"]].strip() if "状態タグ" in idx and len(row) > idx["状態タグ"] else "",
                "cause": row[idx["主因"]].strip() if "主因" in idx and len(row) > idx["主因"] else "",
                "next_action": row[idx["次アクション"]].strip() if "次アクション" in idx and len(row) > idx["次アクション"] else "",
            }
    return notes


def load_attendance_alert_master(csv_path):
    """出退勤放置アラートのマスターCSV（data/cyzen_dashboard_master.csv）を読み込む。
    列: ユーザーコード,ユーザー名,グループ名,アラート判定,アイコン,出退勤区分,状況解説,
        最新出勤日時,最新退勤日時,スポット作成数,総打刻数,...(以下ステータス別打刻数は未使用)

    「出勤打刻なし」を単一の注意表示にしていた旧版に代え、①稼働の実態は7月のスポット作成数で見る
    ②出退勤の打刻放置（出勤したまま退勤せず、ルート自動記録だけが延々発生している状態）は別軸の
    アラートとして扱う、という2026-07-28の要件に基づく。このCSV自体が既に「7月時点の最新スナップ
    ショット」であり期間フィルタの概念を持たないため、日次/週次/月次のどの表示期間を選んでも同じ値を
    返す（会社別集計はここでは行わない・呼び出し側で resolve_company() 等と組み合わせる想定）。

    戻り値:
      total: 全行数
      spot_active_count: スポット作成数>0のユニークユーザー数
      spot_active_rate: 稼働率(%, 小数1桁)
      by_alert: {'要対応':N,'未打刻':N,'正常':N} のような内訳カウント
      records: 行ごとのdictのリスト
      lookup: {norm_name(氏名): record} 氏名で引けるlookup dict（company_resolverのnorm_nameでキー化）
    """
    with open(csv_path, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        header = next(r)
        idx = {h: i for i, h in enumerate(header)}
        rows = list(r)

    def get(row, col, default=""):
        i = idx.get(col)
        if i is None or i >= len(row):
            return default
        return row[i].strip()

    records = []
    lookup = {}
    by_alert = defaultdict(int)
    spot_active_names = set()

    route_active_names = set()

    def to_int(raw):
        try:
            return int(re.sub(r"[^\d\-]", "", raw) or "0")
        except ValueError:
            return 0

    for row in rows:
        if not row or not get(row, "ユーザー名"):
            continue
        name = get(row, "ユーザー名")
        spot_count = to_int(get(row, "スポット作成数", "0"))
        route_count = to_int(get(row, "ルート自動記録", "0"))
        alert = get(row, "アラート判定")
        rec = {
            "user_code": get(row, "ユーザーコード"),
            "name": name,
            "group": get(row, "グループ名"),
            "alert": alert,
            "icon": get(row, "アイコン"),
            "attendance_status": get(row, "出退勤区分"),
            "note": get(row, "状況解説"),
            "last_in": get(row, "最新出勤日時"),
            "last_out": get(row, "最新退勤日時"),
            "spot_count": spot_count,
            "route_count": route_count,
            "report_kind": get(row, "報告種別（最新）"),
            "last_report": get(row, "最新報告日時"),
            "report_mismatch": get(row, "報告日に出退勤記録なし") == "TRUE",
            "chronic_days": to_int(get(row, "長期放置日数", "0")),
            "chronic_stuck": get(row, "勤怠つけっぱなし疑い") == "TRUE",
        }
        records.append(rec)
        lookup[norm_name(canon_name(name))] = rec
        by_alert[alert] += 1
        if spot_count > 0:
            spot_active_names.add(norm_name(canon_name(name)))
        if route_count > 0:
            route_active_names.add(norm_name(canon_name(name)))

    total = len(records)
    spot_active_count = len(spot_active_names)
    route_active_count = len(route_active_names)
    return {
        "total": total,
        "spot_active_count": spot_active_count,
        "spot_active_rate": round(spot_active_count / total * 100, 1) if total else None,
        "route_active_count": route_active_count,
        "route_active_rate": round(route_active_count / total * 100, 1) if total else None,
        "by_alert": dict(by_alert),
        "records": records,
        "lookup": lookup,
    }


def company_attendance_alert_counts(alert_master):
    """出退勤放置アラートマスター(load_attendance_alert_master()の戻り値)のrecordsを、氏名から
    resolve_company()で会社に紐付けて、会社ごとの「要対応」「未打刻」「正常」人数を積み上げる。
    cyzen_dashboard_master.csv自体に会社名列が無いため、氏名解決を介して間接的に紐付ける。
    会社が解決できない氏名は「（不明）」に集約する（黙って捨てない）。
    戻り値: {会社名: {"要対応": N, "未打刻": N, "正常": N, "total": N}}"""
    out = defaultdict(lambda: defaultdict(int))
    if not alert_master:
        return {}
    for rec in alert_master["records"]:
        co = resolve_company(rec["name"]) or "（不明）"
        alert = rec["alert"] or "（不明）"
        out[co][alert] += 1
        out[co]["total"] += 1
    return {co: dict(v) for co, v in out.items()}


def augment_with_alert_master(ranking_rows, alert_master):
    """個人別ランキング行（flag_attendance_mismatch後: 末尾にlegacy bool flag）に、
    load_attendance_alert_master() のlookupで氏名一致する場合は実データ（スポット作成数・
    最新出退勤・出退勤区分）を末尾に追加する。一致しない場合（例: cyzen_dashboard_master.csv
    に載っていない外部パートナー企業の担当者等）は None を並べ、呼び出し側（JS）が
    legacy bool flag にフォールバックできるようにする。"""
    lookup = alert_master["lookup"] if alert_master else {}
    out = []
    for r in ranking_rows:
        name = r[1]
        rec = lookup.get(norm_name(canon_name(name)))
        if rec:
            out.append(list(r) + [rec["spot_count"], rec["last_in"], rec["last_out"],
                                   {"attendance_status": rec["attendance_status"], "note": rec["note"],
                                    "alert": rec["alert"]}])
        else:
            out.append(list(r) + [None, None, None, None])
    return out


SPOT_AREA_COLS = ['東北エリア', '関東エリア', '東海エリア', '関西エリア', '中国エリア', '四国エリア', '九州エリア',
                   'cyzenユーザー説明会', '予定管理用', 'Fit Founder', '用地開発']
SPOT_TAIMEN_TAGS = ["対面お断り", "宅入", "AP見込み", "AP獲得"]


def _norm_spot_status(raw):
    """スポットのステータス（AREA_COLS中の最初の非空列）の括弧注記を除去する。
    メインプロジェクト build_data.py の norm_status() と同じロジック。"""
    s = (raw or "").strip()
    if not s:
        return ""
    return re.split(r"[（(※]", s)[0].strip()


def aggregate_visits(spot_csv, start=None, end=None):
    """スポット台帳CSV（cp932）から、訪問種別（新規訪問/再訪問）・対面数・対面率を集計する。
    start/end: '作成日'ベースの期間フィルタ（'YYYY-MM-DD' 文字列・両端含む）。Noneなら全期間。

    判定ロジック（2026-07-28 要件で検証済み。数値を変えるとダッシュボードの正解値と食い違うので注意）:
      - 作成日/更新日どちらかが空の行はスキップ。
      - 新規訪問: 作成日の日付部分 == 更新日の日付部分 かつ ステータス(正規化後) != '訪問予定'
      - 再訪問  : 作成日の日付部分 <  更新日の日付部分
      - 上記どちらにも該当しない行（作成日==更新日 かつ ステータス=='訪問予定'）は新規/再訪問どちらにも数えない。
      - 対面    : ステータス(正規化後)が SPOT_TAIMEN_TAGS のいずれかを部分一致で含む場合。
      - 対面率の分母は常に「そのスコープの全スポット数」（新規+再訪問の合計ではない）。
    担当者名（作成者）は canon_name() で表記ゆれを統一したのち resolve_company() で会社を解決する
    （ranking_core内の他の集計関数と同じ名寄せロジック）。
    """
    def in_range(d):
        if start is None and end is None:
            return True
        return d and (start is None or d >= start) and (end is None or d <= end)

    with open(spot_csv, encoding="cp932", errors="replace") as f:
        r = csv.reader(f)
        header = next(r)
        idx = {h: i for i, h in enumerate(header)}
        rows = list(r)

    def get(row, col):
        i = idx.get(col)
        if i is None or i >= len(row):
            return ""
        return row[i].strip()

    total_spots = 0
    new_visit_count = 0
    revisit_count = 0
    taimen_count = 0
    taimen_new_count = 0
    taimen_revisit_count = 0

    person_display = {}
    person_company = {}
    person_stats = defaultdict(lambda: {"new_visit_count": 0, "revisit_count": 0,
                                         "taimen_count": 0, "taimen_new_count": 0, "taimen_revisit_count": 0})
    company_stats = defaultdict(lambda: {"new_visit_count": 0, "revisit_count": 0,
                                          "taimen_count": 0, "taimen_new_count": 0, "taimen_revisit_count": 0,
                                          "total_spots": 0})
    status_counts = defaultdict(int)

    for row in rows:
        created_raw = get(row, "作成日")
        updated_raw = get(row, "更新日")
        if not created_raw or not updated_raw:
            continue
        created_date = created_raw.split(" ")[0]
        updated_date = updated_raw.split(" ")[0]

        if not in_range(created_date):
            continue

        total_spots += 1

        raw_name = get(row, "作成者")
        name = canon_name(raw_name)
        n = norm_name(name) if name else ""
        if n:
            person_display.setdefault(n, name)
        co = resolve_company(name) if name else None
        if n:
            person_company.setdefault(n, co or "（不明）")
        company_stats[co or "（不明）"]["total_spots"] += 1

        status_raw = ""
        for col in SPOT_AREA_COLS:
            v = get(row, col)
            if v:
                status_raw = v
                break
        status = _norm_spot_status(status_raw)
        status_counts[status or "（未入力）"] += 1

        is_new = (created_date == updated_date and status != "訪問予定")
        is_revisit = created_date < updated_date
        is_taimen = any(tag in status for tag in SPOT_TAIMEN_TAGS)

        if is_taimen:
            taimen_count += 1
            if n:
                person_stats[n]["taimen_count"] += 1
            company_stats[co or "（不明）"]["taimen_count"] += 1

        if is_new:
            new_visit_count += 1
            if n:
                person_stats[n]["new_visit_count"] += 1
            company_stats[co or "（不明）"]["new_visit_count"] += 1
            if is_taimen:
                taimen_new_count += 1
                if n:
                    person_stats[n]["taimen_new_count"] += 1
                company_stats[co or "（不明）"]["taimen_new_count"] += 1
        elif is_revisit:
            revisit_count += 1
            if n:
                person_stats[n]["revisit_count"] += 1
            company_stats[co or "（不明）"]["revisit_count"] += 1
            if is_taimen:
                taimen_revisit_count += 1
                if n:
                    person_stats[n]["taimen_revisit_count"] += 1
                company_stats[co or "（不明）"]["taimen_revisit_count"] += 1

    def _rate(numer, denom):
        return round(numer / denom * 100, 1) if denom else None

    person = {}
    for n, s in person_stats.items():
        person[n] = {
            "name": person_display.get(n, n),
            "company": person_company.get(n, "（不明）"),
            "new_visit_count": s["new_visit_count"],
            "revisit_count": s["revisit_count"],
            "taimen_count": s["taimen_count"],
            "taimen_new_count": s["taimen_new_count"],
            "taimen_revisit_count": s["taimen_revisit_count"],
            "taimen_rate": None,  # 全スポット数を分母に、下のループで確定させる
            "taimen_rate_new": _rate(s["taimen_new_count"], s["new_visit_count"]),
            "taimen_rate_revisit": _rate(s["taimen_revisit_count"], s["revisit_count"]),
        }

    # 個人別の対面率は「担当者ごとの全スポット数（訪問種別を問わない）」を分母にする必要があるため、
    # 上のループとは別に全スポット数を数え直す（要件どおり全社対面率の分母定義と統一する）。
    person_total_spots = defaultdict(int)
    for row in rows:
        created_raw = get(row, "作成日")
        updated_raw = get(row, "更新日")
        if not created_raw or not updated_raw:
            continue
        created_date = created_raw.split(" ")[0]
        if not in_range(created_date):
            continue
        raw_name = get(row, "作成者")
        name = canon_name(raw_name)
        n = norm_name(name) if name else ""
        if n:
            person_total_spots[n] += 1
    for n, rec in person.items():
        rec["taimen_rate"] = _rate(rec["taimen_count"], person_total_spots.get(n, 0))

    company = {}
    for co, s in company_stats.items():
        company[co] = {
            "company": co,
            "total_spots": s["total_spots"],
            "new_visit_count": s["new_visit_count"],
            "revisit_count": s["revisit_count"],
            "taimen_count": s["taimen_count"],
            "taimen_new_count": s["taimen_new_count"],
            "taimen_revisit_count": s["taimen_revisit_count"],
            "taimen_rate": _rate(s["taimen_count"], s["total_spots"]),
        }

    return {
        "start": start, "end": end,
        "total_spots": total_spots,
        "new_visit_count": new_visit_count,
        "revisit_count": revisit_count,
        "taimen_count": taimen_count,
        "taimen_new_count": taimen_new_count,
        "taimen_revisit_count": taimen_revisit_count,
        "taimen_rate": _rate(taimen_count, total_spots),
        "person": person,
        "company": company,
        "by_status": dict(sorted(status_counts.items(), key=lambda kv: -kv[1])),
    }


def resolve_attendance_source(path):
    """Cyzen「報告書出力履歴」からダウンロードしたzip（例: 報告書一覧_YYYYMMDDHHMMSS.zip）を渡された場合は
    中のCSV（list_出勤報告.csv）を展開してそのパスを返す。すでにCSVパスならそのまま返す。"""
    if not path:
        return path
    if path.lower().endswith(".zip"):
        extract_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "_attendance_extract")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if not infos:
                raise SystemExit(f"ERROR: {path} 内にファイルがありません")
            info = infos[0]
            try:
                name = info.filename.encode("cp437").decode("cp932")
            except Exception:
                name = info.filename
            data = z.read(info.filename)
            out_path = os.path.join(extract_dir, name)
            with open(out_path, "wb") as f:
                f.write(data)
            return out_path
    return path
