"""棋盘上的图形：内野正方形 + 投打 / 外野 / 传球三条固定行。

内野：四个垒包连成正方形，四条边都画通，垒名在方框外面，方框里面是三行钉死位置的实时槽。
三条行（`ProgressTrack` 及其子类）永远都在，任何阶段都不出现、不消失、不变形：
排版（左边距、前缀、结果符号、两条边界竖线、格点、右竖线外的留白）全在基类，
子类只回答"这一帧这一行有什么"。所有字形一律按一列量宽（中日韩文字两列），
宽字形连格子一起占，所以每一行的宽度都由格点数决定、永远相等。
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from ...config import (
    COLOR_GAME_BALL, COLOR_GAME_FIELDER, COLOR_GAME_MARK, NF_ARROW_D,
    NF_ARROW_L, NF_ARROW_R, NF_ARROW_U, NF_CIRCLE_NOTCH, NF_CROSS,
    NF_HIT_FLAT, NF_HIT_HIGH, NF_HIT_LOW, NF_OFFLINE, NF_ONLINE, NF_USER,
)
from ...protocol.animation import Animator
from ...window_engine import PinnedSlots
from ...window_engine.text import cell_width, grapheme_clusters
from . import style
from .view import STAGE_SWING, Board, Runner

BOARD_HEIGHT_UNKNOWN = 19   # 棋盘区还没排版（高度为 0）时的兜底：88×32 下棋盘区 19 行

# 正方形尺寸：随棋盘区缩放，屏幕上一个字符格约 2:1，所以高 ≈ 宽 / 2
SQUARE_INDENT = 2           # 正方形左边的留白（三条行、垒名行共用，整块棋盘左边是一条直线）
_SQUARE_MARGIN = 6          # 左留白 + 角上标记 + 两侧空格
_SQUARE_OVERHEAD = 7        # 上下垒名 2 行 + 投打行 / 传球行 / 外野线 3 行 + 余量 2
_MIN_EDGE = 10
_MIN_ROWS = 3
_MAX_ROWS = 26

# 三条固定行各自的前缀：2 个汉字（＝4 列）+ 1 个空格
_ROW_LABELS = {'pitch': '投打 ', 'throw': '传球 ', 'field': '外野 '}
# 前缀宽度自己量：标签一改宽度自动跟上，不用手抄一个常量
_LABEL_COLS = max(cell_width(label) for label in _ROW_LABELS.values())
_ICON_COLS = 1              # 结果符号占几列：所有字形都占一列（见 config 的宽度契约）
_HEAD_GAP = 1               # 结果符号和左竖线之间留一格（贴在一起＝相切，用户 2026-10-15 报）
_BAR_GLYPH = '│'            # 轨道两侧的边界竖线（三条行同一列，用户 2026-10-15 定）
_BAR_COLS = 1
# 左竖线左边的宽度：左边距 + 前缀 + 结果符号那一列
_ROW_PREFIX_COLS = _LABEL_COLS + _ICON_COLS + _HEAD_GAP
_ROW_LEFT_COLS = SQUARE_INDENT + _ROW_PREFIX_COLS + _BAR_COLS
_FIELD_CELL_MAX = 6         # 外野每格最多拉宽到几列
_WALL_COLS = 3              # 本垒打墙至少有这么宽（余数都归它，铺到棋盘右边缘）
_WALL_GLYPH = '█'           # 墙用实心块画
GUIDE_GLYPH = '┆'           # 击球时机分界线：投打行上淡色的细线，不写字
SPAN_GLYPH = '─'            # 落点范围：一条细横线，两端收成半截线，随球飞近一路缩短
SPAN_CAPS = ('╶', '╴')
SPAN_POINT = 1.0            # 范围窄到不足一格，就收成一个虚线圈（落点）

_BASE_NUMBERS = {'一垒': 1, '二垒': 2, '三垒': 3}
_BASE_NAMES = {number: name for name, number in _BASE_NUMBERS.items()}

# 棋盘中间的实时槽（用户 2026-10-15 定）：高度位置钉死，某一槽没内容就是留白——
# 别的内容绝不允许挤过来。倒数 / 灯或球位 / 当前动作钉在方框的 1/4、1/2、3/4；
# 判定另有自己的一槽（第 2 行，倒数槽上方），不和交牌灯共用，所以出结果后灯还在原位
# （用户 2026-11-15 定：东西都在原位，亮不亮都占同样空间）。
# 自上而下：判定（第 1 行）/ 倒数 / 灯或球位 / 当前动作
LIVE_SLOTS = PinnedSlots(1, 0.25, 0.5, 0.75)
# 这一拍的判定：实时状态一律中文 + 英文（英文是权威写法）；
# 颜色按结果分：安全/保送＝绿、各种出局/三振/双杀＝红、全垒打＝金（用户 2026-10-16 定）；
# 出局按方式写清（2026-10-21 用户要求显示封杀 / 接杀）
_VERDICT_LABELS = {
    'safe': '安全 SAFE',
    'catch_out': '接杀 FLY OUT',
    'force_out': '封杀 FORCE OUT',
    'tag_out': '触杀 TAG OUT',
    'homerun': '全垒打 HOME RUN',
    'strikeout': '三振 STRIKEOUT',
    'walk': '保送 WALK',
    'double_play': '双杀 DOUBLE PLAY',
}
_VERDICT_STYLES = {
    'safe': style.READY, 'walk': style.READY,
    'catch_out': style.BALL, 'force_out': style.BALL, 'tag_out': style.BALL,
    'strikeout': style.BALL, 'double_play': style.BALL,
    'homerun': style.MARK,
}

Segments = list[tuple[str, str]]       # 一槽的内容：[(文字, 样式), …]，空槽＝空列表


# ── 正方形（四条边都画通，垒包就是四个角） ──

def square_size(board_width: int, board_height: int) -> tuple[int, int]:
    """正方形取棋盘区能放下的最大尺寸：(每边格数, 中间行数)。"""
    height = board_height or BOARD_HEIGHT_UNKNOWN
    rows = min(_MAX_ROWS, max(_MIN_ROWS, height - _SQUARE_OVERHEAD))
    edge = max(_MIN_EDGE, min(board_width - _SQUARE_MARGIN, rows * 2))
    return edge, rows


def situation_label(board: Board) -> str:
    """当前这一拍在干什么：最多三个字，不写句子（棋盘中间的槽用它）。"""
    phase = board.phase
    if phase == 'delivery':
        return '挥棒' if board.delivery.stage == STAGE_SWING else '投球'
    if phase == 'throw':
        return '传球'
    if phase == 'flight':
        return '追球' if board.fielding_side else '跑垒'
    if phase == 'ground':
        if not board.fielding_side:
            return '跑垒'
        if board.ground.base:
            return '转传'
        return '传球' if board.ground.at_ball else '捡球'
    if phase == 'tag':
        return '触垒' if board.batting_side else '等触垒'
    if phase == 'call':
        return '打击' if board.batting_side else '投球'
    if board.winner:
        return f'{board.winner} 胜'
    return '等待'


def ready_segments(board: Board) -> Segments:
    """两边交牌了没有：实心绿灯＝已交牌，空心＝还没（用户定档）。

    返回段列表而不是字符串：绿灯的颜色写在格子的样式上，
    不往文字里塞富文本标记（格子不解析标记，塞了会原样显示出来）。
    """
    segments: Segments = []
    for ready, label in ((board.ready_fielding, '投'),
                         (board.ready_batting, '打')):
        if segments:
            segments.append(('  ', style.DIM))
        segments.append((f'{label} ', style.HEAD))
        segments.append((NF_ONLINE, style.READY) if ready
                        else (NF_OFFLINE, style.DIM))
    return segments


def live_slot_segments(
        board: Board) -> tuple[Segments, Segments, Segments, Segments]:
    """方框中间四槽的内容，自上而下：判定 / 倒数 / 交牌灯（或球的方位）/ 当前动作。

    每样东西各占自己钉死的一槽，互不顶替：判定出来后交牌灯照旧在中槽（下一球的准备阶段
    两盏灯一直都在），只是"这一槽此刻写什么"。球被打出去之后、还没判出安全/出局之前，
    中槽写球的方位（飞向哪 / 落在哪），守方攻方都能一眼对上球路。

    样式走格点自己的（一格一样式），**绝不把富文本标记塞进文字**——格子不解析标记，
    塞进去玩家就会看到 `[#50b070]` 这种生字符串（2026-10-17 实机抓到的 bug）。
    """
    verdict: Segments = ([(_VERDICT_LABELS[board.verdict],
                            _VERDICT_STYLES[board.verdict])]
                         if board.verdict else [])
    countdown: Segments = ([(str(board.countdown), style.HEAD)]
                           if board.countdown > 0 else [])
    if board.phase == 'call':
        middle = ready_segments(board)
    elif board.phase == 'flight':
        middle = [(f'飞向 {board.flight.estimate_label}', style.HEAD)]
    elif board.phase == 'ground':
        middle = [(f'落点 {board.ground.ball_label}', style.HEAD)]
    else:
        middle = []
    return verdict, countdown, middle, [(situation_label(board), style.HEAD)]


Cells = list[list[tuple[str, str]]]


def _put_cell(border: Cells, row: int, col: int, glyph: str,
              glyph_style: str) -> None:
    """在格子里落一个字形：宽的字形（中文占两列）把后面的格子一起占掉。

    格点是一列一格的：一个汉字画两列、若只占一格，这一行后面所有东西都会
    被顶出去一列（用户 2026-10-15 报的"垒包中间的文字导致没对齐"）。
    """
    if not (0 <= row < len(border) and 0 <= col < len(border[row])):
        return
    border[row][col] = (glyph, glyph_style)
    for extra in range(1, max(1, cell_width(glyph))):
        if col + extra < len(border[row]):
            border[row][col + extra] = ('', glyph_style)


def _blend(low: str, high: str, ratio: float) -> str:
    """两个 `#rrggbb` 之间按比例插值（0＝low，1＝high）。"""
    return '#%02x%02x%02x' % tuple(
        round(a + (b - a) * ratio)
        for a, b in zip(_rgb(low), _rgb(high)))


def _rgb(value: str) -> tuple[int, int, int]:
    """`#rrggbb` → 三个 0–255 的分量（距离配色只在客户端算，服务端不认识颜色）。"""
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _distance_colors(meters: dict) -> dict[str, str]:
    """四个垒的距离 → 颜色：按这四个值互相之间的远近插值（绿→金→红，平滑）。"""
    if not meters:
        return {}
    low, high = min(meters.values()), max(meters.values())
    if high - low < 0.1:                       # 四个垒几乎一样远：统一用中间色
        high = low + 1.0
    colors = {}
    for base, meter in meters.items():
        ratio = max(0.0, min(1.0, (meter - low) / (high - low)))
        if ratio <= 0.5:
            colors[base] = _blend(COLOR_GAME_FIELDER, COLOR_GAME_MARK,
                                  ratio * 2)
        else:
            colors[base] = _blend(COLOR_GAME_MARK, COLOR_GAME_BALL,
                                  (ratio - 0.5) * 2)
    return colors


class Infield:
    """内野正方形：左上 三垒、右上 二垒、右下 一垒、左下 本垒。

    四条边一路画通（垒包就是四个角上的标记）；正在跑垒的人画在线上，一格一格挪。
    垒名与传球距离写在方框外面；方框**里面**是三行固定位置的实时槽。
    """

    def __init__(self, board: Board, anim: Animator | None,
                 board_width: int, board_height: int) -> None:
        self.board = board
        self.anim = anim
        self.edge, self.rows = square_size(board_width, board_height)
        self.width = self.edge + _SQUARE_MARGIN
        self.left = SQUARE_INDENT
        self.right = self.left + self.edge + 3

    def render(self) -> list[Text]:
        board = self.board
        marks = self._base_marks()
        styles = {name: self._base_style(name) for name in marks}
        border: Cells = [[(' ', style.DIM)] * (self.right + 1)
                         for _ in range(self.rows + 2)]
        for col in range(self.left + 2, self.right - 1):
            border[0][col] = ('─', style.DIM)
            border[self.rows + 1][col] = ('─', style.DIM)
        for row in range(1, self.rows + 1):
            border[row][self.left] = ('│', style.DIM)
            border[row][self.right] = ('│', style.DIM)
        for row, segments in zip(self.slot_rows(), live_slot_segments(board)):
            if segments and row is not None:
                self._write_slot(border, row, segments)
        corners = {'三垒': (0, self.left), '二垒': (0, self.right),
                   '本垒': (self.rows + 1, self.left),
                   '一垒': (self.rows + 1, self.right)}
        for name, (row, col) in corners.items():
            _put_cell(border, row, col, marks[name], styles[name])
        self._place_runners(border)
        distances = self._distances()
        spans = _distance_colors(board.base_distances)
        return [
            self._corner_row('三垒', '二垒', distances, spans),
            *[self._row_text(row) for row in border],
            self._corner_row('本垒', '一垒', distances, spans),
        ]

    @staticmethod
    def _row_text(row: list[tuple[str, str]]) -> Text:
        text = Text()
        for glyph, glyph_style in row:
            text.append(glyph, style=glyph_style)
        return text

    def _base_marks(self) -> dict[str, str]:
        """垒包上的标记：站稳＝实心圆，正在跑向该垒＝箭头，打者始终在本垒。"""
        marks = {'本垒': NF_USER}
        for number, name in _BASE_NAMES.items():
            marks[name] = (NF_ONLINE if number in self.board.bases
                           else NF_OFFLINE)
        for runner in self.board.runners:
            name = _BASE_NAMES.get(runner.to)
            if name and not runner.out:
                marks[name] = NF_ONLINE if runner.settled else NF_ARROW_R
        return marks

    def _base_style(self, name: str) -> str:
        if name == self._throw_target():
            return style.BALL
        if name == '本垒':
            return style.HEAD
        number = _BASE_NUMBERS[name]
        for runner in self.board.runners:
            if runner.to == number:
                return style.DIM if runner.out else style.MARK
        return style.MARK if number in self.board.bases else style.DIM

    def _throw_target(self) -> str:
        """角上高亮的目标垒：传球飞行时是目标垒，球停在垒上待转传时是球所在的垒。"""
        board = self.board
        if board.throw:
            return board.throw.base
        return board.ground.base if board.ground else ''

    def _distances(self) -> dict[str, str]:
        """四个垒的传球距离：球一被打出去就显示（服务端按"玩家看得见的球位"算好）。

        飞行阶段那组值是拿**预测落点**算的（真实落点保密），所以它只帮忙判断，
        不会把落点提前卖给守方。
        """
        board = self.board
        if board.base_distances:
            return {base: f'{meter}米'
                    for base, meter in board.base_distances.items()}
        options = ((board.ground.options if board.ground else ())
                   or (board.throw.options if board.throw else ()))
        if options:
            return {option.base: f'{option.distance}米' for option in options}
        if board.throw:
            return {board.throw.base: f'{board.throw.distance}米'}
        return {}

    def slot_rows(self) -> tuple[int | None, ...]:
        """四个实时槽在 border 里的行号（自上而下）；没位置的槽（太矮）不画。"""
        return tuple(None if row is None else 1 + row
                     for row in LIVE_SLOTS.rows(self.rows))

    def _write_slot(self, border: Cells, row: int,
                    segments: Segments) -> None:
        """把一槽写进方框中间那一行：居中，夹在两条竖线之间，绝不越界。"""
        width = sum(cell_width(text) for text, _ in segments)
        room = self.right - self.left - 1
        if width > room:
            return
        col = self.left + 1 + (room - width) // 2
        for text, segment_style in segments:
            for cluster in grapheme_clusters(text):
                span = max(1, cell_width(cluster))
                if col + span > self.right:
                    return
                _put_cell(border, row, col, cluster, segment_style)
                col += span

    def _corner_row(self, left: str, right: str, distances: dict[str, str],
                    spans: dict[str, str]) -> Text:
        """垒名那一行：球被打出去之后，垒名旁边写上"传到这个垒有多远"。

        垒名永远在原位（用户 2026-11-15 定：东西都在原位，亮不亮都占同样空间）：左边的名字
        贴左、距离写在它右边；右边的名字贴着方框右缘、距离写在它**左边**，所以有没有距离
        名字都不挪。颜色按四个垒之间的**相对远近平滑变化**：最近的偏绿、最远的偏红
        （用户 2026-10-16 定）。带距离之后要是比正方形还宽，就**连距离一起省掉**（只留垒名）：
        这一行的宽度是棋盘的骨架，宁可少写一个字也不许把它顶出去。
        """
        def shown(name: str, mirrored: bool) -> str:
            distance = distances.get(name)
            if not distance:
                return name
            return f'{distance} {name}' if mirrored else f'{name} {distance}'

        if (SQUARE_INDENT + cell_width(shown(left, False)) + 2
                + cell_width(shown(right, True))) > self.width:
            distances, spans = {}, {}
        gap = max(2, self.width - SQUARE_INDENT
                  - cell_width(shown(left, False))
                  - cell_width(shown(right, True)))
        text = Text(' ' * SQUARE_INDENT)
        self._append_corner(text, left, distances, spans, mirrored=False)
        text.append(' ' * gap)
        self._append_corner(text, right, distances, spans, mirrored=True)
        return text

    @staticmethod
    def _append_corner(text: Text, name: str, distances: dict[str, str],
                       spans: dict[str, str], *, mirrored: bool) -> None:
        """垒名 + 距离：有距离时名字提到正文亮度，
        距离退一档（只留远近配色、不加粗）——先看地形，再看数字（2026-10-17 定）。"""
        distance = distances.get(name)
        if distance and mirrored:
            text.append(distance + ' ', style=spans.get(name, style.DIM))
        text.append(name, style=style.TEXT if distance else style.DIM)
        if distance and not mirrored:
            text.append(' ' + distance, style=spans.get(name, style.DIM))

    def _base_cell(self, base: int) -> tuple[int, int]:
        """垒包在方框里的格子（行, 列）：0 和 4 都是本垒。"""
        return {0: (self.rows + 1, self.left), 4: (self.rows + 1, self.left),
                1: (self.rows + 1, self.right), 2: (0, self.right),
                3: (0, self.left)}[base]

    def _place_runners(self, border: Cells) -> None:
        """把正在跑垒的人画在垒线之间（站在垒上的人由角上的标记表示）。"""
        for runner in self.board.runners:
            if not runner.running:
                continue
            ratio = self._runner_ratio(runner)
            start, end = self._base_cell(runner.base), self._base_cell(runner.to)
            if start == end:
                continue
            row = round(start[0] + (end[0] - start[0]) * ratio)
            col = round(start[1] + (end[1] - start[1]) * ratio)
            if (row, col) in (start, end):
                continue                     # 没离开起垒或已到垒：角标记更清楚
            _put_cell(border, row, col, _runner_glyph(start, end),
                      style.RUNNER)

    def _runner_ratio(self, runner: Runner) -> float:
        if self.anim is None:
            return runner.ratio
        return self.anim.values.get(f'runner:{runner.key}', runner.ratio)


def _runner_glyph(start: tuple[int, int], end: tuple[int, int]) -> str:
    """跑者用指向目标的箭头表示，一眼能看出往哪边跑。"""
    row_delta = end[0] - start[0]
    col_delta = end[1] - start[1]
    if abs(col_delta) >= abs(row_delta):
        return NF_ARROW_R if col_delta > 0 else NF_ARROW_L
    return NF_ARROW_D if row_delta > 0 else NF_ARROW_U


# ── 三条固定行（球在飞的进度条） ──

def _field_cell(board_width: int, cells: int) -> int:
    """外野每格几列：窄窗口最少 2 列一格（46 列时也放得下），宽窗口最多 6 列。"""
    room_for_cells = max(cells * 2, board_width - _ROW_LEFT_COLS
                         - _BAR_COLS - _WALL_COLS)
    return max(2, min(_FIELD_CELL_MAX, room_for_cells // cells))


def wall_span(board_width: int, cells: int) -> tuple[int, int]:
    """右竖线右边那段留白在第几列：格点铺完之后剩下的整段。

    余数全部给它，格点间距因此保持均匀、整行又刚好铺到棋盘右边缘。
    三条行留同样的宽度，所以两条竖线在三行上同列；外墙、倒计时都写在这段留白里。
    """
    start = (_ROW_LEFT_COLS + cells * _field_cell(board_width, cells)
             + _BAR_COLS)
    return start, max(_WALL_COLS, board_width - start)


@dataclass(frozen=True)
class TrackMark:
    """格点上的一样东西：格位（可带小数，客户端插值出来的）、字形、样式。

    每个字形占一列，标记落在一个格子上，永远不会压到旁边的格点。
    """

    cell: float
    glyph: str
    style: str


@dataclass(frozen=True)
class TrackSpan:
    """轨道上的一段范围：从 low 格到 high 格（可带小数）。"""

    low: float
    high: float
    style: str


def home_mark(last_ball: str) -> str:
    """本垒上的结果符号（用户定档）：空心圆 / 叉 / 右上・右・右下箭头。"""
    return {
        'whiff': NF_CROSS,          # 挥空
        'fly': NF_HIT_HIGH,         # 高飞 / 全垒打
        'line': NF_HIT_FLAT,        # 平飞
        'ground': NF_HIT_LOW,       # 滚地
    }.get(last_ball, NF_OFFLINE)


class ProgressTrack:
    """棋盘底部那条「球在飞」的轨道：投打行 / 外野线 / 传球行共用一个实现。

    基类负责排版——前缀、结果符号那一列、格点铺满整行、右端墙（或等宽留白）；
    子类只回答"这一帧这一行有什么"（`head()` / `marks()` / `_tail()`）。宽度与格点因此
    不可能在三条行之间走样，也不会有人重复算一遍。
    """

    label: str = _ROW_LABELS['field']

    def __init__(self, board: Board, anim: Animator | None,
                 board_width: int) -> None:
        self.board = board
        self.anim = anim
        self.board_width = board_width
        self.cells = board.cells
        self.slot = _field_cell(board_width, self.cells)

    # ── 子类要回答的 ──

    def head(self) -> TrackMark | None:
        """前缀后面那一列（投打行画本垒结果符号，其余行留空）。"""
        return None

    def marks(self) -> list[TrackMark]:
        """这一帧往格点上放什么（球、人、垒名、预测落点圈）。"""
        return []

    def guides(self) -> list[int]:
        """轨道里画细线的列（只有投打行有：击球时机的分界）。"""
        return []

    def spans(self) -> list[TrackSpan]:
        """轨道里画一段范围的横线（只有外野线有：落点范围）。"""
        return []

    def over_wall(self) -> bool:
        """球是不是已经越过墙（只有外野线可能）。"""
        return False

    def _tail(self) -> Text:
        """右竖线右边那段留白：外野线画墙，投打行写倒数，传球行写目标垒名。"""
        _start, width = wall_span(self.board_width, self.cells)
        return Text(' ' * width)

    def _animated(self, name: str, fallback: float) -> float:
        """动画里此刻的值；没有动画状态（还没滑起来）就用服务端给的位置。"""
        if self.anim is None:
            return fallback
        return self.anim.values.get(name, fallback)

    # ── 共用 ──

    def column(self, cell: float, width: int = 1) -> int:
        """格位 → 列号：按格心落位，夹在轨道里。"""
        column = int((cell - 1) * self.slot + self.slot / 2)
        return max(0, min(self.slot * self.cells - width, column))

    def render(self) -> Text:
        columns: list[tuple[str, str]] = [(' ', style.DIM)] * (
            self.slot * self.cells)
        marks = self.marks()
        # 标记（球/人/落点圈）两侧各留一格呼吸位：插值滑动时球会落在两个格点之间，
        # 不这么让位就会出现「球贴着点」的相切（用户 2026-10-17 报的问题）
        breathing: set[int] = set()
        for mark in marks:
            width = max(1, cell_width(mark.glyph))
            at = self.column(mark.cell, width)
            breathing.update(range(at - 1, at + width + 1))
        for index in range(1, self.cells + 1):
            column = self.column(index)
            if column not in breathing:      # 离标记太近的点让位，不许贴上去
                columns[column] = ('·', style.DIM)
        for column in self.guides():
            if column not in breathing:      # 线和格点一样，离球太近就让位
                columns[column] = (GUIDE_GLYPH, style.DIM)
        for span in self.spans():            # 范围的横线盖在格点上，标记再盖在它上面
            first, last = self.column(span.low), self.column(span.high)
            for column in range(first, last + 1):
                columns[column] = (SPAN_GLYPH, span.style)
            columns[first] = (SPAN_CAPS[0], span.style)
            columns[last] = (SPAN_CAPS[1], span.style)
        for mark in marks:
            width = max(1, cell_width(mark.glyph))
            at = self.column(mark.cell, width)
            for offset in range(width):     # 中文占两格：占满，别把右边的格点顶出去
                columns[at + offset] = (mark.glyph if offset == 0 else '',
                                        mark.style)
        head = self.head()
        line = Text(' ' * SQUARE_INDENT + self.label, style=style.DIM)
        # 前缀后面固定「符号 + 一格空隙」：有结果符号就画，没有也留白，三行的竖线才对得齐
        line.append(head.glyph if head else ' ',
                    style=head.style if head else style.DIM)
        line.append(' ' * _HEAD_GAP)
        line.append(_BAR_GLYPH, style=style.DIM)          # 左竖线（三行同列）
        for glyph, glyph_style in columns:
            line.append(glyph, style=glyph_style)
        line.append(_BAR_GLYPH, style=style.DIM)          # 右竖线（三行同列）
        line.append_text(self._tail())
        return line


class PitchTrack(ProgressTrack):
    """投打行：前缀后面是本垒结果符号，12 格是球路，投手站在右竖线外面。

    结果符号保持到下一球开投（`last_ball`）：空心圆＝还没结果、叉＝挥空、
    ↗＝高飞/全垒打、→＝平飞、↘＝滚地。打者一按下击球，本垒处立刻亮一个实心点
    （挥棒是公开动作，双方都看得到），结果揭晓时换成结果符号。
    投手一直站在右竖线外面（2026-10-21 用户要求：一直显示、并且站在线外），和左边的本垒结果符号对称：
    竖线外隔一格；球从第 12 格起飞。右竖线右边的倒数（3→2→1）贴棋盘右边缘（用户 2026-10-15 定）。
    """

    label = _ROW_LABELS['pitch']

    def head(self) -> TrackMark:
        board = self.board
        if board.delivery and board.delivery.swung and not board.last_ball:
            return TrackMark(0.0, NF_ONLINE, style.HIT)
        return TrackMark(0.0, home_mark(board.last_ball),
                         style.HIT if board.last_ball not in ('', 'whiff')
                         else style.DIM)

    def guides(self) -> list[int]:
        """击球时机三档（提前 / 正常 / 延后）的两条分界线：球越过线的那一刻就换档。

        线直接落在分界位置上（顶替那里的格点），所以球压在线上的瞬间正好是换档的瞬间。
        """
        span = self.cells - 1
        return [self.column(1 + span * (1 - cut))
                for cut in self.board.timing_cuts]

    def marks(self) -> list[TrackMark]:
        delivery = self.board.delivery
        if delivery is None:
            return []
        if delivery.stage == STAGE_SWING:
            return [TrackMark(1.0, NF_ONLINE, style.BALL)]
        frame = max(0.0, min(float(delivery.frames),
                             self._animated('delivery', delivery.frame)))
        span = self.cells - 1
        return [TrackMark(1 + span * (1 - frame / delivery.frames),
                          NF_ONLINE, style.BALL)]

    def _tail(self) -> Text:
        """右竖线外：投手（隔一格）+ 贴右边缘的倒数。"""
        _start, width = wall_span(self.board_width, self.cells)
        columns = [(' ', style.DIM)] * width
        columns[_HEAD_GAP] = (NF_USER, style.FIELDER)
        left = str(self.board.countdown) if self.board.countdown > 0 else ''
        if left:
            columns[width - cell_width(left)] = (left, style.READY)
        text = Text()
        for glyph, glyph_style in columns:
            text.append(glyph, style=glyph_style)
        return text


class FieldTrack(ProgressTrack):
    """外野线：球落地、野手追球、落点范围都画在这 12 格上，右端是本垒打墙。

    落点范围一开始是一段宽横线（含真落点，但不在正中），球飞近时一路缩短，
    窄到不足一格就收成一个虚线圈，球到的那一拍正好停在真落点上。
    """

    label = _ROW_LABELS['field']

    def _span(self) -> tuple[float, float] | None:
        """此刻画面上的落点范围（没有球在飞就没有）：动画里的值，还没滑起来用服务端给的。"""
        flight = self.board.flight
        if flight is None:
            return None
        return (self._animated('span_low', flight.span[0]),
                self._animated('span_high', flight.span[1]))

    def spans(self) -> list[TrackSpan]:
        span = self._span()
        if span is None or span[1] - span[0] < SPAN_POINT:
            return []
        return [TrackSpan(span[0], span[1], style.MARK)]

    def _fielder_style(self) -> str:
        """野手起跳后：在空中是亮白，落地缓冲是暗灰，其余时候是己方的绿。"""
        if self._animated('air', 0.0) > 0:
            return style.HEAD
        if self._animated('lock', 0.0) > 0:
            return style.DIM
        return style.FIELDER

    def marks(self) -> list[TrackMark]:
        board = self.board
        marks: list[TrackMark] = []
        span = self._span()
        if span is not None and span[1] - span[0] < SPAN_POINT:
            marks.append(TrackMark((span[0] + span[1]) / 2, NF_CIRCLE_NOTCH,
                                   style.MARK))
        fielder = board.fielder
        marks.append(TrackMark(
            float(self._animated('field', fielder.pos if fielder
                                 else board.field_start)),
            NF_USER, self._fielder_style()))
        ball = self._ball()
        if ball and not self.over_wall():
            marks.append(TrackMark(float(ball), NF_ONLINE, style.BALL))
        return marks

    def _ball(self) -> float:
        """球在哪一格（0＝场上没有球）：飞行中用动画里的值，落地后停在落点。"""
        board = self.board
        flight = board.flight
        if board.phase == 'flight' and flight and not flight.done:
            return self._animated('ball', flight.ball)
        if flight:
            return flight.ball
        return board.ground.ball if board.ground else 0

    def over_wall(self) -> bool:
        """全垒打：球已经越到墙外，就不再画在外野线上（由 `_tail` 压在墙上）。"""
        flight = self.board.flight
        return bool(flight and flight.homerun and flight.ball >= self.cells)

    def _tail(self) -> Text:
        _start, width = wall_span(self.board_width, self.cells)
        if self.over_wall():
            text = Text()
            text.append(NF_ONLINE, style=style.BALL)     # 全垒打的球停在墙上
            text.append(_WALL_GLYPH * (width - 1), style=style.WALL)
            return text
        return Text(_WALL_GLYPH * width, style=style.WALL)


class ThrowTrack(ProgressTrack):
    """传球行：整条线＝这次传球的距离——球从最左一格一直走到最右一格。

    传球时第 1 格是守方野手，球从那儿出发；**球走满全程**（最后一拍正好落在最右格），
    所以距离远的传球只是走得慢（拍数多），不是只走半截（用户 2026-10-16 定）。
    右竖线右边的留白里写「垒名 距离」（和墙 / 倒数同一个位置，用户 2026-10-21 定）。
    不传球时这一行只有格点（不摆人、不写垒名）。
    """

    label = _ROW_LABELS['throw']

    def _throw(self):
        return self.board.throw if self.board.phase == 'throw' else None

    def marks(self) -> list[TrackMark]:
        throw = self._throw()
        if throw is None:
            return []
        done = max(0.0, min(float(throw.ticks),
                            self._animated('throw', throw.done)))
        # 整条线＝这次传球：球从最左一格出发，走满全程，最后一拍正好落在最右格
        return [
            TrackMark(1.0, NF_USER, style.FIELDER),
            TrackMark(1 + (self.cells - 1) * done / throw.ticks,
                      NF_ONLINE, style.BALL),
        ]

    def _tail(self) -> Text:
        """右竖线右边写「垒名 距离」（右对齐，贴棋盘右边缘）；放不下就先去掉垒名、再去掉单位。"""
        _start, width = wall_span(self.board_width, self.cells)
        throw = self._throw()
        if throw is None:
            return Text(' ' * width)
        distance = f'{throw.distance:.1f}'
        for text in (f'{throw.base} {distance}米', f'{distance}米', distance):
            if cell_width(text) <= width:
                return Text(' ' * (width - cell_width(text)) + text,
                            style=style.HEAD)
        return Text(' ' * width)


_TRACKS: tuple[type[ProgressTrack], ...] = (PitchTrack, FieldTrack, ThrowTrack)


def track_rows(board: Board, anim: Animator | None,
               board_width: int) -> list[Text]:
    """三条固定行，顺序固定：投打 → 外野 → 传球（用户 2026-10-15 定档）。"""
    return [track(board, anim, board_width).render() for track in _TRACKS]
