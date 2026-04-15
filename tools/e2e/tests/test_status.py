"""test_status.py — 角色/状态面板测试"""

from __future__ import annotations

from ..actions import (
    login, nav, space_open_panel, focus_panel,
)
from ..checks import (
    assert_mode, assert_no_disconnect, assert_status_page,
    get_status_page,
)


async def _go_to_status(pilot):
    """登录后通过 Space 菜单打开角色面板"""
    await login(pilot)
    # 角色面板 idx=2
    await space_open_panel(pilot, 2)
    await pilot.pause(0.3)


async def test_status_default_page(pilot):
    """打开角色面板→默认 status 页"""
    await _go_to_status(pilot)
    app = pilot.app
    assert_status_page(app, "status")
    assert_no_disconnect(app)


async def test_status_page_switch(pilot):
    """h/l 切换状态页→验证页面名称变化"""
    await _go_to_status(pilot)
    app = pilot.app

    # 向右切换到下一页
    await nav(pilot, "right")
    await pilot.pause(0.2)
    page1 = get_status_page(app)

    await nav(pilot, "right")
    await pilot.pause(0.2)
    page2 = get_status_page(app)

    # 至少切换了一次
    assert page1 != "status" or page2 != "status", "页面未切换"
    assert_no_disconnect(app)


async def test_status_page_cycle(pilot):
    """循环切换所有页面→不崩溃"""
    await _go_to_status(pilot)
    app = pilot.app

    # status → equip → card → settings → game → 继续
    for _ in range(6):
        await nav(pilot, "right")
        await pilot.pause(0.1)

    for _ in range(6):
        await nav(pilot, "left")
        await pilot.pause(0.1)

    assert_no_disconnect(app)


async def test_status_jk_scroll(pilot):
    """角色面板 j/k 滚动内容"""
    await _go_to_status(pilot)
    app = pilot.app

    for _ in range(5):
        await nav(pilot, "down")
    for _ in range(5):
        await nav(pilot, "up")
    await pilot.pause(0.1)

    assert_no_disconnect(app)
