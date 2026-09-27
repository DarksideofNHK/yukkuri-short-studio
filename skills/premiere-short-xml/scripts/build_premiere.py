#!/usr/bin/env python3
"""台本＋ナレーション音声＋テロップ定義（spec）から、Premiere Pro で読み込む素材一式（FCP7 XML）を作る。

usage:
  python3 build_premiere.py --spec path/to/spec.json [--out 出力フォルダ] [--no-measure]

出力（--out、省略時は spec と同じフォルダ）:
  {title}.xml / {title}_予備_ビンなし.xml … Premiere の「ファイル→読み込み」で開く
  media/…（音声のコピー、題名以外の画像：エンドカード・注記・ラベル・暗幕・背景の仮・図/スクショ枠）
  テロップ.srt / ナレーション.srt / 素材リスト.md / README.md / timeline.json / anchor_times.json

テロップ（spec の telop_mode）:
  text（既定）… Premiere の文字クリップ（FCP7 の Outline Text）。Premiere 上で打ち替えられる。1クリップ1色なので、
                 色が変わる行は別のトラックに分け、前の行ぶんを全角スペースの空行でそろえて縦に重ねる
  image        … 画像（PNG）。語ごとの色分け・影つき。Premiere 上では文字を直せない
テロップの出る時刻：目印（anchor）の手前までを同じ声・速さで yukkuri に読ませた長さで測る（yukkuri v2 の音声のとき。
結果は anchor_times.json にためる）。測れないときは文字数の比例で見積もる。
動く図（build_anim.py の出力 media_anim/*.mov）があり長さが合えば、静止画の代わりにそれを使う。
"""
import argparse
import difflib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import wave
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (COL, FONT_PS, LAYOUTS, layout_of, Shot, blank, color, dash, draw_plain, draw_rich, font,  # noqa: E402
                    render_chart_frame, render_quote, render_slot, wrap)
from PIL import Image, ImageDraw  # noqa: E402
from chars import CharAnim, image_files, iter_ats, resolve_actor  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
# 文字クリップは1行1クリップ。Premiere は複数行の文字を1行ずつ別のレイヤーに分け、行数に応じて自分で並べ直す
# （空行も1行と数える・行の間隔は文字サイズと同じ）ので、行ごとに別のクリップにして、高さは origin（原点）で指定する。
# 1行のクリップは origin=0 で「高さ/2 −（サイズ/8 + 2）」に文字の下端（ベースライン）が来て、origin の縦 v で v×高さ px 下がる
# （2026-09-27、Premiere 2026 で実測。Basic Motion の center は文字クリップには効かない）。

BINS = {'A': '01_ナレーション', 'v2': '02_図・スクショ・グラフ', 'bg': '03_背景_仮', 'end': '04_エンドカード',
        'note': '05_注記', 'label': '06_ラベル・暗幕', 'telop': '07_テロップ画像',
        'chars': '08_イラスト（人物など）'}   # ビン名＝読み込み用フォルダの素材フォルダ名
TRACK_NAMES = {'V1': '背景（仮）', 'V2': '図・スクショ・グラフ', 'V3': '暗幕（最初はオフ）',
               'V4': 'テロップ 説明役 1段目', 'V5': 'テロップ 説明役 2段目', 'V6': 'テロップ 説明役 3段目',
               'V7': 'テロップ 聞き手 1段目', 'V8': 'テロップ 聞き手 2段目', 'V9': 'エンドカード', 'V10': '注記',
               'V11': 'ラベル'}
DEFAULT_SPEAKERS = {'説明役': {'tracks': ['V4', 'V5', 'V6'], 'audio_track': 'A1'},
                    '聞き手': {'tracks': ['V7', 'V8'], 'audio_track': 'A2', 'listener': True}}
VOICE_SPEAKER = {'まりさ': '説明役', 'れいむ': '聞き手'}
CHAR_TRACK_NAME = 'イラスト（人物など）'


def track_layout(has_chars, speakers=None):
    """(元のトラック名 → 書き出すトラック名, 書き出すトラック名 → 中身, 役目 → トラック)。
    イラスト（spec の chars）があるときは V3 にイラストを入れ、暗幕から上を1つずつ上げる（テロップの下・図の上）。
    has_chars はイラストの段の数（True＝1段）。時間が重なるイラストは段を分ける（VC＝V3、VC2＝V4 …。最初の案件 の表）。"""
    lanes = int(has_chars)

    def mp(t):
        if not lanes or not t.startswith('V'):
            return t
        if t.startswith('VC'):
            return f'V{2 + int(t[2:] or 1)}'
        return f'V{int(t[1:]) + lanes}' if int(t[1:]) >= 3 else t
    names = {mp(k): v for k, v in TRACK_NAMES.items()}
    for k in range(1, lanes + 1):
        names[f'V{2 + k}'] = CHAR_TRACK_NAME + (f'（{k}段目）' if lanes > 1 else '')
    sp = speakers or DEFAULT_SPEAKERS
    roles = {'veil': mp('V3'), 'end': mp('V9'), 'note': mp('V10'), 'label': mp('V11'),
             'explainer': [mp(t) for t in sp.get('説明役', DEFAULT_SPEAKERS['説明役'])['tracks']],
             'listener': [mp(t) for t in sp.get('聞き手', DEFAULT_SPEAKERS['聞き手'])['tracks']],
             'chars': ('V3' if lanes == 1 else f'V3〜V{2 + lanes}') if lanes else None}
    return mp, names, roles


def slug(text, n=14):
    s = re.sub(r'[\s　／/？?！!「」『』、。,.:：・+＋…（）()％%〔〕《》]', '', text)
    return s[:n] or 'x'


def load_script(path):
    """台本を読む。Markdown の ``` ブロック内の「番号 話者：セリフ」か、TSV（番号<TAB>話者<TAB>セリフ）。"""
    src = Path(path).read_text(encoding='utf-8')
    body = src.split('```')[1] if path.suffix == '.md' and '```' in src else src
    lines = {}
    for l in body.strip().splitlines():
        l = l.strip()
        m = re.match(r'^L?(\d+)\s+([^：:\t]+)[：:](.+)$', l) or re.match(r'^L?(\d+)\t([^\t]+)\t(.+)$', l)
        if m:
            spk = m.group(2).strip()
            lines[int(m.group(1))] = (VOICE_SPEAKER.get(spk, spk), m.group(3).strip())
    if not lines:
        raise SystemExit(f'台本から行を読めません: {path}（「1 説明役：セリフ」の形で ``` の中に書く）')
    return lines


def load_manifest(path, file_key='fast_file', sec_key='fast_sec'):
    """音声の一覧を {行番号: {text, audio, sec, voice, speed, prepared, key}} で返す。
    yukkuri v2 の batch 出力（{"status": "complete", "items": [...]}）と、旧形式（行のリスト）の両方を読む。"""
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    out = {}
    if isinstance(data, dict) and 'items' in data:
        if data.get('status') != 'complete':
            raise SystemExit(f'音声の生成が終わっていない（status={data.get("status")}）: {path}')
        for x in data['items']:
            out[int(str(x['id']).lstrip('L'))] = {
                'text': x['text'], 'audio': (path.parent / x['file']).resolve(), 'sec': float(x['duration_seconds']),
                'voice': x['voice'], 'speed': x.get('speed'), 'prepared': x.get('prepared_text') or x['text'],
                'key': x.get('request_hash')}
    else:
        for e in data:
            rel = Path(e[file_key])
            for cand in (rel, path.parent / rel, path.parent.parent / rel):
                if cand.exists():
                    break
            else:
                raise SystemExit(f'音声ファイルが見つかりません: {rel}')
            out[int(e['id'])] = {'text': e['text'], 'audio': cand.resolve(), 'sec': float(e[sec_key]),
                                 'voice': e.get('voice'), 'speed': None, 'prepared': e['text'], 'key': None}
    return out


def prepared_prefix(text, prepared, p):
    """台本の p 文字目の手前までに当たる、エンジンに渡した文（読み置換後）の頭の部分"""
    if text == prepared:
        return text[:p]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, text, prepared, autojunk=False).get_opcodes():
        if i1 <= p < i2:
            return prepared[:j1 + (p - i1 if tag == 'equal' else 0)]
    return prepared


def mov_frames(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                          'stream=nb_read_packets', '-of', 'csv=p=0', str(path)], capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else -1


def unit_lines(u):
    """テロップ1つ分の行を [(文字, 色), ...] で返す。旧形式 text=[[(文字,色),...],...] は色の変わり目で行を分ける
    （1文字だけの切れ端は前の行につなぐ）。"""
    if 'lines' in u:
        return [(t, c) for t, c in u['lines']]
    out = []
    for spans in u['text']:
        cur = []
        for t, c in spans:
            if cur and (cur[-1][1] == c or len(t) <= 1):
                cur[-1] = (cur[-1][0] + t, cur[-1][1])
            elif not cur and len(t) <= 1 and out:
                out[-1] = (out[-1][0] + t, out[-1][1])
            else:
                cur.append((t, c))
        out.extend(cur)
    return out



class Builder:
    def __init__(self, spec_path, out, measure=True):
        self.spec_path = Path(spec_path).resolve()
        self.base = self.spec_path.parent
        self.spec = json.loads(self.spec_path.read_text(encoding='utf-8'))
        self.out = Path(out).resolve() if out else self.base
        self.L = layout_of(self.spec)
        self.fps = self.spec.get('fps', 30)
        self.media = self.out / 'media'
        self.mode = self.spec.get('telop_mode', 'text')
        self.speakers = self.spec.get('speakers', DEFAULT_SPEAKERS)
        self.font_ps = self.spec.get('font_ps', FONT_PS['m'])
        self.measure_ok = measure
        self.clips = []

    def frames(self, sec):
        return int(round(sec * self.fps))

    def save(self, img, key, name):
        folder = self.media / BINS[key]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        img.save(path)
        return path

    # ------------------------------------------------ タイミング
    def measure(self, M, todo):
        """(行, 文字位置) ごとに、その手前までを同じ声・速さで読ませた長さ（秒）。結果は anchor_times.json にためる。"""
        cpath = self.out / 'anchor_times.json'
        cache = json.loads(cpath.read_text(encoding='utf-8')) if cpath.exists() else {}
        times, missing = {}, []
        for i, p in sorted(set(todo)):
            if not M[i]['key']:
                continue
            ck = f'{M[i]["key"]}:{p}'
            if ck in cache:
                times[(i, p)] = cache[ck]
            else:
                missing.append((i, p, ck))
        if missing and self.measure_ok:
            yk = shutil.which('yukkuri') or str(Path.home() / '.local/bin/yukkuri')
            if not Path(yk).exists():
                print('注意: yukkuri が見つからないので、テロップの時刻は文字数の比例で見積もった')
            else:
                print(f'テロップ・動きの時刻を yukkuri で測定中（{len(missing)}か所）…')
                with tempfile.TemporaryDirectory() as tmp:
                    for i, p, ck in missing:
                        m = M[i]
                        wav = Path(tmp) / f'L{i:02d}_{p}.wav'
                        cmd = [yk, 'say', '-t', prepared_prefix(m['text'], m['prepared'], p), '-v', m['voice'], '--trim',
                               '-o', str(wav)]
                        if m['speed']:
                            cmd += ['--speed', str(m['speed'])]
                        r = subprocess.run(cmd, capture_output=True, text=True)
                        if r.returncode != 0 or not wav.exists():
                            print(f'注意: L{i:02d} の{p}文字目は測れなかったので比例で見積もった: {r.stderr.strip()[:160]}')
                            continue
                        with wave.open(str(wav), 'rb') as w:
                            times[(i, p)] = cache[ck] = round(w.getnframes() / w.getframerate(), 3)
                self.out.mkdir(parents=True, exist_ok=True)
                cpath.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        return times

    def timeline(self):
        sp = self.spec
        lines = load_script(self.base / sp['script'])
        audio = sp.get('audio', {})
        mpath = (self.base / (audio.get('manifest') or sp.get('manifest') or 'voice/manifest.json')).resolve()
        M = load_manifest(mpath, audio.get('file_key', sp.get('audio_key', 'fast_file')), audio.get('sec_key', 'fast_sec'))
        t = sp.get('start_offset_sec', 0.1)
        gap = sp.get('gap_sec', 0.2)
        L = {}
        for i in sorted(lines):
            spk, text = lines[i]
            if i not in M:
                raise SystemExit(f'音声の一覧（manifest）に L{i:02d} がない')
            m = M[i]
            if m['text'] != text:
                raise SystemExit(f'台本と音声の文が違う: L{i:02d}\n  台本: {text}\n  音声: {m["text"]}\n→ 音声を作り直すか台本を合わせる')
            L[i] = {'id': i, 'speaker': spk, 'text': text, 'audio': m['audio'], 'sec': m['sec'], 'voice': m['voice'],
                    'start': self.frames(t), 'dur': math.ceil(m['sec'] * self.fps)}
            L[i]['end'] = L[i]['start'] + L[i]['dur']
            t += m['sec'] + gap
        last = max(L)
        self.end_start = L[last]['end'] + self.frames(sp.get('tail_before_end_sec', 0.3))
        self.seq_end = self.end_start + self.frames(sp.get('end_card_sec', 2.5)) if sp.get('end_card') else self.end_start
        self.lead = sp.get('lead_frames', 2)
        self.L_lines = L
        # 目印の位置（テロップ・動きの手順）
        found = {}
        for i in sorted(L):
            text, pos_from, got = L[i]['text'], 0, []
            specs = sp.get('lines', {}).get(str(i), [])
            for k, u in enumerate(specs):
                p = text.find(u['anchor'], pos_from) if u.get('anchor') else -1
                if p < 0:
                    got.append((u, int(len(text) * k / max(1, len(specs))), False))
                else:
                    pos_from = p + len(u['anchor'])
                    got.append((u, p, True))
            found[i] = got
        step_pos = []
        for it in sp.get('v2', []):
            for s in it.get('steps', []):
                at = s.get('at')
                if isinstance(at, str):
                    at = {'line': it['from'], 'anchor': at}
                if isinstance(at, dict) and at.get('anchor'):
                    p = L[at['line']]['text'].find(at['anchor'])
                    if p < 0:
                        raise SystemExit(f'{it["id"]} の手順の目印「{at["anchor"]}」が L{at["line"]:02d} にない')
                    step_pos.append((at['line'], p))
        for it in sp.get('chars', []):
            for at in iter_ats(it):
                if isinstance(at, str):
                    at = {'line': it['from'], 'anchor': at}
                if isinstance(at, dict) and at.get('anchor'):
                    p = L[at['line']]['text'].find(at['anchor'])
                    if p < 0:
                        raise SystemExit(f'{it["id"]} の目印「{at["anchor"]}」が L{at["line"]:02d} にない')
                    step_pos.append((at['line'], p))
        todo = [(i, p) for i, g in found.items() for _, p, ok in g if ok and p > 0] + [x for x in step_pos if x[1] > 0]
        self.times = self.measure(M, todo)
        self.timing_note = f'{sum(1 for x in set(todo) if x in self.times)}/{len(set(todo))} か所を実測'
        units = []
        for i in sorted(L):
            prev = None
            for k, (u, p, ok) in enumerate(found[i]):
                st = self.anchor_frame(i, p)
                if prev is not None:
                    st = max(st, prev + 6)
                prev = st
                units.append({'line': i, 'k': k + 1, 'speaker': L[i]['speaker'], 'spec': u, 'start': st,
                              'timing': 'measured' if (i, p) in self.times else ('line' if p == 0 else 'estimate')})
        units.sort(key=lambda u: u['start'])
        for a, b in zip(units, units[1:]):
            a['end'] = b['start']
        if units:
            units[-1]['end'] = self.end_start
        for u in units:                          # hold：締めのテロップなど、エンドカードの終わりまで残す
            if u['spec'].get('hold'):
                u['end'] = self.seq_end
        self.units = units
        self.title_end = units[0]['start'] if units else self.line_out(min(L))

    def anchor_frame(self, i, p):
        l = self.L_lines[i]
        off = self.frames(self.times[(i, p)]) if (i, p) in self.times else int(l['dur'] * p / len(l['text']))
        return max(l['start'] + off - self.lead, self.line_in(i))

    def step_frame(self, it, s, st):
        """動きの手順 s が、図の先頭から何フレーム目か。at=目印（文字列か {line, anchor}）/ {line} / {frame}、on=範囲内の何番目のテロップか"""
        at = s.get('at')
        if 'on' in s:
            ev = [u['start'] for u in self.units if it['from'] <= u['line'] <= it['to']]
            k = s['on']
            return max(0, (ev[k - 1] if 1 <= k <= len(ev) else st) - st)
        if at is None:
            return 0
        if isinstance(at, (int, float)):
            return int(at)
        if isinstance(at, str):
            at = {'line': it['from'], 'anchor': at}
        if 'frame' in at:
            return int(at['frame'])
        i = at['line']
        if at.get('anchor'):
            return max(0, self.anchor_frame(i, self.L_lines[i]['text'].find(at['anchor'])) - st)
        return max(0, self.line_in(i) - st)

    def line_in(self, i):
        return max(0, self.L_lines[i]['start'] - self.lead)

    def line_out(self, i):
        return self.line_in(i + 1) if i + 1 in self.L_lines else self.end_start

    # ------------------------------------------------ テロップ
    def telop_px(self, key, listener, lines):
        """文字の大きさ（px）。text_scale の倍数にそろえ、いちばん長い行が画面幅に収まるまで小さくする。"""
        L = self.L
        ts = L['text_scale'] if self.mode == 'text' else 1
        px = L['telop_sizes'][key] * (L['listener_scale'] if listener else 1)
        px = max(ts, math.floor(px / ts) * ts)
        while px > 24 and max(font('m', px).getlength(t) for t, _ in lines) > L['telop_max_w']:
            px -= ts
        return px

    def motion_for(self, spec, listener, lines):
        mo = self.L['motion']
        if spec.get('motion') == 'title':
            return [(0, 96), (6, 100)]
        if spec.get('motion') == 'spin':
            return [(0, 20), (14, 100)]          # くるっと1回転しながら大きく（回転は add_telop で付ける）
        if spec.get('motion'):
            return mo.get(spec['motion'])
        if listener:
            return mo['soft']
        if spec.get('size') == 's':
            return None
        return mo['pop'] if {c for _, c in lines} & {'y', 'r'} else mo['rise']

    def add_telop(self, speaker, lines, start, end, size_key, spec, name_prefix, srt):
        cfg = self.speakers.get(speaker, DEFAULT_SPEAKERS['説明役'])
        cfg = dict(cfg, tracks=cfg['tracks'][spec.get('tracks_from', 0):])      # tracks_from：同じ時間に出ている別のテロップと段を分ける
        listener = cfg.get('listener', False)
        px = self.telop_px(size_key, listener, lines)
        sc = self.motion_for(spec, listener, lines)
        op = [(0, 0), (3, 100)] if (self.L['telop_fade'] and sc) else None
        if spec.get('fade_in'):
            op = [(0, 0), (spec['fade_in'], 100)]
        srt.append((start, end, '\n'.join(t for t, _ in lines)))
        if self.mode == 'image':
            img = draw_rich(blank(self.L), [[(t, c)] for t, c in lines], self.L['W'] / 2, self.L['telop_block_y'], px,
                            self.L['telop_max_w'])
            path = self.save(img, 'telop', f'{cfg["tracks"][0]}_{name_prefix}_{slug("".join(t for t, _ in lines))}.png')
            self.add(cfg['tracks'][0], path, start, end, 'telop', scale=sc, opacity=op)
            return
        if len(lines) > len(cfg['tracks']):
            raise SystemExit(f'{name_prefix}: 行が多すぎる（{len(lines)}行、トラックは{len(cfg["tracks"])}本）')
        L = self.L
        n = len(lines)
        # line_px：行ごとの文字の大きさ（px・text_scale の倍数）。ユーザーが Premiere で行ごとに拡大した題名などを写すとき
        pxs = spec.get('line_px') or [px] * n
        if len(pxs) != n:
            raise SystemExit(f'{name_prefix}: line_px の数（{len(pxs)}）が行の数（{n}）と違う')
        pitches = [p * L['line_pitch'] for p in pxs]
        block_y = spec.get('y', L['telop_block_y'])      # y：このテロップだけ中心の高さを変える
        top = block_y - sum(pitches) / 2
        for i, ((t, c), track) in enumerate(zip(lines, cfg['tracks'])):
            p, pitch = pxs[i], pitches[i]
            y_default = L['H'] / 2 - (p * L.get('base_k', 1 / 8) + L.get('base_b', 2))   # 1行・origin 0 のときのベースライン（実測。横は base_k）
            # 行の箱（高さ pitch）を telop_block_y を中心に積み、箱の中で字面（em）を上下中央に置いたときのベースライン
            base = top + sum(pitches[:i]) + (pitch - p) / 2 + 0.88 * p
            self.clips.append({'kind': 'text', 'track': track, 'start': start, 'end': end, 'text': t, 'px': p,
                               'color': c, 'name': f'{name_prefix} {t}', 'scale': sc, 'opacity': op,
                               'rotation': [(0, -360), (14, 0)] if spec.get('motion') == 'spin' else None,
                               'dissolve_in': spec.get('dissolve_in'),
                               'origin_v': round((base - y_default) / L['H'], 6), 'baseline': round(base, 1),
                               'cid': f'gi-{len(self.clips) + 1:03d}'})
        box = self.spec.get('telop_box')
        if box and spec.get('box', True):
            # 座布団：テロップ全体の後ろに角丸の四角（テロップと同じ拡大の動き。不透明度は Premiere で変えられる）
            w = max(font('m', p).getlength(t) for (t, _), p in zip(lines, pxs)) + L['stroke_px'] * 2 + box.get('pad_x', 34) * 2
            h = sum(pitches) + box.get('pad_y', 10) * 2
            rect = (round(L['W'] / 2 - w / 2), round(block_y - h / 2), round(L['W'] / 2 + w / 2), round(block_y + h / 2))
            spin = spec.get('motion') == 'spin'           # 回る文字の座布団は回さず、14フレームでふわっと出す
            self.boxes.append({'start': start, 'end': end, 'rect': rect, 'scale': None if spin else sc,
                               'fade_in': 14 if spin else spec.get('fade_in'),
                               'name': f'座布団_{name_prefix}'})

    def box_img(self, rect):
        box, L = self.spec['telop_box'], self.L
        img = blank(L)
        ImageDraw.Draw(img).rounded_rectangle(rect, radius=box.get('radius', 18), fill=tuple(box.get('color', [44, 44, 48])) + (255,))
        return img

    def add_boxes(self):
        """座布団を1本のトラック（暗幕の段）に並べる。時間が重なる（締めの hold など）ところは、前の座布団をそこで切り、
        2つを囲む1枚にして続ける。"""
        op = self.spec['telop_box'].get('opacity', 40)
        out = []
        for b in sorted(self.boxes, key=lambda b: b['start']):
            if out and out[-1]['end'] > b['start']:
                p = out[-1]
                old_end, p['end'] = p['end'], b['start']
                r0, r1 = p['rect'], b['rect']
                b = dict(b, rect=(min(r0[0], r1[0]), min(r0[1], r1[1]), max(r0[2], r1[2]), max(r0[3], r1[3])),
                         end=max(old_end, b['end']), scale=None, fade_in=None)
                if p['end'] <= p['start']:
                    out.pop()
            out.append(b)
        for b in out:
            x0, y0, x1, y1 = b['rect']
            path = self.save(self.box_img(b['rect']), 'label', f'座布団_{x1 - x0}x{y1 - y0}_y{(y0 + y1) // 2}.png')
            opk = [(0, 0), (b['fade_in'], op)] if b.get('fade_in') else op
            self.add('V3', path, b['start'], b['end'], 'label', name=b['name'], scale=b['scale'], opacity=opk)

    # ------------------------------------------------ 画像
    def end_card(self):
        L = self.L
        e = self.spec['end_card']
        img = Image.new('RGBA', (L['W'], L['H']), (0, 0, 0, 255))
        g = ImageDraw.Draw(img)
        for yy in range(L['H']):
            t = yy / L['H']
            g.line([(0, yy), (L['W'], yy)], fill=(int(18 + 10 * t), int(20 + 6 * t), int(34 - 14 * t), 255))
        k = L['end_scale']
        rows = e['lines']
        hs = [(r.get('size', 46) * k) * (1.9 if r.get('font', 'g') == 'm' else 1.6) for r in rows]
        sender_h = (200 * k) if e.get('sender') else 0
        y = L['H'] / 2 - (sum(hs) + sender_h) / 2
        for r, h in zip(rows, hs):
            cy = y + h / 2
            size = r.get('size', 46) * k
            if r.get('font', 'g') == 'm':
                spans = r['spans'] if 'spans' in r else [(r['text'], r.get('color', 'w'))]
                draw_rich(img, [spans], L['W'] / 2, cy, size, L['W'] - 120, boost=1.0)
            else:
                draw_plain(img, r['text'], (L['W'] / 2, cy), font('g', size), fill=color(r.get('color', 'w')) + (255,))
            y += h
        if e.get('sender'):
            bw = min(L['W'] - 160, 860)
            x0, y0 = (L['W'] - bw) / 2, y + 40 * k
            x1, y1 = x0 + bw, y0 + 140 * k
            dash(g, x0, y0, x1, y1, (255, 255, 255, 200), 3, 14)
            f = font('g', 30 * max(k, 0.8))
            for i, ln in enumerate(wrap(e['sender'], f, bw - 40)):
                draw_plain(img, ln, (L['W'] / 2, y0 + 45 * k + i * 42 * k), f, stroke=0)
        return img

    def sender_box(self, text):
        """発信者表示の点線の枠（透明の全画面。下1/3の上のほう）"""
        L = self.L
        img = blank(L)
        g = ImageDraw.Draw(img)
        bw = min(L['W'] - 160, 860)
        f = font('g', 30)
        lines = wrap(text, f, bw - 40)
        h = 40 + len(lines) * 42
        x0, y0 = (L['W'] - bw) / 2, L.get('sender_y', L['H'] * 0.73) - h / 2
        g.rounded_rectangle([x0, y0, x0 + bw, y0 + h], radius=12, fill=(0, 0, 0, 150))
        dash(g, x0, y0, x0 + bw, y0 + h, (255, 255, 255, 200), 3, 14)
        for i, ln in enumerate(lines):
            draw_plain(img, ln, (L['W'] / 2, y0 + 40 + i * 42), f, stroke=0)
        return img

    def note(self, text):
        L = self.L
        img = blank(L)
        size = L['note_size']
        parts = text.split('\n')
        if len(parts) > 1 or L.get('note_fit'):
            # 改行（\n）を書いた注記は、その位置で改行し、どの行も note_w に収まるまで字を小さくする（最小 note_min_size）。
            # 1字ずつの折り返しで「202／6年」のように変な位置で切れるのを防ぐ（NHK会長編 v1c、2026-09-28 ユーザー指示）
            mn = L.get('note_min_size', 20)
            while size > mn and max(font('g', size).getlength(p) for p in parts) > L['note_w']:
                size -= 1
            f = font('g', size)
            lines = [ln for p in parts for ln in wrap(p, f, L['note_w'])]
        else:
            f = font('g', size)
            lines = wrap(text, f, L['note_w'])
        step = size * 1.35
        y = L['note_y'] - (len(lines) - 1) * step / 2
        left = L.get('note_align') == 'left'           # note_align：注記を左寄せに（layout_overrides で {"note_align": "left"}）
        left_x = L.get('note_x', L['W'] / 2 - L['note_w'] / 2)   # note_x：左寄せのときの左端（省略で中央から note_w/2）
        for ln in lines:
            if left:
                draw_plain(img, ln, (left_x, y), f, anchor='lm', stroke=4)
            else:
                draw_plain(img, ln, (L['W'] / 2, y), f, stroke=4)
            y += step
        return img

    def label(self):
        L = self.L
        img = blank(L)
        d = ImageDraw.Draw(img)
        f = font('m', L['label_size'])
        x, y = L['label_pos']
        tw = f.getlength(self.spec['label'])
        h = L['label_size'] * 1.64
        d.rounded_rectangle([x, y, x + tw + L['label_size'], y + h], radius=10, fill=(190, 20, 20, 235))
        d.text((x + L['label_size'] / 2, y + h / 2), self.spec['label'], font=f, fill=(255, 255, 255, 255), anchor='lm')
        return img

    def veil(self):
        L = self.L
        img = blank(L)
        a = Image.new('L', (L['W'], L['H']), 0)
        ad = ImageDraw.Draw(a)
        top, bot = L['veil']
        mid, half = (top + bot) / 2, (bot - top) / 2
        for yy in range(int(top), int(bot)):
            t = 1 - abs(yy - mid) / half
            ad.line([(0, yy), (L['W'], yy)], fill=int(150 * min(1, t * 1.6)))
        img.putalpha(a)
        return img

    def bg(self, bg):
        L = self.L
        W, H = L['W'], L['H']
        if bg.get('image'):                     # イラスト・写真を画面いっぱいに（はみ出しは切る）して暗くする
            src = Image.open(self.base / bg['image']).convert('RGB')
            k = max(W / src.width, H / src.height)
            src = src.resize((math.ceil(src.width * k), math.ceil(src.height * k)), Image.LANCZOS)
            x0, y0 = (src.width - W) // 2, (src.height - H) // 2
            src = src.crop((x0, y0, x0 + W, y0 + H))
            mul = {'night': (0.30, 0.36, 0.58)}.get(bg.get('tint'), (1, 1, 1))
            dim = bg.get('dim', 0.5)
            r, g, b = src.split()
            src = Image.merge('RGB', [ch.point(lambda v, m=m: int(v * m * dim)) for ch, m in zip((r, g, b), mul)])
            return src.convert('RGBA')
        img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
        d = ImageDraw.Draw(img)
        for yy in range(H):
            t = yy / H
            d.line([(0, yy), (W, yy)], fill=(int(27 - 18 * t), int(39 - 29 * t), int(53 - 38 * t), 255))
        for k in range(-H, W, 90):
            d.line([(k, 0), (k + H, H)], fill=(255, 255, 255, 14), width=2)
        if bg.get('plain'):                     # 暗い無地（仮の文字なし）
            return img
        # 仮の文字は、テロップ・図・注記と重ならない画面の下のほうに置く
        draw_plain(img, bg['id'], (W / 2, L['bg_mark_y']), font('g', min(W, H) * 0.14), fill=(255, 255, 255, 30), stroke=0)
        draw_plain(img, '［差し替え］背景', (W / 2, L['bg_label_y']), font('g', 44), fill=(255, 230, 0, 255))
        for i, ln in enumerate(wrap(bg['label'], font('g', 38), min(900, W - 120))[:2]):
            draw_plain(img, ln, (W / 2, L['bg_label_y'] + 64 + i * 50), font('g', 38))
        tip = '縦1080×1920の素材か、横の素材を拡大して置く' if H > W else '横1920×1080の素材か、縦の素材を拡大して置く'
        draw_plain(img, tip + '（ゆっくり寄るモーション付き）', (W / 2, L['bg_tip_y']), font('g', 24),
                   fill=(210, 210, 210, 255), stroke=2)
        return img

    # ------------------------------------------------ 組み立て
    def add(self, track, path, start, end, bin_key, name=None, **kw):
        n = len(self.clips) + 1
        self.clips.append({'kind': 'file', 'track': track, 'path': Path(path), 'start': start, 'end': end, 'bin': BINS[bin_key],
                           'name': name or Path(path).stem, 'cid': f'ci-{n:03d}', 'mcid': f'mc-{n:03d}', 'fid': f'f-{n:03d}',
                           **kw})

    def build(self):
        sp, L = self.spec, self.L
        self.timeline()
        if self.media.exists():
            shutil.rmtree(self.media)
        # 音声
        adir = self.media / BINS['A']
        adir.mkdir(parents=True, exist_ok=True)
        for i, l in sorted(self.L_lines.items()):
            dst = adir / l['audio'].name
            shutil.copy(l['audio'], dst)
            at = self.speakers.get(l['speaker'], {}).get('audio_track', 'A1')
            self.add(at, dst, l['start'], l['end'], 'A')
        # テロップ（題名も同じトラックに、時間をずらして置く）
        srt = []
        self.boxes = []
        if sp.get('title_card'):
            tc = sp['title_card']
            lines = unit_lines(tc) if isinstance(tc, dict) else [(''.join(t for t, _ in spans), spans[0][1]) for spans in tc]
            spec = tc if isinstance(tc, dict) else {}
            spec = dict(spec, motion=spec.get('motion', 'title'), fade_in=spec.get('fade_in', 4))
            n0 = len(self.clips)
            self.add_telop('説明役', lines, 0, self.title_end, spec.get('size', 'm'), spec, '題名', srt)
            # text_start_f：題名の文字だけ遅らせて出す（座布団は 0 から）。冒頭にユーザーが Premiere で足した絵を出す間をあける
            for c in self.clips[n0:]:
                if c['kind'] == 'text' and spec.get('text_start_f'):
                    c['start'] = min(spec['text_start_f'], c['end'] - 1)
        for u in self.units:
            lines = unit_lines(u['spec'])
            self.add_telop(u['speaker'], lines, u['start'], u['end'], u['spec'].get('size', 'm'), u['spec'],
                           f'L{u["line"]:02d}-{u["k"]}', srt)
        # エンドカード・注記・ラベル・暗幕
        if sp.get('end_card') and sp['end_card'].get('style') == 'hold':
            # 締め：最後の行のテロップ（hold）と背景をそのまま残し、発信者表示だけ下1/3に重ねる
            if sp['end_card'].get('sender'):
                p = self.save(self.sender_box(sp['end_card']['sender']), 'end', 'エンドカード_発信者表示.png')
                self.add('V9', p, self.end_start, self.seq_end, 'end', opacity=[(0, 0), (6, 100)])
        elif sp.get('end_card'):
            p = self.save(self.end_card(), 'end', 'エンドカード.png')
            self.add('V9', p, self.end_start, self.seq_end, 'end', opacity=[(0, 0), (6, 100)])
        for nt in sp.get('notes', []):
            a, b = min(nt['lines']), max(nt['lines'])
            p = self.save(self.note(nt['text']), 'note', f'注記_L{a:02d}.png')
            self.add('V10', p, self.line_in(a), self.line_out(b), 'note')
        if sp.get('label'):
            self.add('V11', self.save(self.label(), 'label', f'ラベル_{slug(sp["label"])}.png'), 0, self.seq_end, 'label')
        if sp.get('telop_box'):
            self.add_boxes()             # 座布団があるときは暗幕を置かない（同じ段に座布団を並べる）
        else:
            self.add('V3', self.save(self.veil(), 'label', '暗幕_テロップ用_最初はオフ.png'), 0, self.end_start, 'label', disabled=True)
        # 背景の仮
        first = min(self.L_lines)
        self.bg_rows = []
        hold_end = bool(sp.get('end_card') and sp['end_card'].get('style') == 'hold')
        for bg in sp.get('backgrounds', []):
            st = 0 if bg['from'] == first else self.line_in(bg['from'])
            en = self.line_out(bg['to'])
            if hold_end and bg['to'] == max(self.L_lines):
                en = self.seq_end                # 締めの背景はエンドカードの終わりまで
            d = en - st
            if bg.get('anim'):                   # anim：動く背景の動画（media_anim/BG_{id}_動き.mov。作業フォルダの make_bg_anim.py などで作る）
                anim = self.out / 'media_anim' / f'BG_{bg["id"]}_動き.mov'
                if anim.exists() and mov_frames(anim) == d:
                    self.add('V1', anim, st, en, 'bg')
                    self.bg_rows.append((dict(bg, anim=True), st, en, anim))
                    continue
                print(f'注意: {anim.name} がないか長さが合わない（{d} フレーム必要）ので静止画の背景を使った → 背景の動画を作り直して build_premiere.py を流し直す')
            sc = [(0, 100), (d, 110)] if bg.get('motion', 'in') == 'in' else [(0, 110), (d, 100)]
            p = self.save(self.bg(bg), 'bg', f'{bg["id"]}_{slug(bg["label"], 12)}.png')
            self.add('V1', p, st, en, 'bg', scale=sc)
            self.bg_rows.append((bg, st, en, p))
        # 図・スクショ・グラフ
        self.v2_rows = []
        v2_timing = []
        cache = self.out / 'media_anim' / '_src'
        for it in sp.get('v2', []):
            st = 0 if it['from'] == first else self.line_in(it['from'])
            en = self.line_out(it['to'])
            if it.get('until'):          # until：行の途中（目印の言葉）で下げる。例 {"line": 6, "anchor": "井上樹彦"}（イラストを大きく見せる場所を空ける）
                en = st + self.step_frame(it, {'at': it['until']}, st)
            ev = [max(0, u['start'] - st) for u in self.units if it['from'] <= u['line'] <= it['to']]
            steps = [dict(s, f=self.step_frame(it, s, st)) for s in it.get('steps', [])]
            v2_timing.append({'id': it['id'], 'kind': it['kind'], 'start': st, 'end': en, 'ev': ev, 'steps': steps})
            anim = self.out / 'media_anim' / f'V2_{it["id"]}_動き.mov'
            if it['kind'] in ('chart', 'shot') and anim.exists():
                if mov_frames(anim) == en - st:
                    self.add('V2', anim, st, en, 'v2')
                    self.v2_rows.append((dict(it, anim=True), st, en, anim))
                    continue
                print(f'注意: {anim.name} の長さが合わないので静止画を使った → build_anim.py → build_premiere.py の順に実行し直す')
            if it['kind'] == 'slot':
                p = self.save(render_slot(it, L), 'v2', f'V2_{it["id"]}_{slug(it["label"], 14)}.png')
            elif it['kind'] == 'chart':
                p = self.save(render_chart_frame(it['chart'], L, static=True), 'v2', f'V2_{it["id"]}_{it["chart"]["type"]}.png')
            elif it['kind'] == 'quote':
                p = self.save(render_quote(it, L), 'v2', f'V2_{it["id"]}_引用.png')
            elif it['kind'] == 'shot':
                n = en - st
                p = self.save(Shot(dict(it, steps=steps), L, self.base, cache, n).frame(n - 1), 'v2', f'V2_{it["id"]}_スクショ.png')
            else:
                raise SystemExit(f'v2 の kind が不明: {it["kind"]}')
            self.add('V2', p, st, en, 'v2', opacity=[(0, 0), (5, 100)])
            self.v2_rows.append((it, st, en, p))
        # イラスト（人物など）：動く絵（media_anim/イラスト_*.mov）があり長さが合えばそれを、なければ仮の静止画
        self.char_rows = []
        chars_timing = []
        for it in sp.get('chars', []):
            st = 0 if it['from'] == first else self.line_in(it['from'])
            en = self.line_out(it['to'])
            if it.get('hold') and it['to'] == max(self.L_lines) and sp.get('end_card'):
                en = self.seq_end                # hold：締めのエンドカードの終わりまで残す（締めの図など）
            at_frame = lambda at, it=it, st=st: self.step_frame(it, {'at': at}, st)
            actors = [resolve_actor(a, at_frame) for a in it.get('actors', [])]
            name = f'イラスト_{it["id"]}_{slug(it.get("name", ""), 16)}'
            chars_timing.append({'id': it['id'], 'name': name, 'start': st, 'end': en, 'actors': actors,
                                 'files': image_files(it)})
            anim = self.out / 'media_anim' / f'{name}.mov'
            if anim.exists() and mov_frames(anim) == en - st:
                self.add('VC', anim, st, en, 'chars')
                self.clips[-1]['char_id'] = it['id']
                self.char_rows.append((dict(it, anim=True), st, en, anim))
                continue
            if anim.exists():
                print(f'注意: {anim.name} の長さが合わないので静止画を使った → build_anim.py → build_premiere.py の順に実行し直す')
            ca = CharAnim({'actors': actors}, L, self.base, en - st)
            p = self.save(ca.frame(ca.still_frame()), 'chars', f'{name}.png')
            self.add('VC', p, st, en, 'chars', opacity=[(0, 0), (4, 100)])
            self.clips[-1]['char_id'] = it['id']
            self.char_rows.append((it, st, en, p))
        # 時間が重なるイラストは段（トラック）を分ける：長いものから下の段に詰める（同じトラックに重ねると Premiere で欠ける）
        lane_end = []
        for c in sorted([c for c in self.clips if c['track'] == 'VC'], key=lambda c: (-(c['end'] - c['start']), c['start'])):
            k = next((i for i, spans in enumerate(lane_end) if all(c['end'] <= a or c['start'] >= b for a, b in spans)), None)
            if k is None:
                lane_end.append([])
                k = len(lane_end) - 1
            lane_end[k].append((c['start'], c['end']))
            c['track'] = 'VC' if k == 0 else f'VC{k + 1}'
        # トラックの並び（イラストがあれば V3 に入れて、暗幕から上を段の数だけ上げる）
        mp, self.track_names, self.roles = track_layout(len(lane_end), self.speakers)
        for c in self.clips:
            c['track'] = mp(c['track'])
        if sp.get('telop_box'):
            self.track_names[self.roles['veil']] = f'テロップの座布団（不透明度{sp["telop_box"].get("opacity", 40)}％）'
        # empty_tracks：空のトラック（例 {"V13": "…"}）。前の版でユーザーが Premiere で足したクリップを貼る場所
        self.track_names.update(sp.get('empty_tracks', {}))
        # 書き出し
        title = sp['title']
        markers = [(l['start'], f'L{i:02d} {l["speaker"]}', l['text']) for i, l in sorted(self.L_lines.items())]
        if sp.get('end_card'):
            markers.append((self.end_start, 'エンドカード', '発信者表示などを公開前に確認'))
        self.write_xml(markers, True, self.out / f'{title}.xml')
        self.write_xml(markers, False, self.out / f'{title}_予備_ビンなし.xml')
        self.write_srt(srt)
        self.write_list()
        self.write_readme()
        tl = {'fps': self.fps, 'size': [L['W'], L['H']], 'layout': sp.get('layout', 'vertical'), 'telop_mode': self.mode,
              'seq_end_frames': self.seq_end, 'seq_end_sec': round(self.seq_end / self.fps, 2), 'timing': self.timing_note,
              'lines': [{k: (str(v) if isinstance(v, Path) else v) for k, v in l.items()} for _, l in sorted(self.L_lines.items())],
              'units': [{'line': u['line'], 'k': u['k'], 'start': u['start'], 'end': u['end'], 'timing': u['timing'],
                         'text': ' / '.join(t for t, _ in unit_lines(u['spec']))} for u in self.units],
              'v2': v2_timing, 'chars': chars_timing,
              'track_names': self.track_names, 'track_roles': self.roles,
              'clips': [{'track': c['track'], 'name': c['name'], 'start': c['start'], 'end': c['end'],
                         **({'text': c['text'], 'px': c['px'], 'color': c['color'], 'origin_v': c['origin_v'],
                                 'baseline': c['baseline']} if c['kind'] == 'text' else
                            {'file': str(c['path']), 'bin': c['bin'], 'alpha': self.final_alpha(c)})} for c in self.clips]}
        (self.out / 'timeline.json').write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding='utf-8')
        ntext = sum(1 for c in self.clips if c['kind'] == 'text')
        print(f'OK: {self.out / (title + ".xml")}（クリップ {len(self.clips)} 個うち文字 {ntext}、{self.seq_end / self.fps:.2f}秒、'
              f'{L["W"]}×{L["H"]}、時刻 {self.timing_note}）')

    @staticmethod
    def final_alpha(c):
        """プレビュー用：クリップの不透明度の最後の値（0〜1）"""
        o = c.get('opacity')
        if isinstance(o, (int, float)):
            return o / 100
        return o[-1][1] / 100 if o else 1.0

    # ------------------------------------------------ XML
    def rate(self):
        return f'<rate><timebase>{self.fps}</timebase><ntsc>FALSE</ntsc></rate>'

    @staticmethod
    def pathurl(p):
        return 'file://localhost' + urllib.parse.quote(str(Path(p).resolve()))

    @staticmethod
    def kf(pid, name, keys, vmax, vmin=0):
        ks = ''.join(f'<keyframe><when>{w}</when><value>{v}</value></keyframe>' for w, v in keys)
        return (f'<parameter authoringApp="PremierePro"><parameterid>{pid}</parameterid><name>{name}</name>'
                f'<valuemin>{vmin}</valuemin><valuemax>{vmax}</valuemax><value>{keys[-1][1]}</value>{ks}</parameter>')

    def filters(self, c):
        out = ''
        if c.get('scale') or c.get('rotation'):
            # 回転（rotation）は文字クリップにも画像にも読み込まれる（2026-09-27 検証_XMLトランジション_v1 で確認）
            out += ('<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>'
                    '<effecttype>motion</effecttype><mediatype>video</mediatype>'
                    + (self.kf('scale', 'Scale', c['scale'], 1000) if c.get('scale') else '')
                    + (self.kf('rotation', 'Rotation', c['rotation'], 8640, -8640) if c.get('rotation') else '')
                    + '</effect></filter>')
        if isinstance(c.get('opacity'), (int, float)):      # 動かない不透明度（座布団など）
            out += ('<filter><effect><name>Opacity</name><effectid>opacity</effectid><effectcategory>motion</effectcategory>'
                    '<effecttype>motion</effecttype><mediatype>video</mediatype><parameter authoringApp="PremierePro">'
                    f'<parameterid>opacity</parameterid><name>opacity</name><valuemin>0</valuemin><valuemax>100</valuemax>'
                    f'<value>{c["opacity"]}</value></parameter></effect></filter>')
        elif c.get('opacity'):
            out += ('<filter><effect><name>Opacity</name><effectid>opacity</effectid><effectcategory>motion</effectcategory>'
                    '<effecttype>motion</effecttype><mediatype>video</mediatype>' + self.kf('opacity', 'opacity', c['opacity'], 100)
                    + '</effect></filter>')
        return out

    @staticmethod
    def num(v):
        return str(int(round(v))) if abs(v - round(v)) < 1e-6 else f'{v:.2f}'

    def text_item(self, c):
        """文字クリップ（FCP7 の Outline Text ジェネレーター）。Premiere では編集できる文字のレイヤーになる。"""
        L = self.L
        d = c['end'] - c['start']
        ts = L['text_scale']
        r, g, b = color(c['color'])

        def par(pid, name, value, lo=None, hi=None):
            rng = f'<valuemin>{lo}</valuemin><valuemax>{hi}</valuemax>' if lo is not None else ''
            return f'<parameter><parameterid>{pid}</parameterid><name>{name}</name>{rng}<value>{value}</value></parameter>'
        text = escape(c['text'])
        params = (par('str', 'Text', text)
                  + par('fontname', 'Font', escape(self.font_ps))
                  + par('fontsize', 'Size', self.num(c['px'] / ts), 0, 1000)
                  + par('fontstyle', 'Style', 1, 1, 4)
                  + par('fontalign', 'Alignment', 2, 1, 3)
                  + par('fontcolor', 'Font Color', f'<alpha>255</alpha><red>{r}</red><green>{g}</green><blue>{b}</blue>')
                  + par('origin', 'Origin', f'<horiz>0</horiz><vert>{c.get("origin_v", 0)}</vert>')
                  + par('linewidth', 'Line Width', self.num(L['stroke_px'] / ts), 0, 200)
                  + par('linesoftness', 'Line Softness', 0, 0, 100)
                  + par('linecolor', 'Line Color', '<alpha>255</alpha><red>0</red><green>0</green><blue>0</blue>')
                  + par('textopacity', 'Text Opacity', 100, 0, 100))
        trans = ''
        if c.get('dissolve_in'):
            # 頭にクロスディゾルブ（alignment start）。Premiere で「クロスディゾルブ」として読み込まれる（2026-09-27 確認）
            trans = (f'<transitionitem>{self.rate()}<start>{c["start"]}</start><end>{c["start"] + c["dissolve_in"]}</end>'
                     '<alignment>start</alignment><effect><name>Cross Dissolve</name><effectid>Cross Dissolve</effectid>'
                     '<effectcategory>Dissolve</effectcategory><effecttype>transition</effecttype><mediatype>video</mediatype>'
                     '<wipecode>0</wipecode><wipeaccuracy>100</wipeaccuracy><startratio>0</startratio><endratio>1</endratio>'
                     '<reverse>FALSE</reverse></effect></transitionitem>')
        return trans + (f'<generatoritem id="{c["cid"]}"><name>{escape(c["name"])}</name><duration>{d}</duration>{self.rate()}'
                f'<start>{c["start"]}</start><end>{c["end"]}</end><in>0</in><out>{d}</out><enabled>TRUE</enabled>'
                '<anamorphic>FALSE</anamorphic><alphatype>black</alphatype>'
                '<effect><name>Outline Text</name><effectid>Outline Text</effectid><effectcategory>Text</effectcategory>'
                f'<effecttype>generator</effecttype><mediatype>video</mediatype>{params}</effect>'
                f'{self.filters(c)}<sourcetrack><mediatype>video</mediatype></sourcetrack></generatoritem>')

    def file_def(self, c):
        d = c['end'] - c['start']
        head = f'<file id="{c["fid"]}"><name>{escape(c["path"].name)}</name><pathurl>{self.pathurl(c["path"])}</pathurl>{self.rate()}<duration>{d}</duration>'
        if c['track'].startswith('A'):
            return head + ('<media><audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate>'
                           '</samplecharacteristics><channelcount>1</channelcount></audio></media></file>')
        return head + (f'<media><video><duration>{d}</duration><samplecharacteristics><width>{self.L["W"]}</width>'
                       f'<height>{self.L["H"]}</height><anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio>'
                       '<fielddominance>none</fielddominance></samplecharacteristics></video></media></file>')

    def src_tag(self, c):
        return ('<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>' if c['track'].startswith('A')
                else '<sourcetrack><mediatype>video</mediatype></sourcetrack>')

    def clipitem(self, c, bins):
        if c['kind'] == 'text':
            return self.text_item(c)
        d = c['end'] - c['start']
        audio = c['track'].startswith('A')
        fileref = f'<file id="{c["fid"]}"/>' if bins else self.file_def(c)
        mc = f'<masterclipid>{c["mcid"]}</masterclipid>' if bins else ''
        extra = '' if audio else '<alphatype>straight</alphatype><pixelaspectratio>square</pixelaspectratio><anamorphic>FALSE</anamorphic>'
        return (f'<clipitem id="{c["cid"]}">{mc}<name>{escape(c["name"])}</name><enabled>{"FALSE" if c.get("disabled") else "TRUE"}</enabled>'
                f'<duration>{d}</duration>{self.rate()}<start>{c["start"]}</start><end>{c["end"]}</end><in>0</in><out>{d}</out>'
                f'{extra}{fileref}{"" if audio else self.filters(c)}{self.src_tag(c)}</clipitem>')

    def master(self, c):
        d = c['end'] - c['start']
        kind = 'audio' if c['track'].startswith('A') else 'video'
        return (f'<clip id="{c["mcid"]}"><masterclipid>{c["mcid"]}</masterclipid><ismasterclip>TRUE</ismasterclip>'
                f'<name>{escape(c["name"])}</name><duration>{d}</duration>{self.rate()}<media><{kind}><track>'
                f'<clipitem id="m{c["cid"]}"><masterclipid>{c["mcid"]}</masterclipid><name>{escape(c["name"])}</name>'
                f'<duration>{d}</duration>{self.rate()}{self.file_def(c)}{self.src_tag(c)}</clipitem></track></{kind}></media></clip>')

    def write_xml(self, markers, bins, path):
        L = self.L
        vt = [f'V{n}' for n in range(1, 1 + max([int(c['track'][1:]) for c in self.clips if c['track'].startswith('V')]
                                                + [int(t[1:]) for t in self.spec.get('empty_tracks', {})]))]
        at = ['A1', 'A2', 'A3', 'A4']
        by = {t: sorted([c for c in self.clips if c['track'] == t], key=lambda c: c['start']) for t in vt + at}
        trk = lambda t: '<track>' + ''.join(self.clipitem(c, bins) for c in by[t]) + '<enabled>TRUE</enabled><locked>FALSE</locked></track>'
        mx = ''.join(f'<marker><comment>{escape(c)}</comment><name>{escape(n)}</name><in>{f}</in><out>-1</out></marker>'
                     for f, n, c in markers)
        seq = (f'<sequence id="seq-1"><name>{escape(self.spec["title"])}</name><duration>{self.seq_end}</duration>{self.rate()}'
               f'<timecode>{self.rate()}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>'
               f'<in>-1</in><out>-1</out><media><video><format><samplecharacteristics>{self.rate()}<width>{L["W"]}</width>'
               f'<height>{L["H"]}</height><anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio>'
               f'<fielddominance>none</fielddominance><colordepth>24</colordepth></samplecharacteristics></format>'
               + ''.join(trk(t) for t in vt) + '</video><audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics>'
               '<depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>'
               + ''.join(trk(t) for t in at) + f'</audio></media>{mx}</sequence>')
        if bins:
            groups = {}
            for c in self.clips:
                if c['kind'] == 'file':
                    groups.setdefault(c['bin'], []).append(c)
            bx = ''.join(f'<bin><name>{escape(b)}</name><children>' + ''.join(self.master(c) for c in cs) + '</children></bin>'
                         for b, cs in sorted(groups.items()))
            body = f'<project><name>{escape(self.spec["title"])}</name><children>{bx}{seq}</children></project>'
        else:
            body = seq
        path.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">{body}</xmeml>\n', encoding='utf-8')

    # ------------------------------------------------ SRT・一覧・README
    def tc(self, f):
        ms = int(round(f / self.fps * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

    def mmss(self, f):
        s = f / self.fps
        return f'{int(s // 60)}:{s % 60:05.2f}'

    def write_srt(self, srt):
        with open(self.out / 'テロップ.srt', 'w', encoding='utf-8') as fh:
            for k, (a, b, t) in enumerate(sorted(srt), 1):
                fh.write(f'{k}\n{self.tc(a)} --> {self.tc(b)}\n{t}\n\n')
        with open(self.out / 'ナレーション.srt', 'w', encoding='utf-8') as fh:
            for k, (i, l) in enumerate(sorted(self.L_lines.items()), 1):
                fh.write(f'{k}\n{self.tc(l["start"])} --> {self.tc(l["end"])}\n{l["text"]}\n\n')

    def write_list(self):
        rows = ['# 素材リスト（差し替え用）', '', f'シーケンス「{self.spec["title"]}」の差し替え枠。時刻はシーケンス上の位置（分:秒）。', '',
                '## 背景（V1）', '', '| 枠 | 時刻 | 入れるもの | ファイル |', '|---|---|---|---|']
        for bg, st, en, p in self.bg_rows:
            now = ('（動く背景の動画）' if bg.get('anim') else
                   f'（今は {Path(bg["image"]).stem} を暗くしたもの。差し替えてもよい）' if bg.get('image') else
                   '（今は暗い無地。差し替えてもよい）' if bg.get('plain') else '')
            rows.append(f'| {bg["id"]} | {self.mmss(st)}〜{self.mmss(en)} | {bg["label"]}{now} | `{p.relative_to(self.out)}` |')
        rows += ['', '## 図・スクショ・グラフ（V2）', '', '| 枠 | 時刻 | 中身 | 出典・メモ |', '|---|---|---|---|']
        for it, st, en, p in self.v2_rows:
            kind = '動き付き動画' if it.get('anim') else '静止画'
            if it['kind'] == 'slot':
                what, memo = f'［差し替え］{it["label"]}', f'{it.get("hint", "")} {it.get("url", "")}'.strip()
            elif it['kind'] == 'chart':
                what, memo = f'グラフ（{kind}・作成済み）：{it["chart"].get("title", "")}', '直すときは spec の chart を直して作り直す'
            elif it['kind'] == 'shot':
                what, memo = f'スクショ（{kind}・作成済み）：{it.get("caption", "")}', it.get('memo', '')
            else:
                qt = ' '.join(t if isinstance(t, str) else t[0] for t in it.get('lines', []))   # 行は文字か [文字, 色]
                what, memo = f'引用カード（作成済み）：{qt}', it.get('source', '')
            rows.append(f'| {it["id"]} | {self.mmss(st)}〜{self.mmss(en)} | {what} | {memo} |')
        if self.char_rows:
            rows += ['', f'## イラスト（{self.roles["chars"]}）', '', '| 枠 | 時刻 | 中身 | 使った絵 |', '|---|---|---|---|']
            for it, st, en, p in self.char_rows:
                kind = '動き付き動画' if it.get('anim') else '静止画（仮）'
                files = '、'.join(Path(x).stem for x in image_files(it))
                rows.append(f'| {it["id"]} | {self.mmss(st)}〜{self.mmss(en)} | {kind}：{it.get("memo", it.get("name", ""))} | {files} |')
        rows += ['', '## 権利・表現の注意', '', '- 実写は、関係のない人の顔が特定できないものにする',
                 '- ほかの人の動画・番組は、題名などの文字の引用にとどめ、映像・サムネイルは使わない',
                 '- 人物の写真を使う場合は、画面に出典を入れる', '- スクショには出典（資料名とページ）を注記（V10）と合わせて出す']
        rows += [f'- {x}' for x in self.spec.get('extra_notes', [])]
        (self.out / '素材リスト.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')

    def write_readme(self):
        sp, L = self.spec, self.L
        title = sp['title']
        vertical = L['H'] > L['W']
        fill_tip = ('16:9 の素材で縦を埋めるには、スケールを約316％にする（寄りのキーフレームも同じ割合で上げる）' if vertical
                    else '9:16 の素材で横を埋めるには、スケールを約316％にする（または左右をぼかし背景で埋める）')
        vt = sorted({c['track'] for c in self.clips if c['track'].startswith('V')} | set(self.spec.get('empty_tracks', {})),
                    key=lambda t: -int(t[1:]))
        track_rows = '\n'.join(f'| {t} | {self.track_names.get(t, "")} |' for t in vt)
        R = self.roles
        ex, li = R['explainer'], R['listener']
        telop_tracks = f'1段目 {ex[0]}・2段目 {ex[1]}・3段目 {ex[2]}、聞き手は {li[0]}・{li[1]}'
        tb = self.spec.get('telop_box')
        veil_note = (f"{R['veil']} はテロップの座布団（グレーの角丸の四角・不透明度{tb.get('opacity', 40)}％）。濃さは各クリップの「不透明度」で変えられる"
                     "（1つ直して、ほかは「属性をペースト」で）。テロップを打ち替えて長さが変わったら、座布団の「スケール」の幅を直す" if tb else
                     f"{R['veil']} の暗幕は最初はオフ（実写が明るくて文字が読みにくいときに有効にする）。")
        cmd = f'python3 {SCRIPTS / "build_all.py"} --spec "{self.spec_path}" --out "{self.out}"'
        text_part = f"""## テロップ（Premiere 上で打ち替えられる文字クリップ）

- テロップは画像ではなく**文字クリップ**。ダブルクリック（または文字ツール）で打ち替えられる。書体・色・縁取りはエッセンシャルグラフィックス（プロパティ）パネルで変えられる
- テロップは1行ずつ別の文字クリップ（{telop_tracks}）。行の高さはクリップごとに決めてあるので、1つのクリップに行を足さない（行を増やすときはクリップを複製して、エッセンシャルグラフィックスの「位置」の Y をずらす）
- 出るときの動き（スケールのキーフレーム）は各クリップに入っている。同じテロップの段はまとめて同じ動きをする
- 書体は `{self.font_ps}`（ヒラギノ明朝 ProN W6）。「フォントを解決」の画面が出たら、読み込んだ後に「グラフィックとタイトル」→「プロジェクト内のフォントを置換」で、まとめて置き換えられる
- 文字の大きさは、1行が画面幅に収まるように自動で小さくしてある（長い行だけ小さい）
- 題名以外の、エンドカード・注記・ラベルは画像（文字を直すときは spec を直して作り直す）

### うまく出ないとき

| 見え方 | 直し方 |
|---|---|
| 「フォントを解決」の画面が出た | 「グラフィックとタイトル」→「プロジェクト内のフォントを置換」でヒラギノ明朝 ProN W6 にまとめて置き換える |
| テロップの行が重なる・上の図にかかる | 行の高さの計算（common.py の telop_block_y・line_pitch）を見直して作り直す |
| 文字が大きすぎる・小さすぎる | spec の layout の text_scale（縦は 4.0）を見直して作り直す |
| 縁取りが出ない | エッセンシャルグラフィックスで「境界線」を足し、スタイルとして保存してほかのテロップに当てる |
""" if self.mode == 'text' else """## テロップ（画像）

テロップは画像なので Premiere 上では文字を直せない。spec を直して作り直す。
"""
        chars_part = (f"""## イラスト（{R['chars']}）

人物などのイラストは、ナレーションに合わせて動く動画（`media_anim/イラスト_*.mov`、ProRes 4444・透明部分あり）。1本ずつ別のクリップなので、Premiere 上で位置・大きさを変える・短くする・消すことができる（絵の中の動きは spec の chars を直して作り直す）。動きの確認は `media_anim/プレビュー_イラスト.mp4`。

""" if R.get('chars') else '')
        text = f"""# Premiere 用素材：{title}（{L['W']}×{L['H']}・{self.fps}fps・約{self.seq_end / self.fps:.0f}秒）

## 読み込み方

1. Premiere Pro で「ファイル」→「読み込み…」で `{title}.xml` を選ぶ → ビンとシーケンス「{title}」ができる
2. 開いて確認したら、プロジェクトを保存する

読み込めない場合は `{title}_予備_ビンなし.xml` を使う（素材がビンに分かれないだけで中身は同じ）。XML は素材を絶対パスで指すので、フォルダを移動したら作り直してから読み込む。

## トラック

| トラック | 中身 |
|---|---|
{track_rows}
| A1〜A2 | ナレーション（話者ごと・1行ずつ別クリップ） |
| A3・A4 | BGM・効果音（空） |

各行の頭にシーケンスマーカー（行番号・話者・セリフ）がある。{veil_note}

{text_part}{chars_part}
## 図・スクショ・グラフ（V2）

グラフとスクショは、ナレーションに合わせて動く動画（`media_anim/V2_*_動き.mov`、ProRes 4444・透明部分あり）。スクショは、資料が出る→寄る→マーカーを引く→ハンコ、の動きが目印の言葉に合わせて入っている。動きの確認は `media_anim/プレビュー_V2.mp4`。［差し替え］枠には自分でスクショ・写真を置く。

## 差し替え（モーションを残したまま）

- 背景（V1）：タイムラインの仮の素材を選び、プロジェクトパネルの素材を Option（Windows は Alt）を押しながらドラッグして重ねる。または右クリック「クリップを置き換え」→「ビンから」
- {fill_tip}
- 素材の候補・出典・権利の注意は `素材リスト.md`

## 作り直し（音声が変わったときも、これ1つで全部そろう）

```bash
{cmd}
```

`media/` と `media_anim/` と XML を作り直す（Premiere で作業を始めていたら、先に別のフォルダに写しておく）。新しい XML を読み込むと新しいシーケンスができる。
"""
        extra = sp.get('readme_extra', [])
        if extra:
            text += '\n## この版のメモ\n\n' + '\n'.join(f'- {x}' for x in extra) + '\n'
        (self.out / 'README.md').write_text(text, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--out')
    ap.add_argument('--no-measure', action='store_true', help='yukkuri で時刻を測らない（文字数の比例で見積もる）')
    a = ap.parse_args()
    Builder(a.spec, a.out, measure=not a.no_measure).build()


if __name__ == '__main__':
    main()
