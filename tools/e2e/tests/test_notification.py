"""test_notification.py — 通知面板测试"""

from __future__ import annotations

from ..actions import (
    login, nav, space_open_panel,
)
from ..checks import (
    assert_no_disconnect, assert_notification_tab,
    get_notification_tab,
)


async def _go_to_notification(pilot):
    """登录后通过 Space 菜单打开通知面板"""
    await login(pilot)
    # 通知面板 idx=7
    await space_open_panel(pilot, 7)
    await pilot.pause(0.3)


async def test_notification_default_tab(pilot):
    """打开通知面板→默认 system tab"""
    await _go_to_notification(pilot)
    app = pilot.app
    tab = get_notification_tab(app)
    assert tab in ("system", "friend", "game"), f"unexpected tab: {tab!r}"
    assert_no_disconnect(app)


async def test_notification_tab_switch(pilot):
    """h/l 切换通知 tab"""
    await _go_to_notification(pilot)
    app = pilot.app

    tabs_seen = {get_notification_tab(app)}
    for _ in range(3):
        await nav(pilot, "right")
        await pilot.pause(0.2)
        tabs_seen.add(get_notification_tab(app))

    assert len(tabs_seen) >= 2, f"only saw tabs: {tabs_seen}"
    assert_no_disconnect(app)


async def test_notification_scroll(pilot):
    """通知面板 j/k 滚动"""
    await _go_to_notification(pilot)
    app = pilot.app

    for _ in range(3):
        await nav(pilot, "down")
    for _ in range(3):
        await nav(pilot, "up")
    await pilot.pause(0.1)

    assert_no_disconnect(app)


async def test_notification_enter_escape(pilot):
    """通知 enter → escape 不崩溃"""
    await _go_to_notification(pilot)
    app = pilot.app

    await pilot.press("enter")
    await pilot.pause(0.2)
    await pilot.press("escape")
    await pilot.pause(0.2)

    assert_no_disconnect(app)
