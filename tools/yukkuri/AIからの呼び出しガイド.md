# AIからゆっくり音声を生成する

利用者の Mac でローカルコマンドを実行できる AI向けの手順です。公式AquesTalkPlayerを使う既存のCLI・APIを利用します。独自の合成エンジンやMCPサーバーではありません。音声生成のためのクラウドAPIは使いません。

コマンド本体はリポジトリの `tools/yukkuri` にあり、`install.sh` で `~/.local/bin/yukkuri` に入れます。AquesTalkPlayer は利用者が[公式サイト](https://www.a-quest.com/products/aquestalkplayer.html)から別途入手し、`/Applications/AquesTalkPlayer.app` に配置してください。アプリ本体・インストーラーは同梱しません。用途に応じて公式の利用条件を確認してください。

## 最初に機能を取得する

```bash
~/.local/bin/yukkuri describe
```

声の一覧、速度の範囲、コマンド例、入出力の形式をJSONで返します。`describe` は音声生成やAPIサーバーの起動を行いません。通常はサーバー不要の `say` と `batch` を使ってください。

## AIに渡せる依頼文

> 利用者の Mac に入れた `~/.local/bin/yukkuri` を使って、台本から音声を作ってください。最初に `describe` で機能を確認してください。動画向けの指定がなければ話速180・前後の無音除去を提案値として使い、明示された声・速度を優先してください。複数行はUTF-8のTSVに保存し、`batch` で生成してください。成功時のJSONとmanifestから、出力の絶対パスと実際の秒数を報告してください。既存ファイルを勝手に上書きせず、途中失敗では完了行を残して原因を直し、同じ設定で `--resume` してください。読みが不明な固有名詞は推測を確定扱いせず、確定した読みを `--reading` または辞書で指定してください。`kana` は参考読みであり、音声エンジン内部の解析結果ではありません。

## 1件の生成をプログラムから呼ぶ

文章は標準入力で渡すと、引用符・改行・シェル特殊文字をそのまま扱えます。シェル文字列に文章を埋め込まず、引数の配列と `input` を使います。

```python
import json
import subprocess
from pathlib import Path

cli = str(Path.home() / '.local/bin/yukkuri')
output = Path('音声/L01_まりさ.wav').resolve()
result = subprocess.run(
    [cli, 'say', '--file', '-', '--voice', 'marisa',
     '--speed', '180', '--trim', '--reading', '井上樹彦=いのうえたつひこ',
     '--output', str(output)],
    input='井上樹彦会長について、音声を作ります。',
    text=True, capture_output=True,
)
if result.returncode != 0:
    raise RuntimeError(result.stderr.strip())
audio = json.loads(result.stdout)
print(audio['output'], audio['duration_seconds'])
```

終了コード0の場合、標準出力はJSONです。`output` は保存先の絶対パス、`duration_seconds` は完成したWAVの秒数です。`sample_rate`、`channels`、`bits`、`bytes` も含みます。音声は48kHz・モノラル・16bit PCMのWAVです。

エラーや進捗は標準エラー出力に出ます。失敗時のメッセージはJSONではありません。終了コード1は処理失敗、2は引数の使い方の誤り、130は中断です。成功前提で標準出力をJSON解析せず、終了コードを先に確認してください。

## 台本をまとめて生成する

台本はタブ区切りで保存します。見出しは `番号・声・セリフ`、任意の4列目は `速度` です。[台本の見本](examples/台本.tsv)を使えます。

```bash
~/.local/bin/yukkuri batch 台本.tsv \
  --outdir 音声/ --speed 180 --trim --reading-dict 読み辞書.json
```

標準出力のJSONには `manifest`、`count`、`total_duration_seconds` が入ります。`manifest` のファイルを開くと、各行の `file`、`status`、`duration_seconds` を取得できます。`file` はmanifest内の `outdir` からの相対パスです。

失敗時もmanifestを保存します。同じ台本・設定の完了行は `--resume` で再利用できます。完了行を変更する場合は新しい出力フォルダを使ってください。音声エンジンは順番に処理するので、並列に大量の生成要求を送らないでください。

## 読みの扱い

- 確定した読みを渡す：`--reading 井上樹彦=いのうえたつひこ`。複数回指定できます。
- 辞書を渡す：`--reading-dict 読み辞書.json`。JSONオブジェクトまたは2列のTSVです。
- 参考読みを取得：`yukkuri kana --file - --json`。文章は標準入力へ渡します。
- 読みを固定する：`kana --phonetic` の出力を確認し、`say --file -` の標準入力へ渡します。

`kana` の `matches_aquestalk_analysis` はfalseです。読み解析にはMeCab/IPADICを使うため、元の漢字文章をAquesTalkに渡した場合の読みを保証しません。固定読み入力に対して、さらに読み置換を重ねることはできません。

## HTTPで呼び出す場合

既存のローカルAPIも使えます。`yukkuri start` で起動し、`yukkuri token` で得たトークンをBearer認証へ渡します。トークンを会話・ログ・成果物へ記録しないでください。

`POST /synthesize` は `text`、`voice`、`speed`、`trim`、`readings` などを受け取り、WAVのバイナリを返します。CLIのような保存先JSONではないので、呼び出し元がファイルへ保存します。HTTPでの台本一括生成は未実装です。詳細は[CLI・APIマニュアル](CLI_APIマニュアル.md)を参照してください。

このAPIはMac内の `127.0.0.1:8767` 専用です。別の端末やクラウドで動くAIから直接呼び出せる設定にはしていません。AI側にこのMacでのコマンド実行手段があれば、CLIで利用できます。
