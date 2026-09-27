"""NHK会長編 v1 の spec.json を作る（premiere-short-xml スキルの定義ファイル）。

手で spec.json を直さず、ここを直して流す。12の席が1つずつ点く時刻は、
一度ビルドしたあとの timeline.json（テロップの時刻）から計算する（なければ目印の言葉で仮置き）。
"""
import json
from pathlib import Path

W = Path(__file__).parent

# ---- 12の席を1つずつ点ける時刻（6行目「賛成の手を挙げたのは」〜「9人」）
def seat_swaps():
    tl = W / "timeline.json"
    if tl.exists():
        units = json.loads(tl.read_text(encoding="utf-8")).get("units", [])
        def f_of(line, head):  # その行で、文字が head で始まるテロップの出る時刻（フレーム）
            for u in units:
                if u.get("line") == line and u.get("text", "").startswith(head):
                    return u.get("start")
        a, b = f_of(6, "賛成の手"), f_of(6, "9人")
        st = next((c["start"] for c in json.loads(tl.read_text(encoding="utf-8")).get("chars", []) if c["id"] == "C06"), None)
        if isinstance(a, int) and isinstance(b, int) and b > a and isinstance(st, int):
            a, b = a - st, b - st  # chars の {"frame": n} は、その絵の項目の頭からのフレーム数
            step = (b - a) / 9
            fr = [int(round(a + 4 + step * i)) for i in range(8)] + [b]
            return [{"at": {"frame": f}, "img": f"chars_src/seats_{i + 1:02d}_lit.png"} for i, f in enumerate(fr)]
    return [{"at": {"line": 6, "anchor": "賛成の手"}, "img": "chars_src/seats_01_lit.png"},
            {"at": {"line": 6, "anchor": "9人"}, "img": "chars_src/seats_09_lit.png"}]


def qmark(inn, out=None):
    """聞き手の問いの行に出す、背景の大きな黄色い「？」（薄め）。"""
    a = {"text": "？", "font": "m", "size": 900, "opacity": 0.3, "stroke": 0, "color": [255, 230, 0], "pos": [540, 900], "in": inn}
    if out:
        a["out"] = out
    return a


SEATS = {"x": 540, "y": 445, "scale": 0.62, "ref": "center"}          # 図の場所（y 197〜693）
FLOW = {"x": 620, "y": 560, "scale": 0.62, "ref": "center"}           # 3段の図（y 170〜951）
Y_LOW = 1150                                                         # 顔・図を見せる拍のテロップの高さ

spec = {
    "_説明": "NHK会長編 v1（ゆっくり縦ショート作成スキルのサンプル）。台本 v2b・音声 v1b。make_spec.py で作る（spec.json を手で直さない）。絵は Codex の JS Paint（絵/NHK_JS_Paint素材_v2）、図は Codex CLI の自作（図/v1）、スクショは e-Gov の放送法52条。",
    "title": "NHK会長編_v2",
    "layout": "vertical",
    "telop_mode": "text",
    "font_ps": "HiraMinProN-W6",
    "script": "../../台本_v2b_NHK会長編.md",
    "audio": {"manifest": "../../音声/v1b/manifest.json"},
    "fps": 30,
    "start_offset_sec": 0.1,
    "gap_sec": 0.2,
    "tail_before_end_sec": 0.3,
    "end_card_sec": 2.5,
    "lead_frames": 2,
    "label": "NHKのしくみ",
    "layout_overrides": {"telop_block_y": 960, "note_align": "left", "note_x": 40, "note_w": 880, "note_size": 30, "note_min_size": 20},
    "telop_box": {"color": [44, 44, 48], "opacity": 40, "pad_x": 34, "pad_y": 10, "radius": 18},
    "title_card": {"lines": [["NHK会長は", "w"], ["誰が", "r"], ["決めている？", "w"]],
                   "line_px": [140, 176, 140], "y": 985, "motion": "spin"},
    "lines": {
        "2": [{"anchor": "NHKの中で", "lines": [["NHKの中で", "p"], ["話し合い？", "p"]]}],
        "3": [{"anchor": "決めるのは", "lines": [["決めるのは", "w"]], "size": "s"},
              {"anchor": "経営委員会", "lines": [["経営委員会", "r"]], "size": "l", "motion": "spin"},
              {"anchor": "12人の", "lines": [["12人", "y"], ["の委員", "w"]]}],
        "4": [{"anchor": "12人で", "lines": [["12人で", "p"], ["多数決？", "p"]]}],
        "5": [{"anchor": "ただの", "lines": [["ただの多数決", "w"], ["じゃない", "w"]]},
              {"anchor": "12人のうち", "lines": [["12人のうち", "w"], ["9人以上", "y"], ["の賛成", "w"]]},
              {"anchor": "法律で", "lines": [["法律で", "w"], ["決まっている", "y"]]}],
        "6": [{"anchor": "井上樹彦", "lines": [["井上樹彦", "r"], ["会長を決めた", "w"]], "y": Y_LOW},
              {"anchor": "2025年", "lines": [["2025年12月", "y"], ["の会議", "w"]], "y": Y_LOW},
              {"anchor": "賛成の手", "lines": [["賛成の手を", "w"], ["挙げたのは", "w"]], "y": Y_LOW},
              {"anchor": "12人中", "lines": [["12人中", "w"]], "y": Y_LOW},
              {"anchor": "9人", "lines": [["9人", "y"]], "size": "l", "y": Y_LOW}],
        "7": [{"anchor": "ぎりぎり", "lines": [["ぎりぎり", "r"], ["じゃない！", "p"]], "y": 1200}],
        "8": [{"anchor": "賛成が", "lines": [["賛成があと", "w"], ["1人", "y"], ["少なければ", "w"]]},
              {"anchor": "決まらなかった", "lines": [["決まらなかった", "r"]]}],
        "9": [{"anchor": "じゃあ", "lines": [["その12人は", "p"], ["誰が選ぶ？", "p"]], "y": Y_LOW}],
        "10": [{"anchor": "国会の", "lines": [["国会の同意を得て", "w"]], "y": Y_LOW},
               {"anchor": "総理大臣", "lines": [["総理大臣", "r"], ["が任命", "w"]], "y": Y_LOW}],
        "11": [{"anchor": "受信料を", "lines": [["受信料を払ってる", "p"], ["私たちは？", "p"]], "y": Y_LOW}],
        "12": [{"anchor": "今年度", "lines": [["今年度の予算で", "w"], ["約5900億円", "y"]], "y": Y_LOW},
               {"anchor": "それを払う", "lines": [["会長を", "w"], ["直接選ぶ場面は", "w"]], "y": Y_LOW},
               {"anchor": "ない", "lines": [["ない", "r"]], "size": "l", "y": Y_LOW}],
        "13": [{"anchor": "払うのは", "lines": [["払うのは私たち", "p"], ["なのに", "p"]], "y": Y_LOW},
               {"anchor": "直接は", "lines": [["直接は選べない", "p"]], "y": Y_LOW}],
        "14": [{"anchor": "会長選びに", "lines": [["会長選びに", "w"]], "y": Y_LOW},
               {"anchor": "受信料を払う", "lines": [["受信料を払う", "w"], ["私たちの", "w"]], "y": Y_LOW},
               {"anchor": "一票は", "lines": [["会長選びの", "w"], ["一票はない", "r"]], "line_px": [96, 128], "y": 1085, "hold": True},
               {"anchor": "NHK会長の", "lines": [["NHK会長の決め方", "y"]], "y": 1270, "hold": True, "tracks_from": 2}],
    },
    "notes": [
        {"lines": [3, 4], "text": "放送法 第30条\n「経営委員会は、委員十二人をもつて組織する」"},
        {"lines": [5, 5], "text": "放送法 第52条2項（e-Gov 法令検索）\n「経営委員会は、委員九人以上の多数による議決によらなければならない」"},
        {"lines": [6, 7], "text": "NHK経営委員会 第1483回議事録（2025年12月8日）\n「採決の結果、賛成9人」（出席は委員12人）"},
        {"lines": [8, 8], "text": "放送法 第52条2項\n会長の任命は、委員9人以上の多数による議決が必要"},
        {"lines": [9, 10], "text": "放送法 第31条（経営委員の任命）\n「両議院の同意を得て、内閣総理大臣が任命する」"},
        {"lines": [11, 13], "text": "受信料収入 5,910億円\n（NHK 2026年度予算。決算ではない）"},
    ],
    "backgrounds": [
        {"id": "BG1", "from": 1, "to": 4, "label": "動く背景：紺（光の帯・放射・粒・走査線・拍の脈・山場の集中線。make_bg_anim.py）", "image": "bg_src/bg_01_navy.png", "dim": 1.0, "motion": "in", "anim": True},
        {"id": "BG2", "from": 5, "to": 8, "label": "動く背景：灰（光の帯・放射・粒・拍の脈・山場の集中線。make_bg_anim.py）", "image": "bg_src/bg_02_slate.png", "dim": 1.0, "motion": "in", "anim": True},
        {"id": "BG3", "from": 9, "to": 14, "label": "動く背景：藍（締めまで。光の帯・放射・粒・拍の脈・山場の集中線。make_bg_anim.py）", "image": "bg_src/bg_03_indigo.png", "dim": 1.0, "motion": "in", "anim": True},
    ],
    "v2": [
        {"id": "SH1", "kind": "shot", "from": 5, "to": 5,
         "source": {"image": "shots_src/SH1_放送法52条_e-Gov.png"},
         "caption": "放送法 第52条（e-Gov 法令検索）",
         "memo": "第52条1項「会長は、経営委員会が任命する。」2項「…委員九人以上の多数による議決によらなければならない。」（令和7年10月1日施行の版・表示倍率160％で撮影）",
         "view": [500, 180, 1512, 900],
         "steps": [
             {"at": "12人のうち", "view": [838, 318, 1450, 553], "dur": 12},
             {"at": "9人以上", "mark": [1059, 381, 1417, 410], "dur": 12},
             {"at": "法律で", "box": [1053, 376, 1423, 415]},
             {"at": "決まっている", "stamp": "九人以上", "sub": "放送法 第52条2項", "pos": [0.78, 0.74]},
         ]},
    ],
    "chars": [
        {"id": "C01", "name": "冒頭_放送センター", "from": 1, "to": 2,
         "memo": "題名の上に NHK の建物（Codex の JS Paint）。ポンと出て、2行目の終わりまで",
         "actors": [{"img": "chars_src/nhk_center.png", "place": {"x": 540, "y": 455, "scale": 1.4, "ref": "center"},
                     "in": {"how": "drop", "dur": 9, "bounce": 26}, "bob": 2,
                     "tilt": [{"at": {"line": 2, "anchor": "話し合って"}, "deg": -5}]},
                    qmark(inn={"at": {"line": 2}, "how": "pop", "dur": 6})]},
        {"id": "C03", "name": "12の席", "from": 3, "to": 4,
         "memo": "「経営委員会」で12の席（全部暗い）が出る",
         "actors": [{"img": "chars_src/seats_00_dark.png", "place": SEATS, "in": {"at": "経営委員会", "how": "pop", "dur": 8}},
                    {"text": "経営委員会（12人）", "pos": [540, 745], "size": 46, "font": "g",
                     "in": {"at": "経営委員会", "how": "fade", "dur": 6, "delay": 4}},
                    qmark(inn={"at": {"line": 4}, "how": "pop", "dur": 6})]},
        {"id": "C06", "name": "賛成9人と会長", "from": 6, "to": 8,
         "memo": "12の席が図の場所に。「賛成の手を挙げたのは」から1つずつ点いて「9人」で9つ。「井上樹彦」で会長が図のすぐ下から（1.5倍）、聞き手の「ぎりぎり」で汗の困り顔にして揺れる。8行目で会長は下へ退き、「少なければ」で9つ目が消える",
         "actors": [
             {"img": "chars_src/seats_00_dark.png", "place": SEATS, "in": {"how": "fade", "dur": 6},
              "swap": seat_swaps() + [{"at": {"line": 8, "anchor": "少なければ"}, "img": "chars_src/seats_10_ninth_off.png"}],
              "hop": [{"line": 6, "anchor": "9人"}], "shake": [{"line": 8, "anchor": "少なければ"}]},
             {"img": "chars_src/viewer_cross.png", "place": {"x": 320, "y": 600, "scale": 0.3, "ref": "center"},
              "in": {"at": {"line": 8, "anchor": "少なければ"}, "how": "pop", "dur": 6}},
             {"img": "chars_src/inoue_01_pokan.png", "place": {"x": 540, "y": 690, "scale": 1.5},
              "in": {"at": "井上樹彦", "how": "up", "dur": 10}, "bob": 2,
              "out": {"at": {"line": 7}, "how": "cut"}},
             {"img": "chars_src/inoue_02_komari.png", "place": {"x": 540, "y": 600, "scale": 1.9},
              "in": {"at": {"line": 7}, "how": "pop", "dur": 5}, "shake": [{"line": 7, "anchor": "ぎりぎり"}],
              "out": {"at": {"line": 8}, "how": "down", "dur": 10}},
             {"text": "※イラストはイメージです", "pos": [200, 1640], "size": 28,
              "in": {"at": "井上樹彦", "how": "fade", "dur": 6}, "out": {"at": {"line": 8}, "how": "fade", "dur": 8}},
             {"text": "もしも賛成8人なら → 不成立", "pos": [540, 760], "size": 44, "font": "g", "color": [255, 230, 0],
              "in": {"at": {"line": 8, "anchor": "少なければ"}, "how": "pop", "dur": 6}},
         ]},
        {"id": "C09", "name": "3段の図と視聴者", "from": 9, "to": 14, "hold": True,
         "memo": "9行目で「経営委員12人 → 会長（枠に井上会長）」、10行目「総理大臣」で上の段（顔のない人形）。「国会の同意」で矢印の横に小さく「衆参両院の同意」。11行目「私たち」で左に家、12行目「直接選ぶ」で点線の矢印が伸び、「ない」で✗と「会長への直接投票なし」。締めまで残す",
         "actors": [
             {"img": "chars_src/flow_02_committee.png", "place": FLOW, "in": {"how": "pop", "dur": 8}},
             {"img": "chars_src/flow_03_chair_frame.png", "place": FLOW, "in": {"how": "pop", "dur": 8, "delay": 6}},
             {"img": "chars_src/inoue_01_pokan.png", "place": {"x": 620, "y": 695, "scale": 0.55},
              "in": {"how": "pop", "dur": 8, "delay": 10}, "hop": [{"line": 12, "anchor": "ない"}]},
             qmark(inn={"at": {"line": 9}, "how": "pop", "dur": 6}, out={"at": {"line": 10}, "how": "fade", "dur": 5}),
             qmark(inn={"at": {"line": 11}, "how": "pop", "dur": 6}, out={"at": {"line": 12}, "how": "fade", "dur": 5}),
             {"text": "※イラストはイメージです", "pos": [200, 1640], "size": 28, "in": {"how": "fade", "dur": 6, "delay": 10},
              "out": {"at": {"line": 10}, "how": "fade", "dur": 8}},
             {"img": "chars_src/flow_01_pm.png", "place": FLOW, "in": {"at": {"line": 10, "anchor": "総理大臣"}, "how": "drop", "dur": 8, "bounce": 20}},
             {"text": "衆参両院の同意", "pos": [880, 355], "size": 42, "font": "g",
              "in": {"at": {"line": 10, "anchor": "国会の"}, "how": "fade", "dur": 6}},
             {"img": "chars_src/viewer_house.png", "place": {"x": 200, "y": 850, "scale": 0.55, "ref": "center"},
              "in": {"at": {"line": 11, "anchor": "私たち"}, "how": "pop", "dur": 8}},
             {"img": "chars_src/viewer_arrow_up.png", "place": {"x": 200, "y": 640, "scale": 0.6, "ref": "center"},
              "in": {"at": {"line": 12, "anchor": "直接選ぶ"}, "how": "up", "dur": 10}},
             {"img": "chars_src/viewer_cross.png", "place": {"x": 200, "y": 520, "scale": 0.45, "ref": "center"},
              "in": {"at": {"line": 12, "anchor": "ない"}, "how": "pop", "dur": 7},
              "shake": [{"line": 13, "anchor": "直接は"}, {"line": 14, "anchor": "一票は"}]},
             {"text": "会長への直接投票なし", "pos": [245, 425], "size": 40, "font": "g",
              "in": {"at": {"line": 12, "anchor": "ない"}, "how": "fade", "dur": 6, "delay": 4}},
         ]},
    ],
    "end_card": {"style": "hold", "sender": "スキルのサンプル動画・出典は概要欄"},
    "extra_notes": [
        "絵（井上会長・放送センター）は Codex が JS Paint で描いた似顔絵・イラスト。公式写真・公式ロゴは使っていない（参考にした写真の URL は 絵/NHK_JS_Paint素材_v2/はじめに.md）",
        "12の席・3段の図・家・矢印・✗は自作（図/v1/make_figures.py）。総理大臣は顔のない人形で、実在の人物に似せていない",
        "条文のスクショは e-Gov 法令検索（法令は著作権の対象外）",
        "声は AquesTalk（ゆっくりボイス）。個人の非営利利用。音声ファイルを公開リポジトリに入れるかは規約を確認してから",
    ],
    "readme_extra": [
        "ゆっくり縦ショート作成スキルのサンプル（NHK会長編）。台本 v2b・音声 v1b",
        "BGM・効果音はまだ入れていない（T09 で規約を確かめてから足す）",
        "井上会長の絵が似ているかは、ユーザーの確認待ち（T05）",
    ],
}

(W / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("spec.json を書いた。席の点灯：", [s["at"] for s in seat_swaps()][:3], "…")
