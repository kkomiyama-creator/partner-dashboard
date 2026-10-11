# -*- coding: utf-8 -*-
"""新規・増員者の立ち上がり状況タブ用データ(2026-10-11新設)。

7・8月に増員した方(Cyzenアカウント作成日が2026/7/1〜8/31)と、9・10月に加わった方・新規パートナーの
稼働、初アポ、成約を集計し、ダッシュボードのタブ「新規・増員者」へ渡すJSONを作る。

  登録日   : tenure.json(Cyzen /users の作成日)。実際に営業を始めた日とずれることがある。
  稼働日   : 出勤打刻の日 + アポ台帳の獲得日(キャンセルを除く)。出勤を押さずに動く人は少なく出る。
  アポ     : アポ台帳(kintone↔アポ集計・後確通過ベース)のキャンセルを除く行。
  成約     : 獲得報告データのアポインター名(アポ成約)・クローザー名(クロ成約)。氏名表記ゆれで拾えない人がいる。
  状態     : 稼働中=直近7日に稼働 / 休眠=稼働記録はあるが直近7日はなし / 未稼働=登録後に稼働記録なし。
  出勤打刻はCIが取得する期間(前月頭〜当日)より前の分が無いため、7・8月分は
  data/newstarter_attendance_history.csv(氏名,日付)に固定して併用する。

使い方:
  python3 build_newstarter.py --tenure-json data/tenure.json --attendance-csv data/attendance_merged.csv \
     --history-csv data/newstarter_attendance_history.csv --roster-csv data/roster_live.csv \
     --closing-csv data/closing_live.csv --out data/newstarter.json
"""
import argparse, collections, csv, datetime, io, json, os, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from company_resolver import norm_name, canon_name  # noqa: E402

N = lambda s: norm_name(canon_name(s) or s or "")


def read_csv(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp932"):
        try:
            return list(csv.reader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            pass
    return []


def build(tenure_json, attendance_csv, history_csv, roster_csv, closing_csv, today=None):
    today = today or (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date()
    rec_start = today - datetime.timedelta(days=6)
    D0 = datetime.date(2026, 7, 1)
    ten = json.load(open(tenure_json, encoding="utf-8"))["people"]
    people = {N(nm): dict(name=nm, company=v["company"], roles=v["roles"], created=v["created_at"]) for nm, v in ten.items()}

    act = collections.defaultdict(set)
    if history_csv and os.path.exists(history_csv):
        for r in read_csv(history_csv)[1:]:
            if len(r) >= 2:
                act[N(r[0])].add(datetime.date.fromisoformat(r[1]))
    if attendance_csv and os.path.exists(attendance_csv):
        rows = read_csv(attendance_csv)
        if rows:
            h = rows[0]
            ni, di = h.index("ユーザー名"), h.index("日付")
            for r in rows[1:]:
                if len(r) > di and r[di]:
                    act[N(r[ni])].add(datetime.date.fromisoformat(r[di][:10]))
    apo = collections.defaultdict(list)
    for r in read_csv(roster_csv)[1:]:
        try:
            d = datetime.date(*map(int, r[0][:10].split("/")))
        except Exception:
            continue
        if not r[5].strip():
            apo[N(r[1])].append(d)
            act[N(r[1])].add(d)
    sa, sc = collections.defaultdict(list), collections.defaultdict(list)
    for r in read_csv(closing_csv)[1:]:
        try:
            d = datetime.datetime.strptime(r[8].strip(), "%Y/%m/%d %H:%M:%S").date()
        except Exception:
            continue
        sa[N(r[1])].append(d)
        sc[N(r[2])].append(d)

    def mrow(k):
        a = sorted(apo.get(k, []))
        days = sorted(d for d in act.get(k, set()) if d >= D0)
        out = []
        for m in (7, 8, 9, 10):
            out.append([sum(1 for d in days if d.month == m), sum(1 for d in a if d.month == m),
                        sum(1 for d in sa.get(k, []) if d.month == m), sum(1 for d in sc.get(k, []) if d.month == m)])
        return out, a, days

    def person(k, p):
        months, a, days = mrow(k)
        allday = sorted(act.get(k, set()))
        cr = datetime.date.fromisoformat(p["created"])
        post = [d for d in allday if d >= cr]
        first_apo = a[0] if a else None
        total = len(days)
        last = allday[-1] if allday else None
        state = "未稼働" if total == 0 else ("稼働中" if last and last >= rec_start else "休眠")
        return {"name": p["name"], "company": p["company"], "roles": "/".join(p["roles"]), "created": p["created"],
                "m": months, "first_apo": first_apo.isoformat() if first_apo else None,
                "d2a": (first_apo - cr).days if first_apo else None,
                "last": last.isoformat() if last else None, "state": state,
                "apo": sum(x[1] for x in months), "sei": sum(x[2] + x[3] for x in months), "days": total}

    cohorts = {"2026-07": [], "2026-08": [], "2026-09": [], "2026-10": []}
    for k, p in people.items():
        ym = p["created"][:7]
        if ym in cohorts:
            cohorts[ym].append(person(k, p))

    def funnel(c):
        d = [r["d2a"] for r in c if r["d2a"] is not None]
        return {"n": len(c), "act": sum(1 for r in c if r["days"] > 0), "apo": sum(1 for r in c if r["apo"] > 0),
                "sei": sum(1 for r in c if r["sei"] > 0), "live": sum(1 for r in c if r["state"] == "稼働中"),
                "med": (statistics.median(d) if d else None),
                "months": [[sum(r["m"][i][j] for r in c) for j in range(4)] for i in range(4)]}

    bycomp = collections.defaultdict(list)
    for k, p in people.items():
        bycomp[p["company"]].append((k, p))
    newcomp = []
    for co, lst in bycomp.items():
        if min(p["created"] for _, p in lst) >= "2026-09-01":
            rows = [person(k, p) for k, p in lst]
            newcomp.append({"company": co, "first": min(r["created"] for r in rows), "members": rows, "f": funnel(rows)})
    c78 = cohorts["2026-07"] + cohorts["2026-08"]
    call = c78 + cohorts["2026-09"] + cohorts["2026-10"]
    comp = collections.defaultdict(list)
    for r in call:
        comp[r["company"]].append(r)
    return {"asof": today.isoformat(), "rec_start": rec_start.isoformat(),
            "f7": funnel(cohorts["2026-07"]), "f8": funnel(cohorts["2026-08"]), "f78": funnel(c78),
            "f9": funnel(cohorts["2026-09"]), "f10": funnel(cohorts["2026-10"]), "fall": funnel(call),
            "people": call,
            "companyAll": [{"company": co, **funnel(l), "apo9": sum(r["m"][2][1] for r in l), "apo10": sum(r["m"][3][1] for r in l)} for co, l in comp.items()],
            "newcomp": newcomp}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenure-json", required=True)
    ap.add_argument("--attendance-csv", required=True)
    ap.add_argument("--history-csv", default=None)
    ap.add_argument("--roster-csv", required=True)
    ap.add_argument("--closing-csv", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = build(a.tenure_json, a.attendance_csv, a.history_csv, a.roster_csv, a.closing_csv)
    json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out}: 7月{res['f7']['n']}名 8月{res['f8']['n']}名 9月{res['f9']['n']}名 10月{res['f10']['n']}名 新規パートナー{len(res['newcomp'])}社")


if __name__ == "__main__":
    main()
