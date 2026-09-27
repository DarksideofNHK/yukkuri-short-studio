#!/usr/bin/env python3
"""T06: Pillowのみで透過図を再生成。既存ファイルは上書きしない。

既定の出力先はこのスクリプトの隣。再生成時は --out 図/v1/rebuild_v2
など未使用のフォルダを指定する（この案件の書込許可は 図/v1/ 内）。
"""
from pathlib import Path
import argparse
import json
import math
from PIL import Image, ImageDraw, ImageFont

S = 3
INK = '#202732'
GRAY = '#666E79'
YELLOW = '#FFE600'
WHITE = '#F3F4F6'
RED = '#F52222'


class Canvas:
    def __init__(self, size):
        self.image = Image.new('RGBA', (size[0] * S, size[1] * S))
        self.draw = ImageDraw.Draw(self.image)

    def box(self, bounds, fill, outline=None, width=0, radius=0):
        bounds = tuple(round(v * S) for v in bounds)
        if radius:
            self.draw.rounded_rectangle(bounds, round(radius*S), fill,
                                        outline, round(width*S))
        else:
            self.draw.rectangle(bounds, fill, outline, round(width*S))

    def ellipse(self, bounds, fill, outline=None, width=0):
        self.draw.ellipse(tuple(round(v*S) for v in bounds), fill,
                          outline, round(width*S))

    def polygon(self, points, fill):
        self.draw.polygon([(round(x*S), round(y*S)) for x, y in points], fill)

    def line(self, points, color, width):
        self.draw.line([(round(x*S), round(y*S)) for x, y in points],
                       color, round(width*S), joint='curve')
        r = width / 2
        for x, y in points:
            self.ellipse((x-r, y-r, x+r, y+r), color)

    def finish(self):
        return self.image.resize((self.image.width//S, self.image.height//S),
                                 Image.Resampling.LANCZOS)


def person(c, cx, top, scale=1, lit=False, raised=False, neutral=False):
    """顔位置固定の汎用人形。点灯時だけ右手を上げる。"""
    color = YELLOW if lit else (WHITE if neutral else GRAY)
    def pt(x, y):
        return cx+x*scale, top+y*scale
    def box(x0, y0, x1, y1):
        return (*pt(x0, y0), *pt(x1, y1))
    # Arms behind torso; hand and arm match the person's fill.
    arms = [[pt(-34, 93), pt(-55, 124), pt(-55, 151)],
            [pt(34, 93), pt(64, 110), pt(83, 45)] if raised else
            [pt(34, 93), pt(55, 124), pt(55, 151)]]
    for arm in arms:
        c.line(arm, INK, 31*scale)
        c.line(arm, color, 17*scale)
    c.box(box(-44, 77, 44, 168), color, INK, 6*scale, 22*scale)
    c.box(box(-39, 148, -6, 201), color, INK, 6*scale, 9*scale)
    c.box(box(6, 148, 39, 201), color, INK, 6*scale, 9*scale)
    c.ellipse(box(-32, 5, 32, 69), color, INK, 6*scale)


def seats(lit=0):
    c = Canvas((1080, 800))
    for i in range(12):
        person(c, 155 + 250*(i % 4), 35 + 258*(i//4),
               lit=i < lit, raised=i < lit)
    return c.finish()


def arrow(c, x, y0, y1):
    # White outer stroke maintains visibility on dark video backgrounds.
    c.polygon([(x-19,y0), (x+19,y0), (x+19,y1-42), (x+48,y1-42),
               (x,y1+6), (x-48,y1-42), (x-19,y1-42)], WHITE)
    c.polygon([(x-12,y0+6), (x+12,y0+6), (x+12,y1-35), (x+32,y1-35),
               (x,y1-3), (x-32,y1-35), (x-12,y1-35)], INK)


def stages():
    top = Canvas((1080, 1300))
    person(top, 540, 30, scale=1.3, neutral=True)
    middle = Canvas((1080, 1300))
    arrow(middle, 540, 325, 414)
    for i in range(12):
        person(middle, 337.5 + 135*(i % 4), 440 + 127*(i//4),
               scale=.55)
    bottom = Canvas((1080, 1300))
    arrow(bottom, 540, 838, 923)
    # 180 x 320 transparent interior: matches the later 360 x 640 portrait.
    bottom.box((437, 950, 643, 1290), None, WHITE, 6, 20)
    bottom.box((443, 956, 637, 1284), None, INK, 7, 14)
    return [top.finish(), middle.finish(), bottom.finish()]


def house():
    c = Canvas((400, 400))
    c.box((273, 74, 309, 152), GRAY, INK, 9, 3)
    c.box((81, 174, 319, 353), WHITE, INK, 10, 9)
    c.polygon([(43,185), (200,50), (357,185), (334,211),
               (200,96), (66,211)], INK)
    c.polygon([(60,184), (200,65), (340,184), (333,195),
               (200,81), (67,195)], GRAY)
    c.box((112, 224, 169, 278), YELLOW, INK, 8, 3)
    c.line([(140,228),(140,274)], INK, 5)
    c.line([(116,251),(165,251)], INK, 5)
    c.box((219, 229, 280, 349), GRAY, INK, 8, 3)
    c.ellipse((259,286,269,296), YELLOW)
    return c.finish()


def dashed_arrow():
    c = Canvas((400, 400))
    # Arrow travels upward. Separate X can be placed at its tip.
    for y in range(137, 354, 54):
        c.line([(200,y),(200,y+25)], WHITE, 22)
        c.line([(200,y),(200,y+25)], INK, 12)
    c.line([(145,112),(200,57),(255,112)], WHITE, 24)
    c.line([(145,112),(200,57),(255,112)], INK, 14)
    return c.finish()


def cross():
    c = Canvas((400, 400))
    for points in [[(99,99),(301,301)],[(301,99),(99,301)]]:
        c.line(points, WHITE, 53)
    for points in [[(99,99),(301,301)],[(301,99),(99,301)]]:
        c.line(points, RED, 37)
    return c.finish()


def overview(assets):
    # Labels are confined to this review sheet; production parts contain no text.
    w, h = 1600, math.ceil(len(assets)/4)*380
    sheet = Image.new('RGBA', (w,h))
    d = ImageDraw.Draw(sheet)
    font_path = '/System/Library/Fonts/Supplemental/Arial.ttf'
    font = ImageFont.truetype(font_path, 17) if Path(font_path).exists() else ImageFont.load_default(size=17)
    for i, (name, im) in enumerate(assets.items()):
        x, y = (i%4)*400, (i//4)*380
        d.rounded_rectangle((x+9,y+9,x+390,y+370), radius=12,
                            fill='#E6E8EB', outline='#B7BDC5', width=2)
        thumb = im.copy()
        thumb.thumbnail((350,305), Image.Resampling.LANCZOS)
        sheet.alpha_composite(thumb, (x+(400-thumb.width)//2, y+24+(305-thumb.height)//2))
        d.text((x+23,y+341), name.removesuffix('.png'), font=font, fill=INK)
    return sheet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    out = args.out.resolve()
    if not out.is_relative_to(root):
        raise SystemExit('出力先は 図/v1/ の中に限定します。')
    assets = {'seats_00_dark.png': seats(0)}
    assets.update({f'seats_{n:02d}_lit.png': seats(n) for n in range(1,10)})
    assets['seats_10_ninth_off.png'] = seats(8)
    layers = stages()
    combined = Image.new('RGBA', (1080,1300))
    for layer in layers:
        combined = Image.alpha_composite(combined, layer)
    assets['flow_all.png'] = combined
    for name, layer in zip(['flow_01_pm.png','flow_02_committee.png','flow_03_chair_frame.png'],layers):
        assets[name] = layer
    assets['viewer_house.png'] = house()
    assets['viewer_arrow_up.png'] = dashed_arrow()
    assets['viewer_cross.png'] = cross()
    assets['一覧.png'] = overview(assets)
    names = [*assets, 'manifest.json']
    existing = [str(out/name) for name in names if (out/name).exists()]
    if existing:
        raise SystemExit('上書き禁止。--out で新しい版を指定してください: ' + ', '.join(existing))
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'assets': [], 'seat_order': '左上から右へ4列、上から下へ3行',
                'colors': {'lit': YELLOW, 'dark': GRAY, 'cross': RED},
                'flow_layers': '3枚とも1080×1300。同じ位置で重ねるとflow_all.pngと一致。第2・第3段は直前の矢印を含む。',
                'chair_safe_area': [450,963,630,1283],
                'viewer_parts': '各400×400。家と上向き点線矢印と×は別配置。矢印の先端は(200,57)。届かない隙間を編集で空ける。',
                'ninth_off': 'seats_10_ninth_off.pngはseats_08_lit.pngと同一の8人点灯状態。9枚目から切り替える。',
                'overview': '一覧.pngのファイル名ラベルは確認用。動画用18枚には文字なし。'}
    for name, im in assets.items():
        with (out/name).open('xb') as f:
            im.save(f, format='PNG')
        manifest['assets'].append({'path':name, 'size':list(im.size), 'mode':im.mode})
    with (out/'manifest.json').open('x', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'{len(assets)} PNG + manifest.json → {out}')


if __name__ == '__main__':
    main()
