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


class BaseState:
    """State 基类 — 统一的多监听器通知机制"""

    def __init__(self):
        self._listeners: list = []

    def add_listener(self, cb):
        if cb not in self._listeners:
            self._listeners.append(cb)

    def remove_listener(self, cb):
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    def _notify(self, event: str, *args):
        for cb in self._listeners:
            cb(event, *args)


class ChatState(BaseState):
    """聊天面板的全部状态 — 支持频道 + 私聊标签页"""

    def __init__(self):
        super().__init__()
        self.entries: list[tuple] = []
        self.current_channel: int = 1
        self.online_count: int = 0
        # 私聊状态
        self.dm_entries: dict[str, list[tuple]] = {}  # {peer_name: [(from, text, time), ...]}
        self.dm_tabs: list[str] = []  # 已打开的私聊标签页（按打开顺序）
        self.active_tab: str = "global"  # "global" | peer_name
        self.dm_unread: dict[str, int] = {}  # {peer: unread_count}
        self.panel_focused: bool = False  # 聊天面板是否当前聚焦
        self._closed_tabs: set[str] = set()  # 用户手动关闭过的标签（防止重登时自动恢复）

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
            if peer not in self._closed_tabs and peer not in self.dm_tabs:
                self.dm_tabs.append(peer)
            self.dm_entries[peer] = [
                (m.get('from', ''), m.get('text', ''), m.get('time', ''))
                for m in msgs
            ]
        self._notify('dm_history_loaded')

    def open_private_tab(self, peer_name: str):
        """打开（或切换到）一个私聊标签页"""
        self._closed_tabs.discard(peer_name)
        if peer_name not in self.dm_tabs:
            self.dm_tabs.append(peer_name)
            self.dm_entries.setdefault(peer_name, [])
        self.active_tab = peer_name
        self.dm_unread.pop(peer_name, None)
        self._notify('open_private_tab', peer_name)

    def close_private_tab(self, peer_name: str):
        """关闭一个私聊标签页"""
        if peer_name in self.dm_tabs:
            self.dm_tabs.remove(peer_name)
        self._closed_tabs.add(peer_name)
        if self.active_tab == peer_name:
            self.active_tab = "global"
        self._notify('close_private_tab', peer_name)

    def clear_private_tab(self, peer_name: str):
        """清空一个私聊标签页的消息"""
        if peer_name in self.dm_entries:
            self.dm_entries[peer_name] = []
        self._notify('switch_tab', peer_name)

    def switch_tab(self, tab_name: str):
        """切换标签页: "global" 或 peer_name"""
        self.active_tab = tab_name
        self.dm_unread.pop(tab_name, None)
        self._notify('switch_tab', tab_name)

    def add_private_message(self, from_name: str, to_name: str, text: str, time_str: str = ""):
        """收到私聊消息 — 自动打开标签页"""
        # 确定对方名字（可能是我发的也可能是对方发的）
        peer = to_name if from_name == self._my_name else from_name
        if peer not in self.dm_tabs:
            self.dm_tabs.append(peer)
        self.dm_entries.setdefault(peer, []).append((from_name, text, time_str))
        # 不在当前标签 → 标记未读（自己发送的不标记）
        if from_name != self._my_name:
            if not (self.panel_focused and self.active_tab == peer):
                self.dm_unread[peer] = self.dm_unread.get(peer, 0) + 1
        self._notify('add_private_message', peer, from_name, text, time_str)

    @property
    def _my_name(self) -> str:
        """从 ModuleStateManager 获取当前玩家名字"""
        return getattr(self, '_player_name', '')

    def set_player_name(self, name: str):
        self._player_name = name


class CmdState(BaseState):
    """指令面板的全部状态"""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self.max_lines: int = MAX_LINES_CMD

    def add_line(self, text: str, **kw):
        from datetime import datetime
        ts = datetime.now().strftime('%H:%M')
        stamped = f'[dim]{ts}[/dim] {text}'
        self.lines.append(stamped)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
        self._notify('add_line', stamped, kw)

    def clear(self):
        self.lines.clear()
        self._notify('clear')


class StatusState(BaseState):
    """状态面板的全部状态（名片 + 状态 + 设置）"""

    def __init__(self):
        super().__init__()
        self.player_data: dict = {}
        self.page: str = 'status'     # status | card | settings
        self.settings_cursor: int = 0

    def update_player_info(self, player_data: dict):
        self.player_data = player_data
        self._notify('update_player_info', player_data)

    def clear(self):
        self.player_data = {}
        self._notify('clear')


class OnlineState(BaseState):
    """在线用户面板的全部状态"""

    def __init__(self):
        super().__init__()
        self.users: list = []
        self.friends: list[str] = []
        self.all_users: list[str] = []
        self.tab: str = "friends"
        self.cursor: int = 0
        self.search_query: str = ""
        self.viewed_card: dict | None = None

    def update_users(self, users: list):
        self.users = users
        self._notify('update_users', users)

    def update_friends(self, friends: list[str]):
        self.friends = friends
        self._notify('update_friends', friends)

    def update_all_users(self, users: list[str]):
        self.all_users = users
        self._notify('update_all_users', users)

    def set_viewed_card(self, card_data: dict):
        self.viewed_card = card_data
        self._notify('viewed_card', card_data)


class GameBoardState(BaseState):
    """游戏面板的全部状态"""

    _MAX_EVENTS = 10

    def __init__(self):
        super().__init__()
        self.room_data: dict = {}
        self.recent_events: list[str] = []
        self.following: str = ''  # 正在跟随的目标名（空=未跟随）

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
        self.following = ''
        self._notify('clear')


class InventoryState(BaseState):
    """物品栏面板的全部状态"""

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []   # [{id, name, count, desc, use_methods}]
        self.gold: int = 0
        self.cursor: int = 0
        self.filter_tab: str = "all"
        self.quality_filter: str = "all"
        self.sort_cursor: int = 0
        self.tab_row: int = 0

    def update_inventory(self, player_data: dict):
        """从 player_data 提取物品并更新

        服务端推送列表格式: inventory = [{id, quality, count, name, desc, category, use_methods}, ...]
        兼容旧字典格式: inventory = {item_id: {count, name, ...}}
        """
        self.gold = player_data.get('gold', 0)
        inventory = player_data.get('inventory', {})
        items = []
        if isinstance(inventory, list):
            for entry in inventory:
                if entry.get('count', 0) > 0:
                    items.append({
                        'id': entry.get('id', ''),
                        'name': entry.get('name', entry.get('id', '')),
                        'desc': entry.get('desc', ''),
                        'category': entry.get('category', ''),
                        'quality': entry.get('quality', 0),
                        'count': entry['count'],
                        'use_methods': entry.get('use_methods', []),
                        'pattern': entry.get('pattern'),
                        'equipped': entry.get('equipped', ''),
                    })
        elif isinstance(inventory, dict):
            for item_id, info in inventory.items():
                if isinstance(info, dict):
                    if info.get('count', 0) > 0:
                        items.append({
                            'id': item_id,
                            'name': info.get('name', item_id),
                            'desc': info.get('desc', ''),
                            'category': info.get('category', ''),
                            'quality': info.get('quality', 0),
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
                            'quality': 0,
                            'count': info,
                            'use_methods': [],
                        })
        self.items = items
        self._notify('update_inventory')


class AIChatState(BaseState):
    """AI 聊天面板状态 — 多视图 + 菜单 + 状态显示"""

    def __init__(self):
        super().__init__()
        self.messages: list[dict] = []   # [{role, content}]
        self.view: str = "select"        # select | create | chat | setup
        self.current_char_id: str = ""
        self.menu_tab: str = "chat"      # chat | gift | action | settings

        # CREATE/SETUP 视图瞬态（rebuild 时保留）
        self.create_step: str = ""       # desc | review
        self.create_desc: str = ""
        self.create_char = None          # Character | None
        self.create_status: str = ""
        self.setup_step: str = "provider" # provider | base_url | api_key | model | model_input
        self.setup_key: str = ""
        self.setup_provider: str = ""
        self.setup_base_url: str = ""
        self.wants_insert: bool = False
        self.streaming_interrupted: bool = False

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


class NotificationState(BaseState):
    """通知面板的全部状态 — 系统通知 + 好友申请"""

    _MAX_NOTIFICATIONS = 200

    def __init__(self):
        super().__init__()
        self.system_notifications: list[str] = []
        # 好友申请: [{name, status}]  status = 'pending' | 'accepted' | 'rejected'
        self.friend_requests: list[dict] = []
        self.tab: str = "system"
        self.cursor: int = 0

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
        if len(self.system_notifications) > self._MAX_NOTIFICATIONS:
            self.system_notifications = self.system_notifications[-self._MAX_NOTIFICATIONS:]
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
