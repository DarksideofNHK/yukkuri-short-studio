# spec.json の書き方

パスはすべて spec.json のあるフォルダからの相対パス。実例は `assets/example_spec.json`（NHK会長編）。この配布用実例はリポジトリ直下へ新しい名前でコピーして使う前提で、`examples/nhk-chairman/` から始まる相対パスを記載している。設定を別の場所に置く場合はパスを書き換える。BGM・効果音の設定は実行時のカレントディレクトリ基準なので、リポジトリ直下から実行する。

## 全体

| 項目 | 例 | 意味 |
|---|---|---|
| `title` | `"NHK会長編_v2"` | XML のファイル名とシーケンス名。作り直すたびに変えると Premiere 上で見分けやすい |
| `layout` | `"vertical"` / `"horizontal"` | 縦 1080×1920 / 横 1920×1080（common.py の LAYOUTS） |
| `layout_overrides` | `{"telop_block_y": 1150}` | 省略可。LAYOUTS の値をこの動画だけ上書き（XML・動く図・プレビューのどれにも効く。common.py の layout_of） |
| `telop_box` | `{"color": [44,44,48], "opacity": 40, "pad_x": 34, "pad_y": 10, "radius": 18}` | 省略可。テロップの座布団（グレーの角丸の四角）。テロップ1枚ごとに、いちばん長い行＋余白の大きさの画像を暗幕の段（イラストありなら V4）に置き、テロップと同じ拡大の動き・不透明度（Premiere の「不透明度」で変えられる）。あると暗幕は置かない。時間が重なる（締めの hold）ところは2つを囲む1枚に。テロップごとに `"box": false` で外せる |
| `telop_mode` | `"text"`（既定）/ `"image"` | 文字クリップ（打ち替え可）/ 画像テロップ |
| `font_ps` | `"HiraMinProN-W6"` | 文字クリップの書体。PostScript 名（空白なし）。ゴシックは `HiraginoSans-W6` など |
| `script` | `"../narration/台本.md"` | 台本。``` の中に「`1 説明役：セリフ`」（話者は説明役・聞き手、または まりさ・れいむ） |
| `audio.manifest` | `"../narration/音声/manifest.json"` | yukkuri-voice の出力。旧形式（行のリスト）なら `audio.file_key`・`audio.sec_key` も |
| `fps` | `30` | |
| `start_offset_sec` / `gap_sec` / `tail_before_end_sec` / `end_card_sec` | `0.1` / `0.2` / `0.3` / `2.5` | 最初の間・行間・最後の行のあと・エンドカードの長さ |
| `lead_frames` | `2` | テロップを言葉より何フレーム早く出すか |
| `label` | `"NHKのしくみ"` | 左上のラベル（画像） |
| `speakers` | 省略可 | 話者ごとのトラック。既定は 説明役 V4〜V6・A1、聞き手 V7〜V8・A2（`listener: true` で小さめ・やわらかい動き） |

## テロップ：`title_card` と `lines`

```json
"title_card": {"lines": [["NHK会長は", "w"], ["誰が", "r"], ["決めている？", "w"]], "size": "m"},
"lines": {
  "3": [{"anchor": "決めるのは", "lines": [["決めるのは", "w"]]},
        {"anchor": "経営委員会", "lines": [["経営委員会", "r"]]}],
  "5": [{"anchor": "12人のうち", "lines": [["12人のうち", "w"], ["9人以上", "y"], ["の賛成", "w"]]}]
}
```

- キーは台本の行番号（文字列）。値はその行で順に出すテロップのリスト
- `anchor`：ナレーションの中の言葉。その言葉が読まれる時刻に出る。同じ行で前のテロップの目印より後ろから探す。見つからないと文字数の比例の位置
- `lines`：`[文字, 色]` の行。色 `w` 白・`y` 黄・`r` 赤・`p` ピンク。同じ色が続く行は1つの文字クリップにまとまる。色が変わるたびに次の段（トラック）になる（説明役は最大3段、聞き手は2段）
- `size`：`s` 80px（動きなし）・`m` 104px・`l` 128px（縦）。聞き手は 0.94 倍。長い行は画面幅に収まるまで小さくなる
- `motion`：省略時は 黄・赤があれば `pop`（65→108→100％）、白だけなら `rise`（92→100％）、聞き手は `soft`
- 旧形式 `text: [[[文字, 色], ...], ...]`（語ごとの色）も読める。文字クリップでは色の変わり目で行が分かれる
- 題名（`title_card`）は最初のテロップが出るまで表示
- `hold: true`：そのテロップをエンドカードの終わりまで残す（締め用）。`y`：そのテロップだけ中心の高さを変える。`tracks_from`：同じ時間に出ている別のテロップと段（トラック）を分ける（例：締めの2つ目は `tracks_from: 2`）
- `y` の使い分けは `design_rules.md` の「テロップ」（真ん中 `telop_block_y: 960` が基本、人物の顔を見せたい拍だけ `"y": 1150`、3段は 1175〜1180）。顔が出る前の短いつなぎ（「実は」など）は真ん中のまま
- `motion: "spin"`：文字がくるっと1回転しながら大きくなって出る（Basic Motion の回転 −360→0°・拡大 20→100％、14フレーム。座布団は回さず14フレームでふわっと出す）。`title_card` にも書ける。Premiere のスピンモーション（トランジション）は XML で渡せないので、その代わり（`premiere_xml_notes.md`）
- `dissolve_in`：文字クリップの頭にクロスディゾルブ（フレーム数。例 8）。Premiere で「クロスディゾルブ」になる
- `line_px`：行ごとの文字の大きさ（px、text_scale の倍数。例 `[88, 100, 120]`）。ユーザーが Premiere で行ごとに拡大した題名などを取り込むとき。行の間隔はそれぞれの行の大きさ×`line_pitch`
- `title_card` の `text_start_f`：題名の文字だけこのフレームから出す（座布団は 0 から）。冒頭にユーザーが Premiere で足した絵（「NHKのしくみ」など）の間をあける
- 注記（`notes`）は既定で中央ぞろえ。`layout_overrides: {"note_align": "left"}` で左寄せ（左端は画面の中央 − note_w/2、`note_x` を書けばその x。実際の制作での指示「いちばん下の注記は左寄せで」）
- 注記の文に `\n` を書くと、その位置で改行し、どの行も `note_w` に収まるまで字を小さくする（最小 `note_min_size`、既定 20）。1字ずつの折り返しで「202／6年」のように変な位置で切れるのを防ぐ。改行を書かない注記は従来どおり（`note_fit: true` で同じく縮める）。ショートの右下の操作ボタンにかからないよう、縦では `note_x` 40・`note_w` 880 前後（NHK会長編 v1c、2026-09-28 ユーザー指示「左寄せかつ、字が小さくなってもいいので変にはみ出さないように」）
- `empty_tracks`（spec の最上位）：`{"V13": "説明"}` で空のビデオトラックを足す。前の版でユーザーが Premiere で作ったクリップ（絵文字・トランジション付きのグラフィックなど XML で作れないもの）を、前のシーケンスからコピーして同じ時刻に貼る場所

## 図・スクショ：`v2`

共通：`id`、`kind`、`from`〜`to`（台本の行番号。その行の頭から、`to` の次の行の頭まで表示。`from` が最初の行なら0フレームから）。`until`（省略可）：`{"line": 6, "anchor": "井上樹彦"}` のように、行の途中の言葉で下げる（そこから上の場所をイラストに譲るときなど）。

### `chart`（グラフ4種、動き付き）

`on` は「この図の範囲の何番目のテロップか」（1から）。

| type | 主な項目 |
|---|---|
| `line` 折れ線 | `points` [[ラベル, 値]...]、`y_range`、`threshold` {value, label, over_label}、`value_format`、`start_on`、`glow_on`、`segment_frames` |
| `hbar` 横棒の比較 | `rows` [[名前, 値, 強調]...]、`x_range`、`flash_on`、`stamp` {text, sub, on, x, y}、`value_format` |
| `compare` 縦棒2〜3本 | `mode` shortfall（不足）/ increase（増えた差）、`bars` [{label, value, color, on}]、`note_on`、`note_label` |
| `hbar_seq` 横棒を順に | `subtitle` {text, on}、`rows` [{label, value, color, on, impact}]、`value_format`（`man_yen` で +2万2400円） |

共通：`title`、`footnote`。

### `shot`（スクショの動き）

```json
{
  "id": "SH1",
  "kind": "shot",
  "from": 5,
  "to": 5,
  "source": {
    "image": "examples/nhk-chairman/premiere/v1/shots_src/SH1_放送法52条_e-Gov.png"
  },
  "caption": "放送法 第52条（e-Gov 法令検索）",
  "memo": "第52条1項「会長は、経営委員会が任命する。」2項「…委員九人以上の多数による議決によらなければならない。」（令和7年10月1日施行の版・表示倍率160％で撮影）",
  "view": [
    500,
    180,
    1512,
    900
  ],
  "steps": [
    {
      "at": "12人のうち",
      "view": [
        838,
        318,
        1450,
        553
      ],
      "dur": 12
    },
    {
      "at": "9人以上",
      "mark": [
        1059,
        381,
        1417,
        410
      ],
      "dur": 12
    },
    {
      "at": "法律で",
      "box": [
        1053,
        376,
        1423,
        415
      ]
    },
    {
      "at": "決まっている",
      "stamp": "九人以上",
      "sub": "放送法 第52条2項",
      "pos": [
        0.78,
        0.74
      ]
    }
  ]
}
```

- `source`：`{"pdf", "page", "dpi"}`（座標はポイント）か `{"image": "画像.png"}`（座標は px）。PDF のページ画像は `media_anim/_src/` にためる
- `view`：最初に見せる範囲 [x0, y0, x1, y1]（省略でページ全体）。縦横比 1.15〜2.6 に広げ、資料の外には出ない
- `steps` の種類
  - `view` + `dur`：その範囲へ寄る（`"page"` で全体）
  - `mark` + `dur`：マーカー（黄、`color` で変更可）。複数行は [[...], [...]] で順に引く。`punch`（既定 true）で軽くポン、`spot: true` でまわりを暗く
  - `box`：赤い角丸の枠
  - `stamp` + `sub` + `pos`（図の範囲に対する割合）：ハンコ・揺れ・白く光る
- `at`：目印の言葉（`from` の行）／`{"line": n, "anchor": "…"}`／`{"line": n}`（行の頭）／`{"frame": n}`／`on: k`
- `drift`（既定 0.035）：全体を通して少しずつ寄る量。`enter_at`：出てくるフレーム
- `memo`：素材リストに載せるメモ

### `slot`（差し替え枠）と `quote`（引用カード）

- `slot`：`label`、`hint`、`url`。黄色い点線の枠に「［差し替え］」と入れる
- `quote`：`caption`（上の小さい字）、`lines`（文字の行。`[文字, 色]` で行ごとの色も可）、`size`、`color`、`source`（下の出典。長ければ2行）、`caption_size`・`source_size`（既定 30・22。テレビ向けの横版は大きめに）

## イラスト：`chars`（人物・小物・雨。動く透明の動画）

1項目＝1本の動画（`media_anim/イラスト_{id}_{name}.mov`、ProRes 4444）。トラックは図・スクショの上、テロップの下（V3）。
chars があると、暗幕から上のトラックが1つずつ上がる（暗幕 V4・テロップ V5〜V9・エンドカード V10・注記 V11・ラベル V12）。

```json
"chars": [
 {"id": "C07", "name": "会長の困り顔", "from": 7, "to": 7,
  "memo": "聞き手の反応に合わせて表情を変えて揺らす",
  "actors": [
   {"img": "examples/nhk-chairman/premiere/v1/chars_src/inoue_02_komari.png",
    "place": {"x": 540, "y": 600, "scale": 1.9},
    "in": {"how": "pop", "dur": 5},
    "shake": [{"line": 7, "anchor": "ぎりぎり"}]},
   {"text": "※イラストはイメージです", "pos": [200, 1640], "size": 28}]}
]
```

- `at` の `{"frame": n}` は、動画全体の時刻ではなく**その項目（chars の1項目・v2 の1つの図）の頭からのフレーム数**（build_premiere.py の step_frame）。テロップの時刻（timeline.json の units の start）から計算するときは、timeline.json の chars の `start` を引く（NHK会長編 v1 で12の席を1つずつ点けたとき、2026-09-28）
- `from`〜`to`：v2 と同じ（その行の頭から、`to` の次の行の頭まで）。`hold: true` で、`to` が最後の行ならエンドカードの終わりまで残す（NHK会長編の3段の図など）。`at` も v2 の手順と同じ書き方（目印の言葉／`{line, anchor}`／`{line}`／`{frame}`）で、省略すると項目の頭
- `place`：`ref: "head"`（既定・人物）は 360×640 の絵の頭の上端の中央（180, 97）を画面の (x, y) に置く。絵の差分は頭の位置をここにそろえておくと、絵を替えても顔の位置が動かない。`ref: "center"`（小物）は絵の中身の中心を (x, y) に。`scale` は絵の倍率（整数なら点のまま、はんぱなら滑らかに拡大）、`flip` で左右反転
- `in`：`how` = `pop`（ポン）・`up`（下から）・`slide_l`/`slide_r`（横から）・`fade`・`cut`・`drop`（上から落ちて「どすん」。着地は `at` の `dur` フレーム後＝効果音はそこに。`height` で落ちる高さの足し、`bounce` で弾む高さ。NHK会長編の放送センターなど）・`spin`（くるっと1回転しながら大きくなる。冒頭の小物など）、`dur`、`delay`（フレーム）
- `out`：`how` = `slide_l`/`slide_r`（横へ出る）・`down`・`fade`・`pop`（縮んで消える）・`cut`。省略すると項目の終わりまで出たまま
- 絵の差し替え：`swap` [{at, img}]、`talk` {img, from, to, every}（その間、口の開いた絵と交互＝口パク）、`loop` {imgs, from, to, every}（くり返し）、`blink` {img, every}（もとの絵のときだけまばたき）
- 動き：`bob`（上下にゆれる幅 px）、`shake` [at...]（揺れ）、`hop` [at...]（小さく跳ねる）、`nod` [at...]（うなずく）、`tilt` [{at, deg}]（首かしげ。足もとを軸に回る）、`ghost` {at}（薄い灰色に＝不在）、`opacity`・`gray`（最初から薄い・灰色）
- `crop_bottom`（y）：そこから下をぼかして切る（上の図の位置に大きく出すとき、テロップにかからないように）
- `rain`：雨の線（`region`・`count`・`speed`・`alpha`）。`text`：文字（`pos`＝中心・`size`・`font`＝`g` ゴシック／`m` 明朝・`stroke`（縁取りの太さ、既定3）・`color`・`opacity`）。小さい注記のほか、背景の大きな「？」（`{"text": "？", "font": "m", "size": 1100, "opacity": 0.3, "stroke": 0}`）にも使う
- 同じ人物を途中で大きく寄せる（パンチイン）：役者を2人にして、1人目に `out: {at, how: "cut"}`、2人目に同じ `at` で `in: {how: "pop"}` と大きい `place`

置き場所の目安（縦・実際の制作で決めた型。`layout_overrides: {"telop_block_y": 1150}` と組み合わせる）：図があるとき＝図のすぐ下に顔 `{"x": 540, "y": 690, "scale": 1.5}`（あご y≈995、2段のテロップは y≈1025 から＝胸から下にだけ重なる）、図がないとき＝上に大きく `{"x": 540, "y": 330, "scale": 2.2}` ＋ `crop_bottom: 1020`。汗の絵は `{"x": 715, "y": 781, "scale": 0.59, "ref": "center"}`。3段のテロップは顔にかかるので2段にまとめる。

## そのほか

- `notes`：`[{"lines": [a, b], "text": "出典…"}]`。a 行目の頭から b 行目の終わりまで画面下（y≈1470）に出す（画像）
- `backgrounds`：`[{"id", "from", "to", "label", "motion": "in"/"out"}]`。背景の仮（ゆっくり寄る／引く）。`image`（絵・写真。画面いっぱいに切って `dim`（既定 0.5）の明るさに、`tint: "night"` で夜の色）か `plain: true`（暗い無地・仮の文字なし）を足すと、そのまま使える背景になる（`label` は素材リストに差し替え候補として残る）
- `backgrounds` の `anim: true`：作業フォルダの `media_anim/BG_{id}_動き.mov`（その区間と同じフレーム数）があれば、静止画の代わりにそれを V1 に置く（ないか長さが違えば静止画のまま・注意を出す）。**なめらかなグラデーションの静止画は、10％寄せても動いて見えない**（NHK会長編 v1c でユーザー「背景の動きが全く無いのがさみしい」）。実例 `examples/nhk-chairman/premiere/v1/make_bg_anim.py`（光の帯・回る放射・漂う粒・走査線・BGM の拍に合わせた脈・山場の集中線とフラッシュ・区間の頭のワイプ。設定は `bg_anim.json`）。流れ：build_all.py → make_bg_anim.py → build_premiere.py
- `end_card`：`{"style": "hold", "sender": …}`（推奨：締めのテロップ・背景をそのまま残し、発信者表示だけ下1/3に重ねる。最後の行の背景はエンドカードの終わりまで伸びる）か、従来の `lines` [{text か spans, font g/m, size, color}]＋`sender`（黒地の画像）
- `extra_notes`：素材リストの「権利・表現の注意」に足す行
- `readme_extra`：README の最後の「この版のメモ」に足す行（代わりに使える版、自分で用意する枠、判断待ちなど）
