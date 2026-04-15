"""test_space_menu.py — Space 菜单测试"""

from __future__ import annotations

from ..actions import (
    login, open_space_menu, close_space_menu, space_open_panel,
    space_window_action, nav,
)
from ..checks import (
    assert_mode, assert_no_disconnect, assert_space_menu_open,
    is_space_menu_open, get_focused_panel,
)


async def test_space_open_close(pilot):
    """Space 打开菜单 → Escape 关闭"""
    await login(pilot)
    app = pilot.app

    await open_space_menu(pilot)
    assert_space_menu_open(app, True)

    await close_space_menu(pilot)
    await pilot.pause(0.1)
    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_space_panel_submenu(pilot):
    """Space → 面板 → 导航子菜单 → Escape"""
    await login(pilot)
    app = pilot.app

    await open_space_menu(pilot)
    # 进入面板子菜单
    await pilot.press("enter")
    await pilot.pause(0.1)

    # 在子菜单中 j/k 导航
    await pilot.press("j")
    await pilot.pause(0.05)
    await pilot.press("j")
    await pilot.pause(0.05)
    await pilot.press("k")
    await pilot.pause(0.05)

    # escape 取消
    await pilot.press("escape")
    await pilot.pause(0.1)
    assert_no_disconnect(app)


async def test_space_open_chat(pilot):
    """Space 菜单打开聊天面板"""
    await login(pilot)
    app = pilot.app

    # idx 0 = 聊天
    await space_open_panel(pilot, 0)
    assert_no_disconnect(app)


async def test_space_open_inventory(pilot):
    """Space 菜单打开背包面板"""
    await login(pilot)
    app = pilot.app

    await space_open_panel(pilot, 5)
    assert_no_disconnect(app)


async def test_space_open_status(pilot):
    """Space 菜单打开角色面板"""
    await login(pilot)
    app = pilot.app

    await space_open_panel(pilot, 2)
    assert_no_disconnect(app)


async def test_space_rapid_open_close(pilot):
    """快速开关 Space 菜单 10 次"""
    await login(pilot)
    app = pilot.app

    for _ in range(10):
        await pilot.press("space")
        await pilot.pause(0.05)
        await pilot.press("escape")
        await pilot.pause(0.05)
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)
