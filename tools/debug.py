"""
调试启动脚本 — 一键启动服务器+客户端，关闭客户端时全部退出
用法: python tools/debug.py
"""

import atexit
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, "Server")
CLIENT_DIR = os.path.join(ROOT, "Client")


def _clear_pycache(base_dir):
    """清除指定目录下所有 __pycache__"""
    for root, dirs, _ in os.walk(base_dir):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))


def _install(target):
    """以 editable 模式安装指定目标"""
    label, cwd = ("Server", SERVER_DIR) if target == "s" else ("Client", CLIENT_DIR)
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if r.returncode != 0:
        print(f"[debug] {label} 安装失败")
        sys.exit(1)


def main():
    _clear_pycache(SERVER_DIR)
    _clear_pycache(CLIENT_DIR)
    _install("s")
    _install("c")

    # 后台启动服务器（stdin=PIPE 保持管道开放，避免 EOF 触发退出）
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "server"],
        cwd=SERVER_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _kill_server():
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=3)

    atexit.register(_kill_server)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    # 等待服务器就绪
    for _ in range(30):
        try:
            s = socket.create_connection(("127.0.0.1", 5555), timeout=1)
            s.close()
            break
        except OSError:
            if server_proc.poll() is not None:
                print("[debug] 服务器启动失败")
                sys.exit(1)
            time.sleep(0.2)
    else:
        print("[debug] 服务器启动超时")
        sys.exit(1)

    # 前台启动客户端（连接本地）
    os.environ["UPARLOR_HOST"] = "127.0.0.1"
    os.chdir(CLIENT_DIR)
    sys.path.insert(0, CLIENT_DIR)
    from client.app import main as client_main
    client_main()


if __name__ == "__main__":
    main()
