"""UParlor 业务窗口集成 — 各窗口 spec 共用的 preconditions / binders / hooks

设计:
- 这一层是宿主业务，**不属于** window_engine 通用引擎
- 每个窗口 spec 引用这里的回调，避免在 spec 内嵌大段业务 lambda
- ctx = GameScreen 实例 (有 .state / .app / .mode / .update_badges())
"""

from __future__ import annotations



# ── Preconditions ──

def logged_in(ctx) -> bool:
    """必须已登录 (mode 不在 login/tutorial)"""
    return getattr(ctx, "mode", "login") not in ("login", "tutorial")


# ── Binders ──

def bind_state(w, ctx) -> None:
    """通用绑定: w.bind_state(ctx.state)"""
    w.bind_state(ctx.state)


def bind_state_with_send(w, ctx) -> None:
    """绑定 state + send_command (waiting/game 主窗口用)"""
    w.bind_state(ctx.state, ctx.app.send_command)


def bind_chat(w, ctx, dm_peer: str = "") -> None:
    """聊天窗口绑定: state + 可选 DM 跳转"""
    w.bind_state(ctx.state)
    if dm_peer:
        w.open_dm(dm_peer)


def bind_game_select(w, ctx) -> None:
    """游戏选择窗口绑定: state + send_command 回调"""
    w.bind_state(ctx.state, ctx.app.send_command)


def bind_profile(w, ctx, card: dict | None = None) -> None:
    """档案窗口绑定: state + 可选名片渲染"""
    w.bind_state(ctx.state)
    if card:
        data = card.get("data") or {}
        my_name = ctx.state.status.player_data.get("name", "")
        is_self = data.get("name") == my_name
        friends = ctx.state.online.friends or []
        w.show_player_card(data, is_self=is_self, friends=friends)


def bind_chat_style(w, ctx) -> None:
    """Bind the standalone chat style editor to status and network output."""
    w.bind_state(ctx.state, ctx.app.network.send)


# ── Lifecycle hooks ──

def chat_on_open(w, ctx) -> None:
    """聊天窗口打开后: 清除所有 DM 未读 + 刷新徽章"""
    if ctx.state.chat.dm_unread:
        ctx.state.chat.clear_dm_unread()
        ctx.update_badges()


def chat_on_close(w, ctx) -> None:
    """聊天窗口关闭后停止跟踪当前私聊。"""
    del ctx
    panel = w.query_one("#chat-content")
    if panel._chat_state:
        panel._chat_state.set_viewing_dm("")


def notification_on_open(w, ctx) -> None:
    """通知窗口打开后: 标记徽章已读 + 刷新徽章"""
    ctx.state.notify.mark_badge_seen()
    ctx.update_badges()
