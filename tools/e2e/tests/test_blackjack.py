"""test_blackjack.py — 21点 E2E 测试（游戏特有逻辑）

通用生命周期/退出/帮助/INSERT 已由 test_game_*.py 参数化覆盖。
本文件只保留 blackjack 特有的游戏操作测试。
"""

from __future__ import annotations

from ..actions import wait_for
from ..checks import assert_no_disconnect
from ..game_actions import setup_game, game_cmd
from ..game_checks import is_my_turn, is_game_over

_GAME = 'blackjack'


async def test_stand(pilot):
    """开始游戏 → stand → 庄家补牌 → 结算"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=10,
    )
    if is_my_turn(app):
        await game_cmd(pilot, "stand")
        await pilot.pause(0.5)

    await wait_for(
        pilot,
        lambda: is_game_over(app),
        timeout=10,
    )
    assert_no_disconnect(app)


async def test_hit_then_stand(pilot):
    """开始游戏 → hit → (如果没爆) stand → 结算"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=10,
    )
    if is_my_turn(app):
        await game_cmd(pilot, "hit")
        await pilot.pause(0.5)

    if not is_game_over(app) and is_my_turn(app):
        await game_cmd(pilot, "stand")
        await pilot.pause(0.5)

    await wait_for(
        pilot,
        lambda: is_game_over(app),
        timeout=10,
    )
    assert_no_disconnect(app)


async def test_double(pilot):
    """开始游戏 → double → 结算"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=10,
    )
    if is_my_turn(app):
        await game_cmd(pilot, "double")
        await pilot.pause(0.5)

    await wait_for(
        pilot,
        lambda: is_game_over(app),
        timeout=10,
    )
    assert_no_disconnect(app)
