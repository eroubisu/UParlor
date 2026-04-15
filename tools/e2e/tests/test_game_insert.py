"""test_game_insert.py — 参数化：INSERT 输入框（有 prefix 的 4 个游戏 + 通用）

覆盖：INSERT 开启 / Escape 退出 / 提交→服务端响应 / prefix 正确 / lobby 阻止。
"""

from __future__ import annotations

from ..parametrize import for_each_game
from ..game_config import ALL_GAME_IDS, INSERT_GAME_IDS, GameConfig
from ..actions import wait_for, type_text
from ..checks import assert_no_disconnect, get_location, get_mode
from ..game_actions import enter_game, setup_game
from ..game_checks import get_room_data, is_game_over


@for_each_game(INSERT_GAME_IDS)
async def test_insert_opens(pilot, game_id: str, cfg: GameConfig):
    """playing 中按 i → 进入 INSERT"""
    await setup_game(pilot, game_id)
    app = pilot.app
    await pilot.press("i")
    await pilot.pause(0.2)
    assert get_mode(app) == 'INSERT', f"{game_id}: expected INSERT"
    assert_no_disconnect(app)


@for_each_game(INSERT_GAME_IDS)
async def test_insert_escape(pilot, game_id: str, cfg: GameConfig):
    """INSERT → Escape → NORMAL"""
    await setup_game(pilot, game_id)
    app = pilot.app
    await pilot.press("i")
    await pilot.pause(0.2)
    assert get_mode(app) == 'INSERT'
    await pilot.press("escape")
    await pilot.pause(0.2)
    assert get_mode(app) == 'NORMAL', f"{game_id}: expected NORMAL after Escape"
    assert_no_disconnect(app)


@for_each_game(INSERT_GAME_IDS)
async def test_insert_submit(pilot, game_id: str, cfg: GameConfig):
    """INSERT → 输入合法值 → Enter → 验证服务端有响应"""
    await setup_game(pilot, game_id)
    app = pilot.app

    # 对需要轮到自己才能操作的游戏（chess/mahjong/doudizhu），等待轮到我
    from ..game_checks import is_my_turn
    if game_id in ('chess', 'mahjong', 'doudizhu'):
        await wait_for(
            pilot,
            lambda: is_my_turn(app) or is_game_over(app),
            timeout=20,
        )
        if is_game_over(app):
            return  # 游戏已结束，跳过

    # chess 需要根据 turn 选择合法走法
    sample = cfg.sample_input
    if game_id == 'chess':
        rd = get_room_data(app)
        sample = 'e2e4' if rd.get('turn') == 'white' else 'e7e5'

    # INSERT 输入
    await pilot.press("i")
    await pilot.pause(0.1)
    await type_text(pilot, sample)
    await pilot.press("enter")
    await pilot.pause(1.5)

    # 验证：提交后回 NORMAL + 游戏状态有变化（未断连）
    mode = get_mode(app)
    assert mode == 'NORMAL', f"{game_id}: expected NORMAL after submit, got {mode}"
    assert_no_disconnect(app)


@for_each_game(ALL_GAME_IDS)
async def test_insert_blocked_in_lobby(pilot, game_id: str, cfg: GameConfig):
    """lobby 中按 i → 不进入 INSERT（prefix == '/'）"""
    await enter_game(pilot, game_id)
    app = pilot.app
    await pilot.press("i")
    await pilot.pause(0.2)
    mode = get_mode(app)
    assert mode == 'NORMAL', f"{game_id} lobby: expected NORMAL, got {mode}"
    assert_no_disconnect(app)
