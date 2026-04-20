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


def _on_location_update(parsed, app, screen, st):
    from ...protocol.commands import set_commands
    set_commands(parsed.commands)
    screen._update_hint_bar()
    screen._update_location(parsed.location, parsed.location_path)
    if screen.logged_in:
        screen.call_later(screen._rebuild_to_game_layout)


def _on_commands_update(parsed, app, screen, st):
    from ...protocol.commands import set_commands
    set_commands(parsed.commands)
    screen._update_hint_bar()


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
        screen.call_later(screen._rebuild_to_login_layout)
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
