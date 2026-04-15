"""test_commands.py — 各类指令测试"""

from __future__ import annotations

from ..actions import (
    login, send_command, open_menu, close_menu, menu_select,
    enter_insert, exit_insert, type_text, wait_for,
)
from ..checks import (
    assert_mode, assert_no_disconnect, get_cmd_lines,
    is_cmd_select_mode,
)


async def test_help_command(pilot):
    """/help → 输出帮助文本"""
    await login(pilot)
    app = pilot.app

    await send_command(pilot, "/help")
    await pilot.pause(0.5)

    lines = get_cmd_lines(app)
    assert len(lines) > 0, "no output from /help"
    assert_no_disconnect(app)


async def test_help_rules(pilot):
    """/help rules → 输出规则"""
    await login(pilot)
    app = pilot.app

    await send_command(pilot, "/help rules")
    await pilot.pause(0.5)

    assert_no_disconnect(app)


async def test_games_command(pilot):
    """/games → 列出可用游戏"""
    await login(pilot)
    app = pilot.app

    await send_command(pilot, "/games")
    await pilot.pause(0.5)

    assert_no_disconnect(app)


async def test_clear_command(pilot):
    """/clear → 清空记录面板"""
    await login(pilot)
    app = pilot.app

    # 先发一条消息以产生输出
    await send_command(pilot, "/help")
    await pilot.pause(0.3)

    await send_command(pilot, "/clear")
    await pilot.pause(0.3)

    assert_no_disconnect(app)


async def test_version_in_cmd(pilot):
    """/version → 显示版本"""
    await login(pilot)
    app = pilot.app

    await send_command(pilot, "/version")
    await pilot.pause(0.5)

    assert_no_disconnect(app)


async def test_unknown_command(pilot):
    """输入不存在的指令→不崩溃"""
    await login(pilot)
    app = pilot.app

    await send_command(pilot, "/nonexistent_cmd_12345")
    await pilot.pause(0.5)

    assert_no_disconnect(app)


async def test_menu_help_select(pilot):
    """p菜单→选择 help → 执行"""
    await login(pilot)
    app = pilot.app

    await open_menu(pilot)
    assert is_cmd_select_mode(app)
    await menu_select(pilot, "help")
    await pilot.pause(0.5)

    assert_no_disconnect(app)


async def test_menu_games_select(pilot):
    """p菜单→选择 games"""
    await login(pilot)
    app = pilot.app

    await open_menu(pilot)
    await menu_select(pilot, "games")
    await pilot.pause(0.5)

    assert_no_disconnect(app)


async def test_tab_complete(pilot):
    """输入 /hel + Tab → 尝试补全"""
    await login(pilot)
    app = pilot.app

    await enter_insert(pilot)
    await type_text(pilot, "/hel")
    await pilot.press("tab")
    await pilot.pause(0.3)
    await pilot.press("escape")
    await pilot.pause(0.1)

    assert_no_disconnect(app)
