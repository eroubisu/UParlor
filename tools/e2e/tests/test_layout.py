"""test_layout.py — 布局与窗口操作测试"""

from __future__ import annotations

from ..actions import (
    login, space_window_action, nav_outer, open_space_menu,
)
from ..checks import (
    assert_mode, assert_no_disconnect,
)


async def test_split_horizontal(pilot):
    """Space→窗口→横分→不崩溃"""
    await login(pilot)
    app = pilot.app

    # 横分 idx=0
    await space_window_action(pilot, 0)
    await pilot.pause(0.3)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_split_vertical(pilot):
    """Space→窗口→纵分→不崩溃"""
    await login(pilot)
    app = pilot.app

    # 纵分 idx=1
    await space_window_action(pilot, 1)
    await pilot.pause(0.3)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_close_pane(pilot):
    """横分→关闭窗格→不崩溃"""
    await login(pilot)
    app = pilot.app

    # 先分一个窗格
    await space_window_action(pilot, 0)
    await pilot.pause(0.3)

    # 再关闭 idx=2
    await space_window_action(pilot, 2)
    await pilot.pause(0.3)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_refresh_pane(pilot):
    """Space→窗口→刷新→不崩溃"""
    await login(pilot)
    app = pilot.app

    # 刷新 idx=3
    await space_window_action(pilot, 3)
    await pilot.pause(0.3)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_split_and_navigate(pilot):
    """横分→H/L 切换窗格→不崩溃"""
    await login(pilot)
    app = pilot.app

    await space_window_action(pilot, 0)
    await pilot.pause(0.3)

    # 在窗格间切换
    for _ in range(3):
        await nav_outer(pilot, "right")
    for _ in range(3):
        await nav_outer(pilot, "left")
    await pilot.pause(0.2)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_resize_after_split(pilot):
    """分割后 > / < 调整大小"""
    await login(pilot)
    app = pilot.app

    await space_window_action(pilot, 0)
    await pilot.pause(0.3)

    for _ in range(3):
        await pilot.press(">")
    for _ in range(3):
        await pilot.press("<")
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)
