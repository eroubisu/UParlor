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
    MAX_LINES_CHAT,
)


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
    """聊天状态 — 世界频道 + 私聊 + 房间"""

    def __init__(self):
        super().__init__()
        self.world_messages: list[tuple[str, str, str]] = []  # [(name, text, time)]
        self.room_messages: list[tuple[str, str, str]] = []   # [(name, text, time)]
        self.dm_entries: dict[str, list[tuple]] = {}  # {peer_name: [(from, text, time), ...]}
        self.dm_tabs: list[str] = []
        self.active_tab: str = "world"
        self.dm_unread: dict[str, int] = {}
        self.dm_muted: set[str] = set()    # 已关闭通知的 peer
        self.viewing_dm: str = ''  # 当前正在查看的私聊对象（为空表示未查看）
        self._player_name: str = ''

    def set_player_name(self, name: str):
        self._player_name = name

    # ── 世界频道 ──

    def add_world_message(self, name: str, text: str, time: str):
        self.world_messages.append((name, text, time))
        if len(self.world_messages) > MAX_LINES_CHAT:
            self.world_messages = self.world_messages[-MAX_LINES_CHAT:]
        self._notify('add_world_message', name, text, time)

    def set_world_history(self, messages: list[dict]):
        self.world_messages = [
            (m.get('name', ''), m.get('text', ''), m.get('time', ''))
            for m in messages
        ]
        self._notify('set_world_history')

    # ── 房间聊天 ──

    def add_room_message(self, name: str, text: str, time: str):
        self.room_messages.append((name, text, time))
        if len(self.room_messages) > MAX_LINES_CHAT:
            self.room_messages = self.room_messages[-MAX_LINES_CHAT:]
        self._notify('add_room_message', name, text, time)

    def clear_room_messages(self):
        self.room_messages.clear()
        self._notify('clear_room_messages')

    # ── 私聊 ──

    def set_dm_history(self, conversations: dict):
        for peer, msgs in conversations.items():
            if peer not in self.dm_tabs:
                self.dm_tabs.append(peer)
            self.dm_entries[peer] = [
                (m.get('from', ''), m.get('text', ''), m.get('time', ''))
                for m in msgs
            ]
        self._notify('update_dm_history')

    def add_private_message(self, from_name: str, to_name: str, text: str, time_str: str = ""):
        peer = to_name if from_name == self._player_name else from_name
        if peer not in self.dm_tabs:
            self.dm_tabs.append(peer)
        self.dm_entries.setdefault(peer, []).append((from_name, text, time_str))
        if len(self.dm_entries[peer]) > MAX_LINES_CHAT:
            self.dm_entries[peer] = self.dm_entries[peer][-MAX_LINES_CHAT:]
        if from_name != self._player_name and peer != self.viewing_dm and peer not in self.dm_muted:
            self.dm_unread[peer] = self.dm_unread.get(peer, 0) + 1
        self._notify('add_private_message', peer, from_name, text, time_str)

    def close_dm_tab(self, peer: str):
        """关闭私聊标签页"""
        if peer in self.dm_tabs:
            self.dm_tabs.remove(peer)
        self.dm_entries.pop(peer, None)
        self.dm_unread.pop(peer, None)
        self._notify('close_private_tab', peer)

    def clear_dm_entries(self, peer: str):
        """清空本地私聊记录"""
        self.dm_entries[peer] = []
        self._notify('update_dm_history')


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
        self.location: str = ''
        self.location_path: str = ''

    def update_player_info(self, player_data: dict):
        self.player_data = player_data
        self._notify('update_player_info', player_data)

    def update_location(self, location: str):
        self.location = location
        self._notify('update_location', location)

    def update_location_path(self, path: str):
        self.location_path = path
        self._notify('update_location_path', path)

    def clear(self):
        self.player_data = {}
        self._notify('clear')


class OnlineState(BaseState):
    """在线用户面板的全部状态"""

    def __init__(self):
        super().__init__()
        self.users: list = []
        self.friends: list[str] | None = None
        self.all_users: list[str] = []
        self.tab: str = "friends"
        self.cursor: int = 0
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

    def __init__(self):
        super().__init__()
        self.room_data: dict = {}
        self.games: list[dict] = []  # 可用游戏列表 [{id, name, icon, ...}]
        self.rooms: list[dict] = []  # 活跃房间列表

    def set_games(self, games: list[dict]):
        self.games = games
        self._notify('set_games', games)

    def set_rooms(self, rooms: list[dict]):
        self.rooms = rooms
        self._notify('set_rooms', rooms)

    def update_room(self, room_data: dict):
        self.room_data = room_data
        self._notify('update_room', room_data)

    def clear(self):
        self.room_data = {}
        self._notify('clear')


class NotificationState(BaseState):
    """通知面板的全部状态 — 系统通知 + 好友申请 + 游戏邀请"""

    _MAX_NOTIFICATIONS = 200

    def __init__(self):
        super().__init__()
        self.system_notifications: list[str] = []
        # 好友申请: [{name, status}]  status = 'pending' | 'accepted' | 'rejected'
        self.friend_requests: list[dict] = []
        # 游戏邀请: [{from, game, room_id, status}]  status = 'pending' | 'accepted' | 'rejected'
        self.game_invites: list[dict] = []
        self.tab: str = "system"
        self.cursor: int = 0
        self.badge_seen: bool = False  # 打开通知面板后标记为已读

    def set_friend_requests(self, names: list[str]):
        """设置完整的好友申请列表（服务端推送的待处理列表）"""
        self.badge_seen = False
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
        self.badge_seen = False
        for r in self.friend_requests:
            if r['name'] == from_name:
                # 如果已存在，重置为 pending
                r['status'] = 'pending'
                self._notify('update_friend_requests')
                return
        self.friend_requests.append({'name': from_name, 'status': 'pending'})
        self._notify('update_friend_requests')

    @property
    def unread_count(self) -> int:
        """未读(pending)好友申请数量"""
        return sum(1 for r in self.friend_requests if r['status'] == 'pending')

    # ── 游戏邀请 ──

    def add_game_invite(self, from_name: str, game: str, room_id: str,
                        expires_in: int = 300):
        """新增游戏邀请（同一游戏同一人只保留最新）"""
        self.badge_seen = False
        import time
        self.game_invites = [
            inv for inv in self.game_invites
            if not (inv['from'] == from_name and inv['game'] == game)
        ]
        self.game_invites.append({
            'from': from_name, 'game': game,
            'room_id': room_id, 'status': 'pending',
            'expires_at': time.time() + expires_in,
        })
        self._notify('update_game_invites')

    def mark_game_invite(self, from_name: str, game: str, status: str):
        """标记游戏邀请状态: 'accepted' | 'rejected'"""
        for inv in self.game_invites:
            if inv['from'] == from_name and inv['game'] == game:
                inv['status'] = status
                break
        self._notify('update_game_invites')

    def remove_game_invite(self, from_name: str, game: str):
        """删除游戏邀请记录"""
        self.game_invites = [
            inv for inv in self.game_invites
            if not (inv['from'] == from_name and inv['game'] == game)
        ]
        self._notify('update_game_invites')

    @property
    def unread_game_count(self) -> int:
        """未读(pending且未过期)游戏邀请数量"""
        import time
        now = time.time()
        return sum(
            1 for inv in self.game_invites
            if inv['status'] == 'pending' and inv.get('expires_at', 0) > now
        )

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
        self.notify = NotificationState()
        self.location = "lobby"
