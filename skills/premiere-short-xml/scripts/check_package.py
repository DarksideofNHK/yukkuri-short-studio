#!/usr/bin/env python3
"""できた素材一式を点検する：XML が読めるか、素材ファイルがあるか、動く図の長さが合っているか、文字クリップの中身。

usage:
  python3 check_package.py --spec path/to/spec.json [--out 出力フォルダ]
"""
import argparse
import json
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LAYOUTS, layout_of, font  # noqa: E402


def frames(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                          'stream=nb_read_packets', '-of', 'csv=p=0', str(path)], capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else -1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--out')
    a = ap.parse_args()
    spec_path = Path(a.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    out = Path(a.out).resolve() if a.out else spec_path.parent
    L = layout_of(spec)
    problems, notes = [], []
    for name in (f'{spec["title"]}.xml', f'{spec["title"]}_予備_ビンなし.xml'):
        p = out / name
        try:
            root = ET.parse(p).getroot()
        except Exception as e:  # noqa: BLE001
            problems.append(f'{name} が XML として読めない: {e}')
            continue
        urls = {u.text for u in root.iter('pathurl')}
        missing = [u for u in urls if not Path(urllib.parse.unquote(u.replace('file://localhost', ''))).exists()]
        if missing:
            problems.append(f'{name}: 素材ファイルがない {len(missing)} 件（例 {urllib.parse.unquote(missing[0])[-80:]}）')
        gens = list(root.iter('generatoritem'))
        fonts = {pp.find('value').text for g in gens for pp in g.iter('parameter') if pp.findtext('parameterid') == 'fontname'}
        if any(' ' in (f or '') for f in fonts):
            problems.append(f'{name}: フォント名に空白がある {fonts}（Premiere で名前が壊れる。PostScript 名にする）')
        notes.append(f'{name}: 素材 {len(urls)} 件・文字クリップ {len(gens)} 個・フォント {sorted(fonts)}')
    tl = json.loads((out / 'timeline.json').read_text(encoding='utf-8'))
    for c in tl['clips']:
        f = c.get('file', '')
        if f.endswith('.mov'):
            n = frames(f)
            if n != c['end'] - c['start']:
                problems.append(f'{Path(f).name}: 動画 {n} フレーム、クリップ {c["end"] - c["start"]} フレーム（長さが合わない）')
    ts = L['text_scale']
    for c in tl['clips']:
        if 'text' not in c:
            continue
        for ln in c['text'].split('\r'):
            if ln.strip('　') and font('m', c['px']).getlength(ln) > L['telop_max_w'] + 1:
                problems.append(f'{c["name"]}: 「{ln}」が画面幅をこえる（{c["px"]}px）')
        if abs(c['px'] / ts - round(c['px'] / ts)) > 1e-6:
            notes.append(f'{c["name"]}: 文字サイズ {c["px"]}px が {ts} の倍数でない')
    for n in notes:
        print('・' + n)
    print(f'・長さ {tl["seq_end_sec"]}秒、時刻 {tl.get("timing", "")}')
    if problems:
        print('問題あり:')
        for p in problems:
            print('  ✗ ' + p)
        raise SystemExit(1)
    print('点検OK')


if __name__ == '__main__':
    main()
