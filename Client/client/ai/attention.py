"""AI 注意力系统 — Function Calling 驱动的选择性感知"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from google.genai import types

if TYPE_CHECKING:
    from ..state import ModuleStateManager

# ── 常量 ──

_MAX_CHAT_LINES = 15
_MAX_ONLINE_USERS = 20
_MAX_INVENTORY_ITEMS = 10
_MAX_GAME_DESC = 1500


# ── 工具函数 ──

def look_chat(state: ModuleStateManager, **_kw) -> str:
    """返回最近公聊消息"""
    try:
        entries = state.chat.entries[-_MAX_CHAT_LINES:]
        lines = []
        for e in entries:
            if len(e) >= 4 and e[0] == "msg":
                lines.append(f"{e[1]}> {e[2]}")
            elif e[0] == "sys":
                lines.append(f"[系统] {e[1]}")
        return "\n".join(lines) if lines else "聊天室暂无消息"
    except Exception:
        return "无法查看聊天室"


def look_online(state: ModuleStateManager, **_kw) -> str:
    """返回在线用户列表"""
    try:
        users = state.online.users
        if not users:
            return "当前没有在线用户"
        names = []
        for u in users[:_MAX_ONLINE_USERS]:
            if isinstance(u, dict):
                name = u.get("name", "?")
                level = u.get("level", "")
                names.append(f"{name}(Lv.{level})" if level else name)
            else:
                names.append(str(u))
        result = f"在线 {len(users)} 人: " + ", ".join(names)
        if len(users) > _MAX_ONLINE_USERS:
            result += f" ...等共{len(users)}人"
        return result
    except Exception:
        return "无法查看在线用户"


def look_inventory(state: ModuleStateManager, **_kw) -> str:
    """返回背包物品"""
    try:
        inv = state.inventory
        if not inv.items:
            return f"背包为空。金币: {inv.gold}G"
        lines = [f"{it['name']} x{it['count']}" +
                 (f" - {it['desc']}" if it.get("desc") else "")
                 for it in inv.items[:_MAX_INVENTORY_ITEMS]]
        result = "\n".join(lines)
        result += f"\n金币: {inv.gold}G"
        return result
    except Exception:
        return "无法查看背包"


def look_game_room(state: ModuleStateManager, **_kw) -> str:
    """返回当前游戏房间状态"""
    import json
    try:
        rd = state.game_board.room_data
        if not rd:
            return "当前不在任何游戏房间"
        parts = []
        game = rd.get("game_type") or rd.get("game", "")
        if game:
            parts.append(f"游戏: {game}")
        players = rd.get("players")
        if players:
            if isinstance(players, dict):
                pnames = list(players.values())
            elif isinstance(players, list):
                pnames = [p.get("name", "?") if isinstance(p, dict) else str(p)
                          for p in players]
            else:
                pnames = [str(players)]
            parts.append(f"玩家: {', '.join(str(n) for n in pnames)}")
        status = rd.get("state") or rd.get("status", "")
        if status:
            parts.append(f"状态: {status}")

        # 优先: 客户端 handler 的 ai_describe 方法
        desc = None
        if game:
            from ..protocol.handler import get_handler
            handler = get_handler(game)
            if handler and hasattr(handler, 'ai_describe'):
                try:
                    desc = handler.ai_describe(rd)
                except Exception:
                    pass
        # 回退: 服务端 room_data 中的 ai_summary
        if not desc:
            desc = rd.get("ai_summary")
        # 最终回退: 仅提取关键字段
        if not desc:
            brief = {k: rd[k] for k in ("game_type", "game", "state", "status",
                                         "round", "turn", "phase")
                     if k in rd}
            try:
                desc = json.dumps(brief, ensure_ascii=False, separators=(',', ':'))
            except Exception:
                desc = str(brief)
        parts.append(desc[:_MAX_GAME_DESC])

        # 附带最近事件缓冲
        events = state.game_board.recent_events
        if events:
            parts.append("[最近事件] " + " / ".join(events[-5:]))

        return " | ".join(parts)
    except Exception:
        return "无法查看游戏房间"


def look_player_status(state: ModuleStateManager, **_kw) -> str:
    """返回玩家详细状态"""
    try:
        pd = state.status.player_data
        if not pd:
            return "未获取到玩家状态"
        lines = []
        for key, label in [("name", "名字"), ("level", "等级"),
                           ("gold", "金币"), ("title", "称号")]:
            val = pd.get(key, "")
            if val not in ("", None, 0):
                lines.append(f"{label}: {val}")
        # game_stats（由 send_player_status 传输）
        gs = pd.get("game_stats")
        if isinstance(gs, dict):
            tw = gs.get("total_wins", 0)
            tl = gs.get("total_losses", 0)
            td = gs.get("total_draws", 0)
            if tw or tl or td:
                lines.append(f"战绩: {tw}胜 {tl}负 {td}平")
        return "\n".join(lines) if lines else "玩家状态为空"
    except Exception:
        return "无法查看玩家状态"


def look_around(state: ModuleStateManager, **_kw) -> str:
    """综合环境感知 — 位置 + 房间 + 周围人"""
    parts = []
    if state.location:
        parts.append(f"位置: {state.location}")
    parts.append(look_online(state))
    room = look_game_room(state)
    if "不在任何" not in room:
        parts.append(room)
    return "\n".join(parts) if parts else "周围没什么特别的"


_MAX_FRIENDS = 30
_MAX_DM_OVERVIEW = 10
_MAX_DM_MESSAGES = 30


def look_friends(state: ModuleStateManager, **_kw) -> str:
    """返回好友列表和在线状态"""
    try:
        friends = state.online.friends
        if not friends:
            return "还没有好友"
        # 获取在线用户名集合
        online_names = set()
        for u in state.online.users:
            if isinstance(u, dict):
                online_names.add(u.get('name', ''))
            else:
                online_names.add(str(u))
        items = []
        for f in friends[:_MAX_FRIENDS]:
            tag = "在线" if f in online_names else "离线"
            items.append(f"{f}({tag})")
        result = f"好友 {len(friends)} 人: " + ", ".join(items)
        if len(friends) > _MAX_FRIENDS:
            result += f" ...等共{len(friends)}人"
        # 附带好友申请详情
        try:
            reqs = state.notify.friend_requests
            pending = [r for r in reqs if r.get('status') == 'pending']
            if pending:
                names = ", ".join(r['name'] for r in pending[:10])
                result += f" | 待处理好友申请: {names}"
        except Exception:
            pass
        return result
    except Exception:
        return "无法查看好友列表"


def look_dm(state: ModuleStateManager, *, peer: str = "", count: int = 10, **_kw) -> str:
    """返回私聊消息: 无 peer 返回概览，有 peer 返回详细消息"""
    try:
        chat = state.chat
        if not peer:
            # 概览模式: 列出所有私聊标签
            tabs = chat.dm_tabs
            if not tabs:
                return "没有私聊对话"
            lines = []
            for t in tabs[:_MAX_DM_OVERVIEW]:
                entries = chat.dm_entries.get(t, [])
                unread = "未读" if t in chat.dm_unread else ""
                if entries:
                    last = entries[-1]
                    preview = last[1][:20] + ("..." if len(last[1]) > 20 else "")
                    tag = f"[{unread}]" if unread else ""
                    lines.append(f"{t}{tag}: {last[0]}> {preview}")
                else:
                    lines.append(f"{t}: (无消息)")
            result = f"私聊对话 {len(tabs)} 个:\n" + "\n".join(lines)
            unread_count = len(chat.dm_unread)
            if unread_count:
                result += f"\n共 {unread_count} 个对话有未读消息"
            return result
        else:
            # 详细模式: 返回与指定用户的最近 count 条消息
            count = max(1, min(count, _MAX_DM_MESSAGES))
            entries = chat.dm_entries.get(peer, [])
            if not entries:
                return f"与{peer}没有私聊记录"
            recent = entries[-count:]
            lines = [f"{from_name}> {text}" for from_name, text, _t in recent]
            return f"与{peer}的私聊(最近{len(recent)}条):\n" + "\n".join(lines)
    except Exception:
        return "无法查看私聊"


def look_notifications(state: ModuleStateManager, **_kw) -> str:
    """返回系统通知列表"""
    try:
        notes = state.notify.system_notifications
        if not notes:
            return "没有系统通知"
        recent = notes[-15:]
        return f"系统通知(最近{len(recent)}条):\n" + "\n".join(recent)
    except Exception:
        return "无法查看系统通知"


# ── 工具注册表 ──

TOOLS = {
    "look_chat": look_chat,
    "look_online": look_online,
    "look_inventory": look_inventory,
    "look_game_room": look_game_room,
    "look_player_status": look_player_status,
    "look_around": look_around,
    "look_friends": look_friends,
    "look_dm": look_dm,
    "look_notifications": look_notifications,
}

# ── Gemini Function Declarations ──

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="look_chat",
        description="查看聊天室最近的公共聊天消息",
        parameters_json_schema={},
    ),
    types.FunctionDeclaration(
        name="look_online",
        description="查看当前在线的用户列表",
        parameters_json_schema={},
    ),
    types.FunctionDeclaration(
        name="look_inventory",
        description="查看玩家的背包物品和金币",
        parameters_json_schema={},
    ),
    types.FunctionDeclaration(
        name="look_game_room",
        description="查看当前游戏房间的状态、玩家和进度",
        parameters_json_schema={},
    ),
    types.FunctionDeclaration(
        name="look_player_status",
        description="查看玩家的详细状态信息（等级、金币、段位等）",
        parameters_json_schema={},
    ),
    types.FunctionDeclaration(
        name="look_around",
        description="环顾四周，了解当前位置、在线用户和游戏房间情况",
        parameters_json_schema={},
    ),
    types.FunctionDeclaration(
        name="look_friends",
        description="查看好友列表和在线状态，以及是否有待处理的好友申请",
        parameters_json_schema={},
    ),
    types.FunctionDeclaration(
        name="look_dm",
        description="查看私聊消息。不指定 peer 时返回所有私聊对话概览，指定 peer 时返回与该用户的最近聊天记录",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "peer": {
                    "type": "string",
                    "description": "对方用户名，留空则返回所有私聊概览"
                },
                "count": {
                    "type": "integer",
                    "description": "查看条数，默认10，最多30"
                }
            },
        },
    ),
    types.FunctionDeclaration(
        name="look_notifications",
        description="查看系统通知（公告、维护提醒等）",
        parameters_json_schema={},
    ),
]

GEMINI_TOOLS = [types.Tool(function_declarations=TOOL_DECLARATIONS)]


# ── 感知摘要 ──

class AwarenessSummary:
    """生成一行极简环境摘要（~30 token）"""

    @staticmethod
    def build(state: ModuleStateManager, buffer: AttentionBuffer | None = None) -> str:
        parts = []

        # 位置
        if state.location:
            parts.append(state.location)

        # 在线人数
        try:
            n = len(state.online.users)
            if n:
                parts.append(f"{n}人在线")
        except Exception:
            pass

        # 公聊消息数
        try:
            chat_count = sum(1 for e in state.chat.entries if e[0] == "msg")
            if chat_count:
                parts.append(f"聊天室有{chat_count}条消息")
        except Exception:
            pass

        # 背包
        try:
            item_count = len(state.inventory.items)
            if item_count:
                parts.append(f"背包{item_count}件物品")
        except Exception:
            pass

        # 游戏房间
        try:
            if state.game_board.room_data:
                rd = state.game_board.room_data
                game = rd.get("game_type") or rd.get("game", "某游戏")
                parts.append(f"在{game}房间中")
        except Exception:
            pass

        # 好友
        try:
            friends = state.online.friends
            if friends:
                online_names = set()
                for u in state.online.users:
                    if isinstance(u, dict):
                        online_names.add(u.get('name', ''))
                    else:
                        online_names.add(str(u))
                online_friends = sum(1 for f in friends if f in online_names)
                parts.append(f"{len(friends)}个好友({online_friends}人在线)")
        except Exception:
            pass

        # 系统通知
        try:
            notes = state.notify.system_notifications
            if notes:
                parts.append(f"{len(notes)}条系统通知")
        except Exception:
            pass

        # 私聊状态
        try:
            chat = state.chat
            if chat.dm_tabs:
                unread = len(chat.dm_unread)
                if chat.active_tab != "global":
                    parts.append(f"正在和{chat.active_tab}私聊")
                elif unread:
                    parts.append(f"{len(chat.dm_tabs)}个私聊对话, {unread}条未读")
                else:
                    parts.append(f"{len(chat.dm_tabs)}个私聊对话")
        except Exception:
            pass

        summary = " | ".join(parts) if parts else "大厅"

        # 事件缓冲
        if buffer:
            events = buffer.drain()
            if events:
                summary += "\n刚才: " + "; ".join(events)

        return summary


# ── 事件缓冲区 ──

class AttentionBuffer:
    """高优先级事件缓冲区 — 不需要 AI 主动查看，直接注入感知"""

    def __init__(self, maxlen: int = 10):
        self._events: deque[str] = deque(maxlen=maxlen)

    def push(self, event: str):
        self._events.append(event)

    def drain(self) -> list[str]:
        """取出所有事件并清空"""
        events = list(self._events)
        self._events.clear()
        return events

    def __len__(self) -> int:
        return len(self._events)

    def __bool__(self) -> bool:
        return bool(self._events)
