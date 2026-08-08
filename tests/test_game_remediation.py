"""Replay, reward, and per-session game interaction regressions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import random
import threading
from unittest.mock import Mock

import pytest

from client.games.ludo.handler import LudoHandler
from client.games.uno.handler import UnoHandler
from client.net.dispatch.game import _on_room_leave, _on_room_update
from client.net.messages import RoomLeave, RoomUpdate
from client.protocol.handler import (
    GameHandlerContext,
    get_handler,
)
from client.screen import GameScreen
from client.state import ModuleStateManager
from client.views.game.board import GameBoardPanel
from server.games.ludo.engine import LudoBotScheduler, LudoEngine
from server.games.ludo.room import LudoRoom
from server.games.uno.engine import UnoBotScheduler, UnoEngine
from server.games.uno.room import UnoRoom
from server.core.result_dispatcher import dispatch_game_result
from server.msg_types import GAME
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

    handler.on_nav('right', ctx)
    assert state.game_interaction.snapshot('ludo')['btn_cursor'] == 1

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
