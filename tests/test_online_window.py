"""Online-window interaction regressions."""

from __future__ import annotations

import asyncio
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

from rich.console import Console
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from client.state import ModuleStateManager
from client.views.social.online_list import OnlineListPanel
from client.views.social.online_window import OnlineWindow
from client.views.social.status_panel import StatusPanel
from client.window_engine import WindowEngine


class _OnlineApp(App):
    CSS = """
    #background {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self):
        super().__init__()
        self.network = SimpleNamespace(send=Mock(return_value=True))
        self.state = ModuleStateManager()
        self.logged_in = True
        self.mode = "game"
        self.engine = WindowEngine()
        self.engine.attach(self, lambda: self)

    def compose(self) -> ComposeResult:
        yield Static("BACKGROUND", id="background")
        yield OnlineWindow(id="online-window")


def _panel_text(panel: StatusPanel) -> str:
    output = StringIO()
    console = Console(
        file=output, width=80, color_system=None,
    )
    console.print(panel.query_one("#t0 .content", Static).content)
    return output.getvalue()


def test_all_players_navigation_scrolls_monotonically_without_jitter():
    async def verify() -> None:
        app = _OnlineApp()
        app.state.online.update_all_users([
            f"player-{index:02d}" for index in range(40)
        ])
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(OnlineWindow)
            window.bind_state(app.state)
            assert app.engine.open("online-window")
            await pilot.pause()
            await pilot.pause()
            panel = app.query_one(OnlineListPanel)
            panel.switch_tab(2)
            await pilot.pause()
            scroll = panel.query_one("#t2", VerticalScroll)

            down_offsets = []
            for _ in range(30):
                panel.nav("down")
                await pilot.pause()
                down_offsets.append(scroll.scroll_offset.y)
                assert (
                    scroll.scroll_offset.y
                    <= panel.selection.index
                    < scroll.scroll_offset.y + scroll.size.height
                )
            assert down_offsets == sorted(down_offsets)

            up_offsets = []
            for _ in range(20):
                panel.nav("up")
                await pilot.pause()
                up_offsets.append(scroll.scroll_offset.y)
                assert (
                    scroll.scroll_offset.y
                    <= panel.selection.index
                    < scroll.scroll_offset.y + scroll.size.height
                )
            assert up_offsets == sorted(up_offsets, reverse=True)

    asyncio.run(verify())


def test_online_window_opens_with_first_player_selected_and_visible():
    async def verify() -> None:
        app = _OnlineApp()
        app.state.online.update_users([
            {"name": f"player-{index:02d}"} for index in range(40)
        ])
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(OnlineWindow)
            window.bind_state(app.state)
            panel = app.query_one(OnlineListPanel)
            panel.switch_tab(1)
            panel.query_one("#t1", VerticalScroll).scroll_end(animate=False)
            await pilot.pause()

            window.show()
            await pilot.pause()
            await pilot.pause()

            scroll = panel.query_one("#t1", VerticalScroll)
            assert panel.selected_option.id == "player-00"
            assert panel._focus_line == 0
            assert scroll.scroll_offset.y == 0
            app.network.send.assert_called_with({
                "type": "get_profile_card",
                "target": "player-00",
            })

    asyncio.run(verify())


def test_online_window_reveals_after_initial_card_is_rendered():
    async def verify() -> None:
        app = _OnlineApp()
        app.state.online.update_users([{"name": "alice"}])
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(OnlineWindow)
            window.bind_state(app.state)
            panel = app.query_one(OnlineListPanel)
            panel.switch_tab(1)

            window.show()
            await pilot.pause()
            await pilot.pause()

            assert window.has_class("-layout-pending")
            app.state.online.set_viewed_card({
                "name": "alice",
                "level": 3,
                "gold": 20,
                "friends_count": 1,
            })
            await pilot.pause()
            await pilot.pause()

            assert not window.has_class("-layout-pending")
            assert "alice" in app.export_screenshot()

    asyncio.run(verify())


def test_online_window_reopen_waits_for_fresh_initial_card():
    async def verify() -> None:
        app = _OnlineApp()
        app.state.online.update_users([{"name": "alice"}])
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(OnlineWindow)
            window.bind_state(app.state)
            panel = app.query_one(OnlineListPanel)
            panel.switch_tab(1)
            assert app.engine.open("online-window")
            await pilot.pause()
            await pilot.pause()
            app.state.online.set_viewed_card({"name": "alice"})
            await pilot.pause()
            await pilot.pause()
            assert app.engine.close("online-window")

            window.presentation_timeout = 10.0
            assert app.engine.open("online-window")
            await pilot.pause()
            await pilot.pause()

            assert window.has_class("-layout-pending")

    asyncio.run(verify())


def test_online_window_ignores_stale_profile_card_response():
    async def verify() -> None:
        app = _OnlineApp()
        app.state.online.update_users([{"name": "alice"}])
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(OnlineWindow)
            window.bind_state(app.state)
            panel = app.query_one(OnlineListPanel)
            panel.switch_tab(1)
            window.show()
            await pilot.pause()
            await pilot.pause()

            app.state.online.set_viewed_card({"name": "bob"})
            await pilot.pause()

            assert window.has_class("-layout-pending")
            detail = app.query_one("#online-detail", StatusPanel)
            assert detail._card_data == {}

    asyncio.run(verify())


def test_status_card_preserves_player_fields_and_tab_titles():
    async def verify() -> None:
        app = _OnlineApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#online-detail", StatusPanel)
            panel.render_card({
                "name": "alice",
                "title": "远行者",
                "level": 7,
                "exp": 35,
                "exp_to_next": 100,
                "gold": 88,
                "friends_count": 4,
                "created_at": "2025-03-04T12:30:00",
                "game_rank": {"name": "白银"},
            }, is_self=True)
            await pilot.pause()

            text = _panel_text(panel)
            assert panel.tabs == ["信息", "操作"]
            assert "信息" in str(panel.border_title)
            assert "操作" in str(panel.border_title)
            assert panel.border_subtitle == "alice"
            for expected in (
                "远行者", "等级", "7", "35/100", "金币", "88",
                "好友", "4", "注册", "2025-03-04", "段位", "白银",
            ):
                assert expected in text

    asyncio.run(verify())


def test_status_card_preserves_friend_actions_and_bot_summary():
    async def verify() -> None:
        app = _OnlineApp()
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#online-detail", StatusPanel)
            panel.render_card({
                "name": "bob",
                "level": 2,
            }, friends=["bob"])
            await pilot.pause()

            assert panel._viewed_name == "bob"
            assert panel.tabs == ["信息", "操作"]
            assert [action["label"] for action in panel._actions] == [
                "私聊", "删除好友",
            ]
            assert panel.border_subtitle == "bob"

            panel.render_card({
                "name": "陪练机器人",
                "is_bot": True,
                "title": "UNO 练习对手",
            })
            await pilot.pause()

            assert panel.tabs == []
            assert panel.border_title == "陪练机器人"
            assert panel.border_subtitle == ""
            assert "UNO 练习对手" in _panel_text(panel)
            assert not panel.query_one("#t1").display

    asyncio.run(verify())


def test_online_window_close_invalidates_both_columns_immediately():
    async def verify() -> None:
        app = _OnlineApp()
        app.state.online.update_users([{"name": "RIGHT-GHOST"}])
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(OnlineWindow)
            window.bind_state(app.state)
            app.query_one(OnlineListPanel).switch_tab(1)
            window.show()
            await pilot.pause()
            await pilot.pause()
            app.state.online.set_viewed_card({
                "name": "RIGHT-GHOST",
                "level": 1,
                "gold": 0,
                "friends_count": 0,
            })
            await pilot.pause()
            assert "RIGHT-GHOST" in app.export_screenshot()

            refresh = Mock(wraps=app.screen.refresh)
            app.screen.refresh = refresh
            window.hide()
            await pilot.pause()

            screenshot = app.export_screenshot()
            refresh.assert_called()
            assert "BACKGROUND" in screenshot
            assert "RIGHT-GHOST" not in screenshot

    asyncio.run(verify())
