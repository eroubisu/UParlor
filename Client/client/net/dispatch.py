"""
消息分发 — 处理服务端推送消息的路由逻辑

数据流：msg_dispatch → State → (listener) → Widget
本模块只写 State，不直接操作 Widget。
"""

from __future__ import annotations

from .messages import (
    parse_server_message,
    LoginPrompt, LoginSuccess,
    SystemMessage, GameMessage, ChatMessage, ChatHistory,
    StatusUpdate, OnlineUsers, GameInvite, GameInviteResult,
    RoomUpdate, RoomLeave, GameQuit, LocationUpdate,
    CommandsUpdate, GameEvent, ActionCommand,
    FriendList, AllUsers, PrivateChat, FriendRequest, DMHistory,
    ProfileCard, GameList, RoomList, RoomChat,
)
import re as _re

from ..protocol.handler import GameHandlerContext, get_handler


def _make_handler_ctx(st, app, screen) -> GameHandlerContext:
    return GameHandlerContext(
        state=st,
        get_module=screen.get_module,
        set_timer=app.set_timer,
        send_command=app.send_command,
    )

def _strip_markup(text: str) -> str:
    """去除 Rich markup 标签，返回纯文本"""
    return _re.sub(r'\[/?[^\]]*\]', '', text)


def dispatch_server_message(app, screen, raw: dict) -> None:
    """将解析后的服务器消息路由到 State。

    Widget 通过 State listener 自动收到通知并渲染。
    只有少数不经过 State 的 UI 操作（如布局、位置指示器）仍直接操作 screen。
    """
    # 版本检查 — 连接后服务器下发最新客户端版本号
    if raw.get('type') == 'client_version':
        _handle_version_check(app, screen, raw.get('latest', ''))
        return

    parsed = parse_server_message(raw)
    handler = _DISPATCH.get(type(parsed))
    if handler:
        handler(parsed, app, screen, screen.state)


def _handle_version_check(app, screen, latest: str):
    """服务器下发最新客户端版本号，与本地对比"""
    if not latest:
        return
    try:
        import re
        from ..config import VERSION, M_DIM, M_END

        def _ver_tuple(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in re.findall(r'\d+', v.split('.dev')[0]))

        current = VERSION or "0.0.0"
        if _ver_tuple(latest) > _ver_tuple(current):
            login = screen.get_module('login')
            msg = f"{M_DIM}发现新版本 v{latest}（当前 v{current}），请更新: pip install -U uparlor{M_END}"
            if login and hasattr(login, 'add_message'):
                login.add_message(msg)
            else:
                screen.state.cmd.add_line(msg)
    except Exception:
        pass


# ── 消息处理器 ──
# 签名: handler(parsed, app, screen, st)


def _on_login_prompt(parsed, app, screen, st):
    login = screen.get_module('login')
    if login and hasattr(login, 'add_message'):
        login.add_message(parsed.text)
    else:
        st.cmd.add_line(parsed.text)


def _on_login_success(parsed, app, screen, st):
    screen.logged_in = True
    st.cmd.add_line(parsed.text)
    login = screen.get_module('login')
    if login:
        login.display = False
    screen.call_later(screen._rebuild_to_game_layout)


def _on_system_message(parsed, app, screen, st):
    st.cmd.add_line(parsed.text)
    if parsed.broadcast:
        st.notify.add_system_notification(parsed.text)
        screen.update_badges()


def _on_game_message(parsed, app, screen, st):
    st.cmd.add_line(parsed.text, update_last=parsed.update_last)


def _on_status_update(parsed, app, screen, st):
    if parsed.location:
        st.status.update_location(parsed.location)
    if parsed.location_path:
        st.status.update_location_path(parsed.location_path)
    layout_data = parsed.data.get('window_layout')
    if layout_data:
        app._saved_layout = layout_data
    player_name = parsed.data.get('name', '')
    if player_name:
        st.chat.set_player_name(player_name)
    st.status.update_player_info(parsed.data)


def _on_online_users(parsed, app, screen, st):
    st.online.update_users(parsed.users)


def _on_friend_list(parsed, app, screen, st):
    old_friends = st.online.friends
    is_init = old_friends is None
    st.online.update_friends(parsed.friends)
    if not is_init:
        old_set = set(old_friends)
        new_set = set(parsed.friends)
        for name in new_set - old_set:
            st.cmd.add_line(f"{name} 已成为你的好友")
        for name in old_set - new_set:
            st.cmd.add_line(f"{name} 已不再是你的好友")
    screen.update_badges()


def _on_all_users(parsed, app, screen, st):
    st.online.update_all_users(parsed.users)


def _on_chat_message(parsed, app, screen, st):
    st.chat.add_world_message(parsed.name, parsed.text, parsed.time)


def _on_room_chat(parsed, app, screen, st):
    st.chat.add_room_message(parsed.name, parsed.text, parsed.time)


def _on_chat_history(parsed, app, screen, st):
    st.chat.set_world_history(parsed.messages)


def _on_private_chat(parsed, app, screen, st):
    st.chat.add_private_message(
        parsed.from_name, parsed.to_name, parsed.text, parsed.time)
    screen.update_badges()


def _on_dm_history(parsed, app, screen, st):
    st.chat.set_dm_history(parsed.conversations)
    screen.update_badges()


def _on_friend_request(parsed, app, screen, st):
    if parsed.from_name:
        st.cmd.add_line(f"{parsed.from_name} 请求添加你为好友")
    if parsed.pending is not None:
        st.notify.set_friend_requests(parsed.pending)
    elif parsed.from_name:
        st.notify.add_friend_request(parsed.from_name)
    screen.update_badges()


def _on_profile_card(parsed, app, screen, st):
    st.online.set_viewed_card(parsed.data)


def _on_game_list(parsed, app, screen, st):
    st.game_board.set_games(parsed.games)


def _on_room_list(parsed, app, screen, st):
    st.game_board.set_rooms(parsed.rooms)


def _on_game_invite(parsed, app, screen, st):
    inv = parsed.raw
    from_name = inv.get('from', '?')
    game = inv.get('game', '?')
    room_id = inv.get('room_id', '')
    expires_in = inv.get('expires_in', 300)
    st.notify.add_game_invite(from_name, game, room_id, expires_in)
    screen.update_badges()


def _on_game_invite_result(parsed, app, screen, st):
    st.notify.mark_game_invite(parsed.from_name, parsed.game, parsed.status)
    screen.update_badges()


def _on_room_update(parsed, app, screen, st):
    if parsed.room_data:
        rd = parsed.room_data
        # 帮助文档 → 路由到对应面板（游戏中→棋盘，等候室→聊天）
        if 'doc' in rd:
            game_type = rd.get('game_type', '')
            from ..protocol.renderer import get_renderer, render_doc
            renderer = get_renderer(game_type) if game_type else None
            if renderer and hasattr(renderer, 'render_doc'):
                doc_renderable = renderer.render_doc(rd['doc'])
            else:
                commands = getattr(renderer, 'doc_commands', None) if renderer else None
                doc_renderable = render_doc(rd['doc'], commands)
            shown = False
            # 优先尝试当前可见窗口中的面板
            rs = rd.get('room_state', '')
            if rs == 'waiting':
                try:
                    chat = screen.query_one('#wait-chat')
                    chat.show_doc(doc_renderable)
                    shown = True
                except Exception:
                    pass
            if not shown:
                try:
                    board = screen.query_one('#game-board')
                    if hasattr(board, 'show_doc'):
                        board.show_doc(doc_renderable)
                        shown = True
                except Exception:
                    pass
            if not shown:
                try:
                    chat = screen.query_one('#wait-chat')
                    chat.show_doc(doc_renderable)
                except Exception:
                    pass
            # 含 room_state 时仍需更新状态以触发窗口切换
            if rd.get('room_state'):
                st.game_board.update_room(rd)
            if parsed.message:
                st.cmd.add_line(parsed.message)
            return
        # 正常 room_update：如果面板在显示帮助，关闭
        try:
            board = screen.query_one('#game-board')
            if hasattr(board, '_showing_doc') and board._showing_doc:
                board.close_doc()
        except Exception:
            pass
        try:
            chat = screen.query_one('#wait-chat')
            if hasattr(chat, '_showing_doc') and chat._showing_doc:
                chat.close_doc()
        except Exception:
            pass
        # 先通知 handler 构建交互态，再更新 State 触发渲染
        game_type = rd.get('game_type', '')
        handler = get_handler(game_type) if game_type else None
        if handler and hasattr(handler, 'on_room_update'):
            ctx = _make_handler_ctx(st, app, screen)
            handler.on_room_update(rd, ctx)
        st.game_board.update_room(rd)
        tile_name = rd.get('tile_name', '')
        try:
            indicator = screen.query_one('#tile-indicator')
            indicator.update(f" {tile_name} " if tile_name else '')
        except Exception:
            pass
    if parsed.message:
        st.cmd.add_line(parsed.message)


def _on_room_leave(parsed, app, screen, st):
    st.game_board.clear()
    if parsed.location:
        if hasattr(parsed, 'commands') and parsed.commands:
            from ..protocol.commands import set_commands
            set_commands(parsed.commands)
            screen._update_hint_bar()
        path = getattr(parsed, 'location_path', None)
        screen._update_location(parsed.location, path)


def _on_location_update(parsed, app, screen, st):
    from ..protocol.commands import set_commands
    set_commands(parsed.commands)
    screen._update_hint_bar()
    screen._update_location(parsed.location, parsed.location_path)
    if screen.logged_in:
        screen.call_later(screen._rebuild_to_game_layout)


def _on_commands_update(parsed, app, screen, st):
    from ..protocol.commands import set_commands
    set_commands(parsed.commands)
    screen._update_hint_bar()


def _on_game_event(parsed, app, screen, st):
    handler = get_handler(parsed.game_type)
    if handler:
        ctx = _make_handler_ctx(st, app, screen)
        handler.handle_event(parsed.event, parsed.data, ctx)


def _on_action_command(parsed, app, screen, st):
    action = parsed.action
    if action == "clear":
        st.cmd.clear()
    elif action == "version":
        sv = parsed.raw.get("server_version", "未知")
        try:
            from ..config import VERSION
        except ImportError:
            VERSION = None
        cv = VERSION or "开发版"
        ver_text = f"版本信息\n客户端: v{cv}\n服务器: v{sv}"
        st.cmd.add_line(ver_text)
    elif action == "exit":
        from .. import ime
        ime.on_app_blur()
        app.network.disconnect()
        app.exit()
    elif action == "return_to_login":
        screen.logged_in = False
        screen.call_later(screen._rebuild_to_login_layout)
    elif action == "maintenance":
        from ..config import M_BOLD, M_END
        maint_text = f"{M_BOLD}系统维护{M_END}: 服务器正在维护，请稍后重连。"
        st.cmd.add_line(maint_text)
        from .. import ime
        ime.on_app_blur()
        app.network.disconnect()


# ── 路由表 ──

_DISPATCH = {
    LoginPrompt: _on_login_prompt,
    LoginSuccess: _on_login_success,
    SystemMessage: _on_system_message,
    GameMessage: _on_game_message,
    ChatMessage: _on_chat_message,
    ChatHistory: _on_chat_history,
    StatusUpdate: _on_status_update,
    OnlineUsers: _on_online_users,
    FriendList: _on_friend_list,
    AllUsers: _on_all_users,
    PrivateChat: _on_private_chat,
    DMHistory: _on_dm_history,
    FriendRequest: _on_friend_request,
    ProfileCard: _on_profile_card,
    GameList: _on_game_list,
    RoomList: _on_room_list,
    GameInvite: _on_game_invite,
    GameInviteResult: _on_game_invite_result,
    RoomUpdate: _on_room_update,
    RoomLeave: _on_room_leave,
    GameQuit: _on_room_leave,
    LocationUpdate: _on_location_update,
    CommandsUpdate: _on_commands_update,
    GameEvent: _on_game_event,
    ActionCommand: _on_action_command,
    RoomChat: _on_room_chat,
}
