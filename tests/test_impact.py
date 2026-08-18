"""Deterministic change-scope resolver tests."""

from tools.impact import analyze_paths


def test_remote_view_selects_focused_validation_without_full_gate():
    impact = analyze_paths(["Client/client/views/system/remote.py"])

    assert impact.scopes == {"client"}
    assert impact.tests == {"tests/test_remote.py"}
    assert impact.manuals == {"docs/testing/02-terminal-and-windows.md"}
    assert impact.contracts == {"Window"}
    assert not impact.full_gate


def test_auth_protocol_change_requires_cross_module_gate():
    impact = analyze_paths([
        "Client/client/views/login.py",
        "Server/server/player/auth.py",
    ])

    assert impact.scopes == {"client", "server"}
    assert impact.tests == {
        "tests/test_server_concurrency.py",
        "tests/test_session_offline.py",
    }
    assert impact.manuals == {"docs/testing/01-smoke.md"}
    assert "cross client/server change" in impact.full_gate_reasons


def test_governance_change_requires_full_gate():
    impact = analyze_paths(["tools/impact.py", "WORKFLOW.md"])

    assert impact.scopes == {"governance"}
    assert impact.full_gate
    assert impact.full_gate_reasons == {"governance or dependency change"}


def test_auth_changes_in_chat_server_do_not_select_social_tests():
    impact = analyze_paths(["Server/server/chat_server.py"])

    assert impact.tests == {"tests/test_sanity.py"}
    assert not impact.manuals


def test_game_dispatch_selects_shared_game_validation():
    impact = analyze_paths(["Client/client/net/dispatch/game.py"])

    assert impact.tests == {"tests/test_game_remediation.py"}
    assert impact.manuals == {
        "docs/testing/04-uno.md",
        "docs/testing/05-ludo.md",
    }
    assert impact.contracts == {"Client State", "Game", "Message"}


def test_user_schema_selects_migration_regressions():
    impact = analyze_paths(["Server/server/player/schema.py"])

    assert impact.tests == {"tests/test_user_schema.py"}
    assert not impact.manuals