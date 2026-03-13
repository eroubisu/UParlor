"""面板组件 — 所有模块面板的统一导出与注册"""

from .chat import ChatPanel
from .command import CommandPanel, CommandHintBar
from .status import StatusPanel
from .online import OnlineUsersPanel
from .game_board import GameBoardPanel
from .login import LoginPanel
from .which_key import WhichKeyPanel

from ...registry import register_module

register_module('login',      '登录',     LoginPanel)
register_module('chat',       '聊天',     ChatPanel)
register_module('cmd',        '指令',     CommandPanel)
register_module('status',     '状态',     StatusPanel)
register_module('online',     '在线用户', OnlineUsersPanel)
register_module('game_board', '游戏',     GameBoardPanel, scope='game')

__all__ = [
    'ChatPanel', 'CommandPanel', 'CommandHintBar',
    'StatusPanel', 'OnlineUsersPanel', 'GameBoardPanel', 'LoginPanel',
    'WhichKeyPanel',
]
