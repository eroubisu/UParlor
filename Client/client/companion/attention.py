"""AI 旅伴的感知工具集 — LLM function calling 入口。

设计:
- 工具函数只读取由主线程从 ModuleStateManager 捕获的账号标记快照。
- 私聊只查询 ChatState 的当前会话 UI 投影，不创建第二份持久化记录。
- 所有工具函数签名: (state, **kwargs) -> str
- 工具返回字符串 (LLM 可读)。失败返回简短错误说明而非抛异常。

工具清单:
  look_self                 玩家自己的资料 (名字/等级/金币)
  look_world_chat(n)        最近 N 条公聊
  look_room_chat(n)         最近 N 条房间聊天
  look_online()             在线列表
  look_friends()            好友列表 + 在线状态
  look_notifications()      系统通知
  look_dm_partners()        当前会话中有私聊投影的玩家
  look_messages(scope, peer, limit)
                            统一的消息查询。scope = "world"|"room"|"dm"
  look_game()               按需查看当前游戏进程
"""

from __future__ import annotations

from copy import deepcopy
from collections import deque
import json
import threading
from types import SimpleNamespace
from typing import Any

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


def _safe_get(obj: Any, *path, default=None):
    cur = obj
    for k in path:
        if cur is None:
            return default
        cur = getattr(cur, k, None)
    return cur if cur is not None else default


def snapshot_state(state: Any, account: str) -> Any:
    """在主线程捕获旅伴可见的最小 State 投影。"""
    chat = _safe_get(state, "chat")
    status = _safe_get(state, "status")
    online = _safe_get(state, "online")
    notify = _safe_get(state, "notify")
    game_board = _safe_get(state, "game_board")
    return SimpleNamespace(
        account=account,
        chat=SimpleNamespace(
            world_messages=deepcopy(
                _safe_get(chat, "world_messages", default=[]) or []),
            room_messages=deepcopy(
                _safe_get(chat, "room_messages", default=[]) or []),
            dm_entries=deepcopy(
                _safe_get(chat, "dm_entries", default={}) or {}),
            dm_tabs=deepcopy(_safe_get(chat, "dm_tabs", default=[]) or []),
        ),
        status=SimpleNamespace(
            player_data=deepcopy(
                _safe_get(status, "player_data", default={}) or {}),
            location=_safe_get(status, "location", default=""),
        ),
        online=SimpleNamespace(
            users=deepcopy(_safe_get(online, "users", default=[]) or []),
            friends=deepcopy(_safe_get(online, "friends", default=[]) or []),
        ),
        notify=SimpleNamespace(
            system_notifications=deepcopy(
                _safe_get(notify, "system_notifications", default=[]) or []),
            unread_count=_safe_get(notify, "unread_count", default=0) or 0,
        ),
        game=SimpleNamespace(
            room_data=deepcopy(
                _safe_get(game_board, "room_data", default={}) or {}),
        ),
    )


# ── 工具函数 ──

def look_self(state: Any, **_kw) -> str:
    pd = _safe_get(state, "status", "player_data", default={}) or {}
    if not pd:
        return "（暂无玩家资料）"
    parts = []
    if pd.get("name"):
        parts.append(f"名字: {pd['name']}")
    if pd.get("level"):
        parts.append(f"等级: Lv.{pd['level']}")
    if pd.get("exp") is not None:
        parts.append(f"经验: {pd['exp']}")
    if pd.get("gold") is not None:
        parts.append(f"金币: {pd['gold']}G")
    if pd.get("title"):
        parts.append(f"称号: {pd['title']}")
    loc = _safe_get(state, "status", "location", default="")
    if loc:
        parts.append(f"位置: {loc}")
    return " | ".join(parts) if parts else "（暂无玩家资料）"


def _format_msgs(msgs: list, limit: int, *, context: str = "") -> str:
    if not msgs:
        return "（无消息）"
    msgs = msgs[-limit:]
    lines = []
    for m in msgs:
        if all(hasattr(m, attr) for attr in ("sender_name", "text", "time")):
            name, text, t = m.sender_name, m.text, m.time
            prefix = f"[{t}] " if t else ""
            lines.append(f"{prefix}{name}: {text}")
        elif isinstance(m, tuple) and len(m) >= 3:
            name, text, t = m[0], m[1], m[2]
            prefix = f"[{t}] " if t else ""
            lines.append(f"{prefix}{name}: {text}")
    if not lines:
        return "（无消息）"
    body = "\n".join(lines)
    return f"{context}\n{body}" if context else body


def look_world_chat(state: Any, count: int = _DEFAULT_LIMIT, **_kw) -> str:
    n = max(1, min(int(count or _DEFAULT_LIMIT), _MAX_LIMIT))
    msgs = _safe_get(state, "chat", "world_messages", default=[]) or []
    return _format_msgs(
        msgs,
        n,
        context="以下是世界频道中玩家彼此的消息，不是对旅伴说的话：",
    )


def look_room_chat(state: Any, count: int = _DEFAULT_LIMIT, **_kw) -> str:
    n = max(1, min(int(count or _DEFAULT_LIMIT), _MAX_LIMIT))
    msgs = _safe_get(state, "chat", "room_messages", default=[]) or []
    return _format_msgs(
        msgs,
        n,
        context="以下是房间频道中玩家彼此的消息，不是对旅伴说的话：",
    )


def look_online(state: Any, **_kw) -> str:
    users = _safe_get(state, "online", "users", default=[]) or []
    if not users:
        return "（无在线玩家）"
    names = []
    for u in users[:20]:
        if isinstance(u, dict):
            names.append(u.get("name", "?"))
        else:
            names.append(str(u))
    return f"{len(users)}人在线: " + ", ".join(names)


def look_friends(state: Any, **_kw) -> str:
    friends = _safe_get(state, "online", "friends", default=[]) or []
    if not friends:
        return "（无好友）"
    online_users = _safe_get(state, "online", "users", default=[]) or []
    online_names = set()
    for u in online_users:
        if isinstance(u, dict):
            online_names.add(u.get("name", ""))
        else:
            online_names.add(str(u))
    lines = []
    for name in friends:
        status = "在线" if name in online_names else "离线"
        lines.append(f"[{status}] {name}")
    return "\n".join(lines)


def look_notifications(state: Any, count: int = _DEFAULT_LIMIT, **_kw) -> str:
    n = max(1, min(int(count or _DEFAULT_LIMIT), _MAX_LIMIT))
    notes = _safe_get(state, "notify", "system_notifications", default=[]) or []
    if not notes:
        return "（无通知）"
    return "\n".join(notes[-n:])


def look_dm_partners(state: Any, **_kw) -> str:
    entries = _safe_get(state, "chat", "dm_entries", default={}) or {}
    partners = sorted(peer for peer, messages in entries.items() if messages)
    if not partners:
        return "（当前会话无私聊消息）"
    return "当前会话私聊玩家: " + ", ".join(partners)


def look_messages(state: Any, scope: str = "dm", peer: str = "",
                  limit: int = _DEFAULT_LIMIT, **_kw) -> str:
    """查询 ChatState 当前会话 UI 投影。"""
    scope = (scope or "dm").lower()
    n = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))

    if scope == "world":
        msgs = _safe_get(state, "chat", "world_messages", default=[]) or []
        return _format_msgs(
            msgs,
            n,
            context="以下是世界频道中玩家彼此的消息，不是对旅伴说的话：",
        )
    if scope == "room":
        msgs = _safe_get(state, "chat", "room_messages", default=[]) or []
        return _format_msgs(
            msgs,
            n,
            context="以下是房间频道中玩家彼此的消息，不是对旅伴说的话：",
        )
    if scope == "dm":
        conversations = _safe_get(
            state, "chat", "dm_entries", default={}) or {}
        selected = (
            [(peer, conversations.get(peer, []))]
            if peer else list(conversations.items())
        )
        messages = [
            entry
            for _peer, entries in selected
            for entry in entries
        ]
        if not messages:
            return "（无符合条件的私聊记录）"
        return _format_msgs(
            messages,
            n,
            context="以下是玩家与其他人的私聊，不是对旅伴说的话：",
        )
    return f"（未知 scope: {scope}）"


def look_game(state: Any, **_kw) -> str:
    """Return the current player-visible game snapshot on demand."""
    room_data = _safe_get(state, "game", "room_data", default={}) or {}
    if not room_data:
        return "（当前没有游戏进程）"
    return json.dumps(room_data, ensure_ascii=False, separators=(",", ":"))


TOOLS: dict[str, Any] = {
    "look_self": look_self,
    "look_world_chat": look_world_chat,
    "look_room_chat": look_room_chat,
    "look_online": look_online,
    "look_friends": look_friends,
    "look_notifications": look_notifications,
    "look_dm_partners": look_dm_partners,
    "look_messages": look_messages,
    "look_game": look_game,
}


# ── 极简环境摘要 (system prompt 注入) ──

class AwarenessSummary:
    @staticmethod
    def build(state: Any, buffer: "AttentionBuffer | None" = None) -> str:
        parts = []
        try:
            pd = _safe_get(state, "status", "player_data", default={}) or {}
            name = pd.get("name", "")
            if name:
                level = pd.get("level", "")
                parts.append(f"主人 {name}" + (f" Lv.{level}" if level else ""))
        except Exception:
            pass
        try:
            loc = _safe_get(state, "status", "location", default="")
            if loc and loc != "lobby":
                parts.append(f"主人在 {loc}")
        except Exception:
            pass
        try:
            n = len(_safe_get(state, "online", "users", default=[]) or [])
            if n:
                parts.append(f"{n}人在线")
        except Exception:
            pass
        try:
            unread = _safe_get(state, "notify", "unread_count", default=0) or 0
            if unread:
                parts.append(f"{unread}条未读通知")
        except Exception:
            pass
        summary = " | ".join(parts) if parts else "私聊中"
        if buffer:
            events = buffer.drain()
            if events:
                summary += "\n刚才: " + "; ".join(events)
        return summary


class AttentionBuffer:
    def __init__(self, maxlen: int = 10):
        self._events: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, event: str):
        with self._lock:
            self._events.append(event)

    def drain(self) -> list[str]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events
