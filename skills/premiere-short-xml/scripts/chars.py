"""イラスト（人物などの人物・小物・雨）を、ナレーションに合わせて動く全画面の絵にする（spec の chars）。

1つの chars 項目 = 1本の動画（ProRes 4444・透明部分あり）。中に役者（actor）を何人でも置ける。
役者の時刻（at）は build_premiere.py が「項目の頭から何フレーム目か」（f）に直して timeline.json の chars に書く。
ここでは f だけを読む（at は読まない）。

役者の種類：
  img   … 人物・小物の絵（透明 PNG）。place で置き場所、in/out で出入り、swap/talk/loop/blink で絵の差し替え、
          bob/shake/hop/nod/tilt/ghost で動き
  rain  … 雨の線（範囲・量）。絵ではなく効果
  text  … 小さい注記（「イラストはイメージ」など）
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from common import draw_plain, font

HEAD = (180, 97)          # 360×640 の似顔絵キャンバスで、頭の上端の中央（Codex 製の絵はどれもここにそろっている）


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in(t):
    return t ** 3


def prog(f, a, dur):
    return 0.0 if f < a else 1.0 if dur <= 0 or f >= a + dur else (f - a) / dur


class _Img:
    """絵の読み込みと、大きさ・向きごとのキャッシュ"""

    def __init__(self, base):
        self.base = Path(base)
        self.raw, self.cache = {}, {}

    def get(self, rel):
        if rel not in self.raw:
            im = Image.open(self.base / rel).convert('RGBA')       # 4bit・8bit のパレット PNG もここで RGBA に
            self.raw[rel] = (im, im.getchannel('A').getbbox() or (0, 0, *im.size))
        return self.raw[rel]

    def scaled(self, rel, s, flip=False, gray=False):
        key = (rel, round(s, 3), flip, gray)
        if key not in self.cache:
            im, _ = self.get(rel)
            w, h = max(1, round(im.width * s)), max(1, round(im.height * s))
            integer = abs(s - round(s)) < 1e-6
            out = im.resize((w, h), Image.NEAREST if integer else Image.LANCZOS)
            if flip:
                out = ImageOps.mirror(out)
            if gray:
                a = out.getchannel('A')
                out = ImageOps.grayscale(out).convert('RGBA')
                out.putalpha(a)
            self.cache[key] = out
            if len(self.cache) > 400:
                self.cache.pop(next(iter(self.cache)))
        return self.cache[key]


class CharAnim:
    """chars 項目1つ分。frame(f) で全画面（透明背景）の1枚を返す。item は timeline.json の chars の1件（f が入ったもの）。"""

    def __init__(self, item, L, base, n):
        self.it, self.L, self.n = item, L, n
        self.W, self.H = L['W'], L['H']
        self.imgs = _Img(base)
        self.actors = item.get('actors', [])

    # ---------------------------------------------- 役者1人の状態
    def _img_at(self, a, f):
        cur = a['img']
        for s in sorted(a.get('swap', []), key=lambda s: s['f']):
            if f >= s['f']:
                cur = s['img']
        lp = a.get('loop')
        if lp and lp['f'] <= f < lp.get('to_f', 10 ** 9):
            k = (f - lp['f']) // max(1, lp.get('every', 8))
            cur = lp['imgs'][k % len(lp['imgs'])]
        tk = a.get('talk')
        if tk:
            for r in (tk['ranges'] if 'ranges' in tk else [tk]):
                if r['f'] <= f < r['to_f'] and ((f - r['f']) // max(1, tk.get('every', 4))) % 2 == 0:
                    return tk['img']
        bl = a.get('blink')
        if bl and cur == a['img']:              # まばたきの絵は、もとの絵（口の形が同じもの）のときだけ
            every, seed = bl.get('every', 84), sum(map(ord, a['img']))
            ph = (f + seed * 7) % every
            if ph < 4 and not (tk and any(r['f'] <= f < r['to_f'] for r in (tk['ranges'] if 'ranges' in tk else [tk]))):
                return bl['img']
        return cur

    def _visible(self, a, f):
        i, o = a.get('in', {}), a.get('out', {})
        start = i.get('f', 0)
        end = o.get('f', self.n) + (o.get('dur', 10) if o.get('how', 'cut') != 'cut' else 0)
        return start <= f < min(end, self.n)

    def _motion(self, a, f):
        """(dx, dy, 拡大の倍率, 回転の角度, 不透明度, 灰色か)"""
        dx = dy = rot = 0.0
        sc, op, gray = 1.0, a.get('opacity', 1.0), a.get('gray', False)
        W = self.W
        i = a.get('in', {})
        how, a0, dur = i.get('how', 'pop'), i.get('f', 0), i.get('dur', 8)
        t = prog(f, a0, dur)
        if how == 'pop':
            sc *= 0.55 + 0.53 * ease_out(min(1, t / 0.7)) - 0.08 * max(0, (t - 0.7) / 0.3)
            op *= min(1, t * 3)
        elif how == 'up':
            dy += 260 * (1 - ease_out(t))
            op *= min(1, t * 2.5)
        elif how in ('slide_l', 'slide_r'):
            dx += (-1 if how == 'slide_l' else 1) * W * 0.75 * (1 - ease_out(t))
        elif how == 'fade':
            op *= t
        elif how == 'drop':
            # 上から落ちて「どすん」：重力で速くなりながら落ち（dur）、着地（f + dur）のあと小さく2回弾む（10フレーム）
            if f < a0 + dur:
                dy -= (a['place']['y'] + i.get('height', 500)) * (1 - ease_in(t))
            else:
                k = f - a0 - dur
                if k < 10:
                    dy -= i.get('bounce', 26) * abs(math.sin(math.pi * k / 5)) * (1 - k / 10)
        elif how == 'spin':
            # くるっと回りながら大きくなって出る（1回転）
            rot -= 360 * (1 - ease_out(t))
            sc *= 0.2 + 0.8 * ease_out(t)
            op *= min(1, t * 3)
        o = a.get('out')
        if o and o.get('how', 'cut') != 'cut':
            t = prog(f, o['f'], o.get('dur', 10))
            h = o['how']
            if h in ('slide_l', 'slide_r'):
                dx += (-1 if h == 'slide_l' else 1) * W * 0.8 * ease_in(t)
            elif h == 'down':
                dy += 320 * ease_in(t)
                op *= 1 - t
            elif h == 'fade':
                op *= 1 - t
            elif h == 'pop':
                sc *= 1 - 0.6 * ease_in(t)
                op *= 1 - t
        if a.get('bob'):
            dy += a['bob'] * math.sin(2 * math.pi * f / 46)
        for s in a.get('shake', []):
            if 0 <= f - s < 12:
                dx += 11 * math.sin((f - s) * 2.4) * (1 - (f - s) / 12)
        for s in a.get('hop', []):
            if 0 <= f - s < 10:
                dy -= 34 * math.sin(math.pi * (f - s) / 10)
        for s in a.get('nod', []):
            k = f - s
            if 0 <= k < 26:
                dy += 18 * (ease_out(k / 6) if k < 6 else 1 if k < 18 else 1 - ease_out((k - 18) / 8))
        for tl in sorted(a.get('tilt', []), key=lambda x: x['f']):
            if f >= tl['f']:
                prev = rot
                rot = prev + (tl['deg'] - prev) * ease_out(prog(f, tl['f'], tl.get('dur', 7)))
        g = a.get('ghost')
        if g and f >= g['f']:
            t = ease_out(prog(f, g['f'], g.get('dur', 8)))
            op *= 1 - (1 - g.get('opacity', 0.28)) * t
            gray = t > 0.5
        return dx, dy, sc, rot, max(0.0, min(1.0, op)), gray

    # ---------------------------------------------- 描く
    def _draw_img(self, canvas, a, f):
        rel = self._img_at(a, f)
        dx, dy, sc, rot, op, gray = self._motion(a, f)
        if op <= 0.003:
            return
        p = a['place']
        s = p.get('scale', 1.0)
        raw, bb = self.imgs.get(rel)
        ref = p.get('ref', 'head')
        rx, ry = HEAD if ref == 'head' else ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
        # 拡大・回転の軸：人物は足もと（絵の下端の中央）、小物は絵の中心
        px, py = ((bb[0] + bb[2]) / 2, bb[3]) if ref == 'head' else (rx, ry)
        flip = p.get('flip', False)
        im = self.imgs.scaled(rel, s * sc, flip, gray)
        ss = s * sc
        # 絵の左上が来る位置：参照点 (rx, ry) が place の (x, y) に。拡大の分は軸を中心に
        ax, ay = p['x'] + (px - rx) * s, p['y'] + (py - ry) * s              # 軸の画面上の位置
        ox, oy = ax - px * ss, ay - py * ss
        if flip:
            ox = ax - (raw.width - px) * ss
        layer = None
        if abs(rot) > 0.05:
            layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
            self._paste(layer, im, ox + dx, oy + dy)
            layer = layer.rotate(rot, resample=Image.BICUBIC, center=(ax + dx, ay + dy))
        if 'crop_bottom' in a or op < 1 or layer is not None:
            if layer is None:
                layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
                self._paste(layer, im, ox + dx, oy + dy)
            alpha = layer.getchannel('A')
            if op < 1:
                alpha = alpha.point(lambda v: int(v * op))
            if 'crop_bottom' in a:
                cb, fe = a['crop_bottom'], a.get('crop_feather', 70)
                mask = Image.new('L', canvas.size, 255)
                md = ImageDraw.Draw(mask)
                for yy in range(max(0, int(cb - fe)), self.H):
                    md.line([(0, yy), (self.W, yy)], fill=max(0, int(255 * (cb - yy) / fe)))
                alpha = Image.composite(alpha, Image.new('L', canvas.size, 0), mask)
            layer.putalpha(alpha)
            canvas.alpha_composite(layer)
        else:
            self._paste(canvas, im, ox + dx, oy + dy)

    @staticmethod
    def _paste(canvas, im, x, y):
        x, y = int(round(x)), int(round(y))
        # 画面の外にはみ出す分を切ってから重ねる（alpha_composite は負の位置を受け付けない）
        sx0, sy0 = max(0, -x), max(0, -y)
        sx1, sy1 = min(im.width, canvas.width - x), min(im.height, canvas.height - y)
        if sx1 <= sx0 or sy1 <= sy0:
            return
        canvas.alpha_composite(im.crop((sx0, sy0, sx1, sy1)), (x + sx0, y + sy0))

    def _draw_rain(self, canvas, a, f):
        r = a['rain']
        x0, y0, x1, y1 = r.get('region', [0, 0, self.W, self.H])
        _, _, _, _, op, _ = self._motion(dict(a, **{'in': dict(a.get('in', {}), how=a.get('in', {}).get('how', 'fade'))}), f)
        if op <= 0:
            return
        rnd = random.Random(r.get('seed', 7))
        n = int(r.get('count', 90))
        speed, slant = r.get('speed', 46), r.get('slant', 0.28)
        layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        hgt = y1 - y0
        for k in range(n):
            ln = rnd.uniform(38, 78)
            x = rnd.uniform(x0 - 80, x1)
            y = (rnd.uniform(0, hgt + 120) + speed * f * rnd.uniform(0.8, 1.2)) % (hgt + 120) + y0 - 120
            al = int(rnd.uniform(70, 150) * op * r.get('alpha', 1.0))
            fade = min(1.0, max(0.0, (y - y0) / 90))                 # 範囲の上の端はぼかす
            d.line([(x, y), (x + ln * slant, y + ln)], fill=(205, 225, 255, int(al * fade)), width=r.get('width', 3))
        canvas.alpha_composite(layer)

    def _draw_text(self, canvas, a, f):
        _, _, _, _, op, _ = self._motion(dict(a, **{'in': dict(a.get('in', {}), how=a.get('in', {}).get('how', 'fade'))}), f)
        if op <= 0:
            return
        layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        x, y = a['pos']
        draw_plain(layer, a['text'], (x, y), font(a.get('font', 'g'), a.get('size', 26)), stroke=a.get('stroke', 3),
                   fill=tuple(a.get('color', [255, 255, 255])) + (255,))
        if op < 1:
            layer.putalpha(layer.getchannel('A').point(lambda v: int(v * op)))
        canvas.alpha_composite(layer)

    def frame(self, f):
        canvas = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        for a in self.actors:
            if not self._visible(a, f):
                continue
            if 'rain' in a:
                self._draw_rain(canvas, a, f)
            elif 'text' in a:
                self._draw_text(canvas, a, f)
            else:
                self._draw_img(canvas, a, f)
        return canvas

    def still_frame(self):
        """動画ができる前の仮の静止画に使うフレーム（いちばん多くの役者が見えているところ）"""
        best, bf = -1, 0
        for f in range(0, self.n, 3):
            k = sum(1 for a in self.actors if self._visible(a, f) and 'rain' not in a)
            if k > best:
                best, bf = k, f
        return min(self.n - 1, bf + 10)


# ------------------------------------------------ 時刻（at）→ フレーム（f）
AT_KEYS_ONE = ('in', 'out', 'ghost')
AT_KEYS_LIST = ('shake', 'hop', 'nod')


def resolve_actor(a, at_frame):
    """役者の定義の at を f（項目の頭から何フレーム目か）に直した写しを返す。at_frame(at) → int"""
    b = dict(a)
    for k in AT_KEYS_ONE:
        if k in a:
            b[k] = dict(a[k])
            if 'at' in a[k]:
                b[k]['f'] = at_frame(a[k]['at']) + a[k].get('delay', 0)
            elif k == 'in':
                b[k]['f'] = a[k].get('delay', 0)
    for k in AT_KEYS_LIST:
        if k in a:
            b[k] = [at_frame(x) for x in a[k]]
    if 'swap' in a:
        b['swap'] = [dict(s, f=at_frame(s['at'])) for s in a['swap']]
    if 'tilt' in a:
        b['tilt'] = [dict(s, f=at_frame(s['at'])) for s in a['tilt']]
    for k in ('loop', 'talk'):
        if k in a:
            x = dict(a[k])
            if 'ranges' in x:
                x['ranges'] = [{'f': at_frame(r['from']), 'to_f': at_frame(r['to']) if 'to' in r else 10 ** 9} for r in x['ranges']]
            else:
                x['f'] = at_frame(x['from']) if 'from' in x else 0
                x['to_f'] = at_frame(x['to']) if 'to' in x else 10 ** 9
            b[k] = x
    return b


def image_files(item):
    """項目の中で使っている絵のファイル（相対パス）"""
    out = []
    for a in item.get('actors', []):
        for k in ('img',):
            if k in a:
                out.append(a[k])
        out += [s['img'] for s in a.get('swap', [])]
        if 'talk' in a:
            out.append(a['talk']['img'])
        if 'blink' in a:
            out.append(a['blink']['img'])
        if 'loop' in a:
            out += a['loop']['imgs']
    return list(dict.fromkeys(out))


def iter_ats(item):
    """項目の中の時刻の指定（at・talk/loop の from/to）を全部返す（目印の時刻を測るため）"""
    for a in item.get('actors', []):
        for k in AT_KEYS_ONE:
            if isinstance(a.get(k), dict) and 'at' in a[k]:
                yield a[k]['at']
        for k in AT_KEYS_LIST:
            yield from a.get(k, [])
        for k in ('swap', 'tilt'):
            for s in a.get(k, []):
                yield s['at']
        for k in ('loop', 'talk'):
            x = a.get(k)
            if x:
                for r in (x['ranges'] if 'ranges' in x else [x]):
                    for kk in ('from', 'to'):
                        if kk in r:
                            yield r[kk]
