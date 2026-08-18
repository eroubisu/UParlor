"""Resolve a concise validation scope from target or changed repository paths."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Impact:
    paths: tuple[str, ...]
    scopes: set[str] = field(default_factory=set)
    tests: set[str] = field(default_factory=set)
    manuals: set[str] = field(default_factory=set)
    instructions: set[str] = field(default_factory=set)
    contracts: set[str] = field(default_factory=set)
    full_gate_reasons: set[str] = field(default_factory=set)

    @property
    def full_gate(self) -> bool:
        return bool(self.full_gate_reasons)

    def as_dict(self) -> dict[str, object]:
        return {
            "path_count": len(self.paths),
            "scopes": sorted(self.scopes),
            "focused_tests": sorted(self.tests),
            "manual_handbooks": sorted(self.manuals),
            "instructions": sorted(self.instructions),
            "contract_sections": sorted(self.contracts),
            "full_gate": self.full_gate,
            "full_gate_reasons": sorted(self.full_gate_reasons),
        }


def _normalize(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(ROOT)
        except ValueError:
            pass
    return candidate.as_posix().lstrip("./")


def _changed_paths() -> list[str]:
    commands = (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    paths: set[str] = set()
    for command in commands:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        paths.update(line for line in result.stdout.splitlines() if line)
    return sorted(paths)


def _has(path: str, *parts: str) -> bool:
    return any(part in path for part in parts)


def _add_scope(path: str, impact: Impact) -> None:
    for prefix, scope in (
        ("client/", "client"),
        ("server/", "server"),
        ("tests/", "tests"),
    ):
        if path.startswith(prefix):
            impact.scopes.add(scope)
    if path.startswith((".github/", "tools/")) or path in {
        "workflow.md", "contributing.md", "pytest.ini",
    }:
        impact.scopes.add("governance")


def _add_guidance(path: str, impact: Impact) -> None:
    if path.endswith(".py") and path.startswith(
        ("client/", "server/", "tests/", "tools/")
    ):
        impact.instructions.add(".github/instructions/python.instructions.md")
    if "/games/" in path and path.endswith((".py", ".json", ".txt")):
        impact.instructions.add(
            ".github/instructions/game-modules.instructions.md")
    if _has(path, "/views/", "/widgets/", "/window_engine/", "screen_nav.py"):
        impact.contracts.add("Window")
    if _has(path, "/state/", "/net/dispatch/"):
        impact.contracts.add("Client State")
    if _has(path, "msg_types.py", "/net/messages.py", "/net/dispatch/"):
        impact.contracts.add("Message")
    if "/games/" in path or path.endswith("/net/dispatch/game.py"):
        impact.contracts.add("Game")


def _add_validation(path: str, impact: Impact) -> None:
    if _has(path, "/remote/", "views/system/remote.py"):
        impact.tests.add("tests/test_remote.py")
        impact.manuals.add("docs/testing/02-terminal-and-windows.md")
    if _has(path, "views/login.py", "player/auth.py", "msg_types.py"):
        impact.tests.update({
            "tests/test_session_offline.py",
            "tests/test_server_concurrency.py",
        })
        impact.manuals.add("docs/testing/01-smoke.md")
    if path.endswith("/player/schema.py"):
        impact.tests.add("tests/test_user_schema.py")
    if "/window_engine/" in path or _has(
        path, "widgets/panel.py", "widgets/window.py"
    ):
        impact.tests.update({
            "tests/test_window_engine.py",
            "tests/test_terminal_text.py",
        })
        impact.manuals.add("docs/testing/02-terminal-and-windows.md")
    if "/companion/" in path:
        impact.tests.update({
            "tests/test_companion.py",
            "tests/test_companion_window.py",
        })
        impact.manuals.add("docs/testing/06-companion.md")
    for game_id, handbook in (
        ("uno", "docs/testing/04-uno.md"),
        ("ludo", "docs/testing/05-ludo.md"),
    ):
        if f"/games/{game_id}/" in path:
            impact.tests.add("tests/test_game_remediation.py")
            impact.manuals.add(handbook)
    if path.endswith("/net/dispatch/game.py"):
        impact.tests.add("tests/test_game_remediation.py")
        impact.manuals.update({
            "docs/testing/04-uno.md",
            "docs/testing/05-ludo.md",
        })
    if _has(
        path,
        "/views/chat/",
        "/views/social/",
        "/state/chat.py",
        "/state/online.py",
        "/handlers/chat.py",
        "chat_style.py",
    ):
        impact.tests.update({
            "tests/test_chat_semantics.py",
            "tests/test_online_window.py",
        })
        impact.manuals.add("docs/testing/03-social.md")
    if _has(path, "/waiting", "waiting_room"):
        impact.tests.add("tests/test_waiting_room_controls.py")


def _add_gate_reason(path: str, impact: Impact) -> None:
    if path.startswith((".github/", "tools/")) or path.endswith(
        "pyproject.toml"
    ) or path in {"workflow.md", "contributing.md", "pytest.ini"}:
        impact.full_gate_reasons.add("governance or dependency change")
    if _has(
        path,
        "/window_engine/",
        "widgets/panel.py",
        "widgets/window.py",
        "docs/architecture/extension-contracts.md",
    ):
        impact.full_gate_reasons.add("shared engine or contract change")


def analyze_paths(paths: list[str]) -> Impact:
    normalized = tuple(sorted({_normalize(path) for path in paths if path}))
    impact = Impact(normalized)

    for path in normalized:
        lower = path.lower()
        _add_scope(lower, impact)
        _add_guidance(lower, impact)
        _add_validation(lower, impact)
        _add_gate_reason(lower, impact)

    if {"client", "server"}.issubset(impact.scopes):
        impact.full_gate_reasons.add("cross client/server change")
    if not impact.tests and impact.scopes.intersection({"client", "server"}):
        impact.tests.add("tests/test_sanity.py")
    return impact


def _format(impact: Impact) -> str:
    data = impact.as_dict()
    lines = [
        f"paths={data['path_count']}",
        f"scopes={','.join(data['scopes']) or 'none'}",
        f"focused_tests={','.join(data['focused_tests']) or 'none'}",
        f"manual_handbooks={','.join(data['manual_handbooks']) or 'none'}",
        f"instructions={','.join(data['instructions']) or 'none'}",
        f"contract_sections={','.join(data['contract_sections']) or 'none'}",
        f"full_gate={'yes' if data['full_gate'] else 'no'}",
    ]
    if data["full_gate_reasons"]:
        lines.append(f"full_gate_reasons={'; '.join(data['full_gate_reasons'])}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report the smallest known UParlor validation scope.")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = args.paths or _changed_paths()
    impact = analyze_paths(paths)
    if args.json:
        print(json.dumps(impact.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(_format(impact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())