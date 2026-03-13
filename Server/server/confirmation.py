"""大厅级待确认状态处理（rename/password/delete）"""

from .profile_commands import do_rename, do_change_password, do_delete_account


# ── pending-type handler registry ──────────────────────────────

def _pending_rename(lobby, player_name, player_data, cmd, raw_input, pending_data):
    if cmd == '/y':
        return do_rename(lobby, player_name, player_data, pending_data)
    return '已取消改名。'


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


def _pending_delete_start(lobby, player_name, player_data, cmd, raw_input, pending_data):
    if raw_input != player_name:
        return '用户名不匹配。已取消。'
    lobby.pending_confirms[player_name] = {'type': 'delete_password'}
    return '请输入你的密码：'


def _pending_delete_password(lobby, player_name, player_data, cmd, raw_input, pending_data):
    return do_delete_account(lobby, player_name, raw_input)


_PENDING_HANDLERS: dict[str, callable] = {
    'rename':           _pending_rename,
    'password_start':   _pending_password_start,
    'password_confirm': _pending_password_confirm,
    'delete_start':     _pending_delete_start,
    'delete_password':  _pending_delete_password,
}


# ── public entry ───────────────────────────────────────────────

def handle_lobby_pending(lobby, player_name, player_data, cmd, command, pending):
    """处理大厅级待确认状态（exit/rename/password/delete）

    返回 result 或 None（未匹配）。
    lobby: LobbyEngine 实例。
    """
    pending_type = pending.get('type') if isinstance(pending, dict) else pending
    pending_data = pending.get('data') if isinstance(pending, dict) else None

    handler = _PENDING_HANDLERS.get(pending_type)
    if handler is None:
        return None

    lobby.pending_confirms.pop(player_name, None)

    raw_input = command.strip()
    if raw_input.startswith('/'):
        raw_input = raw_input[1:]

    return handler(lobby, player_name, player_data, cmd, raw_input, pending_data)
