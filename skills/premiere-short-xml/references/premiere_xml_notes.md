# Premiere Pro 2026（26.5.1）で確かめた FCP7 XML の癖

2026-09-26、最初の案件 で、ユーザーの Premiere に読み込んでもらい、自動保存（.prproj）を読んで確かめた。「未確認」は次に読み込んだときに `inspect_prproj.py` で確かめて、ここを直す。

## 確かめたこと

| 項目 | 結果 |
|---|---|
| 形式 | `<xmeml version="4">`。`<project>` の中に `<bin>`（マスタークリップ `ismasterclip`）とシーケンスを入れるとビンに分かれる。ビンなし（シーケンスだけ）でも読める |
| 静止画 | `in=0`。1080×1920 の全画面 PNG にしておくと「フレームサイズに合わせる」で縮まない。位置は画像の中で決める |
| キーフレーム | Basic Motion（`effectid basic`）のスケール、Opacity の不透明度。`<when>` はクリップの頭からのフレーム。読み込まれる |
| 無効のクリップ | `<enabled>FALSE</enabled>` で無効のまま入る（暗幕に使用） |
| マーカー | シーケンスの `<marker>` は名前・コメントつきで入る |
| パス | `file://localhost` ＋パーセントエンコード。絶対パスなのでフォルダを動かしたら作り直す |
| トラック名 | 読み込まれない。中身はクリップ名とビン名で見分ける |
| .prproj | 直接は作れない（XML を読み込んでもらう） |
| ProRes 4444 の透明 | `prores_ks -profile:v 4444 -pix_fmt yuva444p10le -vendor apl0 -alpha_bits 16` で透明のまま重なる |
| 文字クリップ | `generatoritem` の `Text` / `Outline Text` → エッセンシャルグラフィックスの文字レイヤー（`AE.ADBE Text`）。打ち替えできる（ユーザー確認） |
| 塗りの色 | `fontcolor` の RGB がそのまま入る |
| 縁取り | `Outline Text` の `linewidth`・`linecolor` が縁取りとして入る（数値は ×4、下記） |
| **文字サイズ** | **FCP の値 × 4 が Premiere の px**（1080×1920 で 120→480、110→440、縁取り 12→48）。「高さ÷480」と思われる。縦は text_scale=4.0 で割って書く |
| **フォント名** | 名前に空白があると壊れる（`Hiragino Mincho ProN W6` → `HiraginoMinchoProNW6W6`、ほかに `A Love of Thunder` → `Aloveofthunderder` の報告あり）。Premiere は PostScript 名で持つので、`HiraMinProN-W6` のように**空白のない PostScript 名**を書く |
| 位置（1行） | 1行の文字クリップは origin (0,0) で、文字の下端（ベースライン）が 960 −（サイズ/8 + 2）px（96px→946、104px→945、128px→942、480px→898）|
| origin | 縦 v で v × 高さ（1920）px 下がる（v=0.1 → +192px）。横は未確認 |
| 複数行 | 1行ずつ別のレイヤーに分けられ、行数だけで並べ直される（空行も1行と数える・行の間隔＝文字サイズ）。104px の2行は 825/929、3行は 744/848/952。行数の違うクリップを重ねると段がずれる → 1行1クリップにする |
| Basic Motion の center | 文字クリップ（generatoritem）には効かない（位置は 540, 960 のまま） |
| leading（行間） | 指定すると行の間隔が変わる（数値の対応は未確認）。1行1クリップにしたので使っていない |
| 縁取り | 12px・外側で入る。シャドウは FCP の Outline Text からは入らない（Premiere 上で足せる） |
| 字幕（SRT） | キャプションとして読めるが画面下に字幕の形で出る。テロップには向かない |

## 未確認

- 横 1920×1080 の text_scale（推定 2.25）と、1行の置き位置の式
- origin の横の対応

自動保存の読み方：`python3 scripts/inspect_prproj.py <プロジェクトのフォルダ> --grep 文字`。文字（⏎ が改行）・フォント名・数値（サイズ・縁取り）・位置が出る。

## 文字クリップの XML（1つ分）

```xml
<generatoritem id="gi-047"><name>L11-4 約25億円</name><duration>45</duration><rate>…</rate>
 <start>770</start><end>815</end><in>0</in><out>45</out><enabled>TRUE</enabled>
 <anamorphic>FALSE</anamorphic><alphatype>black</alphatype>
 <effect><name>Outline Text</name><effectid>Outline Text</effectid><effectcategory>Text</effectcategory>
  <effecttype>generator</effecttype><mediatype>video</mediatype>
  <parameter><parameterid>str</parameterid><name>Text</name><value>　&#13;約25億円</value></parameter>
  <parameter><parameterid>fontname</parameterid><name>Font</name><value>HiraMinProN-W6</value></parameter>
  <parameter><parameterid>fontsize</parameterid>…<value>26</value></parameter>   ← 104px ÷ 4
  <parameter><parameterid>fontstyle</parameterid>…<value>1</value></parameter>
  <parameter><parameterid>fontalign</parameterid>…<value>2</value></parameter>   ← 中央
  <parameter><parameterid>fontcolor</parameterid>…<value><alpha>255</alpha><red>255</red><green>230</green><blue>0</blue></value></parameter>
  <parameter><parameterid>origin</parameterid>…<value><horiz>0</horiz><vert>0</vert></value></parameter>
  <parameter><parameterid>linewidth</parameterid>…<value>3</value></parameter>   ← 12px ÷ 4
  <parameter><parameterid>linesoftness</parameterid>…<value>0</value></parameter>
  <parameter><parameterid>linecolor</parameterid>…<value><alpha>255</alpha><red>0</red><green>0</green><blue>0</blue></value></parameter>
  <parameter><parameterid>textopacity</parameterid>…<value>100</value></parameter>
 </effect>
 <filter>… Basic Motion scale のキーフレーム …</filter>
 <sourcetrack><mediatype>video</mediatype></sourcetrack></generatoritem>
```

XML では生の CR は読み込み時に LF に変わるので、改行は必ず `&#13;` と書く（build_premiere.py の `LINE_BREAK`）。

## 音声（A3 の BGM）：曲まるごとの WAV と XML のオーディオトランジション（2026-09-27 確認）

実際の制作で確認（自動保存を inspect_sequence.py で読んだ）：

- 曲の頭から終わりまでの WAV を `<file>` に置き、`<clipitem>` の `<in>`/`<out>` で使う区間だけを置く形は、そのとおりに読み込まれる。クリップの端をドラッグして伸ばせる（ユーザー確認「素晴らしい」）
- `<transitionitem>`（`Cross Fade (+3dB)`・`KGAudioTransCrossFade3dB`、`<alignment>` start / end / center）はオーディオトランジションとして読み込まれ、Premiere では **「カスタムフェード」** という名前になる。クリップの頭（start）・終わり（end）・2つのクリップのつなぎ目（center）のどれも入った
- 同じトラックで2つのクリップが重なる置き方は書かない（あとのクリップで上書きされる）。つなぐときは前の end と後の start をそろえ、center のトランジションを1つ置く

## 映像のトランジションと動き（2026-09-27 検証_XMLトランジション_v1 で確認）

文字・画像のキーフレームと各トランジションを組み合わせた検証用 XML を、Premiere 2026 に読み込んで目で確かめた。案件専用の検証ファイルは同梱しない。

| XML に書いたもの | 結果 |
|---|---|
| 文字クリップ（Outline Text）の Basic Motion `rotation`＋`scale` のキーフレーム | 読み込まれる（くるっと回って出る）。spec の `motion: "spin"` |
| 画像クリップの `rotation`＋`scale` のキーフレーム | 読み込まれる |
| 画像クリップの `center`（位置）のキーフレーム（horiz −0.3→0.3） | 動いた（目視）。何 px に当たるかは未測定 |
| `<transitionitem>` Cross Dissolve（つなぎ目 center／文字の頭 start） | 「クロスディゾルブ」として読み込まれる。spec の `dissolve_in` |
| Dip to Color Dissolve（黒） | 「カラーブレンドトランジションに相当するものがありません。代わりに暗転が使用されます」＝暗転（黒）になる。黒なら同じ見た目 |
| Premiere のスピンモーション（`AE.AE_Impact_Spin`）・ポップモーション（`AE.AE_Impact_Pop`） | **読み込めない**。「トランジション <スピンモーション> は変換されません。代わりにクロスディゾルブが使用されます」。Premiere 独自（Impact）のトランジションは FCP7 XML では渡せない |

- 回る・跳ねる動きは、Basic Motion のキーフレームで作る（文字は `motion: "spin"`）か、イラストの動画（chars の `in.how: "spin"`）に作り込む。Premiere のスピンモーションそのものが欲しいときは、読み込み後にエフェクトパネルで「デフォルトトランジションとして設定」→ クリップを選んで Cmd＋D
- 未確認：前のクリップとすき間なく続く文字クリップの頭に start の Cross Dissolve を置いたとき（試しは前に空きがあった）
