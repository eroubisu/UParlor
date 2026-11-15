"""棋盘下方的操作区画面：一级表单（SelectList）或按钮盘（╭─╮），二级菜单带标题与横杠。"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from ...config import (
    COLOR_ACCENT, COLOR_FG_PRIMARY, COLOR_FG_TERTIARY, ICON_INDENT,
)
from ...protocol.renderer import render_button_boxes
from ...window_engine import Option, SelectList
from . import style
from .controls import MODE_ACT, MODE_IDLE, Controls

_RULE_GLYPH = '─'           # 标题下面那根横杠（和 app 里其它面板的标题线一致）


def render_controls(controls: Controls | None,
                    board_width: int) -> RenderableType | None:
    """第一行是子菜单标题（一级主盘留空），下面是按钮盘或表单菜单。"""
    if controls is None:
        return None
    if not controls.items:
        return Text(controls.title, style=style.HEAD) if controls.title else None
    body = (_pad(controls, board_width) if controls.is_pad
            else _form(controls, board_width))
    if not controls.title:
        return body
    # 标题独占一行，下面一根横杠——和 app 里其它面板的标题线一个样子
    rule = Text(_RULE_GLYPH * board_width, style=style.DIM)
    return Group(Text(controls.title, style=style.HEAD), rule, body)


def _form(controls: Controls, board_width: int) -> RenderableType:
    """一列表单：每行「标签 + 当前取值」，光标那一行高亮。

    菜单本身用引擎自带的 `SelectList`，前缀与配色跟房间菜单、UNO 完全同一套参数。
    """
    selection = SelectList(
        (Option(str(index), item.label, description=item.desc)
         for index, item in enumerate(controls.items)),
        'baseball-menu',
    )
    if controls.mode != MODE_IDLE:
        selection.select(str(controls.cursor))
    selected = (f'bold {COLOR_FG_PRIMARY}' if controls.mode == MODE_ACT
                else style.DIM)
    return Text.from_markup(selection.render(
        board_width,
        idle_prefix=ICON_INDENT,
        selected_style=selected,
        idle_style=COLOR_FG_TERTIARY,
    ))


def _pad(controls: Controls, board_width: int) -> RenderableType:
    """按钮盘：每行一组 ╭─╮ 按钮，光标那个高亮。"""
    rows: dict[int, list[tuple[int, str]]] = {}
    for index, item in enumerate(controls.items):
        rows.setdefault(item.row, []).append((index, item.label))
    text = Text()
    for row in sorted(rows):
        entries = []
        for index, label in rows[row]:
            if controls.mode != MODE_IDLE and index == controls.cursor:
                if controls.mode == MODE_ACT:
                    entries.append((label, f'bold {COLOR_FG_PRIMARY}',
                                    f'bold {style.CURSOR}'))
                else:                       # 预告：光标画得淡一点，表示还按不动
                    entries.append((label, style.DIM, style.DIM))
            else:
                entries.append((label, COLOR_FG_TERTIARY, COLOR_ACCENT))
        if text.plain:
            text.append('\n')
        render_button_boxes(text, entries, max_width=board_width)
    return text
