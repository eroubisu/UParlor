"""Wordle 游戏引擎 — 房间制猜词游戏

per_player=False 共享实例，玩家通过 create 创建房间 → start 开始。
位置层级: wordle_lobby → wordle_room (等待) → wordle_playing (游戏中)
"""

from __future__ import annotations

import json
import os
import random
import string

from english_words import get_english_words_set

from ...game_core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE

_dir = os.path.dirname(__file__)

MAX_GUESSES = 6
WORD_LENGTH = 5


def _load_answers() -> list[str]:
    path = os.path.join(_dir, 'words.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _build_valid_set() -> set[str]:
    """从 english-words 库获取全部 5 字母合法词"""
    return {w.lower() for w in get_english_words_set(['web2'])
            if len(w) == WORD_LENGTH and w.isalpha()}


_ANSWERS = _load_answers()
_VALID_WORDS = _build_valid_set() | set(_ANSWERS)


def _load_help() -> str:
    path = os.path.join(_dir, 'help.txt')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


_HELP_TEXT = _load_help()


def _evaluate_guess(answer: str, guess: str) -> list[str]:
    """评估猜测，返回每个字母的状态列表。

    'correct' = 位置正确 (绿)
    'present' = 字母存在但位置错 (黄)
    'absent'  = 字母不存在 (灰)
    """
    result = ['absent'] * WORD_LENGTH
    answer_chars = list(answer)

    # 第一遍: 标记正确位置
    for i in range(WORD_LENGTH):
        if guess[i] == answer[i]:
            result[i] = 'correct'
            answer_chars[i] = None

    # 第二遍: 标记存在但位置错误
    for i in range(WORD_LENGTH):
        if result[i] == 'correct':
            continue
        if guess[i] in answer_chars:
            result[i] = 'present'
            answer_chars[answer_chars.index(guess[i])] = None

    return result


def _gen_room_id() -> str:
    """生成 4 字符房间 ID"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))


class WordleRoom:
    """Wordle 房间"""

    __slots__ = ('room_id', 'host', 'state', 'answer',
                 'guesses', 'results', 'letter_states')

    def __init__(self, room_id: str, host: str):
        self.room_id = room_id
        self.host = host
        self.state = 'waiting'  # waiting → playing → finished
        self.answer: str | None = None
        self.guesses: list[str] = []
        self.results: list[list[str]] = []
        self.letter_states: dict[str, str] = {}

    def start(self):
        self.answer = random.choice(_ANSWERS)
        self.state = 'playing'

    def guess(self, word: str) -> list[str]:
        result = _evaluate_guess(self.answer, word)
        self.guesses.append(word)
        self.results.append(result)
        # 更新字母状态
        priority = {'correct': 3, 'present': 2, 'absent': 1, 'unknown': 0}
        for ch, st in zip(word, result):
            old = self.letter_states.get(ch, 'unknown')
            if priority.get(st, 0) > priority.get(old, 0):
                self.letter_states[ch] = st
        # 检查结束
        if word == self.answer:
            self.state = 'finished'
            return result
        if len(self.guesses) >= MAX_GUESSES:
            self.state = 'finished'
        return result

    @property
    def won(self) -> bool:
        return self.state == 'finished' and bool(self.guesses) and self.guesses[-1] == self.answer

    @property
    def finished(self) -> bool:
        return self.state == 'finished'

    def get_board_data(self) -> dict:
        """构建客户端渲染用数据"""
        return {
            'game_type': 'wordle',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'guesses': self.guesses,
            'results': self.results,
            'max_guesses': MAX_GUESSES,
            'word_length': WORD_LENGTH,
            'finished': self.finished,
            'won': self.won,
            'answer': self.answer if self.finished else None,
            'letter_states': self.letter_states,
        }


class WordleEngine(BaseGameEngine):
    """Wordle 游戏引擎 — 房间制

    所有游戏反馈通过 ROOM_UPDATE 传递到客户端游戏面板。
    room_data 可选字段: doc(文档), message(状态消息)
    """

    game_key = 'wordle'

    def __init__(self):
        self._rooms: dict[str, WordleRoom] = {}
        self._player_room: dict[str, str] = {}  # player_name → room_id

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        cmd_name = cmd.lstrip('/')
        location = lobby.get_player_location(player_name)

        if location == 'wordle_lobby':
            if cmd_name == 'create':
                return self._cmd_create(lobby, player_name)
            if cmd_name == 'rooms':
                return self._cmd_rooms(player_name)
        elif location == 'wordle_room':
            if cmd_name == 'start':
                return self._cmd_start(lobby, player_name)
            if cmd_name == 'leave':
                return self._cmd_leave(lobby, player_name)
        elif location == 'wordle_playing':
            if cmd_name == 'guess':
                return self._cmd_guess(lobby, player_name, args)

        return None

    def handle_disconnect(self, lobby, player_name):
        self._remove_player(player_name)
        return []

    def handle_back(self, lobby, player_name, player_data):
        location = lobby.get_player_location(player_name)
        if location == 'wordle_playing':
            return self._cmd_back_playing(lobby, player_name)
        if location == 'wordle_finished':
            return self._cmd_back_finished(lobby, player_name)
        if location == 'wordle_room':
            return self._cmd_leave(lobby, player_name)
        return self.handle_quit(lobby, player_name, player_data)

    def handle_quit(self, lobby, player_name, player_data):
        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'world_library')
        return {
            'action': 'location_update',
            'location': 'world_library',
            'message': '离开了 Wordle。',
            'refresh_commands': True,
        }

    def get_welcome_message(self, player_data):
        board = self._lobby_board()
        board['doc'] = _HELP_TEXT
        return {
            'send_to_caller': [
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'wordle_lobby'},
            ],
            'location': 'wordle_lobby',
            'refresh_commands': True,
        }

    # ── 辅助方法 ──

    def _lobby_board(self) -> dict:
        """空白大厅面板数据"""
        return {'game_type': 'wordle', 'room_state': 'lobby'}

    def _msg(self, player_name, text):
        """返回带消息的 room_data 更新（显示在游戏面板内）"""
        room_id = self._player_room.get(player_name)
        room = self._rooms.get(room_id) if room_id else None
        board = room.get_board_data() if room else self._lobby_board()
        board['message'] = text
        # lobby 状态下保留帮助文档
        if board.get('room_state') == 'lobby':
            board['doc'] = _HELP_TEXT
        return {
            'action': 'wordle_message',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
        }

    def _remove_player(self, player_name: str):
        room_id = self._player_room.pop(player_name, None)
        if room_id:
            self._rooms.pop(room_id, None)

    # ── 指令实现 ──

    def _cmd_create(self, lobby, player_name):
        self._remove_player(player_name)
        room_id = _gen_room_id()
        while room_id in self._rooms:
            room_id = _gen_room_id()
        room = WordleRoom(room_id, player_name)
        self._rooms[room_id] = room
        self._player_room[player_name] = room_id
        lobby.set_player_location(player_name, 'wordle_room')
        return {
            'action': 'wordle_room_created',
            'send_to_caller': [
                {'type': GAME, 'text': f'创建了 Wordle 房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_board_data()},
                {'type': LOCATION_UPDATE, 'location': 'wordle_room'},
            ],
            'refresh_commands': True,
        }

    def _cmd_rooms(self, player_name):
        if not self._rooms:
            return self._msg(player_name, '暂无房间。')
        lines = ['当前房间:']
        for room in self._rooms.values():
            label = {'waiting': '等待中', 'playing': '进行中', 'finished': '已结束'}
            lines.append(f'  #{room.room_id}  {room.host}  {label.get(room.state, room.state)}')
        return self._msg(player_name, '\n'.join(lines))

    def _cmd_start(self, lobby, player_name):
        room_id = self._player_room.get(player_name)
        room = self._rooms.get(room_id) if room_id else None
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已经开始或已结束。')
        room.start()
        lobby.set_player_location(player_name, 'wordle_playing')
        return {
            'action': 'wordle_start',
            'send_to_caller': [
                {'type': GAME, 'text': 'Wordle 游戏开始'},
                {'type': ROOM_UPDATE, 'room_data': room.get_board_data()},
                {'type': LOCATION_UPDATE, 'location': 'wordle_playing'},
            ],
            'refresh_commands': True,
        }

    def _cmd_leave(self, lobby, player_name):
        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'wordle_lobby')
        board = self._lobby_board()
        board['doc'] = _HELP_TEXT
        return {
            'action': 'wordle_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'wordle_lobby'},
            ],
            'refresh_commands': True,
        }

    def _cmd_guess(self, lobby, player_name, word):
        room_id = self._player_room.get(player_name)
        room = self._rooms.get(room_id) if room_id else None
        if not room or room.finished:
            return self._msg(player_name, '没有进行中的游戏。')

        word = word.strip().lower() if word else ''
        if len(word) != WORD_LENGTH:
            return self._msg(player_name, f'需要 {WORD_LENGTH} 个字母。')
        if not word.isalpha():
            return self._msg(player_name, '只能输入英文字母。')
        if word not in _VALID_WORDS:
            return self._msg(player_name, f'"{word}" 不在词库中。')

        room.guess(word)
        board = room.get_board_data()

        if room.won:
            board['message'] = '恭喜！'
            attempts = len(room.guesses)
            lobby.set_player_location(player_name, 'wordle_finished')
            return {
                'action': 'wordle_win',
                'send_to_caller': [
                    {'type': GAME, 'text': f'Wordle 胜利！{attempts}/{MAX_GUESSES} 次猜出'},
                    {'type': ROOM_UPDATE, 'room_data': board},
                    {'type': LOCATION_UPDATE, 'location': 'wordle_finished'},
                ],
                'refresh_commands': True,
            }
        elif room.finished:
            board['message'] = '很遗憾'
            answer = room.answer or '?????'
            lobby.set_player_location(player_name, 'wordle_finished')
            return {
                'action': 'wordle_lose',
                'send_to_caller': [
                    {'type': GAME, 'text': f'Wordle 失败，答案: {answer.upper()}'},
                    {'type': ROOM_UPDATE, 'room_data': board},
                    {'type': LOCATION_UPDATE, 'location': 'wordle_finished'},
                ],
                'refresh_commands': True,
            }
        else:
            return {
                'action': 'wordle_guess',
                'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
            }

    def _cmd_back_playing(self, lobby, player_name):
        """playing 时 back — 放弃并直接回到房间（客户端已确认）"""
        room_id = self._player_room.get(player_name)
        room = self._rooms.get(room_id) if room_id else None
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')

        answer = room.answer or '?????'
        # 重置房间为等待状态
        room.state = 'waiting'
        room.answer = None
        room.guesses = []
        room.results = []
        room.letter_states = {}
        lobby.set_player_location(player_name, 'wordle_room')
        return {
            'action': 'wordle_giveup',
            'send_to_caller': [
                {'type': GAME, 'text': f'已放弃，答案: {answer.upper()}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_board_data()},
                {'type': LOCATION_UPDATE, 'location': 'wordle_room'},
            ],
            'refresh_commands': True,
        }

    def _cmd_back_finished(self, lobby, player_name):
        """finished 时 back — 重置房间回到 room"""
        room_id = self._player_room.get(player_name)
        room = self._rooms.get(room_id) if room_id else None
        if room:
            room.state = 'waiting'
            room.answer = None
            room.guesses = []
            room.results = []
            room.letter_states = {}
            lobby.set_player_location(player_name, 'wordle_room')
            return {
                'action': 'wordle_back_to_room',
                'send_to_caller': [
                    {'type': GAME, 'text': '返回房间'},
                    {'type': ROOM_UPDATE, 'room_data': room.get_board_data()},
                    {'type': LOCATION_UPDATE, 'location': 'wordle_room'},
                ],
                'refresh_commands': True,
            }
        # 房间已不存在，回大厅
        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'wordle_lobby')
        board = self._lobby_board()
        board['doc'] = _HELP_TEXT
        return {
            'action': 'wordle_back_to_lobby',
            'send_to_caller': [
                {'type': GAME, 'text': '房间已关闭，返回大厅'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'wordle_lobby'},
            ],
            'refresh_commands': True,
        }
