"""Commit size limit counts only code, not tests, docs, or binaries."""

from tools.commit_size import changed_lines


def test_only_code_roots_count():
    numstat = (
        "10\t5\tClient/client/app.py\n"
        "900\t0\ttests/test_big.py\n"
        "-\t-\tServer/server/logo.png\n"
        "3\t2\ttools/check.py\n"
    )

    assert changed_lines(numstat) == 20
