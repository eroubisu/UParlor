"""test_doudizhu.py — 斗地主 E2E 测试（游戏特有逻辑）

通用生命周期/退出/帮助/INSERT 已由 test_game_*.py 参数化覆盖。
本文件只保留 doudizhu 特有的叫分和出牌测试。
"""

from __future__ import annotations

from ..actions import wait_for, menu_select, type_text
from ..checks import assert_no_disconnect
from ..game_actions import setup_game, game_cmd
from ..game_checks import (
    get_room_data, get_room_state,
    is_my_turn, is_game_over,
)

_GAME = 'doudizhu'


async def test_bid_phase(pilot):
    """开始游戏 → 叫分阶段 → 叫 0 分（不叫）"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: (is_my_turn(app) and get_room_state(app) == 'bidding')
                or get_room_state(app) == 'playing',
        timeout=20,
    )

    if get_room_state(app) == 'bidding' and is_my_turn(app):
        await game_cmd(pilot, "bid")
        await pilot.pause(0.3)
        await menu_select(pilot, "0")
        await pilot.pause(0.5)

    await wait_for(
        pilot,
        lambda: get_room_state(app) in ('playing', 'waiting', 'bidding'),
        timeout=20,
    )
    assert_no_disconnect(app)


async def test_play_or_pass(pilot):
    """完整游戏：叫分 → 出牌/不出 → 等待结束"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    for _ in range(40):
        await pilot.pause(0.5)
        state = get_room_state(app)

        if state == 'bidding' and is_my_turn(app):
            await game_cmd(pilot, "bid")
            await pilot.pause(0.3)
            await menu_select(pilot, "0")
            await pilot.pause(0.5)
            continue

        if state == 'playing' and is_my_turn(app):
            rd = get_room_data(app)
            last_player = rd.get('last_play', {}).get('player', '')
            username = getattr(app, '_e2e_username', '')
            if not last_player or last_player == username:
                await pilot.press("i")
                await pilot.pause(0.1)
                await type_text(pilot, "0")
                await pilot.press("enter")
                await pilot.pause(0.5)
            else:
                app.send_command("/pass")
                await pilot.pause(0.5)
            continue

        if is_game_over(app):
            break

    assert_no_disconnect(app)
