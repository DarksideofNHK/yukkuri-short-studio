#!/usr/bin/env python3
"""V2 のグラフ（chart）とスクショ（shot）、イラスト（chars）を、ナレーションに合わせて動くアルファ付き動画（ProRes 4444 .mov）にする。

usage:
  python3 build_anim.py --spec path/to/spec.json [--out 出力フォルダ] [--only CH1,SH1]

build_premiere.py の後に実行する（timeline.json から各図の長さと、動くタイミングを読む）。
出力: media_anim/V2_{id}_動き.mov・media_anim/イラスト_{id}_{名前}.mov（全画面・透明部分あり）と
     media_anim/プレビュー_V2.mp4・プレビュー_イラスト.mp4（確認用、灰色の背景に重ねたもの）
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chars import CharAnim  # noqa: E402
from common import LAYOUTS, layout_of, Shot, render_chart_frame  # noqa: E402


def render_char(args):
    """イラスト1本：フレームを ffmpeg に直接流して ProRes 4444 に（PNG を書かない）"""
    tl_item, L, base, out, fps = args
    n = tl_item['end'] - tl_item['start']
    ca = CharAnim(tl_item, L, base, n)
    W, H = L['W'], L['H']
    dst = out / 'media_anim' / f'{tl_item["name"]}.mov'
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}', '-r', str(fps),
                          '-i', '-', '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-vendor', 'apl0',
                          '-alpha_bits', '16', str(dst)], stdin=subprocess.PIPE)
    for f in range(n):
        p.stdin.write(ca.frame(f).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise SystemExit(f'{dst.name} の書き出しに失敗')
    pv = out / 'media_anim' / '_pv' / f'{tl_item["name"]}.mp4'
    pv.parent.mkdir(exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=0x3c3e48:s={W}x{H}:r={fps}:d={n / fps}',
                    '-i', str(dst), '-filter_complex', f'[0][1]overlay=format=auto,scale={W // 2}:{H // 2},format=yuv420p',
                    '-t', f'{n / fps}', '-c:v', 'libx264', '-crf', '20', str(pv)], check=True)
    return tl_item['name'], n, dst.stat().st_size / 1024 / 1024


def concat(pvs, dst):
    pvs = [p for p in pvs if p.exists()]
    if not pvs:
        return
    lst = dst.parent / '_pv' / f'list_{dst.stem}.txt'
    lst.write_text(''.join(f"file '{p}'\n" for p in pvs), encoding='utf-8')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', str(dst)], check=True)
    print('プレビュー:', dst)


def render_item(args):
    it, tl_item, L, base, out, fps = args
    n = tl_item['end'] - tl_item['start']
    tmp = Path(tempfile.mkdtemp(prefix=f'anim_{it["id"]}_'))
    try:
        if it['kind'] == 'shot':
            shot = Shot(dict(it, steps=tl_item['steps']), L, base, out / 'media_anim' / '_src', n)
            frame = shot.frame
        else:
            ev = tl_item['ev']
            frame = lambda f: render_chart_frame(it['chart'], L, f, ev)
        for f in range(n):
            frame(f).save(tmp / f'{f:04d}.png', compress_level=1)
        dst = out / 'media_anim' / f'V2_{it["id"]}_動き.mov'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(fps), '-i', str(tmp / '%04d.png'),
                        '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-vendor', 'apl0',
                        '-alpha_bits', '16', str(dst)], check=True)
        pv = out / 'media_anim' / '_pv' / f'{it["id"]}.mp4'
        pv.parent.mkdir(exist_ok=True)
        W, H = L['W'], L['H']
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=0x3c3e48:s={W}x{H}:r={fps}:d={n / fps}',
                        '-i', str(dst), '-filter_complex', f'[0][1]overlay=format=auto,scale={W // 2}:{H // 2},format=yuv420p',
                        '-t', f'{n / fps}', '-c:v', 'libx264', '-crf', '20', str(pv)], check=True)
        return it['id'], n, dst.stat().st_size / 1024 / 1024
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--out')
    ap.add_argument('--only', help='作る図の id（カンマ区切り）')
    a = ap.parse_args()
    spec_path = Path(a.spec).resolve()
    base = spec_path.parent
    out = Path(a.out).resolve() if a.out else base
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    tl = json.loads((out / 'timeline.json').read_text(encoding='utf-8'))
    L = layout_of(spec)
    fps = spec.get('fps', 30)
    only = set(a.only.split(',')) if a.only else None
    by_id = {x['id']: x for x in tl['v2']}
    jobs = [(it, by_id[it['id']], L, base, out, fps) for it in spec.get('v2', [])
            if it['kind'] in ('chart', 'shot') and (not only or it['id'] in only)]
    cjobs = [(x, L, base, out, fps) for x in tl.get('chars', []) if not only or x['id'] in only]
    (out / 'media_anim').mkdir(exist_ok=True)
    with ProcessPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(render_item, j) for j in jobs] + [ex.submit(render_char, j) for j in cjobs]
        for fu in futs:
            cid, n, mb = fu.result()
            print(f'{cid}: {n}フレーム（{n / fps:.2f}秒）→ {mb:.1f}MB')
    concat([out / 'media_anim' / '_pv' / f'{it["id"]}.mp4' for it in spec.get('v2', []) if it['kind'] in ('chart', 'shot')],
           out / 'media_anim' / 'プレビュー_V2.mp4')
    concat([out / 'media_anim' / '_pv' / f'{x["name"]}.mp4' for x in tl.get('chars', [])],
           out / 'media_anim' / 'プレビュー_イラスト.mp4')


if __name__ == '__main__':
    main()
