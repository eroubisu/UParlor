"""test_game_lifecycle.py — 参数化：游戏生命周期（全 6 游戏）

每个游戏自动测试：进入大厅 / 创建房间 / 开始游戏 / 返回世界。
"""

from __future__ import annotations

from ..parametrize import for_each_game
from ..game_config import ALL_GAME_IDS, GameConfig
from ..checks import assert_no_disconnect, get_location
from ..game_actions import enter_game, create_room, setup_game, leave_to_world
from ..game_checks import (
    get_doc, get_room_state, assert_game_type, assert_room_state,
)


@for_each_game(ALL_GAME_IDS)
async def test_enter(pilot, game_id: str, cfg: GameConfig):
    """进入游戏大厅 → location 正确 + doc 非空"""
    await enter_game(pilot, game_id)
    app = pilot.app
    assert get_location(app) == f'{game_id}_lobby'
    assert_game_type(app, game_id)
    doc = get_doc(app)
    assert doc, f"{game_id} lobby should have doc"
    assert_no_disconnect(app)


@for_each_game(ALL_GAME_IDS)
async def test_create_room(pilot, game_id: str, cfg: GameConfig):
    """创建房间 → room_state=waiting"""
    await enter_game(pilot, game_id)
    await create_room(pilot, game_id)
    app = pilot.app
    assert get_location(app) == f'{game_id}_room'
    assert_room_state(app, 'waiting')
    assert_no_disconnect(app)


@for_each_game(ALL_GAME_IDS)
async def test_start(pilot, game_id: str, cfg: GameConfig):
    """创建 + bot + 开始 → playing"""
    await setup_game(pilot, game_id)
    app = pilot.app
    assert get_location(app) == f'{game_id}_playing'
    assert_game_type(app, game_id)
    assert_no_disconnect(app)


@for_each_game(ALL_GAME_IDS)
async def test_back_to_world(pilot, game_id: str, cfg: GameConfig):
    """进入大厅 → 返回世界"""
    await enter_game(pilot, game_id)
    await leave_to_world(pilot)
    app = pilot.app
    assert get_location(app).startswith("world_")
    assert_no_disconnect(app)
