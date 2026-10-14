"""飞行棋棋盘模型

72 格公共环形轨道 + 4 条终点跑道（每条 8 格）+ 4 机场 + 4 终点。
4 色: red / yellow / blue / green，每色 4 枚棋子。

坐标系统:
- 公共轨道: 0-71（顺时针，对应 19x19 视觉网格的外环）
- 终点跑道: 每色独立 0-7
- 棋子状态: airport / track / runway / finished
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple

# ── 颜色 ──

COLORS = ('red', 'yellow', 'blue', 'green')
COLOR_NAMES = {'red': '红', 'yellow': '黄', 'blue': '蓝', 'green': '绿'}
PIECES_PER_COLOR = 4

# ── 每色的关键位置（公共轨道索引） ──
# 起飞点、转弯入口（进入终点跑道）、同色跳跃格、虚线飞行入口

# 每色在 72 格轨道上占 18 格，start 相隔 18；turn_in = start + 69 (mod 72)。
#
# JP 格（fly_entry）：位于每色 ST 往后第 9 格（offset +8）。
# 自己颜色踩上自己 JP → fly 沿垂直方向跳 4 格到达 fly_exit。
_COLOR_CONFIG = {
    #              start  turn_in  fly_entry  fly_exit
    'red':    {'start': 0,  'turn_in': 69,
               'fly_entry':  8, 'fly_exit': 22},
    'yellow': {'start': 18, 'turn_in': 15,
               'fly_entry': 26, 'fly_exit': 40},
    'blue':   {'start': 36, 'turn_in': 33,
               'fly_entry': 44, 'fly_exit': 58},
    'green':  {'start': 54, 'turn_in': 51,
               'fly_entry': 62, 'fly_exit':  4},
}

TRACK_LEN = 72

RUNWAY_LEN = 8  # 终点跑道格数

# 与渲染器一致：轨道上每格的底色。
_COLOR_SEQ = ('red', 'yellow', 'blue', 'green')
_START_IDX = {conf['start']: c for c, conf in _COLOR_CONFIG.items()}

# 4 个 JP 格 → JP 拥有色（渲染底色与业主一致）。
_JP_OWNER = {conf['fly_entry']: c for c, conf in _COLOR_CONFIG.items()}

# 每个 JP 触发的飞行轨迹：JP → 3 中间格 → fly_exit（共 5 个 (y, x) 坐标）。
# 中间格不在 track 上，动画期间以 state='fly' + (y, x) 形式发给客户端渲染。
# 第一个元素是 JP 自身，最后一个是 fly_exit 对应的 track 坐标。
_FLY_COORDS: dict[int, list[tuple[int, int]]] = {
    8:  [(5, 7),  (5, 8),  (5, 9),  (5, 10), (5, 11)],   # red
    26: [(7, 13), (8, 13), (9, 13), (10, 13), (11, 13)],  # yellow
    44: [(13, 11), (13, 10), (13, 9), (13, 8), (13, 7)],  # blue
    62: [(11, 5), (10, 5), (9, 5),  (8, 5),  (7, 5)],     # green
}

# 终点跑道每色 8 格的视觉坐标（与客户端 renderer._RUNWAY_COORDS 完全一致）。
# 用于飞行途中检测“撞掉跑道上飞机”：飞行中间格如果与某色 runway 某格重合，
# 该跑道上该位置的非己方棋子被撞回机场。
_RUNWAY_COORDS: dict[str, list[tuple[int, int]]] = {
    'red':    [(9, 1), (9, 2), (9, 3), (9, 4),
               (9, 5), (9, 6), (9, 7), (9, 8)],
    'yellow': [(1, 9), (2, 9), (3, 9), (4, 9),
               (5, 9), (6, 9), (7, 9), (8, 9)],
    'blue':   [(9, 17), (9, 16), (9, 15), (9, 14),
               (9, 13), (9, 12), (9, 11), (9, 10)],
    'green':  [(17, 9), (16, 9), (15, 9), (14, 9),
               (13, 9), (12, 9), (11, 9), (10, 9)],
}

# 反向映射：(y, x) → (color, runway_pos)
_COORD_TO_RUNWAY: dict[tuple[int, int], tuple[str, int]] = {
    coord: (color, idx)
    for color, coords in _RUNWAY_COORDS.items()
    for idx, coord in enumerate(coords)
}


def _cell_color(t: int) -> str:
    """轨道第 t 格的渲染颜色（优先级：JP > start > 默认模 4）。"""
    if t in _JP_OWNER:
        return _JP_OWNER[t]
    if t in _START_IDX:
        return _START_IDX[t]
    return _COLOR_SEQ[t % 4]


# 填充每色的 jumps：所有己色格，排除起点与 fly_entry（后者走飞行分支）。
for _c, _conf in _COLOR_CONFIG.items():
    _conf['jumps'] = [
        t for t in range(TRACK_LEN)
        if _cell_color(t) == _c
        and t != _conf['start']
        and t != _conf['fly_entry']
    ]
    # 每色所有同色格（含 start 与 fly_entry），用于查找“下一格同色”。
    _conf['all_color_cells'] = sorted(
        t for t in range(TRACK_LEN) if _cell_color(t) == _c
    )


def _next_same_color(color: str, pos: int) -> int:
    """沿轨道前进方向，返回 pos 之后第一格同色 track 索引（含 JP / start）。"""
    cells = _COLOR_CONFIG[color]['all_color_cells']
    for t in cells:
        if t > pos:
            return t
    return cells[0]  # 环回


# ── 棋子状态 ──

class PieceState(Enum):
    AIRPORT = 'airport'
    TRACK = 'track'
    RUNWAY = 'runway'
    FINISHED = 'finished'


class Piece:
    """一枚棋子"""
    __slots__ = ('color', 'index', 'state', 'track_pos', 'runway_pos')

    def __init__(self, color: str, index: int):
        self.color = color
        self.index = index
        self.state = PieceState.AIRPORT
        self.track_pos: int = 0      # 公共轨道位置 (state == TRACK)
        self.runway_pos: int = 0     # 终点跑道位置 (state == RUNWAY)

    @property
    def id(self) -> str:
        return f'{self.color}_{self.index}'

    def to_dict(self) -> dict:
        d = {'id': self.id, 'color': self.color, 'index': self.index,
             'state': self.state.value}
        if self.state == PieceState.TRACK:
            d['track_pos'] = self.track_pos
        elif self.state == PieceState.RUNWAY:
            d['runway_pos'] = self.runway_pos
        return d

    def __repr__(self) -> str:
        if self.state == PieceState.AIRPORT:
            return f'Piece({self.id}, airport)'
        if self.state == PieceState.TRACK:
            return f'Piece({self.id}, track@{self.track_pos})'
        if self.state == PieceState.RUNWAY:
            return f'Piece({self.id}, runway@{self.runway_pos})'
        return f'Piece({self.id}, finished)'


class MoveResult(NamedTuple):
    """移动结果"""
    captured: list[Piece]      # 被吃掉的棋子
    jumped: bool               # 是否发生了同色跳跃
    flew: bool                 # 是否发生了虚线飞行
    finished: bool             # 是否刚到达终点


# ── 棋盘 ──

def _wrap(pos: int) -> int:
    """环形轨道取模"""
    return pos % TRACK_LEN


def _track_distance(start: int, end: int) -> int:
    """顺时针距离"""
    return (end - start) % TRACK_LEN


class Board:
    """飞行棋棋盘"""

    def __init__(self, colors: list[str]):
        """初始化棋盘。colors: 参与游戏的颜色列表（2-4）"""
        self.colors = list(colors)
        self.pieces: dict[str, list[Piece]] = {}
        for c in self.colors:
            self.pieces[c] = [Piece(c, i) for i in range(PIECES_PER_COLOR)]

    def get_piece(self, color: str, index: int) -> Piece:
        return self.pieces[color][index]

    def pieces_at_track(self, pos: int) -> list[Piece]:
        """获取公共轨道某位置上的所有棋子"""
        result = []
        for color_pieces in self.pieces.values():
            for p in color_pieces:
                if p.state == PieceState.TRACK and p.track_pos == pos:
                    result.append(p)
        return result

    def get_valid_moves(self, color: str, dice: int) -> list[int]:
        """返回可移动棋子的索引列表。
        掷出 6 时：若机场还有飞机，强制仅返回机场棋子（必须起飞）。"""
        if dice == 6:
            airport_idx = [i for i, p in enumerate(self.pieces[color])
                           if p.state == PieceState.AIRPORT]
            if airport_idx:
                return airport_idx
        valid = []
        for i, piece in enumerate(self.pieces[color]):
            if piece.state == PieceState.FINISHED:
                continue
            if piece.state == PieceState.AIRPORT:
                if dice == 6:
                    valid.append(i)
                continue
            if piece.state == PieceState.TRACK:
                valid.append(i)
                continue
            if piece.state == PieceState.RUNWAY:
                # 跑道上需要精确步数或可反弹
                target = piece.runway_pos + dice
                if target <= RUNWAY_LEN:
                    valid.append(i)
                else:
                    # 反弹规则: 超过终点反弹回来
                    bounce = 2 * RUNWAY_LEN - target
                    if bounce >= 0:
                        valid.append(i)
                continue
        return valid

    def move_piece(self, color: str, piece_idx: int, dice: int) -> MoveResult:
        """移动棋子，返回移动结果。调用前应确保 piece_idx 在 get_valid_moves 中。"""
        piece = self.pieces[color][piece_idx]
        conf = _COLOR_CONFIG[color]
        captured: list[Piece] = []
        jumped = False
        flew = False
        finished = False

        if piece.state == PieceState.AIRPORT:
            # 起飞: 放到起飞点
            piece.state = PieceState.TRACK
            piece.track_pos = conf['start']
            # 起飞点吃子
            captured = self._capture_at(piece.track_pos, color)
            # 起飞点通常也是自己的跳跃格 → 触发跳跃/飞行
            j_cap, jumped, flew = self._apply_track_jumps(piece, color, conf)
            captured += j_cap
            return MoveResult(captured, jumped, flew, False)

        if piece.state == PieceState.RUNWAY:
            return self._move_on_runway(piece, dice)

        # piece.state == TRACK
        start = piece.track_pos
        turn_in = conf['turn_in']

        # 计算到转弯入口的距离
        dist_to_turn = _track_distance(start, turn_in)

        if dist_to_turn < dice and dist_to_turn > 0:
            # 这一步会经过转弯入口 → 进入终点跑道
            remaining = dice - dist_to_turn - 1  # 转弯入口本身消耗1步
            piece.state = PieceState.RUNWAY
            piece.runway_pos = remaining
            if piece.runway_pos == RUNWAY_LEN:
                piece.state = PieceState.FINISHED
                finished = True
            elif piece.runway_pos > RUNWAY_LEN:
                # 反弹
                piece.runway_pos = 2 * RUNWAY_LEN - piece.runway_pos
                piece.state = PieceState.RUNWAY
            return MoveResult([], False, False, finished)

        if dist_to_turn == 0 and dice <= RUNWAY_LEN:
            # 正好站在转弯入口
            piece.state = PieceState.RUNWAY
            piece.runway_pos = dice - 1
            if piece.runway_pos == RUNWAY_LEN:
                piece.state = PieceState.FINISHED
                finished = True
            elif piece.runway_pos > RUNWAY_LEN:
                piece.runway_pos = 2 * RUNWAY_LEN - piece.runway_pos
                piece.state = PieceState.RUNWAY
            return MoveResult([], False, False, finished)

        # 正常在公共轨道移动
        target = _wrap(start + dice)
        piece.track_pos = target

        # 吃子
        captured = self._capture_at(target, color)

        # 同色跳跃 + 虚线飞行：集中在 _apply_track_jumps 处理
        j_cap, jumped, flew = self._apply_track_jumps(piece, color, conf)
        captured += j_cap
        return MoveResult(captured, jumped, flew, finished)

    def _apply_track_jumps(self, piece: 'Piece', color: str,
                           conf: dict) -> tuple[list['Piece'], bool, bool]:
        """棋子落入 track 上后，检查并应用同色跳跃 / 虚线飞行。
        返回 (captured_pieces, jumped, flew)。piece.track_pos 会被改写。
        """
        captured: list[Piece] = []
        jumped = False
        flew = False
        target = piece.track_pos

        if target in conf['jumps']:
            jumped = True
            jump_target = _next_same_color(color, target)
            piece.track_pos = jump_target
            captured += self._capture_at(jump_target, color)

            if jump_target == conf['fly_entry']:
                flew = True
                fly_dest = conf['fly_exit']
                piece.track_pos = fly_dest
                captured += self._capture_along_fly(conf['fly_entry'], color)
                captured += self._capture_at(fly_dest, color)
        elif target == conf['fly_entry']:
            flew = True
            fly_dest = conf['fly_exit']
            piece.track_pos = fly_dest
            captured += self._capture_along_fly(conf['fly_entry'], color)
            captured += self._capture_at(fly_dest, color)

        return captured, jumped, flew

    def _move_on_runway(self, piece: Piece, dice: int) -> MoveResult:
        """终点跑道内移动"""
        target = piece.runway_pos + dice
        if target == RUNWAY_LEN:
            piece.state = PieceState.FINISHED
            return MoveResult([], False, False, True)
        if target > RUNWAY_LEN:
            # 反弹
            piece.runway_pos = 2 * RUNWAY_LEN - target
            return MoveResult([], False, False, False)
        piece.runway_pos = target
        return MoveResult([], False, False, False)

    def _capture_at(self, pos: int, my_color: str) -> list[Piece]:
        """吃掉指定位置上所有非己方棋子"""
        captured = []
        for p in self.pieces_at_track(pos):
            if p.color != my_color:
                p.state = PieceState.AIRPORT
                p.track_pos = 0
                captured.append(p)
        return captured

    def _capture_runway_at(self, runway_color: str, runway_pos: int,
                           my_color: str) -> list[Piece]:
        """吃掉指定终点跑道某格上的非己方棋子（用于 JP 飞行掠过跑道）。

        飞行会掠过全部 4 条跑道，其中可能包含本局未参战的颜色。
        """
        captured = []
        for p in self.pieces.get(runway_color, ()):
            if (p.color != my_color
                    and p.state == PieceState.RUNWAY
                    and p.runway_pos == runway_pos):
                p.state = PieceState.AIRPORT
                p.track_pos = 0
                p.runway_pos = 0
                captured.append(p)
        return captured

    def _capture_along_fly(self, fly_entry: int, my_color: str) -> list[Piece]:
        """JP 飞行途经的中间格若与某色跑道重合，撞掉该格非己方棋子。"""
        captured: list[Piece] = []
        coords = _FLY_COORDS.get(fly_entry, [])
        # 仅检查 3 个中间格（首格是 JP、末格是 fly_exit，分别由调用方处理）
        for coord in coords[1:-1]:
            hit = _COORD_TO_RUNWAY.get(coord)
            if hit is None:
                continue
            r_color, r_pos = hit
            captured += self._capture_runway_at(r_color, r_pos, my_color)
        return captured

    def send_to_airport(self, piece: Piece) -> None:
        """将棋子送回机场"""
        piece.state = PieceState.AIRPORT
        piece.track_pos = 0
        piece.runway_pos = 0

    def all_finished(self, color: str) -> bool:
        """某色是否全部到达终点"""
        return all(p.state == PieceState.FINISHED for p in self.pieces[color])

    def count_finished(self, color: str) -> int:
        """某色已到终点的棋子数"""
        return sum(1 for p in self.pieces[color] if p.state == PieceState.FINISHED)

    def to_dict(self) -> dict:
        """序列化为 dict（发送给客户端）"""
        result = {}
        for color, pieces in self.pieces.items():
            result[color] = [p.to_dict() for p in pieces]
        return result

    def _snapshot_at(self, color: str, index: int, state: PieceState,
                     track_pos: int = 0, runway_pos: int = 0) -> dict:
        d = {'color': color, 'index': index, 'state': state.value}
        if state == PieceState.TRACK:
            d['track_pos'] = track_pos
        elif state == PieceState.RUNWAY:
            d['runway_pos'] = runway_pos
        return d

    def compute_path(self, color: str, piece_idx: int,
                     dice: int) -> list[dict]:
        """预演移动：返回棋子从当前到终点的一系列中间快照（不含起点）。
        简化规则：机场→起飞为 1 帧；轨道逐格前进；跳跃/飞行视为 1 帧（整段跳到落点）。
        """
        piece = self.pieces[color][piece_idx]
        conf = _COLOR_CONFIG[color]
        frames: list[dict] = []

        if piece.state == PieceState.AIRPORT:
            # 1 帧：直接放到起飞点
            frames.append(self._snapshot_at(
                color, piece_idx, PieceState.TRACK, track_pos=conf['start']))
            # 起飞点若在自己的 jumps 中，补跳跃/飞行逐格帧
            self._append_jump_frames(
                frames, color, piece_idx, conf['start'], conf)
            return frames

        if piece.state == PieceState.RUNWAY:
            target = piece.runway_pos + dice
            step = 1
            cur = piece.runway_pos
            if target <= RUNWAY_LEN:
                while cur < target:
                    cur += step
                    if cur == RUNWAY_LEN:
                        frames.append(self._snapshot_at(
                            color, piece_idx, PieceState.FINISHED))
                    else:
                        frames.append(self._snapshot_at(
                            color, piece_idx, PieceState.RUNWAY,
                            runway_pos=cur))
            else:
                # 反弹
                while cur < RUNWAY_LEN:
                    cur += 1
                    frames.append(self._snapshot_at(
                        color, piece_idx, PieceState.RUNWAY, runway_pos=cur))
                overshoot = target - RUNWAY_LEN
                cur = RUNWAY_LEN
                for _ in range(overshoot):
                    cur -= 1
                    frames.append(self._snapshot_at(
                        color, piece_idx, PieceState.RUNWAY, runway_pos=cur))
            return frames

        # TRACK: 逐格前进，经过 turn_in 改入跑道
        start = piece.track_pos
        turn_in = conf['turn_in']
        dist_to_turn = _track_distance(start, turn_in)

        if 0 < dist_to_turn < dice:
            # 前 dist_to_turn 步在轨道，第 dist_to_turn+1 步到 turn_in（仍在轨道）
            cur = start
            for _ in range(dist_to_turn):
                cur = _wrap(cur + 1)
                frames.append(self._snapshot_at(
                    color, piece_idx, PieceState.TRACK, track_pos=cur))
            # 剩余步数进入跑道
            remaining = dice - dist_to_turn - 1
            rpos = remaining
            if rpos > RUNWAY_LEN:
                rpos = 2 * RUNWAY_LEN - rpos
            for i in range(1, min(remaining, RUNWAY_LEN) + 1):
                if i == RUNWAY_LEN:
                    frames.append(self._snapshot_at(
                        color, piece_idx, PieceState.FINISHED))
                else:
                    frames.append(self._snapshot_at(
                        color, piece_idx, PieceState.RUNWAY, runway_pos=i))
            # 如果反弹，补足反弹帧
            if remaining > RUNWAY_LEN:
                cur_r = RUNWAY_LEN
                for _ in range(remaining - RUNWAY_LEN):
                    cur_r -= 1
                    frames.append(self._snapshot_at(
                        color, piece_idx, PieceState.RUNWAY,
                        runway_pos=cur_r))
            return frames

        if dist_to_turn == 0 and dice <= RUNWAY_LEN:
            # 正好站在 turn_in：dice 步全部走跑道
            for i in range(1, dice + 1):
                if i == RUNWAY_LEN:
                    frames.append(self._snapshot_at(
                        color, piece_idx, PieceState.FINISHED))
                else:
                    frames.append(self._snapshot_at(
                        color, piece_idx, PieceState.RUNWAY, runway_pos=i))
            return frames

        # 普通轨道前进
        cur = start
        for _ in range(dice):
            cur = _wrap(cur + 1)
            frames.append(self._snapshot_at(
                color, piece_idx, PieceState.TRACK, track_pos=cur))
        # 落点可能触发跳跃 / 飞行，追加逐格动画帧
        self._append_jump_frames(frames, color, piece_idx, cur, conf)
        return frames

    def _append_jump_frames(self, frames: list[dict], color: str,
                            piece_idx: int, landed: int, conf: dict) -> None:
        """棋子停在 track[landed] 后若触发跳跃/飞行，追加逐格中间帧。"""
        # 同色跳跃：跳到下一个同色格（包含 JP / start，可能 1~4 步）
        if landed in conf['jumps']:
            jump_target = _next_same_color(color, landed)
            steps = _track_distance(landed, jump_target)
            cur = landed
            for _ in range(steps):
                cur = _wrap(cur + 1)
                frames.append(self._snapshot_at(
                    color, piece_idx, PieceState.TRACK, track_pos=cur))
            # 跳到 fly_entry → 继续飞
            if jump_target == conf['fly_entry']:
                self._append_fly_frames(frames, color, piece_idx, conf)
        elif landed == conf['fly_entry']:
            self._append_fly_frames(frames, color, piece_idx, conf)

    def _append_fly_frames(self, frames: list[dict], color: str,
                           piece_idx: int, conf: dict) -> None:
        """飞行：沿 _FLY_COORDS 逐格（3 个中间格以 state='fly' 传坐标）。"""
        coords = _FLY_COORDS[conf['fly_entry']]
        # coords[0] 是 JP 自身，已由上层追加；从 coords[1] 开始
        for i in range(1, len(coords) - 1):
            y, x = coords[i]
            frames.append({
                'color': color,
                'index': piece_idx,
                'state': 'fly',
                'y': y,
                'x': x,
            })
        # 最终落点：fly_exit 对应的 track 格
        frames.append(self._snapshot_at(
            color, piece_idx, PieceState.TRACK,
            track_pos=conf['fly_exit']))

    def preview_dest(self, color: str, piece_idx: int, dice: int) -> dict:
        """返回若选择该棋子将落在哪里（终点快照）。"""
        frames = self.compute_path(color, piece_idx, dice)
        if frames:
            return frames[-1]
        p = self.pieces[color][piece_idx]
        return self._snapshot_at(
            color, piece_idx, p.state,
            track_pos=p.track_pos, runway_pos=p.runway_pos)
