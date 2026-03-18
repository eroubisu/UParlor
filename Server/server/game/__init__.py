"""游戏框架子包 — 引擎协议、结果分发、房间处理"""

from .protocol import GameEngine
from .result_dispatcher import dispatch_game_result, register_action

__all__ = ['GameEngine', 'dispatch_game_result', 'register_action']
