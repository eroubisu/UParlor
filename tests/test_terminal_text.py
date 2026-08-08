"""Unicode terminal layout and built-in glyph contract tests."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.config import GAME_GLYPHS, NERD_FONT_BASELINE, NERD_GLYPHS
from client.screen import GameScreen
from client.protocol.renderer import RENDERER_REGISTRY, register_renderer
from client.window_engine.text import (
    cell_width,
    fit_cells,
    grapheme_clusters,
    uses_emoji_presentation,
    wrap_cells,
)


@pytest.mark.parametrize(
    ("text", "width"),
    [
        ("ASCII", 5),
        ("中文", 4),
        ("e\u0301", 1),
        ("😀", 2),
        ("👍🏽", 2),
        ("👨‍👩‍👧‍👦", 2),
        ("🇨🇳", 2),
        ("1️⃣", 2),
    ],
)
def test_cell_width_matches_terminal_rendering(text, width):
    assert cell_width(text) == width


@pytest.mark.parametrize(
    "cluster",
    ["e\u0301", "👍🏽", "👨‍👩‍👧‍👦", "🇨🇳", "1️⃣"],
)
def test_extended_graphemes_remain_atomic(cluster):
    assert grapheme_clusters(cluster) == [cluster]


def test_wrap_cells_preserves_chinese_and_emoji_clusters():
    text = "中文🇨🇳e\u0301"
    assert wrap_cells(text, 4) == ["中文", "🇨🇳e\u0301"]


def test_fit_cells_uses_rendered_width_and_safe_cropping():
    assert fit_cells("中A", 5, "center") == " 中A "
    assert fit_cells("中AB", 3, crop=True) == "中A"
    assert fit_cells("🇨🇳A", 2, crop=True) == "🇨🇳"


def test_global_terminal_size_requires_88_by_32():
    warning = Mock()
    screen = SimpleNamespace(
        _terminal_too_small=False,
        query_one=lambda *_args: warning,
    )

    GameScreen._update_terminal_size(screen, 88, 32)
    assert screen._terminal_too_small is False
    assert warning.display is False

    GameScreen._update_terminal_size(screen, 87, 32)
    assert screen._terminal_too_small is True
    assert warning.display is True
    assert "至少 88 × 32" in warning.update.call_args.args[0]

    GameScreen._update_terminal_size(screen, 88, 31)
    assert screen._terminal_too_small is True
    assert "当前 88 × 31" in warning.update.call_args.args[0]


def test_nerd_font_registry_is_single_cell_private_use():
    assert NERD_FONT_BASELINE.startswith("3")
    for glyph in NERD_GLYPHS:
        assert len(glyph) == 1
        assert 0xE000 <= ord(glyph) <= 0xF8FF
        assert cell_width(glyph) == 1
        assert not uses_emoji_presentation(glyph)


def test_registered_game_renderers_use_declared_glyphs():
    import client.games  # noqa: F401

    assert set(RENDERER_REGISTRY) == {"uno", "ludo"}
    assert all(renderer.glyphs for renderer in RENDERER_REGISTRY.values())
    assert all(
        renderer.icon in renderer.glyphs
        for renderer in RENDERER_REGISTRY.values()
    )


def test_renderer_registration_rejects_colored_emoji():
    class BadRenderer:
        game_type = "bad"
        icon = "🥇"
        glyphs = frozenset({"🥇"})
        def status_height(self, room_data):
            return 1
        controls_height = 1

        def render_board(self, room_data):
            return {"info": None, "board": None, "controls": None}

    with pytest.raises(ValueError, match="emoji presentation"):
        register_renderer(BadRenderer())


def test_renderer_registration_requires_game_specific_controls_height():
    class MissingHeightRenderer:
        game_type = "missing-height"
        icon = next(iter(GAME_GLYPHS))
        glyphs = frozenset({icon})
        def status_height(self, room_data):
            return 1

        def render_board(self, room_data):
            return {"info": None, "board": None, "controls": None}

    with pytest.raises(ValueError, match="controls_height"):
        register_renderer(MissingHeightRenderer())


def test_emoji_presentation_detection():
    assert not uses_emoji_presentation("中文")
    assert not uses_emoji_presentation("\uf005")
    assert not uses_emoji_presentation("☀")
    assert uses_emoji_presentation("☀️")
    assert uses_emoji_presentation("🥇")
    assert uses_emoji_presentation("👨‍👩‍👧‍👦")


def test_production_sources_do_not_embed_colored_emoji():
    root = Path(__file__).parent.parent
    source_roots = (
        root / "Client" / "client",
        root / "Server" / "server",
    )
    offenders = []
    for source_root in source_roots:
        for path in source_root.rglob("*"):
            if path.suffix not in {".py", ".json", ".txt"}:
                continue
            if uses_emoji_presentation(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_ludo_grid_rows_have_stable_cell_width():
    from client.games.ludo.renderer import _render_ascii_board

    board = _render_ascii_board({}, None, None)
    rows = board.plain.splitlines()[:19]
    assert len(rows) == 19
    assert {cell_width(row) for row in rows} == {42}
