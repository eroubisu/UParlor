"""游戏大厅 - 服务器入口"""

import sys
import threading
import time

from .chat_server import ChatServer


def main():
    server = ChatServer()

    server_thread = threading.Thread(target=server.start)
    server_thread.daemon = True
    server_thread.start()

    if sys.stdin.isatty():
        print("\n输入 'quit' 或 'exit' 关闭服务器")
        print("或按 Ctrl+C 强制关闭\n")
        try:
            while True:
                cmd = input().strip().lower()
                if cmd in ('quit', 'exit', 'q'):
                    print("正在关闭服务器...")
                    server.stop()
                    break
        except KeyboardInterrupt:
            print("\n正在关闭服务器...")
            server.stop()
    else:
        print("\n[后台模式] 服务器运行中...")
        print("使用 'pkill -f server.py' 停止服务器\n")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            server.stop()

    print("服务器已关闭")
