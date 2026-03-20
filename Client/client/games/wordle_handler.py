"""Wordle 客户端事件处理器"""

from __future__ import annotations

from ..protocol.handler import register_handler, GameHandlerContext


class WordleClientHandler:
    """Wordle 客户端事件处理器"""

    game_type = 'wordle'

    def get_input_prefix(self, location: str) -> str | None:
        """playing 状态直接输入单词即作为 guess"""
        if location == 'wordle_playing':
            return '/guess '
        # wordle_finished / wordle_room / wordle_lobby — 禁止文字输入
        return None

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        if event == 'select_menu':
            ctx.show_select_menu(
                title=data.get('title', ''),
                items=data.get('items', []),
                empty_msg=data.get('empty_msg', ''),
            )
            return True
        return False

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        ctx.ensure_panel('game_board')

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        pass

    def ai_describe(self, room_data: dict) -> str:
        room_state = room_data.get('room_state', 'lobby')
        if room_state == 'lobby':
            return 'Wordle 大厅'
        if room_state == 'waiting':
            room_id = room_data.get('room_id', '?')
            return f'Wordle 房间#{room_id}，等待开始'
        guesses = room_data.get('guesses', [])
        max_guesses = room_data.get('max_guesses', 6)
        finished = room_data.get('finished', False)
        if finished:
            answer = room_data.get('answer', '?')
            won = room_data.get('won', False)
            return f'Wordle 已结束，答案: {answer}，{"猜对了" if won else "未猜出"}'
        remain = max_guesses - len(guesses)
        letters = room_data.get('letter_states', {})
        correct = [k for k, v in letters.items() if v == 'correct']
        present = [k for k, v in letters.items() if v == 'present']
        parts = [f'Wordle 进行中，已猜{len(guesses)}次，剩余{remain}次']
        if correct:
            parts.append(f'正确字母: {",".join(correct)}')
        if present:
            parts.append(f'位置错误: {",".join(present)}')
        return '；'.join(parts)


register_handler(WordleClientHandler())
