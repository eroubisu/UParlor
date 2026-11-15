"""每个已注册游戏都必须遵守的共享契约（新游戏注册后自动纳入）。

这些契约曾经各游戏单独违反过：棒球的 add_bot 返回整句话、放弃要确认两次、
画出来的字形没有登记。把它们写成一组参数化测试，新游戏照着同一张表过一遍。
"""

from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

import client.games  # noqa: F401  注册客户端渲染器与处理器
from client.config import GAME_GLYPHS, GAME_TEXT_GLYPHS
from client.protocol.handler import HANDLER_REGISTRY
from client.protocol.renderer import RENDERER_REGISTRY
from client.window_engine.text import cell_width
from server import chat_server as chat_server_module
from server.games import GAMES
from server.player.manager import PlayerManager, get_default_user_template

GAME_IDS = sorted(GAMES)
BOARD_SIZES = ((46, 19), (80, 30))
SELECT_MENU = 'select_menu'


class _Table:
    """一个真人 + 机器人把房间坐满并开局的现场（和游戏无关的通用夹具）。"""

    def __init__(self, monkeypatch, game: str) -> None:
        monkeypatch.setattr(chat_server_module, 'ChatLogManager', Mock)
        monkeypatch.setattr(chat_server_module, 'DMLogManager', Mock)
        monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())
        monkeypatch.setattr(threading, 'Timer', Mock)
        self.server = chat_server_module.ChatServer()
        self.lobby = self.server.lobby_engine
        self.engine = self.lobby._ensure_engine(game)
        self.human = 'human'
        self.data = get_default_user_template(name=self.human,
                                              password_hash='x')
        self.data.pop('password_hash', None)
        self.lobby.register_player(self.human, self.data)
        self.lobby.set_player_location(self.human, game)

    def command(self, name: str, arg: str = '') -> dict:
        return self.engine.handle_command(
            self.lobby, self.human, self.data, name, arg)

    @property
    def room(self):
        return self.engine.get_player_room(self.human)

    def add_bot(self) -> dict:
        return self.command('bot')

    def start_full_match(self) -> None:
        self.command('create')
        while not self.room.is_full():
            self.add_bot()
        self.command('start')
        assert self.room.state == 'playing'


@pytest.fixture(params=GAME_IDS)
def table(request, monkeypatch) -> _Table:
    return _Table(monkeypatch, request.param)


def test_every_server_game_has_a_matching_client_renderer_and_handler():
    assert set(GAMES) == set(RENDERER_REGISTRY) == set(HANDLER_REGISTRY)


def test_adding_a_bot_announces_exactly_one_clear_line(table):
    table.command('create')

    result = table.add_bot()

    bot = next(name for name in table.room.players if name != table.human)
    texts = [message['text'] for message in result['send_to_caller']
             if message.get('type') == 'game']
    assert texts == [f'已添加机器人: {bot}']
    assert table.room.is_bot(bot)


@pytest.mark.parametrize('leave', ('handle_back', 'handle_quit'))
def test_leaving_a_match_confirms_once_and_then_forfeits(table, leave):
    table.start_full_match()

    menu = getattr(table.engine, leave)(
        table.lobby, table.human, table.data)['send_to_caller'][0]
    assert menu['type'] == SELECT_MENU
    yes = next(item for item in menu['items'] if item.get('label') == '是')
    name, _, arg = yes['command'].removeprefix('/').partition(' ')
    result = table.command(name, arg)

    messages = [*result.get('send_to_caller', []),
                *(m for batch in result.get('send_to_players', {}).values()
                  for m in batch)]
    assert all(message.get('type') != SELECT_MENU for message in messages)
    assert table.room.state == 'waiting'


def test_every_rendered_glyph_is_declared_by_its_renderer(table):
    game = table.engine.game_key
    renderer = RENDERER_REGISTRY[game]
    table.start_full_match()
    undeclared = set()
    for viewer in table.room.players:
        if table.room.is_bot(viewer):
            continue
        data = table.room.get_game_data(viewer=viewer)
        for width, height in BOARD_SIZES:
            sections = renderer.render_board(data, None, width, height)
            for section in sections.values():
                text = getattr(section, 'plain', None)
                if text is None:
                    continue
                for char in text:
                    if (ord(char) > 127 and cell_width(char) == 1
                            and char not in renderer.glyphs
                            and char not in GAME_TEXT_GLYPHS):
                        undeclared.add(char)
    assert not undeclared, [f'U+{ord(c):04X}' for c in sorted(undeclared)]


def test_declared_renderer_glyphs_belong_to_the_central_contract():
    for game, renderer in RENDERER_REGISTRY.items():
        assert renderer.glyphs <= GAME_GLYPHS, game


def test_the_forfeit_command_confirms_before_it_forfeits(table):
    table.start_full_match()

    first = table.command('forfeit')

    assert [m['type'] for m in first['send_to_caller']] == [SELECT_MENU]
    assert table.room.state == 'playing'          # 只弹了确认，还没放弃
    second = table.command('forfeit', 'yes')
    assert all(m.get('type') != SELECT_MENU
               for m in second.get('send_to_caller', []))
    assert table.room.state == 'waiting'


def test_login_fields_declare_the_english_input_method_the_server_rule_implies():
    """服务器只收英文字母和数字的用户名，登录框就必须声明英文输入法（两边规则绑在一起）。"""
    from client.views.login import LoginPanel
    from server.player.auth import validate_username

    assert validate_username('张三') is not None
    assert validate_username('alice01') is None

    panel = LoginPanel.__new__(LoginPanel)
    panel._tab, panel._submitted, panel._auth_state = 'login', False, None
    for step in ('username', 'password'):
        panel._step = step
        assert panel.input_spec().english_ime


def test_kick_asks_for_confirmation_with_the_target_name_before_acting(table):
    table.command('create')
    table.add_bot()
    bot = next(name for name in table.room.players if name != table.human)

    first = table.command('kick', f'@{bot}')

    menu = first['send_to_caller'][0]
    assert menu['type'] == SELECT_MENU
    assert menu['confirm'] == {'message': f'确认踢出 {bot}?',
                               'command': f'/kick @{bot} yes'}
    assert bot in table.room.players                   # 只问了，还没踢
    table.command('kick', f'@{bot} yes')
    assert bot not in table.room.players


def test_every_confirmation_carries_the_shared_confirm_payload(table):
    table.start_full_match()

    menu = table.command('forfeit')['send_to_caller'][0]

    assert menu['confirm'] == {'message': '确认放弃对局?',
                               'command': '/forfeit yes'}


def test_invite_confirmation_names_the_friend_and_resends_with_yes(table):
    request = table.engine._confirm_menu('invite', '@alice')

    assert request['send_to_caller'][0]['confirm'] == {
        'message': '确认邀请 alice?', 'command': '/invite @alice yes'}
