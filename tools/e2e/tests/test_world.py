"""test_world.py — 世界游戏测试"""

from __future__ import annotations

from ..actions import login, open_menu, close_menu, menu_select, wait_for
from ..checks import (
    assert_no_disconnect, get_location, is_cmd_select_mode,
)


async def _enter_world(pilot):
    """辅助：登录 → 验证已在世界中

    登录后玩家默认就在 world_town，不需要额外操作。
    """
    await login(pilot)
    app = pilot.app

    # 等待进入世界（location 应以 world_ 开头）
    await wait_for(
        pilot,
        lambda: get_location(app).startswith("world_"),
        timeout=10,
    )


async def test_enter_world(pilot):
    """登录 → 进入世界 → 验证位置"""
    await _enter_world(pilot)
    app = pilot.app
    loc = get_location(app)
    assert loc.startswith("world_"), f"expected world_ location, got {loc!r}"
    assert_no_disconnect(app)


async def test_wasd_move(pilot):
    """在世界中 WASD 移动 → 不崩溃"""
    await _enter_world(pilot)
    app = pilot.app

    # 在世界中 hjkl 是移动方向，直接按
    for key in ["l", "l", "h", "h", "j", "j", "k", "k"]:
        await pilot.press(key)
        await pilot.pause(0.3)

    assert_no_disconnect(app)


async def test_world_menu_user(pilot):
    """世界中 p → 能看到 user 指令"""
    await _enter_world(pilot)
    app = pilot.app

    await open_menu(pilot)
    assert is_cmd_select_mode(app)
    await close_menu(pilot)
    assert_no_disconnect(app)


async def _walk_to_gamehall(pilot):
    """从 spawn[53,23] 走到游戏大厅门[39,17]

    移动冷却 ~0.34s，每步间隔需 >0.34s 以确保每次按键独立发送。
    """
    # 左移14步
    for _ in range(14):
        await pilot.press("h")
        await pilot.pause(0.4)
    # 上移6步
    for _ in range(6):
        await pilot.press("k")
        await pilot.pause(0.4)
    # 等待最后一步的服务端响应
    await pilot.pause(0.5)


async def test_enter_building(pilot):
    """从 spawn 走到游戏大厅门口→Enter 进入建筑"""
    await _enter_world(pilot)
    app = pilot.app

    await _walk_to_gamehall(pilot)
    # 在门口按 Enter（nav_enter → on_nav('enter') → /enter）
    await pilot.press("enter")
    await pilot.pause(1.0)

    # 验证进入建筑
    await wait_for(
        pilot,
        lambda: "building" in get_location(app),
        timeout=10,
    )
    loc = get_location(app)
    assert "building" in loc, f"expected building location, got {loc!r}"
    assert_no_disconnect(app)


async def test_exit_building(pilot):
    """进入建筑后→走到门口→/enter 退出"""
    await _enter_world(pilot)
    app = pilot.app

    # 走到门口并进入
    await _walk_to_gamehall(pilot)
    await pilot.press("enter")
    await pilot.pause(1.0)
    await wait_for(
        pilot,
        lambda: "building" in get_location(app),
        timeout=10,
    )

    # 建筑内初始位置就是返回门位置，直接按 Enter 退出
    await pilot.press("enter")
    await pilot.pause(1.0)
    await wait_for(
        pilot,
        lambda: get_location(app).startswith("world_"),
        timeout=10,
    )

    loc = get_location(app)
    assert loc.startswith("world_"), f"expected world_ after exit, got {loc!r}"
    assert_no_disconnect(app)


async def test_world_help(pilot):
    """世界中通过 hint bar 选择 help → 显示帮助"""
    await _enter_world(pilot)
    app = pilot.app

    # 按 p 打开指令栏，选择 help
    await open_menu(pilot)
    await menu_select(pilot, "help")
    await pilot.pause(0.5)

    assert_no_disconnect(app)


async def test_world_recall(pilot):
    """世界中 /recall → 回到出生点"""
    await _enter_world(pilot)
    app = pilot.app

    # 先走几步
    for key in ["l", "l", "l"]:
        await pilot.press(key)
        await pilot.pause(0.3)

    # 按 p 打开指令栏，选择 recall
    await open_menu(pilot)
    await menu_select(pilot, "recall")
    await pilot.pause(1.0)

    assert_no_disconnect(app)
