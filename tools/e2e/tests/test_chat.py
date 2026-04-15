"""test_chat.py — 聊天面板测试"""

from __future__ import annotations

from ..actions import (
    login, enter_insert, exit_insert, type_text, nav, nav_outer,
    send_command, space_open_panel, focus_panel, wait_for,
)
from ..checks import (
    assert_mode, assert_no_disconnect, assert_chat_tab,
    assert_focused_panel, get_chat_tab, get_focused_panel,
)


async def _go_to_chat(pilot):
    """登录后切换到聊天面板"""
    await login(pilot)
    # 聊天面板 idx=0（面板列表第一个）
    await space_open_panel(pilot, 0)
    await pilot.pause(0.3)


async def test_chat_default_tab(pilot):
    """打开聊天面板→默认在 global 频道"""
    await _go_to_chat(pilot)
    app = pilot.app
    assert_chat_tab(app, "global")
    assert_no_disconnect(app)


async def test_chat_send_message(pilot):
    """在聊天面板发送一条消息→不崩溃"""
    await _go_to_chat(pilot)
    app = pilot.app
    await focus_panel(pilot, "chat")
    await enter_insert(pilot, sticky=True)
    await type_text(pilot, "hello e2e")
    await pilot.press("enter")
    await pilot.pause(0.5)
    # 粘滞模式应仍在 INSERT
    assert_mode(app, "INSERT")
    await exit_insert(pilot)
    assert_no_disconnect(app)


async def test_chat_tab_switch(pilot):
    """聊天面板 h/l 切换 tab→不崩溃"""
    await _go_to_chat(pilot)
    app = pilot.app
    await focus_panel(pilot, "chat")

    # 尝试切换 tab
    await nav(pilot, "right")
    await pilot.pause(0.2)
    await nav(pilot, "left")
    await pilot.pause(0.2)

    assert_no_disconnect(app)


async def test_chat_scroll(pilot):
    """聊天面板 j/k 滚动消息列表"""
    await _go_to_chat(pilot)
    app = pilot.app
    await focus_panel(pilot, "chat")

    for _ in range(5):
        await nav(pilot, "down")
    for _ in range(5):
        await nav(pilot, "up")
    await pilot.pause(0.1)

    assert_no_disconnect(app)
