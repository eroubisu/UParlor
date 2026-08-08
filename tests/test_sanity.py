"""客户端导入/注册 sanity tests — 启动时不该有 import error"""
import asyncio

from types import SimpleNamespace
from unittest.mock import Mock


def test_client_app_import():
    import client.app  # noqa


def test_client_screen_import():
    import client.screen  # noqa


def test_app_mount_switches_to_english_input_language(monkeypatch):
    from client import ime
    from client.app import UParlorApp

    switch = Mock()
    monkeypatch.setattr(ime, "on_app_focus", switch)
    app = type("_MountedApp", (), {
        "push_screen": Mock(),
        "set_interval": Mock(),
        "_send_ping": Mock(),
    })()

    UParlorApp.on_mount(app)

    switch.assert_called_once_with()


def test_window_engine_registers_16_windows():
    import client.screen  # 触发所有窗口注册
    from client.window_engine.registry import get_registry
    reg = get_registry()
    specs = reg.all_specs()
    assert len(specs) == 16
    assert [spec.id for spec in specs].count("companion-window") == 1
    assert all(spec.id != "companion-settings-window" for spec in specs)
    assert "companion-creation-window" in {spec.id for spec in specs}
    assert "chat-style-window" in {spec.id for spec in specs}
    assert "root-menu-window" in {spec.id for spec in specs}
    assert all(spec.id != "companion-custom-input-window" for spec in specs)


def test_root_menu_has_7_selectable_windows_without_shortcuts():
    import client.screen
    from client.window_engine.registry import get_registry
    items = get_registry().menu_entries('root')
    assert len(items) == 7
    assert [spec.title for spec in items] == [
        "聊天", "在线", "通知", "游戏", "旅伴", "档案", "设置",
    ]
    assert all(spec.menu for spec in items)


def test_primary_group_has_5_windows():
    import client.screen
    from client.window_engine.registry import get_registry
    primary = get_registry().by_group('primary')
    ids = [s.id for s in primary]
    assert set(ids) == {
        'tutorial-window', 'login-window', 'lobby-window',
        'waiting-window', 'game-window',
    }


def test_hidden_option_window_reflows_after_opening(monkeypatch, tmp_path):
    from textual.app import App, ComposeResult

    from client import storage
    from client.views.system.settings import SettingsPanel, SettingsWindow

    monkeypatch.setattr(storage, "_FILE", tmp_path / "config.json")

    class WindowApp(App):
        def compose(self) -> ComposeResult:
            yield SettingsWindow(id="settings-window")

    async def verify() -> None:
        app = WindowApp()
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one("#settings-window", SettingsWindow)
            measured_frames = []
            prepare = window._prepare_after_show

            def capture_measured_frame(revision: int) -> None:
                measured_frames.append((
                    window.region.x,
                    window.region.width,
                    "打开教程" in app.export_screenshot(),
                ))
                prepare(revision)

            window._prepare_after_show = capture_measured_frame
            window.show()
            assert window.has_class("-layout-pending")
            await pilot.pause()
            await pilot.pause()

            panel = app.query_one("#settings-panel", SettingsPanel)
            assert measured_frames
            measured_x, measured_width, exposed_content = measured_frames[0]
            assert measured_x + measured_width <= 0
            assert measured_width == window.region.width
            assert not exposed_content
            assert not window.has_class("-layout-pending")
            assert "打开教程" in app.export_screenshot()
            content = str(panel.query_one(".content").content)
            assert panel.content_region.width > 1
            assert "打开教程" in content
            assert content.count("\n") == 3
            assert "打开用户档案" not in content
            assert "旅伴设置" not in content
            assert "屏蔽 Ctrl+C：开" in content
            assert "退出 UParlor" in content

            panel.selection.select("ctrl_c")
            panel.nav("enter")
            assert not storage.get_block_ctrl_c()
            assert "屏蔽 Ctrl+C：关" in str(
                panel.query_one(".content").content)

            panel.selection.select("quit")
            panel.nav("enter")
            assert panel._confirming_quit
            assert "确认退出 UParlor?" in str(
                panel.query_one(".content").content)

            panel.nav("down")
            panel.nav("enter")
            assert not panel._confirming_quit

    asyncio.run(verify())


def test_primary_window_focus_is_ready_before_first_frame():
    from textual.app import App, ComposeResult

    from client.views.lobby.window import LobbyWindow

    class LobbyApp(App):
        def compose(self) -> ComposeResult:
            yield LobbyWindow(id="lobby-window")

    async def verify() -> None:
        app = LobbyApp()
        async with app.run_test() as pilot:
            window = app.query_one("#lobby-window", LobbyWindow)
            window.set_active(True)
            window.show()
            assert window.has_class("-layout-pending")
            await pilot.pause()
            await pilot.pause()

            focused = [
                panel.id for panel in window._panels.values()
                if panel.has_class("-focused")
            ]
            assert not window.has_class("-layout-pending")
            assert window.has_class("-active")
            assert focused == ["room-search"]

    asyncio.run(verify())


def test_root_menu_is_centered_and_contains_labels_only():
    from textual.app import App, ComposeResult

    from client.views.system.root_menu import RootMenuPanel, RootMenuWindow

    class MenuApp(App):
        CSS = """
        Screen {
            align: center middle;
        }
        """

        def compose(self) -> ComposeResult:
            yield RootMenuWindow(id="root-menu-window")

    async def verify() -> None:
        app = MenuApp()
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one("#root-menu-window", RootMenuWindow)
            window.show()
            await pilot.pause()
            await pilot.pause()

            panel = app.query_one("#root-menu-panel", RootMenuPanel)
            content = str(panel.query_one(".content").content)
            assert panel.border_title == "菜单"
            assert window.region.x == 25
            assert window.region.width == 30
            assert window.region.height == 18
            assert all(label in content for label in (
                "聊天", "在线", "通知", "游戏", "旅伴", "档案", "设置",
            ))
            assert all(f"{key} " not in content for key in "congaps")

            await pilot.resize_terminal(100, 30)
            await pilot.pause()
            assert window.region.x == 35
            assert window.region.y == 6
            assert not app.screen.show_vertical_scrollbar
            assert not app.screen.show_horizontal_scrollbar

    asyncio.run(verify())


def test_notification_actions_are_selected_from_a_submenu():
    from textual.app import App, ComposeResult

    from client.state import ModuleStateManager
    from client.views.social.notification_panel import NotificationPanel

    class NotificationApp(App):
        def __init__(self) -> None:
            super().__init__()
            self.network = SimpleNamespace(send=Mock())

        def compose(self) -> ComposeResult:
            yield NotificationPanel(id="notification-panel")

    async def verify() -> None:
        app = NotificationApp()
        state = ModuleStateManager()
        state.notify.set_friend_requests(["bob"])
        async with app.run_test(size=(80, 24)):
            panel = app.query_one("#notification-panel", NotificationPanel)
            panel.bind_state(state)
            panel.switch_tab(1)

            panel.nav("enter")
            assert panel._action_menu
            assert [option.label for option in panel.selection.options] == [
                "接受", "拒绝", "返回",
            ]
            panel.nav("tab_next")
            assert panel._action_menu
            assert panel._active == 1

            panel.selection.select("reject")
            panel.nav("enter")
            assert panel._confirming == "reject"
            panel.nav("tab_next")
            assert panel._confirming == "reject"
            assert panel._active == 1
            panel.nav("down")
            panel.nav("enter")
            assert not panel._confirming
            app.network.send.assert_not_called()

            panel.nav("enter")
            panel.selection.select("accept")
            panel.nav("enter")
            panel.nav("enter")
            app.network.send.assert_called_once_with({
                "type": "friend_accept", "name": "bob",
            })

    asyncio.run(verify())


def test_private_chat_actions_open_with_selection_not_delete():
    from textual.app import App, ComposeResult

    from client.state import ModuleStateManager
    from client.views.chat.list import ChatListPanel

    class ChatListApp(App):
        def compose(self) -> ComposeResult:
            yield ChatListPanel(id="chat-list")

    async def verify() -> None:
        app = ChatListApp()
        state = ModuleStateManager()
        state.chat.add_dm_tab("bob")
        async with app.run_test(size=(80, 24)):
            panel = app.query_one("#chat-list", ChatListPanel)
            panel.bind_state(state)
            panel.nav("down")
            panel.nav("enter")

            assert panel._menu_open
            assert [option.label for option in panel.selection.options] == [
                "清空记录", "关闭对话", "返回",
            ]

            panel.selection.select("return")
            panel.nav("enter")
            assert not panel._menu_open

    asyncio.run(verify())


def test_ctrl_c_blocking_is_persisted_and_defaults_on(monkeypatch, tmp_path):
    from client import storage
    from client.app import UParlorApp

    monkeypatch.setattr(storage, "_FILE", tmp_path / "config.json")
    app = type("_App", (), {"action_quit": Mock()})()

    assert storage.get_block_ctrl_c()
    UParlorApp.action_controlled_quit(app)
    app.action_quit.assert_not_called()

    storage.set_block_ctrl_c(False)
    assert not storage.get_block_ctrl_c()
    UParlorApp.action_controlled_quit(app)
    app.action_quit.assert_called_once_with()


def test_companion_module_exports():
    from client.companion import (
        CompanionController, AIService, Character,
        CharacterSummary, list_characters,
    )
    assert CompanionController is not None
    assert AIService is not None
    assert callable(list_characters)


def test_server_main_import():
    """server 包级 import - 不调用 __main__ 避免启动服务器"""
    import server  # noqa
    import server.config  # noqa


def test_server_version_uses_package_metadata(monkeypatch):
    import server.config as config

    monkeypatch.setattr(config, "version", lambda _: "1.2.3")

    assert config._get_server_version() == "1.2.3"


def test_server_games_register():
    from server.games import GAMES
    assert 'uno' in GAMES
    assert 'ludo' in GAMES
