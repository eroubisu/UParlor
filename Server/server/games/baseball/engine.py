"""棒球引擎 — 房间外壳来自 core.room_engine，本模块只写玩法。

阶段机：布阵 → 投球 → 打击 → （击中则进入逐格飞行）→ 结算 → 下一个打者。
飞行、捡球、传球由 BaseballScheduler 按房间给出的 `next_tick()` 一拍一拍推进，
野手在窗口内自己跑、自己选接球动作（普通 / 跳跃 / 飞扑）。
"""

from __future__ import annotations

import functools
import logging
import threading
from copy import deepcopy

from ...core.room_engine import RoomBotScheduler, RoomGameEngine
from ...msg_types import COMMANDS_UPDATE, GAME, LOCATION_UPDATE, ROOM_UPDATE
from .bot import BaseballBot
from .room import DEFAULT_INNINGS, BaseballRoom
from .state import Tick
from . import rules

logger = logging.getLogger(__name__)

BOT_THINK_RANGE = (0.6, 1.1)

_NOT_PLAYING = '当前不在比赛中'
# 完整指令的参数表：每个位置允许的取值（客户端总是发完整指令，缺了或写错就是无效）
_PITCH_ARGS = (rules.PITCH_TYPES, rules.BANDS, rules.EFFORTS, rules.HOLDS)
_SWING_ARGS = (rules.PITCH_TYPES, rules.SWINGS, rules.RUN_SCOPES)
_MOVES = {'left': -1, 'stop': 0, 'right': 1}


def _valid_args(parts: list[str], allowed: tuple) -> bool:
    return len(parts) == len(allowed) and all(
        part in choices for part, choices in zip(parts, allowed))


def _in_match(handler):
    """棋盘上的指令：找到发令人的房间，不在比赛中就回一句提示。"""
    @functools.wraps(handler)
    def wrapper(self, lobby, player_name, player_data, args):
        room = self.get_player_room(player_name)
        if room is None or room.state != 'playing':
            return self._msg(player_name, _NOT_PLAYING)
        return handler(self, lobby, room, player_name, player_data, args)
    return wrapper


def _split_game_lines(messages: list[dict]) -> list[dict]:
    split: list[dict] = []
    for message in messages:
        if message['type'] == GAME and '\n' in message['text']:
            split.extend({**message, 'text': line}
                         for line in message['text'].split('\n') if line)
        else:
            split.append(message)
    return split


def _one_line(result):
    """上方通知栏一次只显示一行：多行的播报拆成一行一条消息。

    栏上留下的是最后一条（所以房间把"这一拍的结论"写在最后一行），
    记录窗口里一行不少。
    """
    if not isinstance(result, dict):
        return result
    if 'send_to_caller' in result:
        result['send_to_caller'] = _split_game_lines(result['send_to_caller'])
    players = result.get('send_to_players')
    if players:
        result['send_to_players'] = {
            name: _split_game_lines(messages)
            for name, messages in players.items()}
    return result


class BaseballEngine(RoomGameEngine):
    """棒球引擎（1v1）。"""

    game_key = 'baseball'
    display_name = '棒球'
    underfilled_start = 'forbid'
    room_class = BaseballRoom
    min_players = 2
    bot_action = 'baseball_action'
    bot_delay_range = BOT_THINK_RANGE
    _HELP_TEXT = RoomGameEngine.load_data_text(__file__, 'help.txt')
    _REWARDS = RoomGameEngine.load_data_json(__file__, 'rewards.json')

    _GLOBAL_COMMANDS: dict[str, str] = {
        'create': '_cmd_create',
    }
    _COMMAND_MAP = {
        'lobby': {
            'rooms': '_cmd_rooms',
            'accept': '_cmd_accept',
            'join': '_cmd_join',
        },
        'room': {
            'start': '_cmd_start',
            'ready': '_cmd_ready',
            'invite': '_cmd_invite',
            'kick': '_cmd_kick',
            'bot': '_cmd_bot',
            'dissolve': '_cmd_dissolve',
        },
        'playing': {
            'shift': '_cmd_shift',
            'pitch': '_cmd_pitch',
            'swing': '_cmd_swing',
            'hit': '_cmd_hit',
            'release': '_cmd_release',
            'field': '_cmd_field',
            'jump': '_cmd_jump',
            'run': '_cmd_run',
            'throw': '_cmd_throw',
            'hold': '_cmd_hold',
            'forfeit': '_cmd_forfeit',
        },
    }

    # ── 文案：播报不用中文标点连句子（开赛那一行由房间自己写）──

    def _text_start(self) -> str:
        return ''

    def _text_left(self) -> str:
        return '离开棒球'

    # ── 指令表按阶段收窄 ──

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        return _one_line(super().handle_command(
            lobby, player_name, player_data, cmd, args))

    def get_commands(self, lobby, location, player_name, player_data):
        room = self.get_player_room(player_name)
        if not room or room.state != 'playing':
            return super().get_commands(
                lobby, location, player_name, player_data)
        commands = self._game_info()['commands'][f'{self.game_key}:playing']
        # 玩法动作全在棋盘下方的操作区，右下角只留房间级操作
        return [c for c in commands if c['name'] == 'forfeit']

    # ── 阶段动作（菜单由客户端按阶段自己生成，服务端只认完整指令）──

    @_in_match
    def _cmd_shift(self, lobby, room, player_name, player_data, args):
        shift = args.strip()
        if shift not in rules.SHIFTS:
            return self._msg(player_name, '请选择守备站位')
        return self._submit(lobby, room, player_name, player_data,
                            room.set_shift(player_name, shift))

    @_in_match
    def _cmd_pitch(self, lobby, room, player_name, player_data, args):
        parts = args.split()
        if not _valid_args(parts, _PITCH_ARGS):
            return self._msg(player_name, '投球参数不完整')
        # 球种/区域/力度是打者要猜的东西：服务端不会把它们写进任何播报
        return self._submit(lobby, room, player_name, player_data,
                            room.set_pitch(player_name,
                                           rules.PitchCall(*parts)))

    @_in_match
    def _cmd_swing(self, lobby, room, player_name, player_data, args):
        parts = args.split()
        if not _valid_args(parts, _SWING_ARGS):
            return self._msg(player_name, '打击参数不完整')
        guess, swing, steal = parts
        # 时机不是选项：交的是"预判球种 + 挥棒方式 + 盗垒"，等球到了再按击球（见 _cmd_hit）
        return self._submit(lobby, room, player_name, player_data,
                            room.set_swing(player_name, rules.SwingCall(
                                guess, swing, steal=steal)))

    @_in_match
    def _cmd_hit(self, lobby, room, player_name, player_data, args):
        """打者按下击球：客户端报它插值出来的帧作延迟参考，时机由服务端校验后定档。"""
        try:
            frame: float | None = float(args)
        except ValueError:
            frame = None                    # 报的不是数字：按服务端当前帧算
        return self._submit(lobby, room, player_name, player_data,
                            room.swing_now(player_name, frame))

    @_in_match
    def _cmd_release(self, lobby, room, player_name, player_data, args):
        """投手按下「投球」：把这一球投出去（按下的时机不参与任何判定）。

        倒数数完投手那边才亮这颗键（`room.armed`）；它是**投出的确认**，
        所以这里只管把球放出去，别的一概不算。
        """
        if not room.release_pitch(player_name):
            return self._silent(f'{player_name} 在 {room.phase} 按了投球键')
        return self._state_result(lobby, room, player_name, player_data)

    def _cmd_field(self, lobby, player_name, player_data, args):
        """飞行/捡球中的按键：朝左 / 朝右跑、或站住（方向保持到下一次改）。"""
        room = self.get_player_room(player_name)
        direction = args.strip()
        if (room is None or room.phase not in ('flight', 'ground')
                or player_name != room.fielding_player()):
            return self._silent(f'{player_name} 现在不能跑位')
        if direction not in _MOVES:
            return self._silent(f'未知跑位方向 {direction!r}')
        if not room.steer_fielder(_MOVES[direction]):
            return self._silent()
        # 野手真的改了方向：两边的屏幕马上跟上，不用等下一拍
        return {'action': 'baseball_input',
                'send_to_players': self._notify_room(room, '')}

    def _cmd_jump(self, lobby, player_name, player_data, args):
        """飞行中的回车：起跳；跳不了（还在缓冲里）就什么也不发生。"""
        room = self.get_player_room(player_name)
        if (room is None or player_name != room.fielding_player()
                or not room.jump_fielder()):
            return self._silent(f'{player_name} 现在不能起跳')
        return {'action': 'baseball_input',
                'send_to_players': self._notify_room(room, '')}

    def _cmd_run(self, lobby, player_name, player_data, args):
        """进攻方的跑垒指令：back / stop / go（触垒窗口里 go 是冒险多进一个垒，其余是保持）。"""
        room = self.get_player_room(player_name)
        order = args.strip()
        if (room is None or player_name != room.batting_player()
                or not room.set_run_order(order)):
            return self._silent(f'{player_name} 的跑垒指令 {order!r} 现在无效')
        return self._state_result(lobby, room, player_name, player_data)

    def _cmd_throw(self, lobby, player_name, player_data, args):
        """捡球后把球传向某个垒包（传球距离与时间由球型与臂力决定）。"""
        room = self.get_player_room(player_name)
        base = args.strip()
        if room is None or player_name != room.fielding_player():
            return self._msg(player_name, '现在不能传球')
        if base not in rules.BASE_POSITIONS:
            return self._msg(player_name, '请选择要传的垒包')
        if not room.at_ball():
            return self._msg(player_name, '还没跑到球位')
        if not room.start_throw(base):
            return self._msg(player_name, '现在不能传球')
        return self._state_result(lobby, room, player_name, player_data)

    def _cmd_hold(self, lobby, player_name, player_data, args):
        """不传球：控球结束这次击球。"""
        room = self.get_player_room(player_name)
        if (room is None or player_name != room.fielding_player()
                or not room.hold_ball()):
            return self._msg(player_name, '现在不能控球')
        return self._state_result(lobby, room, player_name, player_data)

    @staticmethod
    def _silent(reason: str = '') -> dict:
        """实时按键落在错误阶段/错误一方时不回聊天，但要终止指令链。

        不回玩家是为了不刷屏（追球键一秒几次），但不能让失败彻底消失，
        所以留一条 debug 记录。
        """
        if reason:
            logger.debug('棒球按键被忽略：%s', reason)
        return {'action': 'baseball_input'}

    @_in_match
    def _cmd_forfeit(self, lobby, room, player_name, player_data, args):
        if not args.strip():
            return self._select_menu('确认', [
                {'label': '确认放弃比赛', 'type': 'text'},
                {'type': 'separator'},
                {'label': '是', 'desc': '', 'command': '/forfeit yes'},
                {'label': '否', 'desc': '', 'command': '', 'type': 'return'},
            ])
        # 放弃＝中止比赛：回等待室、不发奖励（和 UNO / Ludo 同一语义）
        msg = f'{player_name} 放弃比赛'
        room.reset_match()
        players = self._notify_room_with_commands(lobby, room, msg,
                                                  exclude=player_name)
        loc = self._loc(room)
        caller_data = lobby.online_players.get(player_name)
        commands = (lobby.get_commands_for_location(loc, caller_data)
                    if caller_data else [])
        return {
            'action': 'baseball_forfeit',
            'send_to_caller': [
                {'type': GAME, 'text': msg},
                {'type': ROOM_UPDATE,
                 'room_data': room.get_game_data(viewer=player_name)},
                {'type': LOCATION_UPDATE, 'location': loc},
                {'type': COMMANDS_UPDATE, 'commands': commands},
            ],
            'send_to_players': players,
            'refresh_commands': True,
        }

    # ── 统一收尾：广播这一拍的播报与棋盘，必要时结算、安排下一步 ──

    def _submit(self, lobby, room, player_name, player_data, outcome) -> dict:
        """房间动作返回 (是否成功, 播报)：失败回一句提示，成功就收尾广播。"""
        ok, lines = outcome
        if not ok:
            return self._msg(player_name, ' '.join(lines))
        return self._state_result(lobby, room, player_name, player_data,
                                  extra_lines=lines)

    def _state_result(self, lobby, room, caller, caller_data,
                      extra_lines=()) -> dict:
        """命令或机器人动作之后：比赛结束走结算，否则双方都在下方的日志里看到同一段播报。"""
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, caller, caller_data)
        text = '\n'.join([*extra_lines, *room._drain()])
        return _one_line({
            'action': 'baseball_play',
            'send_to_caller': [],
            'send_to_players': self._notify_room_with_commands(
                lobby, room, text),
            'refresh_commands': True,
            'schedule': self._maybe_schedule_bot(room) + self._tick_tasks(room),
        })

    def _tick_result(self, lobby, room) -> dict:
        """计时器走完一拍之后：补发这一拍的播报与棋盘（计时链由调度器自己续）。"""
        if room.state == 'finished':
            return self._handle_game_over(lobby, room, '', {})
        return _one_line({
            'action': 'baseball_play',
            'send_to_players': self._notify_room(
                room, '\n'.join(room._drain())),
            'schedule': ([] if room.next_tick()
                         else self._maybe_schedule_bot(room)),
        })

    def _handle_game_over(self, lobby, room, caller, caller_data):
        return _one_line(super()._handle_game_over(
            lobby, room, caller, caller_data))

    def _tick_tasks(self, room) -> list[dict]:
        """命令改了阶段之后，让调度器核对计时链（链没变就什么也不做）。"""
        if room.next_tick() is None:
            return []
        return [{'game_id': self.game_key, 'action': 'tick',
                 'room_id': room.room_id}]

    # ── Bot ──

    def _maybe_schedule_bot(self, room) -> list[dict]:
        if room.state != 'playing':
            return []
        owner = room.decision_owner()
        if not owner or not room.is_bot(owner):
            return []
        return [{
            'game_id': self.game_key,
            'action': self.bot_action,
            'room_id': room.room_id,
        }]

    # ── 结算钩子 ──

    def _outcome_for(self, room, player: str) -> str:
        if not room.winner:
            return 'draw'
        return 'win' if room.winner == player else 'loss'

    def _settle_player(self, room, player, player_data) -> bool:
        from ...player.manager import PlayerManager
        from ...systems.leveling import check_level_up

        outcome = self._outcome_for(room, player)
        exp, gold = self._REWARDS[outcome]
        # 奖励按局数缩放（2026-10-21 用户定）：3 局是基准，1 局三分之一，9 局三倍
        ratio = room.total_innings / DEFAULT_INNINGS
        exp, gold = round(exp * ratio), round(gold * ratio)
        if room.bots:
            # 和 UNO / Ludo 一致：打机器人按单人倍率发金币（设计原则 0.15×）
            gold = int(exp * self._REWARDS['gold_ratio_bot'])
        working = deepcopy(player_data)
        self._apply_game_result(working, outcome)
        rank_change = self._update_player_rank(
            working, outcome, bool(room.bots), multiplier=ratio,
        )
        working['exp'] = working.get('exp', 0) + exp
        check_level_up(working)
        working['gold'] = max(0, working.get('gold', 0) + gold)
        try:
            PlayerManager.save_player_data(player, working)
        except OSError:
            logger.exception("棒球房间 %s 保存 %s 失败，等待重试",
                             room.room_id, player)
            return False
        room._settlement_results[player] = {
            'outcome': outcome, 'exp': exp, 'gold': gold,
            'rank_change': rank_change,
            'score': dict(room.score),
        }
        room._settled_players.add(player)
        working.pop('password_hash', None)
        player_data.clear()
        player_data.update(working)
        return True

    def _format_result(self, player, room, settlement) -> str:
        """结算结论：一行（它是留在上方通知栏的那一句），比分先写自己的。"""
        label = {'win': '获胜', 'loss': '落败',
                 'draw': '平手'}[settlement['outcome']]
        score = settlement['score']
        opponent = next(other for other in room.players if other != player)
        parts = [
            f'{label} {score[player]}-{score[opponent]}',
            f'经验+{settlement["exp"]} 金币+{settlement["gold"]}',
        ]
        delta = (settlement['rank_change'] or {}).get('delta')
        if delta:
            parts.append(f'段位{"+" if delta > 0 else ""}{delta}')
        return ' '.join(parts)

    def _build_settlement_messages(self, lobby, room, caller):
        send_to_players = {}
        refresh_status = []
        caller_messages = None
        location = self._loc(room)
        # 最后一拍的播报（含"下半局不再进行 / 比赛提前结束"的原因）、战报和结算结论
        # 一行一条消息：记录窗口里都在，上方通知栏最后留下的是结算结论
        closing = [*room._drain(), *room.report_lines()]
        for player in room.players:
            settlement = room._settlement_results.get(player)
            if settlement is None:
                continue
            refresh_status.append(player)
            lobby.set_player_location(player, location)
            text = '\n'.join(
                [*closing, self._format_result(player, room, settlement)])
            messages = [
                {'type': GAME, 'text': text},
                {'type': ROOM_UPDATE,
                 'room_data': room.get_game_data(viewer=player)},
                {'type': LOCATION_UPDATE, 'location': location},
            ]
            if player == caller:
                caller_messages = messages
            else:
                send_to_players[player] = messages
        return caller_messages, send_to_players, refresh_status

    @staticmethod
    def _finalize_settlement(lobby, room, send_to_players) -> None:
        room.state = 'waiting'
        room._settlement_retry_scheduled = False
        room._result_pending = {
            p for p in room.players if not room.is_bot(p)
        }

    def _match_disconnect(self, lobby, room, player_name):
        # 断线＝中止：比赛结束但不判胜负、双方都不发奖励（和 UNO / Ludo 同一语义）
        room.state = 'finished'
        room.winner = ''
        send_to_players = {}
        for player in room.players:
            if player == player_name or room.is_bot(player):
                continue
            send_to_players[player] = [
                {'type': GAME, 'text': f'{player_name} 断线 比赛结束'},
                {'type': ROOM_UPDATE,
                 'room_data': room.get_game_data(viewer=player)},
            ]
        self._cleanup_room(room)
        return [{
            'send_to_players': send_to_players,
            'refresh_room_list': True,
        }]


class _TickChain:
    """一条正在走的计时链：同一种 tick 一拍接一拍，种类一变就换新链。"""

    def __init__(self, tick: Tick):
        self.tick = tick
        self.timer: threading.Timer | None = None    # None＝这一拍刚走完，等着续


class BaseballScheduler(RoomBotScheduler):
    """棒球调度器：机器人思考 + 每个房间一条计时链（倒数 / 投打 / 飞行 / 捡球 / 传球）。

    计时链的所有读写都在 `lobby._lock` 里；Timer 线程醒来先核对"我还是不是这个房间
    当前那条链、房间的阶段是不是还没变"，旧计时器因此推不动新阶段。
    """

    def __init__(self, server):
        super().__init__(server, 'baseball', bot_action='baseball_action',
                         delay_range=BOT_THINK_RANGE)
        self._bot = BaseballBot()
        self._chains: dict[str, _TickChain] = {}

    # ── 调度入口 ──

    def handle_schedule(self, task) -> None:
        if task['action'] != 'tick':
            super().handle_schedule(task)
            return
        with self._server.lobby_engine._lock:
            room = self._room(task['room_id'])
            self._sync(task['room_id'], room.next_tick() if room else None)

    def _room(self, room_id: str):
        return self._server.lobby_engine.game_engines[
            self._game_key]._rooms.get(room_id)

    # ── 计时链 ──

    def _sync(self, room_id: str, tick: Tick | None) -> None:
        """让这个房间的计时链和房间当前该有的下一拍一致（持锁调用）。"""
        chain = self._chains.get(room_id)
        if tick is None:
            self._stop(room_id)
        elif chain is None or chain.tick != tick:
            self._stop(room_id)
            self._chains[room_id] = chain = _TickChain(tick)
            self._arm(room_id, chain)
        elif chain.timer is None:
            self._arm(room_id, chain)           # 同一种 tick，上一拍刚走完：续下一拍

    def _arm(self, room_id: str, chain: _TickChain) -> None:
        chain.timer = threading.Timer(
            chain.tick.ms / 1000, self._fire, args=(room_id, chain))
        chain.timer.daemon = True
        chain.timer.start()

    def _stop(self, room_id: str) -> None:
        chain = self._chains.pop(room_id, None)
        if chain and chain.timer:
            chain.timer.cancel()

    def _fire(self, room_id: str, chain: _TickChain) -> None:
        """Timer 线程：一拍到了，推进房间、广播、再续下一拍。"""
        server = self._server
        lobby = server.lobby_engine
        with lobby._lock:
            if self._chains.get(room_id) is not chain:
                return                          # 旧链：阶段已经换了
            chain.timer = None
            room = self._room(room_id)
            if room is None or room.next_tick() != chain.tick:
                self._sync(room_id, room.next_tick() if room else None)
                return
            self._advance(room, chain.tick.kind)
            self._sync(room_id, room.next_tick())
            server.dispatch_game_result(self._engine()._tick_result(lobby, room))

    def _engine(self) -> BaseballEngine:
        return self._server.lobby_engine.game_engines[self._game_key]

    def _advance(self, room, kind: str) -> None:
        """按这一拍的种类推进房间；机器人先动一步，再推进这一拍。"""
        bot = self._bot
        if kind == 'countdown':
            room.countdown_tick()               # 两边交牌后的倒数：数到 0 就交给投手
        elif kind == 'delivery':
            room.delivery_step()
            if room.phase == 'delivery':
                bot.press(room)                 # 机器人也要按时按击球（在段内，不推帧）
        elif kind == 'throw':
            room.throw_tick()
        else:
            if room.is_bot(room.fielding_player()):
                (bot.ground if kind == 'ground' else bot.field)(room)
            if room.is_bot(room.batting_player()):
                bot.run(room)
            if kind == 'flight':
                room.flight_step()
            elif room.phase == 'ground':        # 机器野手可能已经把球传出去了
                room.ground_tick()

    # ── Bot 一次决策 ──

    def _bot_move(self, engine, lobby, room, bot_name) -> None:
        """机器行动一次（持锁调用）。"""
        if room.phase == 'call':
            if room.armed:                      # 机器投手：倒数完就把球投出去
                room.release_pitch(bot_name)
            else:
                self._bot.submit(room, bot_name)
        elif room.phase == 'ground':
            self._bot.ground(room)
        elif room.phase == 'tag':
            self._bot.tag(room)
        else:
            return
        self._server.dispatch_game_result(
            engine._state_result(lobby, room, '', {}))


def create_bot_scheduler(server):
    return BaseballScheduler(server)
