"""麻将客户端事件处理器"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext, format_ai_rank_changes


class MahjongClientHandler:
    """麻将客户端事件处理器"""

    game_type = 'mahjong'

    _win_active: bool = False
    _win_data: dict | None = None
    _win_ctx: GameHandlerContext | None = None
    _win_step: int = 0
    _win_max: int = 0

    def get_input_prefix(self, location: str) -> str | None:
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
        self._win_active = False
        self._win_data = None
        self._win_ctx = None
        self._win_step = 0

    # ── 和牌渐进展示 ──

    def on_room_update(self, room_data: dict, ctx: GameHandlerContext):
        state = room_data.get('room_state', '')
        if (state == 'finished'
                and room_data.get('winner')
                and 'win_info' in room_data):
            self._start_win_reveal(room_data, ctx)
        else:
            self._win_active = False

    def _start_win_reveal(self, room_data: dict, ctx: GameHandlerContext):
        self._win_active = False  # 取消正在进行的链
        yaku = room_data.get('win_info', {}).get('yaku', [])
        # 总步数: 1 (手牌) + len(yaku) + 1 (总番) + 1 (分数变动) + 1 (下一局)
        self._win_max = len(yaku) + 4
        self._win_step = 0
        self._win_data = room_data
        self._win_ctx = ctx
        self._win_active = True
        # 初始 render 已经由 game_board 完成 (win_step=0: 显示手牌)
        # 1.5秒后开始显示第一条役
        ctx.set_timer(1.5, self._advance_win)

    def _advance_win(self):
        if not self._win_active or not self._win_data:
            return
        self._win_step += 1
        self._win_data['win_step'] = self._win_step
        ctx = self._win_ctx
        if ctx:
            ctx._widget_call('game_board', '_render_room', self._win_data)
        if self._win_step < self._win_max:
            delay = 0.8
            if ctx:
                ctx.set_timer(delay, self._advance_win)

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
                parts.append(f"{win_info.get('han', 0)}番{win_info.get('fu', 0)}符")
            else:
                parts.append('流局')
            rk = format_ai_rank_changes(room_data)
            if rk:
                parts.append(rk)

        return ' | '.join(parts) if parts else '麻将游戏中'


register_handler(MahjongClientHandler())
