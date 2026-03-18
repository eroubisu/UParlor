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
