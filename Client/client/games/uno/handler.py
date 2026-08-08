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
        'active': True,
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
            state['active'] = True
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
        if (
            not state['playing']
            or not state['active']
            or not state['my_turn']
        ):
            return

        room_data = ctx.state.game_board.room_data or {}
        n_cards = len(room_data.get('my_cards', []))
        playable = room_data.get('playable', [])
        buttons = state['buttons']
        row = state['row']

        if direction == 'left':
            if row == 0 and playable:
                state['hand_cursor'] = self._move_card_cursor(
                    state['hand_cursor'], playable, -1,
                )
            elif row == 1 and buttons:
                state['btn_cursor'] = move_option_index(
                    (Option(str(index), item.get("label", ""), data=item)
                     for index, item in enumerate(buttons)),
                    state['btn_cursor'],
                    -1,
                )
        elif direction == 'right':
            if row == 0 and playable:
                state['hand_cursor'] = self._move_card_cursor(
                    state['hand_cursor'], playable, 1,
                )
            elif row == 1 and buttons:
                state['btn_cursor'] = move_option_index(
                    (Option(str(index), item.get("label", ""), data=item)
                     for index, item in enumerate(buttons)),
                    state['btn_cursor'],
                    1,
                )
        elif direction == 'down' and row == 0:
            next_cursor = self._vertical_card_cursor(
                state['hand_cursor'], playable,
                state['cards_per_row'], 1,
            )
            if next_cursor is not None:
                state['hand_cursor'] = next_cursor
            elif buttons:
                state['row'] = 1
        elif direction == 'up':
            if row == 1 and playable:
                state['row'] = 0
            elif row == 0:
                next_cursor = self._vertical_card_cursor(
                    state['hand_cursor'], playable,
                    state['cards_per_row'], -1,
                )
                if next_cursor is not None:
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
                state['selected'] = cursor
                self._update_play_label(state, room_data)
                if state['buttons']:
                    state['row'] = 1
                    state['btn_cursor'] = 0
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
        state['active'] = False
        ctx.state.game_interaction.replace(self.game_type, state)

    def on_room_update(self, room_data: dict,
                       ctx: GameHandlerContext) -> None:
        if room_data.get('room_state', '') != 'playing':
            ctx.state.game_interaction.reset(self.game_type)
            return

        state = self._snapshot(ctx)
        my_cards = room_data.get('my_cards', [])
        state['playing'] = True
        if state['color_mode'] and not state['active']:
            state['color_mode'] = False
        state['active'] = True
        state['my_turn'] = (
            room_data.get('current_player', '') == ctx.state.chat.player_name)
        playable = room_data.get('playable', [])

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

        if state['my_turn'] and playable:
            if state['hand_cursor'] not in playable:
                state['hand_cursor'] = playable[0]
            if state['row'] not in (0, 1):
                state['row'] = 0
        elif state['my_turn'] and state['buttons']:
            state['row'] = 1
        else:
            state['row'] = -1
            state['hand_cursor'] = 0
            state['selected'] = -1
        if state['selected'] >= len(my_cards):
            state['selected'] = -1
        if state['btn_cursor'] >= len(state['buttons']):
            state['btn_cursor'] = max(0, len(state['buttons']) - 1)
        ctx.state.game_interaction.replace(self.game_type, state)

    @staticmethod
    def _move_card_cursor(current: int, playable: list[int], delta: int) -> int:
        if not playable:
            return current
        try:
            position = playable.index(current)
        except ValueError:
            return playable[0]
        return playable[max(0, min(len(playable) - 1, position + delta))]

    @staticmethod
    def _vertical_card_cursor(
        current: int, playable: list[int], cards_per_row: int, direction: int,
    ) -> int | None:
        current_row = current // cards_per_row
        candidates = [
            index for index in playable
            if (
                index // cards_per_row > current_row
                if direction > 0
                else index // cards_per_row < current_row
            )
        ]
        if not candidates:
            return None
        target = current + direction * cards_per_row
        return min(candidates, key=lambda index: abs(index - target))

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
