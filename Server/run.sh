#!/bin/bash
# 后台启动游戏大厅服务器
# 用法: ./run.sh [port]

cd "$(dirname "$0")"
PORT="${1:-11451}"

if [ -f server.pid ]; then
    OLD_PID=$(cat server.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "服务器已在运行 (PID: $OLD_PID)"
        exit 1
    fi
    rm server.pid
fi

nohup python3 server.py "$PORT" > server.log 2>&1 &
echo $! > server.pid
echo "服务器已启动 (PID: $(cat server.pid), 端口: $PORT)"
echo "日志: tail -f server.log"
