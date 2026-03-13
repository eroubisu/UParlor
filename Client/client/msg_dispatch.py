"""
消息分发 — 处理服务端推送消息的路由逻辑

从 on_server_msg() 提取，纯函数式分发，不依赖 Widget。
"""

from __future__ import annotations

from .messages import (
    parse_server_message,
    LoginPrompt, LoginSuccess,
    SystemMessage, GameMessage, ChatMessage, ChatHistory,
    StatusUpdate, OnlineUsers, GameInvite,
    RoomUpdate, RoomLeave, GameQuit, LocationUpdate,
    CommandsUpdate, GameEvent, ActionCommand,
)
from .game_handler import GameHandlerContext, get_handler
from .ui.panels import (
    ChatPanel, CommandPanel, StatusPanel, OnlineUsersPanel, LoginPanel,
)


def dispatch_server_message(app, screen, raw: dict) -> None:
    """将解析后的服务器消息路由到对应的 State + Widget。

    Parameters
    ----------
    app : GameLobbyApp
    screen : GameScreen
    raw : dict — 原始 JSON 消息
    """
    parsed = parse_server_message(raw)
    st = screen.state

    def _cmd_add(text, **kw):
        st.cmd.add_line(text)
        w = screen._get_module('cmd')
        if isinstance(w, CommandPanel):
            w.add_message(text, **kw)

    def _chat():
        w = screen._get_module('chat')
        return w if isinstance(w, ChatPanel) else None

    def _status():
        w = screen._get_module('status')
        return w if isinstance(w, StatusPanel) else None

    def _online():
        w = screen._get_module('online')
        return w if isinstance(w, OnlineUsersPanel) else None

    if isinstance(parsed, LoginPrompt):
        login = screen._get_module('login')
        if isinstance(login, LoginPanel):
            login.add_message(parsed.text)
        else:
            _cmd_add(parsed.text)

    elif isinstance(parsed, LoginSuccess):
        screen.logged_in = True
        st.cmd.add_line(parsed.text)
        screen.call_later(screen._rebuild_to_game_layout)

    elif isinstance(parsed, SystemMessage):
        st.chat.add_system_message(parsed.text)
        chat = _chat()
        if chat:
            chat.add_system_message(parsed.text)

    elif isinstance(parsed, GameMessage):
        st.cmd.add_line(parsed.text)
        w = screen._get_module('cmd')
        if isinstance(w, CommandPanel):
            w.add_message(parsed.text, update_last=parsed.update_last)

    elif isinstance(parsed, ChatMessage):
        st.chat.add_message(parsed.name, parsed.text, parsed.channel, parsed.time)
        chat = _chat()
        if chat:
            chat.add_message(parsed.name, parsed.text, parsed.channel, parsed.time)

    elif isinstance(parsed, ChatHistory):
        st.chat.set_history(parsed.messages, parsed.channel)
        chat = _chat()
        if chat:
            chat.show_history(parsed.messages, parsed.channel)

    elif isinstance(parsed, StatusUpdate):
        if parsed.location_path:
            try:
                from textual.widgets import Static
                indicator = screen.query_one("#location-indicator", Static)
                indicator.update(parsed.location_path)
            except Exception:
                pass
        layout_data = parsed.data.get('window_layout')
        if layout_data:
            app._saved_layout = layout_data
            if not screen._layout_loaded:
                from .ui.layout import deserialize
                tree = deserialize(layout_data)
                if tree:
                    screen._layout_loaded = True
                    screen._layout_tree = tree
                    screen.call_later(screen._apply_saved_layout)
        st.status.update_player_info(parsed.data)
        status = _status()
        if status:
            status.update_player_info(parsed.data)

    elif isinstance(parsed, OnlineUsers):
        st.online.users = parsed.users
        st.chat.update_online_count(parsed.users)
        chat = _chat()
        if chat:
            chat.update_online_users(parsed.users)
        online = _online()
        if online:
            online.update_users(parsed.users)

    elif isinstance(parsed, GameInvite):
        inv = parsed.raw
        invite_text = f"[b]游戏邀请[/b]: {inv.get('from', '?')} 邀请你加入 {inv.get('game', '?')}"
        _cmd_add(invite_text)

    elif isinstance(parsed, RoomUpdate):
        if parsed.room_data:
            st.game_board.update_room(parsed.room_data)
            board = screen._get_module('game_board')
            if board and hasattr(board, 'update_room'):
                board.update_room(parsed.room_data)
        if parsed.message:
            _cmd_add(parsed.message)

    elif isinstance(parsed, (RoomLeave, GameQuit)):
        if parsed.location:
            if hasattr(parsed, 'commands') and parsed.commands:
                from .commands import set_commands
                set_commands(parsed.commands)
                screen._update_hint_bar()
            path = getattr(parsed, 'location_path', None)
            screen._update_location(parsed.location, path)

    elif isinstance(parsed, LocationUpdate):
        from .commands import set_commands
        set_commands(parsed.commands)
        screen._update_hint_bar()
        screen._update_location(parsed.location, parsed.location_path)

    elif isinstance(parsed, CommandsUpdate):
        from .commands import set_commands
        set_commands(parsed.commands)
        screen._update_hint_bar()

    elif isinstance(parsed, GameEvent):
        handler = get_handler(parsed.game_type)
        if handler:
            ctx = GameHandlerContext(
                state=st,
                get_module=screen._get_module,
                set_timer=app.set_timer,
                ensure_panel=screen._ensure_module_panel,
                remove_panel=screen._remove_module_panel,
            )
            handler.handle_event(parsed.event, parsed.data, ctx)

    elif isinstance(parsed, ActionCommand):
        action = parsed.action
        if action == "clear":
            st.cmd.clear()
            w = screen._get_module('cmd')
            if w and hasattr(w, 'clear'):
                w.clear()
        elif action == "version":
            sv = parsed.raw.get("server_version", "未知")
            try:
                from .config import VERSION
            except ImportError:
                VERSION = None
            cv = VERSION or "开发版"
            ver_text = f"版本信息\n客户端: v{cv}\n服务器: v{sv}"
            _cmd_add(ver_text)
        elif action == "exit":
            app.network.disconnect()
            app.exit()
        elif action == "maintenance":
            maint_text = "[b]系统维护[/b]: 服务器正在维护，请稍后重连。"
            _cmd_add(maint_text)
            app.network.disconnect()
