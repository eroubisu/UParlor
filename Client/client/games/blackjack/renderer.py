"""21点渲染器 — 扑克牌风格"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer, render_doc

_HEAD = 'bold #e0e0e0'
_DIM = '#808080'
_SCORE = '#b0b0b0'
_SEP = '#454545'
_WIN = 'bold #a0a0a0'
_LOSE = '#606060'
_PUSH = '#909090'
_BJ = 'bold #d0d0d0'

_DOC_COMMANDS = {
    'create', 'rooms', 'start', 'invite', 'kick',
    'hit', 'stand', 'double', 'back', 'help',
}

# 花色符号和颜色
_SUIT_DISPLAY = {'♠': '#b0b0b0', '♥': '#c07070', '♦': '#c07070', '♣': '#b0b0b0'}


def _card_style(card_str: str) -> str:
    """根据牌面字符串返回 Rich 样式"""
    if card_str == '??':
        return '#505050'
    for suit, color in _SUIT_DISPLAY.items():
        if suit in card_str:
            return f'bold {color}'
    return 'bold #b0b0b0'


class BlackjackRenderer:
    """21点渲染器"""

    game_type = 'blackjack'

    def render_board(self, room_data: dict) -> RenderableType:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return self._render_waiting(room_data)
        if state in ('playing', 'dealer', 'finished'):
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

        text.append('  ♠ 21点\n\n', style=_HEAD)
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
        dealer_cards = data.get('dealer_cards', [])
        dealer_value = data.get('dealer_value')
        players_data = data.get('players_data', [])
        state = data.get('room_state', 'playing')
        results = data.get('results', {})
        room_id = data.get('room_id', '')

        text.append('  ♠ 21点', style=_HEAD)
        if room_id:
            text.append(f'  #{room_id}', style=_DIM)
        text.append('\n\n')

        # 庄家
        text.append('  庄家: ', style=_HEAD)
        for c in dealer_cards:
            text.append(f'[{c}]', style=_card_style(c))
            text.append(' ')
        if dealer_value is not None:
            if dealer_value > 21:
                text.append(f' ({dealer_value} 爆了)', style=_LOSE)
            else:
                text.append(f' ({dealer_value})', style=_SCORE)
        text.append('\n')
        text.append('  ' + '─' * 30 + '\n', style=_SEP)

        # 玩家
        for pd in players_data:
            name = pd.get('name', '?')
            cards = pd.get('cards', [])
            value = pd.get('value', 0)
            is_current = pd.get('is_current', False)
            busted = pd.get('busted', False)
            stood = pd.get('stood', False)
            is_bj = pd.get('is_blackjack', False)
            doubled = pd.get('doubled', False)

            # 名字
            prefix = '→ ' if is_current else '  '
            name_style = 'bold #d0d0d0' if is_current else _SCORE
            text.append(prefix, style=_DIM)
            text.append(name, style=name_style)
            if doubled:
                text.append(' [×2]', style=_DIM)
            text.append(': ')

            # 手牌
            for c in cards:
                text.append(f'[{c}]', style=_card_style(c))
                text.append(' ')

            # 点数 & 状态
            if is_bj:
                text.append(f' (BJ!)', style=_BJ)
            elif busted:
                text.append(f' ({value} 爆了)', style=_LOSE)
            elif stood:
                text.append(f' ({value})', style=_SCORE)
            else:
                text.append(f' ({value})', style='bold #d0d0d0')

            # 结算结果
            r = results.get(name)
            if r:
                outcome = r.get('outcome', '')
                payout = r.get('payout', 0)
                labels = {'win': '赢', 'blackjack': 'BJ!', 'push': '平', 'lose': '输'}
                sign = '+' if payout >= 0 else ''
                o_style = {
                    'win': _WIN, 'blackjack': _BJ,
                    'push': _PUSH, 'lose': _LOSE,
                }.get(outcome, _DIM)
                text.append(f'  {labels.get(outcome, "")} {sign}{payout}',
                            style=o_style)

            text.append('\n')

        # 当前操作者提示
        current = data.get('current_player')
        if current and state == 'playing':
            text.append(f'\n  轮到 {current} — hit/stand/double\n',
                        style='bold #b8b8b8')

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)

        return text


register_renderer(BlackjackRenderer())
