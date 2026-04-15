"""reporter.py — 统一彩色终端报告"""

from __future__ import annotations

import sys
import time


# ── ANSI 颜色 ──

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"


class Reporter:
    """收集测试结果并输出格式化报告"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._results: list[dict] = []
        self._start_time = time.monotonic()

    def test_start(self, name: str):
        sys.stdout.write(f"  {_DIM}[RUN]{_RESET}  {name}\r")
        sys.stdout.flush()

    def test_pass(self, name: str, elapsed: float):
        self._results.append({"name": name, "status": "pass", "elapsed": elapsed})
        sys.stdout.write(f"  {_GREEN}[PASS]{_RESET} {name}{_DIM}  {elapsed:.1f}s{_RESET}\n")
        sys.stdout.flush()

    def test_fail(self, name: str, elapsed: float, error: str, snapshot: str = ""):
        self._results.append({
            "name": name, "status": "fail",
            "elapsed": elapsed, "error": error,
        })
        sys.stdout.write(f"  {_RED}[FAIL]{_RESET} {name}{_DIM}  {elapsed:.1f}s{_RESET}\n")
        for line in error.strip().splitlines():
            sys.stdout.write(f"         {_RED}{line}{_RESET}\n")
        if snapshot:
            for line in snapshot.strip().splitlines():
                sys.stdout.write(f"         {_DIM}{line}{_RESET}\n")
        sys.stdout.flush()

    def test_error(self, name: str, elapsed: float, error: str):
        self._results.append({
            "name": name, "status": "error",
            "elapsed": elapsed, "error": error,
        })
        sys.stdout.write(f"  {_YELLOW}[ERR]{_RESET}  {name}{_DIM}  {elapsed:.1f}s{_RESET}\n")
        for line in error.strip().splitlines():
            sys.stdout.write(f"         {_YELLOW}{line}{_RESET}\n")
        sys.stdout.flush()

    def summary(self):
        total = time.monotonic() - self._start_time
        passed = sum(1 for r in self._results if r["status"] == "pass")
        failed = sum(1 for r in self._results if r["status"] == "fail")
        errors = sum(1 for r in self._results if r["status"] == "error")

        sys.stdout.write(f"\n  {'─' * 52}\n")
        parts = []
        if passed:
            parts.append(f"{_GREEN}{passed} passed{_RESET}")
        if failed:
            parts.append(f"{_RED}{failed} failed{_RESET}")
        if errors:
            parts.append(f"{_YELLOW}{errors} errors{_RESET}")
        summary_str = ", ".join(parts) if parts else "no tests"
        sys.stdout.write(
            f"  {summary_str}{_DIM}  in {total:.1f}s{_RESET}\n\n"
        )
        sys.stdout.flush()
        return failed == 0 and errors == 0
