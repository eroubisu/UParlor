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

from .config import (
    MAX_LINES_CMD,
)

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
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def add_message(self, name: str, text: str, channel: int = 1, time_str: str = ""):
        self.entries.append((MSG, name, text, channel, time_str))
        self._notify('add_message', name, text, channel, time_str)

    def add_system_message(self, text: str):
        self.entries.append((SYS, text))
        self._notify('add_system_message', text)

    def set_history(self, messages: list, channel: int):
        self.entries = [e for e in self.entries
                        if not (e[0] == MSG and e[3] == channel)]
        self.entries.append((HISTORY, messages, channel))
        self._notify('set_history', messages, channel)

    def switch_channel(self, channel_id: int):
        self.current_channel = channel_id
        self._notify('switch_channel', channel_id)

    def update_online_count(self, users: list):
        self.online_count = len(users) if users else 0
        self._notify('update_online_count', users)


class CmdState:
    """指令面板的全部状态"""

    def __init__(self):
        self.lines: list[str] = []
        self.max_lines: int = MAX_LINES_CMD
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def add_line(self, text: str, **kw):
        self.lines.append(text)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
        self._notify('add_line', text, kw)

    def clear(self):
        self.lines.clear()
        self._notify('clear')


class StatusState:
    """状态面板的全部状态（固定显示玩家信息）"""

    def __init__(self):
        self.player_data: dict = {}
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def update_player_info(self, player_data: dict):
        self.player_data = player_data
        self._notify('update_player_info', player_data)

    def clear(self):
        self.player_data = {}
        self._notify('clear')


class OnlineState:
    """在线用户面板的全部状态"""

    def __init__(self):
        self.users: list = []
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def update_users(self, users: list):
        self.users = users
        self._notify('update_users', users)


class GameBoardState:
    """游戏面板的全部状态"""

    def __init__(self):
        self.room_data: dict = {}
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def update_room(self, room_data: dict):
        self.room_data = room_data
        self._notify('update_room', room_data)

    def clear(self):
        self.room_data = {}
        self._notify('clear')


class InventoryState:
    """物品栏面板的全部状态"""

    def __init__(self):
        self.items: list[dict] = []   # [{id, name, count, desc, use_methods}]
        self.gold: int = 0
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def update_inventory(self, player_data: dict):
        """从 player_data 提取物品并更新

        服务端推送富格式: inventory = {item_id: {count, name, desc, use_methods}}
        """
        self.gold = player_data.get('gold', 0)
        inventory = player_data.get('inventory', {})
        items = []
        for item_id, info in inventory.items():
            if isinstance(info, dict):
                if info.get('count', 0) > 0:
                    items.append({
                        'id': item_id,
                        'name': info.get('name', item_id),
                        'desc': info.get('desc', ''),
                        'count': info['count'],
                        'use_methods': info.get('use_methods', []),
                    })
            else:
                # 兼容旧格式 {item_id: count}
                if isinstance(info, int) and info > 0:
                    items.append({
                        'id': item_id,
                        'name': item_id,
                        'desc': '',
                        'count': info,
                        'use_methods': [],
                    })
        self.items = items
        self._notify('update_inventory')


class AIChatState:
    """AI 聊天面板状态 — 多视图 + 菜单 + 状态显示"""

    def __init__(self):
        self.messages: list[dict] = []   # [{role, content}]
        self.view: str = "select"        # select | create | chat
        self.current_char_id: str = ""
        self.menu_tab: str = "chat"      # chat | gift | action | settings
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def add_user_message(self, text: str):
        self.messages.append({"role": "user", "content": text})
        self._notify("add_user", text)

    def add_ai_message(self, text: str):
        self.messages.append({"role": "assistant", "content": text})
        self._notify("add_ai", text)

    def switch_view(self, view: str):
        self.view = view
        self._notify("view_change", view)

    def switch_tab(self, tab: str):
        self.menu_tab = tab
        self._notify("tab_change", tab)


class ModuleStateManager:
    """所有模块状态的统一管理器，生命周期跟随 GameScreen"""

    def __init__(self):
        self.chat = ChatState()
        self.cmd = CmdState()
        self.status = StatusState()
        self.online = OnlineState()
        self.game_board = GameBoardState()
        self.inventory = InventoryState()
        self.ai_chat = AIChatState()
        self.location = "lobby"
