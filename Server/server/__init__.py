"""游戏大厅 - 服务器入口"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from .chat_server import ChatServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)


def main():
    server = ChatServer()

    def _graceful_stop(signum=None, frame=None):
        logging.info("正在关闭服务器...")
        server.graceful_stop()

    # 注册信号（非 Windows 可用 SIGTERM）
    signal.signal(signal.SIGINT, _graceful_stop)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _graceful_stop)

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
                    _graceful_stop()
                    break
        except (KeyboardInterrupt, EOFError):
            _graceful_stop()
    else:
        print("\n[后台模式] 服务器运行中...")
        print("发送 SIGTERM 停止服务器\n")
        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, EOFError):
            _graceful_stop()

    print("服务器已关闭")
