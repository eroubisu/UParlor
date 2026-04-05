"""开放世界客户端处理器 — 处理世界事件、导航移动、切换面板"""

from __future__ import annotations

from ...protocol.handler import register_handler, GameHandlerContext

# 移动定时器间隔：服务端通过 room_data.move_cd 下发实际冷却，此为回退默认值
_DEFAULT_MOVE_CD = 0.32
# 定时器 buffer：保证命令在服务端冷却之后到达，消除时钟漂移
_TIMER_BUFFER = 0.02


class WorldClientHandler:
    """开放世界客户端事件处理器"""

    game_type = 'world'

    def __init__(self):
        self._pending_moves: int = 0
        self._pending_move_dir: str = ''
        self._pending_ctx: GameHandlerContext | None = None
        self._move_timer = None
        self._hold_active: bool = False
        self._move_cd: float = _DEFAULT_MOVE_CD

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
        """发起移动：多步(count>1)逐步续发，单步持续按键节流续发"""
        if count > 1:
            # 显式多步：立即首步 + 定时续发剩余步
            self._cancel_pending_moves(ctx)
            self._pending_moves = count - 1
            self._pending_move_dir = direction
            self._pending_ctx = ctx
            ctx.send_command(direction)
            self._move_timer = ctx.set_timer(self._move_cd + _TIMER_BUFFER, self._tick_pending_move)
            return
        # 单步：同方向定时器已运行则仅标记持续
        if self._move_timer and self._pending_move_dir == direction:
            self._hold_active = True
            return
        # 新方向或首次：立即发送 + 启动持续定时器
        self._cancel_pending_moves(ctx)
        self._pending_move_dir = direction
        self._pending_ctx = ctx
        self._hold_active = False
        ctx.send_command(direction)
        self._move_timer = ctx.set_timer(self._move_cd + _TIMER_BUFFER, self._tick_hold)

    def _tick_pending_move(self):
        """定时器续发：按服务端冷却节奏连续发送"""
        self._move_timer = None
        ctx = self._pending_ctx
        if self._pending_moves > 0 and self._pending_move_dir and ctx:
            self._pending_moves -= 1
            ctx.send_command(self._pending_move_dir)
            if self._pending_moves > 0:
                self._move_timer = ctx.set_timer(self._move_cd + _TIMER_BUFFER, self._tick_pending_move)

    def _tick_hold(self):
        """持续按键续发：松键（无新事件刷新标记）自动停止"""
        self._move_timer = None
        ctx = self._pending_ctx
        if not self._hold_active or not ctx:
            return
        self._hold_active = False
        ctx.send_command(self._pending_move_dir)
        self._move_timer = ctx.set_timer(self._move_cd + _TIMER_BUFFER, self._tick_hold)

    def on_room_update(self, room_data: dict, ctx: GameHandlerContext):
        """地图更新 — 门口提示 + 地块名 + 冷却同步"""
        cd = room_data.get('move_cd')
        if cd:
            self._move_cd = cd
        door = room_data.get('door')
        if door:
            from ...panels.game_board import GameBoardPanel
            board = ctx.get_module('game_board')
            if isinstance(board, GameBoardPanel):
                board.show_toast(f"\\[{door['name']}] enter 进入")


    def _cancel_pending_moves(self, ctx: GameHandlerContext):
        self._pending_moves = 0
        self._pending_move_dir = ''
        self._pending_ctx = None
        self._hold_active = False
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

        if event == 'npc_moved':
            self._handle_npc_moved(data, ctx)
            return True

        if event == 'follow_started':
            ctx.state.game_board.following = data.get('target', '')
            return True

        if event == 'follow_cancelled':
            ctx.state.game_board.following = ''
            return True

        if event == 'fish_cast':
            self._handle_fish_cast(data, ctx)
            return True

        if event == 'fish_result':
            self._cancel_fish_timer()
            return True

        if event == 'recall_start':
            self._handle_recall_start(data, ctx)
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
        from ...panels.game_board import GameBoardPanel
        board = ctx.get_module('game_board')
        if isinstance(board, GameBoardPanel):
            board._render_room(room_data)

    def _handle_npc_moved(self, data: list | dict, ctx: GameHandlerContext):
        """NPC 巡逻增量更新"""
        room_data = ctx.state.game_board.room_data
        if not room_data:
            return
        map_view = room_data.get('map')
        if not map_view:
            return
        npcs = map_view.get('npcs', [])
        ox, oy = map_view.get('offset', [0, 0])
        moves = data if isinstance(data, list) else [data]
        for m in moves:
            old_vx, old_vy = m['old'][0] - ox, m['old'][1] - oy
            new_vx, new_vy = m['new'][0] - ox, m['new'][1] - oy
            npc_name = m.get('name', '')
            # 按名称移除旧 NPC（同位置可能有多个不同 NPC）
            npcs = [n for n in npcs if n.get('name') != npc_name]
            # 添加到新位置（如果在视口内）
            view_w = len(map_view['tiles'][0]) if map_view.get('tiles') else 0
            view_h = len(map_view['tiles']) if map_view.get('tiles') else 0
            if 0 <= new_vx < view_w and 0 <= new_vy < view_h:
                npcs.append({
                    'x': new_vx, 'y': new_vy,
                    'char': m.get('char', '*'), 'color': m.get('color', '#b8b8b8'),
                    'name': m.get('name', ''),
                })
        map_view['npcs'] = npcs
        from ...panels.game_board import GameBoardPanel
        board = ctx.get_module('game_board')
        if isinstance(board, GameBoardPanel):
            board._render_room(room_data)

    # ── 钓鱼 ──

    _fish_timer = None

    def _handle_fish_cast(self, data: dict, ctx: GameHandlerContext):
        """钓鱼开始 — 设定本地计时器，到时提示鱼上钩"""
        self._cancel_fish_timer()
        bite_delay = data.get('bite_delay', 5.0)
        self._fish_timer = ctx.set_timer(bite_delay, lambda: self._on_fish_bite(ctx))

    def _on_fish_bite(self, ctx: GameHandlerContext):
        """鱼上钩了"""
        self._fish_timer = None
        from ...panels.game_board import GameBoardPanel
        board = ctx.get_module('game_board')
        if isinstance(board, GameBoardPanel):
            board.show_toast("鱼上钩了！快 /pull 收杆！")

    def _cancel_fish_timer(self):
        if self._fish_timer:
            self._fish_timer.stop()
            self._fish_timer = None

    # ── 回城 ──

    _recall_timer = None

    def _handle_recall_start(self, data: dict, ctx: GameHandlerContext):
        """回城开始 — 吟唱计时，到时发送完成指令"""
        self._cancel_recall_timer()
        channel_time = data.get('channel_time', 4.0)
        from ...panels.game_board import GameBoardPanel
        board = ctx.get_module('game_board')
        if isinstance(board, GameBoardPanel):
            board.show_toast(f"回城中... {int(channel_time)} 秒")
        self._recall_timer = ctx.set_timer(
            channel_time, lambda: self._on_recall_done(ctx))

    def _on_recall_done(self, ctx: GameHandlerContext):
        """吟唱结束 — 发送回城完成指令"""
        self._recall_timer = None
        ctx.send_command('/_recall_complete')

    def _cancel_recall_timer(self):
        if self._recall_timer:
            self._recall_timer.stop()
            self._recall_timer = None

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
        self._cancel_pending_moves(ctx)
        self._cancel_fish_timer()
        self._cancel_recall_timer()


register_handler(WorldClientHandler())
