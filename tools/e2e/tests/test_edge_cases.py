"""test_edge_cases.py — 边界与异常输入测试"""

from __future__ import annotations

from ..actions import (
    login, send_command, enter_insert, exit_insert, type_text,
    open_menu, close_menu, nav, nav_outer, open_space_menu,
    close_space_menu, space_open_panel,
)
from ..checks import (
    assert_mode, assert_no_disconnect, get_mode,
)


async def test_empty_input(pilot):
    """INSERT 模式空回车→不崩溃"""
    await login(pilot)
    app = pilot.app

    # 先切到 cmd 面板防止 game_board 阻止输入
    for _ in range(5):
        await nav_outer(pilot, "right")
    await pilot.pause(0.1)

    await enter_insert(pilot)
    await pilot.press("enter")
    await pilot.pause(0.3)
    await pilot.press("escape")
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_long_input(pilot):
    """输入超长文本→不崩溃"""
    await login(pilot)
    app = pilot.app

    for _ in range(5):
        await nav_outer(pilot, "right")
    await pilot.pause(0.1)

    await enter_insert(pilot)
    long_text = "a" * 200
    await type_text(pilot, long_text)
    await pilot.press("escape")
    await pilot.pause(0.2)

    assert_no_disconnect(app)


async def test_special_characters(pilot):
    """输入特殊字符→不崩溃"""
    await login(pilot)
    app = pilot.app

    for _ in range(5):
        await nav_outer(pilot, "right")
    await pilot.pause(0.1)

    await enter_insert(pilot)
    for ch in "!@#$%^&*()_+-=[]{}|;':\",./<>?":
        await pilot.press(ch)
    await pilot.press("escape")
    await pilot.pause(0.1)

    assert_no_disconnect(app)


async def test_rapid_insert_escape(pilot):
    """高频 i/escape 交替 50 次"""
    await login(pilot)
    app = pilot.app

    for _ in range(50):
        await pilot.press("i")
        await pilot.press("escape")
    await pilot.pause(0.2)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_rapid_panel_switch(pilot):
    """高频 H/L 交替 50 次"""
    await login(pilot)
    app = pilot.app

    for _ in range(50):
        await pilot.press("H")
        await pilot.press("L")
    await pilot.pause(0.2)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_menu_in_insert(pilot):
    """INSERT 模式下按 p → 不应打开菜单"""
    await login(pilot)
    app = pilot.app

    for _ in range(5):
        await nav_outer(pilot, "right")
    await pilot.pause(0.1)

    await enter_insert(pilot)
    assert_mode(app, "INSERT")
    # p 在 INSERT 模式是普通字符
    await pilot.press("p")
    await pilot.pause(0.1)
    # 应仍在 INSERT
    assert_mode(app, "INSERT")
    await exit_insert(pilot)
    assert_no_disconnect(app)


async def test_space_in_insert(pilot):
    """INSERT 模式下按 space → 输入空格而非打开菜单"""
    await login(pilot)
    app = pilot.app

    for _ in range(5):
        await nav_outer(pilot, "right")
    await pilot.pause(0.1)

    await enter_insert(pilot)
    await pilot.press("space")
    await pilot.pause(0.1)
    assert_mode(app, "INSERT")
    await exit_insert(pilot)
    assert_no_disconnect(app)


async def test_multiple_commands_sequence(pilot):
    """连续执行多个指令"""
    await login(pilot)
    app = pilot.app

    await send_command(pilot, "/help")
    await pilot.pause(0.3)
    await send_command(pilot, "/version")
    await pilot.pause(0.3)
    await send_command(pilot, "/games")
    await pilot.pause(0.3)

    assert_no_disconnect(app)


async def test_escape_all_modes(pilot):
    """连续多次 escape → 回到 NORMAL"""
    await login(pilot)
    app = pilot.app

    await pilot.press("escape")
    await pilot.press("escape")
    await pilot.press("escape")
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)
