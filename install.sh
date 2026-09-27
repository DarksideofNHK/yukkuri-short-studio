#!/bin/bash
# スキルを ~/.claude/skills に（シンボリックリンク）、yukkuri コマンドを ~/.local/bin に入れる。
# 同じ名前のスキルがリンク以外で既にあるときは上書きしない。
set -e
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.claude/skills" "$HOME/.local/bin"

for s in yukkuri-short-studio premiere-short-xml yukkuri-voice; do
  dst="$HOME/.claude/skills/$s"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "スキップ: $dst が既にある（リンクではないので上書きしない）"
    continue
  fi
  ln -sfn "$here/skills/$s" "$dst"
  echo "スキル: $dst → $here/skills/$s"
done

bin="$HOME/.local/bin/yukkuri"
if [ -L "$bin" ] || { [ -e "$bin" ] && ! grep -q "yukkuri-short-studio" "$bin"; }; then
  echo "スキップ: $bin が既にある（このリポジトリが作ったものではないので上書きしない）"
else
  cat > "$bin" <<EOF
#!/bin/bash
# yukkuri-short-studio の install.sh が作ったラッパー
exec /usr/bin/env python3 "$here/tools/yukkuri/yukkuri.py" "\$@"
EOF
  chmod +x "$bin"
  echo "コマンド: $bin（PATH に ~/.local/bin があること）"
fi

if [ ! -d /Applications/AquesTalkPlayer.app ]; then
  echo "注意: AquesTalkPlayer が /Applications にない。公式サイトから入手して入れる（規約も確認）"
fi
for c in ffmpeg pdftoppm mecab; do
  command -v "$c" >/dev/null || echo "注意: $c が見つからない（brew install ffmpeg poppler mecab mecab-ipadic）"
done
python3 -c "import PIL, numpy, matplotlib" 2>/dev/null || echo "注意: python3 -m pip install pillow numpy matplotlib"
python3 -c "import mlx_whisper" 2>/dev/null || echo "注意: 聞き取り確認に mlx-whisper が要る（python3 -m pip install mlx-whisper）"
