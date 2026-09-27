"""読み込み用フォルダの A4 に効果音を足す（同じフォルダの中で。今ある素材は変えない）。

- 最初に元の XML を `確認用/効果音なし_<XML名>` に写し、毎回そこから作り直す（何度流しても同じ結果）
- 効果音は音の種類ごとに1つの WAV（モノラル 48kHz・音量とフェードを焼き込み）を `素材/09_効果音/` に置き、
  必要な数だけ A4 に並べる。音のいちばん大きいところが、合わせたいフレームに来るように置く
- 置く位置は timeline.json（作業フォルダ）から：ハンコ（stamp）・行の頭（line）・フレーム直接（frame）
- 確認用：全体の流れの動画の音を「ナレーション＋BGM＋効果音」で作り直し、効果音の置き場所の図を書く
- Premiere に読み込み済み（.prproj・自動保存がある）のフォルダには書かない

使い方: python3 add_se.py 設定.json
"""
import json, re, shutil, subprocess, sys, urllib.parse
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from add_bgm import (SR, FPS, SPF, decode, write_wav, parse_package, mix_narration, masterclip, clipitem, dec_url)


def momentary_max(x):
    tmp = Path('/tmp') / f'_se_{abs(hash(x.tobytes())) % 10**8}.wav'
    write_wav(tmp, x)
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(tmp), '-af', 'ebur128', '-f', 'null', '-'],
                       capture_output=True, text=True).stderr
    tmp.unlink()
    M = [float(v) for v in re.findall(r'M:\s*(-?[\d.]+)', r) if float(v) > -70]
    return max(M) if M else None


def render_sound(s, narr_lufs):
    """s: file, frames（WAV の長さ）, fade_from（秒。そこから終わりまで消す）, rel（ナレーション比 LU・瞬間の最大）"""
    x = decode(s['file'])
    n = s['frames'] * SPF
    x = np.pad(x, (0, max(0, n - len(x))))[:n]
    if 'gain_db' in s:          # 前の版と同じ音量で入れ直すとき（前の版の se_placement.json の gain_db）
        g = s['gain_db']
    else:
        mm = momentary_max(x)
        if mm is None:          # 0.4秒より短い音（自作のピコッなど）は測れないので、後ろに無音を足して測る（ピークの上限で抑える）
            mm = momentary_max(np.pad(x, (0, SR)))
        g = s.get('rel', -7) + narr_lufs - mm
        g = min(g, s.get('peak_max', -6) - 20 * np.log10(np.abs(x).max() + 1e-9))   # 一瞬の音はピークで抑える
    y = x * 10 ** (g / 20)
    ff = s.get('fade_from')
    if ff is not None:
        a = int(ff * SR)
        y[a:] *= np.linspace(1, 0, n - a)
    y[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))
    peak = int(np.argmax(np.abs(y)))
    return y, round(g, 1), round(peak / SR, 3)


def bgm_preview(a3, files, dur):
    """確認用の動画の BGM：A3 のクリップを XML のとおり（使う区間 in/out・つなぎ目と終わりのフェード）に混ぜる。
    前は開始位置だけを見て曲の頭から置いていたので、曲の途中から使う設定（in_sec）だと確認用の音がずれた（2026-09-28）"""
    items = []
    for m in re.finditer(r'<(clipitem|transitionitem)[^>]*>(.*?)</\1>', a3, flags=re.S):
        b = m.group(2)
        num = lambda k, b=b: int(re.search(rf'<{k}>(-?\d+)</{k}>', b).group(1))
        if m.group(1) == 'clipitem':
            items.append(dict(k='c', start=num('start'), end=num('end'), inn=num('in'),
                              fid=re.search(r'<file id="([^"]+)"', b).group(1)))
        else:
            al = re.search(r'<alignment>(\w+)</alignment>', b)
            items.append(dict(k='t', start=num('start'), end=num('end'), al=al.group(1) if al else 'center'))
    trans = [i for i in items if i['k'] == 't']
    mix, cache = np.zeros(dur * SPF), {}
    for c in (i for i in items if i['k'] == 'c'):
        w = cache.setdefault(c['fid'], decode(files[c['fid']]))
        a, b = c['start'], c['end']
        lo, hi, fin, fout = a, b, None, None
        for t in trans:
            if t['al'] == 'center' and t['start'] < a < t['end']:
                lo, fin = t['start'], (t['start'], t['end'])
            elif t['al'] == 'center' and t['start'] < b < t['end']:
                hi, fout = t['end'], (t['start'], t['end'])
            elif t['al'] == 'start' and t['start'] == a:
                fin = (t['start'], t['end'])
            elif t['al'] == 'end' and t['end'] == b:
                fout = (t['start'], t['end'])
        src0 = (c['inn'] - (a - lo)) * SPF               # 曲の中の、タイムライン lo にあたるサンプル
        n = (hi - lo) * SPF
        seg = np.zeros(n)
        s0, d0 = max(0, src0), max(0, -src0)
        part = w[s0:s0 + n - d0]
        seg[d0:d0 + len(part)] = part
        tt = lo + np.arange(n) / SPF
        g = np.ones(n)
        if fin:
            g *= np.sin(np.clip((tt - fin[0]) / max(1, fin[1] - fin[0]), 0, 1) * np.pi / 2)
        if fout:
            g *= np.cos(np.clip((tt - fout[0]) / max(1, fout[1] - fout[0]), 0, 1) * np.pi / 2)
        st = lo * SPF
        e = min(len(mix), st + n)
        mix[st:e] += (seg * g)[:e - st]
    return mix


def resolve_at(a, tl):
    if 'frame' in a:
        return a['frame']
    if 'line' in a:
        l = [l for l in tl['lines'] if l['id'] == a['line']][0]
        return l['start'] - 2
    if 'stamp' in a:
        for v in tl['v2']:
            for st in v.get('steps', []):
                txt = st.get('stamp')
                txt = txt.get('text') if isinstance(txt, dict) else txt
                if txt == a['stamp']:
                    return v['start'] + st['f'] + 2   # ハンコが揺れて光るフレーム
        raise SystemExit(f"ハンコ「{a['stamp']}」が見つからない")
    raise SystemExit(f'位置の書き方が分からない: {a}')


def tc(f):
    s = f / FPS
    return f'{int(s // 60)}:{s % 60:05.2f}'


def plot(out, title, narr_mix, fx_mix, narr, places, dur):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    f = '/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc'
    font_manager.fontManager.addfont(f)
    plt.rcParams['font.family'] = font_manager.FontProperties(fname=f).get_name()
    fig, ax = plt.subplots(2, 1, figsize=(18, 5.2), sharex=True, gridspec_kw=dict(height_ratios=[1, 2]))
    for c in narr:
        y = 0.55 if c['track'] == 1 else 0.05
        ax[0].add_patch(plt.Rectangle((c['start'] / FPS, y), (c['end'] - c['start']) / FPS, 0.4,
                                      color='#3b6ea5' if c['track'] == 1 else '#c8553d', alpha=0.8))
        ax[0].text(c['start'] / FPS + 0.05, y + 0.2, c['name'].split('_')[0], fontsize=7, va='center', color='white')
    ax[0].set_ylim(0, 1); ax[0].set_yticks([0.25, 0.75]); ax[0].set_yticklabels(['A2 聞き手', 'A1 説明役'])
    ax[0].set_title(title, fontsize=12, loc='left')
    st = SR // 100
    for x, col in ((narr_mix, '#bbb'), (fx_mix, '#e76f51')):
        m = len(x) // st
        xx = x[:m * st].reshape(m, st)
        ax[1].fill_between(np.arange(m) / 100, xx.min(1), xx.max(1), color=col, lw=0)
    lim = np.abs(narr_mix).max()
    ax[1].set_ylim(-lim, lim)
    for k, p in enumerate(places):
        for a in ax:
            a.axvline(p['at'] / FPS, color='#e76f51', lw=1.2, ls='--')
        ax[1].text(p['at'] / FPS + 0.1, lim * (0.9 - 0.18 * (k % 3)), f"{p['sound']}：{p['why']}", fontsize=8.5,
                   color='#9b3a22', bbox=dict(facecolor='white', edgecolor='none', alpha=0.8, pad=1))
    ax[1].set_ylabel('灰＝ナレーション\n赤＝効果音（A4）', fontsize=9)
    T = dur / FPS
    ax[1].set_xlim(0, T); ax[1].set_xticks(np.arange(0, T + 0.1, 5)); ax[1].set_xticks(np.arange(0, T + 0.1, 1), minor=True)
    for a in ax:
        a.grid(axis='x', alpha=0.3)
    ax[1].set_xlabel('秒')
    fig.tight_layout(); fig.savefig(out, dpi=80); plt.close(fig)


def main(cfg_path):
    cfg = json.load(open(cfg_path, encoding='utf-8'))
    pkg = Path(cfg['pkg'])
    if list(pkg.glob('*.prproj')) or (pkg / 'Adobe Premiere Pro Auto-Save').exists():
        raise SystemExit(f'{pkg.name} は Premiere に読み込み済みなので書かない（版を上げて作る）')
    xml_p = next(pkg.glob('00_*.xml'))
    chk = pkg / '確認用'
    pristine = chk / f'効果音なし_{xml_p.name}'
    if not pristine.exists():
        shutil.copy(xml_p, pristine)
    xml = pristine.read_text(encoding='utf-8')
    tl = json.load(open(cfg['timeline'], encoding='utf-8'))
    narr, end_card, dur, _ = parse_package(xml)
    narr_mix = mix_narration(narr, dur)
    from add_bgm import loudness
    narr_lufs, _ = loudness(narr_mix)

    se_dir = pkg / '素材' / '09_効果音'
    if se_dir.exists():
        shutil.rmtree(se_dir)
    se_dir.mkdir(parents=True)
    sounds = {}
    mc_xml = ''
    for i, (key, s) in enumerate(cfg['sounds'].items(), 1):
        y, g, peak = render_sound(s, narr_lufs)
        path = se_dir / f'SE_{key}.wav'
        write_wav(path, y)
        mid = f'se{i:02d}'
        sounds[key] = dict(y=y, frames=s['frames'], mid=mid, peak=peak, gain=g, path=path, src=Path(s['file']).name)
        mc_xml += masterclip(mid, f'SE_{key}', s['frames'], path)
    places, items = [], ''
    fx_mix = np.zeros(dur * SPF)
    last_end = -1
    for j, p in enumerate(sorted(cfg['places'], key=lambda p: resolve_at(p['at'], tl)), 1):
        at = resolve_at(p['at'], tl)
        snd = sounds[p['sound']]
        start = at - round(snd['peak'] * FPS)
        if start < last_end:
            raise SystemExit(f"{p['why']}: 前の効果音と重なる（{start} < {last_end}）")
        if start + snd['frames'] > end_card:
            raise SystemExit(f"{p['why']}: エンドカードにかかる")
        last_end = start + snd['frames']
        items += clipitem(snd['mid'], f'SE_{p["sound"]}', snd['frames'], start).replace(
            f'id="ci-{snd["mid"]}"', f'id="ci-{snd["mid"]}-{j}"')
        fx_mix[start * SPF:start * SPF + len(snd['y'])] += snd['y']
        places.append(dict(at=at, start=start, sound=p['sound'], why=p['why']))
    bin_xml = f'<bin><name>09_効果音</name><children>{mc_xml}</children></bin>'
    s = xml.find('<sequence')
    xml = xml[:s] + bin_xml + xml[s:]
    s = xml.find('<sequence')
    pos = xml.find('<audio>', s)
    for _ in range(4):                                  # A4 = シーケンスの音声の4つ目の <track>
        pos = xml.find('<track>', pos) + len('<track>')
    xml = xml[:pos] + items + xml[pos:]
    xml_p.write_text(xml, encoding='utf-8')

    # 確認用の動画：ナレーション＋BGM（A3 の WAV）＋効果音
    bgm_mix = np.zeros(dur * SPF)
    seq = xml[xml.find('<sequence'):]
    tracks = re.findall(r'<track>(.*?)</track>', seq[seq.find('<audio>'):], flags=re.S)
    files = {m.group(1): dec_url(m.group(2)) for m in
             re.finditer(r'<file id="([^"]+)"><name>[^<]*</name><pathurl>([^<]+)</pathurl>', xml)}
    bgm_mix = bgm_preview(tracks[2], files, dur)
    total = narr_mix + bgm_mix + fx_mix
    peak_db = 20 * np.log10(np.abs(total).max() + 1e-9)
    if peak_db > -1:                                   # 確認用の動画だけ、全体を下げて音割れを防ぐ
        total = total * 10 ** ((-1 - peak_db) / 20)
    src_v = next((chk / n for n in ('全体の流れ_目安_BGM・効果音入り.mp4', '全体の流れ_目安_BGM入り.mp4') if (chk / n).exists()), None)
    outv = chk / '全体の流れ_目安_BGM・効果音入り.mp4'
    if src_v:
        tmp = chk / '_mix_tmp.wav'
        write_wav(tmp, total)
        tmpv = chk / '_tmp.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(src_v), '-i', str(tmp), '-map', '0:v', '-map', '1:a',
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', str(tmpv)], check=True)
        tmp.unlink()
        if src_v.name != outv.name:
            src_v.unlink()
        tmpv.rename(outv)
    plot(chk / '効果音の配置.png', f'{xml_p.stem.replace("00_これを読み込む_", "")}：A4 の効果音（{len(places)}か所）',
         narr_mix, fx_mix, narr, places, dur)
    info = dict(xml=str(xml_p), narration_lufs=narr_lufs, mix_peak_dbfs=round(peak_db, 1),
                sounds={k: dict(file=v['src'], frames=v['frames'], gain_db=v['gain'], peak_sec=v['peak']) for k, v in sounds.items()},
                places=places)
    json.dump(info, open(chk / 'se_placement.json', 'w'), ensure_ascii=False, indent=1)
    print(f"{pkg.name}: 効果音 {len(places)} か所・全体のピーク {peak_db:.1f} dBFS")
    for p in places:
        print(f"   {tc(p['at'])} {p['sound']}：{p['why']}")


if __name__ == '__main__':
    main(sys.argv[1])
