"""面板组件 — 所有模块面板的统一导出与注册"""

from .chat import ChatPanel
from .command import CommandPanel, CommandHintBar
from .status import StatusPanel
from .online import OnlineUsersPanel
from .game_board import GameBoardPanel
from .login import LoginPanel
from .which_key import WhichKeyPanel
from .inventory import InventoryPanel
from .ai_chat import AIChatPanel
from .notification import NotificationPanel

from ..registry import register_module

register_module('login',      '登录',     LoginPanel, scope='internal')
register_module('chat',       '聊天',     ChatPanel)
register_module('cmd',        '指令',     CommandPanel)
register_module('status',     '状态',     StatusPanel)
register_module('online',     '用户', OnlineUsersPanel)
register_module('game_board', '游戏',     GameBoardPanel, scope='game')
register_module('inventory',  '背包',   InventoryPanel)
register_module('ai',         '旅伴',     AIChatPanel)
register_module('notify',     '通知',     NotificationPanel)

__all__ = [
    'ChatPanel', 'CommandPanel', 'CommandHintBar',
    'StatusPanel', 'OnlineUsersPanel', 'GameBoardPanel', 'LoginPanel',
    'WhichKeyPanel', 'InventoryPanel', 'AIChatPanel', 'NotificationPanel',
]
