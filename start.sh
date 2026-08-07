#!/usr/bin/env bash
# Vibe-Research 一键启动（macOS / Linux）
# 用法：
#   ./start.sh              # 启动后端 + 前端
#   ./start.sh --install    # 先安装依赖再启动
#   VIBE_LLM_CLI=claude ./start.sh   # 短线复盘走本机 CLI

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV_PY="$BACKEND/.venv/bin/python"
VENV_PIP="$BACKEND/.venv/bin/pip"
INSTALL=0
BACKEND_PID=""

step() { printf '\n==> %s\n' "$*"; }
cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    step "关闭后端…"
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for arg in "$@"; do
  case "$arg" in
    --install|-i) INSTALL=1 ;;
    -h|--help)
      echo "用法: $0 [--install]"
      echo "环境变量: VIBE_LLM_CLI=claude  （短线复盘用本机 CLI）"
      exit 0
      ;;
  esac
done

command -v python3 >/dev/null || { echo "未找到 python3"; exit 1; }
command -v npm >/dev/null || { echo "未找到 npm"; exit 1; }

if [[ ! -x "$VENV_PY" ]]; then
  step "创建 Python 虚拟环境…"
  python3 -m venv "$BACKEND/.venv"
fi

if [[ "$INSTALL" -eq 1 ]] || ! "$VENV_PY" -c "import fastapi, langgraph, langchain_openai" >/dev/null 2>&1; then
  step "安装后端依赖（首次可能较慢）…"
  "$VENV_PIP" install -r "$BACKEND/requirements.txt"
  "$VENV_PY" -c "import fastapi, langgraph, langchain_openai" || { echo "依赖安装后仍缺失"; exit 1; }
fi

if [[ "$INSTALL" -eq 1 ]] || [[ ! -d "$FRONTEND/node_modules" ]]; then
  step "安装前端依赖…"
  (cd "$FRONTEND" && npm install)
fi

# backend/.env 由 app.py 启动时自动加载
step "启动后端 http://127.0.0.1:8900"
(cd "$BACKEND" && "$VENV_PY" -m uvicorn app:app --host 127.0.0.1 --port 8900) &
BACKEND_PID=$!

for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:8900/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

printf '\n  Vibe-Research\n  后端 :8900  |  前端 :5899  |  浏览器 http://localhost:5899\n\n'

step "启动前端 http://localhost:5899 （Ctrl+C 结束）"
cd "$FRONTEND"
npm run dev
