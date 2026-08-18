"""Read-only periodic quality metrics with a ratcheted repository baseline."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = ROOT / "docs" / "quality" / "quality-baseline.json"
SOURCE_PATHS = ("Client/client", "Server/server", "tools")
VULTURE_LINE = re.compile(
    r"^(?P<path>.+?):\d+: .*?'(?P<name>[^']+)' \(\d+% confidence\)$"
)


class AuditError(RuntimeError):
    """Raised when a quality tool cannot produce a trustworthy result."""


def _run(args: list[str], accepted_codes: set[int]) -> str:
    result = subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode not in accepted_codes:
        detail = (result.stderr or result.stdout).strip()
        raise AuditError(f"{' '.join(args[:2])} failed: {detail}")
    return result.stdout


def _load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _complexity() -> dict[str, int]:
    output = _run(["radon", "cc", *SOURCE_PATHS, "-n", "D", "-j"], {0})
    report = json.loads(output)
    entries: dict[str, int] = {}
    for raw_path, blocks in report.items():
        path = raw_path.replace("\\", "/")
        for block in blocks:
            owner = block.get("classname")
            symbol = f"{owner}.{block['name']}" if owner else block["name"]
            entries[f"{path}:{symbol}"] = block["complexity"]
    return dict(sorted(entries.items()))


def _dead_code() -> list[dict[str, str]]:
    output = _run(
        ["vulture", *SOURCE_PATHS, "--min-confidence", "90"],
        {0, 3},
    )
    findings = []
    for line in output.splitlines():
        match = VULTURE_LINE.match(line)
        if match:
            findings.append({
                "path": match.group("path").replace("\\", "/"),
                "name": match.group("name"),
            })
    return findings


def _duplicate_groups() -> int:
    output = _run([
        "pylint",
        "Client/client",
        "Server/server",
        "--disable=all",
        "--enable=duplicate-code",
        "--min-similarity-lines=12",
        "--score=no",
    ], {0, 8})
    return sum("R0801: Similar lines in" in line for line in output.splitlines())


def _coverage() -> float:
    with tempfile.TemporaryDirectory() as directory:
        report_path = Path(directory) / "coverage.json"
        _run([
            "pytest",
            "--cov=Client/client",
            "--cov=Server/server",
            "--cov=tools",
            f"--cov-report=json:{report_path}",
        ], {0})
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return round(float(report["totals"]["percent_covered"]), 2)


def collect_metrics() -> dict[str, Any]:
    return {
        "coverage_percent": _coverage(),
        "duplicate_groups": _duplicate_groups(),
        "severe_complexity": _complexity(),
        "vulture_findings": _dead_code(),
    }


def assess(metrics: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors = []
    coverage = metrics["coverage_percent"]
    if coverage < baseline["coverage_floor"]:
        errors.append(
            f"coverage {coverage:.2f} is below {baseline['coverage_floor']:.2f}"
        )

    duplicates = metrics["duplicate_groups"]
    if duplicates > baseline["duplicate_group_ceiling"]:
        errors.append(
            f"duplicate groups increased to {duplicates} "
            f"from {baseline['duplicate_group_ceiling']}"
        )

    expected_complexity = baseline["severe_complexity"]
    for identity, score in metrics["severe_complexity"].items():
        if identity not in expected_complexity:
            errors.append(f"new severe complexity: {identity} ({score})")
        elif score > expected_complexity[identity]:
            errors.append(
                f"complexity worsened: {identity} "
                f"{expected_complexity[identity]} -> {score}"
            )

    allowed_dead_code = {
        (item["path"], item["name"])
        for item in baseline["vulture_allowlist"]
    }
    for finding in metrics["vulture_findings"]:
        identity = (finding["path"], finding["name"])
        if identity not in allowed_dead_code:
            errors.append(
                f"new dead-code candidate: {finding['path']}:{finding['name']}"
            )
    return errors


def _format(metrics: dict[str, Any], baseline: dict[str, Any], errors: list[str]) -> str:
    lines = [
        f"coverage={metrics['coverage_percent']:.2f} "
        f"floor={baseline['coverage_floor']:.2f}",
        f"duplicate_groups={metrics['duplicate_groups']} "
        f"ceiling={baseline['duplicate_group_ceiling']}",
        f"severe_complexity={len(metrics['severe_complexity'])} "
        f"baseline={len(baseline['severe_complexity'])}",
        f"vulture_findings={len(metrics['vulture_findings'])} "
        f"allowlisted={len(baseline['vulture_allowlist'])}",
        f"quality_ratchet={'fail' if errors else 'pass'}",
    ]
    lines.extend(f"error={error}" for error in errors)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args()

    try:
        baseline = _load_baseline()
        metrics = collect_metrics()
    except (AuditError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"quality_audit_error={exc}", file=sys.stderr)
        return 2

    errors = assess(metrics, baseline)
    if args.json:
        print(json.dumps({"metrics": metrics, "errors": errors}, indent=2))
    else:
        print(_format(metrics, baseline, errors))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
