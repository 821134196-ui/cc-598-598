#!/usr/bin/env bash
# 汽车玻璃保险直赔与安装验收系统 —— 一条命令启动
# 用法：./run.sh        （首次运行自动安装依赖、初始化数据库与演示数据）
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"

# 1) 依赖（若系统 Python 标记 PEP 668，则使用 --break-system-packages；有 venv 时正常安装）
if ! "$PYTHON" -c "import fastapi, uvicorn, sqlalchemy, multipart" 2>/dev/null; then
  echo "[run] 正在安装 Python 依赖..."
  "$PYTHON" -m pip install -q -r requirements.txt 2>/dev/null \
    || "$PYTHON" -m pip install -q --break-system-packages -r requirements.txt
fi

# 2) 初始化数据库表 + 演示工单（已存在数据则自动跳过）
"$PYTHON" -m backend.seed

# 3) 启动服务（FastAPI 同时托管 API 与 Vue 前端、本地上传图片）
echo "[run] 服务启动中..."
echo "      门店工作台 / 车主查询: http://localhost:${PORT}/"
echo "      接口文档(Swagger):     http://localhost:${PORT}/docs"
exec "$PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
