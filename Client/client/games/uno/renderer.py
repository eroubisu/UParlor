"""UNO Flip 渲染器 — ASCII art 彩色牌面"""

from __future__ import annotations

import unicodedata
_east_asian_width = unicodedata.east_asian_width

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer

# ── 样式常量 ──

_HEAD = 'bold #e0e0e0'
_DIM = '#808080'
_SCORE = '#b0b0b0'
_ACTIVE = 'bold #d0d0d0'
_IDX = '#606060'

# 牌面颜色（游戏内容可使用彩色）
_COLOR_MAP = {
    'red': '#e06060',
    'yellow': '#e0c040',
    'green': '#50b070',
    'blue': '#5080d0',
    'pink': '#d070a0',
    'teal': '#40b0b0',
    'purple': '#9070c0',
    'orange': '#d08040',
    'wild': '#c0c0c0',
}

_SIDE_LABEL = {'light': 'Light ☀', 'dark': 'Dark ☾'}
_DIR_LABEL = {
    1: ('↓↓↓ 顺序 ↓↓↓', 'bold #50b070'),
    -1: ('↑↑↑ 逆序 ↑↑↑', 'bold #e06060')
}

_DOC_COMMANDS = {
    'create', 'rooms', 'start', 'invite', 'kick', 'bot',
    'play', 'draw', 'uno', 'pass', 'challenge', 'back', 'help',
}


# 卡牌值标签（客户端只显示值，不显示颜色名）
_VALUE_LABELS = {
    '0': '0', '1': '1', '2': '2', '3': '3', '4': '4',
    '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
    'draw1': '+1', 'draw5': '+5',
    'skip': '⊘', 'skip_all': '⊘⊘',
    'reverse': '⇄', 'flip': '⟳',
    'wild': 'W', 'wild_draw2': 'W2', 'wild_draw_color': 'WC',
}


def _card_text(card: dict) -> str:
    """返回牌面短文本（仅值，不含颜色名）"""
    value = card.get('value', '')
    if value:
        return _VALUE_LABELS.get(value, value)
    return card.get('label', '??')


_CARD_W = 3  # 所有卡牌统一内宽（显示列数），含边框共 5 列


def _cell_len(s: str) -> int:
    """计算字符串显示宽度（CJK 字符占 2 列）"""
    return sum(2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1 for c in s)


def _pad_center(s: str, target: int) -> str:
    """将字符串居中填充到 target 显示宽度"""
    w = _cell_len(s)
    if w >= target:
        return s
    left = (target - w) // 2
    right = target - w - left
    return ' ' * left + s + ' ' * right


def _pad_left(s: str, target: int) -> str:
    """将字符串左对齐填充到 target 显示宽度"""
    w = _cell_len(s)
    return s + ' ' * max(0, target - w)


# 边框颜色（不可打→可打→聚焦/选中，灰度递增更明显）
_BORDER_UNPLAYABLE = '#383838'
_BORDER_PLAYABLE = '#a0a0a0'
_BORDER_CURSOR = '#ffffff'


def _dim_color(hex_c: str) -> str:
    """将颜色变暗（乘以 0.35）用于不可出的牌背景"""
    c = hex_c.lstrip('#')
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f'#{int(r*0.35):02x}{int(g*0.35):02x}{int(b*0.35):02x}'


def _render_top_card(text: Text, top: dict, chosen_color: str | None) -> None:
    """渲染弃牌堆顶牌"""
    display_color = chosen_color or top.get('color', 'wild')
    hex_c = _COLOR_MAP.get(display_color, '#c0c0c0')
    label = _card_text(top)
    padded = _pad_left(label, _CARD_W)
    pad = '            '  # 12 列对齐 '  要求跟牌: '
    bg = f'bold #000000 on {hex_c}'
    # 顶边
    text.append('  要求跟牌: ', style=_DIM)
    text.append('╭' + '─' * _CARD_W + '╮', style=_BORDER_PLAYABLE)
    if chosen_color:
        text.append('  指定 ', style=_DIM)
        hex_cc = _COLOR_MAP.get(chosen_color, '#c0c0c0')
        text.append('██', style=f'bold on {hex_cc}')
    text.append('\n')
    # 内容行
    text.append(pad)
    text.append('│', style=_BORDER_PLAYABLE)
    text.append(padded, style=bg)
    text.append('│', style=_BORDER_PLAYABLE)
    text.append('\n')
    # 空白行
    text.append(pad)
    text.append('│', style=_BORDER_PLAYABLE)
    text.append(' ' * _CARD_W, style=bg)
    text.append('│', style=_BORDER_PLAYABLE)
    text.append('\n')
    # 底边
    text.append(pad)
    text.append('╰' + '─' * _CARD_W + '╯', style=_BORDER_PLAYABLE)
    text.append('\n')


def _render_card_row(text: Text, line: str) -> None:
    """解析 @cards 指令并渲染一行彩色卡牌。

    格式: @cards color:value color:value ...
    """
    indent = '    '
    border = _BORDER_PLAYABLE
    parts = line.strip().split()[1:]  # skip '@cards'
    cards = []
    for p in parts:
        color, _, value = p.partition(':')
        label = _VALUE_LABELS.get(value, value)
        hex_c = _COLOR_MAP.get(color, '#c0c0c0')
        cards.append((label, hex_c))

    gap = ' '
    # 顶边
    text.append(indent)
    for i, (_, _) in enumerate(cards):
        if i:
            text.append(gap)
        text.append('╭' + '─' * _CARD_W + '╮', style=border)
    text.append('\n')
    # 值行
    text.append(indent)
    for i, (label, hex_c) in enumerate(cards):
        if i:
            text.append(gap)
        bg = f'bold #000000 on {hex_c}'
        text.append('│', style=border)
        text.append(_pad_center(label, _CARD_W), style=bg)
        text.append('│', style=border)
    text.append('\n')
    # 空行
    text.append(indent)
    for i, (_, hex_c) in enumerate(cards):
        if i:
            text.append(gap)
        bg = f'#000000 on {hex_c}'
        text.append('│', style=border)
        text.append(' ' * _CARD_W, style=bg)
        text.append('│', style=border)
    text.append('\n')
    # 底边
    text.append(indent)
    for i, (_, _) in enumerate(cards):
        if i:
            text.append(gap)
        text.append('╰' + '─' * _CARD_W + '╯', style=border)
    text.append('\n')


def _render_doc_with_cards(doc: str, commands: set[str]) -> RenderableType:
    """渲染帮助文档，支持 @cards 指令绘制彩色卡牌行。"""
    import re
    from ...config import NF_STAR, COLOR_CMD

    result = Text()
    pat = re.compile(
        r'\b(' + '|'.join(re.escape(c) for c in commands) + r')\b')

    for line in doc.split('\n'):
        stripped = line.lstrip()
        if stripped.startswith('@cards '):
            _render_card_row(result, stripped)
        elif stripped.startswith('◆'):
            heading = line.lstrip().replace('◆', NF_STAR, 1)
            result.append(heading + '\n', style='bold #e0e0e0')
        else:
            last = 0
            for m in pat.finditer(line):
                result.append(line[last:m.start()], style='#808080')
                result.append(m.group(), style=f'bold {COLOR_CMD}')
                last = m.end()
            result.append(line[last:] + '\n', style='#808080')

    return result


class UnoRenderer:
    """UNO Flip 渲染器"""

    game_type = 'uno'
    scroll_hint: int = -1  # 渲染后建议滚动到的行号（-1=不滚动）
    doc_commands = _DOC_COMMANDS

    def render_doc(self, text: str) -> RenderableType:
        return _render_doc_with_cards(text, _DOC_COMMANDS)

    def render_board(self, room_data: dict, interaction: dict | None = None,
                     board_width: int = 80, board_height: int = 30) -> dict[str, RenderableType | None]:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return {'info': None, 'board': self._render_waiting(room_data), 'controls': None}
        if state in ('playing', 'finished'):
            return self._render_game(room_data, interaction, board_width)
        return {'info': None, 'board': self._render_lobby(room_data), 'controls': None}

    def _render_lobby(self, data: dict) -> RenderableType:
        doc = data.get('doc')
        if doc:
            return _render_doc_with_cards(doc, _DOC_COMMANDS)
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
        max_p = data.get('max_players', 10)

        text.append('  等待中\n\n', style=_HEAD)
        text.append(f'  房间 #{room_id}  房主: {host}\n', style=_SCORE)
        text.append(f'  等待中 ({len(players)}/{max_p})\n\n', style=_DIM)

        for p in players:
            text.append(f'  · {p}\n', style='#c0c0c0')
        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)
        return text

    def _render_game(self, data: dict, interaction: dict | None = None,
                     board_width: int = 80) -> dict[str, RenderableType | None]:
        players = data.get('players', [])
        side = data.get('side', 'light')
        direction = data.get('direction', 1)
        current = data.get('current_player', '')
        hand_counts = data.get('hand_counts', {})
        top_card = data.get('top_card')
        chosen_color = data.get('chosen_color')
        pending_draw = data.get('pending_draw', 0)
        draw_until_color = data.get('draw_until_color')
        challengeable = data.get('challengeable', False)
        deck_remaining = data.get('deck_remaining', 0)
        my_cards = data.get('my_cards', [])
        playable = data.get('playable', [])
        state = data.get('room_state', 'playing')

        # ── info 区：头信息 + 状态提示 ──
        info = Text()
        _GAP = '  '
        side_label = _SIDE_LABEL.get(side, side)
        dir_text, dir_style = _DIR_LABEL.get(direction, ('?', _DIM))
        _sl_w = sum(2 if _east_asian_width(c) in ('F', 'W') else 1 for c in side_label)
        info.append(f'  {side_label}' + ' ' * max(0, 8 - _sl_w), style=_HEAD)
        info.append(f'{_GAP}{dir_text}', style=dir_style)
        info.append(f'{_GAP}牌堆:{deck_remaining:<3d}', style=_DIM)
        my_turn = interaction.get('my_turn', False) if interaction else False
        if my_turn:
            turn_text = '★ 你的回合'
            turn_style = 'bold #e0c040'
        elif current:
            turn_text = f'等待 {current}'
            turn_style = _DIM
        else:
            turn_text = ''
            turn_style = _DIM
        _tw = sum(2 if _east_asian_width(c) in ('F', 'W') else 1 for c in turn_text)
        turn_text += ' ' * max(0, 14 - _tw)
        info.append(f'{_GAP}{turn_text}', style=turn_style)
        all_colors = ('red', 'yellow', 'green', 'blue') if side == 'light' else ('pink', 'teal', 'purple', 'orange')
        played_set = set(data.get('played_colors', []))
        info.append(f'{_GAP}已出:', style=_DIM)
        for c in all_colors:
            c_hex = _COLOR_MAP.get(c, '#808080')
            if c in played_set:
                info.append('██', style=c_hex)
            else:
                info.append('░░', style=f'dim {c_hex}')
        info.append('\n')
        if pending_draw > 0:
            info.append(f'  ⚠ 累积摸牌 {pending_draw} 张', style='bold #e06060')
            if data.get('draw_stacking'):
                info.append('（可叠加同类 Draw 牌）', style='#e06060')
            info.append('\n')
        if draw_until_color:
            duc_hex = _COLOR_MAP.get(draw_until_color, '#808080')
            info.append('  ⚠ 持续摸牌直到摸到 ', style='bold #e06060')
            info.append('██', style=f'bold on {duc_hex}')
            info.append('\n')
        if challengeable:
            info.append('  ⚠ 上家打出 Wild，可以挑战！', style='bold #e0c040')
            info.append('\n')
        if top_card and chosen_color is None and top_card.get('value') == 'wild':
            info.append('  ⚠ 首张为 Wild，请选择颜色', style='bold #e0c040')
            info.append('\n')
        if data.get('draw_play'):
            info.append('  ⚠ 摸到的牌可以打出，选择出牌或跳过', style='bold #e0c040')
            info.append('\n')

        # ── board 区：弃牌堆 + 玩家列表 + 结算 ──
        board = Text()
        if top_card:
            _render_top_card(board, top_card, chosen_color)
            board.append('\n')

        max_name_len = max([_cell_len(p) for p in players] + [0])
        for p in players:
            count = hand_counts.get(p, 0)
            prefix = '> ' if p == current else '  '
            board.append(prefix, style=_DIM)
            style = _ACTIVE if p == current else _SCORE
            board.append(_pad_left(p, max_name_len), style=style)
            count = hand_counts.get(p, 0)
            board.append(f'  [{count}张]', style=_DIM)
            if count == 1:
                board.append('  UNO!', style='bold #e0c040')
            board.append('\n')

        if state == 'finished':
            winner = data.get('winner', '')
            scores = data.get('scores', {})
            board.append('\n')
            if winner:
                board.append(f'  ★ {winner} 获胜！\n', style=_HEAD)
            for p, pts in scores.items():
                if p == winner:
                    continue
                board.append(f'    {p}: {pts}分\n', style=_DIM)

        msg = data.get('message')
        if msg:
            board.append(f'\n  {msg}\n', style=_SCORE)

        # ── controls 区：手牌 + 按钮 ──
        controls = Text()
        _focus_line = -1

        card_total = _CARD_W + 2
        card_gap = 1
        cards_per_row = max(1, (board_width - 2 + card_gap) // (card_total + card_gap))

        if my_cards:
            active = interaction is not None
            hand_cursor = interaction.get('hand_cursor', 0) if active else -1
            selected = interaction.get('selected', -1) if active else -1
            row = interaction.get('row', 0) if active else -1
            show_cursor = active and row == 0
            _CARD_ROW_H = 4

            _line_base = 0
            for start in range(0, len(my_cards), cards_per_row):
                end = min(start + cards_per_row, len(my_cards))
                row_cards = my_cards[start:end]
                focus_idx = hand_cursor if show_cursor else selected
                if focus_idx >= 0 and start <= focus_idx < end:
                    _focus_line = _line_base
                _render_hand_row(controls, row_cards, start, playable,
                                 hand_cursor if show_cursor else -1, selected)
                _line_base += _CARD_ROW_H

        if interaction and interaction.get('buttons'):
            buttons = interaction['buttons']
            btn_cursor = interaction.get('btn_cursor', 0)
            btn_active = interaction.get('row', 0) == 1
            color_mode = interaction.get('color_mode', False)
            has_selection = interaction.get('selected', -1) >= 0
            my_turn_btn = interaction.get('my_turn', True)
            if btn_active and _focus_line < 0:
                _focus_line = str(controls).count('\n')
            _render_button_row(controls, buttons, btn_cursor, btn_active,
                               color_mode, has_selection, my_turn_btn)

        self.scroll_hint = _focus_line
        has_controls = bool(my_cards) or (interaction and interaction.get('buttons'))
        return {
            'info': info,
            'board': board,
            'controls': controls if has_controls else None,
        }


def _render_hand_row(text: Text, cards: list[dict],
                     start_idx: int, playable: list[int],
                     cursor: int, selected: int) -> None:
    """渲染一行等宽卡牌（边框灰色，内容背景色）"""
    if not cards:
        return
    playable_set = set(playable)
    W = _CARD_W

    def _styles(card: dict, idx: int) -> tuple[str, str]:
        """返回 (border_style, content_style)"""
        hex_c = _COLOR_MAP.get(card.get('color', 'wild'), '#c0c0c0')
        is_cursor = idx == cursor
        is_selected = idx == selected
        is_playable = idx in playable_set

        if is_cursor or is_selected:
            return f'bold {_BORDER_CURSOR}', f'bold #000000 on {hex_c}'
        if is_playable:
            return _BORDER_PLAYABLE, f'#000000 on {hex_c}'
        # 不可出的牌：暗色边框 + 同一背景色（仅靠边框区分）
        return _BORDER_UNPLAYABLE, f'#303030 on {hex_c}'

    # 顶边
    text.append('  ')
    for i, card in enumerate(cards):
        b_style, _ = _styles(card, start_idx + i)
        text.append('╭' + '─' * W + '╮', style=b_style)
        text.append(' ')
    text.append('\n')

    # 内容行 1: 卡牌文本（左上角）
    text.append('  ')
    for i, card in enumerate(cards):
        b_style, c_style = _styles(card, start_idx + i)
        l, r = '│', '│'
        padded = _pad_left(_card_text(card), W)
        text.append(l, style=b_style)
        text.append(padded, style=c_style)
        text.append(r, style=b_style)
        text.append(' ')
    text.append('\n')

    # 内容行 2: 空白
    text.append('  ')
    for i, card in enumerate(cards):
        b_style, c_style = _styles(card, start_idx + i)
        l, r = '│', '│'
        text.append(l, style=b_style)
        text.append(' ' * W, style=c_style)
        text.append(r, style=b_style)
        text.append(' ')
    text.append('\n')

    # 底边
    text.append('  ')
    for i, card in enumerate(cards):
        b_style, _ = _styles(card, start_idx + i)
        text.append('╰' + '─' * W + '╯', style=b_style)
        text.append(' ')
    text.append('\n')


def _render_button_row(text: Text, buttons: list[dict], cursor: int,
                       active: bool, color_mode: bool,
                       has_selection: bool, my_turn: bool = True) -> None:
    """渲染操作按钮行（出牌按钮在无选中时置灰，非回合全部置灰）"""
    if not buttons:
        return
    btn_styles = []

    for i, btn in enumerate(buttons):
        label = btn.get('label', '?')
        cmd = btn.get('command', '')
        is_cursor = active and i == cursor

        if not my_turn:
            style = '#505050'
            b_style = f'bold {_BORDER_PLAYABLE}' if is_cursor else '#505050'
        elif color_mode:
            desc = btn.get('desc', '')
            hex_c = _COLOR_MAP.get(desc, '#c0c0c0')
            style = f'bold {hex_c}'
            b_style = f'bold {_BORDER_CURSOR}' if is_cursor else style
        elif cmd == '_play_selected' and not has_selection:
            # 出牌按钮置灰（未选牌）
            style = '#505050'
            b_style = f'bold {_BORDER_CURSOR}' if is_cursor else style
        else:
            style = 'bold #ffffff'
            b_style = f'bold {_BORDER_CURSOR}' if is_cursor else 'bold #a0a0a0'

        btn_styles.append((label, style, b_style))

    text.append('  ')
    # 顶边
    for label, style, b_style in btn_styles:
        w = max(8, _cell_len(label) + 2)
        text.append('╭' + '─' * w + '╮', style=b_style)
        text.append(' ')
    text.append('\n  ')

    # 内容行
    for label, style, b_style in btn_styles:
        w = max(8, _cell_len(label) + 2)
        padded = _pad_center(label, w)
        text.append('│', style=b_style)
        text.append(padded, style=style)
        text.append('│', style=b_style)
        text.append(' ')
    text.append('\n  ')

    # 底边
    for label, style, b_style in btn_styles:
        w = max(8, _cell_len(label) + 2)
        text.append('╰' + '─' * w + '╯', style=b_style)
        text.append(' ')
    text.append('\n')

register_renderer(UnoRenderer())
