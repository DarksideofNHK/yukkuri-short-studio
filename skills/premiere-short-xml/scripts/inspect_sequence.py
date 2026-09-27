#!/usr/bin/env python3
"""Premiere のプロジェクト（.prproj か自動保存）から、シーケンスのクリップの並びと手直しを取り出す（読むだけ）。

usage:
  python3 inspect_sequence.py <プロジェクト.prproj か、それがあるフォルダ> <シーケンス名> [--fx] [--text] [--diff]

- 各トラックのクリップ：時刻（秒とフレーム）・名前
- --fx   ：モーション（位置・スケール）・不透明度・ベクトルモーション・文字レイヤーの位置
- --text ：文字クリップの中身（ユーザーが打ち替えた文字）と文字サイズ
- --diff ：同じ名前のシーケンスが2つあるとき（XML を読み込むと2つできることがある）、1つ目と2つ目の違いだけ出す。
           ユーザーが Premiere で直したところ（長さ・位置・足したクリップ・打ち替え）が分かる
フォルダを渡すと「Adobe Premiere Pro Auto-Save」の中のいちばん新しい自動保存を読む。元のファイルには書かない。
inspect_prproj.py は文字レイヤーの書式を見るもの、こちらはシーケンスの中身（手直し）を見るもの。
"""
import argparse
import base64
import difflib
import gzip
import re
import struct
from pathlib import Path

TPS = 254016000000          # Premiere の時間の単位（1秒あたり）


def latest(path):
    p = Path(path).expanduser()
    if p.is_file():
        return p
    cands = list(p.glob('Adobe Premiere Pro Auto-Save/*.prproj')) + list(p.glob('*.prproj'))
    if not cands:
        raise SystemExit(f'.prproj が見つからない: {p}')
    return max(cands, key=lambda x: x.stat().st_mtime)


class Proj:
    def __init__(self, src):
        raw = gzip.open(src).read().decode('utf-8', 'ignore')
        self.objs = {m.group(3): (m.group(1), m.group(4))
                     for m in re.finditer(r'<(\w+) (ObjectU?ID)="([^"]+)"[^>]*>(.*?)</\1>', raw, re.S)}
        self.blobs = {}
        for _, b in self.objs.values():
            m = re.search(r'<StartKeyframeValue Encoding="base64" BinaryHash="([^"]+)">([^<]+)</StartKeyframeValue>', b)
            if m:
                self.blobs[m.group(1)] = base64.b64decode(m.group(2))

    def get(self, ref):
        return self.objs.get(ref, (None, ''))

    def sequences(self, name):
        return [(k, b) for k, (t, b) in self.objs.items() if t == 'Sequence' and f'<Name>{name}</Name>' in b]

    def text_of(self, pb):
        h = re.search(r'BinaryHash="([^"]+)"', pb)
        data = self.blobs.get(h.group(1), b'') if h else b''
        txt = data.decode('utf-8', 'ignore')
        runs = [r for r in re.findall(r'[　-ヿ一-鿿＀-￯A-Za-z0-9+＋？！!?、。「」()（）.\r\n ]+', txt)
                if re.search(r'[^\x00-\x7f]', r)]
        sizes = sorted({round(struct.unpack('<f', data[i:i + 4])[0]) for i in range(len(data) - 3)
                        if 8 <= struct.unpack('<f', data[i:i + 4])[0] <= 3000
                        and abs(struct.unpack('<f', data[i:i + 4])[0] % 1) < 1e-4} - {512})
        return (max(runs, key=len).strip() if runs else ''), sizes

    def effects(self, comp_ref, want_text):
        out, texts = [], []
        _, cb = self.get(comp_ref)
        for cr in re.findall(r'<Component Index="\d+" ObjectRef="(\d+)"/>', cb):
            ct, fb = self.get(cr)
            mn = re.search(r'<MatchName>(.*?)</MatchName>', fb)
            dn = re.search(r'<DisplayName>(.*?)</DisplayName>', fb)
            ps = []
            for pr in re.findall(r'<Param Index="\d+" ObjectRef="(\d+)"/>', fb):
                _, pb = self.get(pr)
                if want_text and 'AE.ADBE Text' in fb and re.search(r'<ParameterID>1</ParameterID>', pb):
                    texts.append(self.text_of(pb))
                nm = re.search(r'<Name>(.*?)</Name>', pb)
                cv = re.search(r'<CurrentValue>(.*?)</CurrentValue>', pb)
                sk = re.search(r'<StartKeyframe>(.*?)</StartKeyframe>', pb)
                kf = re.search(r'<Keyframes>', pb) or re.search(r'<IsTimeVarying>true</IsTimeVarying>', pb)
                val = cv.group(1) if cv else (sk.group(1).split(',')[1] if sk and ',' in sk.group(1) else None)
                if nm and nm.group(1).strip() and val is not None and nm.group(1) in (
                        '位置', 'スケール', '不透明度', '回転', 'Position', 'Scale', 'Opacity', 'Rotation'):
                    ps.append(f'{nm.group(1)}={val[:24]}{"[KF]" if kf else ""}')
            label = (dn.group(1) if dn else '') or (mn.group(1) if mn else ct)
            if ps:
                out.append(f'{label}: ' + ' '.join(ps))
        return out, texts

    def dump(self, seq_body, fx=False, text=False):
        lines = []
        groups = re.findall(r'<Second ObjectRef="(\d+)"/>', seq_body)
        for g in groups:
            gt, gb = self.get(g)
            kind = 'V' if gt == 'VideoTrackGroup' else 'A' if gt == 'AudioTrackGroup' else None
            if not kind:
                continue
            for ti, tref in re.findall(r'<Track Index="(\d+)" ObjectURef="([^"]+)"/>', gb):
                _, tb = self.get(tref)
                for ir in re.findall(r'<TrackItem Index="\d+" ObjectRef="(\d+)"/>', tb):
                    it, ib = self.get(ir)
                    st = re.search(r'<Start>(-?\d+)</Start>', ib)
                    en = re.search(r'<End>(-?\d+)</End>', ib)
                    s0, e0 = (int(st.group(1)) if st else 0), (int(en.group(1)) if en else 0)
                    if 'Transition' in (it or ''):
                        dn = re.search(r'<DisplayName>(.*?)</DisplayName>', ib)
                        name = f'（トランジション {dn.group(1) if dn else ""}）'
                    else:
                        sub = re.search(r'<SubClip ObjectRef="(\d+)"', ib)
                        nm = re.search(r'<Name>(.*?)</Name>', self.get(sub.group(1))[1]) if sub else None
                        name = nm.group(1) if nm else '?'
                    head = f'{kind}{int(ti) + 1:<2} {s0 / TPS:7.3f}〜{e0 / TPS:7.3f}秒 f{round(s0 / TPS * 30):>5}〜{round(e0 / TPS * 30):>5}  {name}'
                    lines.append(head)
                    comp = re.search(r'<Components ObjectRef="(\d+)"', ib)
                    if comp and (fx or text):
                        eff, texts = self.effects(comp.group(1), text)
                        if fx:
                            lines += [f'      {e}' for e in eff]
                        for t, sz in texts:
                            lines.append(f'      文字「{t}」 サイズ候補 {sz}')
        return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path')
    ap.add_argument('sequence')
    ap.add_argument('--fx', action='store_true')
    ap.add_argument('--text', action='store_true')
    ap.add_argument('--diff', action='store_true')
    a = ap.parse_args()
    src = latest(a.path)
    print(f'読んだファイル: {src}')
    pj = Proj(src)
    seqs = pj.sequences(a.sequence)
    if not seqs:
        raise SystemExit(f'シーケンス「{a.sequence}」がない')
    dumps = [pj.dump(b, a.fx, a.text) for _, b in seqs]
    if a.diff:
        if len(dumps) < 2:
            raise SystemExit('同じ名前のシーケンスが1つしかない（--diff は2つあるときだけ）')
        # 編集した方（再生ヘッドの位置 MZ.EditLine があることが多い）を「後」、もう一方を「前」にする
        order = sorted(range(len(seqs)), key=lambda i: 'MZ.EditLine' in seqs[i][1])
        before, after = dumps[order[0]], dumps[order[-1]]
        print(f'前: {seqs[order[0]][0]} → 後: {seqs[order[-1]][0]}（- は前だけ、+ は後だけ）')
        for ln in difflib.unified_diff(before, after, lineterm='', n=0):
            if not ln.startswith(('---', '+++', '@@')):
                print(ln)
        return
    for (k, _), d in zip(seqs, dumps):
        print(f'=== {a.sequence}（{k}）')
        print('\n'.join(d))


if __name__ == '__main__':
    main()
