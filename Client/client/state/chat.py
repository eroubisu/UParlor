"""聊天状态 — 世界频道 + 私聊 + 房间"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import MAX_LINES_CHAT
from ..storage import (
    get_world_chat_clear_marker,
    set_world_chat_clear_marker,
)
from .base import BaseState


WORLD_CHAT_INITIAL_LIMIT = 16


@dataclass(frozen=True)
class ChatEntry:
    sender_name: str
    text: str
    time: str
    message_id: str = ""


class ChatState(BaseState):
    """聊天状态 — 世界频道 + 私聊 + 房间"""

    def __init__(self):
        super().__init__()
        self.world_messages: list[ChatEntry] = []
        self.world_has_more: bool = False
        self.world_history_loading: bool = False
        self._world_clear_marker: str = ""
        self.room_messages: list[ChatEntry] = []
        self.dm_entries: dict[str, list[ChatEntry]] = {}
        self.senders: dict[str, dict] = {}
        self.dm_tabs: list[str] = []
        self.active_tab: str = "world"
        self.dm_unread: dict[str, int] = {}
        self.dm_muted: set[str] = set()    # 已关闭通知的 peer
        self.dm_history_hidden: set[str] = set()
        self.dm_history_loaded: set[str] = set()
        self.viewing_dm: str = ''  # 当前正在查看的私聊对象（为空表示未查看）
        self._player_name: str = ''

    def set_player_name(self, name: str):
        self._player_name = name
        self._world_clear_marker = get_world_chat_clear_marker(name)

    @property
    def player_name(self) -> str:
        return self._player_name

    # ── 世界频道 ──

    def _register_sender(self, name: str, sender: dict | None) -> str:
        current = dict(sender) if isinstance(sender, dict) else {}
        canonical_name = str(current.get("name") or name)
        current["name"] = canonical_name
        self.senders[canonical_name] = current
        return canonical_name

    def sender(self, name: str) -> dict:
        return self.senders.get(name, {"name": name})

    def update_sender(self, sender: dict) -> None:
        name = str(sender.get("name", ""))
        if not name:
            return
        self._register_sender(name, sender)
        self._notify('sender_updated', name)

    def add_world_message(
        self, name: str, text: str, time: str, sender: dict | None = None,
        message_id: str = "",
    ):
        canonical_name = self._register_sender(name, sender)
        self.world_messages.append(
            ChatEntry(canonical_name, text, time, message_id))
        if len(self.world_messages) > MAX_LINES_CHAT:
            self.world_messages = self.world_messages[-MAX_LINES_CHAT:]
        self._notify('add_world_message')

    def set_world_history(
            self, messages: list[dict], has_more: bool = False):
        entries = []
        for message in messages:
            name = message.get('name', '')
            canonical_name = self._register_sender(
                name, message.get('sender'))
            entries.append(ChatEntry(
                canonical_name,
                message.get('text', ''),
                message.get('time', ''),
                message.get('id', ''),
            ))
        if self._world_clear_marker:
            marker_index = next((
                index
                for index, entry in enumerate(entries)
                if entry.message_id == self._world_clear_marker
            ), -1)
            if marker_index >= 0:
                entries = entries[marker_index + 1:]
        self.world_messages = entries[-WORLD_CHAT_INITIAL_LIMIT:]
        self.world_has_more = has_more or bool(self._world_clear_marker)
        self.world_history_loading = False
        self._notify('set_world_history')

    def prepend_world_history(
            self, messages: list[dict], has_more: bool) -> None:
        existing_ids = {
            entry.message_id for entry in self.world_messages
            if entry.message_id
        }
        entries = []
        for message in messages:
            message_id = message.get('id', '')
            if message_id and message_id in existing_ids:
                continue
            name = self._register_sender(
                message.get('name', ''), message.get('sender'))
            entries.append(ChatEntry(
                name,
                message.get('text', ''),
                message.get('time', ''),
                message_id,
            ))
        self.world_messages = [
            *entries,
            *self.world_messages,
        ][-MAX_LINES_CHAT:]
        self.world_has_more = has_more
        self.world_history_loading = False
        self._notify('prepend_world_history', len(entries))

    def reset_world_projection(self) -> None:
        if self._world_clear_marker:
            marker_index = next((
                index
                for index, entry in enumerate(self.world_messages)
                if entry.message_id == self._world_clear_marker
            ), -1)
            if marker_index >= 0:
                self.world_messages = self.world_messages[marker_index + 1:]
            self.world_has_more = True
            self.world_history_loading = False
        if len(self.world_messages) <= WORLD_CHAT_INITIAL_LIMIT:
            return
        self.world_messages = self.world_messages[-WORLD_CHAT_INITIAL_LIMIT:]
        self.world_has_more = True
        self.world_history_loading = False
        self._notify('set_world_history')

    def begin_world_history_request(self) -> bool:
        if self.world_history_loading or not self.world_has_more:
            return False
        self.world_history_loading = True
        return True

    @property
    def oldest_world_message_id(self) -> str:
        if not self.world_messages:
            return ""
        return self.world_messages[0].message_id

    @property
    def world_clear_marker(self) -> str:
        return self._world_clear_marker

    def clear_world_messages(self) -> None:
        if self.world_messages:
            marker = self.world_messages[-1].message_id
            if marker:
                self._world_clear_marker = marker
                set_world_chat_clear_marker(self._player_name, marker)
        self.world_messages.clear()
        self.world_has_more = bool(self._world_clear_marker)
        self.world_history_loading = False
        self._notify('clear_world_messages')

    # ── 房间聊天 ──

    def add_room_message(
        self, name: str, text: str, time: str, sender: dict | None = None,
    ):
        canonical_name = self._register_sender(name, sender)
        self.room_messages.append(ChatEntry(canonical_name, text, time))
        if len(self.room_messages) > MAX_LINES_CHAT:
            self.room_messages = self.room_messages[-MAX_LINES_CHAT:]
        self._notify('add_room_message')

    def clear_room_messages(self):
        self.room_messages.clear()
        self._notify('clear_room_messages')

    # ── 私聊 ──

    def set_dm_history(self, conversations: dict):
        for peer, msgs in conversations.items():
            if peer not in self.dm_tabs:
                self.dm_tabs.append(peer)
            self.dm_history_loaded.add(peer)
            if peer in self.dm_history_hidden:
                continue
            entries = []
            for message in msgs:
                sender_name = message.get('from', '')
                canonical_name = self._register_sender(
                    sender_name, message.get('sender'))
                entries.append(ChatEntry(
                    canonical_name,
                    message.get('text', ''),
                    message.get('time', ''),
                ))
            self.dm_entries[peer] = entries
        self._notify('update_dm_history')

    def add_private_message(
        self, from_name: str, to_name: str, text: str,
        time_str: str = "", sender: dict | None = None,
    ):
        peer = to_name if from_name == self._player_name else from_name
        canonical_name = self._register_sender(from_name, sender)
        self.dm_history_loaded.add(peer)
        if peer not in self.dm_tabs:
            self.dm_tabs.append(peer)
        self.dm_entries.setdefault(peer, []).append(
            ChatEntry(canonical_name, text, time_str))
        if len(self.dm_entries[peer]) > MAX_LINES_CHAT:
            self.dm_entries[peer] = self.dm_entries[peer][-MAX_LINES_CHAT:]
        if from_name != self._player_name and peer != self.viewing_dm and peer not in self.dm_muted:
            self.dm_unread[peer] = self.dm_unread.get(peer, 0) + 1
        self._notify('add_private_message', peer)

    def close_dm_tab(self, peer: str):
        """关闭私聊标签页"""
        if peer in self.dm_tabs:
            self.dm_tabs.remove(peer)
        self.dm_entries.pop(peer, None)
        self.dm_unread.pop(peer, None)
        if peer not in self.dm_history_hidden:
            self.dm_history_loaded.discard(peer)
        self._notify('close_private_tab', peer)

    def clear_dm_entries(self, peer: str):
        """隐藏当前会话投影；不会请求服务端删除持久记录。"""
        self.dm_entries[peer] = []
        self.dm_history_hidden.add(peer)
        self.dm_history_loaded.add(peer)
        self._notify('update_dm_history')

    def should_request_dm_history(self, peer: str) -> bool:
        return (
            peer not in self.dm_history_hidden
            and peer not in self.dm_history_loaded
        )

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
