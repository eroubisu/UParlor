"""UNO 渲染器 — ASCII art 彩色牌面"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import (
    GameStatusContent, make_status_table, register_renderer,
)
from ...config import (
    NF_ARROW_D, NF_ARROW_U, NF_BAN, NF_EXCHANGE, NF_MOON, NF_OFFLINE,
    NF_ONLINE, NF_REPEAT, NF_CARDS, NF_STAR, NF_SUN, NF_WARNING,
)
from ...window_engine.text import cell_width, fit_cells

# ── 样式常量 ──

_HEAD = 'bold #e0e0e0'
_DIM = '#808080'
_SCORE = '#b0b0b0'
_ACTIVE = 'bold #d0d0d0'
_STATUS_BASE_HEIGHT = 7

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

_SIDE_LABEL = {'light': f'Light {NF_SUN}', 'dark': f'Dark {NF_MOON}'}
_DIR_LABEL = {
    1: (f'{NF_ARROW_D * 3} 顺序 {NF_ARROW_D * 3}', 'bold #50b070'),
    -1: (f'{NF_ARROW_U * 3} 逆序 {NF_ARROW_U * 3}', 'bold #e06060')
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
    'skip': NF_BAN, 'skip_all': NF_BAN * 2,
    'reverse': NF_EXCHANGE, 'flip': NF_REPEAT,
    'wild': 'W', 'wild_draw2': 'W2', 'wild_draw_color': 'WC',
}


def _card_text(card: dict) -> str:
    """返回牌面短文本（仅值，不含颜色名）"""
    value = card.get('value', '')
    if value:
        return _VALUE_LABELS.get(value, value)
    return card.get('label', '??')


_CARD_W = 3  # 所有卡牌统一内宽（显示列数），含边框共 5 列
_CARD_ROW_HEIGHT = 4


# 边框颜色（不可打→可打→聚焦/选中，灰度递增更明显）
_BORDER_UNPLAYABLE = '#383838'
_BORDER_PLAYABLE = '#a0a0a0'
_BORDER_CURSOR = '#ffffff'


def _render_top_card(text: Text, top: dict, chosen_color: str | None) -> None:
    """渲染弃牌堆顶牌"""
    display_color = chosen_color or top.get('color', 'wild')
    hex_c = _COLOR_MAP.get(display_color, '#c0c0c0')
    label = _card_text(top)
    padded = fit_cells(label, _CARD_W)
    pad = '            '  # 12 列对齐 '  要求跟牌: '
    bg = f'bold #000000 on {hex_c}'
    # 顶边
    text.append('  要求跟牌: ', style=_DIM)
    text.append('╭' + '─' * _CARD_W + '╮', style=_BORDER_PLAYABLE)
    if chosen_color:
        text.append('  指定 ', style=_DIM)
        hex_cc = _COLOR_MAP.get(chosen_color, '#c0c0c0')
        text.append('██', style=f'bold {hex_cc}')
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
        text.append(fit_cells(label, _CARD_W, "center"), style=bg)
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


def _render_game_board(data: dict) -> Text:
    board = Text()
    top_card = data.get('top_card')
    if top_card:
        _render_top_card(board, top_card, data.get('chosen_color'))
        board.append('\n')

    if data.get('room_state', 'playing') == 'finished':
        winner = data.get('winner', '')
        board.append('\n')
        if winner:
            board.append(f'  {NF_STAR} {winner} 获胜！\n', style=_HEAD)
        for player, points in data.get('scores', {}).items():
            if player != winner:
                board.append(f'    {player}: {points}分\n', style=_DIM)

    message = data.get('message')
    if message:
        board.append(f'\n  {message}\n', style=_SCORE)
    return board


def _cards_per_row(board_width: int) -> int:
    card_total = _CARD_W + 2
    card_gap = 1
    return max(
        1,
        (board_width - 2 + card_gap) // (card_total + card_gap),
    )


def _render_game_hand(
    controls: Text,
    cards: list[dict],
    playable: list[int],
    interaction: dict | None,
    cards_per_row: int,
) -> int:
    if not cards:
        return -1
    active = bool(interaction and interaction.get('active', True))
    hand_cursor = interaction.get('hand_cursor', 0) if active else -1
    selected = interaction.get('selected', -1) if active else -1
    row = interaction.get('row', 0) if active else -1
    show_cursor = active and row == 0
    focus_line = -1
    line_base = 0
    for start in range(0, len(cards), cards_per_row):
        end = min(start + cards_per_row, len(cards))
        focus_index = hand_cursor if show_cursor else selected
        if focus_index >= 0 and start <= focus_index < end:
            focus_line = line_base
        _render_hand_row(
            controls,
            cards[start:end],
            start,
            playable,
            hand_cursor if show_cursor else -1,
            selected,
        )
        line_base += _CARD_ROW_HEIGHT
    return focus_line


def _render_game_buttons(
    controls: Text,
    interaction: dict | None,
    focus_line: int,
) -> int:
    if not interaction or not interaction.get('buttons'):
        return focus_line
    buttons = interaction['buttons']
    button_active = bool(
        interaction.get('active', True)
        and interaction.get('my_turn', False)
        and interaction.get('row', 0) == 1
    )
    if button_active and focus_line < 0:
        focus_line = str(controls).count('\n')
    _render_button_row(
        controls,
        buttons,
        interaction.get('btn_cursor', 0),
        button_active,
        interaction.get('color_mode', False),
        interaction.get('selected', -1) >= 0,
        interaction.get('my_turn', True),
    )
    return focus_line


def _render_game_controls(
    data: dict,
    interaction: dict | None,
    board_width: int,
) -> tuple[RenderableType | None, int]:
    cards = data.get('my_cards', [])
    controls = Text()
    focus_line = _render_game_hand(
        controls,
        cards,
        data.get('playable', []),
        interaction,
        _cards_per_row(board_width),
    )
    focus_line = _render_game_buttons(
        controls, interaction, focus_line,
    )
    has_buttons = bool(interaction and interaction.get('buttons'))
    return (controls if cards or has_buttons else None), focus_line


def _make_status_header(room_data: dict):
    side = room_data.get('side', 'light')
    direction = room_data.get('direction', 1)
    side_label = _SIDE_LABEL.get(side, side)
    direction_label, direction_style = _DIR_LABEL.get(
        direction, ('?', _DIM),
    )
    header = make_status_table()
    header.add_row(
        f'[{_HEAD}]{side_label}[/]  '
        f'[{direction_style}]{direction_label}[/]',
        f'[{_DIM}]牌堆: {room_data.get("deck_remaining", 0)}[/]',
    )
    return header


def _turn_display(room_data: dict, interaction: dict | None) -> str:
    if interaction and interaction.get('my_turn', False):
        return f'[bold #e0c040]{NF_STAR} 你的回合[/]'
    current = room_data.get('current_player', '')
    return f'[{_DIM}]等待 {current}[/]' if current else ''


def _played_colors_display(room_data: dict) -> str:
    colors = (
        ('red', 'yellow', 'green', 'blue')
        if room_data.get('side', 'light') == 'light'
        else ('pink', 'teal', 'purple', 'orange')
    )
    played = set(room_data.get('played_colors', []))
    display = f'[{_DIM}]已出: [/]'
    for color in colors:
        color_hex = _COLOR_MAP.get(color, '#808080')
        style = color_hex if color in played else f'dim {color_hex}'
        block = '██' if color in played else '░░'
        display += f'[{style}]{block}[/]'
    return display


def _status_prompts(room_data: dict) -> list[str]:
    prompts = []
    pending_draw = room_data.get('pending_draw', 0)
    if pending_draw > 0:
        warning = f'[bold #e06060]{NF_WARNING} 摸牌 +{pending_draw}[/]'
        if room_data.get('draw_stacking'):
            warning += '[#e06060]（可叠）[/]'
        prompts.append(warning)
    if draw_until_color := room_data.get('draw_until_color'):
        color_hex = _COLOR_MAP.get(draw_until_color, '#808080')
        prompts.append(
            f'[bold #e06060]{NF_WARNING} 摸至[/] '
            f'[bold {color_hex}]██[/][bold #e06060]色[/]'
        )
    if room_data.get('challengeable'):
        prompts.append(
            f'[bold #e0c040]{NF_WARNING} 可挑战 Wild[/]'
        )
    top_card = room_data.get('top_card')
    if (
        top_card
        and room_data.get('chosen_color') is None
        and top_card.get('value') == 'wild'
    ):
        prompts.append(f'[bold #e0c040]{NF_WARNING} 请选择颜色[/]')
    if room_data.get('draw_play'):
        prompts.append(f'[bold #e0c040]{NF_WARNING} 出牌或跳过[/]')
    return prompts


def _add_status_prompts(status, prompts: list[str]) -> None:
    visible = prompts[:2]
    for prompt in visible:
        status.add_row(prompt, '')
    for _ in range(2 - len(visible)):
        status.add_row('', '')


def _add_status_players(status, room_data: dict) -> None:
    current = room_data.get('current_player', '')
    hand_counts = room_data.get('hand_counts', {})
    for player in room_data.get('players', []):
        count = hand_counts.get(player, 0)
        marker = '>' if player == current else ' '
        left = (
            f'[{_DIM}]{marker}[/] '
            f'[{_ACTIVE if player == current else _SCORE}]{player}[/]'
        )
        right = f'[{_DIM}]{count} 张[/]'
        if count == 1:
            right += '  [bold #e0c040]UNO![/]'
        status.add_row(left, right)


class UnoRenderer:
    """UNO 渲染器"""

    game_type = 'uno'
    icon = NF_CARDS
    controls_height = 7
    glyphs = frozenset({
        NF_ARROW_D, NF_ARROW_U, NF_BAN, NF_EXCHANGE, NF_MOON, NF_OFFLINE,
        NF_ONLINE, NF_REPEAT, NF_CARDS, NF_STAR, NF_SUN, NF_WARNING,
    })
    scroll_hint: int = -1  # 渲染后建议滚动到的行号（-1=不滚动）
    doc_commands = _DOC_COMMANDS

    def render_doc(self, text: str) -> RenderableType:
        return _render_doc_with_cards(text, _DOC_COMMANDS)

    def status_height(self, room_data: dict) -> int:
        return _STATUS_BASE_HEIGHT + len(room_data.get('players', []))

    def render_status(
        self, room_data: dict, interaction: dict | None = None,
    ) -> GameStatusContent:
        if room_data.get('room_state') not in ('playing', 'finished'):
            return GameStatusContent(None)
        status = make_status_table()
        status.add_row(
            _turn_display(room_data, interaction),
            _played_colors_display(room_data),
        )
        _add_status_prompts(status, _status_prompts(room_data))
        _add_status_players(status, room_data)
        return GameStatusContent(status, _make_status_header(room_data))

    def render_board(self, room_data: dict, interaction: dict | None = None,
                     board_width: int = 80, board_height: int = 30) -> dict[str, RenderableType | None]:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return {'board': self._render_waiting(room_data), 'controls': None}
        if state in ('playing', 'finished'):
            return self._render_game(room_data, interaction, board_width)
        return {'board': self._render_lobby(room_data), 'controls': None}

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
        ready = set(data.get('ready') or [])
        bots = set(data.get('bots') or [])

        text.append('  等待中\n\n', style=_HEAD)
        text.append(f'  房间 #{room_id}  房主: {host}\n', style=_SCORE)
        text.append(f'  等待中 ({len(players)}/{max_p})\n\n', style=_DIM)

        for p in players:
            if p == host:
                text.append(f'  {NF_ONLINE} ', style='#d4a017')
                text.append(f'{p}\n', style='#c0c0c0')
            elif p in ready or p in bots:
                text.append(f'  {NF_ONLINE} ', style='#81c784')
                text.append(f'{p}\n', style='#c0c0c0')
            else:
                text.append(f'  {NF_OFFLINE} ', style='#ffffff')
                text.append(f'{p}\n', style='#c0c0c0')
        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)
        return text

    def _render_game(self, data: dict, interaction: dict | None = None,
                     board_width: int = 80) -> dict[str, RenderableType | None]:
        controls, focus_line = _render_game_controls(
            data, interaction, board_width,
        )
        self.scroll_hint = focus_line
        return {
            'board': _render_game_board(data),
            'controls': controls,
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
        padded = fit_cells(_card_text(card), W)
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
        w = max(8, cell_width(label) + 2)
        text.append('╭' + '─' * w + '╮', style=b_style)
        text.append(' ')
    text.append('\n  ')

    # 内容行
    for label, style, b_style in btn_styles:
        w = max(8, cell_width(label) + 2)
        padded = fit_cells(label, w, "center")
        text.append('│', style=b_style)
        text.append(padded, style=style)
        text.append('│', style=b_style)
        text.append(' ')
    text.append('\n  ')

    # 底边
    for label, style, b_style in btn_styles:
        w = max(8, cell_width(label) + 2)
        text.append('╰' + '─' * w + '╯', style=b_style)
        text.append(' ')

register_renderer(UnoRenderer())
