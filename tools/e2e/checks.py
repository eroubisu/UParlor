"""checks.py — 断言工具：读取 app/screen 状态"""

from __future__ import annotations


def _get_screen(app):
    """安全获取 GameScreen"""
    from client.ui.screen import GameScreen
    screen = app.screen
    return screen if isinstance(screen, GameScreen) else None


def get_mode(app) -> str:
    """返回 'NORMAL' | 'INSERT'"""
    return app.vim.mode_label


def is_logged_in(app) -> bool:
    screen = _get_screen(app)
    return screen is not None and screen.logged_in


def get_location(app) -> str:
    screen = _get_screen(app)
    return screen.current_location if screen else ""


def get_focused_panel(app) -> str | None:
    screen = _get_screen(app)
    return screen._focused_module() if screen else None


def is_cmd_select_mode(app) -> bool:
    screen = _get_screen(app)
    return screen is not None and screen._cmd_select_mode


def has_input_bar(app) -> bool:
    from client.ui.vim_mode import Mode
    return app.vim.mode == Mode.INSERT


def get_cmd_lines(app) -> list[str]:
    screen = _get_screen(app)
    return list(screen.state.cmd.lines) if screen else []


def get_hint_bar_items(app) -> list[str]:
    screen = _get_screen(app)
    if not screen:
        return []
    board = screen.get_module('game_board')
    if not board or not hasattr(board, '_hint_bar'):
        return []
    bar = board._hint_bar()
    if not bar or not hasattr(bar, '_current_items'):
        return []
    return [it.get('label', it.get('name', '')) for it in bar._current_items()]


# ── 面板特定读取器 ──

def get_panel(app, name: str):
    """获取指定名称的面板 widget，不存在返回 None"""
    screen = _get_screen(app)
    if not screen:
        return None
    return screen.get_module(name)


def get_chat_tab(app) -> str:
    panel = get_panel(app, 'chat')
    return getattr(panel, '_active_tab', '') if panel else ''


def get_inventory_mode(app) -> str:
    panel = get_panel(app, 'inventory')
    return getattr(panel, '_mode', '') if panel else ''


def get_status_page(app) -> str:
    panel = get_panel(app, 'status')
    return getattr(panel, '_page', '') if panel else ''


def get_online_tab(app) -> str:
    panel = get_panel(app, 'online')
    return getattr(panel, '_tab', '') if panel else ''


def get_online_mode(app) -> str:
    panel = get_panel(app, 'online')
    return getattr(panel, '_mode', '') if panel else ''


def get_notification_tab(app) -> str:
    panel = get_panel(app, 'notify')
    return getattr(panel, '_tab', '') if panel else ''


def is_space_menu_open(app) -> bool:
    screen = _get_screen(app)
    if not screen:
        return False
    return screen._wk.is_open


def get_input_target(app) -> str:
    screen = _get_screen(app)
    return screen._input_target if screen else ''


# ── 断言辅助 ──

def assert_mode(app, expected: str):
    actual = get_mode(app)
    assert actual == expected, f"expected mode={expected!r}, got {actual!r}"


def assert_logged_in(app):
    assert is_logged_in(app), "expected logged_in=True"


def assert_location(app, expected: str):
    actual = get_location(app)
    assert actual == expected, f"expected location={expected!r}, got {actual!r}"


def assert_focused_panel(app, expected: str):
    actual = get_focused_panel(app)
    assert actual == expected, f"expected panel={expected!r}, got {actual!r}"


def assert_cmd_select(app, expected: bool):
    actual = is_cmd_select_mode(app)
    assert actual == expected, f"expected cmd_select={expected}, got {actual}"


def assert_no_disconnect(app):
    lines = get_cmd_lines(app)
    for line in lines:
        assert "连接已断开" not in line, f"发现断连消息: {line!r}"


def assert_chat_tab(app, expected: str):
    actual = get_chat_tab(app)
    assert actual == expected, f"expected chat_tab={expected!r}, got {actual!r}"


def assert_inventory_mode(app, expected: str):
    actual = get_inventory_mode(app)
    assert actual == expected, f"expected inventory_mode={expected!r}, got {actual!r}"


def assert_status_page(app, expected: str):
    actual = get_status_page(app)
    assert actual == expected, f"expected status_page={expected!r}, got {actual!r}"


def assert_online_tab(app, expected: str):
    actual = get_online_tab(app)
    assert actual == expected, f"expected online_tab={expected!r}, got {actual!r}"


def assert_notification_tab(app, expected: str):
    actual = get_notification_tab(app)
    assert actual == expected, f"expected notification_tab={expected!r}, got {actual!r}"


def assert_space_menu_open(app, expected: bool = True):
    actual = is_space_menu_open(app)
    assert actual == expected, f"expected space_menu_open={expected}, got {actual}"


def assert_input_target(app, expected: str):
    actual = get_input_target(app)
    assert actual == expected, f"expected input_target={expected!r}, got {actual!r}"
