"""harness.py — 测试驾具：管理服务器进程 + App 生命周期"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import traceback

from .reporter import Reporter

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SERVER_DIR = os.path.join(_ROOT, "Server")
_CLIENT_DIR = os.path.join(_ROOT, "Client")
_PORT = 5555
_TEST_TIMEOUT = 60  # 秒/测试
_TEST_PASS = "test123"
_test_counter = 0


def _next_test_user() -> str:
    """返回下一个唯一测试用户名"""
    global _test_counter
    _test_counter += 1
    return f"e2e{_test_counter}"


def _ensure_test_users(count: int):
    """在服务器数据目录预创建 count 个测试用户"""
    if _SERVER_DIR not in sys.path:
        sys.path.insert(0, _SERVER_DIR)
    from server.player.manager import PlayerManager
    for i in range(1, count + 1):
        name = f"e2e{i}"
        if not PlayerManager.player_exists(name):
            PlayerManager.register_player(name, _TEST_PASS)
        else:
            # 清除残留世界状态，确保每次测试从出生点开始
            world_file = os.path.join(
                _SERVER_DIR, "data", "users", name, "games", "world.json"
            )
            if os.path.exists(world_file):
                os.remove(world_file)


# ── 服务器管理 ──

def start_server(test_count: int = 100) -> subprocess.Popen:
    """启动服务器进程，等待端口可用"""
    _ensure_test_users(test_count)
    proc = subprocess.Popen(
        [sys.executable, "-m", "server"],
        cwd=_SERVER_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            s = socket.create_connection(("127.0.0.1", _PORT), timeout=1)
            s.close()
            return proc
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError("服务器启动失败")
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("服务器启动超时")


def stop_server(proc: subprocess.Popen):
    """终止服务器进程"""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── App 工厂 ──

def _create_app():
    """构造 UParlorApp 实例（跳过版本检查、直连本地）"""
    os.environ["UPARLOR_HOST"] = "127.0.0.1"
    # 确保 client 包可导入
    for _p in [_CLIENT_DIR, _ROOT]:
        if _p not in sys.path:
            sys.path.insert(0, _p)
    from client.app import UParlorApp
    return UParlorApp()


# ── 测试执行 ──

async def run_single_test(test_fn, reporter: Reporter) -> bool:
    """运行单个异步测试函数，返回是否通过"""
    name = f"{test_fn.__module__.split('.')[-1]}.{test_fn.__name__}"
    reporter.test_start(name)
    t0 = time.monotonic()

    # 每个测试用唯一用户名，避免「已在线」冲突
    username = _next_test_user()

    app = _create_app()
    app._e2e_username = username
    app._e2e_password = _TEST_PASS
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            try:
                await asyncio.wait_for(test_fn(pilot), timeout=_TEST_TIMEOUT)
                elapsed = time.monotonic() - t0
                reporter.test_pass(name, elapsed)
                return True
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - t0
                snapshot = _snapshot(app)
                reporter.test_fail(name, elapsed, f"超时 ({_TEST_TIMEOUT}s)", snapshot)
                return False
            except AssertionError as e:
                elapsed = time.monotonic() - t0
                snapshot = _snapshot(app)
                reporter.test_fail(name, elapsed, str(e) or "AssertionError", snapshot)
                return False
            except Exception:
                elapsed = time.monotonic() - t0
                reporter.test_error(name, elapsed, traceback.format_exc())
                return False
    except Exception:
        elapsed = time.monotonic() - t0
        reporter.test_error(name, elapsed, traceback.format_exc())
        return False


def _snapshot(app) -> str:
    """捕获当前 app 状态用于失败诊断"""
    from client.ui.screen import GameScreen
    parts = []
    parts.append(f"mode={app.vim.mode_label}")
    screen = app.screen
    if isinstance(screen, GameScreen):
        parts.append(f"location={screen.current_location}")
        parts.append(f"logged_in={screen.logged_in}")
        parts.append(f"panel={screen._focused_module()}")
        parts.append(f"cmd_select={screen._cmd_select_mode}")
    return "State: " + ", ".join(parts)
