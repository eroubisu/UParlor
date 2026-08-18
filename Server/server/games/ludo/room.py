"""飞行棋房间逻辑 — 2-4 人

流程:
  1. 等待 2-4 人 → start()
  2. 掷骰决定先手（最大者先行）
  3. 掷 6 起飞，掷 6 可再掷一次
  4. 三连 6 → 所有棋子回机场
  5. 先完成所有棋子者获胜
"""

from __future__ import annotations

import random

from .board import (
    Board, COLOR_NAMES, PIECES_PER_COLOR,
    PieceState, MoveResult,
)

MIN_PLAYERS = 2
MAX_PLAYERS = 4

# 颜色分配（按玩家顺序）
_COLOR_ASSIGN = {
    2: ['red', 'blue'],
    3: ['red', 'yellow', 'blue'],
    4: ['red', 'yellow', 'blue', 'green'],
}


class LudoRoom:
    """飞行棋房间"""

    def __init__(self, room_id: str, players: list[str],
                 settings: dict | None = None):
        self.room_id = room_id
        self.host = players[0]
        self.players = list(players)
        self.state = 'waiting'
        self.bots: set[str] = set()
        # 非房主玩家的准备状态（仅在等待室有意义）
        self.ready: set[str] = set()

        s = settings or {}
        self.max_players: int = s.get('max_players', MAX_PLAYERS)
        self.ranked: bool = s.get('mode', 'casual') == 'ranked'
        self.rank_tier: int = 0

        # 游戏状态
        self.board: Board | None = None
        self.player_colors: dict[str, str] = {}  # player_name → color
        self.color_players: dict[str, str] = {}   # color → player_name
        self.current_idx: int = 0
        self.dice: int = 0
        self.consecutive_sixes: int = 0
        self.rankings: list[str] = []      # 完成顺序
        self._result_pending: set[str] = set()
        self._settled_players: set[str] = set()
        self._settlement_results: dict[str, dict] = {}
        self._settlement_generation: int = 0
        self._settlement_retry_scheduled: bool = False
        self._settlement_retry_attempt: int = 0

        # 掷骰阶段（待选棋子）
        self.pending_move: bool = False     # 已掷骰，等待选棋子
        # 最近一次移动的动画路径（给客户端播放移动动画）
        self.last_move: dict | None = None
        self._move_seq: int = 0

    def reset_match(self) -> None:
        """清除一局对战的全部状态，保留房间成员和设置。"""
        self._settlement_generation += 1
        self._settlement_retry_scheduled = False
        self._settlement_retry_attempt = 0
        self.board = None
        self.player_colors.clear()
        self.color_players.clear()
        self.current_idx = 0
        self.dice = 0
        self.consecutive_sixes = 0
        self.rankings.clear()
        self._result_pending.clear()
        self._settled_players.clear()
        self._settlement_results.clear()
        self.pending_move = False
        self.last_move = None
        self._move_seq = 0

    def is_bot(self, name: str) -> bool:
        return name in self.bots

    def is_full(self) -> bool:
        return len(self.players) >= self.max_players

    def add_bot(self) -> tuple[bool, str]:
        """添加一个 Bot，返回 (ok, name)"""
        if len(self.players) >= self.max_players:
            return False, ''
        n = len(self.bots) + 1
        name = f'Bot_{n}'
        while name in self.players:
            n += 1
            name = f'Bot_{n}'

        self.players.append(name)
        self.bots.add(name)
        return True, name

    def current_player(self) -> str:
        if not self.players:
            return ''
        return self.players[self.current_idx % len(self.players)]

    # ── 开始游戏 ──

    def start(self) -> str:
        """开始游戏，返回开场消息"""
        self.reset_match()
        n = len(self.players)
        color_list = _COLOR_ASSIGN.get(n, _COLOR_ASSIGN[4][:n])

        # 随机打乱玩家顺序后再按顺序分配颜色
        random.shuffle(self.players)
        for i, player in enumerate(self.players):
            c = color_list[i]
            self.player_colors[player] = c
            self.color_players[c] = player

        self.board = Board(list(self.player_colors.values()))
        self.state = 'playing'

        lines = ['颜色分配:']
        for p in self.players:
            c = self.player_colors[p]
            lines.append(f'  {p} → {COLOR_NAMES[c]}')
        lines.append(f'\n{self.current_player()} 先手')
        return '\n'.join(lines)

    # ── 掷骰子 ──

    def roll_dice(self, player_name: str) -> tuple[bool, str, int]:
        """掷骰子。返回 (ok, msg, dice)"""
        if self.state != 'playing':
            return False, '游戏未开始。', 0
        if player_name != self.current_player():
            return False, '不是你的回合。', 0
        if self.pending_move:
            return False, '请先选择要移动的棋子。', 0

        dice = random.randint(1, 6)
        self.dice = dice
        self.last_move = None  # 新回合：清除上一动画

        color = self.player_colors[player_name]

        # 三连 6 检查
        if dice == 6:
            self.consecutive_sixes += 1
            if self.consecutive_sixes >= 3:
                # 所有在场棋子回机场
                self._send_all_to_airport(color)
                self.consecutive_sixes = 0
                self._advance_turn()
                return True, f'{player_name} 连掷三个 6！所有棋子回机场。', dice
        else:
            self.consecutive_sixes = 0

        # 获取可移动棋子
        valid = self.board.get_valid_moves(color, dice)

        if not valid:
            # 无可移动棋子
            if dice != 6:
                self._advance_turn()
            return True, f'{player_name} 掷了 {dice}，无棋可走。', dice

        # 无论可移动棋子数量，都等待玩家显式选择（不再单棋自动走）
        self.pending_move = True
        return True, f'{player_name} 掷了 {dice}，请选择棋子。', dice

    # ── 选择棋子移动 ──

    def move_piece(self, player_name: str, piece_idx: int) -> tuple[bool, str]:
        """选择移动某枚棋子。返回 (ok, msg)"""
        if self.state != 'playing':
            return False, '游戏未开始。'
        if player_name != self.current_player():
            return False, '不是你的回合。'
        if not self.pending_move:
            return False, '请先掷骰子。'

        color = self.player_colors[player_name]
        valid = self.board.get_valid_moves(color, self.dice)

        if piece_idx not in valid:
            return False, '该棋子不可移动。'

        path = self.board.compute_path(color, piece_idx, self.dice)
        result = self.board.move_piece(color, piece_idx, self.dice)
        self._record_move(color, piece_idx, path)
        msg = self._format_move_msg(player_name, piece_idx, self.dice, result)
        self.pending_move = False
        self._post_move(player_name, self.dice, result)
        return True, msg

    def _record_move(self, color: str, piece_idx: int,
                     path: list[dict]) -> None:
        self._move_seq += 1
        self.last_move = {
            'seq': self._move_seq,
            'color': color,
            'piece_idx': piece_idx,
            'path': path,
        }

    # ── 移动后处理 ──

    def _post_move(self, player_name: str, dice: int,
                   result: MoveResult) -> None:
        color = self.player_colors[player_name]

        # 检查是否全部完成
        if self.board.all_finished(color):
            if player_name not in self.rankings:
                self.rankings.append(player_name)
            # 检查游戏是否结束（只剩一人未完成）
            unfinished = [p for p in self.players
                          if p not in self.rankings]
            if len(unfinished) <= 1:
                # 最后一名也加入排名
                for p in unfinished:
                    self.rankings.append(p)
                self.state = 'finished'
                return

        # 掷 6 → 再掷一次（不换人）；但若本步触发 JP 飞行则不再投。
        if dice == 6 and not result.flew:
            # 不换人，等待再掷
            return

        self._advance_turn()

    def _advance_turn(self) -> None:
        """切换到下一个未完成的玩家"""
        self.pending_move = False
        n = len(self.players)
        for _ in range(n):
            self.current_idx = (self.current_idx + 1) % n
            p = self.players[self.current_idx]
            if p not in self.rankings:
                self.consecutive_sixes = 0
                return
        # 所有人都完成了（不应发生）
        self.state = 'finished'

    def _send_all_to_airport(self, color: str) -> None:
        """将某色所有在场棋子送回机场"""
        for piece in self.board.pieces[color]:
            if piece.state in (PieceState.TRACK, PieceState.RUNWAY):
                self.board.send_to_airport(piece)

    def _format_move_msg(self, player_name: str, piece_idx: int,
                         dice: int, result: MoveResult) -> str:
        """格式化移动消息"""
        color = self.player_colors[player_name]
        cn = COLOR_NAMES[color]
        parts = [f'{player_name} 掷了 {dice}']
        piece = self.board.pieces[color][piece_idx]

        if piece.state == PieceState.TRACK and dice == 6 and \
                result.captured == [] and not result.jumped:
            # 起飞
            parts.append(f'，{cn}{piece_idx+1}号起飞')
        else:
            parts.append(f'，移动{cn}{piece_idx+1}号')

        if result.jumped:
            parts.append('，跳跃！')
        if result.flew:
            parts.append('，飞行！')
        if result.captured:
            names = set()
            for cp in result.captured:
                owner = self.color_players.get(cp.color, '?')
                names.add(owner)
            parts.append(f'，吃掉了 {",".join(names)} 的棋子')
        if result.finished:
            n = self.board.count_finished(color)
            parts.append(f'，到达终点（{n}/{PIECES_PER_COLOR}）')

        return ''.join(parts)

    # ── 放弃 ──

    def forfeit(self, player_name: str) -> str:
        """玩家放弃"""
        if player_name not in self.rankings:
            self.rankings.append(player_name)
        # 若只剩一人未完成
        unfinished = [p for p in self.players if p not in self.rankings]
        if len(unfinished) <= 1:
            for p in unfinished:
                self.rankings.append(p)
            self.state = 'finished'
        elif player_name == self.current_player():
            self._advance_turn()
        return f'{player_name} 放弃了游戏。'

    # ── 数据序列化 ──

    def get_game_data(self, viewer: str | None = None) -> dict:
        """获取游戏状态（发给客户端 room_update）"""
        data = {
            'game_type': 'ludo',
            'room_id': self.room_id,
            'room_state': self.state,
            'host': self.host,
            'players': self.players,
            'max_players': self.max_players,
            'ready': sorted(self.ready),
            'bots': sorted(self.bots),
        }
        if self.state in ('playing', 'finished'):
            data.update({
                'player_colors': self.player_colors,
                'current_player': self.current_player(),
                'dice': self.dice,
                'pending_move': self.pending_move,
                'board': self.board.to_dict() if self.board else {},
                'rankings': self.rankings,
            })
            if viewer:
                color = self.player_colors.get(viewer)
                if color and self.board:
                    valid = (
                        self.board.get_valid_moves(color, self.dice)
                        if self.pending_move else []
                    )
                    data['valid_moves'] = valid
                    if valid:
                        data['move_previews'] = {
                            str(i): {
                                'dest': self.board.preview_dest(
                                    color, i, self.dice),
                                'path': self.board.compute_path(
                                    color, i, self.dice),
                            }
                            for i in valid
                        }
            if self.last_move:
                data['last_move'] = self.last_move
        if self.state == 'finished':
            data['rankings'] = self.rankings
        return data

    def get_table_data(self) -> dict:
        """获取等待室数据"""
        return {
            'game_type': 'ludo',
            'room_id': self.room_id,
            'room_state': 'waiting',
            'host': self.host,
            'players': self.players,
            'max_players': self.max_players,
            'ready': sorted(self.ready),
            'bots': sorted(self.bots),
        }
