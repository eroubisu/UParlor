"""test_inventory.py — 背包面板测试"""

from __future__ import annotations

from ..actions import (
    login, nav, nav_outer, space_open_panel, focus_panel, wait_for,
)
from ..checks import (
    assert_mode, assert_no_disconnect, assert_inventory_mode,
    get_inventory_mode, get_focused_panel,
)


async def _go_to_inventory(pilot):
    """登录后通过 Space 菜单打开背包面板"""
    await login(pilot)
    # 背包面板 idx=5
    await space_open_panel(pilot, 5)
    await pilot.pause(0.3)


async def test_inventory_open(pilot):
    """打开背包面板→默认 browse 模式"""
    await _go_to_inventory(pilot)
    app = pilot.app
    mode = get_inventory_mode(app)
    assert mode == "browse", f"expected browse, got {mode!r}"
    assert_no_disconnect(app)


async def test_inventory_tab_navigation(pilot):
    """背包 Tab 键切换行→不崩溃"""
    await _go_to_inventory(pilot)
    app = pilot.app

    # Tab 切换 tab_row
    await pilot.press("tab")
    await pilot.pause(0.1)
    await pilot.press("tab")
    await pilot.pause(0.1)
    await pilot.press("tab")
    await pilot.pause(0.1)

    assert_no_disconnect(app)


async def test_inventory_cursor_move(pilot):
    """背包 j/k 移动光标"""
    await _go_to_inventory(pilot)
    app = pilot.app

    for _ in range(3):
        await nav(pilot, "down")
    for _ in range(3):
        await nav(pilot, "up")
    await pilot.pause(0.1)

    assert_inventory_mode(app, "browse")
    assert_no_disconnect(app)


async def test_inventory_hl_tabs(pilot):
    """背包 h/l 在 tab_row 内切换"""
    await _go_to_inventory(pilot)
    app = pilot.app

    await nav(pilot, "right")
    await pilot.pause(0.1)
    await nav(pilot, "left")
    await pilot.pause(0.1)

    assert_no_disconnect(app)


async def test_inventory_enter_action(pilot):
    """背包 enter 进入 action 模式 → escape 返回"""
    await _go_to_inventory(pilot)
    app = pilot.app

    # 按 enter 尝试打开动作菜单（可能无物品，也不应崩溃）
    await pilot.press("enter")
    await pilot.pause(0.2)

    # 按 escape 返回
    await pilot.press("escape")
    await pilot.pause(0.2)

    assert_no_disconnect(app)
