#!/usr/bin/env python3
"""作った素材一式から、Premiere に読み込むためのフォルダ（XML・素材・説明）だけを取り出す。

usage:
  python3 export_package.py --spec spec.json --dest <読み込み用フォルダ> [--out 作業フォルダ] [--name シーケンス名] [--force]

できるフォルダ:
  00_これを読み込む_{name}.xml        … Premiere の「ファイル→読み込み」で開く（素材はこのフォルダの中を指す）
  01_はじめに読む.md                  … 読み込み方・トラック・テロップの直し方・自分で入れるもの
  02_素材リスト（差し替え・出典）.md
  素材/01_ナレーション/ …             … Premiere のビンと同じ名前
  確認用/動きの確認_図・スクショ・グラフ.mp4
作業用のファイル（spec・timeline・測定のキャッシュ・途中の画像）は入れない。
既にあるフォルダには書かない（ユーザーが使っている素材を上書きしないため。上書きは --force）。
build_all.py の後に実行する。
"""
import argparse
import datetime
import json
import re
import shutil
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_premiere import TRACK_NAMES  # noqa: E402
from common import LAYOUTS, layout_of  # noqa: E402


KIND_JP = {'chart': 'グラフ', 'shot': 'スクショ', 'slot': '差し替え枠', 'quote': '引用'}


def pathurl(p):
    return 'file://localhost' + urllib.parse.quote(str(Path(p).resolve()))


def v2_label(it):
    if it['kind'] == 'chart':
        return it['chart'].get('title', '')
    return it.get('caption') or it.get('label') or ''


def nice(text, n=34):
    """ファイル名に使えない文字と空白を除く（（）は残す）"""
    return re.sub(r'[\\/:：*?"<>|\s　「」『』、。,]', '', text)[:n] or 'x'


def mmss(f, fps):
    s = f / fps
    return f'{int(s // 60)}:{s % 60:04.1f}'


def guide(spec, tl, name, xml_name, work):
    L = layout_of(spec)
    vt = sorted({c['track'] for c in tl['clips'] if c['track'].startswith('V')} | set(spec.get('empty_tracks', {})),
                key=lambda t: -int(t[1:]))
    bins = sorted({c['bin'] for c in tl['clips'] if c.get('bin')})
    text_mode = tl.get('telop_mode', 'text') == 'text'
    fill = ('16:9 の実写で縦を埋めるときは、スケールを約316％にする（寄りのキーフレームも同じ割合で上げる：100→110 を 316→348 など）'
            if L['H'] > L['W'] else '9:16 の素材で横を埋めるときは、スケールを約316％にする（または左右をぼかした背景で埋める）')
    slots = [it for it in spec.get('v2', []) if it['kind'] == 'slot']
    rows = [f'# {name}（Premiere 読み込み用）', '',
            f'{L["W"]}×{L["H"]}・{tl["fps"]}fps・{tl["seq_end_sec"]}秒。{datetime.date.today():%Y-%m-%d} 作成（作業版 {spec["title"]}）。', '',
            '## 読み込み方（新しいプロジェクトで）', '',
            '1. Premiere Pro で「新規プロジェクト」を作る。保存場所は**このフォルダ**にすると、素材とプロジェクトが1か所にまとまる',
            f'2. 「ファイル」→「読み込み…」で `{xml_name}` を選ぶ',
            f'3. ビン（{"・".join(bins)}）とシーケンス「{name}」ができる。シーケンスを開いて作業する', '',
            '素材はこのフォルダの中の `素材/` を直接指している。**読み込んだ後は、このフォルダを動かさない・名前を変えない**'
            '（動かしたときは、Premiere が聞いてくる「メディアをリンク」でこのフォルダを探させる）。', '',
            '## トラック', '', '| トラック | 中身 |', '|---|---|']
    names = tl.get('track_names') or TRACK_NAMES
    R = tl.get('track_roles') or {'veil': 'V3', 'explainer': ['V4', 'V5', 'V6'], 'listener': ['V7', 'V8'], 'chars': None}
    ex, li = R['explainer'], R['listener']
    rows += [f'| {t} | {names.get(t, "")} |' for t in vt]
    rows += ['| A1・A2 | ナレーション（説明役・聞き手、1行ずつ別クリップ） |', '| A3・A4 | BGM・効果音（空。自分で入れる） |', '',
             '各行の頭にシーケンスマーカー（行番号・話者・セリフ）がある。' + (
                 f'{R["veil"]} はテロップの座布団（グレーの角丸の四角・不透明度{spec["telop_box"].get("opacity", 40)}％）。濃さは各クリップの「不透明度」で変えられる'
                 '（1つ直して、ほかは「属性をペースト」で）。テロップを打ち替えて長さが変わったら、座布団の「スケール」の幅を直す。'
                 if spec.get('telop_box') else
                 f'{R["veil"]} の暗幕は最初はオフ（実写が明るくて文字が読みにくいときに有効にする）。'), '']
    if text_mode:
        rows += ['## テロップ（Premiere 上で打ち替えられる文字）', '',
                 '- ダブルクリック（または文字ツール）で打ち替える。書体・色・縁取りはプロパティ（エッセンシャルグラフィックス）パネルで変える',
                 f'- テロップは1行ずつ別の文字クリップ（1行目 {ex[0]}・2行目 {ex[1]}・3行目 {ex[2]}、聞き手は {li[0]}・{li[1]}）。行の高さはクリップごとに決めてあるので、1つのクリップの中で改行して行を足さない（行を足すときはクリップを複製して、プロパティの「位置」の Y をずらす）',
                 '- 同じテロップの行は、同じ長さ・同じ動き。長さを変えるときは、縦に並んだクリップをまとめて選んで動かす',
                 '- 「フォントを解決」が出たときは、「グラフィックとタイトル」→「プロジェクト内のフォントを置換」でヒラギノ明朝 ProN W6 にまとめて置き換える', '']
    rows += ['## 図・スクショ・グラフ（V2）', '',
             'グラフとスクショは、ナレーションの言葉に合わせて動く動画（透明部分あり）。動きは `確認用/動きの確認_図・スクショ・グラフ.mp4` で見られる。', '']
    if R.get('chars') and tl.get('chars'):
        rows += [f'## イラスト（{R["chars"]}）', '',
                 f'人物などのイラストは、ナレーションに合わせて動く動画（透明部分あり・{len(tl["chars"])}本）。図・スクショの上、テロップの下のトラック。'
                 '1本ずつ別のクリップなので、位置・大きさを変える・短くする・消すことは Premiere 上でできる'
                 '（絵の中の動き・表情の切り替えを変えるときは作業フォルダの spec の chars を直して作り直す）。'
                 '動きは `確認用/動きの確認_イラスト.mp4`。使った元の絵（透明 PNG）は `素材/イラストの元の絵/`（自分で並べ直したいとき用。XML には入っていない）。', '']
        rows += ['| クリップ | 時刻 | 中身 |', '|---|---|---|']
        memo = {it['id']: it.get('memo', it.get('name', '')) for it in spec.get('chars', [])}
        rows += [f'| {x["name"]} | {mmss(x["start"], tl["fps"])}〜{mmss(x["end"], tl["fps"])} | {memo.get(x["id"], "")} |'
                 for x in tl['chars']]
        rows += ['']
    rows += [
             '## 自分で入れるもの', '',
             ('- 背景（V1）：今はイラストの背景か暗い無地が入っている（このままでも使える）。実写・イメージに替えるときは、プロジェクトパネルの素材を Option（Windows は Alt）を押しながら、タイムラインの背景にドラッグして重ねる（ゆっくり寄る動きは残る）'
              if spec.get('backgrounds') and all(b.get('image') or b.get('plain') for b in spec['backgrounds']) else
              '- 背景（V1）：仮の画像（BG1〜）を実写・イメージに置き換える。プロジェクトパネルの素材を Option（Windows は Alt）を押しながら、タイムラインの仮の画像にドラッグして重ねる（ゆっくり寄る動きは残る）'),
             f'- {fill}']
    when = {x['id']: x for x in tl.get('v2', [])}
    rows += [f'- {it["id"]}（{mmss(when[it["id"]]["start"], tl["fps"])}〜{mmss(when[it["id"]]["end"], tl["fps"])}、{it["label"]}）：'
             'V2 の［差し替え］枠のクリップに、用意した画像を Option を押しながらドラッグして置き換え、'
             'モーションの位置・スケールで画面の上側（図と同じ高さ）に合わせる' for it in slots]
    rows += ['- BGM（A3）・効果音（A4）']
    if (spec.get('end_card') or {}).get('sender'):      # 発信者の仮枠を外した回（最初の案件）は書かない
        rows += ['- エンドカードの発信者表示（公開前に。画像なので差し替える）']
    rows += ['',
             '差し替え枠ごとの時刻・入れるもの・出典・権利の注意は `02_素材リスト（差し替え・出典）.md`。', '']
    extra = spec.get('readme_extra', [])
    if extra:
        rows += ['## この版のメモ', ''] + [f'- {x}' for x in extra] + ['']
    rows += ['## 作り直すとき', '',
             f'文字・図・音声を作り直すときは、作業フォルダ `{work}` の spec を直して作り直し、新しい読み込み用フォルダ（版の番号を上げたもの）を作る。'
             'このフォルダは上書きしない（読み込んだプロジェクトの素材が入れ替わってしまうため）。', '']
    return '\n'.join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--dest', required=True)
    ap.add_argument('--out', help='作業フォルダ（省略時は spec と同じ）')
    ap.add_argument('--name', help='シーケンス名（省略時は spec の title）')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    spec_path = Path(a.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    work = Path(a.out).resolve() if a.out else spec_path.parent
    dest = Path(a.dest).expanduser().resolve()
    name = a.name or spec['title']
    tl = json.loads((work / 'timeline.json').read_text(encoding='utf-8'))
    src_xml = work / f'{spec["title"]}.xml'
    if dest.exists() and any(dest.iterdir()):
        if not a.force:
            raise SystemExit(f'既にあるフォルダには書かない: {dest}（新しい名前にするか --force）')
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    # 素材をビンと同じ名前のフォルダに写し、XML のパスを付け替える
    xml = src_xml.read_text(encoding='utf-8')
    items = {it['id']: it for it in spec.get('v2', [])}
    done = {}
    for c in tl['clips']:
        f = c.get('file')
        if not f or f in done:
            continue
        src = Path(f)
        new_name = src.name
        m = re.match(r'V2_([A-Za-z0-9]+)_', src.name)
        if m and m.group(1) in items:          # 図・スクショは中身の分かる名前にする（クリップ名も同じに）
            it = items[m.group(1)]
            new_name = f'{it["id"]}_{KIND_JP.get(it["kind"], it["kind"])}_{nice(v2_label(it))}{src.suffix}'
        dst = dest / '素材' / c['bin'] / new_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        done[f] = dst
        old = pathurl(src)
        if old not in xml:
            raise SystemExit(f'XML に素材のパスが見つからない: {f}（build_all.py を流し直してから書き出す）')
        xml = xml.replace(old, pathurl(dst))
        if new_name != src.name:
            xml = xml.replace(f'<name>{src.name}</name>', f'<name>{new_name}</name>')
            xml = xml.replace(f'<name>{src.stem}</name>', f'<name>{Path(new_name).stem}</name>')
    xml = re.sub(r'<project><name>[^<]*</name>', f'<project><name>{name}</name>', xml, count=1)
    xml = re.sub(r'(<sequence id="seq-1"><name>)[^<]*(</name>)', rf'\g<1>{name}\g<2>', xml, count=1)
    xml_name = f'00_これを読み込む_{name}.xml'
    (dest / xml_name).write_text(xml, encoding='utf-8')
    # 点検：XML が読めて、パスが全部このフォルダの中にあるか
    root = ET.parse(dest / xml_name).getroot()
    urls = {u.text for u in root.iter('pathurl')}
    bad = [u for u in urls if not urllib.parse.unquote(u.replace('file://localhost', '')).startswith(str(dest))
           or not Path(urllib.parse.unquote(u.replace('file://localhost', ''))).exists()]
    if bad:
        raise SystemExit(f'素材のパスがおかしい {len(bad)} 件（例 {urllib.parse.unquote(bad[0])}）')
    # 説明・素材リスト・確認用
    (dest / '01_はじめに読む.md').write_text(guide(spec, tl, name, xml_name, work), encoding='utf-8')
    lst = (work / '素材リスト.md').read_text(encoding='utf-8').replace('`media/', '`素材/').replace(f'「{spec["title"]}」', f'「{name}」')
    (dest / '02_素材リスト（差し替え・出典）.md').write_text(lst, encoding='utf-8')
    for src_name, dst_name in (('プレビュー_V2.mp4', '動きの確認_図・スクショ・グラフ.mp4'),
                               ('プレビュー_イラスト.mp4', '動きの確認_イラスト.mp4'), ('全体の流れ_目安.mp4', '全体の流れ_目安.mp4')):
        pv = work / 'media_anim' / src_name
        if pv.exists():
            (dest / '確認用').mkdir(exist_ok=True)
            shutil.copy2(pv, dest / '確認用' / dst_name)
    # イラストの元の絵（XML には入れない。自分で並べ直したいとき用）
    files = list(dict.fromkeys(f for x in tl.get('chars', []) for f in x.get('files', [])))
    for f in files:
        src = spec_path.parent / f
        if src.exists():
            (dest / '素材' / 'イラストの元の絵').mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / '素材' / 'イラストの元の絵' / src.name)
    size = sum(p.stat().st_size for p in dest.rglob('*') if p.is_file()) / 1024 / 1024
    print(f'OK: {dest}（素材 {len(done)} 件・{size:.0f}MB、シーケンス「{name}」）')
    for p in sorted(dest.iterdir()):
        print('  ' + p.name + ('/' if p.is_dir() else ''))


if __name__ == '__main__':
    main()
