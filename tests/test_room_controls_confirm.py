"""右下角操作面板：服务端声明的确认一律用共享的确认组件显示和处理。"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from client.views.game.controls import RoomControlsPanel


class _App(App):
    def compose(self) -> ComposeResult:
        yield RoomControlsPanel(id="room-controls")


def _run(scenario):
    async def runner():
        app = _App()
        async with app.run_test(size=(60, 14)) as pilot:
            panel = app.query_one(RoomControlsPanel)
            sent: list[str] = []
            panel._send = sent.append
            await pilot.pause()
            await scenario(pilot, panel, sent)

    asyncio.run(runner())


def _ask(panel, command="/kick @bob yes"):
    panel.show_select_menu(
        title="确认", items=[], confirm={"message": "确认踢出 bob?",
                                         "command": command})


def test_a_server_confirmation_sends_its_yes_command_only_after_yes():
    async def scenario(pilot, panel, sent):
        _ask(panel)
        await pilot.pause()
        assert panel.confirmation.is_open
        assert sent == []                              # 只显示确认，什么都没发

        panel.nav("enter")                             # 光标默认在「是」

        assert sent == ["/kick @bob yes"]
        assert not panel._confirming

    _run(scenario)


def test_declining_a_server_confirmation_sends_nothing():
    async def scenario(pilot, panel, sent):
        _ask(panel)
        await pilot.pause()

        panel.nav("down")
        panel.nav("enter")

        assert sent == [] and not panel._confirming

    _run(scenario)


def test_the_client_no_longer_decides_what_needs_confirmation():
    assert not hasattr(RoomControlsPanel, "_CONFIRM_PREFIXES")
