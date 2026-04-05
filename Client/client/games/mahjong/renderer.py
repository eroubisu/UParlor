"""麻将游戏渲染器 — 纵向五列布局"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer, render_doc

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
_SEP = '#808080'
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

# ── 工具函数 ──



def _pad(width: int, s: str = '') -> str:
    """返回补齐到 width 所需的空格"""
    return ' ' * max(0, width - cell_len(s))


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

        text.append('\n\n')

        # ── 列头: 风位行 ──
        text.append(' ' * CW)
        for wi in range(4):
            p = players[wi] if wi < len(players) else {}
            pos = p.get('position', '?')
            is_current = wi == current_turn
            is_dealer_seat = wi == dealer
            arrow = '*' if is_current else ' '
            d_mark = '親' if is_dealer_seat else ''
            lbl = f'{pos}{d_mark}{arrow}'
            style = _TURN if is_current else _HEAD
            text.append('│', style=_SEP)
            text.append(lbl, style=style)
            text.append(_pad(CW - 1, lbl))
        text.append('\n')

        # 玩家名行
        text.append(' ' * CW)
        for wi in range(4):
            p = players[wi] if wi < len(players) else {}
            name = p.get('name', '---')
            is_current = wi == current_turn
            while cell_len(name) >= CW - 1:
                name = name[:-1]
            text.append('│', style=_SEP)
            text.append(name, style=_TURN if is_current else _SCORE)
            text.append(_pad(CW - 1, name))
        text.append('\n')

        # 分数行 (手牌列显示 "手牌" 标签)
        lbl_hand = '  手牌'
        text.append(lbl_hand, style=_HEAD)
        text.append(_pad(CW, lbl_hand))
        for wi in range(4):
            p = players[wi] if wi < len(players) else {}
            score = p.get('score', 0)
            riichi = p.get('riichi', False)
            s = f'{score}pt'
            text.append('│', style=_SEP)
            text.append(s, style=_RIICHI if riichi else _DIM)
            text.append(_pad(CW - 1, s))
        text.append('\n')

        # 立直棒行
        my_riichi = any(
            players[wi].get('riichi') for wi in range(min(4, len(players))))
        if my_riichi:
            lbl = '  立直'
            text.append(lbl, style=_DIM)
            text.append(_pad(CW, lbl))
            for wi in range(4):
                p = players[wi] if wi < len(players) else {}
                riichi = p.get('riichi', False)
                text.append('│', style=_SEP)
                if riichi:
                    stick = '──────'
                    text.append(stick, style=_RIICHI)
                    text.append(_pad(CW - 1, stick))
                else:
                    text.append(' ' * (CW - 1))
            text.append('\n')

        # ── 分数 → 副露 分隔线 ──
        text.append(' ' * CW)
        for wi in range(4):
            sep_line = '─' * (CW - 1)
            text.append('│', style=_SEP)
            text.append(sep_line, style=_SEP)
        text.append('\n')

        # ── 构建每家列数据: 副露 → 分隔线 → 弃牌 ──
        last_discard_seat = data.get('last_discard_seat', -1)
        col_data = []  # col_data[wi] = list of (tile_cn, tile_str, is_sep, is_last)
        for wi in range(4):
            col = []
            player_melds = melds[wi] if wi < len(melds) else []
            for mi, meld in enumerate(player_melds):
                if mi > 0:
                    col.append(('·', '', False, False))
                for t in meld:
                    cn = _short_to_chinese(t)
                    col.append((cn, t, False, False))
            # 分隔线（无论有无副露都加，统一对齐）
            sep_line = '─' * (CW - 1)
            col.append((sep_line, '', True, False))
            d_cn = discards_chinese[wi] if wi < len(discards_chinese) else []
            d = discards[wi] if wi < len(discards) else []
            for di in range(len(d_cn)):
                tile_cn = d_cn[di]
                tile_str = d[di] if di < len(d) else ''
                is_last = (wi == last_discard_seat and di == len(d_cn) - 1)
                col.append((tile_cn, tile_str, False, is_last))
            col_data.append(col)

        max_col_rows = max((len(c) for c in col_data), default=0)
        max_rows = max(len(tiles), max_col_rows)

        # ── 纵向牌面 ──
        for row in range(max_rows):
            # 手牌列
            if row < len(tiles):
                tile_name = tiles[row]
                is_drawn_tile = bool(drawn) and row == len(tiles) - 1
                marker = '→' if is_drawn_tile else ' '
                idx_str = f'{row + 1:>2}'
                prefix = f'{marker}{idx_str} '

                color = _tile_color(hand[row]) if row < len(hand) else _HONOR_DEFAULT
                tile_sty = f'bold {color}'
                if is_drawn_tile:
                    tile_sty += ' underline'

                is_dora = (row < len(hand_136)
                           and hand_136[row] // 4 in dora_tiles_34)
                dora_mark = '★' if is_dora else ''

                text.append(prefix, style=_DIM)
                text.append(tile_name, style=tile_sty)
                if dora_mark:
                    text.append(dora_mark, style='bold #e8a040')
                used = (cell_len(prefix) + cell_len(tile_name)
                        + cell_len(dora_mark))
                text.append(' ' * max(0, CW - used))
            else:
                text.append(' ' * CW)

            # 各家列 (副露+分隔+弃牌)
            for wi in range(4):
                col = col_data[wi]
                text.append('│', style=_SEP)
                if row < len(col):
                    tile_cn, tile_str, is_sep, is_last = col[row]
                    if is_sep:
                        text.append(tile_cn, style=_SEP)
                    elif tile_cn == '·':
                        text.append('·', style=_DIM)
                        text.append(' ' * (CW - 2))
                    else:
                        color = _tile_color(tile_str) if tile_str else _DIM
                        if is_last:
                            text.append(tile_cn, style=f'bold {color} underline')
                            text.append('◄', style=_DIM)
                            text.append(_pad(CW - 1, tile_cn + '◄'))
                        else:
                            text.append(tile_cn, style=f'bold {color}')
                            text.append(_pad(CW - 1, tile_cn))
                else:
                    text.append(' ' * (CW - 1))

            text.append('\n')

        # ── 手牌底部: 听牌区 ──
        full_sep = '─' * (CW + (CW + 1) * 4 - 6)
        text.append(f'  {full_sep}\n', style=_SEP)

        tenpai_discards = data.get('tenpai_discards', [])
        waiting_tiles = data.get('waiting_tiles', [])
        is_furiten = data.get('furiten', False)

        if tenpai_discards:
            if is_furiten:
                text.append('  [振听]\n', style='bold #ff6666')
            for td in tenpai_discards:
                idx = td.get('idx', '?')
                tile_cn = td.get('tile_chinese', '?')
                waits = td.get('waiting', [])
                text.append(f'  打{idx} ', style=_DIM)
                text.append(tile_cn, style='bold #ffffff')
                text.append(' → 听 ', style=_DIM)
                for wi, w in enumerate(waits):
                    if wi > 0:
                        text.append('  ')
                    name = w.get('name', '?')
                    ts = w.get('tile_str', '')
                    rem = w.get('remaining', '?')
                    han = w.get('han')
                    pts = w.get('points')
                    color = _tile_color(ts) if ts else '#66bb6a'
                    text.append(f'{name}', style=f'bold {color}')
                    text.append(f'×{rem}', style=_DIM)
                    if w.get('furiten'):
                        text.append('振', style='bold #ff6666')
                    elif w.get('no_yaku'):
                        text.append('(无役)', style='bold #707070')
                    elif han and pts:
                        text.append(f'({han}番{pts})', style=_DIM)
                text.append('\n')
        elif waiting_tiles:
            if is_furiten:
                text.append('  [振听] ', style='bold #ff6666')
            text.append('  听 ', style='bold #66bb6a')
            for wi, w in enumerate(waiting_tiles):
                if wi > 0:
                    text.append('  ')
                if isinstance(w, dict):
                    name = w.get('name', '?')
                    ts = w.get('tile_str', '')
                    rem = w.get('remaining', '?')
                    han = w.get('han')
                    pts = w.get('points')
                    color = _tile_color(ts) if ts else '#66bb6a'
                    text.append(f'{name}', style=f'bold {color}')
                    text.append(f'×{rem}', style=_DIM)
                    if w.get('furiten'):
                        text.append('振', style='bold #ff6666')
                    elif w.get('no_yaku'):
                        text.append('(无役)', style='bold #707070')
                    elif han and pts:
                        text.append(f'({han}番{pts})', style=_DIM)
                else:
                    text.append(str(w), style='bold #66bb6a')
            text.append('\n')

        # ── 操作提示 ──
        text.append('\n')
        available_actions = data.get('available_actions')
        action_tile = data.get('action_tile', '')
        if available_actions:
            has_ron = 'ron' in available_actions
            if has_ron:
                text.append('  ★ ', style='bold #ff6666')
                text.append(action_tile, style='bold #ffffff')
                text.append('  ', style=_DIM)
                for ai, a in enumerate(available_actions):
                    if ai > 0:
                        text.append(' / ', style=_DIM)
                    if a == 'ron':
                        text.append('和(ron)', style='bold #ff6666')
                    elif a == 'pon':
                        text.append('碰(pon)', style='bold #ffffff')
                    elif a == 'chi':
                        text.append('吃(chi)', style='bold #ffffff')
                    else:
                        text.append('过(pass)', style=_DIM)
                text.append('\n')
            else:
                _ACTION_LABELS = {
                    'pon': '碰(pon)', 'chi': '吃(chi)', 'pass': '过(pass)',
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

    # ── 結束（渐进展示）──

    def _render_finished(self, data: dict) -> RenderableType:
        text = Text()
        round_name = data.get('round_name', '')
        winner = data.get('winner')

        if data.get('draw', False):
            return self._render_draw(data)

        # ── 和牌渐进展示 ──
        win_info = data.get('win_info', {})
        win_pos = data.get('winner_position', '?')
        is_tsumo = data.get('is_tsumo', True)
        win_type = '自摸' if is_tsumo else '荣和'
        yaku = win_info.get('yaku', [])
        win_step = data.get('win_step', 0)
        n_yaku = len(yaku)

        text.append(f'  * MAHJONG  {round_name}\n\n', style=_HEAD)
        text.append(f'  [{win_pos}] {winner} {win_type}!\n',
                    style='bold #66bb6a')

        # 荣和: 显示放铳牌
        if not is_tsumo:
            from_player = data.get('from_player', '')
            from_pos = data.get('from_position', '')
            ron_tile = data.get('ron_tile', '')
            ron_tile_cn = data.get('ron_tile_chinese', '')
            if ron_tile_cn:
                color = _tile_color(ron_tile)
                text.append(f'  [{from_pos}] {from_player} 放铳: ',
                            style=_DIM)
                text.append(ron_tile_cn, style=f'bold {color}')
                text.append('\n')

        text.append('\n')

        # 各家手牌（step 1 才展示）
        if win_step < 1:
            return text

        players = data.get('players', [])
        all_hands = data.get('all_hands', [])
        all_hands_cn = data.get('all_hands_chinese', [])
        all_melds = data.get('all_melds', [])
        all_melds_str = data.get('all_melds_str', [])
        tenpai_seats = data.get('tenpai_seats', [])

        for i, h in enumerate(all_hands):
            p = players[i] if i < len(players) else {}
            pos = p.get('position', '?')
            name = p.get('name', '?')
            if not name:
                continue
            is_winner = (name == winner)
            tag = ''
            if is_winner:
                tag = ' ★'
            elif i in tenpai_seats:
                tag = ' 聴'

            label_style = 'bold #66bb6a' if is_winner else _DIM
            text.append(f'  [{pos}] {name}{tag}: ', style=label_style)

            if h:
                h_cn = all_hands_cn[i] if i < len(all_hands_cn) else h
                for j, tile in enumerate(h):
                    if j > 0:
                        text.append(' ')
                    tile_name = h_cn[j] if j < len(h_cn) else tile
                    color = _tile_color(tile)
                    text.append(tile_name, style=f'bold {color}')

            # 副露
            melds_cn = all_melds[i] if i < len(all_melds) else []
            melds_s = all_melds_str[i] if i < len(all_melds_str) else []
            for mi, meld_cn in enumerate(melds_cn):
                text.append('  [', style=_DIM)
                meld_s = melds_s[mi] if mi < len(melds_s) else meld_cn
                for ti, tc in enumerate(meld_cn):
                    if ti > 0:
                        text.append(' ')
                    ts = meld_s[ti] if ti < len(meld_s) else ''
                    color = _tile_color(ts)
                    text.append(tc, style=f'bold {color}')
                text.append(']', style=_DIM)

            text.append('\n')

        # 渐进: 役种（逐条, step 2 起）
        if win_step >= 2:
            text.append('\n')
            shown = yaku[:min(win_step - 1, n_yaku)]
            for y in shown:
                text.append(f'  · {y}\n', style='#c0c0c0')

        # 渐进: 总番数/得点
        if win_step >= n_yaku + 2:
            han = win_info.get('han', 0)
            fu = win_info.get('fu', 0)
            cost = win_info.get('cost', 0)
            text.append(f'\n  {han}番{fu}符  {cost}点\n', style=_HEAD)

        # 渐进: 各家分数变动 + 段位pt
        if win_step >= n_yaku + 3:
            score_changes = data.get('score_changes', [])
            rank_changes = data.get('rank_changes', {})
            text.append('\n')
            for i, p in enumerate(players):
                name = p.get('name', '---')
                if not name:
                    continue
                pos = p.get('position', '?')
                score = p.get('score', 0)
                delta = score_changes[i] if i < len(score_changes) else 0
                sign = '+' if delta >= 0 else ''
                text.append(
                    f'  [{pos}] {name}  {score}pt  ({sign}{delta})',
                    style=_SCORE)
                rc = rank_changes.get(name)
                if rc:
                    d = rc.get('delta', 0)
                    rsign = '+' if d >= 0 else ''
                    text.append(f'  [{rsign}{d}段位pt]', style=_DIM)
                    if rc.get('promoted'):
                        text.append(
                            f' ↑{rc["new_rank_name"]}', style='bold #66bb6a')
                    elif rc.get('demoted'):
                        text.append(
                            f' ↓{rc["new_rank_name"]}', style='bold #ef6a4a')
                text.append('\n')

        # 渐进: 下一局提示
        if win_step >= n_yaku + 4:
            next_round = data.get('next_round')
            if next_round:
                text.append(
                    f'\n  下一局: {next_round}  (房主输入 start)\n',
                    style=_DIM)
            msg = data.get('message')
            if msg:
                text.append(f'\n  {msg}\n', style=_SCORE)

        return text

    def _render_draw(self, data: dict) -> RenderableType:
        """流局"""
        text = Text()
        round_name = data.get('round_name', '')
        text.append(f'  * MAHJONG  {round_name}  流局\n\n', style=_HEAD)

        players = data.get('players', [])
        rank_changes = data.get('rank_changes', {})
        for p in players:
            name = p.get('name', '---')
            pos = p.get('position', '?')
            score = p.get('score', 0)
            if name:
                text.append(f'  [{pos}] {name}  {score}pt', style=_SCORE)
                rc = rank_changes.get(name)
                if rc:
                    d = rc.get('delta', 0)
                    rsign = '+' if d >= 0 else ''
                    text.append(f'  [{rsign}{d}段位pt]', style=_DIM)
                    if rc.get('promoted'):
                        text.append(
                            f' ↑{rc["new_rank_name"]}', style='bold #66bb6a')
                    elif rc.get('demoted'):
                        text.append(
                            f' ↓{rc["new_rank_name"]}', style='bold #ef6a4a')
                text.append('\n')

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
                        color = _tile_color(tile)
                        text.append(tile_name, style=f'bold {color}')
                    text.append('\n')

        next_round = data.get('next_round')
        if next_round:
            text.append(f'\n  下一局: {next_round}  (房主输入 start)\n',
                        style=_DIM)

        msg = data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style=_SCORE)

        return text


register_renderer(MahjongRenderer())
