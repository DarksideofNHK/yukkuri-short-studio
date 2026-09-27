#!/usr/bin/env python3
"""Premiere の自動保存（.prproj）から、読み込んだ文字クリップが Premiere の中でどうなったかを取り出す（読むだけ）。

usage:
  python3 inspect_prproj.py <プロジェクト.prproj か、それがあるフォルダ> [--grep 文字] [--all]

フォルダを渡すと「Adobe Premiere Pro Auto-Save」の中のいちばん新しい自動保存を読む（元のファイルには触らない）。
文字レイヤー（AE.ADBE Text）ごとに、文字（改行は ⏎ で表示）・フォント名・数値（文字サイズや縁取りの幅の候補）・位置を出す。
ユーザーにスクショを頼まなくても、フォント名が壊れていないか、改行が効いたか、サイズが何 px になったかが分かる。
"""
import argparse
import base64
import gzip
import re
import struct
from pathlib import Path


def latest(path):
    p = Path(path).expanduser()
    if p.is_file():
        return p
    cands = list(p.glob('Adobe Premiere Pro Auto-Save/*.prproj')) + list(p.glob('*.prproj'))
    if not cands:
        raise SystemExit(f'.prproj が見つからない: {p}')
    return max(cands, key=lambda x: x.stat().st_mtime)


def floats(raw):
    out = []
    for i in range(0, len(raw) - 3):
        f = struct.unpack('<f', raw[i:i + 4])[0]
        if 2 <= f <= 3000 and abs(f * 4 - round(f * 4)) < 1e-4 and f not in (512.0,):
            out.append(f)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path')
    ap.add_argument('--grep', help='この文字を含むレイヤーだけ出す')
    ap.add_argument('--all', action='store_true', help='同じ内容のレイヤーも全部出す')
    a = ap.parse_args()
    src = latest(a.path)
    s = gzip.open(src).read().decode('utf-8', 'ignore')
    print(f'読んだファイル: {src}')
    objs = {m.group(2): m.group(3) for m in re.finditer(r'<(\w+) ObjectID="(\d+)"[^>]*>(.*?)</\1>', s, re.S)}
    blobs = {}
    for body in objs.values():
        m = re.search(r'<StartKeyframeValue Encoding="base64" BinaryHash="([^"]+)">([^<]+)</StartKeyframeValue>', body)
        if m:
            blobs[m.group(1)] = base64.b64decode(m.group(2))
    seen = set()
    n = 0
    for m in re.finditer(r'<VideoFilterComponent ObjectID="(\d+)"[^>]*>(.*?)</VideoFilterComponent>', s, re.S):
        body = m.group(2)
        if 'AE.ADBE Text' not in body:
            continue
        inst = re.search(r'<InstanceName>(.*?)</InstanceName>', body)
        refs = re.findall(r'<Param Index="\d+" ObjectRef="(\d+)"/>', body)
        raw, pos = b'', ''
        for r in refs:
            pb = objs.get(r, '')
            pid = re.search(r'<ParameterID>(\d+)</ParameterID>', pb)
            if not pid:
                continue
            if pid.group(1) == '1':
                h = re.search(r'BinaryHash="([^"]+)"', pb)
                raw = blobs.get(h.group(1), b'') if h else b''
            elif pid.group(1) == '3':
                k = re.search(r'<StartKeyframe>[^,]+,([^,]+),', pb)
                pos = k.group(1) if k else ''
        txt = raw.decode('utf-8', 'ignore')
        runs = re.findall(r'[　-ヿ一-鿿＀-￯A-Za-z0-9+＋？！!?、。「」()（）\r\n ]{2,}', txt)
        fonts = [x.decode() for x in re.findall(rb'[A-Za-z][A-Za-z0-9\-]{5,60}', raw)]
        jp = [r for r in runs if re.search(r'[^\x00-\x7f]', r)]
        other = [r for r in runs if r.strip() and r not in fonts]
        text = max(jp, key=len) if jp else (max(other, key=len) if other else '')
        name = inst.group(1) if inst else ''
        if a.grep and a.grep not in name + text:
            continue
        key = (name, text, tuple(fonts), pos)
        if key in seen and not a.all:
            continue
        seen.add(key)
        n += 1
        print(f'- {name} | 文字「{text.replace(chr(13), "⏎").replace(chr(10), "↵")}」 | フォント {fonts[:2]} | '
              f'数値 {floats(raw)[:6]} | 位置 {pos}')
    print(f'文字レイヤー {n} 個（同じ内容は1つにまとめた）')


if __name__ == '__main__':
    main()
