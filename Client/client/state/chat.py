"""聊天状态 — 世界频道 + 私聊 + 房间"""

from __future__ import annotations

from ..config import MAX_LINES_CHAT
from .base import BaseState


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

    def set_viewing_dm(self, peer: str):
        """设置当前正在查看的私聊对象"""
        self.viewing_dm = peer
        self._notify('viewing_dm_changed', peer)

    def clear_dm_unread(self, peer: str | None = None):
        """清除未读计数：指定 peer 则清单个，否则清全部"""
        if peer is not None:
            self.dm_unread.pop(peer, None)
        else:
            self.dm_unread.clear()
        self._notify('dm_unread_changed')

    def add_dm_tab(self, peer: str):
        """确保私聊标签存在，不存在则添加并初始化"""
        if peer not in self.dm_tabs:
            self.dm_tabs.append(peer)
            self.dm_entries.setdefault(peer, [])
            self._notify('dm_tab_added', peer)

    def toggle_dm_muted(self, peer: str):
        """切换私聊静音状态"""
        if peer in self.dm_muted:
            self.dm_muted.discard(peer)
        else:
            self.dm_muted.add(peer)
        self._notify('dm_muted_toggled', peer)
