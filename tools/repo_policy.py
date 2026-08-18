"""Repository policy checks that require no third-party tooling."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = (
    "WORKFLOW.md",
    "CONTRIBUTING.md",
    ".github/copilot-instructions.md",
    ".github/agents/quality-auditor.agent.md",
    ".github/prompts/review-current-change.prompt.md",
    ".github/prompts/record-game-preference.prompt.md",
    ".github/prompts/update-manual-tests.prompt.md",
    ".github/workflows/quality.yml",
    ".vscode/settings.json",
    ".vscode/tasks.json",
    "tools/check.ps1",
    "tools/impact.py",
    "tools/quality_audit.py",
    "tools/repo_policy.py",
    "docs/quality/README.md",
    "docs/quality/quality-baseline.json",
    "docs/design/game-design-principles.md",
    "docs/testing/README.md",
    "docs/testing/07-release-checklist.md",
    "docs/architecture/extension-contracts.md",
)
FORBIDDEN_ROOT_PATHS = ("temp",)
FORBIDDEN_TRACKED_PARTS = {
    ".pytest_cache",
    "__pycache__",
    "temp",
}
FORBIDDEN_TRACKED_PATHS = {
    "server/scripts/deploy.py",
}
FORBIDDEN_TRACKED_SUFFIXES = {
    ".key",
    ".log",
    ".orig",
    ".p12",
    ".pem",
    ".pfx",
    ".ppk",
    ".pyc",
    ".pyo",
    ".rej",
    ".tmp",
}


def _git_files(*args: str) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        Path(raw.decode("utf-8"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def _tracked_files() -> list[Path]:
    return _git_files("--cached")


def _repository_files() -> list[Path]:
    return _git_files("--cached", "--others", "--exclude-standard")


def _check_required_files(
    errors: list[str],
    tracked: set[Path],
    require_tracked: bool,
) -> None:
    for relative in REQUIRED_FILES:
        path = Path(relative)
        if not (ROOT / path).is_file():
            errors.append(f"missing required repository file: {relative}")
        elif require_tracked and path not in tracked:
            errors.append(f"required repository file is not tracked: {relative}")


def _check_forbidden_root_paths(errors: list[str]) -> None:
    for relative in FORBIDDEN_ROOT_PATHS:
        if (ROOT / relative).exists():
            errors.append(f"temporary root path must be removed: {relative}")


def _check_tracked_files(errors: list[str], tracked: set[Path]) -> None:
    for relative in tracked:
        lower_parts = tuple(part.lower() for part in relative.parts)
        lower_path = relative.as_posix().lower()
        if FORBIDDEN_TRACKED_PARTS.intersection(lower_parts):
            errors.append(f"runtime or temporary path is tracked: {relative}")
        if any(part == ".env" or part.startswith(".env.") for part in lower_parts):
            errors.append(f"environment file is tracked: {relative}")
        if lower_path in FORBIDDEN_TRACKED_PATHS:
            errors.append(f"deployment credential path is tracked: {relative}")
        if relative.suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES:
            errors.append(f"generated or sensitive file is tracked: {relative}")


def _check_whitespace(errors: list[str]) -> None:
    for relative in _repository_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            errors.append(f"cannot read repository file: {relative}: {exc}")
            continue
        if b"\0" in content:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if line.endswith((b" ", b"\t")):
                errors.append(
                    f"trailing whitespace: {relative}:{line_number}")


def _check_json(errors: list[str]) -> None:
    roots = (ROOT / ".vscode", ROOT / "Client", ROOT / "Server")
    for base in roots:
        for path in base.rglob("*.json"):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"invalid JSON: {path.relative_to(ROOT)}: {exc}")


def _frontmatter(path: Path, errors: list[str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        errors.append(f"missing YAML frontmatter: {path.relative_to(ROOT)}")
        return
    try:
        end = lines.index("---", 1)
    except ValueError:
        errors.append(f"unterminated YAML frontmatter: {path.relative_to(ROOT)}")
        return
    fields = {
        line.split(":", 1)[0].strip()
        for line in lines[1:end]
        if ":" in line and not line.startswith((" ", "\t"))
    }
    if "description" not in fields:
        errors.append(
            f"frontmatter requires description: {path.relative_to(ROOT)}")


def _check_customizations(errors: list[str]) -> None:
    patterns = (
        ".github/agents/*.agent.md",
        ".github/instructions/*.instructions.md",
        ".github/prompts/*.prompt.md",
    )
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            _frontmatter(path, errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-tracked",
        action="store_true",
        help="Require quality-system files to be present in the Git index.",
    )
    args = parser.parse_args()

    errors: list[str] = []
    tracked = set(_tracked_files())
    _check_required_files(errors, tracked, args.require_tracked)
    _check_forbidden_root_paths(errors)
    _check_tracked_files(errors, tracked)
    _check_whitespace(errors)
    _check_json(errors)
    _check_customizations(errors)
    if errors:
        print("Repository policy violations:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Repository policy checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
