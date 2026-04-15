"""test_mahjong.py — 麻将 E2E 测试（游戏特有逻辑）

通用生命周期/退出/帮助/INSERT 已由 test_game_*.py 参数化覆盖。
本文件只保留 mahjong 特有的打牌和多轮测试。
"""

from __future__ import annotations

from ..actions import wait_for, type_text
from ..checks import assert_no_disconnect, get_location
from ..game_actions import setup_game
from ..game_checks import is_my_turn, is_game_over

_GAME = 'mahjong'


async def test_insert_discard(pilot):
    """INSERT 模式打牌：i → 输入序号 → Enter"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=30,
    )
    if not is_my_turn(app):
        assert_no_disconnect(app)
        return

    await pilot.press("i")
    await pilot.pause(0.1)
    await type_text(pilot, "0")
    await pilot.press("enter")
    await pilot.pause(1.0)

    loc = get_location(app)
    assert loc.startswith('mahjong_'), f"expected mahjong_*, got {loc}"
    assert_no_disconnect(app)


async def test_play_rounds(pilot):
    """打几轮牌：轮到我就打序号 0（第一张）"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    played = 0
    for _ in range(60):
        await pilot.pause(0.5)

        if is_game_over(app):
            break

        if not is_my_turn(app):
            continue

        await pilot.press("i")
        await pilot.pause(0.1)
        await type_text(pilot, "0")
        await pilot.press("enter")
        await pilot.pause(0.5)
        played += 1
        if played >= 3:
            break

    assert played > 0 or is_game_over(app), "should have played at least once"
    assert_no_disconnect(app)
