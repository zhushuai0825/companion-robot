#!/usr/bin/env bash
# 树莓派上一键更新代码并检测说话链路（在 Pi 上运行）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== companion-robot 语音环境 ==="
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [[ ! -f src/.env ]]; then
  echo "缺少 src/.env — 请从 Mac 复制（含 DEEPSEEK_API_KEY、MINIMAX_API_KEY）"
  cp src/.env.example src/.env
  exit 1
fi

git pull origin main 2>/dev/null || echo "（非 git 目录，跳过 pull）"

echo
echo "=== 音频硬件 ==="
python3 scripts/test_audio.py || true

echo
echo "=== MiniMax 男声试听 ==="
python3 scripts/test_minimax_tts.py

echo
echo "完成。启动路遥: python3 src/companion_voice.py"
