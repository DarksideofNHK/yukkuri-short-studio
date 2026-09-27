#!/usr/bin/env python3
"""自作の効果音「どすん」（札束が落ちる音）を合成する（無料・ローカル・権利の問題なし）。
最初の案件（2026-09-27）で作った。スマホのスピーカーは 150Hz より下がほとんど出ないので、
低い「ドン」（160→55Hz の下降・軽く歪ませて倍音を足す）に、中域の打音（230Hz・短い）と紙のこすれ（帯域を絞ったノイズ）を重ねる。
出力：自作_どすん_札束.wav（48kHz・16bit・モノラル・約0.7秒・頭に0.01秒の無音）"""
import wave
import numpy as np

SR = 48000
n = int(SR * 0.7)
t = np.arange(n) / SR
rng = np.random.default_rng(20260927)

# 低い「ドン」：周波数を下げながら速く減衰
f = 55 + (160 - 55) * np.exp(-t / 0.05)
ph = 2 * np.pi * np.cumsum(f) / SR
body = np.sin(ph) * np.exp(-t / 0.16) * (1 - np.exp(-t / 0.002))
body = np.tanh(2.2 * body) / np.tanh(2.2)            # 軽い歪み＝倍音（小さいスピーカーでも聞こえる）

# 中域の打音
knock = np.sin(2 * np.pi * 230 * t) * np.exp(-t / 0.045) * (1 - np.exp(-t / 0.001))


def band(x, lo, hi):
    X = np.fft.rfft(x)
    fq = np.fft.rfftfreq(len(x), 1 / SR)
    X[(fq < lo) | (fq > hi)] = 0
    return np.fft.irfft(X, len(x))


# 紙のこすれ（札束の「サッ」）
noise = band(rng.standard_normal(n), 700, 5000)
paper = noise / (np.abs(noise).max() + 1e-9) * np.exp(-t / 0.06) * (1 - np.exp(-t / 0.003))

y = 1.0 * body + 0.45 * knock + 0.30 * paper
y = np.concatenate([np.zeros(int(SR * 0.01)), y])
fade = int(SR * 0.08)
y[-fade:] *= np.linspace(1, 0, fade)
y = y / np.abs(y).max() * 10 ** (-3 / 20)            # ピーク −3 dBFS（使うときは add_se.py が音量をそろえる）
with wave.open('自作_どすん_札束.wav', 'wb') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((y * 32767).astype('<i2').tobytes())
print('OK: 自作_どすん_札束.wav', round(len(y) / SR, 3), '秒')
