#!/usr/bin/env python3
"""timeline.json から、全体の流れを確かめる動画（半分の大きさ・ナレーション入り）を作る。

usage:
  python3 preview_video.py --spec spec.json [--out 作業フォルダ]

出力: media_anim/全体の流れ_目安.mp4（540×960・H.264・ナレーション入り）
画像・動画のクリップはそのまま重ね、文字クリップは preview_frames.py と同じ置き方で描く（ポンの動き・背景の寄りは入れない）。
暗幕（最初はオフ）は入れない。Premiere の描画そのものではない（流れ・タイミング・重なりの確認用）。
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

K = 2          # 縮める割合（1/2）


class MovReader:
    """動画のクリップを頭から1フレームずつ読む（縮めた RGBA）"""

    def __init__(self, path, w, h):
        self.w, self.h = w, h
        self.p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'scale={w}:{h}', '-f', 'rawvideo',
                                   '-pix_fmt', 'rgba', '-'], stdout=subprocess.PIPE)
        self.last = Image.new('RGBA', (w, h))

    def next(self):
        buf = self.p.stdout.read(self.w * self.h * 4)
        if len(buf) == self.w * self.h * 4:
            self.last = Image.frombytes('RGBA', (self.w, self.h), buf)
        return self.last

    def close(self):
        self.p.stdout.close()
        self.p.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--out')
    a = ap.parse_args()
    spec_path = Path(a.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    out = Path(a.out).resolve() if a.out else spec_path.parent
    tl = json.loads((out / 'timeline.json').read_text(encoding='utf-8'))
    L = layout_of(spec)
    W, H = L['W'] // K, L['H'] // K
    fps, n = tl['fps'], tl['seq_end_frames']
    vclips = [c for c in tl['clips'] if c['track'].startswith('V') and '暗幕' not in c['name']]
    vclips.sort(key=lambda c: (int(c['track'][1:]), c['start']))
    pngs, texts, readers = {}, {}, {}
    dst = out / 'media_anim' / '全体の流れ_目安.mp4'
    dst.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        silent = Path(tmp) / 'v.mp4'
        enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}',
                                '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-crf', '21', '-pix_fmt', 'yuv420p',
                                str(silent)], stdin=subprocess.PIPE)
        for f in range(n):
            img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
            for i, c in enumerate(vclips):
                if not (c['start'] <= f < c['end']):
                    if i in readers and f >= c['end']:
                        readers.pop(i).close()
                    continue
                if 'text' in c:
                    if i not in texts:
                        layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                        ImageDraw.Draw(layer).text((W / 2, c['baseline'] / K), c['text'], font=font('m', c['px'] / K),
                                                   fill=color(c['color']) + (255,), anchor='ms',
                                                   stroke_width=max(1, int(L['stroke_px'] / K)), stroke_fill=(0, 0, 0, 255))
                        texts[i] = layer
                    img.alpha_composite(texts[i])
                elif c['file'].endswith('.png'):
                    key = (c['file'], c.get('alpha', 1))
                    if key not in pngs:
                        im = Image.open(c['file']).convert('RGBA').resize((W, H), Image.BILINEAR)
                        if key[1] < 1:             # 座布団など、不透明度を下げたクリップ
                            im.putalpha(im.getchannel('A').point(lambda v, k=key[1]: int(v * k)))
                        pngs[key] = im
                    img.alpha_composite(pngs[key])
                elif c['file'].endswith('.mov'):
                    if i not in readers:
                        readers[i] = MovReader(c['file'], W, H)
                    img.alpha_composite(readers[i].next())
            enc.stdin.write(img.tobytes())
        enc.stdin.close()
        enc.wait()
        for r in readers.values():
            r.close()
        # ナレーション（行ごとの音声を、シーケンスの位置に置いて重ねる）
        aclips = [c for c in tl['clips'] if c['track'] in ('A1', 'A2')]
        args, fil = [], []
        for k, c in enumerate(aclips):
            args += ['-i', c['file']]
            ms = int(round(c['start'] / fps * 1000))
            fil.append(f'[{k + 1}:a]aresample=48000,adelay={ms}|{ms}[a{k}]')
        mix = ''.join(f'[a{k}]' for k in range(len(aclips))) + f'amix=inputs={len(aclips)}:normalize=0[aout]'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(silent), *args, '-filter_complex', ';'.join(fil + [mix]),
                        '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-t', f'{n / fps}',
                        '-movflags', '+faststart', str(dst)], check=True)
    print(f'OK: {dst}（{n / fps:.2f}秒、{dst.stat().st_size / 1024 / 1024:.1f}MB）')


if __name__ == '__main__':
    main()
