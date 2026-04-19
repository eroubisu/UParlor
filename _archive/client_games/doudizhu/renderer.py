"""斗地主渲染器"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer, render_doc

_HEAD = 'bold #e0e0e0'
_DIM = '#808080'
_SCORE = '#b0b0b0'
_SEP = '#454545'
_ACTIVE = 'bold #d0d0d0'
_DIZHU = 'bold #c0c0c0'
_FARMER = '#a0a0a0'
_WIN = 'bold #a0a0a0'
_IDX = '#606060'
_BG_A = '#707070'
_BG_NEW = '#909090'

_DOC_COMMANDS = {
    'create', 'rooms', 'start', 'invite', 'kick',
    'bid', 'play', 'pass', 'back', 'help',
}

_SUIT_COLORS = {
    '♠': '#c0c0c0',
    '♥': '#e06868',
    '♦': '#e0a050',
    '♣': '#60b060',
}


def _card_style(card_str: str) -> str:
    if card_str.startswith('B') and '☆' in card_str:
        return 'bold #e8c840'
    if card_str.startswith('S') and '☆' in card_str:
        return 'bold #50b8c8'
    for suit, color in _SUIT_COLORS.items():
        if suit in card_str:
            return f'bold {color}'
    return 'bold #b0b0b0'


def _strip_suit(card_str: str) -> str:
    for s in ('♠', '♥', '♦', '♣'):
        card_str = card_str.replace(s, '')
    return card_str


def _render_hand(text: Text, my_cards: list[str]) -> None:
    """纵向双列渲染手牌"""
    n = len(my_cards)
    if not n:
        return
    text.append('  你的手牌:\n', style=_HEAD)
    mid = (n + 1) // 2
    for row in range(mid):
        card = my_cards[row]
        text.append(f'  {row:>2}  ', style=_IDX)
        text.append(card, style=_card_style(card))
        cw = 3 if card.startswith('10') else 2
        text.append(' ' * (4 - cw))
        j = row + mid
        if j < n:
            text.append('    ')
            text.append(f'{j:>2}  ', style=_IDX)
            text.append(my_cards[j], style=_card_style(my_cards[j]))
        text.append('\n')


class DoudizhuRenderer:
    """斗地主渲染器"""

    game_type = 'doudizhu'

    def render_board(self, room_data: dict) -> RenderableType:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return self._render_waiting(room_data)
        if state == 'bidding':
            return self._render_bidding(room_data)
        if state in ('playing', 'finished'):
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
        max_p = data.get('max_players', 3)

        text.append('  等待中\n\n', style=_HEAD)
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

    def _render_bidding(self, data: dict) -> RenderableType:
        text = Text()
        players = data.get('players', [])
        bids = data.get('bids', {})
        current = data.get('current_player', '')
        my_cards = data.get('my_cards', [])

        text.append('  叫分阶段\n\n', style=_HEAD)

        for p in players:
            bid = bids.get(p)
            prefix = '→ ' if p == current else '  '
            text.append(prefix, style=_DIM)
            style = _ACTIVE if p == current else _SCORE
            text.append(p, style=style)
            if bid is not None:
                text.append(f'  {bid}分' if bid > 0 else '  不叫', style=_DIM)
            else:
                text.append('  …', style=_DIM)
            text.append('\n')

        # 显示自己的手牌
        if my_cards:
            text.append('\n  ' + '─' * 30 + '\n', style=_SEP)
            _render_hand(text, my_cards)

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)
        return text

    def _render_game(self, data: dict) -> RenderableType:
        text = Text()
        players = data.get('players', [])
        dizhu = data.get('dizhu', '')
        multiplier = data.get('multiplier', 1)
        hand_counts = data.get('hand_counts', {})
        current = data.get('current_player', '')
        play_history = data.get('play_history', [])
        dizhu_cards = data.get('dizhu_cards', [])
        my_cards = data.get('my_cards', [])
        state = data.get('room_state', 'playing')

        text.append(f'  倍率 ×{multiplier}', style=_DIM)
        text.append('\n\n')

        # 底牌
        if dizhu_cards:
            text.append('  底牌: ', style=_DIM)
            for c in dizhu_cards:
                text.append(f'[{c}]', style=_card_style(c))
                text.append(' ')
            text.append('\n')

        # 收集每个玩家的出牌（保留打出顺序 + 轮次信息）
        player_plays: dict[str, list[dict]] = {p: [] for p in players}
        for i, entry in enumerate(play_history):
            ep = entry.get('player', '')
            if ep in player_plays:
                player_plays[ep].append({
                    'cards': entry.get('cards', []),
                    'round': entry.get('round', 0),
                    'gidx': i,
                })
        last_gidx = len(play_history) - 1 if play_history else -1
        cur_round = play_history[-1].get('round', 0) if play_history else -1

        # 各玩家状态
        for p in players:
            prefix = '→ ' if p == current else '  '
            text.append(prefix, style=_DIM)

            role_style = _DIZHU if p == dizhu else _FARMER
            if p == dizhu:
                text.append('*', style=_DIZHU)
            else:
                text.append(' ', style=_DIM)
            text.append(p, style=role_style)

            count = hand_counts.get(p, 0)
            text.append(f'  [{count}张]', style=_DIM)
            text.append('\n')

            # 累计已出的牌（按打出顺序，仅当前轮加背景）
            plays = player_plays[p]
            if plays:
                text.append('    ')
                for play in plays:
                    rnd = play['round']
                    cards = play['cards']
                    if rnd == cur_round:
                        bg = _BG_NEW if play['gidx'] == last_gidx else _BG_A
                        for j, c in enumerate(cards):
                            text.append(_strip_suit(c), style=f'{_card_style(c)} on {bg}')
                            if j < len(cards) - 1:
                                text.append(' ', style=f'on {bg}')
                    else:
                        for j, c in enumerate(cards):
                            text.append(_strip_suit(c), style=_card_style(c))
                            if j < len(cards) - 1:
                                text.append(' ')
                    text.append(' ')
                text.append('\n')

        # 最新出牌
        last_play = data.get('last_play')
        if last_play:
            lp_type = last_play.get('type', '')
            lp_cards = last_play.get('cards', [])
            text.append(f'\n  {lp_type} ', style=_DIM)
            for c in lp_cards:
                text.append(_strip_suit(c), style=_card_style(c))
                text.append(' ')
            text.append('\n')

        # 自己的手牌
        if my_cards:
            text.append('\n')
            _render_hand(text, my_cards)

        # 结果
        if state == 'finished':
            winner = data.get('winner', '')
            spring = data.get('spring', False)
            results = data.get('results', {})
            text.append('\n')
            for p in players:
                outcome = results.get(p, '')
                role = '地主' if p == dizhu else '农民'
                mark = '★' if outcome == 'win' else ' '
                style = _WIN if outcome == 'win' else _DIM
                text.append(f'  {mark} {p} ({role}) ', style=style)
                text.append('胜\n' if outcome == 'win' else '败\n', style=style)
            text.append(f'  ×{multiplier}', style=_DIM)
            if spring:
                text.append('  春天', style=_WIN)
            text.append('\n')

        # 提示 / 推荐出牌
        elif state != 'finished':
            suggestions = data.get('suggestions')
            if suggestions:
                n = len(my_cards)
                text.append('\n  推荐出牌:\n', style=_DIM)
                for si, sug in enumerate(suggestions):
                    idx = n + si
                    stype = sug.get('type', '')
                    if stype == 'pass':
                        text.append(f'  {idx:>2}  ', style=_IDX)
                        text.append('pass\n', style=_DIM)
                    elif stype == 'single_hint':
                        text.append('  单张（输入序号）\n', style=_DIM)
                    else:
                        cards = sug.get('cards', [])
                        text.append(f'  {idx:>2}  ', style=_IDX)
                        for j, c in enumerate(cards):
                            text.append(c, style=_card_style(c))
                            if j < len(cards) - 1:
                                text.append(' ')
                        text.append('\n')

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)

        return text


register_renderer(DoudizhuRenderer())
