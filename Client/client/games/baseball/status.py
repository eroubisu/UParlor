"""右栏状态页：局面 → 比分 → 侦察 → 属性，按重要度排序（聚焦右栏后 ← → 翻页）。

**只放棋盘上没有的**（用户 2026-10-16 定）：这一拍在干什么、交牌灯、球位、落点、野手、
跑者进度、传球目标全在棋盘上（方框实时槽 + 三条固定行），右栏不再重复。
每页都是"槽位固定 + 内容填空"：行位固定，没有内容也不许把别的行挤上来。
"""

from __future__ import annotations

from rich.console import RenderableType

from ...config import NF_CARET_D, NF_CARET_U, NF_LEVEL, NF_OFFLINE, NF_ONLINE
from ...protocol.renderer import GameStatusContent, StatusRows, make_status_table
from ...window_engine.text import cell_width, fit_cells
from .view import Board

# 固定高度：够最高的那一页（侦察 6 行）+ 上下边框，多出来的行还给下面的聊天区
# （用户 2026-10-16 定：右栏只留棋盘没有的，面板不随局面长高变矮）
STATUS_HEIGHT = 8
_HISTORY_SLOTS = 3          # 侦察板显示最近几球（每球两行）
_OUT_DOTS = 3               # 出局名额
_ROW_COLS = 34              # 右栏一行能放多少列（40 宽 − 边框 − 左右各缩进 2）


def _dots(filled: int, total: int) -> str:
    """用圆点表示名额：实心＝用掉的名额，空心＝剩余。"""
    return ' '.join([NF_ONLINE] * filled + [NF_OFFLINE] * (total - filled))


def _situation_page(board: Board) -> StatusRows:
    """局面页：永远这 5 行，按美职棒的记分牌写法，两列各贴一边。"""
    table = make_status_table()
    # 局数：当前局/总局数，上半＝▲、下半＝▼；球数：坏球-好球（如 3-2 是满球数）；客队在前
    table.add_row('局数', f'{board.innings}/{board.total_innings} '
                  f'{NF_CARET_U if board.half == "top" else NF_CARET_D}')
    table.add_row('比分', f'{board.away} {board.score[board.away]} - '
                  f'{board.score[board.home]} {board.home}')
    table.add_row('出局', _dots(board.outs, _OUT_DOTS))
    table.add_row('球数', f'{board.balls}-{board.strikes}')
    table.add_row('体力', f'{NF_LEVEL} {board.stamina}')
    return table


def _line_score_page(board: Board) -> StatusRows:
    """比分页：逐局得分，客队在前；还没打的半局写 `-`，不必再打的下半局写 `X`。"""
    def cell(value: int | None) -> str:
        if value is None:
            return 'X' if board.finished else '-'
        return str(value)

    def cells(runs: tuple[int | None, ...]) -> str:
        return ''.join(f'{cell(value):>2}' for value in runs)

    table = make_status_table()
    inning_numbers = ''.join(f'{number:>2}'
                             for number in range(1, board.total_innings + 1))
    table.add_row('局', f'{inning_numbers} 合计')
    for side, name in (('away', board.away), ('home', board.home)):
        value = f'{cells(board.line_score[side])} {board.score[name]:>4}'
        room = _ROW_COLS - cell_width(value) - 1
        label = (name if cell_width(name) <= room
                 else fit_cells(name, room - 1, crop=True) + '…')
        table.add_row(label, value)
    return table


def _history_page(board: Board) -> StatusRows:
    """侦察页：**固定 3 槽 × 2 行**：守方投了什么、攻方怎么打、结果如何。

    槽位永远在（第 1~3 个最近球），还没打到的槽留空占位——
    新球进槽时老球的位置不挪、行数也不变（用户 2026-10-16 定）。
    第一行不写名字（写了就放不下：球种 + 区域 + 力度已经占去 26 列），
    第二行写这一球的打者——两个人里剩下的那个就是投手。
    """
    table = make_status_table()
    recent = board.history[-_HISTORY_SLOTS:]
    first = len(board.history) - len(recent) + 1
    for _ in range(_HISTORY_SLOTS - len(recent)):      # 还没有球的槽：留空占位
        table.add_row('', '')
        table.add_row('', '')
    for index, record in enumerate(recent):
        table.add_row(f'{first + index} 守',
                      f'{record.type_label} {record.band_label} '
                      f'{record.effort_label}')
        table.add_row(f'  攻 {record.batter}',
                      f'{record.batter_swing_label} → {record.result_label}')
    return table


def _attributes_page(board: Board) -> StatusRows:
    """属性页：我的能力（球探报告），固定四行。"""
    pitcher, batter, fielder = (board.attributes.pitcher,
                                board.attributes.batter,
                                board.attributes.fielder)
    table = make_status_table()
    table.add_row('我方投手', f'控球 {pitcher["control"]}  '
                  f'球速 {pitcher["velocity"]}  变化 {pitcher["breaking"]}')
    table.add_row('我方打者', f'力量 {batter["power"]}  '
                  f'接触 {batter["contact"]}  选球 {batter["eye"]}')
    table.add_row('我方野手', f'速度 {fielder["speed"]}  '
                  f'守备 {fielder["fielding"]}  臂力 {fielder["arm"]}')
    table.add_row('布阵', board.shift_label)
    return table


def status_pages(board: Board) -> tuple[tuple[str, RenderableType], ...]:
    return (('局面', _situation_page(board)),
            ('比分', _line_score_page(board)),
            ('侦察', _history_page(board)),
            ('属性', _attributes_page(board)))


def status_content(board: Board) -> GameStatusContent:
    return GameStatusContent(None, pages=status_pages(board))
