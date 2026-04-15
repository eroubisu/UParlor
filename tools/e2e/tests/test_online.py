"""test_online.py — 在线用户面板测试"""

from __future__ import annotations

from ..actions import (
    login, nav, space_open_panel, focus_panel,
)
from ..checks import (
    assert_mode, assert_no_disconnect, assert_online_tab,
    get_online_tab, get_online_mode,
)


async def _go_to_online(pilot):
    """登录后通过 Space 菜单打开用户面板"""
    await login(pilot)
    # 用户面板 idx=3
    await space_open_panel(pilot, 3)
    await pilot.pause(0.3)


async def test_online_default_tab(pilot):
    """打开用户面板→默认 friends tab"""
    await _go_to_online(pilot)
    app = pilot.app
    tab = get_online_tab(app)
    # 默认应该是 friends 或 all
    assert tab in ("friends", "all", "online"), f"unexpected tab: {tab!r}"
    assert_no_disconnect(app)


async def test_online_tab_switch(pilot):
    """h/l 切换 tab (friends/all/online/search)"""
    await _go_to_online(pilot)
    app = pilot.app

    tabs_seen = {get_online_tab(app)}
    for _ in range(4):
        await nav(pilot, "right")
        await pilot.pause(0.2)
        tabs_seen.add(get_online_tab(app))

    # 应该看到至少 2 个不同 tab
    assert len(tabs_seen) >= 2, f"only saw tabs: {tabs_seen}"
    assert_no_disconnect(app)


async def test_online_scroll(pilot):
    """用户面板 j/k 滚动列表"""
    await _go_to_online(pilot)
    app = pilot.app

    for _ in range(5):
        await nav(pilot, "down")
    for _ in range(5):
        await nav(pilot, "up")
    await pilot.pause(0.1)

    assert_no_disconnect(app)


async def test_online_enter_escape(pilot):
    """选中用户 enter → 动作菜单 → escape 返回"""
    await _go_to_online(pilot)
    app = pilot.app

    await pilot.press("enter")
    await pilot.pause(0.2)
    await pilot.press("escape")
    await pilot.pause(0.2)

    assert_no_disconnect(app)
