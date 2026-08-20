# -*- coding: utf-8 -*-
import csv
import os

CYZEN_MASTER = "/Users/fitfounderkomiyamakyousuke/Desktop/Cyzenからのエクスポートデータ/ユーザーマスター（営業担当者の情報）.csv"

COMPANY_CANON = {
    "株式会社JINNOVA(元栗山推進)": "株式会社JINNOVA",
    "株式会社LIVIONpartners(元イージスホーム)": "株式会社LIVION partners",
    "株式会社LIVIONpartners": "株式会社LIVION partners",
    "Birth47": "株式会社Birth47",
    "Noble Seed": "Noble Seed株式会社",
    "株式会社GUIDANCE": "株式会社guidance",
}
def canon(co):
    co = (co or "").strip()
    return COMPANY_CANON.get(co, co)

def norm_name(n):
    return (n or "").strip().replace(" ", "").replace("　", "").replace("髙", "高").replace("濵", "濱")

NON_COMPANY = {"アポインター", "クローザー", "パートナー", "社員", "直販", "管理者", "本部", "マネージャー",
               "代表取締役", "役員"}

FUZZY_OVERRIDE = {  # 2026-07-26 表記ゆれ・タイプミスを手動照合（ユーザーマスタに厳密一致がないもの）
    "井伊大陽": "株式会社ASG",
    "伊井太陽": "株式会社ASG",
    "百瀬遥希": "株式会社Fit Founder",
    "ハマダユウタ": "株式会社ASG",
    "中川魅人": "Ambitious株式会社",
    "春日ゆきや": "Ambitious株式会社",  # 2026-07-27 春日柚樹也の読み仮名表記（Ambitious・東海）
    "髙橋雄多(wiz)": "株式会社Wiz",
    "wiz 髙橋雄多": "株式会社Wiz",
    "辻坂修太郎": "株式会社UNIVA FIT",
    "春日": "Ambitious株式会社",  # 唯一の該当行がエリア=東海・クローザー井上務(Ambitious)のため推定。要確認
    "野崎太志": "Ambitious株式会社",  # 2026-07-26 小宮山さん確認済み
}

# 2026-07-27: 会社名は正しく解決できていても「同一人物が別表記で2行に分かれる」問題が発覚
# （例: 百瀬遥希/百瀬遥輝、辻坂修太郎/辻坂修太朗が別人としてランキングに二重計上されていた）。
# FUZZY_OVERRIDEは会社名の解決にしか使われず、個人別ランキングの行の名寄せには使われていなかったのが原因。
# ここで表記ゆれをユーザーマスタの正式表記に統一し、ranking_core側で集計前に必ずcanon_name()を通す。
NAME_CANON = {
    "百瀬遥希": "百瀬遥輝",
    "辻坂修太郎": "辻坂修太朗",
    "中川魅人": "中川魁人",
    "井伊大陽": "伊井大陽",
    "伊井太陽": "伊井大陽",
    "ハマダユウタ": "濵田裕大",
    "春日": "春日柚樹也",  # 唯一の該当行がエリア=東海・クローザー井上務(Ambitious)のため推定。要確認
    "春日ゆきや": "春日柚樹也",
    "wiz 髙橋雄多": "髙橋雄多",
    "髙橋雄多(wiz)": "髙橋雄多",
    # 2026-08-03: 小宮山さんから「栗山さんの7月合計が合わない」との指摘を受けた監査で発覚。
    # 獲得報告データの「アポインター名」「クローザー名」欄に、稀に社名サフィックス付きの表記
    # （例:「野村 俊介 Corest home」）が混じっており、素の表記（「野村 俊介」）と別人扱いされ
    # 個人別ランキングの実績が2行に分割されていた（会社合計は元々正しいので企業別ランキングには影響なし）。
    "野村 俊介 Corest home": "野村 俊介",
    "伊木 裕二 Corest home": "伊木 裕二",
}


def canon_name(raw_name):
    """個人名の表記ゆれを統一する。ranking_core側で各データソースから名前を読んだ直後に必ず通すこと。
    エイリアス辞書(NAME_CANON)の照合は元の表記のまま行うが、戻り値は常にnorm_name()と同じ文字種
    （髙→高・濵→濱）に畳んでから返す。これをしないと、データソースによって「髙橋崇大」「高橋崇大」の
    ように表示名だけが日によって割れ、フロント側の文字列完全一致マッチ（ドリルダウン等）が崩れる
    （2026-08-19修正・小宮山さん報告：一興商事髙橋さんのドリルダウン件数が表全体の数と合わない件）。"""
    n = (raw_name or "").strip()
    n = NAME_CANON.get(n, n)
    return n.replace("髙", "高").replace("濵", "濱")

def load_master():
    # CYZEN_MASTERは小宮山さんのローカルMac上にしか無いブラウザ手動エクスポートファイル(個人情報を
    # 含むため公開リポジトリにはコミットしない)。GitHub Actions実行環境には存在しないので、無い場合は
    # 空辞書にフォールバックする(2026-08-20・CI対応)。company_of()の優先順位が1段階弱まる
    # (ロースター多数決/Slack送信者パース/直販スタッフ判定にフォールバック)だけで、クラッシュはしない。
    if not os.path.exists(CYZEN_MASTER):
        return {}
    m = {}
    with open(CYZEN_MASTER, encoding="utf-8-sig", errors="replace") as f:
        r = csv.reader(f)
        idx = {h: i for i, h in enumerate(next(r))}
        for row in r:
            name = row[idx["名前"]].strip()
            if not name:
                continue
            attrs = [a.strip() for a in row[idx["メンバー属性"]].split("\n") if a.strip()]
            comps = [a for a in attrs if a not in NON_COMPANY]
            if comps:
                m[norm_name(name)] = canon(comps[0])
    return m

MASTER = load_master()

def resolve_company(raw_name, roster_votes=None, sender_map=None, direct_staff=None):
    """会社解決の優先順位: Cyzenユーザーマスタ(厳密一致) > 手動fuzzy補正 > ロースター多数決 > Slack送信者パース > 直販スタッフ判定"""
    n = norm_name(raw_name)
    if n in MASTER:
        return MASTER[n]
    if n in {norm_name(k) for k in FUZZY_OVERRIDE}:
        for k, v in FUZZY_OVERRIDE.items():
            if norm_name(k) == n:
                return v
    if roster_votes and n in roster_votes and roster_votes[n]:
        return max(roster_votes[n].items(), key=lambda kv: kv[1])[0]
    if sender_map and n in sender_map:
        return sender_map[n]
    if direct_staff and n in {norm_name(x) for x in direct_staff}:
        return "株式会社Fit Founder"
    return None
