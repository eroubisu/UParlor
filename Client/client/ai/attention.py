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


# ── 工具注册表 ──

TOOLS = {
    "look_chat": look_chat,
    "look_online": look_online,
    "look_inventory": look_inventory,
    "look_game_room": look_game_room,
    "look_player_status": look_player_status,
    "look_around": look_around,
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
