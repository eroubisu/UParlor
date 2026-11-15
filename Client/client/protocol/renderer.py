"""游戏渲染注册表"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from rich.console import RenderableType
from rich.text import Text

from ..config import GAME_GLYPHS, ICON_INDENT
from ..window_engine.text import cell_width, fit_cells, uses_emoji_presentation

BUTTON_MIN_CELLS = 8


def render_button_boxes(
    text: Text,
    entries: list[tuple[str, str, str]],
    max_width: int = 0,
) -> None:
    """把操作按钮画成 ╭─╮ 框追加到 text。

    entries 为 (标签, 内容样式, 边框样式)；max_width > 0 时按可用宽度折行，
    每行固定三行高（顶框 / 内容 / 底框）。按钮最小内宽 = BUTTON_MIN_CELLS。
    """
    if not entries:
        return
    rows: list[list[tuple[str, str, str]]] = []
    row: list[tuple[str, str, str]] = []
    used = 2
    for entry in entries:
        needed = max(BUTTON_MIN_CELLS, cell_width(entry[0]) + 2) + 3
        if row and max_width > 0 and used + needed > max_width:
            rows.append(row)
            row, used = [], 2
        row.append(entry)
        used += needed
    rows.append(row)

    for index, box_row in enumerate(rows):
        if index:
            text.append('\n')
        top = Text(ICON_INDENT)
        middle = Text(ICON_INDENT)
        bottom = Text(ICON_INDENT)
        for label, content_style, border_style in box_row:
            width = max(BUTTON_MIN_CELLS, cell_width(label) + 2)
            top.append('╭' + '─' * width + '╮', style=border_style)
            top.append(' ')
            middle.append('│', style=border_style)
            middle.append(
                fit_cells(label, width, 'center'), style=content_style)
            middle.append('│', style=border_style)
            middle.append(' ')
            bottom.append('╰' + '─' * width + '╯', style=border_style)
            bottom.append(' ')
        text.append_text(top)
        text.append('\n')
        text.append_text(middle)
        text.append('\n')
        text.append_text(bottom)


@dataclass(frozen=True)
class GameStatusContent:
    """Structured game status with an optional divided header.

    pages 非空时右栏状态面板按标签页显示（页名 + 内容，顺序＝重要度，
    最多 config.GAME_STATUS_MAX_PAGES 页），body 只作为单页内容使用；
    两者都给出时以 pages 为准。
    """

    body: RenderableType | None
    header: RenderableType | None = None
    pages: tuple[tuple[str, RenderableType], ...] = ()


class StatusRows:
    """两列状态行：标签靠左、数值贴右，整块缩进一个 `ICON_INDENT`（左右对称）。

    不用 rich 的 `Table`：内容比面板宽时 rich 会去压**第一列**（标签变成 `…`），
    数值反而保住；而且它没法保证数值贴死右边缘。这里在渲染那一刻拿到真实宽度：
    间距由剩下的列数算出来，数值因此永远共用同一条右边缘；
    真放不下时**先砍数值**（`…`），标签永远保持完整——标签是这张表的骨架。
    """

    def __init__(self) -> None:
        self._rows: list[tuple[str, str]] = []

    def add_row(self, label: object = '', value: object = '') -> None:
        """加一行（和 rich 的 `Table.add_row` 同名同用法，调用方不用改）。"""
        self._rows.append((str(label), str(value)))

    def __rich_console__(self, _console, options):
        # 左右各留一个 ICON_INDENT：整块内容不贴边框，左右缝一样宽（用户 2026-10-16 定），
        # 数值之间仍然共用同一条右边缘（右对齐）。
        inset = min(cell_width(ICON_INDENT), max(0, options.max_width - 2))
        width = max(1, options.max_width - inset * 2)
        for label, value in self._rows:
            head = Text.from_markup(label)
            tail = Text.from_markup(value)
            head_width = cell_width(head.plain)
            gap = width - head_width - cell_width(tail.plain)
            if gap < 0:                      # 太挤：先砍数值（给标签留一格），标签不动
                tail.truncate(max(1, width - head_width - 1),
                              overflow='ellipsis')
                gap = max(0, width - head_width - cell_width(tail.plain))
            row = Text(' ' * inset)
            row.append_text(head)
            row.append(' ' * gap)
            row.append_text(tail)
            row.no_wrap = True
            yield row


def make_status_table() -> StatusRows:
    """Create the shared edge-aligned two-column status layout.

    标签靠左、数值贴右边框（所有游戏共用一套；面板左右两边对齐靠它）。
    """
    return StatusRows()


@runtime_checkable
class GameRenderer(Protocol):
    """游戏渲染协议 — 所有游戏渲染器必须实现

    render_status() 返回右栏游戏状态。
    render_board() 返回 dict，包含两个分区的 Rich 可渲染对象：
    - 'board': 中间可滚动区（主要游戏内容）
    - 'controls': 底部固定区（手牌/操作按钮）
    空分区传 None。

    可选属性（用 getattr 读取）：
    - scroll_hint: int — 建议滚动到的行号（board 区内，-1=不滚动）

    每个游戏必须声明：
    - status_height(room_data): int — 该游戏按当前状态计算的面板高度
    - controls_height: int — 该游戏底部手牌/操作区的固定高度
    """

    game_type: str  # 游戏标识符，与 room_data["game_type"] 一致
    icon: str  # 游戏列表使用的 Nerd Font 单色图标
    glyphs: frozenset[str]  # 游戏使用的单色布局字形
    controls_height: int  # 该游戏独立声明的底部操作区高度

    def status_height(self, room_data: dict) -> int:
        """返回该游戏当前状态面板的高度。"""
        ...

    def render_status(
        self, room_data: dict, interaction: dict | None = None,
    ) -> GameStatusContent:
        """渲染右栏游戏状态。"""
        ...

    def render_board(self, room_data: dict) -> dict[str, RenderableType | None]:
        """渲染游戏主画面，返回分区 dict"""
        ...


# ── 全局注册表 ──

RENDERER_REGISTRY: dict[str, GameRenderer] = {}


def register_renderer(renderer: GameRenderer) -> None:
    """注册游戏渲染器"""
    status_height = getattr(renderer, "status_height", None)
    if not callable(status_height):
        raise ValueError(
            f"{renderer.game_type}: status_height must be callable"
        )
    for attribute in ("controls_height",):
        height = getattr(renderer, attribute, None)
        if (
            not isinstance(height, int)
            or isinstance(height, bool)
            or height <= 0
        ):
            raise ValueError(
                f"{renderer.game_type}: {attribute} must be a positive integer"
            )
    if renderer.icon not in renderer.glyphs:
        raise ValueError(
            f"{renderer.game_type}: renderer icon must be a declared glyph")
    for glyph in renderer.glyphs:
        if uses_emoji_presentation(glyph):
            raise ValueError(
                f"{renderer.game_type}: emoji presentation is not allowed")
        if cell_width(glyph) != 1:
            raise ValueError(
                f"{renderer.game_type}: glyph must occupy one cell: {glyph!r}")
        if glyph not in GAME_GLYPHS:
            raise ValueError(
                f"{renderer.game_type}: unregistered game glyph {glyph!r}")
    RENDERER_REGISTRY[renderer.game_type] = renderer


def get_renderer(game_type: str) -> GameRenderer | None:
    """根据 game_type 获取渲染器"""
    return RENDERER_REGISTRY.get(game_type)


def render_doc(text: str, commands: set[str] | None = None) -> RenderableType:
    """渲染帮助/教程文档 — 游戏面板内文档显示统一框架。

    room_data 中包含 'doc' 字段时，渲染器调用此函数将文档
    渲染为 Rich Text，commands 集合中的词高亮为指令样式。
    """
    import re
    from ..config import COLOR_FG_SECONDARY, COLOR_FG_TERTIARY

    result = Text()
    if commands:
        pat = re.compile(
            r'\b(' + '|'.join(re.escape(c) for c in commands) + r')\b')
    else:
        pat = None

    for line in text.split('\n'):
        if line.lstrip().startswith('◆'):
            from ..config import NF_STAR
            heading = line.lstrip().replace('◆', NF_STAR, 1)
            result.append(heading + '\n', style=f'bold {COLOR_FG_SECONDARY}')
        elif pat:
            last = 0
            for m in pat.finditer(line):
                result.append(line[last:m.start()], style=COLOR_FG_TERTIARY)
                from ..config import COLOR_CMD
                result.append(m.group(), style=f'bold {COLOR_CMD}')
                last = m.end()
            result.append(line[last:] + '\n', style=COLOR_FG_TERTIARY)
        else:
            result.append(line + '\n', style=COLOR_FG_TERTIARY)

    return result
