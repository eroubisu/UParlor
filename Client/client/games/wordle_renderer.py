"""Wordle 游戏渲染器 — ASCII 方括号风格"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ..protocol.renderer import register_renderer, render_doc

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

# 文档中需要高亮的指令词
_DOC_COMMANDS = {
    'create', 'start', 'giveup', 'leave', 'back', 'home', 'rooms', 'help',
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
        text.append('  ◆ WORDLE\n\n', style='bold #e0e0e0')
        text.append(f'  房间 #{room_id}  房主: {host}\n', style='#b0b0b0')
        text.append('  状态: 等待中\n', style='#808080')
        msg = room_data.get('message')
        if msg:
            text.append(f'\n  {msg}\n', style='#b0b0b0')
        return text

    def _render_game(self, room_data: dict) -> RenderableType:
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


register_renderer(WordleRenderer())
