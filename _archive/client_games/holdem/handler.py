"""德州扑克客户端处理器"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext, format_ai_rank_changes


class HoldemHandler:
    """德州扑克客户端处理器"""

    game_type = 'holdem'

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
        state = room_data.get('room_state', 'lobby')
        if state == 'waiting':
            players = room_data.get('players', [])
            return f'德州扑克等待中，{len(players)}名玩家。'

        if state in ('playing', 'showdown'):
            phase = room_data.get('phase', 'preflop')
            pot = room_data.get('pot', 0)
            community = room_data.get('community', [])
            current = room_data.get('current_player', '')
            return (
                f'德州扑克进行中 ({phase})，'
                f'公共牌:{" ".join(community) if community else "无"}，'
                f'底池:{pot}，轮到:{current or "无"}'
            )

        if state == 'finished':
            winners = room_data.get('winners', [])
            if winners:
                w = winners[0]
                desc = f'德州扑克结束。{w["name"]}赢得{w["amount"]}({w["hand_name"]})'
            else:
                desc = '德州扑克已结束。'
            rk = format_ai_rank_changes(room_data)
            if rk:
                desc += f' {rk}'
            return desc

        return '德州扑克大厅。'

    def ai_on_room_update(
        self, old_data: dict | None, new_data: dict
    ) -> tuple[str, bool] | None:
        if not old_data:
            return None

        old_state = old_data.get('room_state', '')
        new_state = new_data.get('room_state', '')

        if old_state != 'finished' and new_state == 'finished':
            winners = new_data.get('winners', [])
            if winners:
                parts = [
                    f'{w["name"]}赢得{w["amount"]}' for w in winners
                ]
                return ('本局结束: ' + ', '.join(parts), True)

        old_phase = old_data.get('phase', '')
        new_phase = new_data.get('phase', '')
        if old_phase != new_phase and new_phase:
            phase_labels = {
                'preflop': '翻牌前', 'flop': '翻牌',
                'turn': '转牌', 'river': '河牌',
                'showdown': '摊牌',
            }
            return (f'进入{phase_labels.get(new_phase, new_phase)}阶段', False)

        return None


register_handler(HoldemHandler())
