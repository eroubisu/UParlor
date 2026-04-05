"""德州扑克渲染器"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer, render_doc

_HEAD = 'bold #e0e0e0'
_DIM = '#808080'
_SCORE = '#b0b0b0'
_SEP = '#454545'
_FOLD = '#505050'
_ACTIVE = 'bold #d0d0d0'
_ALLIN = 'bold #b8b8b8'
_DEALER = '#a0a0a0'
_WIN = 'bold #a0a0a0'

_DOC_COMMANDS = {
    'create', 'rooms', 'start', 'invite', 'kick',
    'fold', 'check', 'call', 'raise', 'allin', 'back', 'help',
}

_SUIT_DISPLAY = {'♠': '#b0b0b0', '♥': '#c07070', '♦': '#c07070', '♣': '#b0b0b0'}


def _card_style(card_str: str) -> str:
    if card_str == '??':
        return '#505050'
    for suit, color in _SUIT_DISPLAY.items():
        if suit in card_str:
            return f'bold {color}'
    return 'bold #b0b0b0'


class HoldemRenderer:
    """德州扑克渲染器"""

    game_type = 'holdem'

    def render_board(self, room_data: dict) -> RenderableType:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return self._render_waiting(room_data)
        if state in ('playing', 'showdown', 'finished'):
            return self._render_game(room_data)
        return self._render_lobby(room_data)

    def _render_lobby(self, data: dict) -> RenderableType:
        parts = []
        doc = data.get('doc')
        if doc:
            parts.append(render_doc(doc, _DOC_COMMANDS))
        msg = data.get('message')
        if msg:
            t = Text()
            if parts:
                t.append('\n')
            for line in msg.split('\n'):
                t.append(f'  {line}\n', style=_SCORE)
            parts.append(t)
        if not parts:
            return Text('')
        if len(parts) == 1:
            return parts[0]
        combined = Text()
        for p in parts:
            combined.append_text(p) if isinstance(p, Text) else combined.append(str(p))
        return combined

    def _render_waiting(self, data: dict) -> RenderableType:
        text = Text()
        room_id = data.get('room_id', '????')
        host = data.get('host', '???')
        players = data.get('players', [])
        max_p = data.get('max_players', 6)

        text.append('  ♠ 德州扑克\n\n', style=_HEAD)
        text.append(f'  房间 #{room_id}  房主: {host}\n', style=_SCORE)
        count = len(players) if isinstance(players, list) else 0
        text.append(f'  等待中 ({count}/{max_p})\n\n', style=_DIM)

        for p in players:
            if isinstance(p, str):
                text.append(f'  · {p}\n', style='#c0c0c0')
        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)
        return text

    def _render_game(self, data: dict) -> RenderableType:
        text = Text()
        community = data.get('community', [])
        pot = data.get('pot', 0)
        phase = data.get('phase', 'preflop')
        seats = data.get('seats', [])
        winners = data.get('winners', [])
        room_id = data.get('room_id', '')
        state = data.get('room_state', 'playing')

        phase_labels = {
            'preflop': '翻牌前', 'flop': '翻牌',
            'turn': '转牌', 'river': '河牌',
            'showdown': '摊牌',
        }

        text.append('  ♠ 德州扑克', style=_HEAD)
        if room_id:
            text.append(f'  #{room_id}', style=_DIM)
        text.append(f'  {phase_labels.get(phase, phase)}', style=_DIM)
        text.append('\n\n')

        # 公共牌
        text.append('  公共牌: ', style=_HEAD)
        if community:
            for c in community:
                text.append(f'[{c}]', style=_card_style(c))
                text.append(' ')
        else:
            text.append('---', style=_DIM)
        text.append('\n')

        # 底池
        text.append(f'  底池: {pot}\n', style=_SCORE)
        text.append('  ' + '─' * 30 + '\n', style=_SEP)

        # 座位
        for s in seats:
            name = s.get('name', '?')
            chips = s.get('chips', 0)
            cards = s.get('cards', [])
            folded = s.get('folded', False)
            all_in = s.get('all_in', False)
            is_dealer = s.get('is_dealer', False)
            is_current = s.get('is_current', False)
            bet = s.get('bet', 0)

            prefix = '→ ' if is_current else '  '
            text.append(prefix, style=_DIM)

            # 庄家标记
            if is_dealer:
                text.append('D ', style=_DEALER)

            # 名字
            if folded:
                text.append(name, style=_FOLD)
                text.append(' (弃)', style=_FOLD)
            elif all_in:
                text.append(name, style=_ALLIN)
                text.append(' ALL-IN', style=_ALLIN)
            elif is_current:
                text.append(name, style=_ACTIVE)
            else:
                text.append(name, style=_SCORE)

            # 筹码
            text.append(f'  ${chips}', style=_DIM)
            if bet > 0:
                text.append(f'  (下注{bet})', style=_DIM)

            # 手牌
            text.append('  ')
            for c in cards:
                text.append(f'[{c}]', style=_card_style(c))
                text.append(' ')

            text.append('\n')

        # 赢家
        if winners:
            text.append('\n')
            for w in winners:
                text.append(
                    f'  ★ {w["name"]} 赢得 {w["amount"]}'
                    f' — {w["hand_name"]}\n',
                    style=_WIN)

        # 当前操作者
        current = data.get('current_player')
        if current and state == 'playing':
            to_call = data.get('to_call', 0)
            can_check = data.get('can_check', False)
            if can_check:
                text.append(f'\n  轮到 {current} — check/raise/fold\n',
                            style='bold #b8b8b8')
            else:
                text.append(f'\n  轮到 {current} — call({to_call})/raise/fold\n',
                            style='bold #b8b8b8')

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)

        return text


register_renderer(HoldemRenderer())
