"""飞行棋客户端无状态处理器。"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext
from ...window_engine import Option, move_option_index

_BOARD_MENUS = {'选择棋子'}


def _default_state() -> dict:
    return {
        'btn_cursor': 0,
        'buttons': [],
        'my_turn': False,
        'playing': False,
        'viewer_color': None,
        'move_previews': {},
        'valid_moves': [],
        'last_move_seq': 0,
        'anim_path': [],
        'anim_idx': 0,
        'anim_color': None,
        'anim_piece': None,
        'anim_override': None,
        'anim_token': 0,
        'blink_on': True,
        'blink_running': False,
        'blink_token': 0,
        'pending_room_data': None,
    }


class LudoHandler:
    """将飞行棋事件转换为当前 ModuleStateManager 的 State 变更。"""

    game_type = 'ludo'
    _ANIM_STEP = 0.35
    _BLINK_STEP = 0.55

    def companion_events(
        self, previous: dict, current: dict, player: str,
    ) -> list[str]:
        """Declare Ludo events important enough for proactive attention."""
        events = []
        old_state = previous.get('room_state', '')
        state = current.get('room_state', '')
        if old_state != 'finished' and state == 'finished':
            rankings = current.get('rankings', [])
            events.append(
                "玩家获得飞行棋第一名"
                if rankings and rankings[0] == player
                else "飞行棋对局结束")
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
            state['buttons'] = items
            state['btn_cursor'] = 0
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
        buttons = state['buttons']
        if direction == 'left' and buttons:
            state['btn_cursor'] = move_option_index(
                (Option(str(index), item.get("label", ""), data=item)
                 for index, item in enumerate(buttons)),
                state['btn_cursor'],
                -1,
            )
        elif direction == 'right' and buttons:
            state['btn_cursor'] = move_option_index(
                (Option(str(index), item.get("label", ""), data=item)
                 for index, item in enumerate(buttons)),
                state['btn_cursor'],
                1,
            )
        elif direction == 'enter':
            self._on_enter(state, ctx)
            return
        ctx.state.game_interaction.replace(self.game_type, state)

    def _on_enter(self, state: dict, ctx: GameHandlerContext) -> None:
        if not state['my_turn']:
            return
        buttons = state['buttons']
        if buttons:
            command = buttons[state['btn_cursor']].get('command', '')
            if command:
                ctx.send_command(command)
                state['buttons'] = [
                    {'label': '掷骰子', 'command': '/roll'},
                ]
                state['btn_cursor'] = 0
                ctx.state.game_interaction.replace(self.game_type, state)
                return
        ctx.send_command('/roll')

    def on_room_update(self, room_data: dict,
                       ctx: GameHandlerContext) -> None:
        if room_data.get('room_state', '') != 'playing':
            ctx.state.game_interaction.reset(self.game_type)
            return

        interaction = ctx.state.game_interaction
        state = self._snapshot(ctx)
        player_name = ctx.state.chat.player_name
        state['playing'] = True
        state['viewer_color'] = (
            room_data.get('player_colors', {}).get(player_name))

        last_move = room_data.get('last_move')
        new_animation = (
            last_move
            and last_move.get('seq', 0) > state['last_move_seq']
            and last_move.get('color')
            and last_move.get('piece_idx') is not None
            and last_move.get('path')
        )
        if new_animation:
            state.update({
                'last_move_seq': last_move['seq'],
                'buttons': [{'label': '掷骰子', 'command': '/roll'}],
                'btn_cursor': 0,
                'move_previews': {},
                'valid_moves': [],
                'anim_path': last_move['path'],
                'anim_idx': 0,
                'anim_color': last_move['color'],
                'anim_piece': last_move['piece_idx'],
                'anim_token': state['anim_token'] + 1,
                'blink_running': False,
                'blink_token': state['blink_token'] + 1,
                'blink_on': True,
                'pending_room_data': room_data,
            })
            self._set_anim_override(state)
            interaction.replace(self.game_type, state)
            generation = interaction.generation(self.game_type)
            token = state['anim_token']
            ctx.set_timer(
                self._ANIM_STEP,
                lambda: self._tick_animation(
                    interaction, generation, token, player_name,
                    ctx.set_timer),
            )
            return

        if state['anim_path']:
            state['pending_room_data'] = room_data
            interaction.replace(self.game_type, state)
            return

        self._apply_room_data(
            interaction, state, room_data, player_name, ctx.set_timer)

    def _apply_room_data(self, interaction, state: dict, room_data: dict,
                         player_name: str, set_timer) -> None:
        state['my_turn'] = (
            room_data.get('current_player', '') == player_name)
        state['move_previews'] = room_data.get('move_previews', {}) or {}
        state['valid_moves'] = room_data.get('valid_moves', []) or []

        start_blink = bool(
            state['move_previews'] and not state['blink_running'])
        if start_blink:
            state['blink_running'] = True
            state['blink_on'] = True
            state['blink_token'] += 1

        pending = room_data.get('pending_move', False)
        showing_pieces = (
            pending and state['my_turn'] and state['buttons']
            and state['buttons'][0].get('command') != '/roll'
        )
        if not showing_pieces:
            state['buttons'] = [
                {'label': '掷骰子', 'command': '/roll'},
            ]
            state['btn_cursor'] = 0
        elif state['btn_cursor'] >= len(state['buttons']):
            state['btn_cursor'] = max(0, len(state['buttons']) - 1)

        interaction.replace(self.game_type, state)
        if start_blink:
            generation = interaction.generation(self.game_type)
            token = state['blink_token']
            set_timer(
                self._BLINK_STEP,
                lambda: self._tick_blink(
                    interaction, generation, token, set_timer),
            )

    @staticmethod
    def _set_anim_override(state: dict) -> None:
        path = state['anim_path']
        index = state['anim_idx']
        if path and 0 <= index < len(path):
            state['anim_override'] = {
                'color': state['anim_color'],
                'piece_idx': state['anim_piece'],
                'snapshot': path[index],
            }
        else:
            state['anim_override'] = None

    def _tick_animation(self, interaction, generation: int, token: int,
                        player_name: str, set_timer) -> None:
        if not interaction.is_current(self.game_type, generation):
            return
        state = interaction.snapshot(self.game_type)
        if not state or state['anim_token'] != token or not state['anim_path']:
            return

        state['anim_idx'] += 1
        if state['anim_idx'] < len(state['anim_path']):
            self._set_anim_override(state)
            interaction.replace(self.game_type, state)
            set_timer(
                self._ANIM_STEP,
                lambda: self._tick_animation(
                    interaction, generation, token, player_name, set_timer),
            )
            return

        pending = state['pending_room_data']
        state.update({
            'anim_path': [],
            'anim_idx': 0,
            'anim_color': None,
            'anim_piece': None,
            'anim_override': None,
            'pending_room_data': None,
        })
        if pending:
            self._apply_room_data(
                interaction, state, pending, player_name, set_timer)
        else:
            interaction.replace(self.game_type, state)

    def _tick_blink(self, interaction, generation: int, token: int,
                    set_timer) -> None:
        if not interaction.is_current(self.game_type, generation):
            return
        state = interaction.snapshot(self.game_type)
        if not state or state['blink_token'] != token:
            return
        if not state['move_previews']:
            state['blink_running'] = False
            state['blink_on'] = True
            interaction.replace(self.game_type, state)
            return
        state['blink_on'] = not state['blink_on']
        interaction.replace(self.game_type, state)
        set_timer(
            self._BLINK_STEP,
            lambda: self._tick_blink(
                interaction, generation, token, set_timer),
        )


register_handler(LudoHandler())
