"""add_se.py の後に、読み込み用フォルダの 01_はじめに読む.md と 02_素材リスト を直す（効果音の節・トラック表・ビン名）。
使い方: python3 add_se_docs.py 設定.json（add_se.py と同じ設定）。何度流しても同じ結果（前に書いた効果音の節は書き直す）"""
import json, re, sys
from pathlib import Path

FPS = 30
LABEL = {'ペタッ': 'ペタッ', 'えっ': '間抜け3（えっ？）', 'ガーン': 'ショック2（ピアノでガーン）',
         'ハリセン': 'ビシッとツッコミ3（ハリセン）', '驚く': '驚く', 'キラッ': 'キラッ2'}


def tc(f):
    s = f / FPS
    return f'{int(s // 60)}:{s % 60:05.2f}'


def main(cfg_path):
    cfg = json.load(open(cfg_path, encoding='utf-8'))
    pkg = Path(cfg['pkg'])
    se = json.load(open(pkg / '確認用' / 'se_placement.json', encoding='utf-8'))
    xml_name = Path(se['xml']).name
    lab = lambda s: LABEL.get(s, s)
    rows = '\n'.join(f"| {tc(p['at'])} | {p['sound']}（{lab(p['sound'])}） | {p['why']} |" for p in se['places'])
    rows2 = '\n'.join(f"| {tc(p['at'])} | {lab(p['sound'])}（出典は設定の sounds と入手元を確認） | {p['why']} |" for p in se['places'])

    p = pkg / '01_はじめに読む.md'
    t = p.read_text(encoding='utf-8')
    t = re.sub(r'・07_BGM）', '・07_BGM・09_効果音）', t, count=1)
    t = t.replace('| A4 | 効果音（空。自分で入れる） |', '| A4 | 効果音（設定した音。音量は焼き込み済み） |')
    t = t.replace('- 効果音（A4）\n', '')
    t = t.replace('全体の流れ_目安_BGM入り.mp4', '全体の流れ_目安_BGM・効果音入り.mp4')
    t = re.sub(r'\n## 効果音（A4）\n.*?(?=\n## )', '', t, flags=re.S)
    sec = f"""
## 効果音（A4）

設定した効果音を、テロップ・図・人物の動きやセリフなどに合わせて {len(se['places'])} か所だけ入れた。音のいちばん大きいところが、ハンコが揺れて光るフレーム・聞き手の行の頭（2フレーム前）・イラストが動くフレームに来るように置いてある。WAV は `素材/09_効果音/`（音の種類ごとに1つ・音量は焼き込み済み）。置き場所の図は `確認用/効果音の配置.png`。

| 時刻 | 音 | 場面 |
|---|---|---|
{rows}

- 配置は設定ファイルの places に従う。声を妨げる箇所や BGM の強い一打と重なる箇所は減らす
- 減らすときは A4 のクリップを消すだけ。足すときはビン 09_効果音 から置く（元の音の場所は設定ファイルの sounds を参照）。効果音なしの XML は `確認用/効果音なし_{xml_name}`
- 効果音の出典・利用条件・クレジットは音源ごとに確認する。自作音と配布音源を区別する
- 書き出しの注意：声・BGM・効果音を合成したピークを確認し、必要ならマスタートラックにリミッター（ハードリミッター −1 dB など）を入れる
"""
    t = t.replace('\n## この版のメモ', sec + '\n## この版のメモ', 1)
    # この版のメモの同じ版の重複（spec の readme_extra と add_bgm_docs の memo）は、先に書かれた方だけ残す
    seen, out = set(), []
    for ln in t.split('\n'):
        m = re.match(r'- (v\d+\w*)：', ln)
        if m and m.group(1) in seen and 'BGM' in ln and '（A3）を足した版' not in ln and ln.count('：') == 1 and len(ln) < 120:
            continue
        if m:
            seen.add(m.group(1))
        out.append(ln)
    p.write_text('\n'.join(out), encoding='utf-8')

    p = pkg / '02_素材リスト（差し替え・出典）.md'
    s = p.read_text(encoding='utf-8')
    s = re.sub(r'\n## 効果音（A4）\n.*?(?=\n## )', '', s, flags=re.S)
    sec2 = f"""
## 効果音（A4）

| 時刻 | 音（出典） | 場面 |
|---|---|---|
{rows2}

配布音源は入手元の現行規約に従う。効果音ラボを使う場合は https://soundeffect-lab.info/agreement/ で利用・再配布・Content ID の条件を確認する。自作音は制作元を記録する。
"""
    s = s.replace('\n## 権利・表現の注意', sec2 + '\n## 権利・表現の注意', 1)
    line = '- 効果音：設定の sounds の各ファイルについて、出典・クレジット・再配布条件を確認する'
    if line not in s:
        s = s.rstrip('\n') + '\n' + line + '\n'
    p.write_text(s, encoding='utf-8')
    print(pkg.name, 'ok', len(se['places']), 'か所')


if __name__ == '__main__':
    main(sys.argv[1])
