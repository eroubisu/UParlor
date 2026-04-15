"""test_vim_modes.py — Vim 模式切换测试"""

from __future__ import annotations

from ..actions import login, enter_insert, exit_insert, type_text, nav_outer
from ..checks import assert_mode, assert_no_disconnect, has_input_bar


async def _to_cmd_panel(pilot):
    """切换到 cmd 面板（支持 INSERT 输入）"""
    # game_board 可能阻止 INSERT，先切到 cmd 面板
    for _ in range(5):
        await nav_outer(pilot, "right")
    await pilot.pause(0.1)


async def test_insert_i(pilot):
    """按 i → INSERT 模式 + InputBar 出现"""
    await login(pilot)
    app = pilot.app
    await _to_cmd_panel(pilot)
    assert_mode(app, "NORMAL")

    await enter_insert(pilot)
    assert_mode(app, "INSERT")
    assert has_input_bar(app), "InputBar not visible"


async def test_insert_I_sticky(pilot):
    """按 I → 输入+回车 → 仍在 INSERT（粘滞模式）"""
    await login(pilot)
    app = pilot.app
    await _to_cmd_panel(pilot)

    await enter_insert(pilot, sticky=True)
    assert_mode(app, "INSERT")

    # 输入一些文字并提交
    await type_text(pilot, "test message")
    await pilot.press("enter")
    await pilot.pause(0.3)

    # 粘滞模式下应该仍在 INSERT
    assert_mode(app, "INSERT")


async def test_escape_normal(pilot):
    """INSERT 中按 escape → 回到 NORMAL"""
    await login(pilot)
    app = pilot.app
    await _to_cmd_panel(pilot)

    await enter_insert(pilot)
    assert_mode(app, "INSERT")

    await exit_insert(pilot)
    assert_mode(app, "NORMAL")


async def test_escape_from_normal(pilot):
    """NORMAL 中按 escape → 仍在 NORMAL（不崩溃）"""
    await login(pilot)
    app = pilot.app
    assert_mode(app, "NORMAL")

    await pilot.press("escape")
    await pilot.pause(0.1)
    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_rapid_mode_switch(pilot):
    """快速切换 i → esc → i → esc 20 次"""
    await login(pilot)
    app = pilot.app

    for _ in range(20):
        await pilot.press("i")
        await pilot.press("escape")
    await pilot.pause(0.1)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_number_prefix_j(pilot):
    """数字前缀 5j → 向下滚动 5 行"""
    await login(pilot)
    app = pilot.app
    await _to_cmd_panel(pilot)

    await pilot.press("5")
    await pilot.press("j")
    await pilot.pause(0.2)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_number_prefix_k(pilot):
    """数字前缀 10k → 向上滚动 10 行"""
    await login(pilot)
    app = pilot.app
    await _to_cmd_panel(pilot)

    await pilot.press("1")
    await pilot.press("0")
    await pilot.press("k")
    await pilot.pause(0.2)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)


async def test_number_prefix_G(pilot):
    """数字前缀后按 G → 不崩溃"""
    await login(pilot)
    app = pilot.app
    await _to_cmd_panel(pilot)

    await pilot.press("3")
    await pilot.press("G")
    await pilot.pause(0.2)

    assert_mode(app, "NORMAL")
    assert_no_disconnect(app)
