"""
本地安装脚本 — 以开发模式安装 uparlor 到当前 venv
用法: python install.py

等同于 pip install -e .
"""

import subprocess
import sys


def main():
    print("安装 uparlor 到本地 (editable mode) ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=__import__("os").path.dirname(__import__("os").path.abspath(__file__)),
    )
    if result.returncode == 0:
        print("\n✓ 安装成功。运行 uparlor 启动客户端。")
    else:
        print("\n✗ 安装失败。")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
