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


def test_layout_never_assumes_double_width_icons():
    """字形宽度契约：图标占一列，排版一律量 `cell_width`，不许再引入宽字形名单。

    2026-10-15 的"没对齐"就是给图标让两列造成的（CJK 才占两列）。这个扫描
    防止宽字形名单或按两列占位的写法再回来。
    """
    root = Path(__file__).parent.parent
    banned = ("WIDE_GLYPHS", "WIDE_GLYPH_COLS", "glyph_width", "visual_width",
              "text_width(")
    offenders = []
    for source_root in (root / "Client" / "client", root / "Server" / "server"):
        for path in source_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            offenders += [f"{path.name}:{name}" for name in banned
                          if name in text]
    assert offenders == []


def test_registered_game_renderers_use_declared_glyphs():
    import client.games  # noqa: F401

    assert set(RENDERER_REGISTRY) == {"uno", "ludo", "baseball"}
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


def test_status_rows_fill_the_panel_and_never_squeeze_the_label():
    """两列状态行：值贴右边框、整行铺满面板；真放不下时先砍值，标签永远是完整的。

    回归 rich `Table` 那版：内容一超宽它就去压第一列（标签变成 `…`），
    而且数值到不了右边缘（用户 2026-10-15 报的"右上角面板右边数据没有右对齐"）。
    """
    from client.protocol.renderer import make_status_table
    from rich.console import Console

    table = make_status_table()
    table.add_row('局数', '\uf0d8 1')
    table.add_row('我方投手', '控球 5  球速 6  变化 7')
    table.add_row('阶段', '投球  四缝线速球 Four-Seam Fastball')   # 比面板还长
    console = Console(width=38, record=True, color_system=None)
    console.print(table)
    rows = [line for line in console.export_text().split('\n') if line.strip()]
    assert {cell_width(line.rstrip()) for line in rows} == {38 - 2}
    assert all(not line.startswith('\u2026') for line in rows)
    assert rows[0].lstrip().startswith('局数') and rows[0].endswith('1')
    assert rows[1].endswith('变化 7')
    assert rows[-1].lstrip().startswith('阶段 投球')
    assert rows[-1].endswith('\u2026')
    # 左右各缩进一个 ICON_INDENT：两边缝一样宽，值都不贴边框
    assert all(row.startswith('  ') for row in rows), rows
    assert {cell_width(row.rstrip()) for row in rows} == {38 - 2}


def test_the_status_rows_remember_nothing_to_reflow():
    """连续两次渲染同一张表：行宽、右边缘都不许漂（面板不随内容抖动）。"""
    from client.protocol.renderer import make_status_table
    from rich.console import Console

    def render(rows) -> list[str]:
        table = make_status_table()
        for row in rows:
            table.add_row(*row)
        console = Console(width=38, record=True, color_system=None)
        console.print(table)
        return [line for line in console.export_text().split('\n') if line.strip()]

    first = render([('局数', '\uf0d8 1'), ('比分', 'alice 0 - 0 bob')])
    second = render([('局数', '\uf0d8 2'), ('比分', 'bob 10 - 0 alice')])
    assert [cell_width(line.rstrip()) for line in first] == \
        [cell_width(line.rstrip()) for line in second]

def test_ludo_grid_rows_have_stable_cell_width():
    from client.games.ludo.renderer import _render_ascii_board

    board = _render_ascii_board({}, None, None)
    rows = board.plain.splitlines()[:19]
    assert len(rows) == 19
    assert {cell_width(row) for row in rows} == {42}


def test_cjk_compositor_patch_never_fails_silently(caplog):
    from client import _cjk_patch

    with caplog.at_level("WARNING"):
        applied = _cjk_patch.apply()

    assert applied is True or "CJK patch skipped" in caplog.text


def test_wrap_markup_matches_wrap_cells_for_text_without_markup():
    from client.window_engine.text import wrap_cells, wrap_markup

    for text in ("一二三四五六七八", "abc def ghi", "中a文b混合 排版", ""):
        for width in (3, 4, 5, 8, 20):
            assert wrap_markup(text, width) == wrap_cells(text, width), (text, width)


def test_wrap_markup_ignores_tags_when_measuring_and_keeps_styles_on_every_row():
    from client.window_engine.text import wrap_markup

    one_row = wrap_markup("[bold #81c784]●[/] 一二三", 8)
    assert one_row == ["[bold #81c784]●[/bold #81c784] 一二三"]

    rows = wrap_markup("[#81c784]一二三四[/]", 4)
    assert len(rows) == 2 and all("[#81c784]" in row for row in rows)
