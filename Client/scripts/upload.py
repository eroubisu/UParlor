"""
上传脚本 — 构建并发布 uparlor 到 PyPI
用法: python upload.py [--test]

流程:
  1. 从 pyproject.toml 读取版本号并确认
  2. 清理旧构建产物
  3. 构建 sdist + wheel
  4. 上传到 PyPI（--test 则上传到 TestPyPI）
"""

import os
import re
import sys
import shutil
import subprocess


def get_version():
    """从 pyproject.toml 读取版本号"""
    toml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")
    with open(toml_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^version\s*=\s*"(.+?)"', line.strip())
            if m:
                return m.group(1)
    print("✗ 未找到版本号")
    sys.exit(1)


def sync_server_version(ver: str, project_dir: str):
    """同步客户端版本号到服务器 config.py 的 CLIENT_VERSION"""
    server_cfg = os.path.join(project_dir, '..', 'Server', 'server', 'config.py')
    server_cfg = os.path.normpath(server_cfg)
    if os.path.exists(server_cfg):
        with open(server_cfg, "r", encoding="utf-8") as f:
            src = f.read()
        src = re.sub(
            r'^(CLIENT_VERSION\s*=\s*)".*?"', rf'\1"{ver}"',
            src, count=1, flags=re.MULTILINE,
        )
        with open(server_cfg, "w", encoding="utf-8") as f:
            f.write(src)


def run(cmd, check=True):
    """执行命令"""
    print(f"  > {cmd}")
    r = subprocess.run(cmd, shell=True)
    if check and r.returncode != 0:
        print(f"  ✗ 失败 (exit {r.returncode})")
        sys.exit(1)
    return r


def main():
    use_test = "--test" in sys.argv
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_dir)

    version = get_version()
    repo_name = "TestPyPI" if use_test else "PyPI"

    print("══════════════════════════════════════")
    print(f"  uparlor v{version} → {repo_name}")
    print("══════════════════════════════════════")

    reply = input(f"\n确认上传 v{version} 到 {repo_name}？[y/N] ").strip().lower()
    if reply != "y":
        print("已取消。")
        return

    # 0. 同步版本号到服务器
    sync_server_version(version, project_dir)

    # 1. 清理旧构建
    print("\n[1/3] 清理旧构建...")
    for d in ("dist", "build"):
        p = os.path.join(project_dir, d)
        if os.path.exists(p):
            shutil.rmtree(p)
            print(f"  - {d}/")

    # 2. 构建
    print("\n[2/3] 构建...")
    run(f"{sys.executable} -m build")

    # 3. 上传
    print(f"\n[3/3] 上传到 {repo_name}...")
    if use_test:
        run(f"{sys.executable} -m twine upload --repository testpypi dist/*")
    else:
        run(f"{sys.executable} -m twine upload dist/*")

    # 4. 清理构建产物
    for d in ("dist", "build"):
        p = os.path.join(project_dir, d)
        if os.path.exists(p):
            shutil.rmtree(p)

    print(f"\n✓ uparlor v{version} 已发布到 {repo_name}")
    if use_test:
        print(f"  pip install -i https://test.pypi.org/simple/ uparlor=={version}")
    else:
        print(f"  pip install uparlor=={version}")


if __name__ == "__main__":
    main()
