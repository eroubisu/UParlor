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
DM = 'dm'            # (DM, from_name, to_name, text, time_str) — 私聊消息


class ChatState:
    """聊天面板的全部状态 — 支持频道 + 私聊标签页"""

    def __init__(self):
        self.entries: list[tuple] = []
        self.current_channel: int = 1
        self.online_count: int = 0
        # 私聊状态
        self.dm_entries: dict[str, list[tuple]] = {}  # {peer_name: [(from, text, time), ...]}
        self.dm_tabs: list[str] = []  # 已打开的私聊标签页（按打开顺序）
        self.active_tab: str = "global"  # "global" | peer_name
        self.dm_unread: set[str] = set()  # 有未读消息的私聊标签
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

    # ── 私聊 ──

    def set_dm_history(self, conversations: dict):
        """批量填充私聊历史（登录时服务端下发）

        conversations: {peer_name: [{from, text, time}, ...]}
        """
        for peer, msgs in conversations.items():
            if peer not in self.dm_tabs:
                self.dm_tabs.append(peer)
            self.dm_entries[peer] = [
                (m.get('from', ''), m.get('text', ''), m.get('time', ''))
                for m in msgs
            ]
        self._notify('dm_history_loaded')

    def open_private_tab(self, peer_name: str):
        """打开（或切换到）一个私聊标签页"""
        if peer_name not in self.dm_tabs:
            self.dm_tabs.append(peer_name)
            self.dm_entries.setdefault(peer_name, [])
        self.active_tab = peer_name
        self.dm_unread.discard(peer_name)
        self._notify('open_private_tab', peer_name)

    def close_private_tab(self, peer_name: str):
        """关闭一个私聊标签页"""
        if peer_name in self.dm_tabs:
            self.dm_tabs.remove(peer_name)
        if self.active_tab == peer_name:
            self.active_tab = "global"
        self._notify('close_private_tab', peer_name)

    def switch_tab(self, tab_name: str):
        """切换标签页: "global" 或 peer_name"""
        self.active_tab = tab_name
        self.dm_unread.discard(tab_name)
        self._notify('switch_tab', tab_name)

    def add_private_message(self, from_name: str, to_name: str, text: str, time_str: str = ""):
        """收到私聊消息 — 自动打开标签页"""
        # 确定对方名字（可能是我发的也可能是对方发的）
        peer = to_name if from_name == self._my_name else from_name
        if peer not in self.dm_tabs:
            self.dm_tabs.append(peer)
        self.dm_entries.setdefault(peer, []).append((from_name, text, time_str))
        # 不在当前标签 → 标记未读（自己发送的不标记）
        if from_name != self._my_name and self.active_tab != peer:
            self.dm_unread.add(peer)
        self._notify('add_private_message', peer, from_name, text, time_str)

    @property
    def _my_name(self) -> str:
        """从 ModuleStateManager 获取当前玩家名字"""
        return getattr(self, '_player_name', '')

    def set_player_name(self, name: str):
        self._player_name = name


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
        self.friends: list[str] = []
        self.all_users: list[str] = []
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def update_users(self, users: list):
        self.users = users
        self._notify('update_users', users)

    def update_friends(self, friends: list[str]):
        self.friends = friends
        self._notify('update_friends', friends)

    def update_all_users(self, users: list[str]):
        self.all_users = users
        self._notify('update_all_users', users)


class GameBoardState:
    """游戏面板的全部状态"""

    _MAX_EVENTS = 10

    def __init__(self):
        self.room_data: dict = {}
        self.recent_events: list[str] = []
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def update_room(self, room_data: dict):
        self.room_data = room_data
        self._notify('update_room', room_data)

    def push_event(self, description: str):
        self.recent_events.append(description)
        if len(self.recent_events) > self._MAX_EVENTS:
            self.recent_events = self.recent_events[-self._MAX_EVENTS:]

    def clear(self):
        self.room_data = {}
        self.recent_events.clear()
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

        服务端推送富格式: inventory = {item_id: {count, name, desc, category, use_methods}}
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
                        'category': info.get('category', ''),
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
                        'category': '',
                        'count': info,
                        'use_methods': [],
                    })
        self.items = items
        self._notify('update_inventory')


class AIChatState:
    """AI 聊天面板状态 — 多视图 + 菜单 + 状态显示"""

    def __init__(self):
        self.messages: list[dict] = []   # [{role, content}]
        self.view: str = "select"        # select | create | chat | setup
        self.current_char_id: str = ""
        self.menu_tab: str = "chat"      # chat | gift | action | settings
        self._listener = None

        # CREATE/SETUP 视图瞬态（rebuild 时保留）
        self.create_step: str = ""       # desc | review
        self.create_desc: str = ""
        self.create_char = None          # Character | None
        self.create_status: str = ""
        self.setup_step: str = "api_key" # api_key | model
        self.setup_key: str = ""
        self.wants_insert: bool = False

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


class NotificationState:
    """通知面板的全部状态 — 系统通知 + 好友申请"""

    def __init__(self):
        self.system_notifications: list[str] = []
        # 好友申请: [{name, status}]  status = 'pending' | 'accepted' | 'rejected'
        self.friend_requests: list[dict] = []
        self._listener = None

    def set_listener(self, cb):
        self._listener = cb

    def _notify(self, event: str, *args):
        if self._listener:
            self._listener(event, *args)

    def set_friend_requests(self, names: list[str]):
        """设置完整的好友申请列表（服务端推送的待处理列表）"""
        # 保留已处理的记录，更新 pending 列表
        existing = {r['name']: r for r in self.friend_requests}
        new_list = []
        for name in names:
            if name in existing:
                # 已存在的保持原状态
                new_list.append(existing[name])
            else:
                new_list.append({'name': name, 'status': 'pending'})
        # 保留已处理但不在新 pending 列表中的记录
        for r in self.friend_requests:
            if r['status'] != 'pending' and r['name'] not in names:
                new_list.append(r)
        self.friend_requests = new_list
        self._notify('update_friend_requests')

    def add_friend_request(self, from_name: str):
        """新增一条好友申请"""
        for r in self.friend_requests:
            if r['name'] == from_name:
                # 如果已存在，重置为 pending
                r['status'] = 'pending'
                self._notify('update_friend_requests')
                return
        self.friend_requests.append({'name': from_name, 'status': 'pending'})
        self._notify('update_friend_requests')

    def mark_friend_request(self, name: str, status: str):
        """标记好友申请状态: 'accepted' | 'rejected'"""
        for r in self.friend_requests:
            if r['name'] == name:
                r['status'] = status
                break
        self._notify('update_friend_requests')

    def remove_friend_request(self, name: str):
        """删除好友申请记录"""
        self.friend_requests = [r for r in self.friend_requests if r['name'] != name]
        self._notify('update_friend_requests')

    @property
    def unread_count(self) -> int:
        """未读(pending)好友申请数量"""
        return sum(1 for r in self.friend_requests if r['status'] == 'pending')

    def add_system_notification(self, text: str):
        self.system_notifications.append(text)
        self._notify('add_system_notification', text)


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
        self.notify = NotificationState()
        self.location = "lobby"
