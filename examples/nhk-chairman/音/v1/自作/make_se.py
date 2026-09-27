#!/usr/bin/env python3
"""NHK会長編の自作効果音（無料・ローカル・権利の問題なし。2026-09-28）。
- 自作_ピコ_01〜09.wav：12の席が1つ点くたびに鳴る短い電子音。1つごとに音程が上がる（ド→レ→…と長調で9段）
- 自作_ブッ.wav：9つ目の灯が消えるときの低いブザー（不成立）
出力はどれも 48kHz・16bit・モノラル・頭に0.01秒の無音。音量は add_se.py がそろえる。"""
import wave
import numpy as np

SR = 48000


def save(name, y):
    y = np.concatenate([np.zeros(int(SR * 0.01)), y])
    y = y / (np.abs(y).max() + 1e-9) * 10 ** (-3 / 20)
    with wave.open(name, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((y * 32767).astype('<i2').tobytes())


# ピコ：矩形波寄りの明るい音（小さいスピーカーでも聞こえる）＋ 1オクターブ上を少し。0.11秒
semis = [0, 2, 4, 5, 7, 9, 11, 12, 16]           # ド レ ミ ファ ソ ラ シ ド ミ（9つ目は高く）
for i, s in enumerate(semis, 1):
    f = 880 * 2 ** (s / 12)
    n = int(SR * (0.11 if i < 9 else 0.22))
    t = np.arange(n) / SR
    env = np.exp(-t / (0.035 if i < 9 else 0.08)) * (1 - np.exp(-t / 0.001))
    tone = np.tanh(3 * np.sin(2 * np.pi * f * t)) + 0.35 * np.sin(2 * np.pi * 2 * f * t)
    save(f'自作_ピコ_{i:02d}.wav', tone * env)

# ブッ：低い矩形波のブザー（140Hz→110Hz）0.35秒
n = int(SR * 0.35)
t = np.arange(n) / SR
f = 110 + 30 * np.exp(-t / 0.08)
ph = 2 * np.pi * np.cumsum(f) / SR
buzz = np.sign(np.sin(ph)) * 0.8 + 0.3 * np.sin(2 * ph)
env = (1 - np.exp(-t / 0.004)) * np.clip((0.35 - t) / 0.06, 0, 1)
save('自作_ブッ.wav', buzz * env)
print('ok')
