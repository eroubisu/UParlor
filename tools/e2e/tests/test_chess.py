"""test_chess.py — 国际象棋 E2E 测试（游戏特有逻辑）

通用生命周期/退出/帮助/INSERT 已由 test_game_*.py 参数化覆盖。
本文件只保留 chess 特有的走棋、认输、和棋测试。
"""

from __future__ import annotations

from ..actions import wait_for, type_text, menu_select
from ..checks import assert_no_disconnect, get_location
from ..game_actions import setup_game, game_cmd
from ..game_checks import (
    get_room_data, get_room_state, is_my_turn, is_game_over,
)

_GAME = 'chess'


async def test_insert_move(pilot):
    """INSERT 模式走棋：i → 输入 UCI → Enter"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await wait_for(
        pilot,
        lambda: is_my_turn(app) or is_game_over(app),
        timeout=20,
    )
    if not is_my_turn(app):
        assert_no_disconnect(app)
        return

    rd = get_room_data(app)
    move = 'e2e4' if rd.get('turn') == 'white' else 'e7e5'
    await pilot.press("i")
    await pilot.pause(0.1)
    await type_text(pilot, move)
    await pilot.press("enter")
    await pilot.pause(1.0)

    loc = get_location(app)
    assert loc.startswith('chess_'), f"expected chess_*, got {loc}"
    assert_no_disconnect(app)


async def test_resign(pilot):
    """游戏中 back → 确认认输 → 回到 room"""
    await setup_game(pilot, _GAME)
    app = pilot.app
    await pilot.pause(1.0)

    await game_cmd(pilot, "back")
    await pilot.pause(0.5)

    try:
        panel = app.screen.query_one('GameBoardPanel')
        bar = panel._hint_bar()
        if bar and bar._nav_stack:
            await menu_select(pilot, "确认认输")
            await pilot.pause(1.0)
    except Exception:
        pass

    await wait_for(
        pilot,
        lambda: get_location(app) in ('chess_room', 'chess_lobby'),
        timeout=15,
    )
    assert_no_disconnect(app)


async def test_draw_vs_bot(pilot):
    """向 bot 提议和棋 → bot 自动接受 → 游戏结束"""
    await setup_game(pilot, _GAME)
    app = pilot.app
    await pilot.pause(1.0)

    await game_cmd(pilot, "draw")
    await pilot.pause(1.0)

    await wait_for(
        pilot,
        lambda: get_location(app) in ('chess_room', 'chess_lobby')
                or get_room_state(app) in ('finished', 'waiting'),
        timeout=15,
    )
    assert_no_disconnect(app)


async def test_game_complete(pilot):
    """完整对局：通过 hint bar select_menu 走棋直到游戏结束"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    for _ in range(50):
        await pilot.pause(0.5)

        if is_game_over(app) or get_location(app) == 'chess_room':
            break

        if not is_my_turn(app):
            continue

        try:
            await game_cmd(pilot, "move")
            await pilot.pause(0.3)
            panel = app.screen.query_one('GameBoardPanel')
            bar = panel._hint_bar()
            if bar and bar._nav_stack:
                await pilot.press("enter")
                await pilot.pause(1.0)
        except Exception:
            break

    await wait_for(
        pilot,
        lambda: is_game_over(app) or get_location(app) == 'chess_room'
                or is_my_turn(app),
        timeout=20,
    )
    assert_no_disconnect(app)
