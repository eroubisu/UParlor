"""
E2E 回归测试入口
用法: python -m tools.e2e.run [--filter <pattern>] [--verbose]
"""

from __future__ import annotations

import gc
import asyncio
import importlib
import inspect
import os
import signal
import sys

# 确保项目根和 Client 在 sys.path，以支持 tools.e2e.* 和 client.* 导入
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in [_ROOT, os.path.join(_ROOT, "Client")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.e2e.harness import start_server, stop_server, run_single_test
from tools.e2e.reporter import Reporter


_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

# 按执行顺序排列
_TEST_MODULES = [
    "tools.e2e.tests.test_login",
    "tools.e2e.tests.test_navigation",
    "tools.e2e.tests.test_vim_modes",
    "tools.e2e.tests.test_cmd_menu",
    "tools.e2e.tests.test_space_menu",
    "tools.e2e.tests.test_chat",
    "tools.e2e.tests.test_inventory",
    "tools.e2e.tests.test_status",
    "tools.e2e.tests.test_online",
    "tools.e2e.tests.test_notification",
    "tools.e2e.tests.test_commands",
    "tools.e2e.tests.test_layout",
    "tools.e2e.tests.test_world",
    "tools.e2e.tests.test_holdem",
    "tools.e2e.tests.test_blackjack",
    "tools.e2e.tests.test_doudizhu",
    "tools.e2e.tests.test_chess",
    "tools.e2e.tests.test_mahjong",
    "tools.e2e.tests.test_wordle",
    "tools.e2e.tests.test_game_lifecycle",
    "tools.e2e.tests.test_game_insert",
    "tools.e2e.tests.test_game_help",
    "tools.e2e.tests.test_game_quit",
    "tools.e2e.tests.test_edge_cases",
]


def _discover_tests(filter_pattern: str = "") -> list:
    """发现所有 async def test_* 函数"""
    tests = []
    for mod_path in _TEST_MODULES:
        try:
            mod = importlib.import_module(mod_path)
        except Exception as e:
            print(f"  导入失败: {mod_path}: {e}")
            continue
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            if not asyncio.iscoroutinefunction(fn):
                continue
            if getattr(fn, '_parametrized', False):
                continue
            full_name = f"{mod_path.split('.')[-1]}.{name}"
            if filter_pattern and filter_pattern not in full_name:
                continue
            tests.append(fn)
    return tests


async def _run_all(tests: list, reporter: Reporter):
    for test_fn in tests:
        await run_single_test(test_fn, reporter)
        gc.collect()
        await asyncio.sleep(2.0)  # 等待服务器处理上一连接的断开


def main():
    import argparse
    parser = argparse.ArgumentParser(description="E2E 回归测试")
    parser.add_argument("--filter", "-f", default="", help="只运行名称含此字符串的测试")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    print(f"\n  {_BOLD}═══ E2E Tests ═══{_RESET}\n")

    # 启动服务器
    print(f"  {_DIM}启动服务器...{_RESET}")
    try:
        server_proc = start_server()
    except RuntimeError as e:
        print(f"  {e}")
        sys.exit(1)

    def _cleanup(*_a):
        stop_server(server_proc)
        sys.exit(1)

    signal.signal(signal.SIGINT, _cleanup)

    print(f"  {_DIM}服务器就绪{_RESET}\n")

    # 发现测试
    tests = _discover_tests(args.filter)
    if not tests:
        print("  没有找到匹配的测试")
        stop_server(server_proc)
        sys.exit(0)

    print(f"  {_DIM}发现 {len(tests)} 个测试{_RESET}\n")

    # 执行测试
    reporter = Reporter(verbose=args.verbose)
    try:
        asyncio.run(_run_all(tests, reporter))
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(server_proc)

    # 汇总
    success = reporter.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
