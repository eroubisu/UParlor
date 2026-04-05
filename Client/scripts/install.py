"""
本地安装脚本 — 以开发模式安装 uparlor 到当前 venv
用法: python Client/scripts/install.py

等同于 pip install -e .，但版本号自动加 .dev 后缀，
与 PyPI 正式版区分。
"""

import os
import re
import shutil
import subprocess
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOML = os.path.join(_DIR, "pyproject.toml")
_VER_RE = re.compile(r'^(version\s*=\s*")(.+?)(")', re.MULTILINE)


def _read_toml():
    with open(_TOML, "r", encoding="utf-8") as f:
        return f.read()


def _write_toml(text):
    with open(_TOML, "w", encoding="utf-8") as f:
        f.write(text)


def _check_path_conflict():
    """检查 PATH 上的 uparlor 是否指向当前 venv"""
    venv_scripts = os.path.join(sys.prefix, 'Scripts')
    result = shutil.which('uparlor')
    if result and not os.path.normcase(result).startswith(
            os.path.normcase(venv_scripts)):
        print(f"\n⚠ PATH 上的 uparlor 指向: {result}")
        print(f"  而非当前环境:         {venv_scripts}")
        print(f"  请先激活 venv 再运行 uparlor。")


def main():
    if sys.prefix == sys.base_prefix:
        print("⚠ 未检测到虚拟环境，建议在 venv 中运行此脚本。")

    original = _read_toml()
    m = _VER_RE.search(original)
    if not m:
        print("✗ 未找到版本号")
        sys.exit(1)

    base_ver = m.group(2)
    dev_ver = base_ver if base_ver.endswith('.dev0') else f"{base_ver}.dev0"
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
        print(f"\n✓ 安装成功 ({dev_ver})。")
        _check_path_conflict()
    else:
        print("\n✗ 安装失败。")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
