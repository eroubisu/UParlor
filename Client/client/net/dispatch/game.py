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
    from ...companion import CompanionController
    CompanionController.instance(st).observe_event(
        f"{from_name} 发来 {game} 游戏邀请")
    screen.update_badges()


def _on_game_invite_result(parsed, app, screen, st):
    st.notify.mark_game_invite(parsed.from_name, parsed.game, parsed.status)
    screen.update_badges()


def _on_room_update(parsed, app, screen, st):
    message_deferred = False
    if parsed.room_data:
        rd = parsed.room_data
        previous_room = st.game_board.room_data
        previous_target = _room_window_target(previous_room)
        target = _room_window_target(rd)
        primary_id = None
        engine = getattr(screen, 'engine', None)
        if engine is not None and hasattr(engine, 'primary_id'):
            primary_id = engine.primary_id()
        committed_target = (
            primary_id.removesuffix('-window')
            if isinstance(primary_id, str)
            else previous_target
        )
        crossing_primary = target != committed_target
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
        # 同窗口更新可直接关闭帮助；跨主窗口时旧帧保持原样。
        if not crossing_primary:
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
        if game_type:
            st.game_interaction.activate(game_type)
        crossing_to_waiting = (
            previous_target == 'game' and target == 'waiting'
        )
        handler = get_handler(game_type) if game_type else None
        if crossing_to_waiting:
            st.game_interaction.reset(game_type, notify=False)
        elif handler and hasattr(handler, 'on_room_update'):
            ctx = make_handler_ctx(st, app, screen)
            handler.on_room_update(rd, ctx)
        if handler and hasattr(handler, 'companion_events'):
            events = handler.companion_events(
                previous_room, rd, st.chat.player_name)
            if events:
                from ...companion import CompanionController
                controller = CompanionController.instance(st)
                for event in events:
                    controller.observe_event(event)
        tile_name = rd.get('tile_name', '')
        if crossing_primary and hasattr(screen, '_switch_main_window'):
            st.game_board.update_room(rd, notify=False)
            if parsed.commands is not None:
                screen._prepare_main_window(target, parsed.commands)
            def on_present() -> None:
                screen._commit_main_window_context(
                    parsed.commands, parsed.location,
                    parsed.location_path, tile_name,
                )
                if parsed.message:
                    st.cmd.add_line(parsed.message)
            message_deferred = bool(parsed.message)
            screen._switch_main_window(target, on_present=on_present)
        else:
            st.game_board.update_room(rd)
            try:
                indicator = screen.query_one('#tile-indicator')
                indicator.update(f" {tile_name} " if tile_name else '')
            except Exception:
                pass
    if parsed.message and not message_deferred:
        st.cmd.add_line(parsed.message)


def _on_room_leave(parsed, app, screen, st):
    st.game_interaction.reset(notify=False)
    st.game_board.clear(notify=False)
    if hasattr(parsed, 'commands'):
        screen._prepare_main_window('lobby', parsed.commands)
    on_present = lambda: screen._commit_main_window_context(
        parsed.commands, parsed.location, parsed.location_path,
    )
    if hasattr(screen, '_switch_main_window'):
        screen._switch_main_window('lobby', on_present=on_present)


def _on_game_quit(parsed, app, screen, st):
    """Keep the final game frame until the waiting-room update is ready."""


def _room_window_target(room_data: dict) -> str:
    room_state = room_data.get('room_state', '') if room_data else ''
    if room_state == 'waiting':
        return 'waiting'
    if room_state in ('playing', 'finished'):
        return 'game'
    return 'lobby'


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
    GameQuit: _on_game_quit,
    GameEvent: _on_game_event,
}
