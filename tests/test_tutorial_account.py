"""教程跟账号走：登录后按账号决定弹不弹；只有最后一页选了"不再显示"才记在服务器上。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from client.net.dispatch.auth import _on_login_success
from client.net.messages import LoginSuccess, parse_server_message
from client.screen_nav import NavigationMixin
from client.views.system.tutorial import TutorialPanel
from server.handlers import client_state
from server.player.auth import AuthMixin
from server.player.manager import PlayerManager


# ── 服务端 ──


def test_login_success_tells_the_client_whether_the_account_dismissed_the_tutorial():
    sent = []
    host = Mock()
    host.send_to = lambda sock, msg: sent.append(msg)

    for data, expected in (({}, False), ({'tutorial_done': True}, True)):
        sent.clear()
        AuthMixin._on_login_success(host, object(), 'alice', data, '登录成功！', 'x')
        first = sent[0]
        assert first['type'] == 'login_success'
        assert first['tutorial_done'] is expected


def test_tutorial_done_message_is_stored_on_the_account(monkeypatch):
    save = Mock()
    monkeypatch.setattr(PlayerManager, 'save_player_data', save)
    data = {}

    client_state.handle_tutorial_done(Mock(), object(), 'alice', data, {})

    assert data['tutorial_done'] is True
    save.assert_called_once_with('alice', data)


# ── 客户端 ──


def test_the_client_parses_the_accounts_tutorial_flag():
    assert parse_server_message({'type': 'login_success', 'text': 'x'}) == LoginSuccess('x', False)
    assert parse_server_message({'type': 'login_success', 'text': 'x',
                          'tutorial_done': True}) == LoginSuccess('x', True)


def _screen():
    return SimpleNamespace(call_later=Mock(), _rebuild_to_game_layout=object(),
                           _open_tutorial=object(), logged_in=False)


def test_login_opens_the_tutorial_for_accounts_that_have_not_dismissed_it():
    screen = _screen()

    _on_login_success(LoginSuccess('ok', tutorial_done=False), None, screen,
                      SimpleNamespace(auth=Mock(), cmd=Mock()))

    calls = [call.args[0] for call in screen.call_later.call_args_list]
    assert calls == [screen._rebuild_to_game_layout, screen._open_tutorial]


def test_login_does_not_open_the_tutorial_for_accounts_that_dismissed_it():
    screen = _screen()

    _on_login_success(LoginSuccess('ok', tutorial_done=True), None, screen,
                      SimpleNamespace(auth=Mock(), cmd=Mock()))

    calls = [call.args[0] for call in screen.call_later.call_args_list]
    assert calls == [screen._rebuild_to_game_layout]


class _Host(NavigationMixin):
    def __init__(self, mode, primary):
        self.mode = mode
        self.logged_in = mode != 'login'
        self.engine = SimpleNamespace(_primary_id=primary,
                                      target_primary_id=lambda: self.primary,
                                      set_primary=self._set_primary)
        self.primary = primary
        self.app = SimpleNamespace(network=SimpleNamespace(send=Mock()))

    def _set_primary(self, window_id):
        self.primary = window_id
        self.engine._primary_id = window_id


def test_finishing_the_tutorial_restores_the_previous_window_and_mode():
    host = _Host('game', 'lobby-window')
    host._open_tutorial()
    assert (host.primary, host.mode) == ('tutorial-window', 'tutorial')

    host._finish_tutorial()

    assert (host.primary, host.mode) == ('lobby-window', 'game')


def test_only_a_remembered_tutorial_exit_tells_the_server():
    for remember, expected in ((False, 0), (True, 1)):
        host = _Host('game', 'lobby-window')
        host._open_tutorial()

        host.on_tutorial_panel_tutorial_done(TutorialPanel.TutorialDone(remember))

        assert host.app.network.send.call_count == expected
        if remember:
            host.app.network.send.assert_called_once_with({"type": "tutorial_done"})


def test_the_tutorial_is_no_longer_remembered_per_device():
    from client import storage

    assert not hasattr(storage, 'get_tutorial_done')
    assert not hasattr(storage, 'set_tutorial_done')


# ── 真实的游戏屏幕走一遍 ──


def _login_flow(tutorial_done: bool, remember: bool):
    import asyncio

    from client.app import UParlorApp
    from client.net.dispatch import dispatch_server_message
    from client.views.system import tutorial

    result = {}

    async def run():
        sent = []
        with __import__("unittest.mock").mock.patch.object(
                UParlorApp, "connect_to_server", lambda self, host: None):
            app = UParlorApp()
            async with app.run_test(size=(100, 36)) as pilot:
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                app.network.send = lambda message: sent.append(message) or True
                dispatch_server_message(app, screen, {
                    "type": "login_success", "text": "ok",
                    "tutorial_done": tutorial_done})
                # 真实服务器登录后紧接着还会发位置更新：它不能把教程盖掉（2026-11-15 实机：注册后没弹教程）
                dispatch_server_message(app, screen, {
                    "type": "location_update", "location": "lobby",
                    "commands": []})
                for _ in range(8):
                    await pilot.pause()
                result["after_login"] = (screen.mode, screen.engine.primary_id())
                if screen.engine.primary_id() != "tutorial-window":
                    return
                panel = screen.query_one("#tutorial-panel")
                panel._goto_page(tutorial._TOTAL - 1)
                for _ in range(4):
                    await pilot.pause()
                if remember:
                    await pilot.press("enter")
                await pilot.press("escape")
                for _ in range(8):
                    await pilot.pause()
                result["after_exit"] = (screen.mode, screen.engine.primary_id())
                result["sent"] = list(sent)

    asyncio.run(run())
    return result


def test_a_new_account_gets_the_tutorial_after_login_and_returns_to_the_lobby():
    result = _login_flow(tutorial_done=False, remember=False)

    assert result["after_login"] == ("tutorial", "tutorial-window")
    assert result["after_exit"] == ("game", "lobby-window")
    assert result["sent"] == []                     # 没选"不再显示"：什么都不记


def test_choosing_not_to_show_it_again_is_sent_to_the_server_once():
    result = _login_flow(tutorial_done=False, remember=True)

    assert result["after_exit"] == ("game", "lobby-window")
    assert result["sent"] == [{"type": "tutorial_done"}]


def test_an_account_that_dismissed_the_tutorial_goes_straight_to_the_lobby():
    result = _login_flow(tutorial_done=True, remember=False)

    assert result["after_login"] == ("game", "lobby-window")
    assert "after_exit" not in result
