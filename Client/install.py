"""
本地安装脚本 — 以开发模式安装 uparlor 到当前 venv
用法: python install.py

等同于 pip install -e .，但版本号自动加 .dev 后缀，
与 PyPI 正式版区分。
"""

import os
import re
import subprocess
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_TOML = os.path.join(_DIR, "pyproject.toml")
_VER_RE = re.compile(r'^(version\s*=\s*")(.+?)(")', re.MULTILINE)


def _read_toml():
    with open(_TOML, "r", encoding="utf-8") as f:
        return f.read()


def _write_toml(text):
    with open(_TOML, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    original = _read_toml()
    m = _VER_RE.search(original)
    if not m:
        print("✗ 未找到版本号")
        sys.exit(1)

    base_ver = m.group(2)
    dev_ver = f"{base_ver}.dev0"
    patched = _VER_RE.sub(rf"\g<1>{dev_ver}\3", original)

    print(f"安装 uparlor {dev_ver} (editable mode) ...")
    _write_toml(patched)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            cwd=_DIR,
        )
    finally:
        _write_toml(original)

    if result.returncode == 0:
        print(f"\n✓ 安装成功 ({dev_ver})。运行 uparlor 启动客户端。")
    else:
        print("\n✗ 安装失败。")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
