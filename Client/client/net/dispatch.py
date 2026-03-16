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
    StatusUpdate, OnlineUsers, GameInvite,
    RoomUpdate, RoomLeave, GameQuit, LocationUpdate,
    CommandsUpdate, GameEvent, ActionCommand, AISyncDown,
    FriendList, AllUsers, PrivateChat, FriendRequest, DMHistory,
)
from ..protocol.handler import GameHandlerContext, get_handler
from ..panels import LoginPanel


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
        panel = screen._get_module('ai')
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
        panel = screen._get_module('ai')
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
    parsed = parse_server_message(raw)
    st = screen.state

    if isinstance(parsed, LoginPrompt):
        login = screen._get_module('login')
        if isinstance(login, LoginPanel):
            login.add_message(parsed.text)
        else:
            st.cmd.add_line(parsed.text)

    elif isinstance(parsed, LoginSuccess):
        screen.logged_in = True
        st.cmd.add_line(parsed.text)
        screen.call_later(screen._rebuild_to_game_layout)

    elif isinstance(parsed, SystemMessage):
        st.chat.add_system_message(parsed.text)

    elif isinstance(parsed, GameMessage):
        st.cmd.add_line(parsed.text, update_last=parsed.update_last)

    elif isinstance(parsed, ChatMessage):
        st.chat.add_message(parsed.name, parsed.text, parsed.channel, parsed.time)

    elif isinstance(parsed, ChatHistory):
        st.chat.set_history(parsed.messages, parsed.channel)

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
        # 记录玩家名用于私聊
        player_name = parsed.data.get('name', '')
        if player_name:
            st.chat.set_player_name(player_name)
        st.status.update_player_info(parsed.data)
        st.inventory.update_inventory(parsed.data)

    elif isinstance(parsed, OnlineUsers):
        st.online.update_users(parsed.users)
        st.chat.update_online_count(parsed.users)

    elif isinstance(parsed, FriendList):
        old_friends = set(st.online.friends)
        st.online.update_friends(parsed.friends)
        new_friends = set(parsed.friends)
        # 好友列表变化时推送被动感知
        if old_friends and new_friends != old_friends:
            added = new_friends - old_friends
            removed = old_friends - new_friends
            if added:
                _push_ai_event(screen, f"新好友: {', '.join(added)}", high_priority=False)
            if removed:
                _push_ai_event(screen, f"好友删除: {', '.join(removed)}", high_priority=False)

    elif isinstance(parsed, AllUsers):
        st.online.update_all_users(parsed.users)

    elif isinstance(parsed, PrivateChat):
        st.chat.add_private_message(
            parsed.from_name, parsed.to_name, parsed.text, parsed.time)
        # 私聊消息推送给 AI（仅对方发来的，排除自己的回显）
        my_name = st.chat._my_name
        if parsed.from_name and parsed.from_name != my_name:
            level = _get_ai_attention_level(screen)
            if level == 'talkative':
                _push_ai_event(screen, f"收到{parsed.from_name}的私信", high_priority=True)
            elif level == 'normal':
                _push_ai_event(screen, f"收到{parsed.from_name}的私信", high_priority=False)

    elif isinstance(parsed, DMHistory):
        st.chat.set_dm_history(parsed.conversations)

    elif isinstance(parsed, FriendRequest):
        # 服务端推送待处理好友申请列表
        if parsed.pending:
            st.notify.set_friend_requests(parsed.pending)
        elif parsed.from_name:
            st.notify.add_friend_request(parsed.from_name)
            # 好友申请是重要社交事件，始终推送给 AI
            _push_ai_event(screen, f"{parsed.from_name}想加你为好友", high_priority=True)

    elif isinstance(parsed, GameInvite):
        inv = parsed.raw
        from ..config import M_BOLD, M_END
        invite_text = f"{M_BOLD}游戏邀请{M_END}: {inv.get('from', '?')} 邀请你加入 {inv.get('game', '?')}"
        st.cmd.add_line(invite_text)
        _push_ai_event(screen, f"{inv.get('from', '?')}邀请你玩{inv.get('game', '?')}", high_priority=True)

    elif isinstance(parsed, RoomUpdate):
        if parsed.room_data:
            st.game_board.update_room(parsed.room_data)
            # 缓存带 ai_description 的房间更新
            rd = parsed.room_data
            ai_desc = rd.get('ai_description')
            if ai_desc:
                st.game_board.push_event(str(ai_desc))
            # 推送房间状态变化给 AI（opt-in: room_data 需声明 ai_priority）
            priority = rd.get('ai_priority')
            if priority:
                game = rd.get('game_type') or rd.get('game', '')
                room_state = rd.get('state') or rd.get('status', '')
                desc = ai_desc or f"{game} {room_state}".strip()
                _push_ai_event(screen, f"房间更新: {desc}", high_priority=(priority == 'high'))
        if parsed.message:
            st.cmd.add_line(parsed.message)

    elif isinstance(parsed, (RoomLeave, GameQuit)):
        st.game_board.clear()
        if parsed.location:
            if hasattr(parsed, 'commands') and parsed.commands:
                from ..protocol.commands import set_commands
                set_commands(parsed.commands)
                screen._update_hint_bar()
            path = getattr(parsed, 'location_path', None)
            screen._update_location(parsed.location, path)
        _push_ai_event(screen, "玩家离开了游戏房间", high_priority=True)

    elif isinstance(parsed, LocationUpdate):
        from ..protocol.commands import set_commands
        set_commands(parsed.commands)
        screen._update_hint_bar()
        screen._update_location(parsed.location, parsed.location_path)
        if screen.logged_in:
            screen.call_later(screen._rebuild_to_game_layout)

    elif isinstance(parsed, CommandsUpdate):
        from ..protocol.commands import set_commands
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
        # 缓存带 ai_description 的游戏事件
        d = parsed.data or {}
        ai_desc = d.get('ai_description')
        if ai_desc:
            st.game_board.push_event(str(ai_desc))
        # 推送游戏事件给 AI（opt-in: data 需声明 ai_priority）
        priority = d.get('ai_priority')
        if priority in ('high', 'normal'):
            desc = ai_desc or parsed.event
            _push_ai_event(screen, f"游戏事件: {desc}", high_priority=(priority == 'high'))

    elif isinstance(parsed, AISyncDown):
        from ..ai.config import import_all_chars, save_stats, load_stats
        import_all_chars(parsed.companions)
        if parsed.token_stats:
            local = load_stats()
            remote = parsed.token_stats
            if remote.get('today') == local.get('today', ''):
                remote['tokens'] = max(
                    remote.get('tokens', 0),
                    local.get('tokens', 0),
                )
            save_stats(remote)

    elif isinstance(parsed, ActionCommand):
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
        elif action == "maintenance":
            from ..config import M_BOLD, M_END
            maint_text = f"{M_BOLD}系统维护{M_END}: 服务器正在维护，请稍后重连。"
            st.cmd.add_line(maint_text)
            from ..ui import ime
            ime.on_app_blur()
            app.network.disconnect()
