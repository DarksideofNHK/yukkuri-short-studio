#!/bin/bash
# ダブルクリックで看板ボードを開く（サーバーが止まっていれば起動する）
cd "$(dirname "$0")"
if ! curl -s -o /dev/null http://127.0.0.1:8765/api/state; then
  nohup python3 ../../tools/studio/studio.py serve --port 8765 > .board_server.log 2>&1 &
  sleep 1
fi
open http://127.0.0.1:8765/
