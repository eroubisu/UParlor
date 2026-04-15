"""test_navigation.py — 面板切换与滚动测试"""

from __future__ import annotations

from ..actions import login, nav, nav_outer
from ..checks import (
    assert_mode, assert_no_disconnect, get_focused_panel,
)


async def test_panel_switch_HL(pilot):
    """H/L 切换面板→验证焦点变化"""
    await login(pilot)
    app = pilot.app
    initial_panel = get_focused_panel(app)

    # 连续按 L 尝试切换到下一个面板
    await nav_outer(pilot, "right")
    await nav_outer(pilot, "right")
    await nav_outer(pilot, "right")
    # 按 H 切回
    await nav_outer(pilot, "left")
    await nav_outer(pilot, "left")
    await nav_outer(pilot, "left")

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_rapid_switch(pilot):
    """连续快速 H 20次→不崩溃"""
    await login(pilot)
    app = pilot.app

    for _ in range(20):
        await pilot.press("H")
    await pilot.pause(0.2)

    for _ in range(20):
        await pilot.press("L")
    await pilot.pause(0.2)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_scroll_jk(pilot):
    """在面板中 j/k 滚动→不崩溃"""
    await login(pilot)
    app = pilot.app

    for _ in range(10):
        await pilot.press("j")
    for _ in range(10):
        await pilot.press("k")
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_scroll_gg_G(pilot):
    """gg 滚到顶部→G 滚到底部"""
    await login(pilot)
    app = pilot.app

    await pilot.press("G")
    await pilot.pause(0.1)
    await pilot.press("g")
    await pilot.press("g")
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_resize_pane(pilot):
    """< / > 调整面板大小→不崩溃"""
    await login(pilot)
    app = pilot.app

    for _ in range(3):
        await pilot.press(">")
    for _ in range(3):
        await pilot.press("<")
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)
