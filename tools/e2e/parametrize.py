"""parametrize.py — 游戏参数化装饰器

将 `async def test_xxx(pilot, game_id, cfg)` 展开为模块级
`test_xxx_holdem(pilot)`, `test_xxx_chess(pilot)` ... 等函数，
兼容现有 harness 的 `async def test_*` 发现机制。

用法::

    from ..parametrize import for_each_game
    from ..game_config import ALL_GAME_IDS

    @for_each_game(ALL_GAME_IDS)
    async def test_enter(pilot, game_id, cfg):
        ...

展开后，调用方模块自动获得 test_enter_holdem, test_enter_blackjack, ... 等函数。
"""

from __future__ import annotations

import functools
import sys
from typing import Callable, Sequence

from .game_config import GAMES, GameConfig


def for_each_game(game_ids: Sequence[str]) -> Callable:
    """装饰器：将一个参数化测试函数展开为多个具名测试函数。

    被装饰函数签名: async def test_xxx(pilot, game_id: str, cfg: GameConfig)
    展开结果: test_xxx_holdem(pilot), test_xxx_chess(pilot), ...

    展开的函数会被注入到**调用方模块**的全局命名空间中。
    """

    def decorator(fn: Callable) -> Callable:
        # 获取调用方模块（装饰器使用处）
        caller_module = sys.modules[fn.__module__]

        for game_id in game_ids:
            cfg = GAMES[game_id]
            # 闭包捕获 game_id 和 cfg
            generated = _make_test(fn, game_id, cfg)
            name = f"{fn.__name__}_{game_id}"
            generated.__name__ = name
            generated.__qualname__ = name
            generated.__module__ = fn.__module__
            generated.__doc__ = f"{fn.__doc__ or fn.__name__} [{game_id}]"
            # 注入到调用方模块
            setattr(caller_module, name, generated)

        # 返回原函数（不会被 harness 发现，因为不是 test_ 开头 — 实际它是，
        # 但 harness 只发现模块中直接可访问的函数，而展开的函数才是真正入口）
        # 标记原函数为非测试，避免被发现
        fn._parametrized = True
        return fn

    return decorator


def _make_test(fn: Callable, game_id: str, cfg: GameConfig) -> Callable:
    """创建绑定了 game_id/cfg 的测试函数"""

    @functools.wraps(fn)
    async def wrapper(pilot):
        await fn(pilot, game_id, cfg)

    return wrapper
