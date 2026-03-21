"""麻将游戏渲染器 — 纵向五列布局"""

from __future__ import annotations

import unicodedata

from rich.text import Text
from rich.console import RenderableType

from ..protocol.renderer import register_renderer, render_doc

# ── 花色颜色 ──
_SUIT_COLORS = {
    'm': '#4a9aef',   # 萬子 蓝
    'p': '#e8a040',   # 筒子 橙
    's': '#4aaf5a',   # 條子 绿
}

_HONOR_COLORS = {
    '東': '#5ab8c8', '南': '#5ab8c8', '西': '#5ab8c8', '北': '#5ab8c8',
    '白': '#e0e0e0', '發': '#4aaf5a', '中': '#ef6a4a',
}

_HONOR_DEFAULT = '#c8b060'

_DIM = '#606060'
_SCORE = '#b0b0b0'
_TURN = 'bold #66bb6a'
_RIICHI = 'bold #ff6666'
_HEAD = 'bold #e0e0e0'

# 文档高亮指令
_DOC_COMMANDS = {
    'create', 'rooms', 'join', 'start', 'bot', 'invite',
    'kick', 'back', 'help', 'discard', 'tsumo', 'ron',
    'pon', 'chi', 'pass', 'accept', 'riichi',
}

# 列宽
_CW = 10
# 手牌与弃牌之间的间隔
_GAP = '   '

# ── 工具函数 ──


def _display_width(s: str) -> int:
    """计算字符串的终端显示宽度（CJK占2列）"""
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def _pad(width: int, s: str = '') -> str:
    """返回补齐到 width 所需的空格"""
    return ' ' * max(0, width - _display_width(s))


def _suit_key(tile_str: str) -> str:
    """从短格式牌字符串提取花色键"""
    if len(tile_str) == 2 and tile_str[1] in ('m', 'p', 's'):
        return tile_str[1]
    return 'z'


_NUM_CH = ['一', '二', '三', '四', '五', '六', '七', '八', '九']
_SUIT_CH = {'m': '萬', 'p': '筒', 's': '條'}


def _short_to_chinese(tile_str: str) -> str:
    """短格式 → 中文: 1m → 一萬, 東 → 東"""
    if len(tile_str) == 2 and tile_str[1] in _SUIT_CH:
        num = int(tile_str[0]) - 1
        if 0 <= num <= 8:
            return _NUM_CH[num] + _SUIT_CH[tile_str[1]]
    return tile_str


def _tile_color(tile_str: str) -> str:
    """根据牌字符串返回颜色值"""
    sk = _suit_key(tile_str)
    if sk != 'z':
        return _SUIT_COLORS[sk]
    return _HONOR_COLORS.get(tile_str, _HONOR_DEFAULT)


def _tile_style(tile_str: str) -> str:
    """根据牌字符串返回花色颜色"""
    return f'bold {_tile_color(tile_str)}'


def _render_tile(text: Text, tile_str: str, *, drawn: bool = False):
    """渲染一张带颜色的牌（短格式）"""
    style = _tile_style(tile_str)
    if drawn:
        style += ' underline'
    text.append(f' {tile_str}', style=style)


class MahjongRenderer:
    """麻将渲染器"""

    game_type = 'mahjong'

    def render_board(self, room_data: dict) -> RenderableType:
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            return self._render_waiting(room_data)
        if state == 'playing':
            return self._render_game(room_data)
        if state == 'finished':
            return self._render_finished(room_data)
        return self._render_lobby(room_data)

    # ── 大厅 ──

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

    # ── 等待 ──

    _TIER_LABELS = {
        'friendly': '友人場', 'bronze': '銅之間',
        'silver': '銀之間', 'gold': '金之間',
    }

    def _render_waiting(self, data: dict) -> RenderableType:
        text = Text()
        room_id = data.get('room_id', '????')
        host = data.get('host', '???')
        players = data.get('players', [])
        max_p = data.get('max_players', 4)
        mode = data.get('game_mode', 'east')
        tier = data.get('room_tier', 'friendly')
        round_name = data.get('round_name', '')

        mode_label = '東風戰' if mode == 'east' else '南風戰'
        tier_label = self._TIER_LABELS.get(tier, '友人場')
        text.append(f'  * MAHJONG  {mode_label}  {tier_label}\n\n', style=_HEAD)
        text.append(f'  房間 #{room_id}  房主: {host}', style=_SCORE)
        if round_name:
            text.append(f'  {round_name}', style=_DIM)
        text.append('\n')
        count = sum(1 for p in players if p.get('name'))
        text.append(f'  等待中 ({count}/{max_p})\n\n', style=_DIM)

        for p in players:
            name = p.get('name')
            pos = p.get('position', '?')
            score = p.get('score', 25000)
            is_bot = p.get('is_bot', False)
            if name:
                mark = ' (Bot)' if is_bot else ''
                text.append(f'  [{pos}] {name}{mark}  {score}pt\n', style='#c0c0c0')
            else:
                text.append(f'  [{pos}] ---\n', style='#484848')

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)
        return text

    # ── 游戏中 ──

    def _render_game(self, data: dict) -> RenderableType:
        text = Text()
        players = data.get('players', [])
        current_turn = data.get('current_turn', 0)
        my_turn = data.get('my_turn', False)
        seat = data.get('seat', 0)
        hand = data.get('hand', [])
        hand_chinese = data.get('hand_chinese', [])
        drawn = data.get('drawn')
        discards = data.get('discards', [[], [], [], []])
        discards_chinese = data.get('discards_chinese', [[], [], [], []])
        melds = data.get('melds', [[], [], [], []])
        wall_remaining = data.get('wall_remaining', 0)
        round_name = data.get('round_name', '東一局')
        honba = data.get('honba', 0)
        riichi_sticks = data.get('riichi_sticks', 0)
        dealer = data.get('dealer', 0)

        tiles = hand_chinese if hand_chinese else hand
        hand_136 = data.get('hand_136', [])
        dora_tiles_34 = set(data.get('dora_tiles_34', []))
        CW = _CW

        # ── 标题行 ──
        text.append(f'  {round_name}', style=_HEAD)
        text.append(f'  剩{wall_remaining}', style=_DIM)
        if honba:
            text.append(f'  {honba}本場', style=_DIM)
        if riichi_sticks:
            text.append(f'  供{riichi_sticks}', style=_DIM)

        # 宝牌指示
        dora_cn = data.get('dora_indicators', [])
        dora_str = data.get('dora_indicators_str', [])
        if dora_cn:
            text.append('  寶牌:', style=_DIM)
            for i, d in enumerate(dora_cn):
                ds = dora_str[i] if i < len(dora_str) else ''
                text.append(f' {d}', style=_tile_style(ds) if ds else _DIM)

        # 向聽
        shanten = data.get('shanten')
        if shanten is not None:
            if shanten <= 0:
                waiting = data.get('waiting_tiles', [])
                if waiting:
                    text.append(f'  聽 ', style='bold #66bb6a')
                    for wi, w in enumerate(waiting):
                        if isinstance(w, dict):
                            name = w.get('name', '?')
                            rem = w.get('remaining', '?')
                            han = w.get('han')
                            fu = w.get('fu')
                            pts = w.get('points')
                            text.append(f'{name}', style='bold #66bb6a')
                            text.append(f'×{rem}', style=_DIM)
                            if han and pts:
                                text.append(
                                    f'({han}翻{fu}符 {pts})',
                                    style=_DIM)
                        else:
                            text.append(str(w), style='bold #66bb6a')
                        if wi < len(waiting) - 1:
                            text.append('  ')
                else:
                    text.append('  聽牌', style='bold #66bb6a')
            else:
                text.append(f'  {shanten}向聽', style=_DIM)

        text.append('\n\n')

        # ── 列头: 手牌 + 東南西北 ──
        # 风位行
        lbl_hand = '    手牌'
        text.append(lbl_hand, style=_HEAD)
        text.append(_pad(CW, lbl_hand))
        text.append(_GAP)
        for wi in range(4):
            p = players[wi] if wi < len(players) else {}
            pos = p.get('position', '?')
            is_current = wi == current_turn
            is_dealer_seat = wi == dealer
            arrow = '*' if is_current else ' '
            d_mark = '親' if is_dealer_seat else ''
            lbl = f'{pos}{d_mark}{arrow}'
            style = _TURN if is_current else _HEAD
            text.append(lbl, style=style)
            text.append(_pad(CW, lbl))
        text.append('\n')

        # 玩家名行
        text.append(' ' * CW)
        text.append(_GAP)
        for wi in range(4):
            p = players[wi] if wi < len(players) else {}
            name = p.get('name', '---')
            is_current = wi == current_turn
            while _display_width(name) >= CW:
                name = name[:-1]
            text.append(name, style=_TURN if is_current else _SCORE)
            text.append(_pad(CW, name))
        text.append('\n')

        # 分数行
        text.append(' ' * CW)
        text.append(_GAP)
        for wi in range(4):
            p = players[wi] if wi < len(players) else {}
            score = p.get('score', 0)
            riichi = p.get('riichi', False)
            s = f'{score}pt'
            text.append(s, style=_RIICHI if riichi else _DIM)
            text.append(_pad(CW, s))
        text.append('\n')

        # 立直棒行
        my_riichi = any(
            players[wi].get('riichi') for wi in range(min(4, len(players))))
        if my_riichi:
            # 手牌列: "立直" 标签
            lbl = '    立直'
            text.append(lbl, style=_DIM)
            text.append(_pad(CW, lbl))
            text.append(_GAP)
            for wi in range(4):
                p = players[wi] if wi < len(players) else {}
                riichi = p.get('riichi', False)
                if riichi:
                    stick = '──────'
                    text.append(stick, style=_RIICHI)
                    text.append(_pad(CW, stick))
                else:
                    text.append(' ' * CW)
            text.append('\n')

        text.append('\n')

        # ── 纵向牌面 ──
        max_discard = max((len(d) for d in discards), default=0)
        max_rows = max(len(tiles), max_discard)

        for row in range(max_rows):
            # 手牌列
            if row < len(tiles):
                tile_name = tiles[row]
                is_drawn_tile = bool(drawn) and row == len(tiles) - 1
                marker = '→' if is_drawn_tile else ' '
                idx_str = f'{row + 1:>2}'
                prefix = f'{marker}{idx_str} '

                sk = _suit_key(hand[row]) if row < len(hand) else 'z'
                color = _tile_color(hand[row]) if row < len(hand) else _HONOR_DEFAULT
                tile_sty = f'bold {color}'
                if is_drawn_tile:
                    tile_sty += ' underline'

                # 宝牌标记
                is_dora = (row < len(hand_136)
                           and hand_136[row] // 4 in dora_tiles_34)
                dora_mark = '★' if is_dora else ''

                text.append(prefix, style=_DIM)
                text.append(tile_name, style=tile_sty)
                if dora_mark:
                    text.append(dora_mark, style='bold #e8a040')
                used = (_display_width(prefix) + _display_width(tile_name)
                        + _display_width(dora_mark))
                text.append(' ' * max(0, CW - used))
            else:
                text.append(' ' * CW)

            text.append(_GAP)

            # 弃牌列 (東南西北)
            for wi in range(4):
                d_cn = discards_chinese[wi] if wi < len(discards_chinese) else []
                d = discards[wi] if wi < len(discards) else []
                if row < len(d_cn):
                    tile_cn = d_cn[row]
                    tile_str = d[row] if row < len(d) else ''
                    sk = _suit_key(tile_str)
                    color = _tile_color(tile_str)
                    text.append(tile_cn, style=f'bold {color}')
                    text.append(_pad(CW, tile_cn))
                else:
                    text.append(' ' * CW)

            text.append('\n')

        # ── 副露 ──
        has_any_melds = any(melds[i] for i in range(4))
        if has_any_melds:
            text.append('\n')
            for wi in range(4):
                player_melds = melds[wi] if wi < len(melds) else []
                if player_melds:
                    p = players[wi] if wi < len(players) else {}
                    pos = p.get('position', '?')
                    text.append(f'  {pos} 副露: ', style=_DIM)
                    for mi, meld in enumerate(player_melds):
                        if mi > 0:
                            text.append(' ')
                        text.append('[')
                        for j, t in enumerate(meld):
                            if j > 0:
                                text.append(' ')
                            cn = _short_to_chinese(t)
                            text.append(cn, style=_tile_style(t))
                        text.append(']')
                    text.append('\n')

        # ── 听牌提示（纵向列表） ──
        tenpai_discards = data.get('tenpai_discards', [])
        if tenpai_discards:
            text.append('\n')
            text.append('  打牌听牌提示:\n', style=_DIM)
            for td in tenpai_discards:
                idx = td.get('idx', '?')
                tile_cn = td.get('tile_chinese', '?')
                waits = td.get('waiting', [])
                text.append(f'  {idx}. {tile_cn} →', style=_DIM)
                for wi, w in enumerate(waits):
                    text.append(
                        f' {w["name"]}×{w["remaining"]}',
                        style='#66bb6a')
                text.append('\n')

        # ── 操作提示 ──
        text.append('\n')
        available_actions = data.get('available_actions')
        action_tile = data.get('action_tile', '')
        if available_actions:
            _ACTION_LABELS = {
                'ron': '和(ron)', 'pon': '碰(pon)',
                'chi': '吃(chi)', 'pass': '过(pass)',
            }
            labels = [_ACTION_LABELS.get(a, a) for a in available_actions]
            text.append(f'  > ', style=_HEAD)
            text.append(f'{action_tile}', style='bold #ffffff')
            text.append(f'  {" / ".join(labels)}\n', style='#ffffff')
        elif my_turn:
            can_tsumo = data.get('can_tsumo', False)
            can_riichi = data.get('can_riichi', False)
            hints = []
            if can_tsumo:
                hints.append('自摸(tsumo)')
            if can_riichi:
                hints.append('立直(riichi <序號>)')
            hints.append('輸入序號打牌')
            text.append(f'  > {" / ".join(hints)}\n', style=_TURN)

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)

        return text

    # ── 結束 ──

    def _render_finished(self, data: dict) -> RenderableType:
        text = Text()
        round_name = data.get('round_name', '')
        text.append(f'  * MAHJONG  {round_name}  結束\n\n', style=_HEAD)

        winner = data.get('winner')
        is_draw = data.get('draw', False)

        if winner:
            win_info = data.get('win_info', {})
            win_pos = data.get('winner_position', '?')
            han = win_info.get('han', 0)
            fu = win_info.get('fu', 0)
            cost = win_info.get('cost', 0)
            yaku = win_info.get('yaku', [])
            text.append(f'  [{win_pos}] {winner} 和牌!\n', style='bold #66bb6a')
            text.append(f'  {han}翻{fu}符  {cost}点\n', style=_HEAD)
            if yaku:
                text.append(f'  役: {", ".join(yaku)}\n', style='#c0c0c0')
        elif is_draw:
            text.append('  流局\n', style='#c0c0c0')

        text.append('\n')

        # 各家得分
        players = data.get('players', [])
        for p in players:
            name = p.get('name', '---')
            pos = p.get('position', '?')
            score = p.get('score', 0)
            if name:
                text.append(f'  [{pos}] {name}  {score}pt\n', style=_SCORE)

        # 手牌公开
        all_hands = data.get('all_hands', [])
        all_hands_cn = data.get('all_hands_chinese', [])
        if all_hands:
            text.append('\n')
            for i, h in enumerate(all_hands):
                p = players[i] if i < len(players) else {}
                pos = p.get('position', '?')
                name = p.get('name', '?')
                if h:
                    h_cn = all_hands_cn[i] if i < len(all_hands_cn) else h
                    text.append(f'  [{pos}] {name}: ', style=_DIM)
                    for j, tile in enumerate(h):
                        if j > 0:
                            text.append(' ')
                        tile_name = h_cn[j] if j < len(h_cn) else tile
                        suit_key = tile[-1] if len(tile) == 2 and tile[-1] in ('m', 'p', 's') else 'z'
                        color = _tile_color(tile)
                        text.append(tile_name, style=f'bold {color}')
                    text.append('\n')

        next_round = data.get('next_round')
        if next_round:
            text.append(f'\n  下一局: {next_round}  (房主輸入 start)\n', style=_DIM)

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)

        return text


register_renderer(MahjongRenderer())
