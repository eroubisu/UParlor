"""开放世界客户端处理器 — 处理世界事件、切换面板"""

from __future__ import annotations

from ..protocol.handler import register_handler, GameHandlerContext


class WorldClientHandler:
    """开放世界客户端事件处理器"""

    game_type = 'world'

    def handle_event(self, event: str, data: dict, ctx: GameHandlerContext) -> bool:
        """处理世界特有事件"""
        if event == 'select_menu':
            from ..panels.game_board import GameBoardPanel
            board = ctx._get_module('game_board')
            if isinstance(board, GameBoardPanel):
                board.show_select_menu(
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
        board = ctx._get_module('game_board')
        if isinstance(board, GameBoardPanel):
            board._render_room(room_data)

    def on_enter_game(self, ctx: GameHandlerContext) -> None:
        """进入开放世界 — 确保 game_board 面板显示"""
        ctx.ensure_panel('game_board')

    def on_leave_game(self, ctx: GameHandlerContext) -> None:
        """离开开放世界"""
        pass


register_handler(WorldClientHandler())
