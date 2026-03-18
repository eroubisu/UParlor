"""
游戏引擎模板 — 实现 GameEngine 协议

必须实现: handle_command, handle_disconnect, handle_back, handle_quit, get_welcome_message
可选覆盖: get_commands, get_status_extras, get_player_room_data
"""

from __future__ import annotations

from typing import Any

from ...game.protocol import BaseGameEngine


class GameEngine(BaseGameEngine):
    """TODO: 游戏引擎 — 替换类名和逻辑"""

    def handle_command(self, lobby: Any, player_name: str, player_data: dict,
                       cmd: str, args: str) -> Any:
        """处理游戏指令。返回 str/dict 消息或 None（未匹配）。

        Rich Result 协议: 返回 dict 时可包含:
          {'type': 'game_msg', 'text': '...'}           — 发给当前玩家
          {'type': 'room_update', 'room_data': {...}}    — 推送房间状态
          {'type': 'broadcast', 'text': '...'}           — 广播给房间全员
        """
        if cmd == 'example':
            return f'收到指令: {args}'
        return None

    def handle_disconnect(self, lobby: Any, player_name: str) -> list[dict]:
        """玩家断线时清理资源，返回需要发送的通知列表"""
        return []

    def handle_back(self, lobby: Any, player_name: str, player_data: dict) -> Any:
        """处理 /back"""
        return None

    def handle_quit(self, lobby: Any, player_name: str, player_data: dict) -> Any:
        """处理 /home — 离开游戏回大厅"""
        return None

    def get_welcome_message(self, player_data: dict) -> dict:
        """进入游戏时的欢迎消息"""
        return {'type': 'game_msg', 'text': '欢迎来到 TODO 游戏名称！'}
