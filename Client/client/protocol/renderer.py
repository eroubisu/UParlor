"""游戏渲染注册表"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from rich.console import RenderableType
from rich.table import Table

from ..config import GAME_GLYPHS
from ..window_engine.text import cell_width, uses_emoji_presentation


@dataclass(frozen=True)
class GameStatusContent:
    """Structured game status with an optional divided header."""

    body: RenderableType | None
    header: RenderableType | None = None


def make_status_table() -> Table:
    """Create the shared edge-aligned two-column status layout."""
    table = Table(
        show_header=False,
        show_edge=False,
        box=None,
        expand=True,
        padding=(0, 0),
        pad_edge=False,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")
    table.add_column(justify="right", no_wrap=True, overflow="ellipsis")
    return table


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
    from rich.text import Text
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
