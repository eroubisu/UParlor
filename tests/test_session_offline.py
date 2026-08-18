"""Displaced-account modal behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from textual.app import App
from textual.app import ComposeResult
from textual.widgets import Input

from client.net.dispatch.system import _on_action_command
from client.net.messages import ActionCommand
from client.config import COLOR_FG_SECONDARY
from client.views.login import LoginPanel, LoginWindow
from client.views.session_offline import SessionOfflineDialog
from client.window_engine import InputSession, InputSpec, Option, SelectList


def test_session_offline_dialog_mounts_with_expected_content():
    async def verify() -> None:
        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(SessionOfflineDialog())
            await pilot.pause()
            content = str(app.screen.query_one(
                "#session-offline-dialog").render())

            assert "账号已下线" in content
            assert "返回登录界面" in content
            assert "退出客户端" in content

    asyncio.run(verify())


def test_session_offline_dialog_uses_existing_monochrome_style():
    assert "$accent" not in SessionOfflineDialog.DEFAULT_CSS
    assert (
        f"border: round {COLOR_FG_SECONDARY}"
        in SessionOfflineDialog.DEFAULT_CSS
    )
    assert "background: transparent" in SessionOfflineDialog.DEFAULT_CSS


def test_session_offline_dialog_navigation():
    dialog = object.__new__(SessionOfflineDialog)
    dialog.selection = SelectList((
        Option("login", "返回登录界面"),
        Option("exit", "退出客户端"),
    ), "session-offline")
    dialog.query_one = Mock()
    dialog.dismiss = Mock()

    SessionOfflineDialog.nav(dialog, "down")
    SessionOfflineDialog.nav(dialog, "enter")

    assert dialog.selection.index == 1
    dialog.dismiss.assert_called_once_with("exit")


def test_login_window_reset_restores_visible_username_form():
    class LoginApp(App):
        def compose(self) -> ComposeResult:
            yield LoginWindow(id="login-window")

        def on_mount(self) -> None:
            self.query_one("#login-window", LoginWindow).show()

    async def verify() -> None:
        app = LoginApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#login-panel", LoginPanel)
            input_widget = panel.query_one("#input", Input)
            input_row = panel.query_one("#input-row")
            input_divider = panel.query_one("#input-divider")
            content = panel.query_one("#t0")

            assert input_row.region.height == 1
            assert input_divider.region.y == input_row.region.y + 1
            assert content.region.y == input_divider.region.y + 1

            panel._tab = "login"
            panel._step = "waiting"
            panel._submitted = True
            input_widget.disabled = True
            input_widget.placeholder = "请稍候..."
            input_widget.password = True

            app.query_one("#login-window", LoginWindow).reset_session()
            await pilot.pause()

            assert panel._step == "username"
            assert panel._submitted is False
            assert input_widget.disabled is True
            assert input_widget.placeholder == "请输入用户名"
            assert input_widget.password is False

    asyncio.run(verify())


def test_shared_input_keeps_long_unicode_cursor_visible():
    class LoginApp(App):
        def compose(self) -> ComposeResult:
            yield LoginWindow(id="login-window")

        def on_mount(self) -> None:
            self.query_one("#login-window", LoginWindow).show()

    async def verify() -> None:
        app = LoginApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#login-panel", LoginPanel)
            assert panel.enter_insert()
            input_widget = panel.query_one("#input", Input)

            await pilot.press(*("a中文输入跟随光标" * 8))
            await pilot.pause()

            cursor = input_widget.cursor_screen_offset.x
            region = input_widget.content_region
            visible = "".join(
                segment.text for segment in input_widget.render_line(0)._segments)
            boundaries = {0}
            offset = 0
            from client.window_engine.text import cell_width, grapheme_clusters
            for cluster in grapheme_clusters(input_widget.value):
                offset += cell_width(cluster)
                boundaries.add(offset)
            assert input_widget.scroll_offset.x > 0
            assert input_widget.scroll_offset.x in boundaries
            assert region.x <= cursor < region.right
            assert any(char in visible for char in "中文")
            assert not input_widget.show_horizontal_scrollbar

    asyncio.run(verify())


def test_wrong_password_changes_password_placeholder():
    class _Input:
        placeholder = "请稍候..."
        password = True
        value = ""
        disabled = True

        def focus(self):
            pass

    input_widget = _Input()
    panel = object.__new__(LoginPanel)
    panel._step = "waiting"
    panel._waiting_for = "password"
    panel._tab = "login"
    panel._auth_state = None
    panel._submitted = True
    panel.update = Mock()
    panel.input_session = InputSession(InputSpec(password=True))
    panel.input_session.mount(input_widget)
    panel.activate_input_context = lambda: panel.input_session.replace(
        LoginPanel.input_spec(panel))

    LoginPanel.add_message(panel, "密码错误，请重试")

    assert panel._step == "password"
    assert panel._submitted is False
    assert input_widget.placeholder == "密码错误，请重试"
    assert input_widget.password is True


def test_password_step_can_request_return_to_username():
    class LoginApp(App):
        def __init__(self) -> None:
            super().__init__()
            self.sent = []
            self.network = SimpleNamespace(
                send=lambda message: self.sent.append(message) or True,
            )

        def compose(self) -> ComposeResult:
            yield LoginWindow(id="login-window")

        def on_mount(self) -> None:
            self.query_one("#login-window", LoginWindow).show()

    async def verify() -> None:
        app = LoginApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#login-panel", LoginPanel)
            panel.add_message("请输入用户名：")
            await pilot.pause()
            content = str(panel.query_one("#t0 .content").render())
            assert "请输入用户名" not in content

            panel._step = "waiting"
            panel._waiting_for = "password"
            panel.add_message("密码错误，请重试")
            await pilot.pause()
            content = str(panel.query_one("#t0 .content").render())
            input_widget = panel.query_one("#input", Input)
            assert "密码错误，请重试" not in content
            assert input_widget.placeholder == "密码错误，请重试"
            panel._step = "password"
            panel._waiting_for = ""
            panel._submitted = False

            assert panel.return_to_username()
            assert app.sent == [{"type": "auth_cancel"}]
            assert panel._step == "waiting"
            assert panel._submitted is True

            app.sent.clear()
            panel._step = "password"
            panel._waiting_for = ""
            panel._submitted = False
            panel.nav("tab_prev")
            assert panel._tab == "settings"
            assert app.sent == [{"type": "auth_cancel"}]

    asyncio.run(verify())


def test_sticky_insert_continues_from_username_to_password():
    class LoginApp(App):
        def compose(self) -> ComposeResult:
            yield LoginWindow(id="login-window")

        def on_mount(self) -> None:
            self.query_one("#login-window", LoginWindow).show()

    async def verify() -> None:
        app = LoginApp()
        async with app.run_test() as pilot:
            panel = app.query_one("#login-panel", LoginPanel)
            input_widget = panel.query_one("#input", Input)
            assert panel.enter_insert(sticky=True)

            panel._submitted = True
            panel._step = "waiting"
            panel.activate_input_context()
            assert input_widget.disabled

            panel.add_message("请输入密码：")
            await pilot.pause()

            assert panel.input_session.editing
            assert panel.input_session.sticky
            assert not input_widget.disabled
            assert input_widget.password
            assert input_widget.has_focus

    asyncio.run(verify())


def test_session_offline_action_waits_for_explicit_choice():
    pushed = []
    network = SimpleNamespace(disconnect=Mock())
    rebuild = Mock()
    app = SimpleNamespace(
        network=network,
        exit=Mock(),
        push_screen=lambda dialog, callback: pushed.append((dialog, callback)),
    )
    screen = SimpleNamespace(
        logged_in=True,
        _mode="insert",
        _to_normal=Mock(),
        call_later=Mock(),
        _rebuild_to_login_layout=rebuild,
        engine=SimpleNamespace(
            open_modal=lambda dialog, callback: pushed.append(
                (dialog, callback)),
        ),
    )

    _on_action_command(
        ActionCommand(action="session_offline"),
        app,
        screen,
        SimpleNamespace(),
    )

    assert screen.logged_in is False
    screen._to_normal.assert_called_once()
    assert isinstance(pushed[0][0], SessionOfflineDialog)
    screen.call_later.assert_not_called()
    network.disconnect.assert_not_called()

    pushed[0][1]("login")
    screen.call_later.assert_called_once_with(rebuild)


def test_session_offline_exit_uses_normal_shutdown(monkeypatch):
    pushed = []
    network = SimpleNamespace(disconnect=Mock())
    app = SimpleNamespace(
        network=network,
        exit=Mock(),
        push_screen=lambda dialog, callback: pushed.append((dialog, callback)),
    )
    screen = SimpleNamespace(
        logged_in=True,
        _mode="normal",
        _to_normal=Mock(),
        engine=SimpleNamespace(
            open_modal=lambda dialog, callback: pushed.append(
                (dialog, callback)),
        ),
    )
    ime_blur = Mock()
    monkeypatch.setattr("client.ime.on_app_blur", ime_blur)

    _on_action_command(
        ActionCommand(action="session_offline"),
        app,
        screen,
        SimpleNamespace(),
    )
    pushed[0][1]("exit")

    ime_blur.assert_called_once()
    network.disconnect.assert_called_once()
    app.exit.assert_called_once()
    screen._to_normal.assert_not_called()
