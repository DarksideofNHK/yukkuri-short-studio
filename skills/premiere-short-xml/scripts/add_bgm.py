"""読み込み用フォルダ（export_package.py の出力）に BGM を足して、版を上げた新しいフォルダを作る。

- 元のフォルダはそのまま。新しいフォルダは APFS のクローン（cp -c）で作るので容量をほぼ使わない
- BGM は曲の頭から終わりまでを、音量（と lifts の持ち上げ）だけ焼き込んだモノラル 48kHz の WAV にし、タイムラインには
  使う区間だけを in/out で置く（既定の handles。Premiere でクリップの端をドラッグして前後に伸ばせる。2026-09-27 ユーザー指示）。
  入り・終わりのフェードは XML のオーディオトランジション（クロスフェード）。"handles": false で前の形
  （使う区間だけを切り出し、フェードも焼き込む）
- A3 に並べ、ビン「07_BGM」を足し、合わせた位置にシーケンスマーカーを打つ
- 確認用：波形の図（ナレーション・BGM・合わせた位置）と、全体の流れの動画に BGM を混ぜたもの

使い方: python3 add_bgm.py 設定.json
"""
import json, re, shutil, subprocess, sys, tempfile, urllib.parse
from pathlib import Path

import numpy as np

SR = 48000
FPS = 30
SPF = SR // FPS  # 1フレームのサンプル数 1600


# ---------- 音 ----------
def decode(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def write_wav(path, x):
    import wave
    y = np.clip(x, -1, 1)
    y = (y * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(y.tobytes())


def loudness(x):
    """(統合ラウドネス LUFS, 短期ラウドネスの最大 LUFS)"""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        tmp = f.name
    write_wav(tmp, x)
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', tmp, '-af', 'ebur128', '-f', 'null', '-'],
                       capture_output=True, text=True).stderr
    Path(tmp).unlink()
    I = re.findall(r'I:\s+(-?[\d.]+) LUFS', r)
    S = [float(v) for v in re.findall(r'S:\s*(-?[\d.]+)', r) if float(v) > -70]
    return (float(I[-1]) if I else None), (max(S) if S else None)


def db2a(db):
    return 10 ** (db / 20)


# ---------- XML ----------
def enc(p):
    # 相対パスのままだと file://localhostexamples/... になって Premiere が見つけられない（公開前の点検で指摘、2026-09-28）
    return 'file://localhost' + urllib.parse.quote(str(Path(p).resolve()))


def dec_url(u):
    return urllib.parse.unquote(u.replace('file://localhost', ''))


def parse_package(xml):
    """ナレーション（A1・A2）のクリップ、エンドカードの位置、シーケンスの長さ"""
    files = {m.group(1): dec_url(m.group(2)) for m in
             re.finditer(r'<file id="([^"]+)"><name>[^<]*</name><pathurl>([^<]+)</pathurl>', xml)}
    s = xml.find('<sequence')
    seq = xml[s:]
    dur = int(re.search(r'<duration>(\d+)</duration>', seq).group(1))
    a = seq.find('<audio>')
    tracks = re.findall(r'<track>(.*?)</track>', seq[a:], flags=re.S)
    narr = []
    for ti, tr in enumerate(tracks[:2]):
        for c in re.finditer(r'<clipitem id="[^"]+">.*?</clipitem>', tr, flags=re.S):
            ci = c.group(0)
            g = lambda k: int(re.search(f'<{k}>(-?\\d+)</{k}>', ci).group(1))
            fid = re.search(r'<file id="([^"]+)"', ci).group(1)
            narr.append(dict(track=ti + 1, name=re.search(r'<name>([^<]+)</name>', ci).group(1),
                             start=g('start'), end=g('end'), inp=g('in'), out=g('out'), file=files[fid]))
    narr.sort(key=lambda c: c['start'])
    m = re.search(r'<name>(エンドカード[^<]*)</name>.*?<start>(\d+)</start>', seq, flags=re.S)
    end_card = int(m.group(2)) if m else dur
    return narr, end_card, dur, tracks


def mix_narration(narr, dur):
    y = np.zeros(dur * SPF)
    for c in narr:
        x = decode(c['file'])[c['inp'] * SPF:c['out'] * SPF]
        s = c['start'] * SPF
        y[s:s + len(x)] += x[:len(y) - s]
    return y


# ---------- BGM の1クリップ ----------
def render_clip(spec, narr_lufs):
    """spec: file, in_sec, start_f, end_f, target_rel(ナレーション比 LU), cap_rel, fade_in_f, fade_out_f,
    lifts: [[video_f, db], ...]（直線でつなぐ音量の上げ下げ。映像の時刻で書く）"""
    src = decode(spec['file'])
    n = (spec['end_f'] - spec['start_f']) * SPF
    i0 = int(round(spec['in_sec'] * SR))
    x = src[i0:i0 + n]
    if len(x) < n:
        raise SystemExit(f"{spec['file']}: 曲が短い（{len(x)/SR:.1f}s しかない、{n/SR:.1f}s 要る）")
    I, Smax = loudness(x)
    g = spec['target_rel'] + narr_lufs - I
    if Smax is not None and spec.get('cap_rel') is not None:
        g = min(g, spec['cap_rel'] + narr_lufs - Smax)
    env_db = np.full(n, g)
    lifts = spec.get('lifts') or []
    if lifts:
        fr = np.array([(f - spec['start_f']) * SPF for f, _ in lifts], dtype=float)
        vals = np.array([d for _, d in lifts], dtype=float)
        env_db += np.interp(np.arange(n), fr, vals)
    amp = db2a(env_db)
    fi = spec.get('fade_in_f', 1) * SPF
    fo = spec.get('fade_out_f', 1) * SPF
    if fi:
        amp[:fi] *= np.linspace(0, 1, fi)
    if fo:
        amp[-fo:] *= np.linspace(1, 0, fo)
    y = x * amp
    return y, dict(src_lufs=round(I, 1), gain_db=round(g, 1), out_lufs=round(loudness(y)[0], 1))


def render_full(spec, narr_lufs):
    """handles（既定）：曲の頭から終わりまでを1つの WAV にし（音量と lifts だけ焼き込む）、タイムラインには使う区間だけを
    in/out で置く。Premiere でクリップの端をドラッグして前後に伸ばせる。入り・終わりのフェードは焼き込まず、
    XML のオーディオトランジション（クロスフェード）にする。
    戻り値：(WAV 全体, 使う区間（フェードをかけた確認用）, in のフレーム, WAV のフレーム数, 情報)"""
    src = decode(spec['file'])
    frames = spec['end_f'] - spec['start_f']
    n = frames * SPF
    i0 = int(round(spec['in_sec'] * SR))
    seg = src[i0:i0 + n]
    if len(seg) < n:
        raise SystemExit(f"{spec['file']}: 曲が短い（{len(seg)/SR:.1f}s しかない、{n/SR:.1f}s 要る）")
    I, Smax = loudness(seg)
    g = spec['target_rel'] + narr_lufs - I
    if Smax is not None and spec.get('cap_rel') is not None:
        g = min(g, spec['cap_rel'] + narr_lufs - Smax)
    in_f = -(-i0 // SPF)                      # in 点をフレームの境目にそろえるため、頭に無音を足す
    full = np.concatenate([np.zeros(in_f * SPF - i0), src])
    full = np.pad(full, (0, (-len(full)) % SPF))
    env_db = np.full(len(full), g)
    lifts = spec.get('lifts') or []
    if lifts:                                  # 曲の中の位置で持ち上げる（クリップを動かしても曲の同じ音で上がる）
        fr = np.array([(in_f + f - spec['start_f']) * SPF for f, _ in lifts], dtype=float)
        env_db += np.interp(np.arange(len(full)), fr, np.array([d for _, d in lifts], dtype=float))
    y = full * db2a(env_db)
    k = int(0.01 * SR)
    y[:k] *= np.linspace(0, 1, k); y[-k:] *= np.linspace(1, 0, k)
    view = y[in_f * SPF:in_f * SPF + n].copy()
    fi, fo = spec.get('fade_in_f', 1) * SPF, spec.get('fade_out_f', 1) * SPF
    if fi:
        view[:fi] *= np.linspace(0, 1, fi)
    if fo:
        view[-fo:] *= np.linspace(1, 0, fo)
    return y, view, in_f, len(y) // SPF, dict(src_lufs=round(I, 1), gain_db=round(g, 1), out_lufs=round(loudness(view)[0], 1))


# ---------- XML の書き足し ----------
def masterclip(mid, name, frames, path):
    fid = f'f-{mid}'
    return (f'<clip id="mc-{mid}"><masterclipid>mc-{mid}</masterclipid><ismasterclip>TRUE</ismasterclip><name>{name}</name>'
            f'<duration>{frames}</duration><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><media><audio><track>'
            f'<clipitem id="mci-{mid}"><masterclipid>mc-{mid}</masterclipid><name>{name}</name><duration>{frames}</duration>'
            f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><file id="{fid}"><name>{Path(path).name}</name>'
            f'<pathurl>{enc(path)}</pathurl><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><duration>{frames}</duration>'
            f'<media><audio><samplecharacteristics><depth>16</depth><samplerate>{SR}</samplerate></samplecharacteristics>'
            f'<channelcount>1</channelcount></audio></media></file><sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex>'
            f'</sourcetrack></clipitem></track></audio></media></clip>')


def clipitem(mid, name, frames, start, inp=0, file_frames=None):
    return (f'<clipitem id="ci-{mid}"><masterclipid>mc-{mid}</masterclipid><name>{name}</name><enabled>TRUE</enabled>'
            f'<duration>{file_frames or frames}</duration><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><start>{start}</start>'
            f'<end>{start + frames}</end><in>{inp}</in><out>{inp + frames}</out><file id="f-{mid}" /><sourcetrack><mediatype>audio</mediatype>'
            f'<trackindex>1</trackindex></sourcetrack></clipitem>')


def fade(start, end, align):
    """クリップの端のオーディオトランジション（Premiere ではコンスタントパワーのクロスフェードになる）"""
    return (f'<transitionitem><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><start>{start}</start><end>{end}</end>'
            f'<alignment>{align}</alignment><effect><name>Cross Fade (+3dB)</name><effectid>KGAudioTransCrossFade3dB</effectid>'
            f'<effectcategory>audio</effectcategory><effecttype>transition</effecttype><mediatype>audio</mediatype></effect></transitionitem>')


def marker(name, comment, at):
    return f'<marker><comment>{comment}</comment><name>{name}</name><in>{at}</in><out>-1</out></marker>'


# ---------- 図 ----------
def plot(out, title, narr_mix, bgm_mix, narr, clips, marks, dur, end_card):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    f = '/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc'
    if Path(f).exists():
        font_manager.fontManager.addfont(f)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=f).get_name()
    T = dur / FPS
    fig, ax = plt.subplots(3, 1, figsize=(18, 7.6), sharex=True, gridspec_kw=dict(height_ratios=[1.1, 2, 2]))

    def wave(a, x, color):
        st = SR // 100
        m = len(x) // st
        xx = x[:m * st].reshape(m, st)
        t = np.arange(m) / 100
        a.fill_between(t, xx.min(1), xx.max(1), color=color, lw=0)

    for c in narr:
        y = 0.55 if c['track'] == 1 else 0.05
        col = '#3b6ea5' if c['track'] == 1 else '#c8553d'
        ax[0].add_patch(plt.Rectangle((c['start'] / FPS, y), (c['end'] - c['start']) / FPS, 0.4, color=col, alpha=0.8))
        ax[0].text(c['start'] / FPS + 0.05, y + 0.2, c['name'].split('_')[0], fontsize=7, va='center', color='white')
    ax[0].set_ylim(0, 1)
    ax[0].set_yticks([0.25, 0.75]); ax[0].set_yticklabels(['A2 聞き手', 'A1 説明役'])
    ax[0].set_title(title, fontsize=12, loc='left')
    wave(ax[1], narr_mix, '#555')
    ax[1].set_ylabel('ナレーション')
    wave(ax[2], bgm_mix, '#2a9d8f')
    lim = max(0.05, np.abs(narr_mix).max())
    blim = max(0.01, np.abs(bgm_mix).max()) * 1.15
    zoom = lim / blim
    ax[1].set_ylim(-lim, lim); ax[2].set_ylim(-blim, blim)
    ax[2].set_ylabel(f'BGM（A3・音量焼き込み済み）\n縦は約{zoom:.0f}倍に拡大', fontsize=9)
    for c in clips:
        ax[2].axvspan(c['start_f'] / FPS, c['end_f'] / FPS, color='#2a9d8f', alpha=0.06)
        ax[2].text(c['start_f'] / FPS + 0.1, blim * 0.86, c['label'], fontsize=9, color='#1d6f65')
    for k, (at, text) in enumerate(marks):
        for a in ax:
            a.axvline(at / FPS, color='#e76f51', lw=1.6, ls='--')
        ax[2].text(at / FPS + 0.1, -blim * (0.92 - 0.17 * (k % 3)), text, fontsize=8.5, color='#b5452a', va='bottom',
                   bbox=dict(facecolor='white', edgecolor='none', alpha=0.75, pad=1))
    for a in ax:
        a.axvline(end_card / FPS, color='k', lw=1, ls=':')
        a.grid(axis='x', alpha=0.3)
    ax[2].set_xlim(0, T)
    ax[2].set_xticks(np.arange(0, T + 0.1, 5))
    ax[2].set_xticks(np.arange(0, T + 0.1, 1), minor=True)
    ax[2].set_xlabel('秒（点線＝エンドカード）')
    fig.tight_layout()
    fig.savefig(out, dpi=80)
    plt.close(fig)


# ---------- 本体 ----------
def main(cfg_path):
    cfg = json.load(open(cfg_path))
    src = Path(cfg['src']); dst = Path(cfg['dst'])
    if dst.exists():
        raise SystemExit(f'{dst} はもうある。版を上げた別の名前にする')
    subprocess.run(['cp', '-cR', str(src), str(dst)], check=True)  # APFS クローン
    old_xml = next(dst.glob('00_*.xml'))
    xml = old_xml.read_text(encoding='utf-8')
    # 1) パスをすべて新しいフォルダに向ける
    xml = xml.replace(urllib.parse.quote(str(src)) + '/', urllib.parse.quote(str(dst)) + '/')
    # 2) プロジェクト・シーケンスの名前と XML のファイル名の版を上げる
    old_name = re.search(r'<project><name>([^<]+)</name>', xml).group(1)
    new_name = old_name.replace(cfg['old_tag'], cfg['new_tag']) if cfg['old_tag'] in old_name else f"{old_name}_{cfg['new_tag']}"
    xml = xml.replace(f'<name>{old_name}</name>', f'<name>{new_name}</name>')
    new_xml = dst / f'00_これを読み込む_{new_name}.xml'
    old_xml.unlink()

    narr, end_card, dur, _ = parse_package(xml)
    narr_mix = mix_narration(narr, dur)
    narr_lufs, _ = loudness(narr_mix)
    K = narr[-2]['start']   # 決め台詞（聞き手）
    F = narr[-1]['start']   # 審判のときだ（説明役）
    ctx = dict(K=K, F=F, E=end_card, Z=dur)
    print(f'{new_name}: ナレーション {narr_lufs} LUFS / 後ろから2行目（K） {K}f・最後の行 {F}f・エンドカード {end_card}f・終わり {dur}f')

    bgm_dir = dst / '素材' / '07_BGM'
    bgm_dir.mkdir(parents=True, exist_ok=True)
    bgm_mix = np.zeros(dur * SPF)
    clips_xml, mc_xml, info, placed, items = '', '', [], [], []
    for i, c in enumerate(cfg['clips'], 1):
        c = dict(c)
        for k in ('start_f', 'end_f'):
            if isinstance(c[k], str):
                c[k] = int(eval(c[k], {}, ctx))
        if isinstance(c.get('in_sec'), str):
            c['in_sec'] = float(eval(c['in_sec'], {}, dict(ctx, fps=FPS)))
        c['lifts'] = [[int(eval(f, {}, ctx)) if isinstance(f, str) else f, d] for f, d in c.get('lifts', [])]
        frames = c['end_f'] - c['start_f']
        name = c['name']
        path = bgm_dir / f'{name}.wav'
        mid = f'bgm{i:02d}'
        if c.get('handles', cfg.get('handles', True)):
            y, view, in_f, file_frames, st = render_full(c, narr_lufs)
            write_wav(path, y)
            bgm_mix[c['start_f'] * SPF:c['end_f'] * SPF] += view
            mc_xml += masterclip(mid, name, file_frames, path)
            items.append(dict(mid=mid, name=name, frames=frames, start_f=c['start_f'], end_f=c['end_f'], in_f=in_f,
                              file_frames=file_frames, fi=c.get('fade_in_f', 0), fo=c.get('fade_out_f', 0)))
            st = dict(st, handles=True, in_f=in_f, file_frames=file_frames)
        else:
            y, st = render_clip(c, narr_lufs)
            write_wav(path, y)
            bgm_mix[c['start_f'] * SPF:c['end_f'] * SPF] += y
            mc_xml += masterclip(mid, name, frames, path)
            clips_xml += clipitem(mid, name, frames, c['start_f'])
        placed.append(dict(c, frames=frames))
        info.append(dict(name=name, file=Path(c['file']).name, in_sec=round(c['in_sec'], 3), start_f=c['start_f'],
                         end_f=c['end_f'], **st))
        print(f"  A3 {name}: {c['start_f']}〜{c['end_f']}f 曲の{c['in_sec']:.2f}秒から ・ 素 {st['src_lufs']} LUFS → {st['gain_db']:+.1f}dB → {st['out_lufs']} LUFS")
    # handles のクリップを並べる。同じトラックで重なるとあとのクリップが上書きされるので、重ならないように確かめる。
    # ぴったり並ぶ2つ（本編の曲の終わり＝締めの曲の頭）は、つなぎ目の真ん中に1つのクロスフェード（両側に曲の余白がある）
    items.sort(key=lambda it: it['start_f'])
    for a, b in zip(items, items[1:]):
        if a['end_f'] > b['start_f']:
            raise SystemExit(f"A3 で {a['name']}（〜{a['end_f']}f）と {b['name']}（{b['start_f']}f〜）が重なる。"
                             "同じトラックでは重ねられないので、前の曲の end_f を後の曲の start_f 以下にする")
    for k, it in enumerate(items):
        prev_adj = k > 0 and items[k - 1]['end_f'] == it['start_f']
        nxt = items[k + 1] if k + 1 < len(items) else None
        if it['fi'] and not prev_adj:
            clips_xml += fade(it['start_f'], it['start_f'] + it['fi'], 'start')
        clips_xml += clipitem(it['mid'], it['name'], it['frames'], it['start_f'], it['in_f'], it['file_frames'])
        if nxt and nxt['start_f'] == it['end_f']:
            d = max(it['fo'], nxt['fi']) or 8
            clips_xml += fade(it['end_f'] - d // 2, it['end_f'] + d - d // 2, 'center')
        elif it['fo']:
            clips_xml += fade(it['end_f'] - it['fo'], it['end_f'], 'end')
    # 差し替え候補（元のフォルダの外にある、音量をそろえたもの）
    alts = [a for a in cfg.get('alternates', []) if Path(a).exists() or print(f'注意: 差し替え候補が見つからないので飛ばす：{a}')]
    for j, p in enumerate(alts, 1):
        mid = f'alt{j:02d}'
        nfr = int(round(len(decode(p)) / SPF))
        mc_xml += masterclip(mid, Path(p).stem, nfr, p)
    bin_xml = f'<bin><name>07_BGM</name><children>{mc_xml}</children></bin>'
    s = xml.find('<sequence')
    xml = xml[:s] + bin_xml + xml[s:]
    # A3 は シーケンスの音声の3つ目の <track>
    s = xml.find('<sequence')
    a = xml.find('<audio>', s)
    pos = a
    for _ in range(3):
        pos = xml.find('<track>', pos) + len('<track>')
    xml = xml[:pos] + clips_xml + xml[pos:]
    # マーカー
    marks = []
    for m in cfg.get('markers', []):
        at = int(eval(m['at'], {}, ctx)) if isinstance(m['at'], str) else m['at']
        marks.append((at, m['text']))
    mk = ''.join(marker('BGM', t, at) for at, t in marks)
    xml = xml.replace('</sequence>', mk + '</sequence>', 1)
    new_xml.write_text(xml, encoding='utf-8')

    # 確認用：波形の図
    chk = dst / '確認用'
    chk.mkdir(exist_ok=True)
    plot(chk / 'BGMの配置_波形.png', f"{new_name}：A3 の BGM の置き方（ナレーション {narr_lufs} LUFS）",
         narr_mix, bgm_mix, narr, [dict(start_f=p['start_f'], end_f=p['end_f'], label=p['label']) for p in placed],
         marks, dur, end_card)
    # 確認用：全体の流れの動画に BGM を混ぜる
    prev = chk / '全体の流れ_目安.mp4'
    if prev.exists():
        # 音は XML のナレーション＋BGM を最後まで（確認動画の元の音はナレーションの終わりで切れているので使わない）
        tmp = chk / '_mix_tmp.wav'
        mix = narr_mix + bgm_mix
        pk = np.abs(mix).max()
        if pk > 10 ** (-1 / 20):                            # 確認用だけ、全体を下げて音割れを防ぐ
            mix = mix * (10 ** (-1 / 20) / pk)
        write_wav(tmp, mix)
        outv = chk / '全体の流れ_目安_BGM入り.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(prev), '-i', str(tmp), '-map', '0:v', '-map', '1:a',
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', str(outv)], check=True)
        tmp.unlink()
        prev.unlink()  # クローンの中の BGM なし版は消す（元のフォルダには残っている）
    # 全体のラウドネス（ナレーション＋BGM）
    tot, _ = loudness(narr_mix + bgm_mix)
    json.dump(dict(xml=str(new_xml), narration_lufs=narr_lufs, total_lufs=tot, clips=info,
                   markers=[dict(frame=a, text=t) for a, t in marks]),
              open(dst / '確認用' / 'bgm_placement.json', 'w'), ensure_ascii=False, indent=1)
    print(f'  ナレーション＋BGM {tot} LUFS → {new_xml}')


if __name__ == '__main__':
    main(sys.argv[1])
