#!/usr/bin/env python3
"""ゆっくりボイス（yukkuri v2）を AI から使うための補助ツール。詳しくは ../SKILL.md。

  yk.py make    台本.md --outdir 音声/v1 --speed 190 [--line-speed 12=180] [--map 説明役=まりさ]
                [--reading-dict 読み辞書.json] [--reading 表記=読み] [--resume | --force] [--no-check] [--gap 0.2]
  yk.py tsv     台本.md -o 台本.tsv --speed 190 [--line-speed 12=180] [--map 説明役=まりさ]
  yk.py check   音声/v1                     Whisper で聞き取り、台本と読みで照合する（1音でも違えば要確認）
  yk.py preview 音声/v1 [--gap 0.2]         全行を行間つきで1本にした確認用 WAV を作る

台本（.md / .txt）は「番号 話者：セリフ」の行を読む（``` の中を優先）。.tsv はそのまま yukkuri batch に渡す。
コマンド本体はリポジトリの tools/yukkuri（install.sh で ~/.local/bin/yukkuri に入れる）。
AquesTalkPlayer は利用者が公式サイトから別途入手する（インストーラーは同梱しない）。
課金 API は使わない（音声は AquesTalkPlayer、聞き取りはローカルの mlx-whisper、読みは MeCab）。
"""
import argparse
import csv
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import wave
from pathlib import Path

YUKKURI = shutil.which('yukkuri') or str(Path.home() / '.local/bin/yukkuri')
MECAB = shutil.which('mecab') or '/opt/homebrew/bin/mecab'
WHISPER_MODEL = 'mlx-community/whisper-large-v3-turbo'
DEFAULT_MAP = {'説明役': 'まりさ', '聞き手': 'れいむ'}
VOICES = {'れいむ', 'まりさ', 'こいし', 'さとり', 'れいむ速', 'まりさ速',
          'reimu', 'marisa', 'koishi', 'satori', 'reimu-fast', 'marisa-fast'}
LINE_RE = re.compile(r'^\s*L?(\d{1,4})[.．:：]?\s+([^\s：:|]+?)\s*[：:]\s*(.+?)\s*$')
PUNCT_RE = re.compile(r'[、。，．,.！？!?「」『』（）()・…―—\-~〜\s　]')


def fail(msg):
    print('エラー: ' + msg, file=sys.stderr)
    sys.exit(1)


def chars(text):
    """台本の字数（句読点・かぎかっこ・空白を除く）"""
    return len(PUNCT_RE.sub('', text))


# ---------------------------------------------------------------- 台本 → TSV
def parse_pairs(values, label, int_key=False):
    out = {}
    for v in values or []:
        if '=' not in v:
            fail(f'{label} は「左=右」で指定してください: {v}')
        k, val = v.split('=', 1)
        k, val = k.strip(), val.strip()
        out[int(k.lstrip('L')) if int_key else k] = int(val) if int_key else val
    return out


def parse_script(path, block=None):
    src = Path(path).read_text(encoding='utf-8-sig')
    parts = src.split('```')
    blocks = [parts[i] for i in range(1, len(parts), 2)]
    if block is not None:
        if not 1 <= block <= len(blocks):
            fail(f'--block {block} はありません（``` のブロックは {len(blocks)} 個）')
        chosen = blocks[block - 1]
    else:
        chosen = next((b for b in blocks if any(LINE_RE.match(l) for l in b.splitlines())), src)
    rows = [(int(m.group(1)), m.group(2), m.group(3))
            for m in map(LINE_RE.match, chosen.splitlines()) if m]
    if not rows:
        fail('台本に「番号 話者：セリフ」の行が見つかりません')
    ids = [r[0] for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        fail(f'番号が重複しています: {dup}（--block で ``` のブロックを選べます）')
    return rows


def to_tsv(rows, mapping, speed, line_speed):
    unknown = sorted({sp for _, sp, _ in rows if sp not in mapping and sp not in VOICES})
    if unknown:
        fail(f'声が決まっていない話者: {unknown}（--map 話者=まりさ のように指定）')
    out = ['番号\t声\tセリフ\t速度']
    for i, sp, text in rows:
        if '\t' in text:
            fail(f'L{i:02d} のセリフにタブ文字があります')
        s = line_speed.get(i, speed)
        out.append(f'{i:02d}\t{mapping.get(sp, sp)}\t{text}\t{"" if s is None else s}')
    return '\n'.join(out) + '\n'


def read_tsv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.reader(f, delimiter='\t') if r and any(r)]
    if rows and rows[0][:1] and rows[0][0].strip() in ('番号', 'id'):
        rows = rows[1:]
    return [(int(r[0].strip().lstrip('L')), r[1].strip(), r[2]) for r in rows]


def reading_args(a):
    args = []
    if a.reading_dict:
        args += ['--reading-dict', str(Path(a.reading_dict).expanduser().resolve())]
    for r in a.reading or []:
        args += ['--reading', r]
    return args


# ---------------------------------------------------------------- 参考読み（MeCab）
def kana_screen(rows, rargs, outdir):
    res = []
    for i, _, text in rows:
        p = subprocess.run([YUKKURI, 'kana', '--text', text, '--json'] + rargs,
                           capture_output=True, text=True)
        if p.returncode != 0:
            fail(f'L{i:02d} の参考読みに失敗: {p.stderr.strip()}')
        d = json.loads(p.stdout)
        # 数字は MeCab では読めないがエンジンは読める（2024年度・25億円などで確認済み）ので除く
        unknown = [u for u in d.get('unknown', []) if not re.fullmatch(r'[0-9０-９,，.．]+', u)]
        res.append({'id': f'L{i:02d}', 'text': text, 'kana': d.get('kana', ''), 'unknown': unknown})
    (outdir / '確認').mkdir(exist_ok=True)
    (outdir / '確認' / '参考読み.json').write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    flagged = [r for r in res if r['unknown']]
    print(f'参考読み（MeCab）：{len(res)}行。読めない語がある行 {len(flagged)}', file=sys.stderr)
    for r in flagged:
        print(f"  {r['id']} 読めない語 {'・'.join(r['unknown'])}：{r['kana']}", file=sys.stderr)
    return res


# ---------------------------------------------------------------- 聞き取り（Whisper）
WHISPER_CODE = r'''
import json, sys
import mlx_whisper
files, model = json.loads(sys.argv[1]), sys.argv[2]
out = {}
for f in files:
    r = mlx_whisper.transcribe(f, path_or_hf_repo=model, language='ja', verbose=None)
    out[f] = (r.get('text') or '').strip()
print('\n@@RESULT@@' + json.dumps(out, ensure_ascii=False))
'''


def whisper_interpreter():
    exe = shutil.which('mlx_whisper')
    if not exe:
        return None
    real = exe
    try:
        real = subprocess.run(['pyenv', 'which', 'mlx_whisper'], capture_output=True,
                              text=True, check=True).stdout.strip() or exe
    except (OSError, subprocess.CalledProcessError):
        pass
    try:
        first = Path(real).read_text(errors='ignore').splitlines()[0]
    except (OSError, IndexError):
        return None
    return first[2:].split() if first.startswith('#!') and 'python' in first else None


def transcribe(files):
    interp = whisper_interpreter()
    if interp:
        p = subprocess.run(interp + ['-c', WHISPER_CODE, json.dumps(files), WHISPER_MODEL],
                           capture_output=True, text=True)
        if p.returncode == 0 and '@@RESULT@@' in p.stdout:
            return json.loads(p.stdout.split('@@RESULT@@')[-1])
        print('mlx_whisper の一括処理に失敗。1ファイルずつ実行します: ' + p.stderr.strip()[-300:], file=sys.stderr)
    if not shutil.which('mlx_whisper'):
        fail('mlx_whisper が見つかりません（聞き取り確認は --no-check で省略できます）')
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        # CLI に複数ファイルを渡すと出力名が1つに潰れるため、1ファイルずつ名前を指定する
        for n, f in enumerate(files):
            try:
                subprocess.run(['mlx_whisper', f, '--model', WHISPER_MODEL, '--language', 'ja',
                                '-f', 'txt', '-o', tmp, '--output-name', f'f{n}', '--verbose', 'False'],
                               capture_output=True, text=True, check=True)
                out[f] = (Path(tmp) / f'f{n}.txt').read_text(encoding='utf-8').strip()
            except (subprocess.CalledProcessError, OSError) as e:
                print(f'聞き取りに失敗（要確認として扱う）: {Path(f).name}: {e}', file=sys.stderr)
                out[f] = ''
    return out


def yomi(texts):
    p = subprocess.run([MECAB, '-Oyomi'], input='\n'.join(texts) + '\n',
                       capture_output=True, text=True, check=True)
    lines = p.stdout.splitlines()
    return [lines[i] if i < len(lines) else '' for i in range(len(texts))]


def norm(s):
    s = PUNCT_RE.sub('', unicodedata.normalize('NFKC', s))
    return ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in s)


def load_manifest(outdir):
    path = outdir / 'manifest.json'
    if not path.exists():
        fail(f'manifest.json がありません: {path}')
    m = json.loads(path.read_text(encoding='utf-8'))
    return m, [x for x in m.get('items', []) if x.get('status') == 'done']


def yomi_diff(a, b):
    """読み（カタカナ）の食い違いを「ク→フ」の形で返す。同音異義（市／詩）は差にならない"""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [f'{a[i1:i2] or "∅"}→{b[j1:j2] or "∅"}'
            for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != 'equal']


def cmd_check(outdir):
    _, items = load_manifest(outdir)
    print(f'聞き取り確認（{WHISPER_MODEL}）：{len(items)}行…', file=sys.stderr)
    files = [str(outdir / x['file']) for x in items]
    heard = transcribe(files)
    src = [x.get('prepared_text') or x['text'] for x in items]
    hrd = [heard.get(f, '') for f in files]
    res = []
    for x, h, a, b in zip(items, hrd, map(norm, yomi(src)), map(norm, yomi(hrd))):
        d = yomi_diff(a, b)
        res.append({'id': x['id'], 'file': x['file'], 'voice': x['voice'], 'speed': x.get('speed'),
                    'sec': x.get('duration_seconds'), 'text': x['text'],
                    'prepared_text': x.get('prepared_text'), 'heard': h,
                    'yomi_text': a, 'yomi_heard': b, 'diff': d, 'flag': bool(d)})
    (outdir / '確認').mkdir(exist_ok=True)
    (outdir / '確認' / '聞き取り.json').write_text(
        json.dumps({'model': WHISPER_MODEL, 'items': res}, ensure_ascii=False, indent=1) + '\n',
        encoding='utf-8')
    return res


# ---------------------------------------------------------------- 通しの確認用 WAV
def cmd_preview(outdir, gap):
    _, items = load_manifest(outdir)
    params, frames = None, []
    for x in items:
        with wave.open(str(outdir / x['file']), 'rb') as w:
            p = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            if params and p != params:
                fail('形式の違う WAV が混ざっています: ' + x['file'])
            params = p
            frames.append(w.readframes(w.getnframes()))
    if not frames:
        fail('生成済みの行がありません')
    ch, sw, sr = params
    silence = b'\x00' * (int(round(gap * sr)) * sw * ch)
    out = outdir / '確認' / f'通し_行間{gap:g}秒.wav'
    out.parent.mkdir(exist_ok=True)
    with wave.open(str(out), 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(sw)
        w.setframerate(sr)
        for n, f in enumerate(frames):
            if n:
                w.writeframes(silence)
            w.writeframes(f)
    total = sum(len(f) for f in frames) / (sw * ch * sr) + gap * (len(frames) - 1)
    return out, round(total, 2)


# ---------------------------------------------------------------- 報告
def report(outdir, checked, preview):
    _, items = load_manifest(outdir)
    by_id = {r['id']: r for r in checked or []}
    print(f'\n| 行 | 声 | 話速 | 秒 | 字/秒 | 読みの差 | 聞き取り |\n|---|---|---:|---:|---:|---|---|')
    tot_sec = tot_chars = 0
    for x in items:
        sec, n = x.get('duration_seconds', 0), chars(x['text'])
        tot_sec, tot_chars = tot_sec + sec, tot_chars + n
        r = by_id.get(x['id'])
        diff = '' if not r else (f"**{' '.join(r['diff'])}**" if r['flag'] else 'なし')
        print(f"| {x['id']} | {x['voice']} | {x.get('speed')} | {sec:.2f} | {n / sec if sec else 0:.1f} | "
              f"{diff} | {r['heard'] if r else ''} |")
    print(f'\n声だけ {tot_sec:.2f}秒（{tot_chars}字・{tot_chars / tot_sec if tot_sec else 0:.1f}字/秒）')
    if preview:
        print(f'通し {preview[1]:.2f}秒（行間込み）：{preview[0]}')
    if checked:
        flagged = [f"{r['id']}（{' '.join(r['diff'])}）" for r in checked if r['flag']]
        print('聞き取りの要確認：' + ('・'.join(flagged) if flagged else 'なし'))
    print(f'出力：{outdir}')


# ---------------------------------------------------------------- コマンド
def cmd_make(a):
    outdir = Path(a.outdir).expanduser().resolve()
    src = Path(a.script).expanduser().resolve()
    if not src.exists():
        fail(f'台本がありません: {src}')
    if outdir.exists() and any(outdir.iterdir()) and not (a.resume or a.force):
        fail(f'出力先に既にファイルがあります: {outdir}\n'
             '  新しいフォルダを指定してください（途中で止まった続きは --resume、意図的な作り直しは --force）')
    outdir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == '.tsv':
        tsv, rows = src, read_tsv(src)
    else:
        rows = parse_script(src, a.block)
        if a.speed is None:
            print('注意: --speed がないので、声のプリセットの速さ（れいむ・まりさは100＝遅め）で作ります。'
                  'ショート動画なら --speed 180', file=sys.stderr)
        mapping = {**DEFAULT_MAP, **parse_pairs(a.map, '--map')}
        tsv = outdir / '台本.tsv'
        tsv.write_text(to_tsv(rows, mapping, a.speed, parse_pairs(a.line_speed, '--line-speed', True)),
                       encoding='utf-8')
    rargs = reading_args(a)
    kana_screen(rows, rargs, outdir)
    cmd = [YUKKURI, 'batch', str(tsv), '--outdir', str(outdir)] + rargs
    if a.speed is not None:
        cmd += ['--speed', str(a.speed)]
    if not a.no_trim:
        cmd.append('--trim')
    if a.resume:
        cmd.append('--resume')
    if a.force:
        cmd.append('--force')
    if subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode != 0:
        fail('yukkuri batch が止まりました。生成済みの行は残っています。台本を直して --resume で続きから')
    checked = None if a.no_check else cmd_check(outdir)
    report(outdir, checked, cmd_preview(outdir, a.gap))


def main():
    ap = argparse.ArgumentParser(description='ゆっくりボイス（yukkuri v2）の補助ツール')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def script_opts(p):
        p.add_argument('script', help='台本（.md / .txt。make は .tsv も可）')
        p.add_argument('--speed', type=int, help='全行の話速 50〜300（標準100。ショートは190）')
        p.add_argument('--line-speed', action='append', help='行ごとの話速 例 12=180（複数可）')
        p.add_argument('--map', action='append', help='話者=声 例 説明役=まりさ（既定 説明役=まりさ・聞き手=れいむ）')
        p.add_argument('--block', type=int, help='台本の何番目の ``` を読むか（既定：最初に行が見つかったもの）')

    p = sub.add_parser('make', help='台本 → TSV → 参考読み → 生成 → 聞き取り確認 → 通し WAV')
    script_opts(p)
    p.add_argument('--outdir', required=True)
    p.add_argument('--reading-dict')
    p.add_argument('--reading', action='append', help='表記=読み（複数可）')
    p.add_argument('--no-trim', action='store_true', help='前後の無音を残す（既定は --trim）')
    p.add_argument('--no-check', action='store_true', help='Whisper の聞き取り確認を省く')
    p.add_argument('--gap', type=float, default=0.2, help='通し WAV の行間（秒）')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--resume', action='store_true')
    mode.add_argument('--force', action='store_true')

    p = sub.add_parser('tsv', help='台本 → yukkuri batch 用 TSV')
    script_opts(p)
    p.add_argument('-o', '--output', required=True)
    p.add_argument('--force', action='store_true')

    p = sub.add_parser('check', help='生成済みフォルダを Whisper で聞き取り確認')
    p.add_argument('outdir')

    p = sub.add_parser('preview', help='生成済みフォルダから通しの確認用 WAV を作る')
    p.add_argument('outdir')
    p.add_argument('--gap', type=float, default=0.2)

    a = ap.parse_args()
    if a.cmd == 'make':
        cmd_make(a)
    elif a.cmd == 'tsv':
        out = Path(a.output).expanduser()
        if out.exists() and not a.force:
            fail(f'出力先が既にあります: {out}（上書きは --force）')
        rows = parse_script(a.script, a.block)
        out.write_text(to_tsv(rows, {**DEFAULT_MAP, **parse_pairs(a.map, '--map')}, a.speed,
                              parse_pairs(a.line_speed, '--line-speed', True)), encoding='utf-8')
        print(f'{out}（{len(rows)}行）')
    elif a.cmd == 'check':
        outdir = Path(a.outdir).expanduser().resolve()
        report(outdir, cmd_check(outdir), None)
    elif a.cmd == 'preview':
        out, total = cmd_preview(Path(a.outdir).expanduser().resolve(), a.gap)
        print(f'{out}（{total:.2f}秒）')


if __name__ == '__main__':
    main()
