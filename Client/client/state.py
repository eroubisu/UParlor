"""
模块状态层 — 独立于 Widget 的持久化数据存储

核心原则：
  Widget 是无状态的纯视图，随时可销毁重建。
  所有持久数据存储在本模块的 State 对象中。
  Widget 创建后通过 restore() 从 State 恢复全部内容。
"""

from __future__ import annotations

# 聊天消息条目类型
MSG = 'msg'          # (MSG, name, text, channel, time_str)
SYS = 'sys'          # (SYS, text)
HISTORY = 'history'  # (HISTORY, messages_list, channel) — 替换该频道的全部消息


class ChatState:
    """聊天面板的全部状态"""

    def __init__(self):
        self.entries: list[tuple] = []
        self.current_channel: int = 1
        self.online_count: int = 0

    def add_message(self, name: str, text: str, channel: int = 1, time_str: str = ""):
        self.entries.append((MSG, name, text, channel, time_str))

    def add_system_message(self, text: str):
        self.entries.append((SYS, text))

    def set_history(self, messages: list, channel: int):
        # 移除该频道的旧消息，替换为新历史
        self.entries = [e for e in self.entries
                        if not (e[0] == MSG and e[3] == channel)]
        self.entries.append((HISTORY, messages, channel))

    def switch_channel(self, channel_id: int):
        self.current_channel = channel_id

    def update_online_count(self, users: list):
        self.online_count = len(users) if users else 0


class CmdState:
    """指令面板的全部状态"""

    def __init__(self):
        self.lines: list[str] = []
        self.max_lines: int = 1000

    def add_line(self, text: str):
        self.lines.append(text)
        # 限制行数防止内存膨胀
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def clear(self):
        self.lines.clear()




class StatusState:
    """状态面板的全部状态（固定显示玩家信息）"""

    def __init__(self):
        self.player_data: dict = {}

    def update_player_info(self, player_data: dict):
        self.player_data = player_data

    def clear(self):
        self.player_data = {}


class OnlineState:
    """在线用户面板的全部状态"""

    def __init__(self):
        self.users: list = []


class GameBoardState:
    """游戏面板的全部状态"""

    def __init__(self):
        self.room_data: dict = {}

    def update_room(self, room_data: dict):
        self.room_data = room_data

    def clear(self):
        self.room_data = {}


class ModuleStateManager:
    """所有模块状态的统一管理器，生命周期跟随 GameScreen"""

    def __init__(self):
        self.chat = ChatState()
        self.cmd = CmdState()
        self.status = StatusState()
        self.online = OnlineState()
        self.game_board = GameBoardState()
