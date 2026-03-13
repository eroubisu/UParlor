#!/bin/bash
# 停止游戏大厅服务器

cd "$(dirname "$0")"

if [ -f server.pid ]; then
    PID=$(cat server.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm server.pid
        echo "服务器已停止 (PID: $PID)"
    else
        rm server.pid
        echo "进程已不存在，已清理 PID 文件"
    fi
else
    echo "未找到 server.pid，服务器可能未运行"
fi
