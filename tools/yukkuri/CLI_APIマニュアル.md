# ゆっくりボイス CLI・APIマニュアル v2

更新：2026年9月28日（公開用 v2）。Mac 用の `yukkuri` コマンドと HTTP API です。音声生成はローカルの AquesTalkPlayer を呼び出し、従量課金 API は使いません。

コマンド本体はリポジトリの `tools/yukkuri` にあり、`install.sh` で `~/.local/bin/yukkuri` に入れます。AquesTalkPlayer は利用者が[公式サイト](https://www.a-quest.com/products/aquestalkplayer.html)から別途入手し、`/Applications/AquesTalkPlayer.app` に配置してください。アプリ本体・インストーラーは同梱しません。用途に応じて公式の利用条件を確認してください。

AIから呼び出す場合は、[AI向けガイド](AIからの呼び出しガイド.md)を参照してください。`yukkuri describe` で機能と入出力の説明をJSONとして取得できます。

## 1. 話速を指定する

```bash
yukkuri say --text '井上樹彦会長について、音声を作ります。' \
  --voice marisa --speed 180 --trim --reading 井上樹彦=いのうえたつひこ -o voice.wav
```

`--speed` は50〜300の整数。通常のれいむ・まりさは100、速めは170〜190が目安です。エンジンの話速パラメーターを変更し、音程設定は引き継ぎます。出力後の倍速加工ではありません。180は厳密に1.8倍の尺になる指定ではなく、句読点などで実際の秒数は変わります。

最初の案件の同一文章での実測（WAV に含まれる前後の余白込み。上の NHK 会長の例文を測った値ではありません）：

| 話速 | れいむ | まりさ |
|---|---:|---:|
| 100 | 4.647秒 | 4.647秒 |
| 170 | 2.778秒 | 2.778秒 |
| 180 | 2.661秒 | 2.661秒 |
| 190 | 2.455秒 | 2.455秒 |

話速を省略すると選択プリセットの設定を使います。「こいし」「さとり」は、もともとの話速・音程設定がれいむと異なります。

### 声の指定

| `--voice` | 日本語名・内容 |
|---|---|
| `reimu` / `れいむ` | れいむ |
| `marisa` / `まりさ` | まりさ |
| `koishi` / `こいし` | こいし |
| `satori` / `さとり` | さとり |
| `reimu-fast` / `れいむ速` | れいむ・話速180 |
| `marisa-fast` / `まりさ速` | まりさ・話速180 |

`yukkuri voices` で一覧表示できます。4声と速めの別名は実音声で検証済みです。速めの別名に `--speed 190` を付けると190を優先します。

自作プリセットやアプリのその他の声も使えます。

```bash
yukkuri say -t 'こんにちは。' --preset 'AquesTalk10 F1' --speed 180 -o other.wav
```

`--preset` は `--voice` より優先します。話速以外の設定は元プリセットを引き継ぎます。GUI のプリセット構成は利用者の設定に従います。速度指定時は元プリセットを上書きせず、`__yukkuri_`で始まる速度別プリセットを自動作成します。GUIで元プリセットを変更した場合は保存後にCLIを使ってください。

## 2. 台本からまとめて生成する

```bash
yukkuri batch 台本.tsv --outdir 音声/ --speed 180 --trim --reading-dict 読み辞書.json
```

TSVはタブ区切り・UTF-8です。番号・声・セリフの3列、任意で4列目に速度を指定します。以下の列間はタブです。

```tsv
番号	声	セリフ	速度
01	まりさ	井上樹彦会長について、音声を作ります。	180
02	れいむ	セリフごとに速さを変えられます。	170
03	まりさ速	前後の無音を取り除きます。	
```

見出しは省略しても使えます。英語の `id / voice / text / speed` も使用できます。番号は `1`・`01`・`L01`などを受け付け、出力は `L01` にそろえます。4列目が空ならコマンドの `--speed`、それもなければ声のプリセット設定を使います。台本の声は上の一覧から指定します。

生成するもの：

```text
音声/
  L01_まりさ.wav
  L02_れいむ.wav
  L03_まりさ速.wav
  manifest.json
```

`manifest.json` には、セリフ、読み置換後の文章、声、話速、ファイル名、実際の秒数、ファイルの検証値、生成状況を保存します。秒数は無音カット後のWAVから測ります。`items` が各セリフ、`total_duration_seconds` が生成済み音声の合計です。動画上のセリフ間の間隔は含みません。

1行生成するごとに一覧を保存します。エラーになったらその行で停止し、生成済みの音声を残します。台本の失敗行を直して、次で再開できます。

```bash
yukkuri batch 台本.tsv --outdir 音声/ --speed 180 --trim \
  --reading-dict 読み辞書.json --resume
```

`--resume` は台本・設定・音声の検証値が一致する完了行を再利用します。既存の完了行を変更した場合は別の出力先を使うか、意図的な再生成として `--force` を指定してください。`--force` と `--resume` は併用できません。番号の重複や不正な声は、生成前に検出します。

[試せる台本](examples/台本.tsv)・[読み辞書JSON](examples/読み辞書.json)・[読み辞書TSV](examples/読み辞書.tsv)を用意しました。生成後の秒数は出力先の `manifest.json` を参照してください。

## 3. 前後の無音をカットする

`say`・`request`・`batch` に `--trim` を付けます。

```bash
yukkuri say -t 'こんにちは。' --speed 180 --trim -o trimmed.wav
```

先頭と末尾の小さい信号（基準−60dBFS）を無音として切り、音の端を守るため10ミリ秒ずつ余白を残します。文章中の間や句読点のポーズは切りません。完全な無音だけの出力はエラーにします。必要に応じて、最終的な聞こえ方は試聴して確認してください。

## 4. 読みを確認する

```bash
yukkuri kana --text '井上樹彦会長' --reading 井上樹彦=いのうえたつひこ
# 参考読みを表示（会長の長音表記は辞書・解析器に依存）
```

**これは利用者の Mac の MeCab/IPADICによる参考読みです。AquesTalk内蔵辞書の解析結果そのものではなく、両者の読みが違う場合があります。** 通常表示ではこの注意を標準エラー出力に出します。

```bash
yukkuri kana --text '井上樹彦会長' --reading 井上樹彦=いのうえたつひこ --json
```

JSONには、読み全体、語ごとの読み、読み不明の語、置換後の文章を返します。`engine` は `MeCab/IPADIC`、`matches_aquestalk_analysis` は `false` です。

### 確認した読みで固定して生成する

参考読みを確認・修正した後、`--phonetic` で `#>`付きの音声記号列を保存します。このファイルから生成すると、AquesTalkの漢字変換に読みを任せず、指定した音声記号列を読み上げます。

```bash
yukkuri kana -t '井上樹彦会長' --reading 井上樹彦=いのうえたつひこ --phonetic > 読み固定.txt
# 読み固定.txt は #> で始まる音声記号列。出力内容を確認して使う

yukkuri say --file 読み固定.txt --voice marisa --speed 180 --trim -o fixed.wav
```

この方法はアクセントを推定しない棒読み向けです。未知の英字・記号などがあれば、仮名の `--reading` 指定で解決してから実行してください。音声記号列（`#>`で始まる入力）に対して再度 `--reading` を適用することはできません。

## 5. 読みを指定する

```bash
yukkuri say -t '井上樹彦会長について、重複を確認します。' \
  --reading 井上樹彦=いのうえたつひこ --reading 重複=ちょうふく --speed 180 -o reading.wav
```

`--reading` は繰り返し指定できます。生成前に該当箇所をカタカナの読みに置き換えます。台本の字幕用の漢字は元ファイルに残ります。読みには、ひらがな・カタカナ・長音記号を使用します。

JSON辞書の例：

```json
{"井上樹彦": "いのうえたつひこ", "重複": "ちょうふく"}
```

または2列のTSV（見出しは任意）：

```tsv
表記	読み
井上樹彦	いのうえたつひこ
重複	ちょうふく
```

```bash
yukkuri say --file 原稿.txt --reading-dict 読み辞書.json -o reading_file.wav
yukkuri kana -t '井上樹彦会長' --reading-dict 読み辞書.json
```

同じ表記はコマンドの `--reading` が辞書より優先します。長い表記を優先して一度だけ置換します。「井上樹彦会長」と「井上樹彦」を両方登録すれば、井上樹彦会長の指定を優先します。単語境界ではなく文字列一致なので、必要に応じて氏名全体を指定してください。この辞書は呼び出しごとの指定で、AquesTalkのGUI辞書そのものは変更しません。

## ファイル・標準入力・保存

```bash
yukkuri say --file '原稿.txt' --voice marisa --speed 180 -o '音声/001.wav'
printf '%s' 'こんにちは。' | yukkuri say --file - --trim -o '音声/002.wav'
```

1回4000文字以内、ファイルはUTF-8です。出力は48kHz・16bit・モノラルWAV。親フォルダは自動作成します。既存ファイルを上書きする場合だけ `--force` を指定します。成功時は出力先・秒数などのJSONと終了コード0、失敗時は標準エラー出力と0以外の終了コードを返します。

## HTTP API

`yukkuri start` で起動すると `http://127.0.0.1:8767` で待ち受けます。実行中の Mac からだけ接続できます。再起動後はもう一度 `yukkuri start` を実行してください。

```bash
yukkuri start
yukkuri status
yukkuri stop
# 手前で起動して使う場合。停止はControl+C。
yukkuri serve
```

すべてのAPIにBearerトークンが必要です。`yukkuri token` で取得できます。トークンは共有しないでください。APIは原稿やトークンをログに出しません。

```bash
curl --fail --silent --show-error http://127.0.0.1:8767/synthesize \
  -H "Authorization: Bearer $(yukkuri token)" \
  -H 'Content-Type: application/json' \
  --data '{"text":"井上樹彦会長","voice":"marisa","speed":180,"trim":true,"readings":{"井上樹彦":"いのうえたつひこ"}}' \
  --output api_output.wav
```

レスポンスは `audio/wav` の音声本体です。curlは保存先を上書きするので、新しい名前を指定してください。

| 入力項目 | 内容 |
|---|---|
| `text` | 必須。4000文字以内 |
| `voice` | 省略時reimu。上記の声一覧 |
| `preset` | 任意のアプリプリセット名。voiceより優先 |
| `speed` | 50〜300の整数。省略時はプリセット設定 |
| `trim` | true / false。省略時false |
| `readings` | 表記と読みのJSONオブジェクト |

API経由のCLIでも同じオプションを使用できます。

```bash
yukkuri request -t '井上樹彦会長' -v marisa --speed 180 --trim --reading 井上樹彦=いのうえたつひこ -o request.wav
```

| メソッド・パス | 結果 |
|---|---|
| `GET /health` | サービス名・バージョン・エンジン有無・ポート |
| `GET /voices` | 声一覧 |
| `POST /synthesize` | WAV本体 |
| `POST /kana` | 参考読みJSON。本文にtextとreadingsを指定 |
| `POST /shutdown` | 停止。本文は `{}`。通常は `yukkuri stop` を使用 |

TSVバッチはローカルCLI機能です。HTTPから複数行を処理する場合は `/synthesize` を順番に呼んでください。HTTPにファイルパスや保存先を渡す機能はありません。

JSON本文は32768バイトまでです。認証エラー401、Origin付きブラウザリクエスト403、入力エラー400、大きすぎる本文413、JSON以外415、エンジン・解析失敗422、別のAPI生成が進行中なら503を返します。503では処理完了後に再送します。CORSは設定していません。

`start / serve / status / stop / request` は `--port` で別ポートを指定できます。接続時・停止時にも同じ番号を指定します。音声エンジンの処理はポートにかかわらず順番に実行します。

## Pythonから直接使う

```python
import sys
from pathlib import Path
# リポジトリ直下から実行
sys.path.insert(0, str(Path('tools/yukkuri').resolve()))
from yukkuri import synthesize

wav = synthesize('井上樹彦会長', voice='marisa', speed=180,
                 trim=True, readings={'井上樹彦': 'いのうえたつひこ'})
with open('python_output.wav', 'xb') as f:
    f.write(wav)
```

HTTPから使う場合は、上記JSONをBearer認証付きで送信し、レスポンス本体を保存します。外部SDKは不要です。

## 構成・保守

- 登録コマンド：`~/.local/bin/yukkuri`
- 実装：`tools/yukkuri/yukkuri.py` と `tools/yukkuri/features.py`
- APIトークンとログ：`tools/yukkuri/.runtime/token`、`tools/yukkuri/.runtime/server.log`
- 初回速度設定前の自動バックアップ：`tools/yukkuri/.runtime/params.before-speed.json`

速度別設定はユーザーの `~/Library/Application Support/AquesTalkPlayer/params.json` に追加します。元の声の設定やアプリ本体は変更しません。AquesTalkPlayer更新などで保存形式が変わった場合は、動作を再確認してください。

コマンドはこのフォルダの絶対パスを参照しているため、フォルダ移動時は `~/.local/bin/yukkuri` の参照先を更新します。ログイン時の自動起動は設定していません。削除する場合は、API停止後に登録コマンドと `tools/yukkuri` フォルダを削除できます。`.runtime`には認証情報があるため、外部へ共有しないでください。

読み解析は既存の `/opt/homebrew/bin/mecab` とIPADICを使用します。AquesTalk内蔵のAqKanji2Koeを別アプリから正確に呼ぶための開発キーは取得・抽出していません。そのためkanaの参考読みと内蔵解析結果は区別しています。

[画面操作マニュアル](使い方マニュアル.md)／[公式Mac版マニュアル](https://www.a-quest.com/products/aquestalkplayer_mac_man.html)／[MeCab公式](https://taku910.github.io/mecab/)
