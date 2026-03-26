"""Wordle 游戏引擎 — 房间制猜词游戏（支持 1-4 人）

per_player=False 共享实例，玩家通过 create 创建房间 → start 开始。
位置层级: wordle_lobby → wordle_room (等待) → wordle_playing (游戏中)

单人模式: 创建房间后直接开始，根据猜测次数发放奖励。
多人模式: 邀请好友后开始，所有人共用同一答案，实时看到所有猜测。
          第一个猜对的人获胜，游戏立即结束。
"""

from __future__ import annotations

import json
import os
import random
import string
import time

from english_words import get_english_words_set

from ...game_core.protocol import BaseGameEngine
from ...msg_types import GAME, ROOM_UPDATE, LOCATION_UPDATE

_dir = os.path.dirname(__file__)

MAX_GUESSES = 6
WORD_LENGTH = 5
MAX_PLAYERS = 4

_INVITE_EXPIRE = 240


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


def _load_rewards() -> dict:
    path = os.path.join(_dir, 'rewards.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


_REWARDS = _load_rewards()


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
    """Wordle 多人房间

    players: 玩家列表 (最多 MAX_PLAYERS)
    player_guesses: {player_name: [guesses]}
    player_results: {player_name: [results]}
    player_letter_states: {player_name: {letter: state}}
    player_finished: {player_name: bool}
    winner: 第一个猜对的玩家 (None 如果无人猜对)
    """

    def __init__(self, room_id: str, host: str):
        self.room_id = room_id
        self.host = host
        self.state = 'waiting'  # waiting → playing → finished
        self.answer: str | None = None
        self.players: list[str] = [host]
        # 每个玩家独立的猜测状态
        self.player_guesses: dict[str, list[str]] = {}
        self.player_results: dict[str, list[list[str]]] = {}
        self.player_letter_states: dict[str, dict[str, str]] = {}
        self.player_finished: dict[str, bool] = {}
        self.winner: str | None = None
        self._multiplayer: bool = False

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def is_multiplayer(self) -> bool:
        return self.player_count > 1

    def is_full(self) -> bool:
        return self.player_count >= MAX_PLAYERS

    def add_player(self, name: str) -> bool:
        if name in self.players or self.is_full():
            return False
        self.players.append(name)
        return True

    def remove_player(self, name: str):
        if name in self.players:
            self.players.remove(name)
            self.player_guesses.pop(name, None)
            self.player_results.pop(name, None)
            self.player_letter_states.pop(name, None)
            self.player_finished.pop(name, None)

    def start(self):
        self.answer = random.choice(_ANSWERS)
        self.state = 'playing'
        self._multiplayer = len(self.players) > 1
        for p in self.players:
            self.player_guesses[p] = []
            self.player_results[p] = []
            self.player_letter_states[p] = {}
            self.player_finished[p] = False

    def guess(self, player_name: str, word: str) -> list[str]:
        result = _evaluate_guess(self.answer, word)
        self.player_guesses[player_name].append(word)
        self.player_results[player_name].append(result)
        # 更新字母状态
        priority = {'correct': 3, 'present': 2, 'absent': 1, 'unknown': 0}
        ls = self.player_letter_states[player_name]
        for ch, st in zip(word, result):
            old = ls.get(ch, 'unknown')
            if priority.get(st, 0) > priority.get(old, 0):
                ls[ch] = st
        # 猜对 → 立即结束（第一个猜对的获胜）
        if word == self.answer:
            self.player_finished[player_name] = True
            self.winner = player_name
            self.state = 'finished'
        elif len(self.player_guesses[player_name]) >= MAX_GUESSES:
            self.player_finished[player_name] = True
            if all(self.player_finished.get(p, False) for p in self.players):
                self.state = 'finished'
        return result

    def player_won(self, player_name: str) -> bool:
        guesses = self.player_guesses.get(player_name, [])
        return bool(guesses) and guesses[-1] == self.answer

    def player_done(self, player_name: str) -> bool:
        return self.player_finished.get(player_name, False)

    @property
    def finished(self) -> bool:
        return self.state == 'finished'

    def get_board_data(self, viewer: str | None = None) -> dict:
        """构建客户端渲染用数据

        多人模式: 包含所有玩家的猜测，观众能看到所有人的猜测。
        单人模式: 兼容旧格式。
        """
        data = {
            'game_type': 'wordle',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'max_guesses': MAX_GUESSES,
            'word_length': WORD_LENGTH,
            'finished': self.finished,
            'answer': self.answer if self.finished else None,
            'players': self.players,
            'player_count': self.player_count,
            'is_multiplayer': self._multiplayer,
        }

        if self.state == 'waiting':
            return data

        if not self._multiplayer:
            # 单人兼容格式
            p = self.players[0] if self.players else viewer
            if p:
                data['guesses'] = self.player_guesses.get(p, [])
                data['results'] = self.player_results.get(p, [])
                data['letter_states'] = self.player_letter_states.get(p, {})
                data['won'] = self.player_won(p)
            return data

        # 多人: 每个人的猜测都可见
        all_boards = {}
        for p in self.players:
            all_boards[p] = {
                'guesses': self.player_guesses.get(p, []),
                'results': self.player_results.get(p, []),
                'finished': self.player_finished.get(p, False),
                'won': self.player_won(p),
            }
        data['all_boards'] = all_boards
        data['winner'] = self.winner
        # 当前观众自己的 letter_states + 身份标识
        if viewer:
            data['viewer'] = viewer
            data['letter_states'] = self.player_letter_states.get(viewer, {})
            data['won'] = self.player_won(viewer)
        return data

    def get_table_data(self) -> dict:
        """等待阶段的房间数据"""
        return {
            'game_type': 'wordle',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': self.players,
            'player_count': self.player_count,
        }


class WordleEngine(BaseGameEngine):
    """Wordle 游戏引擎 — 房间制（1-4人）

    所有游戏反馈通过 ROOM_UPDATE 传递到客户端游戏面板。
    room_data 可选字段: doc(文档), message(状态消息)
    """

    game_key = 'wordle'

    def __init__(self):
        self._rooms: dict[str, WordleRoom] = {}
        self._player_room: dict[str, str] = {}  # player_name → room_id
        self._invites: dict[str, dict] = {}
        self.pending_confirms: dict[str, dict] = {}

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        cmd_name = cmd.lstrip('/')
        location = lobby.get_player_location(player_name)

        if location == 'wordle_lobby':
            if cmd_name == 'create':
                return self._cmd_create(lobby, player_name)
            if cmd_name == 'rooms':
                return self._cmd_rooms(player_name)
            if cmd_name == 'accept':
                return self._cmd_accept(lobby, player_name, player_data)

        elif location == 'wordle_room':
            if cmd_name == 'start':
                return self._cmd_start(lobby, player_name, player_data)
            if cmd_name == 'invite':
                return self._cmd_invite(lobby, player_name, player_data, args)
            if cmd_name == 'kick':
                return self._cmd_kick(lobby, player_name, args)
            if cmd_name == 'leave':
                return self._cmd_leave(lobby, player_name)

        elif location == 'wordle_playing':
            if cmd_name == 'guess':
                return self._cmd_guess(lobby, player_name, player_data, args)

        return None

    def get_player_room(self, player_name: str) -> WordleRoom | None:
        room_id = self._player_room.get(player_name)
        return self._rooms.get(room_id) if room_id else None

    def handle_disconnect(self, lobby, player_name):
        room = self.get_player_room(player_name)
        if room:
            was_playing = room.state == 'playing' and room._multiplayer
            room.remove_player(player_name)
            room_id = self._player_room.pop(player_name, None)
            if not room.players:
                if room_id:
                    self._rooms.pop(room_id, None)
            else:
                if room.host == player_name:
                    room.host = room.players[0]
                # 多人游戏中断线: 检查剩余玩家是否全部已结束
                if was_playing and room.state == 'playing':
                    if all(room.player_finished.get(p, False)
                           for p in room.players):
                        room.state = 'finished'
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
        room_data = lobby.get_player_room_data(player_name)
        send_to_caller = []
        if room_data:
            send_to_caller.append({'type': ROOM_UPDATE, 'room_data': room_data})
        send_to_caller.append({'type': GAME, 'text': '离开了 Wordle。'})
        return {
            'action': 'location_update',
            'location': 'world_library',
            'send_to_caller': send_to_caller,
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

    # ── 邀请管理 ──

    def send_invite(self, from_player, to_player, room_id):
        self._invites[to_player] = {
            'from': from_player,
            'room_id': room_id,
            'time': time.time(),
        }

    def get_pending_invite(self, player_name):
        inv = self._invites.get(player_name)
        if inv and time.time() - inv['time'] > _INVITE_EXPIRE:
            del self._invites[player_name]
            return None
        return inv

    def get_invite(self, player_name):
        return self.get_pending_invite(player_name)

    def clear_invite(self, player_name):
        self._invites.pop(player_name, None)

    # ── 辅助方法 ──

    def _lobby_board(self) -> dict:
        """空白大厅面板数据"""
        return {'game_type': 'wordle', 'room_state': 'lobby'}

    def _msg(self, player_name, text):
        """返回带消息的 room_data 更新（显示在游戏面板内）"""
        room = self.get_player_room(player_name)
        board = room.get_board_data(viewer=player_name) if room else self._lobby_board()
        board['message'] = text
        # lobby 状态下保留帮助文档
        if board.get('room_state') == 'lobby':
            board['doc'] = _HELP_TEXT
        return {
            'action': 'wordle_message',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
        }

    def _remove_player(self, player_name: str):
        room = self.get_player_room(player_name)
        if room:
            room.remove_player(player_name)
            room_id = self._player_room.pop(player_name, None)
            if not room.players and room_id:
                self._rooms.pop(room_id, None)
            elif room.host == player_name and room.players:
                room.host = room.players[0]

    def _notify_room(self, room, message, exclude=None, location=None):
        """通知房间内其他真人"""
        players = {}
        board_data = room.get_table_data()
        for p in room.players:
            if p == exclude:
                continue
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': board_data})
            if location:
                msgs.append({'type': LOCATION_UPDATE, 'location': location})
            players[p] = msgs
        return players

    def _notify_room_game(self, room, message, exclude=None, location=None,
                           ai_desc=None):
        """通知房间内的人，每人发各自视角数据"""
        players = {}
        for p in room.players:
            if p == exclude:
                continue
            board = room.get_board_data(viewer=p)
            if ai_desc:
                board['ai_description'] = ai_desc
                board['ai_priority'] = 'high'
            msgs = []
            if message:
                msgs.append({'type': GAME, 'text': message})
            msgs.append({'type': ROOM_UPDATE, 'room_data': board})
            if location:
                msgs.append({'type': LOCATION_UPDATE, 'location': location})
            players[p] = msgs
        return players

    # ── 指令实现: 大厅 ──

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
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
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
            lines.append(
                f'  #{room.room_id}  {room.host}'
                f'  {room.player_count}人  {label.get(room.state, room.state)}'
            )
        return self._msg(player_name, '\n'.join(lines))

    def _cmd_accept(self, lobby, player_name, player_data):
        """接受邀请加入房间"""
        inv = self.get_pending_invite(player_name)
        if not inv:
            return self._msg(player_name, '没有待处理的邀请。')
        room_id = inv['room_id']
        room = self._rooms.get(room_id)
        if not room or room.state != 'waiting':
            self._invites.pop(player_name, None)
            return self._msg(player_name, '房间已不存在或游戏已开始。')
        if room.is_full():
            self._invites.pop(player_name, None)
            return self._msg(player_name, '房间已满。')

        self._remove_player(player_name)
        room.add_player(player_name)
        self._player_room[player_name] = room_id
        self._invites.pop(player_name, None)
        lobby.set_player_location(player_name, 'wordle_room')

        table_data = room.get_table_data()
        notify = self._notify_room(room, f'{player_name} 加入了房间',
                                   exclude=player_name)
        return {
            'action': 'wordle_join',
            'send_to_caller': [
                {'type': GAME, 'text': f'加入了房间 #{room_id}'},
                {'type': ROOM_UPDATE, 'room_data': table_data},
                {'type': LOCATION_UPDATE, 'location': 'wordle_room'},
            ],
            'send_to_players': notify,
            'refresh_commands': True,
        }

    # ── 指令实现: 房间 ──

    def _cmd_invite(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if not room:
            return self._msg(player_name, '你还没有创建或加入房间。')

        if not args or not args.startswith('@'):
            # 弹出在线好友子菜单
            friends = player_data.get('friends', [])
            online = set(lobby.online_players)
            items = []
            for name in friends:
                if name not in online:
                    continue
                if self.get_player_room(name):
                    continue
                items.append({
                    'label': name,
                    'command': f'/invite @{name}',
                })
            return {
                'action': 'select_menu',
                'send_to_caller': [{
                    'type': 'game_event',
                    'game_type': 'wordle',
                    'event': 'select_menu',
                    'data': {
                        'title': '邀请好友',
                        'items': items,
                        'empty_msg': '没有可邀请的在线好友。',
                    },
                }],
            }

        target = args[1:].strip()
        friends = player_data.get('friends', [])
        if target not in friends:
            return self._msg(player_name, f'{target} 不是你的好友。')
        if target not in lobby.online_players:
            return self._msg(player_name, f'好友 {target} 不在线。')
        if self.get_player_room(target):
            return self._msg(player_name, f'{target} 已经在一个房间中了。')
        self.send_invite(player_name, target, room.room_id)
        lobby._track_invite(player_name, player_data)
        from ...msg_types import GAME_INVITE
        if lobby.invite_callback:
            lobby.invite_callback(target, {
                'type': GAME_INVITE,
                'from': player_name,
                'game': 'wordle',
                'room_id': room.room_id,
                'expires_in': _INVITE_EXPIRE,
            })
        return self._msg(player_name, f'已向 {target} 发送邀请。')

    def _cmd_kick(self, lobby, player_name, args):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '只有房主才能踢人。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏进行中无法踢人。')

        others = [p for p in room.players if p != player_name]
        if not others:
            return self._msg(player_name, '房间里没有其他玩家。')

        if not args or not args.startswith('@'):
            items = [{'label': p, 'command': f'/kick @{p}'} for p in others]
            return {
                'action': 'select_menu',
                'send_to_caller': [{
                    'type': 'game_event',
                    'game_type': 'wordle',
                    'event': 'select_menu',
                    'data': {
                        'title': '踢出玩家',
                        'items': items,
                    },
                }],
            }

        target = args[1:].strip()
        if target not in others:
            return self._msg(player_name, f'{target} 不在房间中。')
        room.remove_player(target)
        self._player_room.pop(target, None)
        lobby.set_player_location(target, 'wordle_lobby')

        table_data = room.get_table_data()
        lobby_board = self._lobby_board()
        lobby_board['doc'] = _HELP_TEXT
        return {
            'action': 'wordle_kick',
            'send_to_caller': [
                {'type': GAME, 'text': f'已踢出 {target}'},
                {'type': ROOM_UPDATE, 'room_data': table_data},
            ],
            'send_to_players': {
                target: [
                    {'type': GAME, 'text': '你被踢出了房间。'},
                    {'type': ROOM_UPDATE, 'room_data': lobby_board},
                    {'type': LOCATION_UPDATE, 'location': 'wordle_lobby'},
                ],
            },
            'refresh_commands': True,
        }

    def _cmd_start(self, lobby, player_name, player_data):
        room = self.get_player_room(player_name)
        if not room or room.host != player_name:
            return self._msg(player_name, '你不是房主。')
        if room.state != 'waiting':
            return self._msg(player_name, '游戏已经开始或已结束。')

        room.start()

        for p in room.players:
            lobby.set_player_location(p, 'wordle_playing')

        mode_label = '多人对战' if room.is_multiplayer else '单人'
        start_msg = f'Wordle {mode_label}模式开始!'

        send_to_players = self._notify_room_game(
            room, start_msg, exclude=player_name, location='wordle_playing',
            ai_desc=start_msg)

        board = room.get_board_data(viewer=player_name)
        board['ai_description'] = start_msg
        board['ai_priority'] = 'high'
        return {
            'action': 'wordle_start',
            'send_to_caller': [
                {'type': GAME, 'text': start_msg},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'wordle_playing'},
            ],
            'send_to_players': send_to_players,
            'refresh_commands': True,
        }

    def _cmd_leave(self, lobby, player_name):
        room = self.get_player_room(player_name)
        is_host = room and room.host == player_name

        self._remove_player(player_name)
        lobby.set_player_location(player_name, 'wordle_lobby')
        board = self._lobby_board()
        board['doc'] = _HELP_TEXT

        result = {
            'action': 'wordle_leave',
            'send_to_caller': [
                {'type': GAME, 'text': '离开了房间'},
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': 'wordle_lobby'},
            ],
            'refresh_commands': True,
        }

        if room and room.players:
            msg = f'{player_name} 离开了房间'
            if is_host:
                msg += f'\n{room.host} 成为了新房主'
            result['send_to_players'] = self._notify_room(room, msg)

        return result

    # ── 指令实现: 游戏中 ──

    def _cmd_guess(self, lobby, player_name, player_data, word):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')
        if room.player_done(player_name):
            return self._msg(player_name, '你已经结束了。')

        word = word.strip().lower() if word else ''
        if len(word) != WORD_LENGTH:
            return self._msg(player_name, f'需要 {WORD_LENGTH} 个字母。')
        if not word.isalpha():
            return self._msg(player_name, '只能输入英文字母。')
        if word not in _VALID_WORDS:
            return self._msg(player_name, f'"{word}" 不在词库中。')

        room.guess(player_name, word)

        won = room.player_won(player_name)
        done = room.player_done(player_name)
        attempts = len(room.player_guesses[player_name])
        game_over = room.finished

        # 单人模式
        if not room._multiplayer:
            return self._handle_solo_guess(
                lobby, room, player_name, player_data, won, done, attempts, game_over)

        # 多人模式
        return self._handle_multi_guess(
            lobby, room, player_name, player_data, won, done, attempts, game_over)

    def _handle_solo_guess(self, lobby, room, player_name, player_data,
                           won, done, attempts, game_over):
        board = room.get_board_data(viewer=player_name)

        if won:
            board['message'] = '恭喜！'
            solo_rewards = _REWARDS['solo']['rewards']
            r = solo_rewards.get(str(attempts), solo_rewards[str(MAX_GUESSES)])
            exp_gain, gold_gain = r[0], r[1]
            reward_msg = self._apply_reward(
                lobby, player_name, player_data, exp_gain, gold_gain)
            lobby.set_player_location(player_name, 'wordle_finished')
            return {
                'action': 'wordle_win',
                'send_to_caller': [
                    {'type': GAME,
                     'text': f'Wordle 胜利！{attempts}/{MAX_GUESSES} 次猜出\n{reward_msg}'},
                    {'type': ROOM_UPDATE, 'room_data': board},
                    {'type': LOCATION_UPDATE, 'location': 'wordle_finished'},
                ],
                'refresh_commands': True,
            }

        if done:
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

        return {
            'action': 'wordle_guess',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
        }

    def _handle_multi_guess(self, lobby, room, player_name, player_data,
                            won, done, attempts, game_over):
        """多人模式: 所有猜测实时公开，猜对立刻结束"""
        if game_over:
            return self._handle_multi_finish(lobby, room, caller=player_name)

        # 游戏继续 — 通知所有人更新面板
        board_caller = room.get_board_data(viewer=player_name)
        send_to_players = {}
        msg = f'{player_name} 用完了所有机会' if done else ''
        for p in room.players:
            if p == player_name:
                continue
            pb = room.get_board_data(viewer=p)
            msgs = []
            if msg:
                msgs.append({'type': GAME, 'text': msg})
            msgs.append({'type': ROOM_UPDATE, 'room_data': pb})
            send_to_players[p] = msgs

        return {
            'action': 'wordle_guess',
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board_caller}],
            'send_to_players': send_to_players,
        }

    def _handle_multi_finish(self, lobby, room, caller=None):
        """多人模式结束 — 奖励数值从 rewards.json 读取。"""
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        mr = _REWARDS['multi']
        answer = room.answer or '?????'
        winner = room.winner
        reward_lines = []
        num_losers = sum(1 for p in room.players if p != winner) if winner else 0

        for p in room.players:
            pd = lobby.online_players.get(p)
            if not pd:
                continue
            if winner and p == winner:
                wb, wl = mr['winner_base'], mr['winner_per_loser']
                exp_gain = wb[0] + wl[0] * num_losers
                gold_gain = wb[1] + wl[1] * num_losers
                reward_lines.append(f'{p}: +{exp_gain}exp +{gold_gain}金币 (优胜)')
            elif winner:
                exp_gain, gold_gain = mr['loser'][0], mr['loser'][1]
                reward_lines.append(f'{p}: +{exp_gain}exp {gold_gain}金币')
            else:
                exp_gain, gold_gain = mr['timeout'][0], mr['timeout'][1]
                reward_lines.append(f'{p}: +{exp_gain}exp')
            pd['exp'] = pd.get('exp', 0) + exp_gain
            check_level_up(pd)
            pd['gold'] = max(0, pd.get('gold', 0) + gold_gain)
            PlayerManager.save_player_data(p, pd)

        summary = f'答案: {answer.upper()}'
        if winner:
            summary += f'\n优胜: {winner}'
        else:
            summary += '\n无人猜对...'
        if reward_lines:
            summary += '\n' + '\n'.join(reward_lines)

        send_to_players = {}
        caller_msgs = None
        for p in room.players:
            lobby.set_player_location(p, 'wordle_finished')
            pb = room.get_board_data(viewer=p)
            pb['message'] = f'优胜: {winner}' if winner else '无人猜对'
            msgs = [
                {'type': GAME, 'text': summary},
                {'type': ROOM_UPDATE, 'room_data': pb},
                {'type': LOCATION_UPDATE, 'location': 'wordle_finished'},
            ]
            if p == caller:
                caller_msgs = msgs
            else:
                send_to_players[p] = msgs

        result = {
            'action': 'wordle_multi_finish',
            'send_to_players': send_to_players,
            'refresh_commands': True,
            'refresh_status': list(room.players),
        }
        if caller_msgs:
            result['send_to_caller'] = caller_msgs
        return result

    def _apply_reward(self, lobby, player_name, player_data, exp_gain, gold_gain):
        """发放单人奖励，返回描述文本"""
        from ...systems.leveling import check_level_up
        from ...player.manager import PlayerManager

        player_data['exp'] = player_data.get('exp', 0) + exp_gain
        player_data['gold'] = player_data.get('gold', 0) + gold_gain
        lvl_ups = check_level_up(player_data)
        PlayerManager.save_player_data(player_name, player_data)
        msg = f'+{exp_gain} 经验  +{gold_gain} 金币'
        if lvl_ups:
            msg += f'\n升级了! Lv.{lvl_ups[-1]}'
        return msg

    # ── 返回/放弃 ──

    def _cmd_back_playing(self, lobby, player_name):
        """playing 时 back — 放弃"""
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return self._msg(player_name, '没有进行中的游戏。')

        if room._multiplayer:
            # 多人: 放弃退出，不发奖励不扣金币
            room.remove_player(player_name)
            self._player_room.pop(player_name, None)
            lobby.set_player_location(player_name, 'wordle_lobby')

            lobby_board = self._lobby_board()
            lobby_board['doc'] = _HELP_TEXT
            caller_msgs = [
                {'type': GAME, 'text': '已放弃，不获得奖励。'},
                {'type': ROOM_UPDATE, 'room_data': lobby_board},
                {'type': LOCATION_UPDATE, 'location': 'wordle_lobby'},
            ]
            send_to_players = {}

            if not room.players:
                self._rooms.pop(room.room_id, None)
            elif all(room.player_finished.get(p, False)
                     for p in room.players):
                # 剩余玩家全部已用完机会 → 触发结算
                room.state = 'finished'
                finish = self._handle_multi_finish(lobby, room)
                send_to_players = finish.get('send_to_players', {})
            else:
                send_to_players = self._notify_room_game(
                    room, f'{player_name} 放弃了')

            return {
                'action': 'wordle_giveup',
                'send_to_caller': caller_msgs,
                'send_to_players': send_to_players,
                'refresh_commands': True,
            }

        # 单人模式
        answer = room.answer or '?????'
        room.state = 'waiting'
        room.answer = None
        room.player_guesses.clear()
        room.player_results.clear()
        room.player_letter_states.clear()
        room.player_finished.clear()
        room.winner = None
        room._multiplayer = False
        lobby.set_player_location(player_name, 'wordle_room')
        return {
            'action': 'wordle_giveup',
            'send_to_caller': [
                {'type': GAME, 'text': f'已放弃，答案: {answer.upper()}'},
                {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
                {'type': LOCATION_UPDATE, 'location': 'wordle_room'},
            ],
            'refresh_commands': True,
        }

    def _cmd_back_finished(self, lobby, player_name):
        """finished 时 back — 回到房间"""
        room = self.get_player_room(player_name)
        if room:
            # 只有所有人都回到 finished 或者离开后，才重置房间
            all_back = all(
                lobby.get_player_location(p) != 'wordle_playing'
                for p in room.players
            )
            if all_back:
                room.state = 'waiting'
                room.answer = None
                room.player_guesses.clear()
                room.player_results.clear()
                room.player_letter_states.clear()
                room.player_finished.clear()
                room.winner = None
                room._multiplayer = False

            lobby.set_player_location(player_name, 'wordle_room')
            return {
                'action': 'wordle_back_to_room',
                'send_to_caller': [
                    {'type': GAME, 'text': '返回房间'},
                    {'type': ROOM_UPDATE, 'room_data': room.get_table_data()},
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
