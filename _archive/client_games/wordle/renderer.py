"""Wordle 游戏渲染器 — ASCII 方括号风格"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer, render_doc

# 状态 → 样式映射
_CELL_STYLES = {
    'correct': 'bold #66bb6a',   # 绿
    'present': 'bold #fdd835',   # 黄
    'absent':  '#808080',        # 灰
    'empty':   '#585858',        # 灰框
}

_KEY_STYLES = {
    'correct': 'bold #66bb6a',
    'present': 'bold #fdd835',
    'absent':  '#606060',
    'unknown': 'bold #ffffff',
}

_KEYBOARD_ROWS = [
    list('qwertyuiop'),
    list('asdfghjkl'),
    list('zxcvbnm'),
]

# 字母状态优先级: correct > present > absent > unknown
_STATE_PRIORITY = {'correct': 3, 'present': 2, 'absent': 1, 'unknown': 0}


def _merge_letter_states(all_boards: dict) -> dict[str, str]:
    """合并所有玩家的字母状态，取最高优先级"""
    merged: dict[str, str] = {}
    for board in all_boards.values():
        for word, result in zip(board.get('guesses', []), board.get('results', [])):
            for ch, st in zip(word, result):
                prev = merged.get(ch, 'unknown')
                if _STATE_PRIORITY.get(st, 0) > _STATE_PRIORITY.get(prev, 0):
                    merged[ch] = st
    return merged


# 文档中需要高亮的指令词
_DOC_COMMANDS = {
    'create', 'start', 'leave', 'back', 'home', 'rooms', 'help',
}


class WordleRenderer:
    """Wordle 渲染器"""

    game_type = 'wordle'

    def render_board(self, room_data: dict) -> RenderableType:
        room_state = room_data.get('room_state', 'lobby')

        if room_state == 'waiting':
            return self._render_waiting(room_data)
        if room_state in ('playing', 'finished'):
            return self._render_game(room_data)

        # lobby 状态 — 先显示文档，再追加消息
        parts = []
        doc = room_data.get('doc')
        if doc:
            parts.append(render_doc(doc, _DOC_COMMANDS))
        msg = room_data.get('message')
        if msg:
            text = Text()
            if parts:
                text.append('\n')
            for line in msg.split('\n'):
                text.append(f'  {line}\n', style='#b0b0b0')
            parts.append(text)
        if not parts:
            return Text('')
        if len(parts) == 1:
            return parts[0]
        # 合并多个 Text 对象
        combined = Text()
        for p in parts:
            combined.append_text(p) if isinstance(p, Text) else combined.append(str(p))
        return combined

    def _render_waiting(self, room_data: dict) -> RenderableType:
        text = Text()
        room_id = room_data.get('room_id', '????')
        host = room_data.get('host', '???')
        players = room_data.get('players', [])
        text.append('  ◆ WORDLE\n\n', style='bold #e0e0e0')
        text.append(f'  房间 #{room_id}  房主: {host}\n', style='#b0b0b0')
        count = len(players) if isinstance(players, list) else 0
        text.append(f'  等待中 ({count}/{4})\n\n', style='#808080')
        for p in players:
            if isinstance(p, str):
                text.append(f'  · {p}\n', style='#c0c0c0')
        msg = room_data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style='#b0b0b0')
        return text

    def _render_game(self, room_data: dict) -> RenderableType:
        is_multi = room_data.get('is_multiplayer', False)
        if is_multi:
            return self._render_multi(room_data)
        return self._render_solo(room_data)

    def _render_solo(self, room_data: dict) -> RenderableType:
        """单人模式渲染"""
        guesses = room_data.get('guesses', [])
        results = room_data.get('results', [])
        max_guesses = room_data.get('max_guesses', 6)
        word_length = room_data.get('word_length', 5)
        finished = room_data.get('finished', False)
        letter_states = room_data.get('letter_states', {})
        room_id = room_data.get('room_id', '')

        text = Text()

        # 标题行
        title = '  ◆ W O R D L E'
        text.append(title, style='bold #e0e0e0')
        if room_id:
            text.append(f'         #{room_id}', style='#707070')
        text.append('\n\n')

        # 猜词格子 — 方括号风格
        for row_idx in range(max_guesses):
            text.append('  ')
            if row_idx < len(guesses):
                word = guesses[row_idx]
                result = results[row_idx]
                for i, (ch, st) in enumerate(zip(word, result)):
                    style = _CELL_STYLES.get(st, '#585858')
                    text.append('[ ', style='#585858')
                    text.append(ch.upper(), style=style)
                    text.append(' ]', style='#585858')
                    if i < word_length - 1:
                        text.append(' ')
            else:
                for i in range(word_length):
                    text.append('[   ]', style='#585858')
                    if i < word_length - 1:
                        text.append(' ')
            text.append('\n')

        text.append('\n')

        # 键盘状态
        indent = ['  ', '   ', '      ']
        for idx, row in enumerate(_KEYBOARD_ROWS):
            text.append(indent[idx])
            for ch in row:
                st = letter_states.get(ch, 'unknown')
                style = _KEY_STYLES.get(st, '#808080')
                text.append(f' {ch.upper()} ', style=style)
            text.append('\n')

        # 状态行
        msg = room_data.get('message')
        if finished:
            answer = room_data.get('answer', '?????')
            won = room_data.get('won', False)
            attempts = len(guesses)
            text.append('\n')
            if won:
                label = f'  ● {answer.upper()}  {attempts}/{max_guesses}'
                if msg:
                    label += f'  {msg}'
                text.append(label + '\n', style='bold #66bb6a')
            else:
                label = f'  ● {answer.upper()}'
                if msg:
                    label += f'  {msg}'
                text.append(label + '\n', style='#c0c0c0')
        elif msg:
            text.append(f'\n  {msg}\n', style='#b0b0b0')
        else:
            remain = max_guesses - len(guesses)
            text.append(f'\n  剩余 {remain} 次\n', style='#808080')

        return text

    # ── 多人模式渲染 ──

    def _render_multi(self, room_data: dict) -> RenderableType:
        """多人模式: 自己大格子 + 对手紧凑词 + 合并键盘"""
        all_boards = room_data.get('all_boards', {})
        max_guesses = room_data.get('max_guesses', 6)
        word_length = room_data.get('word_length', 5)
        finished = room_data.get('finished', False)
        viewer = room_data.get('viewer', '')
        room_id = room_data.get('room_id', '')
        winner = room_data.get('winner')

        text = Text()

        # 标题
        text.append('  ◆ W O R D L E', style='bold #e0e0e0')
        if room_id:
            text.append(f'  #{room_id}', style='#707070')
        text.append('  多人对战\n\n', style='#808080')

        # ── 自己的棋盘（大格子，完整 6 行）──
        my_board = all_boards.get(viewer, {})
        my_guesses = my_board.get('guesses', [])
        my_results = my_board.get('results', [])

        for row_idx in range(max_guesses):
            text.append('  ')
            if row_idx < len(my_guesses):
                word = my_guesses[row_idx]
                result = my_results[row_idx]
                for i, (ch, st) in enumerate(zip(word, result)):
                    style = _CELL_STYLES.get(st, '#585858')
                    text.append('[ ', style='#585858')
                    text.append(ch.upper(), style=style)
                    text.append(' ]', style='#585858')
                    if i < word_length - 1:
                        text.append(' ')
            else:
                for i in range(word_length):
                    text.append('[   ]', style='#585858')
                    if i < word_length - 1:
                        text.append(' ')
            text.append('\n')

        # ── 对手棋盘（紧凑: 彩色字母词 + 次数）──
        opponents = [
            (name, board)
            for name, board in all_boards.items()
            if name != viewer
        ]
        if opponents:
            text.append('\n  ')
            text.append('─' * 30, style='#454545')
            text.append('\n')

        for opp_name, board in opponents:
            guesses = board.get('guesses', [])
            results = board.get('results', [])
            p_won = board.get('won', False)
            p_finished = board.get('finished', False)
            attempt_count = len(guesses)

            # 名字 + 状态
            text.append('\n')
            if p_won:
                text.append(f'  ★ {opp_name}', style='bold #66bb6a')
                text.append(f'  {attempt_count}/{max_guesses}\n', style='#66bb6a')
            elif finished or p_finished:
                text.append(f'  ✗ {opp_name}', style='#808080')
                text.append(f'  {attempt_count}/{max_guesses}\n', style='#606060')
            else:
                text.append(f'  ● {opp_name}', style='bold #b0b0b0')
                text.append(f'  {attempt_count}/{max_guesses}\n', style='#808080')

            # 每行猜词: 紧凑彩色字母
            for word, result in zip(guesses, results):
                text.append('    ')
                for ch, st in zip(word, result):
                    style = _CELL_STYLES.get(st, '#585858')
                    text.append(ch, style=style)
                text.append('\n')

        # ── 键盘（合并所有玩家的字母状态）──
        merged_states = _merge_letter_states(all_boards)

        text.append('\n')
        indent = ['  ', '   ', '      ']
        for idx, row in enumerate(_KEYBOARD_ROWS):
            text.append(indent[idx])
            for ch in row:
                st = merged_states.get(ch, 'unknown')
                style = _KEY_STYLES.get(st, '#808080')
                text.append(f' {ch.upper()} ', style=style)
            text.append('\n')

        # 状态行
        msg = room_data.get('message')
        if finished:
            answer = room_data.get('answer', '?????')
            text.append('\n')
            if winner:
                text.append(f'  ● {answer.upper()}  优胜: {winner}',
                            style='bold #66bb6a')
            else:
                text.append(f'  ● {answer.upper()}  无人猜对', style='#c0c0c0')
            text.append('\n')
            if msg:
                text.append(f'  {msg}\n', style='#b0b0b0')
        elif msg:
            text.append(f'\n  {msg}\n', style='#b0b0b0')

        return text


register_renderer(WordleRenderer())
