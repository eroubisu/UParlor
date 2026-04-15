"""test_wordle.py — Wordle E2E 测试（游戏特有逻辑）

通用生命周期/退出/帮助/INSERT 已由 test_game_*.py 参数化覆盖。
本文件只保留 wordle 特有的猜词逻辑测试。
"""

from __future__ import annotations

from ..actions import wait_for, type_text
from ..checks import assert_no_disconnect, get_location
from ..game_actions import setup_game
from ..game_checks import get_room_data, is_game_over

_GAME = 'wordle'

_GUESS_WORDS = ['crane', 'mouse', 'stain', 'blimp', 'rocky', 'depth']


async def test_insert_guess(pilot):
    """INSERT 模式猜词：i → 输入 crane → Enter → 验证猜测记录"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await pilot.press("i")
    await pilot.pause(0.1)
    await type_text(pilot, "crane")
    await pilot.press("enter")
    await pilot.pause(1.0)

    rd = get_room_data(app)
    guesses = rd.get('guesses', [])
    assert len(guesses) >= 1, f"expected at least 1 guess, got {len(guesses)}"
    loc = get_location(app)
    assert loc.startswith('wordle_'), f"expected wordle_*, got {loc}"
    assert_no_disconnect(app)


async def test_invalid_guess(pilot):
    """输入非法单词（3 字母）→ 不消耗猜测次数"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    await pilot.press("i")
    await pilot.pause(0.1)
    await type_text(pilot, "abc")
    await pilot.press("enter")
    await pilot.pause(1.0)

    rd = get_room_data(app)
    guesses = rd.get('guesses', [])
    assert len(guesses) == 0, f"invalid guess should not count, got {len(guesses)}"
    assert get_location(app) == 'wordle_playing'
    assert_no_disconnect(app)


async def test_play_until_end(pilot):
    """反复猜直到游戏结束（最多 6 次）"""
    await setup_game(pilot, _GAME)
    app = pilot.app

    for word in _GUESS_WORDS:
        if is_game_over(app):
            break

        await pilot.press("i")
        await pilot.pause(0.1)
        await type_text(pilot, word)
        await pilot.press("enter")
        await pilot.pause(1.0)

    await wait_for(
        pilot,
        lambda: is_game_over(app) or get_location(app) == 'wordle_finished',
        timeout=10,
    )
    assert_no_disconnect(app)

