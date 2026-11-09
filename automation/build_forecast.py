# -*- coding: utf-8 -*-
"""月末着地予測モデル（2026-09-21追加・責任者会議タブ③「月末着地予測」の算出元）。

【なぜ単純日割りをやめたか】
従来は `実績 ÷ 経過日数 × 月日数` の単純日割りだった。過去15ヶ月の実データで
バックテストしたところ平均絶対誤差(MAPE)は9〜15%、最大33%外していた。
誤差の主因は「月内の曜日構成」であり、この事業は曜日による稼働量の差が極端に大きい
（土日=1日70件前後 / 平日=11〜38件 / 火曜=ほぼ0件）。

【採用モデル: 曜日プロファイル加算方式】
  予測 = 経過日の実績（確定値としてそのまま使う）
       + 残り日の Σ（その日の区分の過去平均 × スケール係数）

「当月ペースで残り日全体をスケーリングする」方式も試したがMAPE 10.9%と悪化した
（月初の偶然のブレが月末まで増幅されるため）。経過分を確定値として動かさず、
残り日だけ過去平均を足す加算方式がMAPE 4.5%で最も安定した。
スケール係数は当月水準への追従だが、λ(FLOW_LAMBDA)で減衰させる（λ=0で純加算）。

【日区分（DAY_TYPE）の設計・実データで検証済み】
  火    … 火曜は祝日であっても稼働しない（2026年の運用実態。2026/05/05=0件・
          2026/08/11=3件で確認）。祝日を一律「土日扱い」にすると9/22のような
          「火曜かつ祝日」で大幅に過大予測するため独立区分にしている。
  休    … 土日
  祝    … 平日にあたる祝日。実績は「土日の約65%」の水準（過去19祝日で検証）。
          平日平均よりはるかに高く土日よりは低いため、独立区分にしている。
  年末年始 … 元日等は実績ゼロ（2026/01/01=0件）。
  月〜金 … 通常平日は曜日ごとに別平均。

【ストック型指標は別モデル】
アポ獲得達成者数・稼働人員数は「期間内に1回でも実績があった人数（重複排除）」であり、
月内で積み上がるフロー型ではなく飽和カーブ型（21日時点で既に月末値の88〜100%に到達）。
フロー型と同じ日割りを当てると必ず過小評価になるため、「その日の到達率の中央値で割り戻す」
到達率モデルを使う（バックテストMAPE 3.2%）。

【精度の注意・成約数/売上】
成約数・売上の元データ（獲得報告データ）は2026/07/01以降しか存在せず、完了month が
2ヶ月しかないためバックテスト検証ができない。アポと同じロジックを適用するが、
`verified=False` を立てて画面側で「参考値」と明示する。月を重ねれば自動的に検証可能になる。

【成約数の新方式（2026-11-09 切替・商談予定積み上げ）】
10月は過去平均系のどの手法も +12.5〜13.4% 高く外れた（主因は商談の成約割合の低下で、過去平均や
アポ数には表れない）。そこで成約数だけ、直近7日を実際の商談予定で見積もる方式に変更した。
  見込み = 実績 + 今後7日の予定数 × 成約割合 + 8日目以降の曜日別平均 × 当月の調子
  幅     = 成約割合の最小〜最大 と、直近3か月の水準の最小〜最大 で算出
成約割合は「ある日の7日先の予定数」に対する「その7日間の実際の成約数」。forecast_ledger/ に毎日
記録した実測で更新する（実測が5日分たまるまでは10月前半の5時点を初期値として使う）。
報告遅れ・提案中の案件は成約割合の中に含まれるため別建てで足さない（二重計上を避ける）。
予定データが古い・足りない場合は旧方式に自動で戻す。旧方式の値は legacy_forecast に残す。
検証は10月の4時点のみで、しかも当時まだ結果の出ていない期間の割合を使ったため、精度は未証明（参考値）。

使い方:
  from build_forecast import build_forecast
  fc = build_forecast(roster_csv, closing_csv, attendance_csv, "2026/09/21", shodan_json="...")
"""
import calendar
import csv
import datetime
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranking_core import parse_price  # noqa: E402  金額表記ゆれ（"¥2,640,000税込"等）を本体と同じ規則で解釈する

JP_DOW = ["月", "火", "水", "木", "金", "土", "日"]

# 日本の祝日（このダッシュボードが扱う範囲のみ手動管理。祝日ライブラリは依存を増やさない方針のため入れない）
HOLIDAYS = {
    "2025/07/21", "2025/08/11", "2025/09/15", "2025/09/23", "2025/10/13",
    "2025/11/03", "2025/11/23", "2025/11/24",
    "2026/01/01", "2026/01/12", "2026/02/11", "2026/02/23", "2026/03/20",
    "2026/04/29", "2026/05/03", "2026/05/04", "2026/05/05", "2026/05/06",
    "2026/07/20", "2026/08/11", "2026/09/21", "2026/09/22", "2026/09/23",
    "2026/10/12", "2026/11/03", "2026/11/23",
    "2027/01/01", "2027/01/11", "2027/02/11", "2027/02/23", "2027/03/21",
}
YEAR_END_NEW_YEAR = {"2025/12/31", "2026/01/01", "2026/01/02", "2026/01/03",
                     "2026/12/31", "2027/01/01", "2027/01/02", "2027/01/03"}

# バックテストで決めたハイパーパラメータ（build_forecast.py 内で完結させ、外から変えない）
TRAIN_WINDOW_MONTHS = 6   # 曜日プロファイルの学習窓
FLOW_LAMBDA = 0.15        # 当月水準への追従度（0=純加算 / 1=完全スケール）。0.15でMAPE最小
STOCK_WINDOW_MONTHS = 6   # 到達率モデルの学習窓

# ---- 成約数の新方式（商談予定積み上げ）
SCHEDULE_WINDOW_DAYS = 7     # 商談予定で見積もる日数
MIN_REAL_RATE_ROWS = 5       # 実測の成約割合がこの件数たまったら初期値を使わない
MAX_RATE_ROWS = 8            # 成約割合の算出に使う直近の件数
MIN_BOOKED_FOR_RATE = 30     # 予定がこれ未満の日は成約割合の計算に使わない
MIN_BOOKED_PER_DAY = 4       # 予定が1日あたりこれ未満なら予定データ不足として旧方式に戻す
BAND_MONTHS = 3              # 幅の算出に使う直近の完了月数
# 初期値: 10月前半に実際に保存されていた商談予定の7日先の件数（当時は取得漏れあり）
SEED_BOOKED = [("2026/10/05", 174), ("2026/10/08", 163), ("2026/10/09", 151),
               ("2026/10/10", 160), ("2026/10/11", 204)]
SHODAN_STATUS_CODE = {"確定": "確", "後確後（事務確認OK）": "後", "仮予定": "仮"}

_HERE = os.path.dirname(os.path.abspath(__file__))
# 記録の正本は本番リポジトリ側。スキル側のコピーから動かす場合も本番側を読む（書き込みはしない）。
DEFAULT_LEDGER_DIR = (os.path.join(_HERE, "data", "forecast_ledger")
                      if os.path.basename(_HERE) == "automation" else
                      os.path.expanduser("~/Documents/partner-dashboard-deploy/automation/data/forecast_ledger"))


def _days_in(y, m):
    return calendar.monthrange(y, m)[1]


def _ds(y, m, d):
    return f"{y}/{m:02d}/{d:02d}"


def day_type(y, m, d):
    """その日の区分を返す。実データ検証に基づく分類（モジュールdocstring参照）。

    2026-09-21 小宮山さんの指示により「祝日は出勤扱い」に変更。祝日判定を火曜判定より
    優先させ、火曜にあたる祝日も稼働日（「祝」区分）として扱う。
    """
    s = _ds(y, m, d)
    w = JP_DOW[datetime.date(y, m, d).weekday()]
    if s in YEAR_END_NEW_YEAR:
        return "年末年始"
    if w in ("土", "日"):
        return "休"
    if s in HOLIDAYS:
        return "祝"          # 平日の祝日（火曜であっても出勤扱い）
    if w == "火":
        return "火"          # 祝日でない通常の火曜は稼働しない（2026年の運用実態）
    return w


def _prev_months(y, m, n):
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        out.append((y, m))
    return list(reversed(out))


# ------------------------------------------------------------------ データ読み込み

def load_daily_counts(roster_csv, closing_csv):
    """{'apo': {日付: 件数}, 'seiyaku': {...}, 'uriage': {...}} を返す。日付は 'YYYY/MM/DD'。"""
    apo = defaultdict(int)
    with open(roster_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            d = row[idx["獲得日"]].strip()
            if d:
                apo[d] += 1

    seiyaku = defaultdict(int)
    uriage = defaultdict(int)
    if closing_csv:
        with open(closing_csv, encoding="utf-8-sig", errors="replace") as f:
            r = csv.reader(f)
            idx = {h: i for i, h in enumerate(next(r))}
            for row in r:
                ts = (row[idx["タイムスタンプ"]] or "").strip()
                if not ts:
                    continue
                d = ts.split(" ")[0]
                seiyaku[d] += 1
                uriage[d] += parse_price(row[idx["販売価格"]])
    return {"apo": dict(apo), "seiyaku": dict(seiyaku), "uriage": dict(uriage)}


def load_daily_people(roster_csv, attendance_csv):
    """{'apo_achiever': {日付: set(氏名)}, 'workforce': {日付: set(氏名)}}

    workforce は Cyzen出勤報告（API取得の attendance_merged.csv）の実打刻ベース。
    """
    achiever = defaultdict(set)
    with open(roster_csv, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            d = row[idx["獲得日"]].strip()
            n = row[idx["アポインター"]].strip()
            if d and n:
                achiever[d].add(n)

    workforce = defaultdict(set)
    if attendance_csv:
        try:
            with open(attendance_csv, encoding="cp932", errors="replace") as f:
                for row in csv.DictReader(f):
                    n = (row.get("ユーザー名") or "").strip()
                    d = (row.get("日付") or "").strip().replace("-", "/")
                    if n and d:
                        workforce[d].add(n)
        except OSError:
            pass
    return {"apo_achiever": dict(achiever), "workforce": dict(workforce)}


# ------------------------------------------------------------------ フロー型モデル

def _profile(daily, months):
    """{日区分: 1日あたり平均} を学習窓の月から作る。

    データが1件も無い月は平均の分母から除外する。成約数・売上は元データが2026/07以降
    しか無いため、これをやらないと「データが存在しないだけの月」がゼロとして平均を
    引き下げ、着地予測が大幅な過小評価になる（2026-09-21に実際に発生した不具合）。
    """
    b = defaultdict(list)
    for (y, m) in months:
        n = _days_in(y, m)
        if sum(daily.get(_ds(y, m, d), 0) for d in range(1, n + 1)) == 0:
            continue
        for d in range(1, n + 1):
            b[day_type(y, m, d)].append(daily.get(_ds(y, m, d), 0))
    return {k: sum(v) / len(v) for k, v in b.items() if v}


def forecast_flow(daily, y, m, asof_day, lam=FLOW_LAMBDA, window=TRAIN_WINDOW_MONTHS):
    """フロー型（件数・金額）の月末着地予測。"""
    n = _days_in(y, m)
    prof = _profile(daily, _prev_months(y, m, window))
    actual = sum(daily.get(_ds(y, m, d), 0) for d in range(1, asof_day + 1))
    expected_sofar = sum(prof.get(day_type(y, m, d), 0) for d in range(1, asof_day + 1))
    raw_scale = actual / expected_sofar if expected_sofar > 0 else 1.0
    scale = 1.0 + lam * (raw_scale - 1.0)
    remain = sum(prof.get(day_type(y, m, d), 0) for d in range(asof_day + 1, n + 1))
    return {
        "actual": actual,
        "forecast": round(actual + remain * scale),
        "remaining_days": n - asof_day,
        "profile": {k: round(v, 1) for k, v in sorted(prof.items())},
    }


# ------------------------------------------------------------------ ストック型モデル

def forecast_stock(daily_sets, y, m, asof_day, window=STOCK_WINDOW_MONTHS):
    """ストック型（ユニーク人数）の月末着地予測＝到達率で割り戻す。"""
    ratios = []
    for (py, pm) in _prev_months(y, m, window):
        pn = _days_in(py, pm)
        # 月の途中からしかデータが無い月（取得開始月など）は到達率が歪むので除外する。
        # 月の前半・後半それぞれに実績があることを最低条件にする。
        first_half = any(daily_sets.get(_ds(py, pm, d)) for d in range(1, min(asof_day, pn) + 1))
        second_half = any(daily_sets.get(_ds(py, pm, d)) for d in range(min(asof_day, pn) + 1, pn + 1))
        if not (first_half and second_half):
            continue
        seen, at_asof = set(), None
        for d in range(1, pn + 1):
            seen |= daily_sets.get(_ds(py, pm, d), set())
            if d == min(asof_day, pn):
                at_asof = len(seen)
        if seen and at_asof:
            ratios.append(at_asof / len(seen))
    ratio = statistics.median(ratios) if ratios else 1.0

    seen = set()
    for d in range(1, asof_day + 1):
        seen |= daily_sets.get(_ds(y, m, d), set())
    actual = len(seen)
    return {
        "actual": actual,
        "forecast": round(actual / ratio) if ratio > 0 else actual,
        "completion_ratio": round(ratio, 3),
        "n_train_months": len(ratios),
    }


# ------------------------------------------------------------------ バックテスト

# この月数ぶんの「完了月」が揃って初めて精度を名乗る。これ未満なら verified=False にして
# 画面側で「参考値」と明示する（成約数・売上は2026/07以降しかデータが無く当面ここに該当する）。
MIN_MONTHS_TO_VERIFY = 4


def backtest_flow(daily, months, asof_days=(10, 14, 16, 20, 21, 25),
                  lam=FLOW_LAMBDA, window=TRAIN_WINDOW_MONTHS):
    """完了月だけを対象にMAPEを出す。

    評価対象は「学習窓(window)ヶ月分の過去実績が実際に存在する月」に限る。
    これをやらないと、データ開始直後の月を『中身の薄いプロファイル』で予測した分まで
    誤差に混ざり、実運用時より悪い数字が出てしまう（逆に月数が足りないのに
    もっともらしいMAPEを出してしまう危険もある）。
    """
    have = set(months)
    errs, evaluated = [], []
    for (y, m) in months:
        # 学習窓ぶんの過去月が全部データとして存在する月だけ評価する
        if not all(pm in have for pm in _prev_months(y, m, window)):
            continue
        n = _days_in(y, m)
        actual_full = sum(daily.get(_ds(y, m, d), 0) for d in range(1, n + 1))
        if not actual_full:
            continue
        evaluated.append((y, m))
        for a in asof_days:
            if a >= n:
                continue
            p = forecast_flow(daily, y, m, a, lam, window)["forecast"]
            errs.append(abs(p - actual_full) / actual_full * 100)
    if len(evaluated) < MIN_MONTHS_TO_VERIFY or not errs:
        return None
    return {"mape": round(statistics.mean(errs), 1), "max_error": round(max(errs), 1),
            "n_samples": len(errs), "n_months": len(evaluated)}


def _completed_months(daily, y, m, lookback=12):
    """データがあり、かつ当月より前の（＝完了済みの）月を返す。"""
    out = []
    for (py, pm) in _prev_months(y, m, lookback):
        n = _days_in(py, pm)
        if sum(daily.get(_ds(py, pm, d), 0) for d in range(1, n + 1)) > 0:
            out.append((py, pm))
    return out


# ------------------------------------------------------------------ 成約数の新方式（商談予定積み上げ）

def _d(s):
    return datetime.datetime.strptime(s, "%Y/%m/%d").date()


def _s(d):
    return d.strftime("%Y/%m/%d")


def load_schedule_deals(shodan_json):
    """商談予定を [(日付, 状態コード, 予定ID)] で返す。氏名・件名（お客様名を含む）は読まない。"""
    if not shodan_json or not os.path.exists(shodan_json):
        return None
    with open(shodan_json, encoding="utf-8") as f:
        raw = json.load(f)
    deals = []
    for x in raw.get("deals") or []:
        code = SHODAN_STATUS_CODE.get(x.get("c"))
        if not code or not x.get("s"):
            continue
        jst = datetime.datetime.utcfromtimestamp(x["s"]) + datetime.timedelta(hours=9)
        deals.append((jst.date(), code, (x.get("sid") or "")[:10]))
    return {"generated": (raw.get("generated") or "")[:10], "deals": deals}


def read_ledger(ledger_dir):
    rows = []
    if ledger_dir and os.path.isdir(ledger_dir):
        for name in sorted(os.listdir(ledger_dir)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(ledger_dir, name), encoding="utf-8") as f:
                    rows.append(json.load(f))
            except (OSError, ValueError):
                continue
    return rows


def schedule_rate_rows(daily, ledger_rows, asof_date):
    """7日間の結果が出そろった基準日について「成約 ÷ 7日先の予定数」を返す（古い順）。"""
    def measure(day_str, booked, seed):
        day = _d(day_str)
        if day + datetime.timedelta(days=SCHEDULE_WINDOW_DAYS) >= asof_date or booked < MIN_BOOKED_FOR_RATE:
            return None
        closed = sum(daily.get(_s(day + datetime.timedelta(days=i)), 0)
                     for i in range(1, SCHEDULE_WINDOW_DAYS + 1))
        return {"date": day_str, "booked": booked, "closed": closed, "rate": closed / booked, "seed": seed}

    real = [m for m in (measure(r["asof"], (r.get("forward") or {}).get("booked", 0), False)
                        for r in ledger_rows if r.get("asof")) if m]
    real.sort(key=lambda r: r["date"])
    if len(real) >= MIN_REAL_RATE_ROWS:
        return real[-MAX_RATE_ROWS:]
    seeds = [m for m in (measure(d, b, True) for d, b in SEED_BOOKED) if m]
    return (seeds + real)[-MAX_RATE_ROWS:]


def _month_level_totals(daily, y, m, days):
    """直近の完了月それぞれの曜日別水準で、指定の日々を埋めた合計を返す。"""
    totals = []
    for (py, pm) in reversed(_prev_months(y, m, BAND_MONTHS)):
        n = _days_in(py, pm)
        if not sum(daily.get(_ds(py, pm, d), 0) for d in range(1, n + 1)):
            continue
        b = defaultdict(list)
        for d in range(1, n + 1):
            b[day_type(py, pm, d)].append(daily.get(_ds(py, pm, d), 0))
        level = {k: sum(v) / len(v) for k, v in b.items()}
        totals.append(sum(level.get(day_type(x.year, x.month, x.day), 0) for x in days))
    return totals


def forecast_with_schedule(daily, schedule, ledger_rows, y, m, asof_day):
    """予定積み上げの月末見込み。使える状態でなければ None と理由を返す（呼び出し側で旧方式へ）。"""
    if not schedule:
        return None, "商談予定データなし"
    asof = datetime.date(y, m, asof_day)
    generated = schedule.get("generated")
    if generated and asof - datetime.date.fromisoformat(generated) > datetime.timedelta(days=1):
        return None, f"商談予定データが古い（{generated}時点）"
    n = _days_in(y, m)
    last = min(asof_day + SCHEDULE_WINDOW_DAYS, n)
    window = [datetime.date(y, m, d) for d in range(asof_day + 1, last + 1)]
    rest = [datetime.date(y, m, d) for d in range(last + 1, n + 1)]
    in_window = [x for x in schedule["deals"] if window and window[0] <= x[0] <= window[-1]]
    booked = len(in_window)
    if len(window) >= 3 and booked < MIN_BOOKED_PER_DAY * len(window):
        return None, f"商談予定が少なすぎる（{len(window)}日で{booked}件）"
    rows = schedule_rate_rows(daily, ledger_rows, asof)
    if not rows:
        return None, "成約割合の実測がまだない"

    rates = [r["rate"] for r in rows]
    rate, rate_low, rate_high = statistics.median(rates), min(rates), max(rates)

    prof = _profile(daily, _prev_months(y, m, TRAIN_WINDOW_MONTHS))
    actual = sum(daily.get(_ds(y, m, d), 0) for d in range(1, asof_day + 1))
    expected_sofar = sum(prof.get(day_type(y, m, d), 0) for d in range(1, asof_day + 1))
    raw_scale = actual / expected_sofar if expected_sofar > 0 else 1.0
    scale = 1.0 + FLOW_LAMBDA * (raw_scale - 1.0)
    rest_center = sum(prof.get(day_type(x.year, x.month, x.day), 0) for x in rest) * scale
    levels = _month_level_totals(daily, y, m, rest) + [rest_center]
    rest_low, rest_high = min(levels), max(levels)

    forecast = actual + booked * rate + rest_center
    low = actual + booked * rate_low + rest_low
    high = actual + booked * rate_high + rest_high
    by_status = defaultdict(int)
    for x in in_window:
        by_status[x[1]] += 1
    return {
        "actual": actual,
        "forecast": round(forecast),
        "forecast_low": round(low),
        "forecast_high": round(high),
        "remaining_days": n - asof_day,
        "profile": {k: round(v, 1) for k, v in sorted(prof.items())},
        "layers": {
            "actual": actual,
            "schedule": {
                "days": len(window),
                "from": _s(window[0]) if window else None, "to": _s(window[-1]) if window else None,
                "booked": booked,
                "kakutei": by_status["確"], "kakugo": by_status["後"], "kari": by_status["仮"],
                "rate": round(rate, 4), "rate_low": round(rate_low, 4), "rate_high": round(rate_high, 4),
                "rate_basis": "初期値（10月前半）を含む" if any(r["seed"] for r in rows) else "実測のみ",
                "n_rate_rows": len(rows),
                "value": round(booked * rate, 1), "low": round(booked * rate_low, 1), "high": round(booked * rate_high, 1),
            },
            "rest": {"days": len(rest), "value": round(rest_center, 1),
                     "low": round(rest_low, 1), "high": round(rest_high, 1)},
        },
    }, None


def write_ledger_row(ledger_dir, asof_date, schedule, metric):
    """その日の予定の状態と新旧の見込みを1日1ファイルで保存する（同じ日は最終版で上書き）。

    あとで「当時仮予定だった案件がどうなったか」「新旧どちらが当たったか」を測るための記録。
    氏名・件名は保存しない。"""
    if not schedule:
        return
    os.makedirs(ledger_dir, exist_ok=True)
    win_end = asof_date + datetime.timedelta(days=SCHEDULE_WINDOW_DAYS)
    horizon = asof_date + datetime.timedelta(days=35)
    forward = [x for x in schedule["deals"] if asof_date < x[0] <= win_end]
    by_status = defaultdict(int)
    for x in forward:
        by_status[x[1]] += 1
    row = {
        "asof": _s(asof_date),
        "generated": schedule.get("generated"),
        "forward": {"days": SCHEDULE_WINDOW_DAYS, "booked": len(forward), "by_status": dict(by_status)},
        "deals": sorted([x[0].strftime("%m%d"), x[1], x[2]] for x in schedule["deals"]
                        if asof_date < x[0] <= horizon),
        "actual": metric.get("actual"),
        "forecast": metric.get("forecast"),
        "forecast_low": metric.get("forecast_low"),
        "forecast_high": metric.get("forecast_high"),
        "legacy_forecast": metric.get("legacy_forecast"),
        "method": metric.get("method"),
    }
    path = os.path.join(ledger_dir, asof_date.isoformat() + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(row, f, ensure_ascii=False, separators=(",", ":"))


def build_company_forecast(companies, prev_companies, forecast, y, m, asof_day):
    """会社別の月末見込み。全体と同じ見込みに合計が一致するように残り分を配分する。

    残りの基礎値 = (1 − 経過の重み) × (当月ペースと前月実績の加重平均)。月初は前月実績を重く、
    月が進むほど当月を重く見る（10月の検証で 10/7時点の誤差 40.9%→31.7%、中旬以降は同程度）。"""
    n = _days_in(y, m)
    metrics = forecast.get("metrics") or {}
    prev_by_co = {c["company"]: c for c in (prev_companies or [])}
    out = {c["company"]: {} for c in companies}
    for field, out_key, metric_key in (("apo_seiyaku", "apo_seiyaku", "seiyaku"),
                                       ("clo_seiyaku", "clo_seiyaku", "seiyaku"),
                                       ("apo_kakutoku", "apo_num", "apo")):
        met = metrics.get(metric_key) or {}
        prof = met.get("profile") or {}
        total = sum(prof.get(day_type(y, m, d), 0) for d in range(1, n + 1))
        done = sum(prof.get(day_type(y, m, d), 0) for d in range(1, asof_day + 1))
        if not met.get("available") or not total or not done:
            continue
        share = done / total
        weight = share / (share + 0.35)
        base = {}
        for c in companies:
            actual = c.get(field) or 0
            prev = (prev_by_co.get(c["company"]) or {}).get(field) or 0
            base[c["company"]] = (1 - share) * (weight * (actual / share) + (1 - weight) * prev)
        remain = max((met.get("forecast") or 0) - (met.get("actual") or 0), 0)
        sum_base = sum(base.values())
        factor = remain / sum_base if sum_base else 0
        for c in companies:
            actual = c.get(field) or 0
            out[c["company"]][out_key] = round(actual + base[c["company"]] * factor, 1)
    return out


# ------------------------------------------------------------------ エントリポイント

def build_forecast(roster_csv, closing_csv, attendance_csv, asof, shodan_json=None,
                   ledger_dir=DEFAULT_LEDGER_DIR, write_ledger=False):
    """asof: 'YYYY/MM/DD'。責任者会議タブに埋め込むJSONを返す。"""
    y, m, asof_day = (int(x) for x in asof.split("/"))
    counts = load_daily_counts(roster_csv, closing_csv)
    people = load_daily_people(roster_csv, attendance_csv)
    schedule = load_schedule_deals(shodan_json)
    ledger_rows = read_ledger(ledger_dir)

    out = {
        "asof": asof,
        "month": f"{y}/{m:02d}",
        "days_in_month": _days_in(y, m),
        "elapsed_days": asof_day,
        "model": {
            "flow": "曜日プロファイル加算方式（経過分は確定値、残り日に区分別平均を加算）",
            "stock": "到達率モデル（ユニーク人数の飽和カーブを到達率で割り戻す）",
            "seiyaku": "商談予定積み上げ（実績＋今後7日の予定×成約割合＋8日目以降の曜日別平均）",
            "train_window_months": TRAIN_WINDOW_MONTHS,
            "lambda": FLOW_LAMBDA,
        },
        "metrics": {},
    }

    # --- フロー型 ---
    for key, label, daily in [
        ("apo", "アポ数", counts["apo"]),
        ("seiyaku", "成約数", counts["seiyaku"]),
        ("uriage", "売上", counts["uriage"]),
    ]:
        if not daily:
            out["metrics"][key] = {"label": label, "available": False,
                                   "reason": "元データ未取得"}
            continue
        res = forecast_flow(daily, y, m, asof_day)
        completed = _completed_months(daily, y, m)
        bt = backtest_flow(daily, completed)
        res.update({
            "label": label, "available": True, "type": "flow",
            "verified": bt is not None,
            "backtest": bt,
            "n_history_months": len(completed),
        })
        if bt is None:
            res["note"] = (f"完了月が{len(completed)}ヶ月しかなく精度検証ができないため参考値です"
                           "（月を重ねると自動的に検証されます）")
        if key == "seiyaku":
            # 旧方式の値は比較用に残し、使える日は商談予定積み上げの値を表の数字にする
            res["legacy_forecast"] = res["forecast"]
            res["method"] = "legacy"
            pipe, reason = forecast_with_schedule(daily, schedule, ledger_rows, y, m, asof_day)
            if pipe:
                res.update(pipe)
                res["method"] = "schedule"
                res["verified"] = False
                res["backtest"] = None
                res["note"] = "2026年11月に切り替えた新方式の参考値です（検証は10月の4時点のみで、精度は未証明）"
            else:
                res["fallback_reason"] = reason
                print(f"[forecast] 成約の新方式を使えず旧方式で算出: {reason}", file=sys.stderr)
        out["metrics"][key] = res

    # --- 成約率（派生値） ---
    apo_f = out["metrics"].get("apo", {})
    sei_f = out["metrics"].get("seiyaku", {})
    if apo_f.get("available") and sei_f.get("available") and apo_f["forecast"]:
        out["metrics"]["seiyaku_rate"] = {
            "label": "全社成約率", "available": True, "type": "derived",
            "actual": round(sei_f["actual"] / apo_f["actual"] * 100, 1) if apo_f["actual"] else None,
            "forecast": round(sei_f["forecast"] / apo_f["forecast"] * 100, 1),
            "verified": False,
            "note": "成約数予測 ÷ アポ数予測の派生値のため、成約数と同じく参考値です",
        }

    # --- ストック型 ---
    for key, label, sets in [
        ("apo_achiever", "アポ獲得達成者数", people["apo_achiever"]),
        ("workforce", "稼働人員数", people["workforce"]),
    ]:
        if not sets:
            out["metrics"][key] = {"label": label, "available": False,
                                   "reason": "元データ未取得"}
            continue
        res = forecast_stock(sets, y, m, asof_day)
        res.update({"label": label, "available": True, "type": "stock"})
        # 学習に使えた月数が少ないものは参考値扱い（稼働人員数＝Cyzen出退勤は蓄積が浅い）
        res["verified"] = res["n_train_months"] >= 4
        if not res["verified"]:
            res["note"] = (f"学習に使えた過去月が{res['n_train_months']}ヶ月しかないため参考値です")
        out["metrics"][key] = res

    if write_ledger and out["metrics"].get("seiyaku", {}).get("available"):
        write_ledger_row(ledger_dir, datetime.date(y, m, asof_day), schedule, out["metrics"]["seiyaku"])

    return out


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv")
    ap.add_argument("--attendance-csv")
    ap.add_argument("--shodan-json")
    ap.add_argument("--asof", required=True, help="YYYY/MM/DD")
    args = ap.parse_args()
    print(json.dumps(build_forecast(args.roster_csv, args.closing_csv,
                                     args.attendance_csv, args.asof, shodan_json=args.shodan_json),
                     ensure_ascii=False, indent=1))
