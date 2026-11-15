"""Reject code commits too large to review: one change per commit."""

from __future__ import annotations

import os
import subprocess
import sys

CODE_ROOTS = ("Client/", "Server/", "tools/")
MAX_CHANGED_LINES = 1500
OVERRIDE_ENV = "UPARLOR_ALLOW_LARGE_COMMIT"


def changed_lines(numstat: str) -> int:
    """Sum added + deleted lines of code files from `git diff --numstat` output."""
    total = 0
    for line in numstat.splitlines():
        added, deleted, path = line.split("\t", 2)
        if added == "-" or not path.startswith(CODE_ROOTS):
            continue
        total += int(added) + int(deleted)
    return total


def main() -> int:
    numstat = subprocess.run(
        ["git", "diff", "--cached", "--numstat"],
        capture_output=True, text=True, check=True,
    ).stdout
    total = changed_lines(numstat)
    if total <= MAX_CHANGED_LINES or os.environ.get(OVERRIDE_ENV):
        return 0
    print(
        f"Commit changes {total} code lines (limit {MAX_CHANGED_LINES}). "
        f"Split it into smaller commits, or set {OVERRIDE_ENV}=1 for a "
        "deliberate large change.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
