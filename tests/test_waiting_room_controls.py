"""Waiting-room operation state, start policy, and native separators."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from textual.app import App, ComposeResult

from client.protocol.commands import CommandInfo
from client.views.game.controls import RoomControlsPanel
from client.widgets.panel import PanelSeparator
from client.window_engine import SelectList
from server.core.protocol import BaseGameEngine
from server.games.ludo import GAME_INFO as LUDO_INFO
from server.games.ludo.engine import LudoEngine
from server.games.uno import GAME_INFO as UNO_INFO
from server.games.uno.engine import UnoEngine


def _commands(*commands: tuple[str, str]):
    return [(
        "房间",
        [
            CommandInfo(command=command, label=label)
            for command, label in commands
        ],
    )]


def test_command_refresh_preserves_selected_command():
    panel = object.__new__(RoomControlsPanel)
    panel._items = [
        {"label": "开始", "command": "/start", "desc": ""},
        {"label": "机器人", "command": "/bot", "desc": ""},
    ]
    panel.selection = SelectList()
    panel._stack = []
    panel._root_signature = (
        ("option", "/start"),
        ("option", "/bot"),
    )
    panel._redraw = lambda: RoomControlsPanel._sync_options(panel)
    RoomControlsPanel._sync_options(panel)
    panel.selection.select("/bot")

    RoomControlsPanel.update_commands(
        panel,
        _commands(
            ("/start", "开始"),
            ("/bot", "机器人"),
        ),
    )

    assert panel.selected_option.data["command"] == "/bot"


def test_entering_room_resets_lobby_help_cursor_to_start():
    panel = object.__new__(RoomControlsPanel)
    panel._items = [
        {"label": "帮助", "command": "/help", "desc": ""},
    ]
    panel.selection = SelectList()
    panel._stack = []
    panel._root_signature = (("option", "/help"),)
    panel._redraw = lambda: RoomControlsPanel._sync_options(panel)
    RoomControlsPanel._sync_options(panel)

    RoomControlsPanel.update_commands(
        panel,
        _commands(
            ("/start", "开始"),
            ("/bot", "机器人"),
            ("/help", "帮助"),
        ),
    )

    assert panel.selected_option.data["command"] == "/start"


def test_native_separator_tracks_panel_resize():
    class ControlsApp(App):
        def compose(self) -> ComposeResult:
            yield RoomControlsPanel(id="room-controls")

    async def verify() -> None:
        app = ControlsApp()
        async with app.run_test(size=(50, 20)) as pilot:
            panel = app.query_one(RoomControlsPanel)
            panel.update_commands([(
                "房间",
                [
                    CommandInfo(command="/start", label="开始"),
                    CommandInfo(
                        command="", label="", type="separator"),
                    CommandInfo(command="/back", label="返回"),
                ],
            )])
            await pilot.pause()
            separator = panel.query_one(
                "#control-items Divider", PanelSeparator)
            first_width = separator.region.width

            await pilot.resize_terminal(80, 20)
            await pilot.pause()

            assert panel.query_one(
                "#control-items Divider", PanelSeparator) is separator
            assert separator.region.width > first_width
            assert separator.region.height == 1

    asyncio.run(verify())


def test_game_controls_show_labels_without_command_descriptions():
    class ControlsApp(App):
        def compose(self) -> ComposeResult:
            yield RoomControlsPanel(id="room-controls")

    async def verify() -> None:
        app = ControlsApp()
        async with app.run_test() as pilot:
            panel = app.query_one(RoomControlsPanel)
            panel.update_commands([(
                "房间",
                [
                    CommandInfo(
                        command="/start",
                        label="开始",
                        description="开始游戏（2-10人）",
                    ),
                    CommandInfo(
                        command="/bot",
                        label="机器人",
                        description="添加机器人玩家",
                    ),
                ],
            )])
            await pilot.pause()

            rendered = "\n".join(
                str(row.content)
                for row in panel.query(".control-row")
            )
            assert "开始" in rendered
            assert "机器人" in rendered
            assert "开始游戏" not in rendered
            assert "添加机器人玩家" not in rendered

    asyncio.run(verify())


def test_select_menu_adds_explicit_return_option():
    panel = object.__new__(RoomControlsPanel)

    items = RoomControlsPanel._with_return_option([
        {"label": "第一项", "command": "/choose first"},
    ])

    assert items[-1] == {
        "type": "return",
        "label": "返回",
        "command": "",
    }


def test_explicit_no_return_does_not_gain_second_return_row():
    items = RoomControlsPanel._with_return_option([
        {"label": "是", "command": "/forfeit"},
        {"label": "否", "command": "", "type": "return"},
    ])

    assert [item["label"] for item in items] == ["是", "否"]


def test_command_return_does_not_gain_second_return_row():
    items = RoomControlsPanel._with_return_option([{
        "label": "返回",
        "command": "/start cancel",
        "type": "return",
    }])

    assert [item["label"] for item in items] == ["返回"]


class _PolicyEngine(BaseGameEngine):
    game_key = "policy"

    def get_player_room(self, _player_name):
        return SimpleNamespace(
            get_game_data=lambda viewer: {
                "game_type": "policy",
                "room_state": "waiting",
            },
        )


def test_forbidden_underfilled_start_opens_return_only_menu_and_logs():
    engine = _PolicyEngine()

    result = engine._check_start_players("alice", 1, 2, 6, "")

    messages = result["send_to_caller"]
    assert messages[0]["type"] == "game"
    assert "人数不足" in messages[0]["text"]
    menu = messages[1]
    assert menu["type"] == "select_menu"
    assert any(
        item.get("label") == "返回"
        and item.get("command") == "/start cancel"
        and item.get("type") == "return"
        for item in menu["items"]
    )
    assert not any(item.get("command") == "/start confirm_underfilled"
                   for item in menu["items"])


def test_allowed_underfilled_start_requires_explicit_confirmation():
    engine = _PolicyEngine()
    engine.underfilled_start = "confirm"

    result = engine._check_start_players("alice", 2, 2, 6, "")
    items = result["send_to_caller"][1]["items"]

    assert any(item.get("command") == "/start confirm_underfilled"
               for item in items)
    assert sum(item.get("type") == "return" for item in items) == 1
    assert engine._check_start_players(
        "alice", 2, 2, 6, "confirm_underfilled") is None


def test_full_room_starts_without_submenu():
    engine = _PolicyEngine()
    engine.underfilled_start = "confirm"

    assert engine._check_start_players("alice", 6, 2, 6, "") is None


def test_return_from_start_submenu_is_logged():
    engine = _PolicyEngine()

    result = engine._check_start_players("alice", 1, 2, 6, "cancel")

    assert result["send_to_caller"][0] == {
        "type": "game",
        "text": "已取消开始游戏。",
    }


def test_existing_games_declare_start_policy():
    assert UNO_INFO["start_policy"] == {
        "minimum_players": 2,
        "underfilled": "confirm",
    }
    assert LUDO_INFO["start_policy"] == {
        "minimum_players": 2,
        "underfilled": "forbid",
    }


def test_uno_underfilled_start_uses_policy_menu_and_log(monkeypatch):
    engine = UnoEngine()
    room = SimpleNamespace(
        host="alice",
        players=["alice"],
        max_players=6,
        state="waiting",
    )
    monkeypatch.setattr(engine, "get_player_room", lambda _name: room)

    result = engine._cmd_start(None, "alice", {}, "")

    assert result["action"] == "select_menu"
    assert result["send_to_caller"][0]["type"] == "game"
    assert "至少需要 2 人" in result["send_to_caller"][0]["text"]


def test_uno_valid_but_underfilled_room_requires_confirmation(monkeypatch):
    engine = UnoEngine()
    room = SimpleNamespace(
        host="alice",
        players=["alice", "Bot_1"],
        max_players=6,
        state="waiting",
        ready=set(),
        is_bot=lambda name: name.startswith("Bot_"),
    )
    monkeypatch.setattr(engine, "get_player_room", lambda _name: room)

    result = engine._cmd_start(None, "alice", {}, "")

    assert result["action"] == "select_menu"
    assert "当前 2/6 人" in result["send_to_caller"][0]["text"]
    assert any(
        item.get("command") == "/start confirm_underfilled"
        for item in result["send_to_caller"][1]["items"]
    )


def test_ludo_underfilled_start_uses_full_room_policy(monkeypatch):
    engine = LudoEngine()
    room = SimpleNamespace(
        host="alice",
        players=["alice", "bob"],
        max_players=4,
        state="waiting",
    )
    monkeypatch.setattr(engine, "get_player_room", lambda _name: room)

    result = engine._cmd_start(None, "alice", {}, "")

    assert result["action"] == "select_menu"
    assert result["send_to_caller"][0]["type"] == "game"
    assert "当前 2/4 人" in result["send_to_caller"][0]["text"]
