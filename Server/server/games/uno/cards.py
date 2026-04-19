"""UNO Flip 双面牌 — 牌组定义

每张牌有 Light 和 Dark 两面。游戏从 Light Side 开始。
翻转(Flip)时所有牌切换到另一面。

Light Side 颜色: red / yellow / green / blue
Dark Side 颜色: pink / teal / purple / orange

牌面值 (value):
  数字: '0'-'9'
  功能牌(Light): 'draw1' '+1摸一张', 'skip' '⊘跳过', 'reverse' '⇄反转', 'flip' '⟳翻转'
  功能牌(Dark):  'draw5' '+5摸五张', 'skip_all' '⊘⊘跳过所有', 'reverse', 'flip'
  万能牌(Light): 'wild' 'W万能', 'wild_draw2' 'W+2万能摸二'
  万能牌(Dark):  'wild' 'W万能', 'wild_draw_color' 'W+C万能摸色'
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# ── 常量 ──

LIGHT_COLORS = ('red', 'yellow', 'green', 'blue')
DARK_COLORS = ('pink', 'teal', 'purple', 'orange')

# 数值牌的文本缩写（用于 select_menu label）
VALUE_LABELS = {
    '0': '0', '1': '1', '2': '2', '3': '3', '4': '4',
    '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
    'draw1': '+1', 'draw5': '+5',
    'skip': '⊘', 'skip_all': '⊘⊘',
    'reverse': '⇄', 'flip': '⟳',
    'wild': 'W', 'wild_draw2': 'W+2', 'wild_draw_color': 'W+C',
}

# 中文描述（用于 select_menu desc）
VALUE_DESCS = {
    'draw1': '摸一张', 'draw5': '摸五张',
    'skip': '跳过', 'skip_all': '跳过所有人',
    'reverse': '反转', 'flip': '翻转',
    'wild': '万能', 'wild_draw2': '万能+摸二', 'wild_draw_color': '万能+摸色',
}

# 计分
POINT_VALUES = {
    'draw1': 10,
    'draw5': 20, 'reverse': 20, 'skip': 20, 'flip': 20,
    'skip_all': 30,
    'wild': 40,
    'wild_draw2': 50,
    'wild_draw_color': 60,
}

COLOR_NAMES = {
    'red': '红', 'yellow': '黄', 'green': '绿', 'blue': '蓝',
    'pink': '粉', 'teal': '青', 'purple': '紫', 'orange': '橙',
}


# ── 牌 ──

@dataclass(slots=True)
class UnoCard:
    """一张 UNO Flip 双面牌

    light_color/light_value: Light 面属性
    dark_color/dark_value:   Dark 面属性
    side: 当前活跃面 ('light' 或 'dark')
    """
    light_color: str   # 'red'/'yellow'/'green'/'blue' 或 'wild'
    light_value: str   # '0'-'9' / 'draw1'/'skip'/'reverse'/'flip'/'wild'/'wild_draw2'
    dark_color: str    # 'pink'/'teal'/'purple'/'orange' 或 'wild'
    dark_value: str    # '0'-'9' / 'draw5'/'skip_all'/'reverse'/'flip'/'wild'/'wild_draw_color'
    side: str = 'light'

    @property
    def color(self) -> str:
        return self.light_color if self.side == 'light' else self.dark_color

    @property
    def value(self) -> str:
        return self.light_value if self.side == 'light' else self.dark_value

    @property
    def is_wild(self) -> bool:
        return self.color == 'wild'

    @property
    def label(self) -> str:
        """显示用短标签，如 'R7' 或 'W+2'"""
        v = VALUE_LABELS.get(self.value, self.value)
        if self.is_wild:
            return v
        return f'{COLOR_NAMES[self.color]}{v}'

    @property
    def desc(self) -> str:
        """select_menu 用描述"""
        return VALUE_DESCS.get(self.value, '')

    @property
    def points(self) -> int:
        """计分值"""
        if self.value.isdigit():
            return int(self.value)
        return POINT_VALUES.get(self.value, 0)

    def flip(self) -> None:
        self.side = 'dark' if self.side == 'light' else 'light'

    def to_dict(self) -> dict:
        """序列化为可传输的 dict"""
        return {
            'color': self.color,
            'value': self.value,
            'label': self.label,
            'side': self.side,
        }


# ── 牌面生成 ──

def _build_side_cards(colors: tuple[str, ...], is_light: bool) -> list[tuple[str, str]]:
    """生成单面的全部牌定义 → [(color, value), ...]

    每色 26 张 = 1×0 + 2×(1-9) + 2×Skip + 2×Reverse + 2×Draw + 1×Flip
    Wild: 4×Wild + 4×WildDraw = 8
    总计: 26×4 + 8 = 112
    """
    cards = []
    if is_light:
        action_values = ['skip', 'reverse', 'draw1', 'flip']
        wild_draw = 'wild_draw2'
    else:
        action_values = ['skip_all', 'reverse', 'draw5', 'flip']
        wild_draw = 'wild_draw_color'

    for color in colors:
        # 0 × 1
        cards.append((color, '0'))
        # 1-9 × 2
        for num in range(1, 10):
            cards.append((color, str(num)))
            cards.append((color, str(num)))
        # 功能牌: skip/reverse/draw 各 ×2, flip ×1
        for val in action_values:
            cards.append((color, val))
            if val != 'flip':
                cards.append((color, val))

    # Wild × 4
    for _ in range(4):
        cards.append(('wild', 'wild'))
    # Wild Draw × 4
    for _ in range(4):
        cards.append(('wild', wild_draw))

    return cards


# ── 牌组 ──

class UnoDeck:
    """UNO Flip 牌组 — 112 张双面牌"""

    def __init__(self):
        light_cards = _build_side_cards(LIGHT_COLORS, is_light=True)
        dark_cards = _build_side_cards(DARK_COLORS, is_light=False)
        assert len(light_cards) == len(dark_cards) == 112, \
            f'牌数不对: light={len(light_cards)}, dark={len(dark_cards)}'

        # 随机配对: 分别洗牌后一一对应
        random.shuffle(light_cards)
        random.shuffle(dark_cards)

        self._cards: list[UnoCard] = []
        for (lc, lv), (dc, dv) in zip(light_cards, dark_cards):
            self._cards.append(UnoCard(lc, lv, dc, dv, side='light'))

    def shuffle(self) -> None:
        random.shuffle(self._cards)

    def draw(self, n: int = 1) -> list[UnoCard]:
        """摸 n 张牌。牌堆不足时返回剩余全部。"""
        drawn = self._cards[:n]
        self._cards = self._cards[n:]
        return drawn

    def draw_one(self) -> UnoCard | None:
        return self._cards.pop(0) if self._cards else None

    def put_bottom(self, cards: list[UnoCard]) -> None:
        """将牌放到牌堆底部"""
        self._cards.extend(cards)

    def flip_all(self) -> None:
        """翻转牌堆中所有牌"""
        for card in self._cards:
            card.flip()

    @property
    def remaining(self) -> int:
        return len(self._cards)

    def reshuffle_from(self, discard_pile: list[UnoCard]) -> None:
        """用弃牌堆重建摸牌堆（保留弃牌堆顶牌）

        discard_pile[-1] 是顶牌，保留。其余洗入牌堆。
        """
        if len(discard_pile) <= 1:
            return
        top = discard_pile[-1]
        rest = discard_pile[:-1]
        discard_pile.clear()
        discard_pile.append(top)
        random.shuffle(rest)
        self._cards.extend(rest)

    @property
    def cards(self) -> list[UnoCard]:
        return self._cards


def can_play(card: UnoCard, top: UnoCard, chosen_color: str | None) -> bool:
    """判断 card 是否可以打在 top 上

    chosen_color: 上一张 Wild 指定的颜色（覆盖 top.color）
    """
    if card.is_wild:
        return True
    effective_color = chosen_color or top.color
    if card.color == effective_color:
        return True
    if card.value == top.value:
        return True
    return False
