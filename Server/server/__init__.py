"""游戏大厅 - 服务器入口"""

from __future__ import annotations

import logging
import signal
import sys
import threading

from .chat_server import ChatServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)


def main():
    server = ChatServer()
    shutdown_event = threading.Event()
    shutdown_lock = threading.Lock()
    stop_requested = False

    def _graceful_stop(signum=None, frame=None):
        nonlocal stop_requested
        _ = signum, frame
        with shutdown_lock:
            if stop_requested:
                return
            stop_requested = True
        logging.info("正在关闭服务器...")
        try:
            server.graceful_stop()
        finally:
            shutdown_event.set()

    # 注册信号（非 Windows 可用 SIGTERM）
    signal.signal(signal.SIGINT, _graceful_stop)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _graceful_stop)

    server_thread = threading.Thread(target=server.start)
    server_thread.start()

    try:
        if sys.stdin.isatty():
            print("\n输入 'quit' 或 'exit' 关闭服务器")
            print("或按 Ctrl+C 强制关闭\n")
            while True:
                cmd = input().strip().lower()
                if cmd in ('quit', 'exit', 'q'):
                    _graceful_stop()
                    break
        else:
            print("\n[后台模式] 服务器运行中...")
            print("发送 SIGTERM 停止服务器\n")
            while server_thread.is_alive() and not shutdown_event.wait(0.1):
                pass
    except (KeyboardInterrupt, EOFError):
        _graceful_stop()
    finally:
        _graceful_stop()
        server_thread.join()

    print("服务器已关闭")
