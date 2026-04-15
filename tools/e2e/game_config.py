"""game_config.py — 游戏配置声明表（数据驱动测试的唯一参数来源）

新增游戏时只需在 GAMES 中加一行，所有参数化测试自动覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameConfig:
    """单个游戏的 E2E 测试配置"""

    bot_count: int
    """开局需要的 bot 数量（0 = 无需 bot，如 blackjack/wordle）"""

    bot_mode: str | None
    """bot 添加方式: 'submenu'（/bot → 选数量）| 'direct'（/bot 直接添加）| None"""

    input_prefix: str | None
    """INSERT 模式前缀（None = 该游戏不使用 INSERT 输入）"""

    sample_input: str
    """合法输入样本，用于 INSERT submit 测试"""

    quit_confirm: str | None
    """退出确认子菜单文本（None = 不允许退出，如斗地主）"""

    help_sections: list[str] = field(default_factory=list)
    """help.txt 中的章节 ID 列表"""


GAMES: dict[str, GameConfig] = {
    'holdem': GameConfig(
        bot_count=1, bot_mode='submenu',
        input_prefix=None, sample_input='',
        quit_confirm='确认退出',
        help_sections=['welcome', 'rules', 'rankings', 'controls', 'commands'],
    ),
    'blackjack': GameConfig(
        bot_count=0, bot_mode=None,
        input_prefix=None, sample_input='',
        quit_confirm='确认退出',
        help_sections=['welcome', 'rules', 'controls', 'commands'],
    ),
    'doudizhu': GameConfig(
        bot_count=2, bot_mode='submenu',
        input_prefix='/play ', sample_input='0',
        quit_confirm=None,  # 斗地主不允许游戏中退出
        help_sections=['welcome', 'rules', 'patterns', 'controls'],
    ),
    'chess': GameConfig(
        bot_count=1, bot_mode='direct',
        input_prefix='/move ', sample_input='e2e4',
        quit_confirm='确认认输',
        help_sections=['welcome', 'rules', 'pieces', 'controls', 'commands'],
    ),
    'mahjong': GameConfig(
        bot_count=3, bot_mode='submenu',
        input_prefix='/discard ', sample_input='0',
        quit_confirm='确认退出',
        help_sections=['welcome', 'rules', 'actions', 'yaku', 'commands'],
    ),
    'wordle': GameConfig(
        bot_count=0, bot_mode=None,
        input_prefix='/guess ', sample_input='crane',
        quit_confirm='确认放弃',
        help_sections=['welcome', 'rules', 'commands'],
    ),
}

ALL_GAME_IDS = list(GAMES.keys())
INSERT_GAME_IDS = [g for g, c in GAMES.items() if c.input_prefix]
