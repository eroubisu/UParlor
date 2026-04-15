"""test_holdem.py — 德州扑克 E2E 测试（游戏特有逻辑）

通用生命周期/退出/帮助/INSERT 已由 test_game_*.py 参数化覆盖。
本文件只保留 holdem 特有的游戏操作测试。
"""

from __future__ import annotations

from ..actions import wait_for
from ..checks import assert_no_disconnect, get_location
from ..game_actions import setup_game, game_cmd
from ..game_checks import (
    get_room_data, is_my_turn, is_game_over,
)

_GAME = 'holdem'


async def test_fold(pilot):
    """开始游戏 → 等轮到我 → fold → 游戏结束"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=15,
    )
    if is_my_turn(app):
        await game_cmd(pilot, "fold")
        await pilot.pause(0.5)

    await wait_for(
        pilot,
        lambda: is_game_over(app),
        timeout=15,
    )
    assert get_location(app) == 'holdem_room'
    assert_no_disconnect(app)


async def test_check_or_call(pilot):
    """开始游戏 → 等轮到我 → check/call → 不崩溃"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=15,
    )
    if is_my_turn(app):
        rd = get_room_data(app)
        can_check = rd.get('can_check', False)
        if can_check:
            await game_cmd(pilot, "check")
        else:
            await game_cmd(pilot, "call")
        await pilot.pause(0.5)

    await wait_for(
        pilot,
        lambda: is_game_over(app),
        timeout=30,
    )
    assert_no_disconnect(app)


async def test_allin(pilot):
    """开始游戏 → 等轮到我 → all-in → 等待结算"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=15,
    )
    if is_my_turn(app):
        await game_cmd(pilot, "allin")
        await pilot.pause(0.5)

    await wait_for(
        pilot,
        lambda: is_game_over(app),
        timeout=20,
    )
    assert_no_disconnect(app)
