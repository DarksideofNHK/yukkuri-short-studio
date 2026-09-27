#!/usr/bin/env python3
"""timeline.json から、指定したフレームの見た目の目安を作る（重なりの点検用）。

usage:
  python3 preview_frames.py --spec spec.json [--out 作業フォルダ] --frames 10,170,800 [--save 画像.png]
  python3 preview_frames.py --spec spec.json --every 45        … 45フレームおきに全体を並べる

画像・動画のクリップはそのまま重ね、文字クリップは Premiere の置き方（build_premiere.py の見積もり：
ベースライン＝timeline の baseline、中央ぞろえ、外側に黒の縁取り）で描く。拡大の動き（ポン）は止まった後の形。
Premiere の描画そのものではないので、最後は Premiere で確かめる。
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LAYOUTS, layout_of, color, font  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

_mov_cache = {}


def mov_frame(path, n, W, H):
    key = (path, n)
    if key not in _mov_cache:
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / 'f.png'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', path, '-vf', f'select=eq(n\\,{n})', '-vsync', '0',
                            '-frames:v', '1', str(png)], check=True)
            _mov_cache[key] = Image.open(png).convert('RGBA').copy() if png.exists() else Image.new('RGBA', (W, H))
    return _mov_cache[key]


def render(tl, L, f):
    W, H = L['W'], L['H']
    img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    tracks = sorted({c['track'] for c in tl['clips'] if c['track'].startswith('V')}, key=lambda t: int(t[1:]))
    for t in tracks:
        for c in tl['clips']:
            if c['track'] != t or not (c['start'] <= f < c['end']) or '暗幕' in c['name']:
                continue
            if 'text' in c:
                layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                ImageDraw.Draw(layer).text((W / 2, c['baseline']), c['text'], font=font('m', c['px']),
                                           fill=color(c['color']) + (255,), anchor='ms',
                                           stroke_width=int(L['stroke_px']), stroke_fill=(0, 0, 0, 255))
                img.alpha_composite(layer)
            elif c['file'].endswith('.png'):
                im = Image.open(c['file']).convert('RGBA')
                if c.get('alpha', 1) < 1:          # 座布団など、不透明度を下げたクリップ
                    im.putalpha(im.getchannel('A').point(lambda v, k=c['alpha']: int(v * k)))
                img.alpha_composite(im)
            elif c['file'].endswith('.mov'):
                img.alpha_composite(mov_frame(c['file'], f - c['start'], W, H))
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--out')
    ap.add_argument('--frames', help='カンマ区切りのフレーム番号')
    ap.add_argument('--every', type=int, help='何フレームおきに並べるか')
    ap.add_argument('--save', help='並べた画像の保存先（省略時は 作業フォルダ/確認_見た目の目安.png）')
    ap.add_argument('--cols', type=int, default=6)
    a = ap.parse_args()
    spec_path = Path(a.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    out = Path(a.out).resolve() if a.out else spec_path.parent
    tl = json.loads((out / 'timeline.json').read_text(encoding='utf-8'))
    L = layout_of(spec)
    frames = [int(x) for x in a.frames.split(',')] if a.frames else list(range(5, tl['seq_end_frames'], a.every or 45))
    tw = 270 if L['H'] > L['W'] else 640        # 横は大きめ（1920×1080 を 640 幅に）
    th = int(tw * L['H'] / L['W'])
    cols = min(a.cols, len(frames))
    sheet = Image.new('RGB', (cols * tw, ((len(frames) + cols - 1) // cols) * (th + 26)), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(frames):
        im = render(tl, L, f).convert('RGB').resize((tw, th), Image.LANCZOS)
        x, y = (i % cols) * tw, (i // cols) * (th + 26)
        sheet.paste(im, (x, y + 26))
        d.text((x + 6, y + 3), f'{f}f  {f // tl["fps"] // 60}:{f / tl["fps"] % 60:05.2f}', font=font('g', 17), fill=(255, 200, 80))
    dst = Path(a.save) if a.save else out / '確認_見た目の目安.png'
    sheet.save(dst)
    print(dst, sheet.size)


if __name__ == '__main__':
    main()
