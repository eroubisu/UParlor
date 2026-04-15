"""test_game_quit.py — 参数化：游戏中退出（全 6 游戏）

覆盖：playing 中 back → 确认退出 / 被拒绝（斗地主）。
"""

from __future__ import annotations

from ..parametrize import for_each_game
from ..game_config import ALL_GAME_IDS, GameConfig
from ..actions import wait_for, menu_select
from ..checks import assert_no_disconnect, get_location
from ..game_actions import setup_game, game_cmd
from ..game_checks import get_room_state


@for_each_game(ALL_GAME_IDS)
async def test_quit(pilot, game_id: str, cfg: GameConfig):
    """playing 中 back → 确认退出 / 验证禁退"""
    await setup_game(pilot, game_id)
    app = pilot.app
    await pilot.pause(0.5)

    await game_cmd(pilot, "back")
    await pilot.pause(1.0)

    if cfg.quit_confirm is None:
        # 不允许退出（如斗地主）→ 仍在 playing
        loc = get_location(app)
        assert loc == f'{game_id}_playing', (
            f"{game_id}: expected still playing, got {loc}"
        )
    else:
        # 弹出确认子菜单 → 选择确认
        try:
            panel = app.screen.query_one('GameBoardPanel')
            bar = panel._hint_bar()
            if bar and bar._nav_stack:
                await menu_select(pilot, cfg.quit_confirm)
                await pilot.pause(1.0)
        except Exception:
            pass

        await wait_for(
            pilot,
            lambda: get_location(app) in (
                f'{game_id}_room', f'{game_id}_lobby',
            ),
            timeout=15,
        )

    assert_no_disconnect(app)
