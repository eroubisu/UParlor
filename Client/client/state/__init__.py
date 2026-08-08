"""
模块状态层 — 独立于 Widget 的持久化数据存储

核心原则：
  Widget 是无状态的纯视图，随时可销毁重建。
  所有持久数据存储在本模块的 State 对象中。
  Widget 创建后通过 restore() 从 State 恢复全部内容。

数据流：
  msg_dispatch → State.方法() → State._notify() → Widget 渲染回调
  State 是唯一数据来源（SSOT），Widget 只负责展示。
"""

from __future__ import annotations

from .base import BaseState
from .chat import ChatState
from .cmd import CmdState
from .status import StatusState
from .online import OnlineState
from .game_board import GameBoardState
from .game_interaction import GameInteractionState
from .notification import NotificationState
from .auth import AuthState


class ModuleStateManager:
    """所有模块状态的统一管理器，生命周期跟随 GameScreen"""

    def __init__(self):
        self.chat = ChatState()
        self.cmd = CmdState()
        self.status = StatusState()
        self.online = OnlineState()
        self.game_board = GameBoardState()
        self.game_interaction = GameInteractionState()
        self.notify = NotificationState()
        self.auth = AuthState()
        self.location = "lobby"

    def unbind_all(self) -> None:
        """解绑当前 State 生命周期内的全部界面监听器。"""
        for state_part in (
                self.chat, self.cmd, self.status, self.online,
                self.game_board, self.game_interaction, self.notify, self.auth):
            state_part.clear_listeners()


__all__ = [
    'BaseState',
    'ChatState', 'CmdState', 'StatusState',
    'OnlineState', 'GameBoardState', 'GameInteractionState', 'NotificationState',
    'AuthState',
    'ModuleStateManager',
]
