"""开放世界客户端处理器 — 处理世界事件、导航移动、切换面板"""

from __future__ import annotations

from ..protocol.handler import register_handler, GameHandlerContext

# 多步移动定时器间隔（与服务端冷却匹配）
_MOVE_INTERVAL = 0.32


class WorldClientHandler:
    """开放世界客户端事件处理器"""

    game_type = 'world'

    def __init__(self):
        self._pending_moves: int = 0
        self._pending_move_dir: str = ''
        self._pending_ctx: GameHandlerContext | None = None
        self._move_timer = None

    # ── 导航移动状态机 ──

    _NAV_DIR_MAP = {
        'down': '/j', 'up': '/k', 'left': '/h', 'right': '/l',
    }

    def on_nav(self, direction: str, count: int, ctx: GameHandlerContext):
        """处理导航键：hjkl 移动角色，enter 进入门口"""
        if direction == 'enter':
            self._cancel_pending_moves(ctx)
            room_data = ctx.state.game_board.room_data
            if room_data and room_data.get('door'):
                ctx.send_command('/enter')
            return
        cmd = self._NAV_DIR_MAP.get(direction)
        if cmd:
            self._send_move(cmd, count, ctx)

    def on_nav_cancel(self, ctx: GameHandlerContext):
        """取消待执行的多步移动"""
        self._cancel_pending_moves(ctx)

    def _send_move(self, direction: str, count: int, ctx: GameHandlerContext):
        """发起多步移动：立即执行第一步，后续步用定时器快速续发"""
        self._cancel_pending_moves(ctx)
        self._pending_moves = count - 1
        self._pending_move_dir = direction
        self._pending_ctx = ctx
        ctx.send_command(direction)
        if self._pending_moves > 0:
            self._move_timer = ctx.set_timer(_MOVE_INTERVAL, self._tick_pending_move)

    def _tick_pending_move(self):
        """定时器续发：按服务端冷却节奏连续发送"""
        self._move_timer = None
        ctx = self._pending_ctx
        if self._pending_moves > 0 and self._pending_move_dir and ctx:
            self._pending_moves -= 1
            ctx.send_command(self._pending_move_dir)
            if self._pending_moves > 0:
                self._move_timer = ctx.set_timer(_MOVE_INTERVAL, self._tick_pending_move)

    def on_room_update(self, room_data: dict, ctx: GameHandlerContext):
        """地图更新 — 门口提示"""
        door = room_data.get('door')
        if door:
            from ..panels.game_board import GameBoardPanel
            board = ctx.get_module('game_board')
            if isinstance(board, GameBoardPanel):
                board.show_toast(f"[{door['name']}] enter 进入")

    def _cancel_pending_moves(self, ctx: GameHandlerContext):
        self._pending_moves = 0
        self._pending_move_dir = ''
        self._pending_ctx = None
        if self._move_timer:
            self._move_timer.stop()
            self._move_timer = None

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        """处理世界特有事件"""
        if event == 'select_menu':
            ctx.show_select_menu(
                title=data.get('title', ''),
                items=data.get('items', []),
                empty_msg=data.get('empty_msg', ''),
            )
            return True

        if event == 'dm_player':
            target = data.get('target', '')
            if target:
                ctx.state.chat.open_private_tab(target)
                ctx.state.cmd.add_line("已打开私聊窗口")
            return True

        if event in ('player_moved', 'player_entered', 'player_left'):
            self._handle_player_delta(event, data, ctx)
            return True

        if event == 'follow_started':
            ctx.state.game_board.following = data.get('target', '')
            return True

        if event == 'follow_cancelled':
            ctx.state.game_board.following = ''
            return True

        return False

    def _handle_player_delta(self, event: str, data: dict, ctx: GameHandlerContext):
        """增量更新其他玩家位置 — 修改缓存的 room_data 并重新渲染"""
        room_data = ctx.state.game_board.room_data
        if not room_data:
            return
        map_view = room_data.get('map')
        if not map_view:
            return
        players = map_view.setdefault('players', [])
        name = data.get('name', '')

        if event == 'player_left':
            map_view['players'] = [p for p in players if p.get('name') != name]
        elif event == 'player_entered':
            # 去重后添加
            map_view['players'] = [p for p in players if p.get('name') != name]
            map_view['players'].append({
                'x': data.get('x', 0), 'y': data.get('y', 0), 'name': name,
            })
        elif event == 'player_moved':
            found = False
            for p in players:
                if p.get('name') == name:
                    p['x'] = data.get('x', 0)
                    p['y'] = data.get('y', 0)
                    found = True
                    break
            if not found:
                players.append({
                    'x': data.get('x', 0), 'y': data.get('y', 0), 'name': name,
                })

        # 触发重新渲染（不经过 update_room 避免替换 room_data）
        from ..panels.game_board import GameBoardPanel
        board = ctx.get_module('game_board')
        if isinstance(board, GameBoardPanel):
            board._render_room(room_data)

    # ── AI 感知 ──

    def ai_describe(self, room_data: dict) -> str:
        """为 AI 旅伴生成人类可读的世界状态描述"""
        parts = []
        map_view = room_data.get('map', {})
        map_name = map_view.get('map_name', '')
        if map_name:
            parts.append(f"当前地图: {map_name}")
        pos = room_data.get('pos')
        if pos:
            parts.append(f"坐标: ({pos[0]}, {pos[1]})")
        # 门口
        door = room_data.get('door')
        if door:
            parts.append(f"门口: {door.get('name', '未知')}")
        # 视野内 NPC
        npcs = map_view.get('npcs', [])
        if npcs:
            npc_names = [n.get('name', '?') for n in npcs[:8]]
            parts.append(f"附近NPC: {', '.join(npc_names)}")
        # 视野内其他玩家
        players = map_view.get('players', [])
        if players:
            names = [p.get('name', '?') for p in players[:8]]
            parts.append(f"附近玩家: {', '.join(names)}")
        return ' | '.join(parts) if parts else '在世界中探索'

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        """进入开放世界 — 确保 game_board 面板显示"""
        ctx.ensure_panel('game_board')

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        """离开开放世界"""


register_handler(WorldClientHandler())
