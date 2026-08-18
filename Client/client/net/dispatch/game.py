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


def _committed_room_target(screen, fallback: str) -> str:
    engine = getattr(screen, 'engine', None)
    primary_id = (
        engine.primary_id()
        if engine is not None and hasattr(engine, 'primary_id')
        else None
    )
    return (
        primary_id.removesuffix('-window')
        if isinstance(primary_id, str)
        else fallback
    )


def _try_show_room_doc(screen, selector: str, doc_renderable) -> bool:
    try:
        panel = screen.query_one(selector)
        if hasattr(panel, 'show_doc'):
            panel.show_doc(doc_renderable)
            return True
    except Exception:
        pass
    return False


def _show_room_doc(screen, rd: dict) -> None:
    game_type = rd.get('game_type', '')
    from ...protocol.renderer import get_renderer, render_doc
    renderer = get_renderer(game_type) if game_type else None
    if renderer and hasattr(renderer, 'render_doc'):
        doc_renderable = renderer.render_doc(rd['doc'])
    else:
        commands = getattr(renderer, 'doc_commands', None) if renderer else None
        doc_renderable = render_doc(rd['doc'], commands)

    selectors = ['#game-board', '#wait-chat']
    if rd.get('room_state') == 'waiting':
        selectors.insert(0, '#wait-chat')
    for selector in selectors:
        if _try_show_room_doc(screen, selector, doc_renderable):
            return


def _handle_room_doc(parsed, screen, st, rd: dict) -> None:
    _show_room_doc(screen, rd)
    if rd.get('room_state'):
        st.game_board.update_room(rd)
    if parsed.message:
        st.cmd.add_line(parsed.message)


def _close_room_docs(screen) -> None:
    for selector in ('#game-board', '#wait-chat'):
        try:
            panel = screen.query_one(selector)
            if getattr(panel, '_showing_doc', False):
                panel.close_doc()
        except Exception:
            pass


def _update_room_interaction(
    rd: dict,
    previous_target: str,
    target: str,
    app,
    screen,
    st,
):
    game_type = rd.get('game_type', '')
    if game_type:
        st.game_interaction.activate(game_type)
    handler = get_handler(game_type) if game_type else None
    if previous_target == 'game' and target == 'waiting':
        st.game_interaction.reset(game_type, notify=False)
    elif handler and hasattr(handler, 'on_room_update'):
        handler.on_room_update(rd, make_handler_ctx(st, app, screen))
    return handler


def _emit_companion_events(handler, previous_room: dict, rd: dict, st) -> None:
    if not handler or not hasattr(handler, 'companion_events'):
        return
    events = handler.companion_events(
        previous_room, rd, st.chat.player_name)
    if not events:
        return
    from ...companion import CompanionController
    controller = CompanionController.instance(st)
    for event in events:
        controller.observe_event(event)


def _commit_room_update(
    parsed,
    screen,
    st,
    rd: dict,
    target: str,
    crossing_primary: bool,
) -> bool:
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

        screen._switch_main_window(target, on_present=on_present)
        return bool(parsed.message)

    st.game_board.update_room(rd)
    try:
        indicator = screen.query_one('#tile-indicator')
        indicator.update(f" {tile_name} " if tile_name else '')
    except Exception:
        pass
    return False


def _on_room_update(parsed, app, screen, st):
    if not parsed.room_data:
        if parsed.message:
            st.cmd.add_line(parsed.message)
        return

    rd = parsed.room_data
    previous_room = st.game_board.room_data
    previous_target = _room_window_target(previous_room)
    target = _room_window_target(rd)
    committed_target = _committed_room_target(screen, previous_target)
    crossing_primary = target != committed_target

    if 'doc' in rd:
        _handle_room_doc(parsed, screen, st, rd)
        return
    if not crossing_primary:
        _close_room_docs(screen)

    handler = _update_room_interaction(
        rd, previous_target, target, app, screen, st,
    )
    _emit_companion_events(handler, previous_room, rd, st)
    message_deferred = _commit_room_update(
        parsed, screen, st, rd, target, crossing_primary,
    )
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
