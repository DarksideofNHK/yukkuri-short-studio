"""NHK会長編 v1 の素材を作業フォルダにそろえる（何度流しても同じ結果）。"""
from pathlib import Path
from PIL import Image, ImageDraw
import shutil
W = Path(__file__).parent
P = W.parent.parent
E = P / "絵/NHK_JS_Paint素材_v2/元サイズ"
F = P / "図/v1"
C = W / "chars_src"
for d in (C, W / "bg_src", W / "shots_src"):   # 初めて流すときにフォルダを作る
    d.mkdir(parents=True, exist_ok=True)

# 人物・建物（Codex の JS Paint。RGBA に直して置く）
for src, dst in [("NHK_井上樹彦_v2_01_ぽかん.png", "inoue_01_pokan.png"),
                 ("NHK_井上樹彦_v2_02_困り顔.png", "inoue_02_komari.png"),
                 ("NHK_放送センター_01.png", "nhk_center.png")]:
    Image.open(E / src).convert("RGBA").save(C / dst)

# 12の席（そのまま）と視聴者の家・矢印・✗
for f in sorted(F.glob("seats_*.png")) + sorted(F.glob("viewer_*.png")):
    shutil.copy(f, C / f.name)

# 3段の図：同じ枠（flow_all の範囲）で切り、四隅にほぼ透明の点を打って「中身の範囲＝画像全体」にする
# （chars の ref:center は中身の中心に置くので、こうしないと段ごとに位置がずれる）
box = Image.open(F / "flow_all.png").getchannel("A").getbbox()
for f in ["flow_01_pm.png", "flow_02_committee.png", "flow_03_chair_frame.png", "flow_all.png"]:
    im = Image.open(F / f).convert("RGBA").crop(box)
    px = im.load()
    for x, y in [(0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)]:
        px[x, y] = (0, 0, 0, 1)
    im.save(C / f)

# 背景（自作のグラデーション。暗めの紺・灰・藍）
def grad(name, top, bottom):
    im = Image.new("RGB", (1080, 1920))
    d = ImageDraw.Draw(im)
    for y in range(1920):
        t = y / 1919
        d.line([(0, y), (1079, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    im.save(W / "bg_src" / name)
grad("bg_01_navy.png", (28, 44, 78), (10, 14, 28))
grad("bg_02_slate.png", (40, 46, 56), (14, 16, 20))
grad("bg_03_indigo.png", (36, 30, 70), (12, 10, 24))

shutil.copy(P / "スクショ/v1/放送法52条_e-Gov.png", W / "shots_src" / "SH1_放送法52条_e-Gov.png")
print("ok", len(list(C.iterdir())), "chars")
