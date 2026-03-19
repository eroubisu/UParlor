"""游戏渲染注册表"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from rich.console import RenderableType


@runtime_checkable
class GameRenderer(Protocol):
    """游戏渲染协议 — 所有游戏渲染器必须实现"""

    game_type: str  # 游戏标识符，与 room_data["game_type"] 一致

    def render_board(self, room_data: dict) -> RenderableType:
        """渲染游戏主画面，返回 Rich 可渲染对象"""
        ...


# ── 全局注册表 ──

RENDERER_REGISTRY: dict[str, GameRenderer] = {}


def register_renderer(renderer: GameRenderer) -> None:
    """注册游戏渲染器"""
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

    result = Text()
    if commands:
        pat = re.compile(
            r'\b(' + '|'.join(re.escape(c) for c in commands) + r')\b')
    else:
        pat = None

    for line in text.split('\n'):
        if line.lstrip().startswith('◆'):
            result.append(line + '\n', style='bold #e0e0e0')
        elif pat:
            last = 0
            for m in pat.finditer(line):
                result.append(line[last:m.start()], style='#808080')
                from ..config import COLOR_CMD
                result.append(m.group(), style=f'bold {COLOR_CMD}')
                last = m.end()
            result.append(line[last:] + '\n', style='#808080')
        else:
            result.append(line + '\n', style='#808080')

    return result
