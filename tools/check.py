"""Repository gate: policy, syntax, Ruff safety checks, and tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _run(label: str, args: list[str], env: dict[str, str]) -> None:
    print(f"\n==> {label}", flush=True)
    result = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--require-tracked", action="store_true")
    args = parser.parse_args()

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "Client"), str(ROOT / "Server")))

    # tests/ 只在本机保留（不进入仓库），CI 检出中不存在时跳过。
    has_tests = (ROOT / "tests").is_dir()
    source_dirs = ["Client/client", "Server/server", "tools"]
    if has_tests:
        source_dirs.append("tests")

    policy_args = ["tools/repo_policy.py"]
    if args.require_tracked:
        policy_args.append("--require-tracked")
    _run("Repository policy", policy_args, env)
    _run("Python syntax", ["-m", "compileall", "-q", *source_dirs], env)
    _run(
        "Ruff name and dead-local safety",
        [
            "-m", "ruff", "check", *source_dirs,
            "--select", "F401,F821,F822,F823,F841",
            "--output-format", "concise",
        ],
        env,
    )
    if not args.skip_tests:
        _run("Baseball frame invariants",
             ["tools/frame_invariants.py", "--games", "2", "--sizes", "46x19"],
             env)
    if not args.skip_tests and has_tests:
        _run("Pytest", ["-m", "pytest", "-q"], env)

    print("\nAll repository checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
