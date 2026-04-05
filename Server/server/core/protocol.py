"""
游戏引擎协议定义

定义游戏引擎标准接口和数据结构，使大厅框架无需知道具体游戏类型。

两种引擎类型(通过 GAME_INFO['per_player'] 区分):
- 房间制引擎(per_player=False): 共享实例，管理多个房间 (如 chess, mahjong)
- 玩家制引擎(per_player=True): 每个玩家独立实例 (如 jrpg)
"""

from __future__ import annotations

import json
import os
import random
import string
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable, Any

from ..msg_types import ROOM_UPDATE, LOCATION_UPDATE


# ── 共享构建器 ──

def build_select_menu(title, items, empty_msg=''):
    """构建 select_menu 响应 — 所有模块统一使用此函数。

    返回的 send_to_caller 消息类型为 'select_menu'（非 game_event），
    由 result_dispatcher.wrap_game_event 自动包装为 game_event 信封
    （自动注入正确的 game_type）。
    """
    return {
        'action': 'select_menu',
        'send_to_caller': [{
            'type': 'select_menu',
            'title': title,
            'items': items,
            'empty_msg': empty_msg,
        }],
    }


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
        _HELP_TEXT: str      — 帮助文档（由 _load_help 加载）
        _REWARDS: dict       — 奖励配置（由 _load_rewards 加载）
    """

    game_key: str = ''
    display_name: str = ''

    # ── 指令路由表 ──
    # 子类覆盖这两个类属性即可，无需重写 handle_command。
    # 位置后缀由 game_key + '_' 前缀去除得到，如 'chess_lobby' → 'lobby'。
    _GLOBAL_COMMANDS: dict[str, str] = {}   # cmd_name → method_name
    _COMMAND_MAP: dict[str, dict[str, str]] = {}  # location_suffix → {cmd → method}

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        """通用指令路由 — 子类通过 _COMMAND_MAP / _GLOBAL_COMMANDS 声明即可。"""
        cmd_name = cmd.lstrip('/')
        method_name = self._GLOBAL_COMMANDS.get(cmd_name)
        if not method_name:
            location = lobby.get_player_location(player_name)
            suffix = location.removeprefix(f'{self.game_key}_')
            commands = self._COMMAND_MAP.get(suffix, {})
            method_name = commands.get(cmd_name)
        if method_name:
            return getattr(self, method_name)(lobby, player_name, player_data, args)
        return None

    @staticmethod
    def gen_room_id() -> str:
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

    @classmethod
    def _load_help(cls) -> str:
        path = os.path.join(os.path.dirname(cls._module_file), 'help.txt')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ''

    @classmethod
    def _load_rewards(cls) -> dict:
        path = os.path.join(os.path.dirname(cls._module_file), 'rewards.json')
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

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
            'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': board}],
        }

    def get_welcome_message(self, player_data):
        from ..lobby.help import get_help_welcome
        lobby_loc = f'{self.game_key}_lobby'
        board = self._lobby_board()
        board['doc'] = get_help_welcome(self.game_key) or self._HELP_TEXT
        return {
            'send_to_caller': [
                {'type': ROOM_UPDATE, 'room_data': board},
                {'type': LOCATION_UPDATE, 'location': lobby_loc},
            ],
            'location': lobby_loc,
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
        from ..systems.titles import check_all_titles
        from ..player.manager import PlayerManager

        # 更新全局 game_stats
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

        # 检查所有头衔
        check_all_titles(player_data)
        PlayerManager.save_player_data(player_data['name'], player_data)

    def leave_room(self, player_name: str) -> None:
        """离开房间"""

    # ── 段位系统 ──

    def _cmd_rank(self, lobby, player_name, player_data, args):
        """显示段位信息"""
        from ..systems.ranks import get_rank_info, get_rank_order

        _gk = self.game_key
        rank_order = get_rank_order(_gk)
        default_rank = rank_order[0]
        gd = player_data.get(_gk, {})
        rank_id = gd.get('rank', default_rank)
        rank_pts = gd.get('rank_points', 0)
        max_rank = gd.get('max_rank', default_rank)
        info = get_rank_info(rank_id, _gk)
        max_info = get_rank_info(max_rank, _gk)

        pts_up = info.get('points_up')
        if pts_up:
            from ..config import RANK_BAR_WIDTH
            pct = min(100, int(rank_pts / pts_up * 100))
            bar = '█' * (pct // RANK_BAR_WIDTH) + '░' * (RANK_BAR_WIDTH - pct // RANK_BAR_WIDTH)
        else:
            bar = '████████████ MAX'
            pct = 100

        name = self.display_name or _gk
        text = f"【{name}段位】\n\n"
        text += f"当前段位: {info['name']}\n"
        text += f"段位点数: {rank_pts}pt"
        if pts_up:
            text += f" / {pts_up}pt"
        text += f"\n升段进度: [{bar}] {pct}%\n"
        text += f"历史最高: {max_info['name']}\n"
        return self._msg(player_data['name'], text)

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

    @staticmethod
    def _format_rank_change(rc):
        """格式化段位变化文本片段"""
        if not rc or rc['delta'] == 0:
            return ''
        sign = '+' if rc['delta'] >= 0 else ''
        part = f'[{sign}{rc["delta"]}pt]'
        if rc['promoted']:
            part += f' 升段→{rc["new_rank_name"]}'
        elif rc['demoted']:
            part += f' 降段→{rc["new_rank_name"]}'
        return part


# ── 游戏事件数据结构 ──

@dataclass
class GameEvent:
    """游戏引擎产生的事件 — 统一的输出协议

    框架级类型(大厅直接处理): room_update / game / location_update / game_end
    游戏特有类型(透传 game_event 信封): 任意自定义，由客户端处理器解读
    """
    type: str
    data: dict = field(default_factory=dict)
    target: str = ""  # 空=广播房间, 玩家名=点对点
