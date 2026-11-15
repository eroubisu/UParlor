"""
游戏引擎协议定义

定义游戏引擎标准接口和数据结构，使大厅框架无需知道具体游戏类型。

两种引擎类型(通过 GAME_INFO['per_player'] 区分):
- 房间制引擎(per_player=False): 共享实例，管理多个房间 (如 chess, mahjong)
- 玩家制引擎(per_player=True): 每个玩家独立实例 (如 jrpg)
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from typing import Protocol, runtime_checkable, Any

from ..msg_types import GAME, ROOM_UPDATE


# ── 共享构建器 ──

def build_select_menu(title, items, empty_msg=''):
    """构建 select_menu 响应 — 所有模块统一使用此函数。

    返回的 send_to_caller 消息类型为 'select_menu'（非 game_event），
    由 result_dispatcher.wrap_game_event 自动包装为 game_event 信封
    （自动注入正确的 game_type）。
    """
    return_count = sum(item.get('type') == 'return' for item in items)
    if return_count > 1:
        raise ValueError('select_menu 只能包含一个返回动作')
    return {
        'action': 'select_menu',
        'send_to_caller': [{
            'type': 'select_menu',
            'title': title,
            'items': items,
            'empty_msg': empty_msg,
        }],
    }


def build_confirm_menu(prompt, yes_command, title='确认'):
    """构建"确认"请求 — 所有需要玩家再确认一次的操作统一用它（是 / 否）。

    客户端看到 `confirm` 字段就用共享的确认组件（`ConfirmMenu`）显示，和聊天、设置里的
    确认长得一样；`items` 是给不认识 `confirm` 的旧客户端留的等价菜单。
    「是」直接发出 yes_command；它必须是**不会再确认**的写法（末尾带 `yes`），
    否则就会连问两次。
    """
    menu = build_select_menu(title, [
        {'label': prompt, 'type': 'text'},
        {'type': 'separator'},
        {'label': '是', 'desc': '', 'command': yes_command},
        {'label': '否', 'desc': '', 'command': '', 'type': 'return'},
    ])
    menu['send_to_caller'][0]['confirm'] = {
        'message': prompt, 'command': yes_command}
    return menu


@dataclass(frozen=True)
class ConfirmedCommand:
    """一条要先确认的指令：在哪个路由键下、确认语是什么。"""

    state: str                    # 'playing'（对局中）/ 'room'（等候室）
    prompt: str                   # 确认语；{target} 换成 @ 后面的名字
    needs_target: bool = False    # True：只有带 @目标 才确认（不带目标是在弹选人菜单）


def split_confirmation(args: str) -> tuple[str, bool]:
    """去掉末尾的确认标记 `yes`：返回 (剩下的参数, 是否已确认)。"""
    tokens = args.split()
    if tokens and tokens[-1] == 'yes':
        return ' '.join(tokens[:-1]), True
    return args, False


# ── 游戏引擎标准接口 ──

@runtime_checkable
class GameEngine(Protocol):
    """游戏引擎标准接口"""

    def handle_command(self, lobby: Any, player_name: str, player_data: dict,
                       cmd: str, args: str) -> Any:
        """处理游戏指令。Returns: 响应消息(str/dict)，None 表示未匹配"""
        ...

    def handle_disconnect(self, lobby: Any, player_name: str) -> list[dict]:
        """处理玩家断线。Returns: 需要发送的通知列表"""
        ...

    def handle_back(self, lobby: Any, player_name: str, player_data: dict) -> Any:
        """处理 /back 指令"""
        ...

    def handle_quit(self, lobby: Any, player_name: str, player_data: dict) -> Any:
        """处理 /home 指令"""
        ...

    def get_welcome_message(self, player_data: dict) -> dict:
        """获取进入游戏时的欢迎信息"""
        ...


class BaseGameEngine:
    """游戏引擎基类 — 提供可选方法的默认空实现。

    游戏引擎继承此类即可省去样板代码，
    框架调用方无需 hasattr 检查。

    房间制引擎子类应设置类属性:
        game_key: str        — 游戏标识（如 'chess'）
    """

    game_key: str = ''
    display_name: str = ''
    underfilled_start: str = 'forbid'

    # ── 指令路由表 ──
    # 子类覆盖这两个类属性即可，无需重写 handle_command。
    # 路由键由房间状态决定: 无房间→'lobby', waiting→'room', playing→'playing'
    _GLOBAL_COMMANDS: dict[str, str] = {}   # cmd_name → method_name
    _COMMAND_MAP: dict[str, dict[str, str]] = {}  # state_key → {cmd → method}
    # 要先确认一次的指令。首次（末尾不带 `yes`）只发确认请求，玩家点「是」再带 `yes` 重发；
    # 游戏的指令实现里不用自己写确认，也看不到 `yes`。
    _CONFIRMED_COMMANDS: dict[str, ConfirmedCommand] = {
        'forfeit': ConfirmedCommand('playing', '确认放弃对局?'),
        'invite': ConfirmedCommand('room', '确认邀请 {target}?', True),
        'kick': ConfirmedCommand('room', '确认踢出 {target}?', True),
    }
    _SETTLEMENT_RETRY_BASE_DELAY = 1.0
    _SETTLEMENT_RETRY_MAX_DELAY = 30.0
    _SETTLEMENT_RETRY_MAX_EXPONENT = 5

    def _get_command_key(self, player_name) -> str:
        """根据玩家房间状态返回指令路由键。"""
        room = self.get_player_room(player_name)
        if not room:
            return 'lobby'
        if room.state == 'playing':
            return 'playing'
        if room.state == 'waiting':
            return 'room'
        return room.state

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        """通用指令路由 — 子类通过 _COMMAND_MAP / _GLOBAL_COMMANDS 声明即可。"""
        cmd_name = cmd.lstrip('/')
        method_name = self._GLOBAL_COMMANDS.get(cmd_name)
        key = self._get_command_key(player_name)
        if not method_name:
            commands = self._COMMAND_MAP.get(key, {})
            method_name = commands.get(cmd_name)
        if method_name:
            rule = self._CONFIRMED_COMMANDS.get(cmd_name)
            if rule and key == rule.state:
                args, confirmed = split_confirmation(args)
                if not confirmed and (args.startswith('@') or not rule.needs_target):
                    return self._confirm_menu(cmd_name, args)
            return getattr(self, method_name)(lobby, player_name, player_data, args)
        return None

    def _confirm_menu(self, cmd_name: str, args: str = ''):
        """某条需确认指令的确认请求（「是」发 `/<指令> <参数> yes`）。"""
        rule = self._CONFIRMED_COMMANDS[cmd_name]
        prompt = rule.prompt.format(target=args.lstrip('@').strip())
        yes = ' '.join(part for part in (f'/{cmd_name}', args, 'yes') if part)
        return build_confirm_menu(prompt, yes)

    @staticmethod
    def gen_room_id() -> str:
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

    def _init_rooms(self):
        """初始化房间制引擎的通用容器"""
        self._rooms = {}
        self._player_room = {}
        self._invites = {}
        self.pending_confirms = {}

    def _lobby_board(self) -> dict:
        return {'game_type': self.game_key, 'room_state': 'lobby'}

    def _select_menu(self, title, items, empty_msg=''):
        """构建 select_menu 响应"""
        return build_select_menu(title, items, empty_msg)

    def _check_start_players(
            self, player_name: str, player_count: int, minimum_players: int,
            room_capacity: int, args: str):
        """Separate the hard minimum from the configured room capacity."""
        if args.strip() == 'cancel':
            return self._msg(player_name, '已取消开始游戏。')
        if player_count < minimum_players:
            message = (
                f'人数不足：当前 {player_count} 人，'
                f'至少需要 {minimum_players} 人才能开始。'
            )
            items = [
                {'label': message, 'type': 'text'},
                {'type': 'separator'},
                {
                    'type': 'return', 'label': '返回',
                    'desc': '', 'command': '/start cancel',
                },
            ]
        elif player_count >= room_capacity:
            return None
        elif self.underfilled_start == 'forbid':
            message = (
                f'房间未满：当前 {player_count}/{room_capacity} 人，'
                '该游戏需要满员才能开始。'
            )
            items = [
                {'label': message, 'type': 'text'},
                {'type': 'separator'},
                {
                    'type': 'return', 'label': '返回',
                    'desc': '', 'command': '/start cancel',
                },
            ]
        elif args.strip() != 'confirm_underfilled':
            message = (
                f'房间未满：当前 {player_count}/{room_capacity} 人，'
                '是否仍然开始？'
            )
            items = [
                {'label': message, 'type': 'text'},
                {'type': 'separator'},
                {
                    'label': '仍然开始',
                    'desc': '',
                    'command': '/start confirm_underfilled',
                },
                {
                    'type': 'return', 'label': '返回',
                    'desc': '', 'command': '/start cancel',
                },
            ]
        else:
            return None
        result = self._select_menu('开始游戏', items)
        result['send_to_caller'].insert(0, {'type': GAME, 'text': message})
        return result

    def _msg(self, player_name, text):
        """构建带有当前棋盘状态和消息的响应"""
        room = self.get_player_room(player_name)
        board = room.get_game_data(viewer=player_name) if room else self._lobby_board()
        board['message'] = text
        if board.get('room_state') == 'lobby':
            from ..lobby.help import get_help_welcome
            board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        return {
            'action': f'{self.game_key}_message',
            'send_to_caller': [
                {'type': GAME, 'text': text},
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
        }

    def _settlement_retry_result(self, room, caller):
        """返回延迟结算结果，并确保同一局最多只有一个待执行任务。"""
        result = self._msg(caller, '结算保存暂时失败，服务器将自动重试。')
        if room._settlement_retry_scheduled:
            result['schedule'] = []
            return result
        room._settlement_retry_scheduled = True
        room._settlement_retry_attempt += 1
        exponent = min(
            room._settlement_retry_attempt - 1,
            self._SETTLEMENT_RETRY_MAX_EXPONENT,
        )
        delay = min(
            self._SETTLEMENT_RETRY_BASE_DELAY * (2 ** exponent),
            self._SETTLEMENT_RETRY_MAX_DELAY,
        )
        result['schedule'] = [{
            'game_id': self.game_key,
            'action': 'settlement_retry',
            'room_id': room.room_id,
            'generation': room._settlement_generation,
            'delay': delay,
        }]
        return result

    def _retry_settlement(self, lobby, room_id, generation):
        """在调度器持有 lobby._lock 时重试仍属于当前对局的结算。"""
        room = self._rooms.get(room_id)
        if (
                room is None
                or room.state != 'finished'
                or room._settlement_generation != generation
                or not room._settlement_retry_scheduled):
            return None
        room._settlement_retry_scheduled = False
        return self._handle_game_over(lobby, room, '', {})

    def get_welcome_message(self, player_data):
        from ..lobby.help import get_help_welcome
        from ..config import DEFAULT_LOCATION
        board = self._lobby_board()
        board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        return {
            'send_to_caller': [
                {'type': ROOM_UPDATE, 'room_data': board},
            ],
            'location': DEFAULT_LOCATION,
            'refresh_commands': True,
        }

    def get_commands(self, lobby: Any, location: str, player_name: str,
                     player_data: dict) -> list[dict] | None:
        """动态返回当前位置的游戏指令列表。返回 None 时 fallback 到 commands.json。"""
        return None

    def get_status_extras(self, player_name: str, player_data: dict) -> dict | None:
        """状态消息附加字段"""
        return None

    def get_player_room(self, player_name: str) -> Any:
        """查询玩家所在房间"""
        return None

    def get_player_room_data(self, player_name: str) -> dict | None:
        """查询房间数据（用于 UI 更新）"""
        return None

    def report_game_result(self, lobby: Any, player_name: str,
                           player_data: dict, result: str,
                           game_specific: dict | None = None) -> None:
        """报告游戏结果，更新全局统计并检查头衔。

        Args:
            result: 'win' | 'loss' | 'draw'
            game_specific: 游戏专属统计增量（如 {'yakuman_count': 1}），
                           将累加到 player_data[game_key]['stats'] 中。
        """
        from ..player.manager import PlayerManager

        self._apply_game_result(player_data, result, game_specific)
        PlayerManager.save_player_data(player_data['name'], player_data)

    def _apply_game_result(
            self, player_data: dict, result: str,
            game_specific: dict | None = None) -> None:
        """只更新结果数据；由需要事务式结算的调用方统一持久化。"""
        gs = player_data.setdefault('game_stats', {
            'total_games': 0, 'total_wins': 0,
            'total_losses': 0, 'total_draws': 0,
        })
        gs['total_games'] = gs.get('total_games', 0) + 1
        if result == 'win':
            gs['total_wins'] = gs.get('total_wins', 0) + 1
        elif result == 'loss':
            gs['total_losses'] = gs.get('total_losses', 0) + 1
        elif result == 'draw':
            gs['total_draws'] = gs.get('total_draws', 0) + 1

        # 累加游戏专属统计
        if game_specific and hasattr(self, 'game_key'):
            gd = player_data.setdefault(self.game_key, {})
            stats = gd.setdefault('stats', {})
            for key, delta in game_specific.items():
                stats[key] = stats.get(key, 0) + delta

    def leave_room(self, player_name: str) -> None:
        """离开房间"""

    def _update_player_rank(self, player_data, outcome, has_bots=False,
                             multiplier=1):
        """更新玩家段位，返回变化信息 dict"""
        from ..systems.ranks import (
            get_rank_info, get_rank_index, get_rank_order,
            get_rank_name, get_title_id_from_rank,
        )

        _gk = self.game_key
        rank_order = get_rank_order(_gk)
        gd = player_data.setdefault(_gk, {})
        cur_rank = gd.get('rank', rank_order[0])
        cur_pts = gd.get('rank_points', 0)
        info = get_rank_info(cur_rank, _gk)
        tier = info.get('tier', 1)

        delta = self._calc_rank_delta(tier, outcome)
        delta = int(delta * multiplier)

        # Bot 惩罚：正收益减半，expert 以上不涨
        if has_bots:
            from ..config import BOT_REWARD_DIVISOR, BOT_TIER_THRESHOLD
            if delta > 0:
                delta = delta // BOT_REWARD_DIVISOR
                if tier >= BOT_TIER_THRESHOLD:
                    delta = 0
            elif delta < 0:
                delta = 0  # 打 bot 不扣分

        new_pts = cur_pts + delta
        new_rank = cur_rank
        promoted = demoted = False

        # 升段
        pts_up = info.get('points_up')
        if pts_up and new_pts >= pts_up:
            idx = get_rank_index(cur_rank, _gk)
            if idx < len(rank_order) - 1:
                new_rank = rank_order[idx + 1]
                new_pts = 0
                promoted = True

        # 降段
        if not promoted and new_pts < 0:
            if info.get('points_down') is not None:
                idx = get_rank_index(cur_rank, _gk)
                if idx > 0:
                    prev = rank_order[idx - 1]
                    prev_info = get_rank_info(prev, _gk)
                    new_rank = prev
                    from ..config import DEMOTION_RECOVERY_DIVISOR
                    new_pts = (prev_info.get('points_up', 40) or 40) // DEMOTION_RECOVERY_DIVISOR
                    demoted = True
            else:
                new_pts = 0

        gd['rank'] = new_rank
        gd['rank_points'] = new_pts
        if get_rank_index(new_rank, _gk) > get_rank_index(
                gd.get('max_rank', rank_order[0]), _gk):
            gd['max_rank'] = new_rank

        if promoted:
            title_id = get_title_id_from_rank(new_rank)
            if title_id:
                from ..player.schema import default_titles
                titles = player_data.setdefault(
                    'titles', default_titles())
                if title_id not in titles['owned']:
                    titles['owned'].append(title_id)

        return {
            'delta': delta,
            'old_rank': cur_rank,
            'new_rank': new_rank,
            'new_rank_name': get_rank_name(new_rank, _gk),
            'promoted': promoted,
            'demoted': demoted,
        }

    def _calc_rank_delta(self, tier, outcome):
        """计算段位点变化 — 子类可覆盖"""
        if outcome == 'win':
            return 8
        elif outcome == 'draw':
            return 2
        else:
            return 0 if tier <= 1 else -5
