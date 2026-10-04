#!/usr/bin/env bash
# 一条命令启动整个系统：./start.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "首次运行，创建虚拟环境…"
  python3 -m venv .venv 2>/dev/null || python3 -m venv --without-pip .venv
fi
source .venv/bin/activate

# 部分系统缺少 ensurepip，需要引导安装 pip
if ! python -m pip --version >/dev/null 2>&1; then
  echo "引导安装 pip…"
  curl -sSL --max-time 120 https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  python /tmp/get-pip.py -q
fi

pip install -q -r requirements.txt

PORT="${PORT:-8000}"
echo ""
echo "  系统地址：       http://localhost:${PORT}"
echo "  模拟保险接口：   http://localhost:${PORT}/mock-insurance/docs"
echo "  业务 API 文档：  http://localhost:${PORT}/docs"
echo ""
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
