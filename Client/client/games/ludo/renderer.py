"""飞行棋渲染器 — 真实 15×15 坐标网格（每格 2 字符宽 × 1 行高）。

设计原则（方案 A：坐标轴）：
  · 没有 "逻辑网格 + gap" 的二分，所有格子都是 15×15 真实网格上的一等公民。
  · 每个 Cell 明确持有 bg / fg / text(2 列宽) / bold 四个属性。
  · 渲染只做一件事：按行列扫描 cells，输出 bg + fg + text。
    没有任何邻居推断、颜色继承、gap 填色。
  · 所有 "画什么" 的逻辑集中在 _paint_* 函数，分层：
      背景层（机场 / track / runway / finish）
        → 标记层（ST/SF/路径点/落点）
        → 棋子层。
    后层只改 text/fg/bold，保留 bg（保证底色连贯）。
"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer, render_doc
from ...config import (
    NF_ARROW_D, NF_ARROW_L, NF_ARROW_R, NF_ARROW_U, NF_BULLSEYE,
    NF_CARET_D, NF_CARET_U, NF_CROSS, NF_DIAMOND, NF_FLAG, NF_OFFLINE,
    NF_ONLINE, NF_PLANE, NF_STAR, NF_TROPHY,
)
from ...window_engine.text import cell_width, fit_cells


# ─────────────────────────── 样式常量 ───────────────────────────

_BORDER_PLAYABLE = '#a0a0a0'
_BORDER_CURSOR = '#ffffff'

_HEAD = 'bold #e0e0e0'
_DIM = '#808080'
_SCORE = '#b0b0b0'
_ACTIVE = 'bold #d0d0d0'

_COLOR_MAP = {
    'red':    '#e06060',
    'yellow': '#e0c040',
    'blue':   '#5080d0',
    'green':  '#50b070',
}

_COLOR_SHAPE = {
    'red':    NF_CARET_U,
    'yellow': NF_ONLINE,
    'blue':   NF_CARET_D,
    'green':  NF_DIAMOND,
}

COLOR_SEQ = ['red', 'yellow', 'blue', 'green']

_DOC_COMMANDS = {
    'create', 'rooms', 'start', 'invite', 'kick', 'bot',
    'roll', 'move', 'back', 'help', 'forfeit',
}


# ─────────────────────────── 坐标定义（19×19 真实网格）──────────
#
# 19×19 布局：
#   · 4 个 7×7 机场块（四角），各含 4 格 2×2 停机位
#   · 外环 track 72 格（每色 18 格，环绕 + 形状外沿）
#   · 4 条 runway 各 8 格（横/纵贯通中心十字）
#   · 中心终点 (9, 9)
# 所有 * 格都是可走路径；不存在纯装饰格。

_AIRPORT_COORDS: dict[str, list[tuple[int, int]]] = {
    'red':    [(3, 3),  (3, 4),  (4, 3),  (4, 4)],
    'yellow': [(3, 14), (3, 15), (4, 14), (4, 15)],
    'blue':   [(14, 14), (14, 15), (15, 14), (15, 15)],
    'green':  [(14, 3), (14, 4), (15, 3), (15, 4)],
}

# Track 72 格（顺时针）。起点：red=0 yellow=18 blue=36 green=54（间隔 18）。
# 每臂外沿 7+4+7 = 18 格，自然衔接 + 形状 4 个凹角。
_PATH_COORDS: list[tuple[int, int]] = [
    # [0..6]  红起点 → 上臂左外沿
    (7, 1), (7, 2), (7, 3), (7, 4), (7, 5), (7, 6), (7, 7),
    # [7..13] 上臂向上（col 7）
    (6, 7), (5, 7), (4, 7), (3, 7), (2, 7), (1, 7), (0, 7),
    # [14..17] 上臂顶端（row 0）
    (0, 8), (0, 9), (0, 10), (0, 11),
    # [18..24] 黄起点 → 上臂向下（col 11）
    (1, 11), (2, 11), (3, 11), (4, 11), (5, 11), (6, 11), (7, 11),
    # [25..31] 右臂上外沿（row 7）
    (7, 12), (7, 13), (7, 14), (7, 15), (7, 16), (7, 17), (7, 18),
    # [32..35] 右臂顶端（col 18）
    (8, 18), (9, 18), (10, 18), (11, 18),
    # [36..42] 蓝起点 → 右臂下外沿（row 11 向左）
    (11, 17), (11, 16), (11, 15), (11, 14), (11, 13), (11, 12), (11, 11),
    # [43..49] 下臂向下（col 11）
    (12, 11), (13, 11), (14, 11), (15, 11), (16, 11), (17, 11), (18, 11),
    # [50..53] 下臂底端（row 18）
    (18, 10), (18, 9), (18, 8), (18, 7),
    # [54..60] 绿起点 → 下臂向上（col 7）
    (17, 7), (16, 7), (15, 7), (14, 7), (13, 7), (12, 7), (11, 7),
    # [61..67] 左臂下外沿（row 11 向左）
    (11, 6), (11, 5), (11, 4), (11, 3), (11, 2), (11, 1), (11, 0),
    # [68..71] 左臂顶端（col 0）
    (10, 0), (9, 0), (8, 0), (7, 0),
]
assert len(_PATH_COORDS) == 72

_START_IDX = {0: 'red', 18: 'yellow', 36: 'blue', 54: 'green'}

# Runway 每色 8 格（从 turn_in 相邻格进入，指向中心 (9,9)）
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

_RUNWAY_CHARS = {
    'red': f'{NF_ARROW_R} ', 'yellow': f'{NF_ARROW_D} ',
    'blue': f'{NF_ARROW_L} ', 'green': f'{NF_ARROW_U} ',
}

# Finish 只有中心一格（其余中心十字延长段全部属于 runway）
_FINISH_CENTER = (9, 9)

TRACK_LEN = 72

# 4 个 JP 格（每色 ST 后第 9 格，offset +8）→ JP 拥有色。
# 与服务端 _JP_OWNER 保持一致。
_JP_OWNER = {
    8:  'red',     # red ST=0,   第 9 格 → (5, 7)
    26: 'yellow',  # yellow ST=18 → (7, 13)
    44: 'blue',    # blue ST=36 → (13, 11)
    62: 'green',   # green ST=54 → (11, 5)
}

# 每对 JP 跳跃的箭头指示格（仅无路格，bg 透明，fg = JP 拥有色）。
# 跳跃轨迹 4 格；中间偶数格落在 runway（有路），不画；仅画两端相邻的
# 奇数格（第 1、3 格）。
_JP_TRAIL: dict[int, list[tuple[int, int, str]]] = {
    # red JP (5, 7) → (5, 11)
    8:  [(5, 8, f'{NF_ARROW_R} '), (5, 10, f'{NF_ARROW_R} ')],
    # yellow JP (7, 13) → (11, 13)
    26: [(8, 13, f'{NF_ARROW_D} '), (10, 13, f'{NF_ARROW_D} ')],
    # blue JP (13, 11) → (13, 7)
    44: [(13, 10, f'{NF_ARROW_L} '), (13, 8, f'{NF_ARROW_L} ')],
    # green JP (11, 5) → (7, 5)
    62: [(10, 5, f'{NF_ARROW_U} '), (8, 5, f'{NF_ARROW_U} ')],
}


# ─────────────────────────── Cell / Board 抽象 ──────────────────

class Cell:
    """真实网格上的一个单元格（2 列宽 × 1 行高）。"""
    __slots__ = ('bg', 'fg', 'text', 'bold')

    def __init__(self) -> None:
        self.bg: str | None = None
        self.fg: str = '#000000'
        self.text: str = '  '
        self.bold: bool = False

    def style(self) -> str:
        parts: list[str] = []
        if self.bold:
            parts.append('bold')
        parts.append(self.fg)
        if self.bg:
            parts.append(f'on {self.bg}')
        return ' '.join(parts)


class Board:
    """19×19 真实坐标网格。渲染做一次线性扫描。"""

    _KEEP_BG = object()  # sentinel: 保留原 bg

    def __init__(self, rows: int = 19, cols: int = 19) -> None:
        self.rows = rows
        self.cols = cols
        self._cells: list[list[Cell]] = [
            [Cell() for _ in range(cols)] for _ in range(rows)
        ]

    def at(self, y: int, x: int) -> Cell:
        return self._cells[y][x]

    def set(self, y: int, x: int, text: str, fg: str = '#000000',
            bg=_KEEP_BG, bold: bool = False) -> None:
        if cell_width(text) != 2:
            raise ValueError(f"board cell text must occupy 2 cells: {text!r}")
        c = self._cells[y][x]
        c.text = text
        c.fg = fg
        c.bold = bold
        if bg is not Board._KEEP_BG:
            c.bg = bg

    def render(self, indent: str = '    ') -> Text:
        t = Text()
        for row in self._cells:
            t.append(indent)
            for c in row:
                t.append(c.text, style=c.style())
            t.append('\n')
        return t


# ─────────────────────────── 绘制层 ─────────────────────────────

def _paint_airports(board: Board, board_data: dict,
                    anim: dict | None) -> None:
    for color, coords in _AIRPORT_COORDS.items():
        bg = _COLOR_MAP[color]
        shape = _COLOR_SHAPE.get(color, NF_ONLINE)
        occupied: set[int] = set()
        for p in board_data.get(color, []):
            pp = p
            if (anim and anim.get('color') == color
                    and anim.get('piece_idx') == p.get('index')):
                pp = {**p, **anim.get('snapshot', {})}
            if pp.get('state') == 'airport':
                occupied.add(pp.get('index', 0))
        for i, (y, x) in enumerate(coords):
            if i in occupied:
                board.set(y, x, f'{shape}{i + 1}',
                          fg='#000000', bg=bg, bold=True)
            else:
                board.set(y, x, '  ', bg=bg)


def _paint_track(board: Board) -> None:
    for t, (y, x) in enumerate(_PATH_COORDS):
        if t in _JP_OWNER:
            color = _JP_OWNER[t]
        elif t in _START_IDX:
            color = _START_IDX[t]
        else:
            color = COLOR_SEQ[t % 4]
        bg = _COLOR_MAP[color]
        if t in _JP_OWNER:
            board.set(y, x, 'JP', fg='#000000', bg=bg, bold=True)
        elif t in _START_IDX:
            board.set(y, x, 'ST', fg='#000000', bg=bg, bold=True)
        else:
            board.set(y, x, '  ', fg='#000000', bg=bg, bold=False)


def _paint_jp_trails(board: Board) -> None:
    """绘制每对 JP 之间的飞行轨迹（仅无路格，bg 透明，fg = JP 拥有色）。"""
    for jp_idx, cells in _JP_TRAIL.items():
        color = _JP_OWNER[jp_idx]
        fg = _COLOR_MAP[color]
        for y, x, arrow in cells:
            board.set(y, x, arrow, fg=fg, bg=None, bold=True)


def _paint_runways(board: Board) -> None:
    for color, coords in _RUNWAY_COORDS.items():
        bg = _COLOR_MAP[color]
        char = _RUNWAY_CHARS[color]
        for y, x in coords:
            board.set(y, x, char, fg='#ffffff', bg=bg, bold=False)


def _paint_finish(board: Board) -> None:
    y, x = _FINISH_CENTER
    # 中心终点：深灰底 + 方格旗
    board.set(y, x, f'{NF_FLAG} ', fg='#ffffff', bg='#2a2a2a', bold=True)


def _collect_pieces(board_data: dict, anim: dict | None
                    ) -> dict[tuple[int, int], list[tuple[str, int]]]:
    cells: dict[tuple[int, int], list[tuple[str, int]]] = {}
    for color in COLOR_SEQ:
        for p in board_data.get(color, []):
            if (anim and anim.get('color') == color
                    and anim.get('piece_idx') == p.get('index')):
                p = {**p, **anim.get('snapshot', {})}
            s = p.get('state')
            idx = p.get('index', 0)
            co: tuple[int, int] | None = None
            if s == 'airport':
                continue
            if s == 'track':
                co = _PATH_COORDS[p.get('track_pos', 0) % TRACK_LEN]
            elif s == 'runway':
                co = _RUNWAY_COORDS[color][min(p.get('runway_pos', 0), 7)]
            elif s == 'finished':
                co = _FINISH_CENTER
            elif s == 'fly':
                co = (int(p.get('y', 0)), int(p.get('x', 0)))
            if co is not None:
                cells.setdefault(co, []).append((color, idx))
    return cells


def _collect_previews(previews: dict, viewer_color: str | None
                      ) -> tuple[set[tuple[int, int]],
                                 set[tuple[int, int]],
                                 set[tuple[int, int]]]:
    """返回 (path_set, mid_set, dest_set)。
    mid_set = 骰子本身走完的落点，若其后仍有跳跃/飞行段则单独标记；
              如无额外跳跃则为空（dest_set 即骰子落点）。
    """
    dest_set: set[tuple[int, int]] = set()
    mid_set: set[tuple[int, int]] = set()
    path_set: set[tuple[int, int]] = set()
    if not previews or not viewer_color:
        return path_set, mid_set, dest_set

    def _coord(snap: dict, c: str) -> tuple[int, int] | None:
        s = snap.get('state')
        if s == 'track':
            return _PATH_COORDS[snap.get('track_pos', 0) % TRACK_LEN]
        if s == 'runway':
            return _RUNWAY_COORDS[c][min(snap.get('runway_pos', 0), 7)]
        if s == 'finished':
            return _FINISH_CENTER
        if s == 'fly':
            return (int(snap.get('y', 0)), int(snap.get('x', 0)))
        return None

    for _, pv in previews.items():
        if not isinstance(pv, dict):
            continue
        path = pv.get('path') or []
        if not path:
            continue
        c = path[0].get('color', viewer_color)
        # 找到第一个 fly 帧；若存在，其前一帧 = 骰子落点（JP 格）
        mid_idx = -1
        for i, snap in enumerate(path):
            if snap.get('state') == 'fly':
                mid_idx = i - 1
                break
        dest_idx = len(path) - 1
        for i, snap in enumerate(path):
            co = _coord(snap, snap.get('color', c))
            if co is None:
                continue
            if i == dest_idx:
                dest_set.add(co)
            elif i == mid_idx:
                mid_set.add(co)
            else:
                path_set.add(co)
    return path_set, mid_set, dest_set


def _paint_previews(board: Board,
                    path_set: set[tuple[int, int]],
                    mid_set: set[tuple[int, int]],
                    dest_set: set[tuple[int, int]],
                    cell_pieces: dict[tuple[int, int], list[tuple[str, int]]],
                    viewer_color: str | None,
                    blink_on: bool) -> None:
    def _has_viewer(co: tuple[int, int]) -> bool:
        if not viewer_color:
            return False
        return any(c == viewer_color for c, _ in cell_pieces.get(co, []))

    for co in path_set - dest_set - mid_set:
        if _has_viewer(co):
            continue
        y, x = co
        board.set(y, x, '··', fg='#d0d0d0')

    # 骰子落点（后续还有跳跃/飞行）：明显的圆点标记
    for co in mid_set - dest_set:
        if _has_viewer(co):
            continue
        y, x = co
        board.set(y, x, f'{NF_BULLSEYE} ', fg='#ffffff', bold=True)

    for co in dest_set:
        if _has_viewer(co):
            continue
        y, x = co
        lst = cell_pieces.get(co, [])
        has_enemy = any(c != viewer_color for c, _ in lst)
        if has_enemy:
            text = f'{NF_CROSS} ' if blink_on else f'{NF_STAR} '
            board.set(y, x, text, fg='#ff4040', bold=True)
        elif blink_on:
            board.set(y, x, f'{NF_STAR} ', fg='#ffff00', bold=True)
        else:
            board.set(y, x, '· ', fg='#b0b060')


def _paint_pieces(board: Board,
                  cell_pieces: dict[tuple[int, int], list[tuple[str, int]]],
                  blink_on: bool) -> None:
    for co, lst in cell_pieces.items():
        y, x = co
        if len(lst) > 1:
            sel = 0 if blink_on else 1
            color, idx = lst[sel % len(lst)]
        else:
            color, idx = lst[0]
        shape = _COLOR_SHAPE.get(color, NF_ONLINE)
        text = f'{shape}{idx + 1}'
        board.set(y, x, text, fg='#000000', bold=True)


# ─────────────────────────── 主渲染入口 ─────────────────────────

def _render_ascii_board(board_data: dict, viewer_color: str | None,
                        interaction: dict | None) -> Text:
    anim = interaction.get('anim_override') if interaction else None
    previews = (interaction or {}).get('move_previews') or {}
    blink_on = bool((interaction or {}).get('blink_on', True))

    board = Board(19, 19)

    _paint_track(board)
    _paint_runways(board)
    _paint_finish(board)
    _paint_airports(board, board_data, anim)
    _paint_jp_trails(board)

    cell_pieces = _collect_pieces(board_data, anim)
    path_set, mid_set, dest_set = _collect_previews(previews, viewer_color)
    _paint_previews(board, path_set, mid_set, dest_set, cell_pieces,
                    viewer_color, blink_on)
    _paint_pieces(board, cell_pieces, blink_on)

    out = board.render()
    out.append('\n')
    return out


# ─────────────────────────── 其余辅助 ───────────────────────────

def _count_pieces(board_data: dict) -> dict:
    result: dict[str, tuple[int, int, int, int]] = {}
    for c in COLOR_SEQ:
        ap = tr = rw = fi = 0
        for p in board_data.get(c, []):
            s = p.get('state')
            if s == 'airport':
                ap += 1
            elif s == 'track':
                tr += 1
            elif s == 'runway':
                rw += 1
            elif s == 'finished':
                fi += 1
        result[c] = (ap, tr, rw, fi)
    return result


class LudoRenderer:
    game_type = 'ludo'
    icon = NF_PLANE
    glyphs = frozenset({
        NF_ARROW_D, NF_ARROW_L, NF_ARROW_R, NF_ARROW_U, NF_BULLSEYE,
        NF_CARET_D, NF_CARET_U, NF_CROSS, NF_DIAMOND, NF_FLAG, NF_OFFLINE,
        NF_ONLINE, NF_PLANE, NF_STAR, NF_TROPHY,
    })
    no_scroll = True
    doc_commands = _DOC_COMMANDS

    def render_doc(self, text: str) -> RenderableType:
        return render_doc(text, _DOC_COMMANDS)

    def render_board(self, room_data: dict, interaction: dict | None = None,
                     board_width: int = 80, board_height: int = 30
                     ) -> dict[str, RenderableType | None]:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return {'info': None, 'board': self._render_waiting(room_data),
                    'controls': None}
        if state in ('playing', 'finished'):
            return self._render_game(room_data, interaction)
        return {'info': None, 'board': self._render_lobby(room_data),
                'controls': None}

    def _render_lobby(self, data: dict) -> RenderableType:
        doc = data.get('doc')
        if doc:
            return render_doc(doc, _DOC_COMMANDS)
        msg = data.get('message')
        if msg:
            t = Text()
            for line in msg.split('\n'):
                t.append(f'  {line}\n', style=_SCORE)
            return t
        return Text('')

    def _render_waiting(self, data: dict) -> RenderableType:
        text = Text()
        room_id = data.get('room_id', '????')
        host = data.get('host', '???')
        players = data.get('players', [])
        max_p = data.get('max_players', 4)
        ready = set(data.get('ready') or [])
        bots = set(data.get('bots') or [])
        text.append('  等待中\n\n', style=_HEAD)
        text.append(f'  房间 #{room_id}  房主: {host}\n', style=_SCORE)
        text.append(f'  等待中 ({len(players)}/{max_p})\n\n', style=_DIM)
        for p in players:
            if p == host:
                # 房主：金色实心圆
                text.append(f'  {NF_ONLINE} ', style='#d4a017')
                text.append(f'{p}\n', style='#c0c0c0')
            elif p in ready or p in bots:
                # 已准备 / Bot：绿色实心圆
                text.append(f'  {NF_ONLINE} ', style='#81c784')
                text.append(f'{p}\n', style='#c0c0c0')
            else:
                # 未准备：白色空心圆
                text.append(f'  {NF_OFFLINE} ', style='#ffffff')
                text.append(f'{p}\n', style='#c0c0c0')
        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)
        return text

    def _render_game(self, data: dict, interaction: dict | None = None
                     ) -> dict[str, RenderableType | None]:
        player_colors = data.get('player_colors', {})
        current = data.get('current_player', '')
        dice = data.get('dice', 0)
        board_data = data.get('board', {})
        rankings = data.get('rankings', [])
        state = data.get('room_state', 'playing')
        pending_move = data.get('pending_move', False)

        my_turn = interaction.get('my_turn', False) if interaction else False

        info = Text()
        _GAP = '  '
        dice_text = f'骰子: {dice}' if dice > 0 else '骰子: -'
        info.append('  ' + dice_text, style=_HEAD if dice > 0 else _DIM)
        info.append(_GAP)
        if my_turn:
            if pending_move:
                info.append(f'{NF_STAR} 请选择棋子移动', style='bold #e0c040')
            else:
                info.append(f'{NF_STAR} 你的回合 — 掷骰子', style='bold #e0c040')
        elif current:
            info.append(f'等待 {current}', style=_DIM)
        info.append('\n')

        board = Text()
        ordered = [c for c in COLOR_SEQ
                   if any(mc == c for mc in player_colors.values())]
        color_to_owner = {
            c: next((n for n, mc in player_colors.items() if mc == c), None)
            for c in ordered
        }
        max_name_len = max(
            [cell_width(n or '') for n in color_to_owner.values()] + [0]
        )
        piece_counts = _count_pieces(board_data)
        for c in ordered:
            owner = color_to_owner[c] or '???'
            is_cur = (owner == current)
            prefix = '> ' if is_cur else '  '
            name_style = _ACTIVE if is_cur else _SCORE
            board.append(prefix, style=_DIM)
            board.append(f' {_COLOR_SHAPE[c]} ',
                         style=f'bold #000000 on {_COLOR_MAP[c]}')
            board.append(' ')
            name_padded = owner + ' ' * max(
                0, max_name_len - cell_width(owner))
            board.append(name_padded, style=name_style)
            cnt = piece_counts.get(c, (4, 0, 0, 0))
            board.append(
                f'   机场:{cnt[0]} 赛道:{cnt[1]} 跑道:{cnt[2]} 完成:{cnt[3]}',
                style=_DIM,
            )
            board.append('\n')
        board.append('\n')

        viewer_color = interaction.get('viewer_color') if interaction else None
        board.append_text(_render_ascii_board(
            board_data, viewer_color, interaction))

        if state == 'finished' and rankings:
            board.append('\n')
            for i, p in enumerate(rankings):
                o = f'{NF_TROPHY} {i + 1}'
                board.append(f'  {o} {p}\n',
                             style=_HEAD if i == 0 else _SCORE)

        msg = data.get('message')
        if msg:
            board.append(f'\n  {msg}\n', style=_SCORE)

        controls = None
        if interaction and interaction.get('buttons'):
            buttons = interaction['buttons']
            btn_cursor = interaction.get('btn_cursor', 0)
            btn_active = interaction.get('active', True)

            controls = Text()
            _render_button_row(controls, buttons, btn_cursor,
                               btn_active, my_turn)

        return {'info': info, 'board': board, 'controls': controls}


def _render_button_row(text: Text, buttons: list[dict], cursor: int,
                       active: bool, my_turn: bool) -> None:
    if not buttons:
        return
    btn_styles = []
    for i, btn in enumerate(buttons):
        label = btn.get('label', '?')
        is_cursor = active and i == cursor
        if not my_turn:
            style = '#505050'
            b_style = f'bold {_BORDER_PLAYABLE}' if is_cursor else '#505050'
        else:
            style = 'bold #ffffff'
            b_style = (f'bold {_BORDER_CURSOR}' if is_cursor
                       else 'bold #a0a0a0')
        btn_styles.append((label, style, b_style))

    text.append('  ')
    for label, _, b_style in btn_styles:
        w = max(8, cell_width(label) + 2)
        text.append('╭' + '─' * w + '╮', style=b_style)
        text.append(' ')
    text.append('\n  ')

    for label, style, b_style in btn_styles:
        w = max(8, cell_width(label) + 2)
        padded = fit_cells(label, w, "center")
        text.append('│', style=b_style)
        text.append(padded, style=style)
        text.append('│', style=b_style)
        text.append(' ')
    text.append('\n  ')

    for label, _, b_style in btn_styles:
        w = max(8, cell_width(label) + 2)
        text.append('╰' + '─' * w + '╯', style=b_style)
        text.append(' ')
    text.append('\n')


register_renderer(LudoRenderer())
