"""Replay, reward, and per-session game interaction regressions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import random
import threading
from unittest.mock import Mock

import pytest
from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from client.games.ludo.handler import LudoHandler
from client.games.ludo.renderer import LudoRenderer
from client.games.uno.handler import UnoHandler
from client.games.uno.renderer import UnoRenderer, _render_hand_row
from client.net.dispatch.game import (
    _on_game_quit, _on_room_leave, _on_room_update,
)
from client.net.messages import GameQuit, RoomLeave, RoomUpdate
from client.protocol.commands import parse_game_tabs
from client.protocol.handler import (
    GameHandlerContext,
    get_handler,
)
from client.screen import GameScreen
from client.state import ModuleStateManager
from client.views.game.board import GameBoardPanel
from client.views.game.controls import RoomControlsPanel
from client.views.game.status import GameStatusPanel
from client.views.game.window import GameWindow
from server.games.ludo.engine import LudoBotScheduler, LudoEngine
from server.games.ludo.board import Board, PieceState
from server.games.ludo.room import LudoRoom
from server.games.uno.cards import UnoCard
from server.games.uno.engine import UnoBotScheduler, UnoEngine
from server.games.uno.room import UnoRoom
from server.core.result_dispatcher import dispatch_game_result
from server.msg_types import (
    COMMANDS_UPDATE, GAME, LOCATION_UPDATE, ROOM_UPDATE,
)
from server.player.manager import PlayerManager
from server.player.schema import get_default_user_template


def _disable_shuffle(monkeypatch) -> None:
    monkeypatch.setattr(random, 'shuffle', lambda _values: None)


@pytest.mark.parametrize('engine_type', [UnoEngine, LudoEngine])
def test_forfeit_confirmation_uses_no_as_its_return_row(engine_type):
    engine = engine_type()
    engine._rooms['room'] = Mock(state='playing')
    engine._player_room['alice'] = 'room'

    result = engine.handle_back(None, 'alice', {})
    items = result['send_to_caller'][0]['items']

    assert [item.get('label') for item in items if item.get('command', '') or
            item.get('type') == 'return'] == ['是', '否']
    assert items[-1]['type'] == 'return'


def _ctx(state, timers=None, commands=None) -> GameHandlerContext:
    timers = timers if timers is not None else []
    commands = commands if commands is not None else []
    return GameHandlerContext(
        state,
        get_module=lambda _: None,
        set_timer=lambda delay, callback: timers.append((delay, callback)),
        send_command=commands.append,
    )


def _uno_handler() -> UnoHandler:
    handler = get_handler('uno')
    assert isinstance(handler, UnoHandler)
    return handler


def _ludo_handler() -> LudoHandler:
    handler = get_handler('ludo')
    assert isinstance(handler, LudoHandler)
    return handler


def _render_text(renderable, width: int = 80) -> str:
    console = Console(width=width, record=True, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_ludo_yellow_same_color_jump_has_intermediate_animation_frames():
    board = Board(['yellow'])
    piece = board.get_piece('yellow', 0)
    piece.state = PieceState.TRACK
    piece.track_pos = 20

    path = board.compute_path('yellow', 0, 1)
    positions = [
        frame.get('track_pos') for frame in path
        if frame.get('state') == 'track'
    ]

    assert positions == [21, 22, 23, 24, 25]


def test_ludo_layout_has_three_line_controls_and_players_in_status():
    class BoardApp(App):
        def compose(self) -> ComposeResult:
            yield GameBoardPanel(id="game-board")

    async def verify_panel() -> None:
        app = BoardApp()
        async with app.run_test(size=(88, 38)) as pilot:
            panel = app.query_one(GameBoardPanel)
            panel.bind_state(ModuleStateManager())
            panel._state.game_board.room_data = {
                "game_type": "ludo",
                "room_state": "playing",
            }
            panel._refresh()
            await pilot.pause()
            assert panel.query_one("#board-controls").region.height == 3

    asyncio.run(verify_panel())

    sections = LudoRenderer().render_board({
        "room_state": "playing",
        "player_colors": {"alice": "red", "bob": "blue"},
        "current_player": "alice",
        "dice": 3,
        "board": {},
    }, {"my_turn": True, "viewer_color": "red"})

    status = LudoRenderer().render_status({
        "room_state": "playing",
        "player_colors": {"alice": "red", "bob": "blue"},
        "current_player": "alice",
        "dice": 3,
        "board": {
            "red": [
                {"state": "airport"},
                {"state": "track"},
                {"state": "runway"},
                {"state": "finished"},
            ],
        },
    }, {"my_turn": True})
    status_text = _render_text(status.body, width=34)
    assert "alice" in status_text
    assert "bob" in status_text
    assert "机场1 赛道1 跑道1 完成1" in status_text
    assert "alice" not in sections["board"].plain


def test_ludo_roll_keeps_controls_visible_while_request_is_pending():
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    state.game_interaction.replace("ludo", {
        "playing": True,
        "my_turn": True,
        "active": True,
        "buttons": [{"label": "掷骰子", "command": "/roll"}],
        "btn_cursor": 0,
    })
    commands = []

    _ludo_handler().on_nav("enter", _ctx(state, commands=commands))

    interaction = state.game_interaction.snapshot("ludo")
    assert commands == ["/roll"]
    assert interaction["buttons"] == [
        {"label": "掷骰子", "command": "/roll"},
    ]
    assert interaction["active"] is False


@pytest.mark.parametrize(
    ("game_type", "expected_status_height", "controls_height"),
    [("ludo", 5, 3), ("uno", 17, 7)],
)
def test_game_window_uses_each_games_declared_layout_at_88_by_32(
    game_type, expected_status_height, controls_height,
):
    class GameApp(App):
        def compose(self) -> ComposeResult:
            yield GameWindow(id="game-window")

    async def verify() -> None:
        app = GameApp()
        async with app.run_test(size=(88, 32)) as pilot:
            window = app.query_one(GameWindow)
            window.add_class("visible")
            state = ModuleStateManager()
            window.bind_state(state)
            state.game_board.update_room({
                "game_type": game_type,
                "room_state": "playing",
                "players": [f"player-{index}" for index in range(10)],
                "player_colors": {
                    "player-0": "red",
                    "player-1": "blue",
                },
                "current_player": "player-0",
                "hand_counts": {
                    f"player-{index}": 7 for index in range(10)
                },
                "board": {},
            })
            await pilot.pause()

            status = window.query_one(GameStatusPanel)
            board = window.query_one(GameBoardPanel)
            board_view = board.query_one("#t0", VerticalScroll)
            controls = board.query_one("#board-controls", VerticalScroll)
            assert status.region.height == expected_status_height
            assert status.border_title == "状态"
            assert controls.region.height == controls_height
            if game_type == "ludo":
                assert board_view.region.height >= 19
                assert board_view.content_region.width >= 38
                assert not board_view.show_vertical_scrollbar
                assert not board_view.show_horizontal_scrollbar
                status_view = status.query_one("#t0", VerticalScroll)
                assert not status_view.show_vertical_scrollbar
            else:
                assert status.query_one("#game-status-header").display
                assert status.query_one("#game-status-divider").display

    asyncio.run(verify())


def test_game_window_first_frame_has_room_operations():
    class GameApp(App):
        def compose(self) -> ComposeResult:
            yield GameWindow(id="game-window")

    async def verify() -> None:
        app = GameApp()
        async with app.run_test(size=(88, 32)) as pilot:
            window = app.query_one(GameWindow)
            state = ModuleStateManager()
            window.bind_state(state)
            controls = window.query_one(RoomControlsPanel)
            controls.prepare_context(parse_game_tabs([
                {"name": "play", "label": "出牌"},
                {"name": "back", "label": "返回"},
                {"name": "help", "label": "帮助"},
            ]))
            state.game_board.update_room({
                "game_type": "uno",
                "room_state": "playing",
                "players": ["alice", "bob"],
            }, notify=False)
            window.show()
            await pilot.pause()
            await pilot.pause()

            rendered = "\n".join(
                str(row.content)
                for row in controls.query(".control-row")
            )
            assert "返回" in rendered
            assert "帮助" in rendered
            assert "暂无可用操作" not in rendered

    asyncio.run(verify())


def test_uno_action_keeps_controls_visible_while_request_is_pending():
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    state.game_board.room_data = {
        "my_cards": [{"color": "red", "value": "5"}],
        "playable": [0],
    }
    state.game_interaction.replace("uno", {
        "playing": True,
        "my_turn": True,
        "active": True,
        "row": 1,
        "buttons": [{"label": "摸牌", "command": "/draw"}],
        "btn_cursor": 0,
        "hand_cursor": 0,
        "selected": -1,
        "cards_per_row": 8,
        "color_mode": False,
    })
    commands = []

    _uno_handler().on_nav("enter", _ctx(state, commands=commands))

    interaction = state.game_interaction.snapshot("uno")
    assert commands == ["/draw"]
    assert interaction["buttons"] == [
        {"label": "摸牌", "command": "/draw"},
    ]
    assert interaction["active"] is False


def test_uno_status_uses_yellow_text_and_edge_aligned_rows():
    status = UnoRenderer().render_status({
        "room_state": "playing",
        "players": ["alice", "bob"],
        "current_player": "alice",
        "hand_counts": {"alice": 3, "bob": 1},
        "deck_remaining": 42,
    }, {"my_turn": True})

    assert status.header is not None
    text = _render_text(status.body, width=36)
    lines = text.splitlines()
    assert "你的回合" in lines[0]
    assert "已出:" in lines[0]
    assert lines[3].lstrip().startswith("> alice")
    assert lines[3].rstrip().endswith("3 张")
    assert lines[4].rstrip().endswith("1 张  UNO!")


def test_uno_status_preserves_dark_reverse_header_and_color_order():
    status = UnoRenderer().render_status({
        "room_state": "playing",
        "side": "dark",
        "direction": -1,
        "players": ["alice", "bob"],
        "current_player": "bob",
        "hand_counts": {"alice": 3, "bob": 1},
        "deck_remaining": 12,
        "played_colors": ["teal", "orange"],
    })

    header = _render_text(status.header, width=38)
    body = _render_text(status.body, width=38)
    assert "Dark" in header
    assert "逆序" in header
    assert "牌堆: 12" in header
    assert "等待 bob" in body
    assert "已出: ░░██░░██" in body
    assert body.rstrip().endswith("1 张  UNO!")


def test_uno_status_keeps_only_first_two_prompts_in_priority_order():
    status = UnoRenderer().render_status({
        "room_state": "playing",
        "pending_draw": 6,
        "draw_stacking": True,
        "draw_until_color": "red",
        "challengeable": True,
        "top_card": {"value": "wild"},
        "draw_play": True,
    })

    body = _render_text(status.body, width=38)
    assert "摸牌 +6（可叠）" in body
    assert "摸至 ██色" in body
    assert "可挑战 Wild" not in body
    assert "请选择颜色" not in body
    assert "出牌或跳过" not in body


def test_uno_status_reserves_all_prompt_rows():
    renderer = UnoRenderer()

    assert renderer.status_height({"players": ["alice", "bob"]}) == 9
    assert renderer.status_height({
        "players": [f"player-{index}" for index in range(10)],
    }) == 17
    assert renderer.status_height({
        "players": [f"player-{index}" for index in range(10)],
        "pending_draw": 4,
        "challengeable": True,
    }) == 17


def test_uno_game_render_preserves_discard_hand_buttons_and_focus_line():
    renderer = UnoRenderer()
    sections = renderer.render_board({
        "room_state": "playing",
        "top_card": {"color": "wild", "value": "wild"},
        "chosen_color": "blue",
        "my_cards": [
            {"color": "red", "value": "1"},
            {"color": "yellow", "value": "2"},
            {"color": "green", "value": "3"},
            {"color": "blue", "value": "4"},
        ],
        "playable": [0, 3],
        "message": "请选择操作",
    }, {
        "active": True,
        "my_turn": True,
        "row": 1,
        "hand_cursor": 3,
        "selected": -1,
        "btn_cursor": 1,
        "buttons": [
            {"label": "出牌", "command": "_play_selected"},
            {"label": "摸牌", "command": "/draw"},
        ],
    }, board_width=20)

    board_text = _render_text(sections["board"], width=40)
    controls_text = _render_text(sections["controls"], width=40)
    assert "要求跟牌" in board_text
    assert "指定 ██" in board_text
    assert "请选择操作" in board_text
    assert all(value in controls_text for value in ("1", "2", "3", "4"))
    assert "出牌" in controls_text
    assert "摸牌" in controls_text
    assert controls_text.count("╭───╮") == 4
    assert renderer.scroll_hint == 8


def test_uno_finished_render_preserves_winner_scores_and_message_order():
    sections = UnoRenderer().render_board({
        "room_state": "finished",
        "winner": "alice",
        "scores": {"alice": 0, "bob": 17, "carol": 23},
        "message": "对局结束",
    })

    board_text = _render_text(sections["board"])
    assert sections["controls"] is None
    assert "alice 获胜！" in board_text
    assert "alice: 0分" not in board_text
    assert board_text.index("bob: 17分") < board_text.index("carol: 23分")
    assert board_text.index("carol: 23分") < board_text.index("对局结束")


def test_game_to_waiting_transition_keeps_old_frame_until_single_target():
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    state.game_board.room_data = {
        "game_type": "uno",
        "room_state": "playing",
    }
    state.game_interaction.replace("uno", {
        "playing": True,
        "buttons": [{"label": "摸牌", "command": "/draw"}],
    })
    board_events = []
    interaction_events = []
    state.game_board.add_listener(
        lambda event, *args: board_events.append(event),
    )
    state.game_interaction.add_listener(
        lambda event, *args: interaction_events.append(event),
    )

    class Screen:
        def __init__(self):
            self.targets = []
            self.prepared = []
            self.locations = []
            self.on_present = None

        def _prepare_main_window(self, target, commands):
            self.prepared.append((target, commands))

        def _switch_main_window(self, target, on_present=None):
            self.targets.append(target)
            assert self.locations == []
            self.on_present = on_present

        def _update_location(self, location, location_path=None):
            self.locations.append((location, location_path))

        def _commit_main_window_context(
            self, _commands, location, location_path, _tile_name='',
        ):
            self._update_location(location, location_path)

        def query_one(self, _selector):
            raise LookupError

    screen = Screen()
    _on_game_quit(GameQuit(location="room"), Mock(), screen, state)
    _on_room_update(RoomUpdate({
        "game_type": "uno",
        "room_state": "waiting",
        "players": ["alice", "bot"],
    }, message="你放弃了游戏。", location="uno#1234",
        location_path="大厅 / UNO / #1234",
        commands=[{"name": "ready"}]), Mock(), screen, state)

    assert screen.targets == ["waiting"]
    assert screen.prepared == [
        ("waiting", [{"name": "ready"}]),
    ]
    assert screen.locations == []
    assert state.cmd.lines == []
    screen.on_present()
    assert screen.locations == [
        ("uno#1234", "大厅 / UNO / #1234"),
    ]
    assert state.cmd.lines[-1].endswith("你放弃了游戏。")
    assert board_events == []
    assert interaction_events == []
    assert state.game_board.room_data["room_state"] == "waiting"
    assert state.game_interaction.snapshot("uno") is None


def test_waiting_to_lobby_transition_clears_silently_once():
    state = ModuleStateManager()
    state.game_board.room_data = {
        "game_type": "ludo",
        "room_state": "waiting",
    }
    events = []
    state.game_board.add_listener(lambda event, *args: events.append(event))

    screen = Mock()
    _on_room_leave(
        RoomLeave(location="lobby", location_path="大厅"),
        Mock(), screen, state,
    )

    screen._prepare_main_window.assert_called_once_with("lobby", [])
    screen._switch_main_window.assert_called_once()
    target = screen._switch_main_window.call_args.args[0]
    on_present = screen._switch_main_window.call_args.kwargs["on_present"]
    assert target == "lobby"
    on_present()
    screen._commit_main_window_context.assert_called_once_with(
        [], "lobby", "大厅",
    )
    assert events == []
    assert state.game_board.room_data == {}


def test_room_commands_update_only_the_active_window_controls():
    active_controls = Mock()
    active_window = Mock()
    active_window.query_one.return_value = active_controls
    hidden_window = Mock()

    screen = Mock()
    screen.state = ModuleStateManager()
    screen.engine.active_window.return_value = active_window
    screen.engine.get_window.return_value = hidden_window

    GameScreen._update_room_controls(screen)

    active_window.query_one.assert_called_once()
    active_controls.update_commands.assert_called_once()
    hidden_window.query_one.assert_not_called()


def test_uno_controls_fit_seven_lines_without_scrollbar():
    class BoardApp(App):
        def compose(self) -> ComposeResult:
            yield GameBoardPanel(id="game-board")

    async def verify() -> None:
        app = BoardApp()
        async with app.run_test(size=(88, 32)) as pilot:
            panel = app.query_one(GameBoardPanel)
            state = ModuleStateManager()
            state.chat.set_player_name("alice")
            panel.bind_state(state)
            state.game_interaction.replace("uno", {
                "playing": True,
                "my_turn": True,
                "active": True,
                "row": 0,
                "hand_cursor": 0,
                "selected": -1,
                "buttons": [
                    {"label": "出牌", "command": "_play_selected"},
                    {"label": "摸牌", "command": "/draw"},
                ],
                "btn_cursor": 0,
                "cards_per_row": 8,
                "color_mode": False,
            })
            state.game_board.update_room({
                "game_type": "uno",
                "room_state": "playing",
                "current_player": "alice",
                "my_cards": [{"color": "red", "value": "5"}],
                "playable": [0],
            })
            await pilot.pause()

            controls = panel.query_one("#board-controls", VerticalScroll)
            assert controls.region.height == 7
            assert not controls.show_vertical_scrollbar

    asyncio.run(verify())


def test_uno_status_reserves_two_prompt_lines_without_scrollbar():
    class GameApp(App):
        def compose(self) -> ComposeResult:
            yield GameWindow(id="game-window")

    async def verify() -> None:
        app = GameApp()
        async with app.run_test(size=(88, 32)) as pilot:
            window = app.query_one(GameWindow)
            window.add_class("visible")
            state = ModuleStateManager()
            window.bind_state(state)
            state.game_board.update_room({
                "game_type": "uno",
                "room_state": "playing",
                "players": [f"player-{index}" for index in range(10)],
                "current_player": "player-0",
                "hand_counts": {
                    f"player-{index}": 7 for index in range(10)
                },
                "pending_draw": 4,
                "challengeable": True,
            })
            await pilot.pause()

            status = window.query_one(GameStatusPanel)
            status_view = status.query_one("#t0", VerticalScroll)
            chat = window.query_one("#game-chat")
            assert status.region.height == 17
            assert window.query_one("#game-right").region.width == 40
            assert window.query_one(GameBoardPanel).region.width == 48
            assert not status_view.show_vertical_scrollbar
            assert chat.region.height == 6
            assert window.query_one("#room-controls").region.height == 6

    asyncio.run(verify())


def test_uno_status_fits_maximum_legal_content_width():
    status = UnoRenderer().render_status({
        "room_state": "playing",
        "players": ["ABCDEFGHIJKL"] + [
            f"player-{index}" for index in range(1, 10)
        ],
        "current_player": "ABCDEFGHIJKL",
        "hand_counts": {
            "ABCDEFGHIJKL": 1,
            **{f"player-{index}": 99 for index in range(1, 10)},
        },
        "deck_remaining": 999,
        "pending_draw": 99,
        "draw_stacking": True,
        "challengeable": True,
    }, {"my_turn": True})

    rendered = _render_text(status.body, width=38)
    assert "摸牌 +99（可叠）" in rendered
    assert "可挑战 Wild" in rendered
    assert "ABCDEFGHIJKL" in rendered
    assert "…" not in rendered


def test_uno_focus_skips_unplayable_cards_and_disables_other_turn():
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    handler = _uno_handler()
    ctx = _ctx(state)
    room_data = {
        "game_type": "uno",
        "room_state": "playing",
        "current_player": "alice",
        "my_cards": [{"value": str(index)} for index in range(5)],
        "playable": [1, 4],
    }
    state.game_board.room_data = room_data
    handler.on_room_update(room_data, ctx)
    assert state.game_interaction.snapshot("uno")["hand_cursor"] == 1

    handler.on_nav("right", ctx)
    assert state.game_interaction.snapshot("uno")["hand_cursor"] == 4
    handler.on_nav("right", ctx)
    assert state.game_interaction.snapshot("uno")["hand_cursor"] == 4

    other_turn = dict(room_data, current_player="bob")
    state.game_board.room_data = other_turn
    handler.on_room_update(other_turn, ctx)
    interaction = state.game_interaction.snapshot("uno")
    assert interaction["row"] == -1
    assert interaction["selected"] == -1
    before = interaction
    handler.on_nav("right", ctx)
    assert state.game_interaction.snapshot("uno") == before


def test_uno_selected_card_can_be_replaced_after_returning_from_play_button():
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    handler = _uno_handler()
    ctx = _ctx(state)
    room_data = {
        "game_type": "uno",
        "room_state": "playing",
        "current_player": "alice",
        "my_cards": [
            {"color": "red", "value": "1"},
            {"color": "blue", "value": "2"},
            {"color": "red", "value": "3"},
        ],
        "playable": [0, 2],
    }
    state.game_board.room_data = room_data
    handler.on_room_update(room_data, ctx)

    handler.on_nav("enter", ctx)
    interaction = state.game_interaction.snapshot("uno")
    assert interaction["selected"] == 0
    assert interaction["row"] == 1
    assert interaction["btn_cursor"] == 0

    handler.on_nav("up", ctx)
    handler.on_nav("right", ctx)
    interaction = state.game_interaction.snapshot("uno")
    assert interaction["row"] == 0
    assert interaction["hand_cursor"] == 2
    assert interaction["selected"] == 0

    handler.on_nav("enter", ctx)
    interaction = state.game_interaction.snapshot("uno")
    assert interaction["selected"] == 2
    assert interaction["row"] == 1
    assert interaction["btn_cursor"] == 0


def test_uno_navigation_respects_card_rows_and_button_boundaries():
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    handler = _uno_handler()
    ctx = _ctx(state)
    room_data = {
        "game_type": "uno",
        "room_state": "playing",
        "current_player": "alice",
        "my_cards": [
            {"value": str(index)} for index in range(30)
        ],
        "playable": [1, 14, 27],
    }
    state.game_board.room_data = room_data
    handler.on_room_update(room_data, ctx)

    handler.on_nav("down", ctx)
    assert state.game_interaction.snapshot("uno")["hand_cursor"] == 14
    handler.on_nav("down", ctx)
    assert state.game_interaction.snapshot("uno")["hand_cursor"] == 27
    handler.on_nav("down", ctx)
    interaction = state.game_interaction.snapshot("uno")
    assert interaction["row"] == 1
    assert interaction["hand_cursor"] == 27

    handler.on_nav("right", ctx)
    assert state.game_interaction.snapshot("uno")["btn_cursor"] == 1
    handler.on_nav("left", ctx)
    assert state.game_interaction.snapshot("uno")["btn_cursor"] == 0

    handler.on_nav("up", ctx)
    assert state.game_interaction.snapshot("uno")["row"] == 0
    handler.on_nav("up", ctx)
    assert state.game_interaction.snapshot("uno")["hand_cursor"] == 14


def test_uno_four_card_states_use_three_border_colors():
    rendered = Text()
    _render_hand_row(
        rendered,
        [
            {"color": "red", "value": "1"},
            {"color": "blue", "value": "2"},
            {"color": "green", "value": "3"},
            {"color": "yellow", "value": "4"},
        ],
        start_idx=0,
        playable=[0, 1, 2],
        cursor=2,
        selected=0,
    )

    top_border_styles = {
        span.start: str(span.style)
        for span in rendered.spans
        if span.start in {2, 8, 14, 20}
    }
    assert top_border_styles == {
        2: "bold #ffffff",
        8: "#a0a0a0",
        14: "bold #ffffff",
        20: "#383838",
    }


def test_game_board_preserves_controls_during_transient_empty_render():
    class BoardApp(App):
        def compose(self) -> ComposeResult:
            yield GameBoardPanel(id="game-board")

    async def verify() -> None:
        app = BoardApp()
        async with app.run_test(size=(88, 32)) as pilot:
            panel = app.query_one(GameBoardPanel)
            state = ModuleStateManager()
            panel.bind_state(state)
            state.game_interaction.replace("ludo", {
                "playing": True,
                "my_turn": True,
                "active": True,
                "buttons": [{"label": "掷骰子", "command": "/roll"}],
                "btn_cursor": 0,
            })
            state.game_board.update_room({
                "game_type": "ludo",
                "room_state": "playing",
                "board": {},
            })
            await pilot.pause()
            content = panel.query_one("#board-controls-content")
            before = str(content.render())

            state.game_interaction.reset("ludo")
            await pilot.pause()
            assert str(content.render()) == before

    asyncio.run(verify())


def test_game_room_controls_use_six_total_lines():
    class GameApp(App):
        def compose(self) -> ComposeResult:
            yield GameWindow(id="game-window")

    async def verify() -> None:
        app = GameApp()
        async with app.run_test(size=(88, 32)) as pilot:
            window = app.query_one(GameWindow)
            window.add_class("visible")
            await pilot.pause()
            assert window.query_one("#room-controls").region.height == 6

    asyncio.run(verify())


def test_ludo_same_room_replay_resets_every_match_field(monkeypatch):
    _disable_shuffle(monkeypatch)
    room = LudoRoom('room', ['alice', 'bob'])
    room.start()
    room.rankings[:] = ['alice', 'bob']
    room._result_pending.add('alice')
    room.last_move = {'seq': 8}
    room._move_seq = 8
    room.pending_move = True
    room.dice = 6
    room.consecutive_sixes = 2

    room.start()

    assert room.state == 'playing'
    assert room.rankings == []
    assert room._result_pending == set()
    assert room.last_move is None
    assert room._move_seq == 0
    assert room.pending_move is False
    assert room.dice == 0
    assert room.consecutive_sixes == 0
    assert set(room.player_colors) == {'alice', 'bob'}
    assert set(room.color_players.values()) == {'alice', 'bob'}


def test_ludo_replay_with_changed_roster_has_no_stale_color(monkeypatch):
    _disable_shuffle(monkeypatch)
    room = LudoRoom('room', ['alice', 'bob', 'carol'])
    room.start()
    room.players = ['alice', 'dave']

    room.start()

    assert set(room.player_colors) == {'alice', 'dave'}
    assert set(room.color_players.values()) == {'alice', 'dave'}
    assert 'bob' not in room.player_colors
    assert 'carol' not in room.player_colors


def test_uno_same_room_replay_resets_every_match_field(monkeypatch):
    _disable_shuffle(monkeypatch)
    room = UnoRoom('room', ['alice', 'bob'])
    room.start()
    room.chosen_color = 'red'
    room.pending_draw = 5
    room.pending_draw_type = 'draw5'
    room.draw_until_color = 'blue'
    room.challengeable = True
    room.last_wild_player = 'alice'
    room.last_wild_had_match = True
    room.winner = 'alice'
    room.scores = {'alice': 100, 'bob': 20}
    room._result_pending.add('alice')

    room.start()

    assert room.state == 'playing'
    assert room.chosen_color is None
    assert room.pending_draw == 0
    assert room.pending_draw_type == ''
    assert room.draw_until_color is None
    assert room.challengeable is False
    assert room.last_wild_player == ''
    assert room.last_wild_had_match is False
    assert room.winner == ''
    assert room.scores == {}
    assert room._result_pending == set()
    assert set(room.hands) == {'alice', 'bob'}


def test_uno_replay_with_changed_roster_has_no_stale_hand(monkeypatch):
    _disable_shuffle(monkeypatch)
    room = UnoRoom('room', ['alice', 'bob', 'carol'])
    room.start()
    room.players = ['alice', 'dave']

    room.start()

    assert set(room.hands) == {'alice', 'dave'}
    assert 'bob' not in room.hands
    assert 'carol' not in room.hands


def test_uno_wild_draw_records_challenge_snapshot_before_playing_card():
    room = UnoRoom('room', ['alice', 'bob'])
    room.state = 'playing'
    room.discard_pile = [
        UnoCard('red', '5', 'pink', '5'),
    ]
    matching_card = UnoCard('red', '7', 'teal', '7')
    wild_draw = UnoCard('wild', 'wild_draw2', 'wild', 'wild_draw_color')
    room.hands = {
        'alice': [matching_card, wild_draw],
        'bob': [UnoCard('blue', '3', 'orange', '3')],
    }

    success, message = room.play_card('alice', 1, 'blue')

    assert success is True
    assert message == 'alice 打出 W+2，下家需摸 2 张（可挑战/叠加）！'
    assert room.challengeable is True
    assert room.last_wild_player == 'alice'
    assert room.last_wild_had_match is True
    assert room.chosen_color == 'blue'
    assert room.pending_draw == 2
    assert room.pending_draw_type == 'wild_draw2'
    assert room.current_player() == 'bob'
    assert room.hands['alice'] == [matching_card]
    assert room.discard_pile[-1] is wild_draw


def test_uno_game_data_separates_public_and_viewer_state():
    room = UnoRoom('room', ['alice', 'bob'])
    room.state = 'playing'
    room.discard_pile = [
        UnoCard('green', '1', 'teal', '1'),
        UnoCard('wild', 'wild', 'wild', 'wild'),
        UnoCard('red', '3', 'pink', '3'),
    ]
    room.hands = {
        'alice': [
            UnoCard('blue', '2', 'orange', '2'),
            UnoCard('red', '8', 'purple', '8'),
        ],
        'bob': [UnoCard('yellow', '4', 'teal', '4')],
    }
    room.draw_play_card = 1

    player_data = room.get_game_data('alice')
    observer_data = room.get_game_data('observer')

    assert player_data['played_colors'] == ['red', 'green']
    assert player_data['top_card']['label'] == '红3'
    assert player_data['hand_counts'] == {'alice': 2, 'bob': 1}
    assert player_data['playable'] == [1]
    assert player_data['draw_play'] is True
    assert [card['label'] for card in player_data['my_cards']] == ['蓝2', '红8']
    assert 'my_cards' not in observer_data
    assert 'playable' not in observer_data
    assert 'draw_play' not in observer_data

    room.state = 'finished'
    room.winner = 'alice'
    room.scores = {'alice': 4, 'bob': 4}
    finished_data = room.get_game_data('alice')

    assert finished_data['current_player'] == ''
    assert finished_data['winner'] == 'alice'
    assert finished_data['scores'] == {'alice': 4, 'bob': 4}


@pytest.mark.parametrize('engine_type,room_type', [
    (UnoEngine, UnoRoom),
    (LudoEngine, LudoRoom),
])
def test_settlement_requires_finished_room(engine_type, room_type):
    engine = engine_type()
    room = room_type('room', ['alice', 'bob'])
    engine._rooms['room'] = room
    engine._player_room['alice'] = 'room'
    player_data = {'exp': 10, 'gold': 10}

    result = engine._handle_game_over(None, room, 'alice', player_data)

    assert result['action'].endswith('_message')
    assert player_data == {'exp': 10, 'gold': 10}


def test_ludo_three_player_settlement_preserves_rank_rewards_and_messages(
        monkeypatch):
    engine = LudoEngine()
    room = LudoRoom('room', ['alice', 'bob', 'carol'])
    room.state = 'finished'
    room.rankings = ['alice', 'bob', 'carol']
    players = {
        name: get_default_user_template(name=name)
        for name in room.players
    }
    saved = []

    def save(name, data):
        saved.append((name, deepcopy(data)))

    monkeypatch.setattr(PlayerManager, 'save_player_data', save)

    class _Lobby:
        online_players = players

        def __init__(self):
            self.locations = []

        def set_player_location(self, name, location):
            self.locations.append((name, location))

        def get_player_location(self, _name):
            return 'ludo#room'

        def get_commands_for_location(self, _location, _data):
            return [{'name': 'ready'}]

    lobby = _Lobby()
    result = engine._handle_game_over(
        lobby, room, 'alice', players['alice'])

    assert [name for name, _data in saved] == ['alice', 'bob', 'carol']
    assert [players[name]['exp'] for name in room.players] == [120, 100, 80]
    assert [players[name]['gold'] for name in room.players] == [130, 110, 90]
    assert players['alice']['game_stats']['total_wins'] == 1
    assert players['bob']['game_stats']['total_draws'] == 1
    assert players['carol']['game_stats']['total_losses'] == 1

    assert '第一名！' in result['send_to_caller'][0]['text']
    assert '经验 +120  金币 +30' in result['send_to_caller'][0]['text']
    assert '第二名！' in result['send_to_players']['bob'][0]['text']
    assert '经验 +100  金币 +10' in result['send_to_players']['bob'][0]['text']
    assert '第三名！' in result['send_to_players']['carol'][0]['text']
    assert '经验 +80  金币 -10' in result['send_to_players']['carol'][0]['text']
    assert [message['type'] for message in result['send_to_players']['bob']] == [
        GAME, ROOM_UPDATE, LOCATION_UPDATE, COMMANDS_UPDATE,
    ]
    assert lobby.locations == [
        ('alice', 'ludo#room'),
        ('bob', 'ludo#room'),
        ('carol', 'ludo#room'),
    ]
    assert room.state == 'waiting'
    assert room.board is None
    assert room._settled_players == {'alice', 'bob', 'carol'}
    assert room._result_pending == {'alice', 'bob', 'carol'}


def test_uno_three_player_settlement_preserves_rewards_scores_and_messages(
        monkeypatch):
    engine = UnoEngine()
    room = UnoRoom('room', ['alice', 'bob', 'carol'])
    room.state = 'finished'
    room.winner = 'alice'
    room.scores = {'alice': 25, 'bob': 10, 'carol': 0}
    room.hands = {'alice': [], 'bob': [], 'carol': []}
    players = {
        name: get_default_user_template(name=name)
        for name in room.players
    }
    saved = []

    def save(name, data):
        saved.append((name, deepcopy(data)))

    monkeypatch.setattr(PlayerManager, 'save_player_data', save)

    class _Lobby:
        online_players = players

        def __init__(self):
            self.locations = []

        def set_player_location(self, name, location):
            self.locations.append((name, location))

        def get_player_location(self, _name):
            return 'uno#room'

        def get_commands_for_location(self, _location, _data):
            return [{'name': 'ready'}]

    lobby = _Lobby()
    result = engine._handle_game_over(
        lobby, room, 'alice', players['alice'])

    assert [name for name, _data in saved] == ['alice', 'bob', 'carol']
    assert [players[name]['exp'] for name in room.players] == [120, 80, 80]
    assert [players[name]['gold'] for name in room.players] == [130, 97, 97]
    assert players['alice']['game_stats']['total_wins'] == 1
    assert players['bob']['game_stats']['total_losses'] == 1
    assert players['carol']['game_stats']['total_losses'] == 1

    assert 'alice 获胜！' in result['send_to_caller'][0]['text']
    assert '赢家得分: 35' in result['send_to_caller'][0]['text']
    assert '经验 +120  金币 +30' in result['send_to_caller'][0]['text']
    assert 'alice 获胜！' in result['send_to_players']['bob'][0]['text']
    assert '经验 +80  金币 -3' in result['send_to_players']['bob'][0]['text']
    assert set(
        result['send_to_players']['bob'][1]['room_data']['rank_changes']
    ) == {'alice', 'bob', 'carol'}
    assert [message['type'] for message in result['send_to_players']['bob']] == [
        GAME, ROOM_UPDATE, LOCATION_UPDATE, COMMANDS_UPDATE,
    ]
    assert lobby.locations == [
        ('alice', 'uno#room'),
        ('bob', 'uno#room'),
        ('carol', 'uno#room'),
    ]
    assert room.state == 'waiting'
    assert room.hands == {}
    assert room._settled_players == {'alice', 'bob', 'carol'}
    assert room._result_pending == {'alice', 'bob', 'carol'}


@pytest.mark.parametrize('engine_type,room_type,scheduler_type', [
    (UnoEngine, UnoRoom, UnoBotScheduler),
    (LudoEngine, LudoRoom, LudoBotScheduler),
])
def test_settlement_retry_automatically_finishes_after_second_save_failure(
        monkeypatch, engine_type, room_type, scheduler_type):
    engine = engine_type()
    room = room_type('room', ['alice', 'bob'])
    engine._rooms['room'] = room
    engine._player_room.update({'alice': 'room', 'bob': 'room'})
    room.state = 'finished'
    if isinstance(room, UnoRoom):
        room.winner = 'alice'
        room.scores = {'alice': 10, 'bob': 0}
    else:
        room.rankings = ['alice', 'bob']

    players = {
        name: get_default_user_template(name=name)
        for name in ('alice', 'bob')
    }

    class _Lobby:
        def __init__(self):
            self._lock = threading.RLock()
            self.online_players = players
            self.game_engines = {engine.game_key: engine}

        def set_player_location(self, _name, _location):
            pass

        def get_player_location(self, _name):
            return f'{engine.game_key}#room'

        def get_commands_for_location(self, _location, _data):
            return []

    lobby = _Lobby()
    timers = []

    class _Timer:
        def __init__(self, delay, callback, args=()):
            self.delay = delay
            self.callback = callback
            self.args = args
            self.daemon = False

        def start(self):
            timers.append(self)

    monkeypatch.setattr(threading, 'Timer', _Timer)

    dispatched = []

    class _Server:
        lobby_engine = lobby

        def _get_player_data(self, name):
            return players.get(name)

        def dispatch_game_result(
                self, result, caller_socket=None, caller_name=None,
                caller_data=None):
            dispatched.append(result)

    scheduler = scheduler_type(_Server())
    attempts = []
    persisted = {}
    failed = False

    def save(name, data):
        nonlocal failed
        attempts.append(name)
        if name == 'bob' and not failed:
            failed = True
            raise OSError('second-player save failed')
        persisted[name] = deepcopy(data)

    monkeypatch.setattr(PlayerManager, 'save_player_data', save)

    result = engine._handle_game_over(
        lobby, room, 'alice', players['alice'])
    for task in result['schedule']:
        scheduler.handle_schedule(task)

    alice_after_failure = deepcopy(players['alice'])
    assert room.state == 'finished'
    assert room._settled_players == {'alice'}
    assert players['bob']['exp'] == 0
    assert players['bob']['gold'] == 100
    assert len(timers) == 1
    assert engine.handle_command(
        lobby, 'alice', players['alice'], 'start', '') is None

    timer = timers.pop()
    timer.callback(*timer.args)

    assert attempts == ['alice', 'bob', 'bob']
    assert players['alice'] == alice_after_failure
    assert persisted['alice']['exp'] == alice_after_failure['exp']
    assert persisted['alice']['gold'] == alice_after_failure['gold']
    assert players['bob']['exp'] > 0
    assert room._settled_players == {'alice', 'bob'}
    assert room.state == 'waiting'
    assert dispatched[-1]['action'] == f'{engine.game_key}_game_over'
    assert timers == []

    room.reset_match()
    assert room._settled_players == set()
    assert room._settlement_results == {}


@pytest.mark.parametrize('engine_type,room_type,scheduler_type', [
    (UnoEngine, UnoRoom, UnoBotScheduler),
    (LudoEngine, LudoRoom, LudoBotScheduler),
])
def test_match_reset_invalidates_stale_settlement_retry(
        monkeypatch, engine_type, room_type, scheduler_type):
    engine = engine_type()
    room = room_type('room', ['alice', 'bob'])
    engine._rooms['room'] = room
    engine._player_room.update({'alice': 'room', 'bob': 'room'})
    room.state = 'finished'
    if isinstance(room, UnoRoom):
        room.winner = 'alice'
        room.scores = {'alice': 10, 'bob': 0}
    else:
        room.rankings = ['alice', 'bob']
    players = {
        name: get_default_user_template(name=name)
        for name in ('alice', 'bob')
    }

    class _Lobby:
        def __init__(self):
            self._lock = threading.RLock()
            self.online_players = players
            self.game_engines = {engine.game_key: engine}

        def set_player_location(self, _name, _location):
            pass

        def get_player_location(self, _name):
            return f'{engine.game_key}#room'

        def get_commands_for_location(self, _location, _data):
            return []

    lobby = _Lobby()
    timers = []

    class _Timer:
        def __init__(self, _delay, callback, args=()):
            self.callback = callback
            self.args = args
            self.daemon = False

        def start(self):
            timers.append(self)

    monkeypatch.setattr(threading, 'Timer', _Timer)
    attempts = []

    def save(name, _data):
        attempts.append(name)
        if name == 'bob':
            raise OSError('save failed')

    monkeypatch.setattr(PlayerManager, 'save_player_data', save)

    class _Server:
        lobby_engine = lobby

        def dispatch_game_result(self, *_args, **_kwargs):
            raise AssertionError('stale retry must not dispatch')

    result = engine._handle_game_over(
        lobby, room, 'alice', players['alice'])
    scheduler = scheduler_type(_Server())
    scheduler.handle_schedule(result['schedule'][0])
    assert len(timers) == 1
    attempts_before_reset = list(attempts)

    room.reset_match()
    room.state = 'playing'
    timer = timers.pop()
    timer.callback(*timer.args)

    assert attempts == attempts_before_reset
    assert room._settled_players == set()


@pytest.mark.parametrize('engine_type,room_type,scheduler_type', [
    (UnoEngine, UnoRoom, UnoBotScheduler),
    (LudoEngine, LudoRoom, LudoBotScheduler),
])
def test_bot_finish_dispatches_settlement_to_every_human(
        monkeypatch, engine_type, room_type, scheduler_type):
    engine = engine_type()
    room = room_type('room', ['alice', 'Bot_1'])
    room.bots.add('Bot_1')
    room.state = 'finished'
    if isinstance(room, UnoRoom):
        room.winner = 'alice'
        room.scores = {'alice': 10, 'Bot_1': 0}
    else:
        room.rankings = ['alice', 'Bot_1']
    engine._rooms['room'] = room
    engine._player_room.update({'alice': 'room', 'Bot_1': 'room'})
    players = {'alice': get_default_user_template(name='alice')}
    saved = []
    monkeypatch.setattr(
        PlayerManager, 'save_player_data',
        lambda name, _data: saved.append(name))

    class _Lobby:
        def __init__(self):
            self._lock = threading.RLock()
            self.online_players = players
            self.game_engines = {engine.game_key: engine}

        def set_player_location(self, _name, _location):
            pass

        def get_player_location(self, _name):
            return f'{engine.game_key}#room'

        def get_location_path(self, location, _name=None):
            return location

        def get_commands_for_location(self, _location, _data):
            return []

    lobby = _Lobby()
    sent = []
    statuses = []
    player_socket = object()

    class _Server:
        lobby_engine = lobby
        bot_schedulers = {}
        _name_to_socket = {'alice': player_socket}

        def _get_player_data(self, name):
            return players.get(name)

        def send_to_player(self, name, message):
            sent.append((name, message))

        def send_player_status(self, socket, data):
            statuses.append((socket, deepcopy(data)))

        def dispatch_game_result(self, result, **kwargs):
            dispatch_game_result(self, result, **kwargs)

    scheduler = scheduler_type(_Server())
    if isinstance(scheduler, UnoBotScheduler):
        scheduler._broadcast(engine, room, '结束')
    else:
        scheduler._handle_finish(engine, room)

    assert saved == ['alice']
    assert room.state == 'waiting'
    assert any(
        name == 'alice'
        and message.get('type') == GAME
        and '经验 +' in message.get('text', '')
        for name, message in sent
    )
    assert [socket for socket, _data in statuses] == [player_socket]


def test_waiting_room_update_carries_complete_first_frame_metadata():
    class Lobby:
        def get_player_location(self, _name):
            return 'uno#room'

        def _get_game_for_location(self, _location):
            return 'uno'

        def get_location_path(self, location, _name=None):
            return f'大厅 / UNO / {location}'

        def get_commands_for_location(self, _location, _player_data):
            return [{'name': 'ready'}]

    sent = []

    class Server:
        lobby_engine = Lobby()
        bot_schedulers = {}

        def send_to(self, _socket, message):
            sent.append(message)

    dispatch_game_result(
        Server(),
        {
            'send_to_caller': [
                {
                    'type': ROOM_UPDATE,
                    'room_data': {
                        'game_type': 'uno', 'room_state': 'waiting',
                    },
                },
                {'type': 'location_update', 'location': 'uno#room'},
            ],
            'refresh_commands': True,
        },
        caller_socket=object(),
        caller_name='alice',
        caller_data={'name': 'alice'},
    )

    assert sent == [{
        'type': ROOM_UPDATE,
        'room_data': {'game_type': 'uno', 'room_state': 'waiting'},
        'location': 'uno#room',
        'location_path': '大厅 / UNO / uno#room',
        'commands': [{'name': 'ready'}],
    }]


def test_dispatch_game_result_runs_all_protocol_stages_in_order(monkeypatch):
    events = []

    class Lobby:
        _lock = threading.RLock()
        player_locations = {'alice': 'lobby', 'carol': 'lobby'}

        def get_player_location(self, _name):
            return 'uno#room'

        def _get_game_for_location(self, _location):
            return 'uno'

        def get_location_path(self, location, _name=None):
            return location

        def get_commands_for_location(self, _location, _player_data):
            return [{'name': 'play'}]

        def get_all_rooms(self):
            return [{'room_id': 'room'}]

    class Scheduler:
        def handle_schedule(self, task):
            events.append(('schedule', task['action']))

    player_data = {
        'alice': {'name': 'alice'},
        'bob': {'name': 'bob'},
    }

    class Server:
        lobby_engine = Lobby()
        bot_schedulers = {'uno': Scheduler()}
        _name_to_socket = {'bob': 'bob-socket'}

        def send_to(self, socket, message):
            events.append(('send_to', socket, message['type']))

        def send_to_player(self, name, message):
            events.append(('send_to_player', name, message['type']))

        def send_player_status(self, socket, data):
            events.append(('status', socket, data['name']))

        def _get_player_data(self, name):
            return player_data.get(name)

    monkeypatch.setattr(
        PlayerManager,
        'save_player_data',
        lambda name, _data: events.append(('save', name)),
    )
    result = {
        'send_to_caller': [{'type': GAME, 'text': '完成'}],
        'send_to_players': {
            'bob': [{'type': 'hand_update', 'cards': []}],
        },
        'schedule': [{'game_id': 'uno', 'action': 'bot_play'}],
        'save': True,
        'refresh_status': ['alice', 'bob'],
        'refresh_commands': True,
        'refresh_room_list': True,
    }

    dispatch_game_result(
        Server(),
        result,
        caller_socket='alice-socket',
        caller_name='alice',
        caller_data=player_data['alice'],
    )

    assert events == [
        ('send_to', 'alice-socket', GAME),
        ('send_to_player', 'bob', 'game_event'),
        ('schedule', 'bot_play'),
        ('save', 'alice'),
        ('status', 'alice-socket', 'alice'),
        ('status', 'bob-socket', 'bob'),
        ('send_to', 'alice-socket', COMMANDS_UPDATE),
        ('send_to_player', 'alice', 'room_list'),
        ('send_to_player', 'carol', 'room_list'),
    ]


def test_same_primary_room_update_does_not_reopen_window():
    state = ModuleStateManager()
    state.game_board.room_data = {
        'game_type': 'uno',
        'room_state': 'playing',
    }
    screen = Mock()
    screen.engine.primary_id.return_value = 'game-window'
    screen.query_one.side_effect = LookupError

    _on_room_update(RoomUpdate({
        'game_type': 'uno',
        'room_state': 'playing',
        'current_player': 'bob',
    }), Mock(), screen, state)

    screen._prepare_main_window.assert_not_called()
    screen._switch_main_window.assert_not_called()


def test_waiting_room_doc_prefers_chat_and_updates_room(monkeypatch):
    state = ModuleStateManager()
    renderer = Mock()
    rendered_doc = object()
    renderer.render_doc.return_value = rendered_doc
    monkeypatch.setattr(
        'client.protocol.renderer.get_renderer',
        lambda _game_type: renderer,
    )
    chat = Mock()
    board = Mock()
    screen = Mock()
    screen.engine.primary_id.return_value = 'waiting-window'
    screen.query_one.side_effect = {
        '#wait-chat': chat,
        '#game-board': board,
    }.__getitem__
    room_data = {
        'game_type': 'uno',
        'room_state': 'waiting',
        'doc': ['帮助内容'],
    }

    _on_room_update(
        RoomUpdate(room_data, message='已打开帮助。'),
        Mock(), screen, state,
    )

    renderer.render_doc.assert_called_once_with(['帮助内容'])
    chat.show_doc.assert_called_once_with(rendered_doc)
    board.show_doc.assert_not_called()
    assert state.game_board.room_data == room_data
    assert state.cmd.lines[-1].endswith('已打开帮助。')


def test_same_primary_room_update_closes_visible_docs():
    state = ModuleStateManager()
    state.game_board.room_data = {'room_state': 'playing'}
    board = Mock()
    board._showing_doc = True
    chat = Mock()
    chat._showing_doc = True
    indicator = Mock()
    screen = Mock()
    screen.engine.primary_id.return_value = 'game-window'
    screen.query_one.side_effect = {
        '#game-board': board,
        '#wait-chat': chat,
        '#tile-indicator': indicator,
    }.__getitem__

    _on_room_update(
        RoomUpdate({'room_state': 'playing'}),
        Mock(), screen, state,
    )

    board.close_doc.assert_called_once_with()
    chat.close_doc.assert_called_once_with()


def test_pending_target_room_update_replaces_staged_context():
    state = ModuleStateManager()
    state.game_board.room_data = {
        'game_type': 'uno',
        'room_state': 'waiting',
    }
    screen = Mock()
    screen.engine.primary_id.return_value = 'game-window'
    screen.query_one.side_effect = LookupError
    commands = [{'name': 'ready', 'label': '准备'}]

    _on_room_update(RoomUpdate({
        'game_type': 'uno',
        'room_state': 'waiting',
        'players': ['alice', 'bob'],
    }, commands=commands), Mock(), screen, state)

    screen._prepare_main_window.assert_called_once_with('waiting', commands)
    screen._switch_main_window.assert_called_once()


def test_lobby_room_update_carries_complete_first_frame_metadata():
    class Lobby:
        def get_player_location(self, _name):
            return 'lobby'

        def _get_game_for_location(self, _location):
            return ''

        def get_location_path(self, _location, _name=None):
            return '大厅'

        def get_commands_for_location(self, _location, _player_data):
            return [{'name': 'games'}]

    sent = []

    class Server:
        lobby_engine = Lobby()
        bot_schedulers = {}

        def send_to(self, _socket, message):
            sent.append(message)

    dispatch_game_result(
        Server(),
        {'send_to_caller': [
            {'type': GAME, 'text': '离开了房间。'},
            {
                'type': ROOM_UPDATE,
                'room_data': {'game_type': 'uno', 'room_state': 'lobby'},
            },
        ]},
        caller_socket=object(),
        caller_name='alice',
        caller_data={'name': 'alice'},
    )

    assert len(sent) == 1
    assert sent[0]['message'] == '离开了房间。'
    assert sent[0]['location'] == 'lobby'
    assert sent[0]['location_path'] == '大厅'
    assert sent[0]['commands'] == [{'name': 'games'}]


def test_playing_room_update_carries_complete_first_frame_commands():
    class Lobby:
        def get_player_location(self, _name):
            return 'uno#room'

        def _get_game_for_location(self, _location):
            return 'uno'

        def get_location_path(self, _location, _name=None):
            return 'UNO > #room 对局中'

        def get_commands_for_location(self, _location, _player_data):
            return [
                {'name': 'play'},
                {'name': 'back', 'label': '返回'},
                {'name': 'help', 'label': '帮助'},
            ]

    sent = []

    class Server:
        lobby_engine = Lobby()
        bot_schedulers = {}

        def send_to(self, _socket, message):
            sent.append(message)

    dispatch_game_result(
        Server(),
        {'send_to_caller': [{
            'type': ROOM_UPDATE,
            'room_data': {'game_type': 'uno', 'room_state': 'playing'},
        }]},
        caller_socket=object(),
        caller_name='alice',
        caller_data={'name': 'alice'},
    )

    assert sent[0]['commands'] == [
        {'name': 'play'},
        {'name': 'back', 'label': '返回'},
        {'name': 'help', 'label': '帮助'},
    ]


def test_main_window_context_commit_does_not_overwrite_prepared_controls():
    screen = Mock()
    screen.state = ModuleStateManager()

    GameScreen._commit_main_window_context(
        screen,
        [{'name': 'back', 'label': '返回'}],
        'uno#room',
        'UNO > #room',
    )

    screen._update_room_controls.assert_not_called()
    screen._update_location.assert_called_once_with(
        'uno#room', 'UNO > #room',
    )


def test_main_window_commands_wait_for_target_presentation_prepare():
    controls = Mock()
    window = Mock()
    window.query_one.return_value = controls
    staged = []
    window.stage_presentation.side_effect = staged.append
    screen = Mock()
    screen.engine.get_window.return_value = window

    GameScreen._prepare_main_window(
        screen,
        'game',
        [
            {'name': 'play', 'label': '出牌'},
            {'name': 'back', 'label': '返回'},
        ],
    )

    controls.prepare_context.assert_not_called()
    assert len(staged) == 1

    staged[0]()

    controls.prepare_context.assert_called_once()


@pytest.mark.parametrize('player_count', range(2, 11))
def test_uno_pvp_rewards_are_positive_net_and_conform(player_count):
    rewards = UnoEngine._REWARDS
    win_exp, win_gold = rewards['win']
    loss_exp, loss_gold = rewards['loss']

    assert rewards['win'] == [120, 30]
    assert rewards['loss'] == [80, -3]
    assert rewards['gold_ratio_bot'] == pytest.approx(0.15)
    assert 0.20 <= win_gold / win_exp <= 0.25
    assert abs(loss_gold) / loss_exp < 0.20
    assert win_gold + loss_gold * (player_count - 1) > 0


def test_registered_handlers_keep_interaction_per_state_manager():
    first = ModuleStateManager()
    second = ModuleStateManager()
    first.chat.set_player_name('alice')
    second.chat.set_player_name('bob')
    handler = _uno_handler()
    room_data = {
        'game_type': 'uno',
        'room_state': 'playing',
        'current_player': 'alice',
        'my_cards': [{'value': '1'}],
        'playable': [0],
    }

    handler.on_room_update(room_data, _ctx(first))

    assert vars(handler) == {}
    assert first.game_interaction.snapshot('uno')['my_turn'] is True
    assert second.game_interaction.snapshot('uno') is None


def test_uno_menu_navigation_and_reset_notify_state():
    state = ModuleStateManager()
    state.chat.set_player_name('alice')
    handler = _uno_handler()
    ctx = _ctx(state)
    events = []
    state.game_interaction.add_listener(
        lambda event, *args: events.append((event, args)))
    room_data = {
        'game_type': 'uno',
        'room_state': 'playing',
        'current_player': 'alice',
        'my_cards': [{'value': '1'}, {'value': '2'}],
        'playable': [0, 1],
    }
    state.game_board.update_room(room_data)
    handler.on_room_update(room_data, ctx)

    assert handler.handle_event('select_menu', {
        'title': '出牌',
        'items': [
            {'label': '1', 'command': '/play 0'},
            {'label': '摸牌', 'command': '/draw'},
        ],
    }, ctx)
    handler.on_nav('down', ctx)
    assert state.game_interaction.snapshot('uno')['row'] == 1

    handler.on_room_update({'room_state': 'waiting'}, ctx)
    assert state.game_interaction.snapshot('uno') is None
    assert [event for event, _ in events].count('update') >= 3
    assert events[-1][0] == 'reset'


def test_ludo_delayed_callback_isolated_from_replacement_state():
    old_state = ModuleStateManager()
    new_state = ModuleStateManager()
    old_state.chat.set_player_name('alice')
    new_state.chat.set_player_name('alice')
    old_timers = []
    handler = _ludo_handler()
    moving = {
        'game_type': 'ludo',
        'room_state': 'playing',
        'current_player': 'alice',
        'player_colors': {'alice': 'red', 'bob': 'blue'},
        'last_move': {
            'seq': 1,
            'color': 'red',
            'piece_idx': 0,
            'path': [{'state': 'track'}, {'state': 'runway'}],
        },
    }
    stationary = {
        'game_type': 'ludo',
        'room_state': 'playing',
        'current_player': 'alice',
        'player_colors': {'alice': 'red', 'bob': 'blue'},
    }

    handler.on_room_update(moving, _ctx(old_state, timers=old_timers))
    handler.on_room_update(stationary, _ctx(new_state))
    replacement_snapshot = new_state.game_interaction.snapshot('ludo')
    old_state.game_interaction.reset()

    old_timers[0][1]()

    assert vars(handler) == {}
    assert old_state.game_interaction.snapshot('ludo') is None
    assert new_state.game_interaction.snapshot('ludo') == replacement_snapshot


def test_logout_replacement_and_board_rebind_invalidate_old_ludo_timer(
        monkeypatch):
    from client.companion import CompanionController

    monkeypatch.setattr(CompanionController, "_instance", None)
    old_state = ModuleStateManager()
    old_state.chat.set_player_name('alice')
    old_timers = []
    handler = _ludo_handler()
    moving = {
        'game_type': 'ludo',
        'room_state': 'playing',
        'current_player': 'alice',
        'player_colors': {'alice': 'red', 'bob': 'blue'},
        'last_move': {
            'seq': 1,
            'color': 'red',
            'piece_idx': 0,
            'path': [{'state': 'track'}, {'state': 'runway'}],
        },
    }
    handler.on_room_update(moving, _ctx(old_state, timers=old_timers))
    panel = GameBoardPanel()
    panel.bind_state(old_state)
    panel._refresh = Mock()
    old_events = []
    for state_part in (
            old_state.chat, old_state.cmd, old_state.status, old_state.online,
            old_state.game_board, old_state.game_interaction, old_state.notify,
            old_state.auth):
        state_part.add_listener(
            lambda event, *args: old_events.append((event, args)))

    class _Engine:
        def __init__(self):
            self.login_window = Mock()

        def close_all(self):
            pass

        def get_window(self, window_id):
            if window_id == "login-window":
                return self.login_window
            return None

        def set_primary(self, _window_id):
            pass

    screen = type("_Screen", (), {})()
    screen._mode = 'normal'
    screen.engine = _Engine()
    screen.state = old_state
    screen.mode = 'game'

    asyncio.run(GameScreen._rebuild_to_login_layout(screen))
    replacement_state = screen.state
    assert all(not state_part._listeners for state_part in (
        old_state.chat, old_state.cmd, old_state.status, old_state.online,
        old_state.game_board, old_state.game_interaction, old_state.notify,
        old_state.auth,
    ))
    old_events.clear()
    panel._refresh.reset_mock()
    old_state.game_board.update_room({'room_state': 'waiting'})
    old_state.online.update_users(['ghost'])
    assert old_events == []
    panel._refresh.assert_not_called()

    panel.bind_state(replacement_state)
    panel._refresh.reset_mock()
    replacement_state.game_board.update_room({'room_state': 'waiting'})
    old_timers[0][1]()

    assert old_state.game_interaction.snapshot('ludo') is None
    assert len(old_timers) == 1
    assert panel._on_event not in old_state.game_board._listeners
    assert (
        panel._on_interaction_event
        not in old_state.game_interaction._listeners
    )
    assert panel._on_event in replacement_state.game_board._listeners
    assert (
        panel._on_interaction_event
        in replacement_state.game_interaction._listeners
    )
    screen.engine.login_window.reset_session.assert_called_once()
    panel._refresh.assert_called_once()


def test_ludo_menu_navigation_and_reset_notify_state():
    state = ModuleStateManager()
    state.chat.set_player_name('alice')
    handler = _ludo_handler()
    ctx = _ctx(state)
    events = []
    state.game_interaction.add_listener(
        lambda event, *args: events.append((event, args)))
    room_data = {
        'game_type': 'ludo',
        'room_state': 'playing',
        'current_player': 'alice',
        'player_colors': {'alice': 'red', 'bob': 'blue'},
        'pending_move': True,
        'move_previews': {
            '0': {'path': [{'track_pos': 1}]},
            '1': {'path': [{'track_pos': 2}]},
        },
    }
    state.game_board.update_room(room_data)
    handler.on_room_update(room_data, ctx)
    handler.handle_event('select_menu', {
        'title': '选择棋子',
        'items': [
            {'label': '棋子 1', 'command': '/move 0'},
            {'label': '棋子 2', 'command': '/move 1'},
        ],
    }, ctx)

    interaction = state.game_interaction.snapshot('ludo')
    assert list(interaction['move_previews']) == ['0']
    assert interaction['blink_running'] is True

    handler.on_nav('right', ctx)
    interaction = state.game_interaction.snapshot('ludo')
    assert interaction['btn_cursor'] == 1
    assert list(interaction['move_previews']) == ['1']

    handler.on_room_update({'room_state': 'waiting'}, ctx)
    assert state.game_interaction.snapshot('ludo') is None
    assert [event for event, _ in events].count('update') >= 3
    assert events[-1][0] == 'reset'


def test_room_dispatch_activates_and_clears_interaction_state():
    state = ModuleStateManager()
    state.chat.set_player_name('alice')
    timers = []

    class _App:
        def set_timer(self, delay, callback):
            timers.append((delay, callback))

        def send_command(self, command):
            raise AssertionError(f'unexpected command: {command}')

    class _Screen:
        def get_module(self, _name):
            return None

        def _prepare_main_window(self, _target, _commands):
            pass

        def query_one(self, _selector):
            raise LookupError

    room_data = {
        'game_type': 'uno',
        'room_state': 'playing',
        'current_player': 'alice',
        'my_cards': [{'value': '1'}],
        'playable': [0],
    }
    app = _App()
    screen = _Screen()

    _on_room_update(RoomUpdate(room_data), app, screen, state)

    assert state.game_board.room_data == room_data
    assert state.game_interaction.snapshot('uno')['playing'] is True

    _on_room_leave(RoomLeave(), app, screen, state)

    assert state.game_board.room_data == {}
    assert state.game_interaction.snapshot('uno') is None
