---
name: yukkuri-voice
description: ゆっくりボイス（AquesTalkPlayer の れいむ・まりさ 等）で、台本やセリフから音声WAVを作る。Mac 用の `yukkuri` コマンド v2（ローカル実行・従量課金 API なし）を使い、台本MD → TSV → 一括生成（エンジンの話速・前後の無音カット・読み辞書）→ Whisper で聞き取り確認 → 通しの確認用WAV までを1コマンドで行う。使用場面 (1) ショート・解説動画のナレーションをゆっくりの声で作る、(2) 1行だけ作り直す、(3) 読み間違いを直す（読み辞書・音声記号列）、(4) 声の速さを決める、(5) 別アプリからローカルHTTP APIで呼ぶ。トリガー "ゆっくりボイス", "ゆっくり音声", "ゆっくりで読み上げ", "ゆっくり解説の声", "れいむ", "まりさ", "AquesTalk", "yukkuri", "/yukkuri-voice"
---

# ゆっくりボイス生成スキル

台本（Markdown）から、ゆっくりの声のWAVを行ごとに作り、聞き取りまで確認して渡すためのスキル。本体はリポジトリの `tools/yukkuri` にある `yukkuri` コマンド（v2・2026-09-26）で、このスキルはその使い方と補助スクリプト `scripts/yk.py` をまとめたもの。

## 0. 最初に読む4行

1. **ローカルで完結**（AquesTalkPlayer・MeCab・mlx-whisper）。従量課金APIは使わないので、コストの事前承認は要らない。
2. **台本を検討している段階では音声化しない**。台本が確定して「音声を作って」と言われてから使う。
3. **上書きしない。** 出力先は毎回新しいフォルダにする。`yk.py make` は中身のあるフォルダを拒否する。
4. **入手と利用条件**：AquesTalkPlayer は利用者が[公式サイト](https://www.a-quest.com/products/aquestalkplayer.html)から入手し、`/Applications/AquesTalkPlayer.app` に配置する。アプリ本体・インストーラーは同梱しない。非営利の個人利用、広告収益化、業務利用など、用途に応じて現行のライセンス条件を確認する。

## 1. 置き場所

| もの | 場所 |
|---|---|
| コマンド | リポジトリの `tools/yukkuri`（`install.sh` で `~/.local/bin/yukkuri` に入れる） |
| 補助スクリプト | `skills/yukkuri-voice/scripts/yk.py` |
| 正本マニュアル（v2） | `tools/yukkuri/CLI_APIマニュアル.md`（コマンドの細部はここが正） |
| 状態確認 | `yukkuri status` → `"version": "2.0", "engine_available": true` |

`say`・`batch`・`kana` はローカルで動き、HTTP APIは要らない。API（`http://127.0.0.1:8767`）は `request` と外部アプリ用で、Macを再起動した後は `yukkuri start` で起動する。

## 2. 標準の流れ：台本からまとめて作る

リポジトリ直下から実行する。読み辞書は `tools/yukkuri/examples/読み辞書.json` を基に、台本の固有名詞に合わせる。

```bash
python3 skills/yukkuri-voice/scripts/yk.py make examples/nhk-chairman/台本_v2b_NHK会長編.md \
  --outdir examples/nhk-chairman/音声/v2 --speed 180 --reading-dict tools/yukkuri/examples/読み辞書.json
```

これ1本で次の5つを順に実行する。

1. 台本の ``` の中にある「`番号 話者：セリフ`」の行を TSV にする。話者は「説明役→まりさ、聞き手→れいむ」に割り当てる。「まりさ」など声の名前を直接書いてもよく、ほかの話者は `--map 話者=こいし` で割り当てる。読む ``` は `--block N` で選べる。`.tsv` を渡した場合は変換せずにそのまま使う
2. 参考読み（MeCab）を出し、読めない語（英字など）がある行を表示する
3. `yukkuri batch --trim` で全行を生成し、`manifest.json` を書く
4. Whisper（large-v3-turbo・ローカル）で聞き取る。台本と聞き取り結果をそれぞれカタカナの読みに直して比べ、**1音でも違えば「要確認」** にして差（例：`ク→フ`）を表示する
5. 行間0.2秒で全行をつないだ、通しの確認用WAVを作る

| 出力（`--outdir` の中） | 中身 |
|---|---|
| `L01_まりさ.wav` … | 行ごとの音声（48kHz・16bit・モノラル。前後の無音はカット済み） |
| `manifest.json` | yukkuri v2 の一覧（セリフ・読み置換後の文・声・話速・秒数・検証値） |
| `台本.tsv` | 生成に使ったTSV（Markdownから作った場合） |
| `確認/参考読み.json`・`確認/聞き取り.json` | 参考読み、聞き取り結果と読みの差 |
| `確認/通し_行間0.2秒.wav` | 通しで聞く用の1本（`確認/` は毎回作り直してよい） |

**ユーザーへの報告**：`make` が出力する表（行・声・話速・秒・字/秒・読みの差・聞き取り）と、声だけの秒数、通しの秒数、要確認の行をそのまま見せる。聞いてもらうときは `確認/通し_行間0.2秒.wav` へのリンクを渡す。

個別に動かすとき：`yk.py tsv 台本.md -o 台本.tsv --speed 180`、`yk.py check 音声/v1`、`yk.py preview 音声/v1 --gap 0.3`

## 3. 話速の決め方（実測）

`--speed` はエンジンの話速パラメーターで、後から倍速にする加工ではない。最初の案件（16行・421字）で測った結果：

| 話速 | 声だけ | 字/秒 | 聞き取り |
|---|---:|---:|---|
| **180（既定）** | 45.56秒 | 9.2 | 16行すべて一致 |
| 185 | 43.71秒 | 9.6 | 1行で子音がつぶれた |
| 190 | 42.31秒 | 10.0 | 2行で子音がつぶれた |
| （旧）atempo 1.9倍の後加工 | 43.54秒 | 9.7 | 一致。ただし後加工なので v2 では使わない |

- 速めにするなら **180** を既定にする。190では子音がつぶれる行が出た
- もっと詰めたいときは 185・190 で作り、`check` で要確認になった行だけ `--line-speed 3=180` のように戻す
- 速い掛け合いの目安は約9〜9.5字/秒。字数は句読点・かぎかっこを除いて数える
- ffmpeg の atempo や rubberband で後から速める方法は使わない（実際の制作で一部の子音や固有名詞が崩れた）

## 4. 読みを直す

1. `make` の「参考読み」で読めない語を見る（英字は要注意。「PR」はピーアールと正しく読んだ）
2. 「聞き取り」の読みの差を見る。同音異義（委員／医院、会長／快調）は読みが同じなので差に出ない。差に出るのは実際の音の違い
3. 直し方（上から順に試す）
   - **読み辞書**：`{"井上樹彦": "いのうえたつひこ"}` のJSON、または「表記・読み」の2列TSVを作って `--reading-dict` に渡す。長い表記が優先され、置き換えは文字列の一致で行う（単語の区切りは見ない）。字幕用の漢字は台本に残る
   - **その場の指定**：`--reading 表記=よみ`（同じ表記なら辞書より優先。複数指定できる）
   - **音声記号列で固定**（最終手段・アクセントを付けない棒読み）：`yukkuri kana -t '…' --reading 井上樹彦=いのうえたつひこ --phonetic > 読み固定.txt` を作り、`yukkuri say --file 読み固定.txt -v marisa --speed 180 --trim -o L08_b.wav` で読ませる
- `yukkuri kana` は MeCab/IPADIC の参考読みで、エンジン内蔵の解析とは別物。最終的な確認は聞き取りとユーザーの耳で行う
- 数字（2024年度・25億円・2万円）はエンジンが正しく読む。MeCabは数字を読めないので、参考読みの「読めない語」からは外してある

## 5. 1行だけ作る・作り直す

- 1行だけ試す：`yukkuri say -t '…' -v marisa --speed 180 --trim --reading-dict 読み辞書.json -o 試し/L05_b.wav`（`-o` の既存ファイルは上書きしない）
- **台本を直したら、新しいフォルダで `make` し直す**（16行なら生成3秒、聞き取り15秒程度）
- `--resume` は、途中でエラーになって止まったときの続き専用。中身を変えた行は、ファイルが残っているとエラーで止まる（仕様）。読み辞書を変えると全行が変更扱いになる
- `--force` は同じフォルダで全行を作り直す（上書き）。ユーザーの了承があるときだけ使う

## 6. manifest.json（v2）の読み方

- `items[]`：`id`（"L01"）、`voice`、`text`、`prepared_text`（読み置換後）、`speed`、`file`、`duration_seconds`（無音カット後の秒数）、`sha256`、`status`
- `total_duration_seconds` は声だけの合計で、行間を含まない
- 動画の尺の見積もり：声だけ ＋ 行間×（行数−1）＋ 前後。NHK会長編の spec は、開始0.1秒・行間0.2秒・末尾0.3秒・エンドカード2.5秒

## 7. NHK会長編サンプルで使うとき

- 台本は `examples/nhk-chairman/台本_v2b_NHK会長編.md`。出力は `examples/nhk-chairman/音声/v2/` など未使用の版にする。
- `skills/premiere-short-xml/assets/example_spec.json` を基にした設定の `audio.manifest` を新しい音声の `manifest.json` に向け、`title` も版を上げる。パスは spec の場所からの相対。
- `skills/premiere-short-xml/scripts/build_all.py --spec 設定.json --out 新しい作業フォルダ` で、図の動き・XML を作り直す。背景動画を別途作る場合は Premiere スキルの手順も参照する。
- テロップの時刻は `build_premiere.py` が実測し、`anchor_times.json` にためる（§10）。音声が変わるとフレーム指定の効果音も再確認する。
- `build_premiere.py` は `media/` を消して作り直し、XML も上書きする。Premiere に読み込み済みのフォルダや別セッションが使用中のフォルダを避け、新しい版のフォルダを使う。

## 8. そのほかの入口

- 声の一覧：`yukkuri voices`（れいむ・まりさ・こいし・さとり・れいむ速・まりさ速）。アプリのほかのプリセットは `--preset '名前'`
- HTTP API：`POST /synthesize`（JSON：text・voice・speed・trim・readings → WAV本体）。Bearer トークンは `yukkuri token` で得られるが、トークンを会話やファイルに書き出さない。TSVバッチはCLIだけの機能
- Python から（リポジトリ直下、`from pathlib import Path` が必要）：`sys.path.insert(0, str(Path('tools/yukkuri').resolve()))` の後に `from yukkuri import synthesize`

## 9. うまくいかないとき

| 症状 | 対処 |
|---|---|
| `manifest.jsonが既にあります` | 新しいフォルダを指定する（続きから作るなら `--resume`） |
| `既存音声と台本・設定が一致しません` | 行か読み辞書を変えた。新しいフォルダで作り直す |
| `engine_available: false` | AquesTalkPlayer が見つからない。`/Applications/AquesTalkPlayer.app` を確認する |
| API が 503 を返す | 別の生成が進行中。終わってから送り直す |
| 声の設定が変わらない | GUIでプリセットを変えたら、保存してからCLIを使う。`__yukkuri_` で始まるプリセットは速度指定用に自動で作られたもの（消さない） |
| Whisper の結果がおかしい | `mlx_whisper` のCLIに複数のファイルを渡すと、出力が1つの名前に上書きされる。`yk.py` はモデルを1回だけ読み込んで順に処理し、失敗したら1ファイルずつ名前を付けて実行する |

## 10. 行の途中の時刻を知りたいとき（テロップ合わせ）

- 行の中のある語が何秒目に読まれるかは、**その手前までを同じ声・速さで読ませた長さ**（`--trim` 付き）で測れる。エンジンは同じ入力に同じ音を返すので、文字数の比例計算より正確
- 最初の案件での実測：文字数の比例による時刻は、この方法と比べて平均4.2フレーム、最大12フレーム（0.4秒）ずれた。Whisper の単語時刻とは平均3フレームの差で一致した
- 測った時刻は「手前の部分を言い終わった瞬間」になる。読点のあとの語なら、間の分だけ少し早めに出る（テロップが先に出る側なので問題ない）
- 読み辞書を使った行は、manifest の `prepared_text`（読み置換後の文）の対応する位置までを読ませる。こうすると辞書を渡し直さなくても同じ読みになる
- 実装例：`skills/premiere-short-xml/scripts/build_premiere.py` の `measure_anchor_times()`（結果を `request_hash` と文字位置をキーにして `anchor_times.json` にためる）
