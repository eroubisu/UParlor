"""test_game_help.py — 参数化：帮助/引导系统（全 6 游戏）

覆盖：/help → doc 非空 / /help {section} → 对应内容。
"""

from __future__ import annotations

from ..parametrize import for_each_game
from ..game_config import ALL_GAME_IDS, GameConfig
from ..actions import send_command
from ..checks import assert_no_disconnect
from ..game_actions import enter_game
from ..game_checks import get_doc


@for_each_game(ALL_GAME_IDS)
async def test_help(pilot, game_id: str, cfg: GameConfig):
    """lobby 中 /help → doc 非空"""
    await enter_game(pilot, game_id)
    app = pilot.app
    await send_command(pilot, "/help")
    await pilot.pause(1.5)
    doc = get_doc(app)
    assert doc, f"{game_id}: /help returned empty doc"
    assert_no_disconnect(app)


@for_each_game(ALL_GAME_IDS)
async def test_help_section(pilot, game_id: str, cfg: GameConfig):
    """/help {section} → doc 非空"""
    await enter_game(pilot, game_id)
    app = pilot.app
    section = cfg.help_sections[1] if len(cfg.help_sections) > 1 else cfg.help_sections[0]
    await send_command(pilot, f"/help {section}")
    await pilot.pause(1.5)
    doc = get_doc(app)
    assert doc, f"{game_id}: /help {section} returned empty doc"
    assert_no_disconnect(app)
