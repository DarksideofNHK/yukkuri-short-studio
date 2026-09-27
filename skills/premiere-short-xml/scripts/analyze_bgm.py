"""BGM の波形解析：音量の推移・拍・区切り目を出して、波形の画像を書く。
使い方: python3 analyze_bgm.py 出力フォルダ 曲1.mp3 曲2.mp3 ...
"""
import json, re, subprocess, sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

SR = 22050
HOP = 0.05  # 50ms

for f in ['/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc']:
    if Path(f).exists():
        font_manager.fontManager.addfont(f)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=f).get_name()
        break


def decode(path, sr=SR, ch=1):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', str(ch), '-ar', str(sr),
                          '-f', 'f32le', '-'], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    return x.reshape(-1, ch) if ch > 1 else x


def lufs(path):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128', '-f', 'null', '-'],
                       capture_output=True, text=True).stderr
    m = re.findall(r'I:\s+(-?[\d.]+) LUFS', r)
    return float(m[-1]) if m else None


def analyze(path):
    x = decode(path)
    n = int(SR * HOP)
    frames = len(x) // n
    fr = x[:frames * n].reshape(frames, n)
    rms = np.sqrt((fr ** 2).mean(1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    # 0.5秒でならした音量
    k = 10
    db_s = np.convolve(db, np.ones(k) / k, mode='same')
    # 拍の手がかり：帯域ごとの対数エネルギーの増え方（スペクトルフラックス）
    win = np.hanning(1024)
    spec = []
    for i in range(frames):
        s = i * n
        seg = x[s:s + 1024]
        if len(seg) < 1024:
            seg = np.pad(seg, (0, 1024 - len(seg)))
        spec.append(np.abs(np.fft.rfft(seg * win)))
    spec = np.log1p(np.array(spec) * 10)
    flux = np.maximum(spec[1:] - spec[:-1], 0).sum(1)
    flux = np.concatenate([[0], flux])
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    # テンポ（60〜180BPM）
    ac = np.correlate(flux, flux, mode='full')[len(flux) - 1:]
    lags = np.arange(len(ac)) * HOP
    ok = (lags >= 60 / 180) & (lags <= 60 / 60)
    best = lags[ok][np.argmax(ac[ok])] if ok.any() else None
    bpm = 60 / best if best else None
    # 強いアタック（上位の山）
    peaks = [i for i in range(1, frames - 1) if flux[i] > 3.0 and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]]
    # 区切り目：前後2秒の平均音量の差が大きいところ
    k2 = int(2 / HOP)
    changes = []
    for i in range(k2, frames - k2, 2):
        d = db[i:i + k2].mean() - db[i - k2:i].mean()
        if abs(d) >= 4:
            changes.append((round(i * HOP, 2), round(float(d), 1)))
    # 近いものはまとめる
    merged = []
    for t, d in changes:
        if merged and t - merged[-1][0] < 1.5 and np.sign(d) == np.sign(merged[-1][1]):
            if abs(d) > abs(merged[-1][1]):
                merged[-1] = (t, d)
        else:
            merged.append((t, d))
    dur = len(x) / SR
    peak_db = float(db.max())
    # 立ち上がり：最大音量 -12dB に初めて届く時刻
    rise = next((i * HOP for i in range(frames) if db_s[i] > peak_db - 12), 0)
    # 終わり：最後に最大音量 -12dB を超えている時刻
    tail = next((i * HOP for i in range(frames - 1, -1, -1) if db_s[i] > peak_db - 12), dur)
    return dict(path=str(path), dur=round(dur, 2), lufs=lufs(path), bpm=round(bpm, 1) if bpm else None,
                rise=round(rise, 2), tail=round(tail, 2), changes=merged,
                peaks=[round(p * HOP, 2) for p in peaks][:200]), (x, db, db_s, flux)


def plot(info, arrays, out):
    x, db, db_s, flux = arrays
    dur = info['dur']
    t = np.arange(len(db)) * HOP
    fig, ax = plt.subplots(2, 1, figsize=(16, 5.2), sharex=True, gridspec_kw=dict(height_ratios=[3, 1.3]))
    # 波形（最大・最小）
    step = int(SR * 0.02)
    m = len(x) // step
    xx = x[:m * step].reshape(m, step)
    tt = np.arange(m) * 0.02
    ax[0].fill_between(tt, xx.min(1), xx.max(1), color='#4a6fa5', lw=0)
    ax2 = ax[0].twinx()
    ax2.plot(t, db_s, color='#d1495b', lw=1.4)
    ax2.set_ylim(-60, 0)
    ax2.set_ylabel('音量 dB（0.5秒平均）', color='#d1495b')
    for c, d in info['changes']:
        ax[0].axvline(c, color='#edae49' if d > 0 else '#00798c', lw=1.5, ls='--')
        ax[0].text(c, 0.95, f'{c:.1f}s', color='k', fontsize=8, ha='center', va='bottom')
    ax[0].axvline(info['rise'], color='green', lw=2)
    ax[0].set_ylim(-1, 1)
    name = Path(info['path']).stem
    ax[0].set_title(f"{name}  長さ {dur:.1f}s ・ {info['lufs']} LUFS ・ 約{info['bpm']} BPM ・ 立ち上がり {info['rise']}s（緑）・"
                    f"黄＝盛り上がる 青＝静まる", fontsize=10)
    ax[1].plot(t, flux, color='#555', lw=0.7)
    for p in info['peaks']:
        ax[1].axvline(p, color='#d1495b', lw=0.6, alpha=0.6)
    ax[1].set_ylabel('アタック')
    ax[1].set_xlim(0, dur)
    ax[1].set_xticks(np.arange(0, dur + 1, 5))
    ax[1].set_xticks(np.arange(0, dur + 1, 1), minor=True)
    for a in ax:
        a.grid(axis='x', which='major', alpha=0.4)
        a.grid(axis='x', which='minor', alpha=0.12)
    ax[1].set_xlabel('秒')
    fig.tight_layout()
    fig.savefig(out, dpi=80)
    plt.close(fig)


if __name__ == '__main__':
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    allinfo = {}
    for p in sys.argv[2:]:
        info, arrays = analyze(p)
        stem = Path(p).stem
        plot(info, arrays, outdir / f'{stem}.png')
        # 音量の推移（0.5秒ごと）も残す：配置の計算で使う
        info['db_half_sec'] = [round(float(v), 1) for v in arrays[2][::10]]
        allinfo[stem] = info
        print(f"{stem}: {info['dur']}s {info['lufs']}LUFS bpm~{info['bpm']} rise={info['rise']} tail={info['tail']} changes={info['changes']}")
    json.dump(allinfo, open(outdir / 'analysis.json', 'w'), ensure_ascii=False, indent=1)
