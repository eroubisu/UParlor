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
    CommandsUpdate, GameEvent, ActionCommand, AISyncDown,
    FriendList, AllUsers, PrivateChat, FriendRequest, DMHistory,
    ProfileCard,
)
import re as _re

from ..protocol.handler import GameHandlerContext, get_handler

def _strip_markup(text: str) -> str:
    """去除 Rich markup 标签，返回纯文本"""
    return _re.sub(r'\[/?[^\]]*\]', '', text)

def _is_ai_chatting(panel) -> bool:
    """AI 面板是否处于聊天视图（仅此时算"已启动"）"""
    return (
        getattr(panel, '_panel_active', False)
        and panel._service
        and getattr(panel, '_view', '') == 'chat'
    )


def _push_ai_event(screen, event: str, *, high_priority: bool = False):
    """如果 AI 面板处于聊天视图，推送事件

    high_priority=True : AttentionBuffer + event_queue（感知 + 主动搭话）
    high_priority=False : AttentionBuffer only（被动感知，不触发搭话）
    """
    try:
        panel = screen.get_module('ai')
        if panel and _is_ai_chatting(panel):
            svc = panel._service
            svc._attention.push(event)
            if high_priority:
                svc.push_event(event)
    except Exception:
        pass


def _get_ai_attention_level(screen) -> str:
    """获取 AI 当前的 attention_level（quiet/normal/talkative）"""
    try:
        panel = screen.get_module('ai')
        if panel and _is_ai_chatting(panel):
            return panel._service.attention_level
    except Exception:
        pass
    return "quiet"


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
        from ..config import VERSION, M_DIM, M_END
        current = VERSION or "0.0.0"
        cur = tuple(int(x) for x in current.split("."))
        lat = tuple(int(x) for x in latest.split("."))
        if lat > cur:
            login = screen.get_module('login')
            msg = f"{M_DIM}发现新版本 v{latest}（当前 v{current}），请更新: pip install --upgrade uparlor{M_END}"
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
    screen.call_later(screen._rebuild_to_game_layout)


def _on_system_message(parsed, app, screen, st):
    st.cmd.add_line(parsed.text)
    if parsed.broadcast:
        st.notify.add_system_notification(parsed.text)
        screen.update_badges()


def _on_game_message(parsed, app, screen, st):
    st.cmd.add_line(parsed.text, update_last=parsed.update_last)
    plain = _strip_markup(parsed.text).strip()
    if plain:
        if parsed.update_last and st.game_board.recent_events:
            st.game_board.recent_events[-1] = plain
        else:
            st.game_board.push_event(plain)


def _on_chat_message(parsed, app, screen, st):
    st.chat.add_message(parsed.name, parsed.text, parsed.channel, parsed.time)


def _on_chat_history(parsed, app, screen, st):
    st.chat.set_history(parsed.messages, parsed.channel)


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
    st.inventory.update_inventory(parsed.data)


def _on_online_users(parsed, app, screen, st):
    st.online.update_users(parsed.users)
    st.chat.update_online_count(parsed.users)


def _on_friend_list(parsed, app, screen, st):
    old_friends = set(st.online.friends)
    st.online.update_friends(parsed.friends)
    new_friends = set(parsed.friends)
    if old_friends and new_friends != old_friends:
        added = new_friends - old_friends
        removed = old_friends - new_friends
        for name in added:
            st.cmd.add_line(f"{name} 已成为你的好友")
            _push_ai_event(screen, f"新好友: {name}", high_priority=False)
        for name in removed:
            st.cmd.add_line(f"{name} 已不再是你的好友")
            _push_ai_event(screen, f"好友删除: {name}", high_priority=False)
    screen.update_badges()


def _on_all_users(parsed, app, screen, st):
    st.online.update_all_users(parsed.users)


def _on_private_chat(parsed, app, screen, st):
    st.chat.add_private_message(
        parsed.from_name, parsed.to_name, parsed.text, parsed.time)
    screen.update_badges()
    my_name = st.chat._my_name
    if parsed.from_name and parsed.from_name != my_name:
        level = _get_ai_attention_level(screen)
        if level == 'talkative':
            _push_ai_event(screen, f"收到{parsed.from_name}的私信", high_priority=True)
        elif level == 'normal':
            _push_ai_event(screen, f"收到{parsed.from_name}的私信", high_priority=False)


def _on_dm_history(parsed, app, screen, st):
    st.chat.set_dm_history(parsed.conversations)
    screen.update_badges()


def _on_friend_request(parsed, app, screen, st):
    if parsed.from_name:
        st.cmd.add_line(f"{parsed.from_name} 请求添加你为好友")
        _push_ai_event(screen, f"{parsed.from_name}想加你为好友", high_priority=True)
    if parsed.pending is not None:
        st.notify.set_friend_requests(parsed.pending)
    elif parsed.from_name:
        st.notify.add_friend_request(parsed.from_name)
    screen.update_badges()


def _on_profile_card(parsed, app, screen, st):
    st.online.set_viewed_card(parsed.data)


def _on_game_invite(parsed, app, screen, st):
    inv = parsed.raw
    from_name = inv.get('from', '?')
    game = inv.get('game', '?')
    room_id = inv.get('room_id', '')
    expires_in = inv.get('expires_in', 300)
    st.notify.add_game_invite(from_name, game, room_id, expires_in)
    _push_ai_event(screen, f"{from_name}邀请你玩{game}", high_priority=True)
    screen.update_badges()


def _on_game_invite_result(parsed, app, screen, st):
    st.notify.mark_game_invite(parsed.from_name, parsed.game, parsed.status)
    screen.update_badges()


def _on_room_update(parsed, app, screen, st):
    if parsed.room_data:
        st.game_board.update_room(parsed.room_data)
        rd = parsed.room_data
        ai_desc = rd.get('ai_description')
        if ai_desc:
            st.game_board.push_event(str(ai_desc))
        priority = rd.get('ai_priority')
        if priority:
            game = rd.get('game_type') or rd.get('game', '')
            room_state = rd.get('state') or rd.get('status', '')
            desc = ai_desc or f"{game} {room_state}".strip()
            _push_ai_event(screen, f"房间更新: {desc}", high_priority=(priority == 'high'))
        # 游戏结束时主动通知 AI 旅伴
        elif rd.get('room_state') == 'finished':
            game = rd.get('game_type', '')
            handler = get_handler(game)
            if handler and hasattr(handler, 'ai_describe'):
                desc = handler.ai_describe(rd)
            else:
                desc = f'{game} 游戏结束'
            st.game_board.push_event(desc)
            _push_ai_event(screen, desc, high_priority=True)
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
    _push_ai_event(screen, "玩家离开了游戏房间", high_priority=True)


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
        ctx = GameHandlerContext(
            state=st,
            get_module=screen.get_module,
            set_timer=app.set_timer,
            ensure_panel=screen._ensure_module_panel,
            remove_panel=screen._remove_module_panel,
            send_command=app.send_command,
        )
        handler.handle_event(parsed.event, parsed.data, ctx)
    d = parsed.data or {}
    ai_desc = d.get('ai_description')
    if ai_desc:
        st.game_board.push_event(str(ai_desc))
    priority = d.get('ai_priority')
    if priority in ('high', 'normal'):
        desc = ai_desc or parsed.event
        _push_ai_event(screen, f"游戏事件: {desc}", high_priority=(priority == 'high'))


def _on_ai_sync_down(parsed, app, screen, st):
    from ..ai.config import import_all_chars, save_stats, load_stats
    import_all_chars(parsed.companions)
    if parsed.token_stats:
        local = load_stats()
        remote = parsed.token_stats
        if remote.get('today') == local.get('today', ''):
            r_models = remote.get('models', {})
            l_models = local.get('models', {})
            merged = {}
            for k in set(r_models) | set(l_models):
                merged[k] = max(r_models.get(k, 0), l_models.get(k, 0))
            remote['models'] = merged
        save_stats(remote)


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
        from ..ui import ime
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
        from ..ui import ime
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
    GameInvite: _on_game_invite,
    GameInviteResult: _on_game_invite_result,
    RoomUpdate: _on_room_update,
    RoomLeave: _on_room_leave,
    GameQuit: _on_room_leave,
    LocationUpdate: _on_location_update,
    CommandsUpdate: _on_commands_update,
    GameEvent: _on_game_event,
    AISyncDown: _on_ai_sync_down,
    ActionCommand: _on_action_command,
}
