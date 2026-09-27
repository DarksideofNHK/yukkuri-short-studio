"""BGM を足した読み込み用フォルダの 01_はじめに読む.md と 02_素材リスト を直す。
使い方: python3 add_bgm_docs.py 設定.json（add_bgm.py と同じ設定）"""
import json, re, sys
from pathlib import Path

FPS = 30


def tc(f):
    s = f / FPS
    return f'{int(s // 60)}:{s % 60:05.2f}'


SOURCES = {
    '魔王魂': ('魔王魂（森田交一）', 'https://maou.audio/rule/', '著作表記が必須（概要欄に「BGM：魔王魂」）'),
    '甘茶': ('甘茶の音楽工房', 'https://amachamusic.chagasi.com/terms.html', '表記は任意'),
    'ElevenLabs': ('ElevenLabs Music（生成した曲）', 'https://elevenlabs.io/terms-of-use', '表記は任意。利用条件は契約プランの規約に従う（音源ファイルは再配布しない）'),
    'OpenTracks': ('OpenTracks（旧DOVA-SYNDROME）', 'https://opentracks.com/help/articles/license/', '用途・表記・再配布条件を配布元の現行規約で確認する。題材固有の注意はスキルの design_rules.md の付録を参照'),
}


def src_of(path, clip=None):
    """曲の出典。設定のクリップに "source"（SOURCES のキー）があればそれ。なければファイルの場所・名前から。
    分からないときは魔王魂にせず止める（NHK会長編 v2 で、ElevenLabs で作った曲が魔王魂と書かれた。2026-09-28）"""
    if clip and clip.get('source'):
        return clip['source']
    for k in SOURCES:
        if f'/{k}' in path or Path(path).name.startswith(k) or k.lower() in Path(path).name.lower():
            return k
    raise SystemExit(f'曲の出典が分からない：{path}。設定のクリップに "source": "魔王魂"／"甘茶"／"ElevenLabs"／"OpenTracks" を書く')


def main(cfg_path):
    cfg = json.load(open(cfg_path))
    dst = Path(cfg['dst'])
    pl = json.load(open(dst / '確認用' / 'bgm_placement.json'))
    new_xml = Path(pl['xml']).name
    new_name = new_xml.replace('00_これを読み込む_', '').replace('.xml', '')
    readme = dst / '01_はじめに読む.md'
    t = readme.read_text(encoding='utf-8')
    old_xml = re.search(r'`(00_これを読み込む_[^`]+\.xml)`', t).group(1)
    old_name = old_xml.replace('00_これを読み込む_', '').replace('.xml', '')
    t = t.replace(old_xml, new_xml)
    t = re.sub(r'^# .*?（Premiere 読み込み用）', f'# {new_name}（Premiere 読み込み用）', t, count=1, flags=re.M)
    t = t.replace(f'シーケンス「{old_name}」', f'シーケンス「{new_name}」')
    t = t.replace('・08_イラスト（人物など））', '・08_イラスト（人物など）・07_BGM）')
    t = re.sub(r'\| A3・A4 \| BGM・効果音（空。自分で入れる） \|',
               '| A3 | BGM（設定した曲。音量は焼き込み済み） |\n| A4 | 効果音（空。自分で入れる） |', t)
    t = t.replace('- BGM（A3）・効果音（A4）', '- 効果音（A4）')
    t = t.replace('全体の流れ_目安.mp4', '全体の流れ_目安_BGM入り.mp4')
    # BGM の節
    rows = []
    for c in pl['clips']:
        rows.append(f"| {c['name']} | {tc(c['start_f'])}〜{tc(c['end_f'])} | {c['file']} の {c['in_sec']:.2f} 秒から | "
                    f"{c['gain_db']:+.1f} dB（{c['out_lufs']} LUFS） |")
    marks = '\n'.join(f"| {tc(m['frame'])} | {m['text']} |" for m in pl['markers'])
    used = sorted({src_of(c['file'], c) for c in cfg['clips']})
    alts = cfg.get('alternates', [])
    alt_line = ''
    if alts:
        names = '・'.join(Path(a).stem.replace('BGM候補_', '').replace('_音量調整済み', '') for a in alts)
        alt_line = (f"- 差し替え候補（同じ音量にそろえた{len(alts)}曲：{names}）がビン 07_BGM に入っている"
                    f"（ファイルは `{Path(alts[0]).parent}`）。A3 の本編の曲と入れ替えるときは、そのまま置けばだいたい同じ大きさで鳴る")
    credit = [f'- {SOURCES[k][0]}：{SOURCES[k][2]}（規約 {SOURCES[k][1]}）' for k in used]
    handles = all(c.get('handles') for c in pl['clips'])
    intro = ('**曲の頭から終わりまでが入っていて（音量は焼き込み済み）、タイムラインには使う区間だけを置いてある**ので、'
             if handles else '**使う区間だけを切り出して、音量・フェードを焼き込んである**ので、')
    ending = cfg.get('ending_note') or ('- 締めの曲・開始位置・フェードは設定ファイルの clips に従う。'
                                        '個別の演出説明は ending_note で指定できる。')
    stretch = ('- **長さ・位置の調整**：クリップの端をドラッグすれば、曲の前後に伸ばしたり縮めたりできる（曲はまるごと入っている）。'
               'スリップツール（Y）で曲のどこを使うかもずらせる。入り・終わりのフェードはオーディオトランジション（コンスタントパワー）なので、'
               '端を動かしたらトランジションも付け直す（Ctrl/Cmd＋Shift＋D）\n'
               '- 音量を変えるときは、クリップを選んで「オーディオゲイン」（G キー）で全体を上げ下げする。設定した音量の持ち上げは曲の中の位置で WAV に焼き込んである'
               if handles else
               '- 曲を長く残したいときは、本編の曲のクリップの右端を伸ばす（切り出した区間の外は入っていないので、伸ばせるのは数フレームだけ。長く残すなら作り直す）\n'
               '- 音量を変えるときは、クリップを選んで「オーディオゲイン」（G キー）で全体を上げ下げする。形（フェード・設定した音量の持ち上げ）は WAV に焼き込んである')
    sec = f"""
## BGM（A3）

曲は `素材/07_BGM/` の WAV（モノラル 48kHz）。{intro}置いたままでナレーション（{pl['narration_lufs']} LUFS）との音量差は設定した target_rel・cap_rel に従う（ナレーション＋BGM で {pl['total_lufs']} LUFS）。波形を見て、曲の盛り上がりをナレーションの区切りに合わせた。置き方の図は `確認用/BGMの配置_波形.png`、音つきの流れは `確認用/全体の流れ_目安_BGM入り.mp4`。

| クリップ | 時刻 | 元の曲 | 音量 |
|---|---|---|---|
{chr(10).join(rows)}

合わせた位置（シーケンスマーカー「BGM」）：

| 時刻 | 中身 |
|---|---|
{marks}

{ending}
{stretch}
{alt_line}

クレジット・規約：

{chr(10).join(credit)}
"""
    t = t.replace('\n## この版のメモ', sec + '\n## この版のメモ', 1) if '\n## この版のメモ' in t else t.rstrip('\n') + '\n' + sec
    memo = cfg.get('memo') or f"{cfg['new_tag']}：{cfg['old_tag']} に BGM（A3）を足した版。映像・テロップ・ナレーションは {cfg['old_tag']} と同じ"
    if '## この版のメモ' in t:
        t = t.replace('\n## 作り直すとき', f"- {memo}\n\n## 作り直すとき", 1)
    else:
        t = t.rstrip('\n') + f"\n\n## この版のメモ\n\n- {memo}\n"
    readme.write_text(t, encoding='utf-8')

    lst = dst / '02_素材リスト（差し替え・出典）.md'
    s = lst.read_text(encoding='utf-8')
    brow = '\n'.join(f"| {c['name']} | {tc(c['start_f'])}〜{tc(c['end_f'])} | {SOURCES[src_of(c2['file'], c2)][0]}「{Path(c2['file']).stem}」 | "
                     f"{SOURCES[src_of(c2['file'], c2)][2]} |" for c, c2 in zip(pl['clips'], cfg['clips']))
    bsec = f"""
## BGM（A3）

| クリップ | 時刻 | 曲（出典） | 表記・規約 |
|---|---|---|---|
{brow}

"""
    s = s.replace('\n## 権利・表現の注意', bsec + '## 権利・表現の注意', 1)
    extra = ['- BGM：魔王魂の曲を使っているので、概要欄に「BGM：魔王魂」を必ず入れる'] if '魔王魂' in used else []
    if 'ElevenLabs' in used:
        extra.append('- BGM：ElevenLabs Music で生成した曲。利用条件は契約プランの規約に従う。音源ファイル（素材/07_BGM の WAV を含む）は公開リポジトリなどで再配布しない')
    if 'OpenTracks' in used:
        extra.append('- BGM：OpenTracks の曲の利用条件・禁止用途・クレジットを公開前に現行規約で確認する。不明な点は提供元に確認する。題材固有の注意はスキルの design_rules.md の付録を参照')
    s = s.rstrip('\n') + '\n' + '\n'.join(extra) + '\n'
    lst.write_text(s, encoding='utf-8')
    print(dst.name, 'ok', used)


if __name__ == '__main__':
    main(sys.argv[1])
