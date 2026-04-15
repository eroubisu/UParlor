"""test_cmd_menu.py — 指令菜单 (p) 测试"""

from __future__ import annotations

from ..actions import login, open_menu, close_menu, menu_nav
from ..checks import (
    assert_mode, assert_no_disconnect, assert_cmd_select,
    is_cmd_select_mode,
)


async def test_open_close(pilot):
    """p 打开菜单 → escape 关闭"""
    await login(pilot)
    app = pilot.app

    await open_menu(pilot)
    assert_cmd_select(app, True)

    await close_menu(pilot)
    assert_cmd_select(app, False)
    assert_mode(app, "NORMAL")


async def test_wasd_navigation(pilot):
    """p → WASD 导航 → 不崩溃且仍在菜单模式"""
    await login(pilot)
    app = pilot.app

    await open_menu(pilot)
    assert_cmd_select(app, True)

    # WASD 在菜单中应该可以导航
    await pilot.press("s")  # down
    await pilot.pause(0.05)
    assert_cmd_select(app, True)

    await pilot.press("w")  # up
    await pilot.pause(0.05)
    assert_cmd_select(app, True)

    await pilot.press("d")  # right
    await pilot.pause(0.05)
    assert_cmd_select(app, True)

    await pilot.press("a")  # left
    await pilot.pause(0.05)
    assert_cmd_select(app, True)

    await close_menu(pilot)
    assert_no_disconnect(app)


async def test_hjkl_navigation(pilot):
    """p → shift+HJKL 导航 → 不崩溃"""
    await login(pilot)
    app = pilot.app

    await open_menu(pilot)
    assert_cmd_select(app, True)

    await pilot.press("J")
    await pilot.pause(0.05)
    await pilot.press("K")
    await pilot.pause(0.05)
    await pilot.press("L")
    await pilot.pause(0.05)
    await pilot.press("H")
    await pilot.pause(0.05)

    assert_cmd_select(app, True)
    await close_menu(pilot)


async def test_rapid_open_close(pilot):
    """快速开关菜单 20 次"""
    await login(pilot)
    app = pilot.app

    for _ in range(20):
        await pilot.press("p")
        await pilot.press("escape")
    await pilot.pause(0.1)

    assert_cmd_select(app, False)
    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_backspace_in_menu(pilot):
    """菜单中按 backspace → 不崩溃"""
    await login(pilot)
    app = pilot.app

    await open_menu(pilot)
    # 按几个字母过滤再 backspace
    await pilot.press("h")
    await pilot.pause(0.05)
    await pilot.press("backspace")
    await pilot.pause(0.05)
    await pilot.press("backspace")  # 空时 backspace = 返回上级
    await pilot.pause(0.05)

    assert_cmd_select(app, True)
    await close_menu(pilot)
    assert_no_disconnect(app)
