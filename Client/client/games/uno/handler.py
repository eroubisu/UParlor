"""UNO Flip 客户端处理器"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext

# 棋盘内交互的 select_menu 标题（这些走棋盘内按钮，不走右侧面板）
_BOARD_MENUS = {'出牌', '选择颜色'}


class UnoHandler:
    """UNO Flip 客户端处理器"""

    game_type = 'uno'

    def __init__(self):
        self._hand_cursor: int = 0      # 手牌光标
        self._btn_cursor: int = 0       # 按钮光标
        self._row: int = 0              # 0=手牌行, 1=按钮行
        self._selected: int = -1        # 选中的牌索引 (-1=未选)
        self._buttons: list[dict] = []  # 当前按钮 [{'label','command'}]
        self._color_mode: bool = False  # 颜色选择模式
        self._my_turn: bool = False     # 是否是我的回合
        self._playing: bool = False     # 是否在游戏中
        self._cards_per_row: int = 13   # 每行牌数（由 game_board 同步）

    def get_input_prefix(self, location: str) -> str | None:
        return None

    @property
    def interaction_state(self) -> dict | None:
        """返回交互状态供 renderer 使用；非游戏中返回 None"""
        if not self._playing:
            return None
        return {
            'hand_cursor': self._hand_cursor,
            'btn_cursor': self._btn_cursor,
            'row': self._row,
            'selected': self._selected,
            'buttons': self._buttons,
            'color_mode': self._color_mode,
            'my_turn': self._my_turn,
        }

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        if event == 'select_menu':
            title = data.get('title', '')
            items = data.get('items', [])
            if title in _BOARD_MENUS:
                # 棋盘内交互
                self._setup_buttons(title, items)
                ctx.state.game_board._notify('update_room', ctx.state.game_board.room_data)
                return True
            # 其他 select_menu（邀请/踢人/抓人）→ 右侧面板
            ctx.show_select_menu(
                title=title, items=items,
                empty_msg=data.get('empty_msg', ''),
            )
            return True
        return False

    def _setup_buttons(self, title: str, items: list[dict]) -> None:
        """从 select_menu items 构建按钮列表"""
        self._playing = True  # select_menu 到达时确保交互态激活
        if title == '选择颜色':
            self._color_mode = True
            self._my_turn = True  # 选色仍是本玩家操作
            self._buttons = items
            self._btn_cursor = 0
            self._row = 1  # 自动聚焦到按钮行
        else:
            # 出牌菜单 → 构建操作按钮
            self._color_mode = False
            buttons = []
            for item in items:
                cmd = item.get('command', '')
                if cmd.startswith('/play'):
                    continue  # 出牌通过手牌选择，不做按钮
                buttons.append(item)
            # 始终在最前面加"出牌"按钮
            buttons.insert(0, {'label': '出牌', 'command': '_play_selected'})
            self._buttons = buttons
            self._btn_cursor = 0

    def on_nav(self, direction: str, ctx: GameHandlerContext) -> None:
        """棋盘聚焦时的导航"""
        if not self._playing:
            return

        rd = ctx.state.game_board.room_data or {}
        my_cards = rd.get('my_cards', [])
        n_cards = len(my_cards)

        if direction == 'left':
            if self._row == 0 and n_cards > 0:
                self._hand_cursor = max(0, self._hand_cursor - 1)
            elif self._row == 1 and self._buttons:
                self._btn_cursor = max(0, self._btn_cursor - 1)
        elif direction == 'right':
            if self._row == 0 and n_cards > 0:
                self._hand_cursor = min(n_cards - 1, self._hand_cursor + 1)
            elif self._row == 1 and self._buttons:
                self._btn_cursor = min(len(self._buttons) - 1, self._btn_cursor + 1)
        elif direction == 'down':
            if self._row == 0:
                # 多行手牌：向下一行
                cpr = self._cards_per_row
                next_cursor = self._hand_cursor + cpr
                if next_cursor < n_cards:
                    self._hand_cursor = next_cursor
                elif self._buttons:
                    # 最后一行 → 按钮行
                    self._row = 1
        elif direction == 'up':
            if self._row == 1 and n_cards > 0:
                self._row = 0
            elif self._row == 0:
                # 多行手牌：向上一行
                cpr = self._cards_per_row
                next_cursor = self._hand_cursor - cpr
                if next_cursor >= 0:
                    self._hand_cursor = next_cursor
        elif direction == 'enter':
            self._on_enter(ctx)
            return

        # 触发重绘
        ctx.state.game_board._notify('update_room', rd)

    def _on_enter(self, ctx: GameHandlerContext) -> None:
        if not self._my_turn:
            return
        rd = ctx.state.game_board.room_data or {}
        playable = set(rd.get('playable', []))

        if self._row == 0:
            # 手牌行：选中/取消
            if self._hand_cursor in playable:
                if self._selected == self._hand_cursor:
                    self._selected = -1  # 取消选中
                else:
                    self._selected = self._hand_cursor
                self._update_play_label(rd)
                ctx.state.game_board._notify('update_room', rd)
        elif self._row == 1 and self._buttons:
            # 按钮行：执行
            btn = self._buttons[self._btn_cursor]
            cmd = btn.get('command', '')
            if cmd == '_play_selected':
                if self._selected >= 0:
                    need_uno = len(rd.get('my_cards', [])) == 2
                    ctx.send_command(f'/play {self._selected}')
                    if need_uno:
                        ctx.send_command('/uno')
                    self._reset()
            elif cmd:
                ctx.send_command(cmd)
                self._reset()

    def _reset(self) -> None:
        """重置所有交互状态"""
        self._hand_cursor = 0
        self._btn_cursor = 0
        self._row = 0
        self._selected = -1
        self._buttons = []
        self._color_mode = False
        self._my_turn = False
        self._playing = False

    def on_room_update(self, room_data: dict, ctx: GameHandlerContext) -> None:
        """房间数据更新时：自动进入/退出交互态，校正光标"""
        my_cards = room_data.get('my_cards', [])
        state = room_data.get('room_state', '')
        current = room_data.get('current_player', '')
        my_name = ctx.state.chat._player_name

        # 非 playing → 清除交互态
        if state != 'playing':
            if self._playing:
                self._reset()
            return

        self._playing = True
        self._my_turn = current == my_name

        # 颜色选择模式中，不覆盖（等待玩家选色）
        if self._color_mode:
            return

        # 构建按钮（始终可见，非我回合只保留基础按钮）
        if self._my_turn:
            if room_data.get('draw_play'):
                self._buttons = [
                    {'label': '出牌', 'command': '_play_selected'},
                    {'label': '跳过', 'command': '/pass'},
                ]
            else:
                self._build_turn_buttons(room_data)
        else:
            self._buttons = [
                {'label': '出牌', 'command': '_play_selected'},
                {'label': '摸牌', 'command': '/draw'},
            ]

        # 校正光标越界
        if my_cards:
            self._hand_cursor = min(self._hand_cursor, len(my_cards) - 1)
        if self._selected >= len(my_cards):
            self._selected = -1
        if self._btn_cursor >= len(self._buttons):
            self._btn_cursor = max(0, len(self._buttons) - 1)

    def _build_turn_buttons(self, rd: dict) -> None:
        """从 room_data 构建当前回合的操作按钮"""
        buttons: list[dict] = []
        buttons.append({'label': '出牌', 'command': '_play_selected'})
        buttons.append({'label': '摸牌', 'command': '/draw'})

        if rd.get('challengeable'):
            buttons.append({'label': '挑战', 'command': '/challenge'})

        # 只在按钮内容变化时重置光标
        old_labels = [b['label'] for b in self._buttons]
        new_labels = [b['label'] for b in buttons]
        if old_labels != new_labels:
            self._buttons = buttons
            self._btn_cursor = 0

        # 手牌剩 2 张且已选中 → 出牌按钮显示 UNO
        self._update_play_label(rd)

    def _update_play_label(self, rd: dict) -> None:
        """根据手牌数和选中状态更新出牌按钮标签"""
        if not self._buttons or self._buttons[0].get('command') != '_play_selected':
            return
        my_cards = rd.get('my_cards', [])
        if len(my_cards) == 2 and self._selected >= 0:
            self._buttons[0]['label'] = 'uno!'
        else:
            self._buttons[0]['label'] = '出牌'


register_handler(UnoHandler())
