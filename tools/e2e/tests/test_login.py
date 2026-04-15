"""test_login.py — 登录流程测试"""

from __future__ import annotations

from ..actions import login, type_text, wait_for
from ..checks import (
    assert_logged_in, assert_mode, assert_no_disconnect,
    is_logged_in, get_focused_panel,
)


async def test_basic_login(pilot):
    """输入用户名→密码→验证登录成功→验证进入游戏布局"""
    await login(pilot)
    app = pilot.app
    assert_logged_in(app)
    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_login_layout_has_panels(pilot):
    """登录后应有 game_board 或 cmd 面板"""
    await login(pilot)
    app = pilot.app
    from client.ui.screen import GameScreen
    screen = app.screen
    assert isinstance(screen, GameScreen)
    # 至少能找到一个核心面板
    found = False
    for mod_name in ('game_board', 'cmd', 'chat'):
        if screen.get_module(mod_name):
            found = True
            break
    assert found, "登录后未找到任何核心面板"
