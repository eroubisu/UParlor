"""客户端渲染器模板 — 将 room_data 渲染为 Rich 可渲染对象"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ..protocol.renderer import register_renderer


class GameRenderer:
    """TODO: 游戏渲染器 — 替换类名"""

    game_type = 'TODO_game_id'  # 必须与服务端 GAME_INFO['id'] 一致

    def render_board(self, room_data: dict) -> RenderableType:
        """渲染游戏画面。

        room_data 来自服务端 engine.get_player_room_data()，
        由 GameBoardPanel 调用此方法后显示在游戏面板中。

        返回任何 Rich 可渲染对象: Text, Table, Panel, Group 等。
        """
        return Text("TODO: 实现游戏渲染")


# 模块导入时自动注册
register_renderer(GameRenderer())
