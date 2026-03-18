"""面板组件 — 所有模块面板的统一导出与注册"""

from .chat import ChatPanel
from .command import CommandPanel
from .status import StatusPanel
from .online import OnlineUsersPanel
from .game_board import GameBoardPanel
from .login import LoginPanel
from .which_key import WhichKeyPanel
from .inventory import InventoryPanel
from .ai_chat import AIChatPanel
from .notification import NotificationPanel

from ..registry import register_module

register_module('login',      '开始',     LoginPanel, scope='internal')
register_module('chat',       '聊天',     ChatPanel, desc='频道消息和私聊')
register_module('cmd',        '记录',     CommandPanel, desc='交互历史记录')
register_module('status',     '状态',     StatusPanel, desc='个人信息总览')
register_module('online',     '用户',     OnlineUsersPanel, desc='在线玩家和好友')
register_module('game_board', '游戏',     GameBoardPanel, scope='game', desc='游戏画面')
register_module('inventory',  '背包',     InventoryPanel, desc='物品管理')
register_module('ai',         '旅伴',     AIChatPanel, desc='AI 伙伴聊天')
register_module('notify',     '通知',     NotificationPanel, desc='系统和好友通知')

__all__ = [
    'ChatPanel', 'CommandPanel',
    'StatusPanel', 'OnlineUsersPanel', 'GameBoardPanel', 'LoginPanel',
    'WhichKeyPanel', 'InventoryPanel', 'AIChatPanel', 'NotificationPanel',
]
