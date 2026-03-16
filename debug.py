"""
调试启动脚本
用法:
  python debug.py -s    # 安装并启动服务器（当前终端）
  python debug.py -c    # 安装并启动客户端（当前终端，连接本地服务器）

多开测试: 一个终端 -s，多个终端各自 -c
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(ROOT, "Server")
CLIENT_DIR = os.path.join(ROOT, "Client")


def _install(target):
    """以 editable 模式安装指定目标"""
    label, cwd = ("Server", SERVER_DIR) if target == "s" else ("Client", CLIENT_DIR)
    print(f"[debug] 安装 {label} ...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
        cwd=cwd,
    )
    if r.returncode != 0:
        print(f"[debug] {label} 安装失败")
        sys.exit(1)
    print("[debug] 安装完成\n")


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("-s", "-c"):
        print("用法:")
        print("  python debug.py -s    启动服务器")
        print("  python debug.py -c    启动客户端")
        sys.exit(1)

    mode = args[0][1]  # 's' or 'c'
    _install(mode)

    if args[0] == "-s":
        sys.path.insert(0, SERVER_DIR)
        from server import main as server_main
        server_main()
    else:
        os.environ["UPARLOR_HOST"] = "127.0.0.1"
        os.chdir(CLIENT_DIR)
        sys.path.insert(0, CLIENT_DIR)
        from client.app import main as client_main
        client_main()


if __name__ == "__main__":
    main()
