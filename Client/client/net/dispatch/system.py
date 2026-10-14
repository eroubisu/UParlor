"""系统消息分发 — 状态更新、位置、指令、动作"""

from __future__ import annotations

from ..messages import (
    SystemMessage, GameMessage, StatusUpdate,
    LocationUpdate, CommandsUpdate, ActionCommand,
)


def _on_system_message(parsed, app, screen, st):
    st.cmd.add_line(parsed.text)
    if parsed.broadcast:
        st.notify.add_system_notification(parsed.text)
        from ...companion import CompanionController
        CompanionController.instance(st).observe_event(
            "收到一条系统通知")
        screen.update_badges()


def _on_game_message(parsed, app, screen, st):
    st.cmd.add_line(parsed.text, update_last=parsed.update_last)


def _on_status_update(parsed, app, screen, st):
    if parsed.location:
        st.status.update_location(parsed.location)
    if parsed.location_path:
        st.status.update_location_path(parsed.location_path)
    player_name = parsed.data.get('name', '')
    if player_name:
        st.chat.set_player_name(player_name)
        style_data = parsed.data.get('chat_style', {})
        config = style_data.get('config', {})
        title_id = config.get('title_id', '')
        title = next((
            item.get('label', '')
            for item in style_data.get('titles', [])
            if item.get('id') == title_id
        ), '')
        st.chat.update_sender({
            'name': player_name,
            'title': title,
            'level': parsed.data.get('level', 1),
            'style': style_data.get('resolved', {}),
        })
        from ...companion import CompanionController
        controller = CompanionController.instance(st)
        controller.set_on_proactive(
            lambda text, revision: app.call_from_thread(
                controller.deliver_proactive,
                text,
                revision,
                screen.receive_companion_message,
            ))
        controller.set_player(player_name)
    st.status.update_player_info(parsed.data)


def _on_location_update(parsed, app, screen, st):
    from ...protocol.commands import set_commands
    set_commands(parsed.commands)
    screen._update_room_controls()
    screen._update_location(parsed.location, parsed.location_path)
    if screen.logged_in:
        screen.call_later(screen._rebuild_to_game_layout)


def _on_commands_update(parsed, app, screen, st):
    from ...protocol.commands import set_commands
    set_commands(parsed.commands)
    screen._update_room_controls()


def _on_action_command(parsed, app, screen, st):
    action = parsed.action
    if action == "clear":
        st.cmd.clear()
    elif action == "version":
        sv = parsed.raw.get("server_version", "未知")
        try:
            from ...config import VERSION
        except ImportError:
            VERSION = None
        cv = VERSION or "开发版"
        ver_text = f"版本信息\n客户端: v{cv}\n服务器: v{sv}"
        st.cmd.add_line(ver_text)
    elif action == "exit":
        from ... import ime
        ime.on_app_blur()
        app.network.disconnect()
        app.exit()
    elif action == "return_to_login":
        screen.logged_in = False
        from ...companion import CompanionController
        if CompanionController._instance is not None:
            CompanionController._instance.clear_session()
        screen.call_later(screen._rebuild_to_login_layout)
    elif action == "session_offline":
        from ...companion import CompanionController
        from ...views.session_offline import SessionOfflineDialog

        screen.logged_in = False
        if screen._mode != "normal":
            screen._to_normal()
        if CompanionController._instance is not None:
            CompanionController._instance.clear_session()
        def handle_choice(choice: str | None) -> None:
            if choice == "login":
                screen.call_later(screen._rebuild_to_login_layout)
            elif choice == "exit":
                from ... import ime
                ime.on_app_blur()
                app.network.disconnect()
                app.exit()

        screen.engine.open_modal(SessionOfflineDialog(), handle_choice)
    elif action == "maintenance":
        from ...config import M_BOLD, M_END
        maint_text = f"{M_BOLD}系统维护{M_END}: 服务器正在维护，请稍后重连。"
        st.cmd.add_line(maint_text)
        from ... import ime
        ime.on_app_blur()
        app.network.disconnect()


HANDLERS = {
    SystemMessage: _on_system_message,
    GameMessage: _on_game_message,
    StatusUpdate: _on_status_update,
    LocationUpdate: _on_location_update,
    CommandsUpdate: _on_commands_update,
    ActionCommand: _on_action_command,
}
