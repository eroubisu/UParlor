"""游戏相关消息分发 — 房间更新、对局事件、游戏列表"""

from __future__ import annotations

from ..messages import (
    RoomUpdate, RoomLeave, GameQuit,
    GameEvent, GameList, RoomList,
    GameInvite, GameInviteResult,
)
from ...protocol.handler import get_handler
from ._util import make_handler_ctx


def _on_game_list(parsed, app, screen, st):
    st.game_board.set_games(parsed.games)


def _on_room_list(parsed, app, screen, st):
    st.game_board.set_rooms(parsed.rooms)


def _on_game_invite(parsed, app, screen, st):
    inv = parsed.raw
    from_name = inv.get('from', '?')
    game = inv.get('game', '?')
    room_id = inv.get('room_id', '')
    expires_in = inv.get('expires_in', 300)
    st.notify.add_game_invite(from_name, game, room_id, expires_in)
    screen.update_badges()


def _on_game_invite_result(parsed, app, screen, st):
    st.notify.mark_game_invite(parsed.from_name, parsed.game, parsed.status)
    screen.update_badges()


def _on_room_update(parsed, app, screen, st):
    if parsed.room_data:
        rd = parsed.room_data
        # 帮助文档 → 路由到对应面板（游戏中→棋盘，等候室→聊天）
        if 'doc' in rd:
            game_type = rd.get('game_type', '')
            from ...protocol.renderer import get_renderer, render_doc
            renderer = get_renderer(game_type) if game_type else None
            if renderer and hasattr(renderer, 'render_doc'):
                doc_renderable = renderer.render_doc(rd['doc'])
            else:
                commands = getattr(renderer, 'doc_commands', None) if renderer else None
                doc_renderable = render_doc(rd['doc'], commands)
            shown = False
            # 优先尝试当前可见窗口中的面板
            rs = rd.get('room_state', '')
            if rs == 'waiting':
                try:
                    chat = screen.query_one('#wait-chat')
                    chat.show_doc(doc_renderable)
                    shown = True
                except Exception:
                    pass
            if not shown:
                try:
                    board = screen.query_one('#game-board')
                    if hasattr(board, 'show_doc'):
                        board.show_doc(doc_renderable)
                        shown = True
                except Exception:
                    pass
            if not shown:
                try:
                    chat = screen.query_one('#wait-chat')
                    chat.show_doc(doc_renderable)
                except Exception:
                    pass
            # 含 room_state 时仍需更新状态以触发窗口切换
            if rd.get('room_state'):
                st.game_board.update_room(rd)
            if parsed.message:
                st.cmd.add_line(parsed.message)
            return
        # 正常 room_update：如果面板在显示帮助，关闭
        try:
            board = screen.query_one('#game-board')
            if hasattr(board, '_showing_doc') and board._showing_doc:
                board.close_doc()
        except Exception:
            pass
        try:
            chat = screen.query_one('#wait-chat')
            if hasattr(chat, '_showing_doc') and chat._showing_doc:
                chat.close_doc()
        except Exception:
            pass
        # 先通知 handler 构建交互态，再更新 State 触发渲染
        game_type = rd.get('game_type', '')
        handler = get_handler(game_type) if game_type else None
        if handler and hasattr(handler, 'on_room_update'):
            ctx = make_handler_ctx(st, app, screen)
            handler.on_room_update(rd, ctx)
        st.game_board.update_room(rd)
        tile_name = rd.get('tile_name', '')
        try:
            indicator = screen.query_one('#tile-indicator')
            indicator.update(f" {tile_name} " if tile_name else '')
        except Exception:
            pass
    if parsed.message:
        st.cmd.add_line(parsed.message)


def _on_room_leave(parsed, app, screen, st):
    st.game_board.clear()
    if parsed.location:
        if hasattr(parsed, 'commands') and parsed.commands:
            from ...protocol.commands import set_commands
            set_commands(parsed.commands)
            screen._update_hint_bar()
        path = getattr(parsed, 'location_path', None)
        screen._update_location(parsed.location, path)


def _on_game_event(parsed, app, screen, st):
    handler = get_handler(parsed.game_type)
    if handler:
        ctx = make_handler_ctx(st, app, screen)
        handler.handle_event(parsed.event, parsed.data, ctx)


HANDLERS = {
    GameList: _on_game_list,
    RoomList: _on_room_list,
    GameInvite: _on_game_invite,
    GameInviteResult: _on_game_invite_result,
    RoomUpdate: _on_room_update,
    RoomLeave: _on_room_leave,
    GameQuit: _on_room_leave,
    GameEvent: _on_game_event,
}
