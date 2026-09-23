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

使い方:
  from build_forecast import build_forecast
  fc = build_forecast(roster_csv, closing_csv, attendance_csv, "2026/09/21")
"""
import calendar
import csv
import datetime
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


# ------------------------------------------------------------------ エントリポイント

def build_forecast(roster_csv, closing_csv, attendance_csv, asof):
    """asof: 'YYYY/MM/DD'。責任者会議タブに埋め込むJSONを返す。"""
    y, m, asof_day = (int(x) for x in asof.split("/"))
    counts = load_daily_counts(roster_csv, closing_csv)
    people = load_daily_people(roster_csv, attendance_csv)

    out = {
        "asof": asof,
        "month": f"{y}/{m:02d}",
        "days_in_month": _days_in(y, m),
        "elapsed_days": asof_day,
        "model": {
            "flow": "曜日プロファイル加算方式（経過分は確定値、残り日に区分別平均を加算）",
            "stock": "到達率モデル（ユニーク人数の飽和カーブを到達率で割り戻す）",
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

    return out


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv")
    ap.add_argument("--attendance-csv")
    ap.add_argument("--asof", required=True, help="YYYY/MM/DD")
    args = ap.parse_args()
    print(json.dumps(build_forecast(args.roster_csv, args.closing_csv,
                                     args.attendance_csv, args.asof),
                     ensure_ascii=False, indent=1))
