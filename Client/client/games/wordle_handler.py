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

    def ai_on_room_update(self, old_data: dict, new_data: dict) -> tuple[str, bool] | None:
        """检测 Wordle 游戏状态变化，通知 AI 旅伴"""
        if new_data.get('room_state') != 'playing':
            return None
        old_guesses = old_data.get('guesses', []) if old_data else []
        new_guesses = new_data.get('guesses', [])
        if len(new_guesses) <= len(old_guesses):
            return None
        # 有新的猜测
        word = new_guesses[-1].upper()
        result = new_data.get('results', [])[-1] if new_data.get('results') else []
        correct_count = result.count('correct') if result else 0
        total = len(result) if result else 0
        won = new_data.get('won', False)
        remain = new_data.get('max_guesses', 6) - len(new_guesses)
        if won:
            desc = f'Wordle: 玩家猜了 {word}，全部正确！猜对了！'
        else:
            desc = f'Wordle: 玩家猜了 {word}，{correct_count}/{total}个字母位置正确，剩余{remain}次机会'
        return (desc, True)

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
