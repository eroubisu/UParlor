"""game_actions.py — 房间制游戏通用操作原语

所有房间制游戏共享相同的生命周期：
  login → walk_to_building → enter → /play <game> → lobby
       → /create → room → /bot N → /start → playing
       → game actions → game_over → room → /back → lobby → /back → world

本模块封装这些通用操作，使各游戏测试只需关注游戏特有逻辑。
"""

from __future__ import annotations

from .actions import (
    login, wait_for, open_menu, menu_select,
)
from .checks import get_location, assert_no_disconnect


# ── 建筑坐标配置 ──
# starter_town 地图 spawn=[53,23]，各建筑门坐标：
_BUILDING_DOORS = {
    'gamehall':  (39, 17),   # map 4: mahjong, doudizhu
    'casino':    (30, 19),   # map 7: blackjack, holdem
    'library':   (45, 17),   # map 6: wordle
    'chesshall': (33, 19),   # map 8: chess
}
_SPAWN = (53, 23)

# 游戏 → 所在建筑
_GAME_BUILDING = {
    'mahjong': 'gamehall', 'doudizhu': 'gamehall',
    'blackjack': 'casino', 'holdem': 'casino',
    'wordle': 'library',
    'chess': 'chesshall',
}

_STEP_DELAY = 0.4  # 移动冷却 ~0.34s，留余量


async def _walk_to_building(pilot, building: str):
    """从 spawn[53,23] 走到指定建筑门口。

    移动使用 hjkl（世界地图 NORMAL 模式下直接发送移动指令）。
    """
    door_x, door_y = _BUILDING_DOORS[building]
    dx = _SPAWN[0] - door_x   # 正值=向左(h)
    dy = _SPAWN[1] - door_y   # 正值=向上(k)

    h_key = "h" if dx > 0 else "l"
    v_key = "k" if dy > 0 else "j"

    for _ in range(abs(dx)):
        await pilot.press(h_key)
        await pilot.pause(_STEP_DELAY)
    for _ in range(abs(dy)):
        await pilot.press(v_key)
        await pilot.pause(_STEP_DELAY)
    # 等待最后一步的服务端响应
    await pilot.pause(0.5)


async def enter_game(pilot, game_id: str):
    """完整流程：登录 → 走到建筑 → 进入建筑 → /play <game> → 等待进入游戏大厅。

    结束后 location = '<game_id>_lobby'。
    """
    app = pilot.app
    building = _GAME_BUILDING[game_id]

    # 1. 登录 → 等待进入世界
    await login(pilot)
    await wait_for(
        pilot,
        lambda: get_location(app).startswith("world_"),
        timeout=10,
    )

    # 2. 走到建筑门口
    await _walk_to_building(pilot, building)

    # 3. 按 Enter 进入建筑（重试一次以应对 door 信息尚未到达的情况）
    for _ in range(3):
        await pilot.press("enter")
        await pilot.pause(1.5)
        if "building" in get_location(app):
            break
    await wait_for(
        pilot,
        lambda: "building" in get_location(app),
        timeout=10,
    )

    # 4. 通过 hint bar 选择 play → 子菜单选择游戏
    await pilot.pause(1.0)
    # 打开 cmd_select（如果尚未开启）
    if not getattr(app.screen, '_cmd_select_mode', False):
        await open_menu(pilot)
        await pilot.pause(0.3)
    await menu_select(pilot, "play")
    await pilot.pause(0.3)
    await menu_select(pilot, game_id)
    await pilot.pause(0.5)

    # 5. 等待进入游戏大厅
    expected = f"{game_id}_lobby"
    await wait_for(
        pilot,
        lambda: get_location(app) == expected,
        timeout=10,
    )


async def create_room(pilot, game_id: str):
    """在游戏大厅中创建房间。

    通过 hint bar 选择 'create' 指令。
    结束后 location = '<game_id>_room'。
    """
    app = pilot.app
    await open_menu(pilot)
    await menu_select(pilot, "create")
    await pilot.pause(0.5)

    expected = f"{game_id}_room"
    await wait_for(
        pilot,
        lambda: get_location(app) == expected,
        timeout=10,
    )


async def add_bots(pilot, count: int = 1):
    """在房间中添加 bot。

    通过 hint bar 选择 'bot' → 弹出子菜单选择数量。
    """
    await open_menu(pilot)
    await menu_select(pilot, "bot")
    await pilot.pause(0.3)
    # 子菜单弹出，选择数量
    await menu_select(pilot, str(count))
    await pilot.pause(0.5)


async def start_game(pilot, game_id: str):
    """在房间中开始游戏。

    通过 hint bar 选择 'start' 指令。
    结束后 location = '<game_id>_playing'。
    """
    app = pilot.app
    await open_menu(pilot)
    await menu_select(pilot, "start")
    await pilot.pause(0.5)

    expected = f"{game_id}_playing"
    await wait_for(
        pilot,
        lambda: get_location(app) == expected,
        timeout=15,
    )


async def game_cmd(pilot, label: str):
    """在游戏中通过 hint bar 选择并执行指令。"""
    await open_menu(pilot)
    await menu_select(pilot, label)
    await pilot.pause(0.5)


async def add_bot_direct(pilot):
    """直接添加 bot（无子菜单，如 chess 的 /bot）。"""
    await open_menu(pilot)
    await menu_select(pilot, "bot")
    await pilot.pause(0.5)


async def setup_and_start(pilot, game_id: str, bot_count: int = 1):
    """一站式：进入游戏 → 创建房间 → 添加 bot → 开始。

    结束后 location = '<game_id>_playing'。
    """
    await enter_game(pilot, game_id)
    await create_room(pilot, game_id)
    await add_bots(pilot, bot_count)
    await start_game(pilot, game_id)


async def setup_and_start_solo(pilot, game_id: str):
    """一站式（无 bot）：进入游戏 → 创建房间 → 开始。

    适用于 wordle 等单人即可开始的游戏。
    结束后 location = '<game_id>_playing'。
    """
    await enter_game(pilot, game_id)
    await create_room(pilot, game_id)
    await start_game(pilot, game_id)


async def setup_game(pilot, game_id: str):
    """配置驱动的一站式 setup：根据 game_config 自动选择路径。

    结束后 location = '<game_id>_playing'。
    """
    from .game_config import GAMES
    cfg = GAMES[game_id]
    await enter_game(pilot, game_id)
    await create_room(pilot, game_id)
    if cfg.bot_count > 0:
        if cfg.bot_mode == 'direct':
            for _ in range(cfg.bot_count):
                await add_bot_direct(pilot)
        else:
            await add_bots(pilot, cfg.bot_count)
    await start_game(pilot, game_id)


async def leave_to_lobby(pilot, game_id: str):
    """/back 返回游戏大厅。"""
    app = pilot.app
    await open_menu(pilot)
    await menu_select(pilot, "back")
    await pilot.pause(0.5)
    expected = f"{game_id}_lobby"
    await wait_for(
        pilot,
        lambda: get_location(app) == expected,
        timeout=10,
    )


async def leave_to_world(pilot):
    """/back 逐层返回世界。

    从 game lobby/room → building（back 可用）→ world（building 中 back 被过滤，
    所以按 escape 退出 → 按 enter 离开建筑回世界）。
    """
    app = pilot.app
    for _ in range(5):
        loc = get_location(app)
        if loc.startswith("world_"):
            return
        if loc.startswith("building_"):
            # building 中没有 back 命令，按 escape 关闭菜单后按 enter 出门
            if getattr(app.screen, '_cmd_select_mode', False):
                await pilot.press("escape")
                await pilot.pause(0.2)
            await pilot.press("enter")
            await pilot.pause(1.0)
            continue
        # game 位置（lobby/room/playing）→ back 可用
        await open_menu(pilot)
        await menu_select(pilot, "back")
        await pilot.pause(1.0)
    await wait_for(
        pilot,
        lambda: get_location(app).startswith("world_"),
        timeout=10,
    )
