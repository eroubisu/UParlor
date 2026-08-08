"""UNO 客户端无状态处理器。"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext
from ...window_engine import Option, move_option_index

_BOARD_MENUS = {'出牌', '选择颜色'}


def _default_state() -> dict:
    return {
        'hand_cursor': 0,
        'btn_cursor': 0,
        'row': 0,
        'selected': -1,
        'buttons': [],
        'color_mode': False,
        'my_turn': False,
        'playing': False,
        'cards_per_row': 13,
    }


class UnoHandler:
    """将 UNO 事件转换为当前 ModuleStateManager 的 State 变更。"""

    game_type = 'uno'

    def companion_events(
        self, previous: dict, current: dict, player: str,
    ) -> list[str]:
        """Declare UNO events important enough for proactive attention."""
        events = []
        old_state = previous.get('room_state', '')
        state = current.get('room_state', '')
        if old_state != 'finished' and state == 'finished':
            winner = current.get('winner', '')
            events.append(
                "玩家赢得 UNO 对局"
                if winner == player else "UNO 对局结束")
        return events

    def get_input_prefix(self, location: str) -> str | None:
        return None

    def _snapshot(self, ctx: GameHandlerContext) -> dict:
        return (
            ctx.state.game_interaction.snapshot(self.game_type)
            or _default_state()
        )

    def handle_event(self, event: str, data: dict,
                     ctx: GameHandlerContext) -> bool:
        if event != 'select_menu':
            return False
        title = data.get('title', '')
        items = data.get('items', [])
        if title in _BOARD_MENUS:
            state = self._snapshot(ctx)
            state['playing'] = True
            state['btn_cursor'] = 0
            if title == '选择颜色':
                state.update({
                    'color_mode': True,
                    'my_turn': True,
                    'buttons': items,
                    'row': 1,
                })
            else:
                buttons = [
                    item for item in items
                    if not item.get('command', '').startswith('/play')
                ]
                buttons.insert(
                    0, {'label': '出牌', 'command': '_play_selected'})
                state.update({'color_mode': False, 'buttons': buttons})
            ctx.state.game_interaction.replace(self.game_type, state)
            return True
        ctx.show_select_menu(
            title=title,
            items=items,
            empty_msg=data.get('empty_msg', ''),
        )
        return True

    def on_nav(self, direction: str, ctx: GameHandlerContext) -> None:
        state = self._snapshot(ctx)
        if not state['playing']:
            return

        room_data = ctx.state.game_board.room_data or {}
        n_cards = len(room_data.get('my_cards', []))
        buttons = state['buttons']
        row = state['row']

        if direction == 'left':
            if row == 0 and n_cards:
                state['hand_cursor'] = max(0, state['hand_cursor'] - 1)
            elif row == 1 and buttons:
                state['btn_cursor'] = move_option_index(
                    (Option(str(index), item.get("label", ""), data=item)
                     for index, item in enumerate(buttons)),
                    state['btn_cursor'],
                    -1,
                )
        elif direction == 'right':
            if row == 0 and n_cards:
                state['hand_cursor'] = min(
                    n_cards - 1, state['hand_cursor'] + 1)
            elif row == 1 and buttons:
                state['btn_cursor'] = move_option_index(
                    (Option(str(index), item.get("label", ""), data=item)
                     for index, item in enumerate(buttons)),
                    state['btn_cursor'],
                    1,
                )
        elif direction == 'down' and row == 0:
            next_cursor = state['hand_cursor'] + state['cards_per_row']
            if next_cursor < n_cards:
                state['hand_cursor'] = next_cursor
            elif buttons:
                state['row'] = 1
        elif direction == 'up':
            if row == 1 and n_cards:
                state['row'] = 0
            elif row == 0:
                next_cursor = state['hand_cursor'] - state['cards_per_row']
                if next_cursor >= 0:
                    state['hand_cursor'] = next_cursor
        elif direction == 'enter':
            self._on_enter(state, room_data, ctx)
            return

        ctx.state.game_interaction.replace(self.game_type, state)

    def _on_enter(self, state: dict, room_data: dict,
                  ctx: GameHandlerContext) -> None:
        if not state['my_turn']:
            return
        if state['row'] == 0:
            cursor = state['hand_cursor']
            if cursor in set(room_data.get('playable', [])):
                state['selected'] = (
                    -1 if state['selected'] == cursor else cursor)
                self._update_play_label(state, room_data)
                ctx.state.game_interaction.replace(self.game_type, state)
            return

        buttons = state['buttons']
        if state['row'] != 1 or not buttons:
            return
        command = buttons[state['btn_cursor']].get('command', '')
        if command == '_play_selected':
            selected = state['selected']
            if selected < 0:
                return
            need_uno = len(room_data.get('my_cards', [])) == 2
            ctx.send_command(f'/play {selected}')
            if need_uno:
                ctx.send_command('/uno')
        elif command:
            ctx.send_command(command)
        else:
            return
        ctx.state.game_interaction.reset(self.game_type)

    def on_room_update(self, room_data: dict,
                       ctx: GameHandlerContext) -> None:
        if room_data.get('room_state', '') != 'playing':
            ctx.state.game_interaction.reset(self.game_type)
            return

        state = self._snapshot(ctx)
        my_cards = room_data.get('my_cards', [])
        state['playing'] = True
        state['my_turn'] = (
            room_data.get('current_player', '') == ctx.state.chat.player_name)

        if not state['color_mode']:
            if state['my_turn']:
                if room_data.get('draw_play'):
                    state['buttons'] = [
                        {'label': '出牌', 'command': '_play_selected'},
                        {'label': '跳过', 'command': '/pass'},
                    ]
                else:
                    self._build_turn_buttons(state, room_data)
            else:
                state['buttons'] = [
                    {'label': '出牌', 'command': '_play_selected'},
                    {'label': '摸牌', 'command': '/draw'},
                ]

        if my_cards:
            state['hand_cursor'] = min(
                state['hand_cursor'], len(my_cards) - 1)
        else:
            state['hand_cursor'] = 0
        if state['selected'] >= len(my_cards):
            state['selected'] = -1
        if state['btn_cursor'] >= len(state['buttons']):
            state['btn_cursor'] = max(0, len(state['buttons']) - 1)
        ctx.state.game_interaction.replace(self.game_type, state)

    def _build_turn_buttons(self, state: dict, room_data: dict) -> None:
        buttons = [
            {'label': '出牌', 'command': '_play_selected'},
            {'label': '摸牌', 'command': '/draw'},
        ]
        if room_data.get('challengeable'):
            buttons.append({'label': '挑战', 'command': '/challenge'})
        if [b['label'] for b in state['buttons']] != [
                b['label'] for b in buttons]:
            state['buttons'] = buttons
            state['btn_cursor'] = 0
        self._update_play_label(state, room_data)

    @staticmethod
    def _update_play_label(state: dict, room_data: dict) -> None:
        buttons = state['buttons']
        if not buttons or buttons[0].get('command') != '_play_selected':
            return
        buttons[0]['label'] = (
            'uno!' if len(room_data.get('my_cards', [])) == 2
            and state['selected'] >= 0 else '出牌'
        )


register_handler(UnoHandler())
