#!/usr/bin/env python3
"""動く背景（V1）を作る：media_anim/BG_{id}_動き.mov（1080×1920・30fps・H.264）。

背景の区間（timeline.json の V1 のクリップ）ごとに1本。どの区間も同じ部品で、色だけ変える：
  ・上下のグラデーション＋外周を暗く（読みやすさ）
  ・斜めに流れる光の帯（いつも何かが動いている）
  ・ゆっくり回る放射状の光（中心は図の場所 y≈620）
  ・上へ漂う光の粒（またたく）
  ・BGM の拍（150BPM）に合わせて中心がふっと明るくなる
  ・山場のフレームで集中線＋白いフラッシュ（数フレームで消える）
  ・区間の頭で、前の区間の色から斜めのワイプで切り替わる
  ・BG1 だけテレビの走査線（放送局の場面）
使い方: python3 make_bg_anim.py  （build_all.py のあと。作ったら build_premiere.py をもう一度）
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

W_, H_ = 1080, 1920
FPS = 30
BASE = Path(__file__).parent
OUT = BASE / "media_anim"
CFG = json.loads((BASE / "bg_anim.json").read_text(encoding="utf-8"))

PAL = {  # 上の色・下の色・差し色
    "BG1": ((30, 48, 88), (8, 12, 26), (90, 170, 255)),
    "BG2": ((44, 48, 60), (12, 13, 18), (255, 196, 64)),
    "BG3": ((44, 30, 84), (12, 8, 26), (255, 84, 140)),
}

yy, xx = np.mgrid[0:H_, 0:W_].astype(np.float32)
CX, CY = 540.0, 620.0
ANG = np.arctan2(yy - CY, xx - CX)
RAD = np.hypot(xx - CX, yy - CY)
VIGN = np.clip(1.0 - (np.hypot((xx - 540) / 700, (yy - 960) / 1150) ** 2) * 0.55, 0.35, 1.0)[..., None]


def grad(top, bot):
    t = (yy / (H_ - 1))[..., None]
    return np.array(top, np.float32) * (1 - t) + np.array(bot, np.float32) * t


def beats_frames():
    """BGM の拍（映像のフレーム）。曲を decode して、0.4秒おきの格子の位相を合わせ、音の出ている拍だけ残す。"""
    b = CFG["bgm"]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", b["file"], "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(raw, np.float32)
    sr, hop = 48000, 480                                    # 10ms
    env = np.sqrt(np.add.reduceat(y[: len(y) // hop * hop] ** 2, np.arange(0, len(y) // hop * hop, hop)) / hop)
    flux = np.maximum(np.diff(env, prepend=env[0]), 0)
    period = 60.0 / b["bpm"]
    best = max(np.arange(0, period, 0.01), key=lambda ph: sum(flux[int((ph + k * period) * 100)]
                                                              for k in range(int((len(env) / 100 - ph) / period))))
    out = []
    for clip in b["clips"]:                                 # [映像の開始f, 終了f, 曲の何秒から]
        f0, f1, ins = clip
        k = 0
        while True:
            ts = best + k * period
            k += 1
            f = f0 + round((ts - ins) * FPS)
            if ts < ins:
                continue
            if f >= f1:
                break
            if 20 * np.log10(env[min(int(ts * 100), len(env) - 1)] + 1e-9) > -30:   # ためで音が引いている拍は光らせない
                out.append(f)
    return sorted(set(out))


def particles(seed, n=70):
    r = np.random.default_rng(seed)
    return dict(x=r.uniform(0, W_, n), y=r.uniform(0, H_, n), v=r.uniform(0.6, 2.2, n), s=r.uniform(2, 6, n),
                ph=r.uniform(0, 6.28, n), w=r.uniform(0.02, 0.06, n))


def render(bg_id, f0, f1, prev_id, beats, impacts):
    top, bot, acc = PAL[bg_id]
    base = grad(top, bot)
    prev = grad(*PAL[prev_id][:2]) if prev_id else None
    accv = np.array(acc, np.float32)
    P = particles(hash(bg_id) % 1000)
    n = f1 - f0
    OUT.mkdir(exist_ok=True)
    dst = OUT / f"BG_{bg_id}_動き.mov"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W_}x{H_}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)], stdin=subprocess.PIPE)
    for i in range(n):
        f = f0 + i
        t = f / FPS
        img = base.copy()
        # 斜めの光の帯（右下へ流れる）
        band = 0.5 + 0.5 * np.sin((xx + yy) * 0.012 - t * 2.4)
        img += accv * (band ** 6 * 0.10)[..., None]
        # 放射状の光（ゆっくり回る）
        rays = np.clip(np.cos(ANG * 12 - t * 0.35), 0, 1) ** 3 * np.clip(1 - RAD / 1400, 0, 1)
        img += accv * (rays * 0.07)[..., None]
        # 拍の脈（中心がふっと明るく）
        pulse = max([np.exp(-(f - b) / 5.0) for b in beats if 0 <= f - b < 20] or [0])
        if pulse:
            img += accv * (np.exp(-(RAD / 520) ** 2) * 0.18 * pulse)[..., None]
        # 山場：集中線＋フラッシュ
        hit = [(f - h, s, h) for h, s in impacts if 0 <= f - h < 10]
        if hit:
            d, s, h = hit[0]
            k = np.exp(-d / 3.0) * s
            lines = (np.clip(np.cos(ANG * 48 + (hash(str(h)) % 7)), 0, 1) ** 12) * np.clip((RAD - 260) / 500, 0, 1)
            img += 255 * (lines * 0.35 * k)[..., None]
            img += 255 * 0.22 * np.exp(-d / 1.5) * s
        # 走査線（BG1 だけ・ゆっくり下へ）
        if bg_id == "BG1":
            img *= (1 - 0.06 * ((yy + t * 40) % 6 < 2))[..., None]
        img = img * VIGN
        # 光の粒
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        ov = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        py = (P["y"] - t * FPS * P["v"]) % H_
        px = P["x"] + 18 * np.sin(t * 1.3 + P["ph"])
        tw = 0.45 + 0.55 * (0.5 + 0.5 * np.sin(t * 5 * P["w"] * 20 + P["ph"]))
        for x, y2, s, a in zip(px, py, P["s"], tw):
            d.ellipse([x - s, y2 - s, x + s, y2 + s], fill=tuple(acc) + (int(150 * a),))
        im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        # 区間の頭：前の区間の色から斜めワイプ（8フレーム）
        if prev is not None and i < 8:
            edge = (i + 1) / 8 * (W_ + H_ * 0.5)
            mask = (xx + yy * 0.5) > edge
            a = np.array(im, np.float32)
            a[mask] = (prev * VIGN)[mask]
            glow = np.exp(-((xx + yy * 0.5 - edge) / 18) ** 2)
            a += 255 * (glow * 0.6)[..., None]
            im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        enc.stdin.write(im.tobytes())
    enc.stdin.close()
    enc.wait()
    return dst, n


def main():
    tl = json.loads((BASE / "timeline.json").read_text(encoding="utf-8"))
    bgs = [c for c in tl["clips"] if c.get("track") == "V1"]
    beats = beats_frames()
    impacts = [(h["f"], h.get("s", 1.0)) for h in CFG["impacts"]]
    print(f"拍 {len(beats)} 個（最初 {beats[:4]}）・山場 {len(impacts)} か所")
    prev = None
    for c in sorted(bgs, key=lambda c: c["start"]):
        bid = next(k for k in PAL if f"{k}_" in Path(c["file"]).name or Path(c["file"]).name.startswith(k))
        dst, n = render(bid, c["start"], c["end"], prev, beats, impacts)
        print(f"{dst.name}: {n} フレーム")
        prev = bid


if __name__ == "__main__":
    main()
