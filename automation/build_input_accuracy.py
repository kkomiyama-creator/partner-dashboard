# -*- coding: utf-8 -*-
"""Cyzen入力精度スコア（企業別・週次）をダッシュボード埋込用JSONに変換する（2026-10-07追加）。

入力: weekly-partner-ranking スキルの data/sept_analysis/sept_analysis_result.json
出力: automation/data/input_accuracy.json（build_dashboard.pyが読み込み、企業別タブに表示）
企業別の集計に加え、企業ごとの担当者別スコア(members)も出力する（パスワード付きダッシュボードの企業名クリック用）。Slackキャンバス「Cyzen入力精度ランキング（企業別・週次）」と同じロジック。
毎週月曜に入力JSONを更新したら、このスクリプトを再実行してpushする（CIは再計算しない）。

使い方: python3 build_input_accuracy.py <sept_analysis_result.json> [更新日YYYY-MM-DD]
"""
import collections
import datetime
import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "input_accuracy.json")
COMPS = ["退勤打刻率", "出勤日整合率", "後確セット率", "ヒアリング充足率", "予定→結果報告率"]
TARGET = {"退勤打刻率": 0.95, "出勤日整合率": 0.98, "後確セット率": 0.97, "ヒアリング充足率": 0.70, "予定→結果報告率": None}
FF = "株式会社Fit Founder"


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def main(src, updated):
    res = json.load(open(src, encoding="utf-8"))
    rk = res["ranking"]
    main_rk = [x for x in rk if not x["参考扱い"] and x["score"] is not None]
    pt_rk = [x for x in main_rk if x["company"] != FF]
    wk = list(res["weekly_team"].keys())
    end = (datetime.date.fromisoformat(wk[-1]) + datetime.timedelta(days=6)).isoformat()

    def stats(xs):
        o = {"n": len(xs), "avg": mean([x["score"] for x in xs])}
        for k in COMPS:
            o[k] = mean([x.get(f"c_{k}") for x in xs])
        return o

    by = collections.defaultdict(list)
    for x in main_rk:
        by[x["company"]].append(x)
    allst = stats(main_rk)
    comp_week = {}
    for w in wk:
        tmp = collections.defaultdict(list)
        for k, v in res["weekly_user"].get(w, {}).items():
            co = k.split("|", 1)[1]
            if v.get("score") is not None and v.get("出勤日数", 0) > 0:
                tmp[co].append(v["score"])
        comp_week[w] = {co: mean(v) for co, v in tmp.items()}

    # 個人別（企業名クリックのドリルダウン用）。全体順位は出勤3日以上の担当者(順位対象)の中でのスコア順位。
    rank_scores = sorted((x["score"] for x in main_rk), reverse=True)
    wuser = res["weekly_user"]
    members = collections.defaultdict(list)
    for x in rk:
        sc = x.get("score")
        weekly = []
        for w in wk:
            v = wuser.get(w, {}).get(f"{x['name']}|{x['company']}")
            weekly.append(None if not v or v.get("score") is None or v.get("出勤日数", 0) <= 0 else round(v["score"], 1))
        members[x["company"]].append({
            "name": x["name"], "roles": x.get("roles", []), "days": x.get("出勤日数"), "apo": x.get("アポ数"),
            "score": None if sc is None else round(sc, 1),
            "rank": None if (x["参考扱い"] or sc is None) else 1 + sum(1 for v in rank_scores if v > sc),
            "ref": bool(x["参考扱い"]),
            "metrics": {k: (None if x.get(f"c_{k}") is None else round(x[f"c_{k}"], 3)) for k in COMPS},
            "weekly": weekly,
        })
    for co in members:
        members[co].sort(key=lambda m: (m["score"] is None, m["ref"], m["score"] if m["score"] is not None else 0))
    companies = []
    for co, xs in by.items():
        st = stats(xs)
        cs = {k: st[k] for k in COMPS if st[k] is not None}
        weak_k = min(cs, key=cs.get) if cs else None
        companies.append({
            "company": co, "n": st["n"], "avg": round(st["avg"], 1),
            "low_n": sum(1 for x in xs if x["score"] < 70),
            "metrics": {k: (None if st[k] is None else round(st[k], 3)) for k in COMPS},
            "weak": weak_k, "weak_val": None if weak_k is None else round(cs[weak_k], 3),
            "members": members.get(co, []),
            "weekly": [None if comp_week[w].get(co) is None else round(comp_week[w][co], 1) for w in wk],
        })
    companies.sort(key=lambda r: (-r["avg"], r["company"]))
    vals = [r["avg"] for r in companies]
    for r in companies:
        r["rank"] = 1 + sum(1 for v in vals if v > r["avg"])
        r["diff"] = round(r["avg"] - allst["avg"], 1)

    out = {
        "updated": updated, "period": f"{res['rule_start']}〜{end}",
        "weeks": [f"{w[5:7].lstrip('0')}/{w[8:].lstrip('0')}週" for w in wk],
        "targets": TARGET, "metrics": COMPS,
        "overall": {"all": {k: (None if v is None else round(v, 3 if k != 'avg' else 1)) for k, v in stats(main_rk).items()},
                    "partner": {k: (None if v is None else round(v, 3 if k != 'avg' else 1)) for k, v in stats(pt_rk).items()}},
        "weekly_team": [{"稼働人数": res["weekly_team"][w]["稼働人数"], **{k: round(res["weekly_team"][w][k], 3) for k in COMPS}} for w in wk],
        "companies": companies,
        "note": "出勤3日以上の担当者の平均。人数2名以下の企業は1人の影響が大きい。スコアは入力の取りこぼしを見る指標で営業成績の優劣ではない。",
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {OUT}: {len(companies)}社 / {allst['n']}名 / {out['period']}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().isoformat())
