"""账号操作 — 修改密码、删除账号、待确认状态处理"""

from __future__ import annotations

from ..player.manager import PlayerManager


def do_change_password(player_name, new_password):
    """执行修改密码"""
    success = PlayerManager.change_password(player_name, new_password)
    if success:
        return '密码修改成功！'
    return '密码修改失败，请稍后重试。'


def do_delete_account(lobby, player_name, password):
    """执行删除账号"""
    if not PlayerManager.verify_password(player_name, password):
        return '密码错误。账号删除已取消。'

    with lobby._lock:
        for game_id, engine in lobby.game_engines.items():
            if engine.get_player_room(player_name):
                engine.leave_room(player_name)

        success = PlayerManager.delete_player(player_name)
        if success:
            lobby.online_players.pop(player_name, None)
            lobby.player_locations.pop(player_name, None)
            return {'action': 'account_deleted', 'message': '账号已删除。再见！'}
        return '删除账号失败，请稍后重试。'


# ── pending-type handler registry ──────────────────────────────

def _pending_password_start(lobby, player_name, player_data, cmd, raw_input, pending_data):
    if len(raw_input) < 6 or len(raw_input) > 20:
        return '密码长度需要在6-20个字符之间。已取消。'
    lobby.pending_confirms[player_name] = {
        'type': 'password_confirm',
        'data': raw_input
    }
    return '请再次输入新密码确认：'


def _pending_password_confirm(lobby, player_name, player_data, cmd, raw_input, pending_data):
    if raw_input != pending_data:
        return '两次输入的密码不一致。已取消。'
    return do_change_password(player_name, pending_data)


_PENDING_HANDLERS: dict[str, callable] = {
    'password_start':   _pending_password_start,
    'password_confirm': _pending_password_confirm,
}


# ── public entry ───────────────────────────────────────────────

def handle_lobby_pending(lobby, player_name, player_data, cmd, command, pending):
    """处理大厅级待确认状态（password）"""
    pending_type = pending.get('type') if isinstance(pending, dict) else pending
    pending_data = pending.get('data') if isinstance(pending, dict) else None

    handler = _PENDING_HANDLERS.get(pending_type)
    if handler is None:
        return None

    lobby.pending_confirms.pop(player_name, None)

    raw_input = command.strip()

    return handler(lobby, player_name, player_data, cmd, raw_input, pending_data)
