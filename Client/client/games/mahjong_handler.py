"""麻将客户端事件处理器"""

from __future__ import annotations

from ..protocol.handler import register_handler, GameHandlerContext


class MahjongClientHandler:
    """麻将客户端事件处理器"""

    game_type = 'mahjong'

    def get_input_prefix(self, location: str) -> str | None:
        """playing 状态直接输入序号作为 discard"""
        if location == 'mahjong_playing':
            return '/discard '
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
        """为 AI 旅伴生成麻将游戏状态描述"""
        parts = []
        state = room_data.get('room_state', 'lobby')

        if state == 'lobby':
            parts.append('在麻将大厅')
        elif state == 'waiting':
            room_id = room_data.get('room_id', '')
            players = room_data.get('players', [])
            names = [p['name'] for p in players if p.get('name')]
            parts.append(f"麻将房间 #{room_id}")
            parts.append(f"玩家: {', '.join(names)}")
            parts.append('等待开始')
        elif state == 'playing':
            position = room_data.get('position', '?')
            hand_chinese = room_data.get('hand_chinese', room_data.get('hand', []))
            my_turn = room_data.get('my_turn', False)
            wall = room_data.get('wall_remaining', 0)
            parts.append(f"座位: {position}")
            parts.append(f"手牌: {' '.join(hand_chinese)}")
            parts.append(f"牌山剩余: {wall}")
            if my_turn:
                parts.append('轮到你出牌')
                drawn = room_data.get('drawn')
                if drawn:
                    parts.append(f"摸到: {drawn}")
        elif state == 'finished':
            winner = room_data.get('winner')
            if winner:
                win_info = room_data.get('win_info', {})
                parts.append(f"和牌: {winner}")
                parts.append(f"{win_info.get('han', 0)}翻{win_info.get('fu', 0)}符")
            else:
                parts.append('流局')

        return ' | '.join(parts) if parts else '麻将游戏中'


register_handler(MahjongClientHandler())
