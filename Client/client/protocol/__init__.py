"""游戏协议子包 — 处理器、渲染器、指令注册表"""

from .handler import GameHandlerContext, GameClientHandler, register_handler, get_handler
from .renderer import GameRenderer, register_renderer, get_renderer
from .commands import CommandInfo, filter_commands, get_game_tabs, set_commands

__all__ = [
    'GameHandlerContext', 'GameClientHandler', 'register_handler', 'get_handler',
    'GameRenderer', 'register_renderer', 'get_renderer',
    'CommandInfo', 'filter_commands', 'get_game_tabs', 'set_commands',
]
