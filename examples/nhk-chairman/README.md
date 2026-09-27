# サンプル：NHK会長は、誰が決めている？（縦ショート・42秒）

このスキル集で作った1本分の記録です。台本 → ファクトチェック → 音声 → 素材 → Premiere 用 XML → 動く背景 → BGM・効果音 → 点検、の順に進めました。作業の受け渡しは `tasks.json` と `tasks/<ID>/`（brief.md → 報告.md）、何が起きたかは `作業ログ.md` にあります。

## 入っているもの・入っていないもの

| もの | 場所 | 同梱 |
|---|---|---|
| 台本（v1 → ファクトチェック → v2 → 確定 v2b） | `台本_*.md` | ✅ |
| ファクト表と一次資料の抜粋（放送法・経営委員会の議事録） | `research/` | ✅ |
| 分担の記録（依頼書と報告） | `tasks.json`・`tasks/`・`作業ログ.md` | ✅ |
| spec.json を作るスクリプト・素材をそろえるスクリプト・動く背景 | `premiere/v1/` | ✅ |
| 図（12の席・3段の図・家・矢印・✗）とそれを描いたスクリプト | `図/v1/` | ✅（CC BY 4.0） |
| 自作の効果音（ピコッ9音・ブッ・どすん）と合成スクリプト | `音/v1/自作/` | ✅（CC BY 4.0） |
| BGM の構成案（ElevenLabs）・BGM と効果音の置き方の設定 | `音/v2/` | ✅（設定だけ） |
| 読み辞書 | `音声/読み辞書.json` | ✅ |
| 概要欄 | `公開/概要欄.md` | ✅ |
| ゆっくりボイスの音声 | `音声/v1b/` | ❌ 作り直す（`yukkuri-voice`） |
| BGM（生成した曲）・効果音ラボの音 | `音/v2/`・効果音フォルダ | ❌ 各自で用意 |
| 人物と建物の絵（Codex の JS Paint） | `絵/NHK_JS_Paint素材_v2/` | ✅（建物は CC BY 4.0。人物の似顔絵は確認用・再利用不可） |
| 完成版の動画（Premiere で書き出し・720p・音あり）と山場の GIF | `公開/demo/` | ✅（鑑賞用・再利用不可） |
| e-Gov の条文のスクショ | `スクショ/v1/` | ❌ `capture_egov.sh` で撮る |

## 作り直す手順

コマンドは、書いてあるフォルダで実行します（`S=~/.claude/skills/premiere-short-xml/scripts` とします）。

**1. 音声**（`examples/nhk-chairman` で）

```bash
python3 ~/.claude/skills/yukkuri-voice/scripts/yk.py make 台本_v2b_NHK会長編.md \
  --outdir 音声/v1b --speed 180 --reading-dict 音声/読み辞書.json
```

**2. 条文のスクショ**（`examples/nhk-chairman` で・browser-use が要る）

```bash
./capture_egov.sh     # 画面の大きさでマーカーの位置が変わったら、premiere/v1/make_spec.py の mark・box を直す
```

**3. 組み立て**（`examples/nhk-chairman/premiere/v1` で）

```bash
python3 prep_assets.py                        # 絵・図・背景・スクショを作業フォルダにそろえる
python3 make_spec.py && python3 $S/build_all.py --spec spec.json
python3 make_spec.py && python3 $S/build_all.py --spec spec.json   # 2回目：実測の時刻で席の点灯を計算し直す
```

**4. BGM**（任意・従量課金）：`音/v2/plan_v2.json` を ElevenLabs Music（music_v2）に渡して生成し、`音/v2/bgm_v2_b.mp3` に置く。サンプルでは seed を変えて2本作り、「ため→ドロップ」が狙いどおりの方を使った（曲の14.41秒のドロップを動画の405フレームに合わせるので `in_sec` 0.91）。別の曲を使うなら `音/v2/bgm_v2.json` と `premiere/v1/bg_anim.json` の曲と `in_sec` を直す。

**5. 動く背景と確認動画**（`examples/nhk-chairman/premiere/v1` で・BGM の拍に合わせるので 4 のあと）

```bash
python3 make_bg_anim.py
python3 $S/build_premiere.py --spec spec.json
python3 $S/preview_video.py --spec spec.json
python3 $S/export_package.py --spec spec.json --dest ../../Premiere読み込み用/_NHK会長編_v2_BGMなし --name NHK会長編
```

**6. BGM と効果音を足す**（**リポジトリの一番上のフォルダ**で。設定のパスはリポジトリの一番上からの相対）

`音/v2/se_v2.json` の `<効果音フォルダ>` を、効果音ラボの音を置いたフォルダに直してから：

```bash
python3 $S/add_bgm.py examples/nhk-chairman/音/v2/bgm_v2.json
python3 $S/add_bgm_docs.py examples/nhk-chairman/音/v2/bgm_v2.json
python3 $S/add_se.py examples/nhk-chairman/音/v2/se_v2.json
python3 $S/add_se_docs.py examples/nhk-chairman/音/v2/se_v2.json
```

できあがり：`examples/nhk-chairman/Premiere読み込み用/NHK会長編_v2/00_これを読み込む_NHK会長編_v2.xml`（Premiere の新規プロジェクトの保存場所をこのフォルダにして読み込む）。確認用の動画は同じフォルダの `確認用/`。

看板ボード：`./ボードを開く.command`（または `python3 ../../tools/studio/studio.py serve`）
