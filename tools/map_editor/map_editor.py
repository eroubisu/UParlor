"""独立 TUI 地图编辑器 — 与游戏完全无关, 仅用于编辑地图 JSON."""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Input
from textual.containers import Vertical

TILE_TYPES: dict[str, dict] = {
    # ── 功能 ──
    ' ': {'name': '空白', 'walkable': False, 'char': ' ', 'color': '#303030'},
    '+': {'name': '门', 'walkable': True, 'char': '+', 'color': '#d0a050'},
    '?': {'name': '告示牌', 'walkable': True, 'char': '?', 'color': '#b8b8b8'},
    '%': {'name': '传送点', 'walkable': True, 'char': '%', 'color': '#8a6ab8'},
    'N': {'name': 'NPC', 'walkable': True, 'char': 'N', 'color': '#e0c060'},
    'S': {'name': '出生点', 'walkable': True, 'char': 'S', 'color': '#ff6060'},
    # ── 地面 ──
    '.': {'name': '草地', 'walkable': True, 'char': '.', 'color': '#5a9a3a', 'cd_mult': 1.15},
    'o': {'name': '地板', 'walkable': True, 'char': '.', 'color': '#6a6a5a'},
    ',': {'name': '泥土', 'walkable': True, 'char': ',', 'color': '#9a7a4a', 'cd_mult': 1.1},
    ':': {'name': '沙地', 'walkable': True, 'char': ':', 'color': '#d0b860', 'cd_mult': 1.5},
    '_': {'name': '雪地', 'walkable': True, 'char': '_', 'color': '#d0d8e8', 'cd_mult': 1.3},
    'i': {'name': '冰面', 'walkable': True, 'char': '~', 'color': '#a0d0e8', 'cd_mult': 0.7,
           'desc': '冷却×0.7'},
    'm': {'name': '沼泽', 'walkable': True, 'char': '~', 'color': '#5a7040', 'cd_mult': 2.0,
           'damage': 2, 'concealment': True, 'desc': '冷却×2.0 每步2伤 隐蔽'},
    'e': {'name': '熔岩地面', 'walkable': True, 'char': ':', 'color': '#c04020', 'cd_mult': 1.3,
           'damage': 5, 'desc': '冷却×1.3 每步5伤'},
    'j': {'name': '矿石地面', 'walkable': True, 'char': '.', 'color': '#8a8060', 'cd_mult': 1.2},
    'x': {'name': '碎石', 'walkable': True, 'char': ',', 'color': '#808080', 'cd_mult': 1.4},
    '1': {'name': '石砖地', 'walkable': True, 'char': '.', 'color': '#a09880'},
    '9': {'name': '落叶', 'walkable': True, 'char': ',', 'color': '#b08030', 'cd_mult': 1.1},
    '/': {'name': '土路', 'walkable': True, 'char': '.', 'color': '#9a8050'},
    '2': {'name': '农田', 'walkable': True, 'char': '#', 'color': '#6a8a40', 'cd_mult': 1.3},
    'd': {'name': '苔石地', 'walkable': True, 'char': '.', 'color': '#5a7a5a', 'cd_mult': 1.2},
    # ── 水体 ──
    '~': {'name': '水', 'walkable': False, 'char': '~', 'color': '#3060a0', 'water': True},
    'w': {'name': '浅水', 'walkable': True, 'char': '~', 'color': '#60b0d8', 'cd_mult': 1.8,
           'water': True},
    'l': {'name': '岩浆', 'walkable': False, 'char': '~', 'color': '#e05020'},
    # ── 墙体 ──
    '#': {'name': '石墙', 'walkable': False, 'char': '#', 'color': '#a0a0a0'},
    'W': {'name': '木墙', 'walkable': False, 'char': '#', 'color': '#8a7050'},
    'r': {'name': '岩壁', 'walkable': False, 'char': '#', 'color': '#706050'},
    '^': {'name': '屋顶', 'walkable': False, 'char': '^', 'color': '#b07040'},
    'z': {'name': '瓦片屋顶', 'walkable': False, 'char': '~', 'color': '#906050'},
    'X': {'name': '残垣', 'walkable': False, 'char': '#', 'color': '#605050'},
    'y': {'name': '铁栏', 'walkable': False, 'char': '|', 'color': '#808890'},
    '|': {'name': '栅栏', 'walkable': False, 'char': '|', 'color': '#907050'},
    'h': {'name': '篱笆', 'walkable': False, 'char': '-', 'color': '#708050'},
    # ── 植物 ──
    'T': {'name': '树木', 'walkable': False, 'char': 'T', 'color': '#2a7a2a', 'fade': True},
    '7': {'name': '松树', 'walkable': False, 'char': 'T', 'color': '#1a6030', 'fade': True},
    't': {'name': '枯树', 'walkable': False, 'char': 'T', 'color': '#706040', 'fade': True},
    '*': {'name': '灌木', 'walkable': True, 'char': '*', 'color': '#408030', 'cd_mult': 1.3,
           'fade': True},
    'F': {'name': '花丛', 'walkable': True, 'char': ';', 'color': '#80b050', 'cd_mult': 1.1},
    'g': {'name': '高草', 'walkable': True, 'char': '"', 'color': '#4a8a30', 'cd_mult': 1.2,
           'concealment': True, 'desc': '冷却×1.2 隐蔽'},
    'v': {'name': '藤蔓', 'walkable': True, 'char': '}', 'color': '#3a7a3a', 'cd_mult': 1.4},
    '5': {'name': '荆棘', 'walkable': True, 'char': '*', 'color': '#3a6a20', 'cd_mult': 1.5,
           'damage': 1, 'desc': '冷却×1.5 每步1伤'},
    '8': {'name': '仙人掌', 'walkable': False, 'char': '*', 'color': '#7a9a30'},
    'K': {'name': '蘑菇', 'walkable': True, 'char': ';', 'color': '#a05050'},
    '<': {'name': '苇丛', 'walkable': False, 'char': ';', 'color': '#6a9a50', 'fade': True},
    'H': {'name': '干草', 'walkable': True, 'char': ',', 'color': '#c0a040', 'cd_mult': 1.2},
    '6': {'name': '竹林', 'walkable': False, 'char': '|', 'color': '#50a050', 'fade': True},
    # ── 道路 ──
    '=': {'name': '石路', 'walkable': True, 'char': '=', 'color': '#c0b890'},
    'P': {'name': '广场', 'walkable': True, 'char': '.', 'color': '#d0c8a0'},
    'B': {'name': '木桥', 'walkable': True, 'char': '=', 'color': '#b0a070'},
    'O': {'name': '岩石', 'walkable': True, 'char': 'O', 'color': '#909090', 'cd_mult': 1.5,
           'fade': True},
    'p': {'name': '木板路', 'walkable': True, 'char': '=', 'color': '#907050'},
    'k': {'name': '石阶', 'walkable': True, 'char': '=', 'color': '#909080'},
    'E': {'name': '台阶', 'walkable': True, 'char': '=', 'color': '#a09080'},
    'R': {'name': '地砖', 'walkable': True, 'char': '.', 'color': '#8a8070'},
    # ── 室内 ──
    '-': {'name': '桌子', 'walkable': False, 'char': '-', 'color': '#7a6a5a'},
    'c': {'name': '椅子', 'walkable': True, 'char': 'o', 'color': '#6a5a4a'},
    'b': {'name': '架子', 'walkable': False, 'char': 'H', 'color': '#6a5a3a'},
    ')': {'name': '柱子', 'walkable': False, 'char': '|', 'color': '#a09080'},
    'f': {'name': '炉火', 'walkable': False, 'char': '*', 'color': '#c87832'},
    '{': {'name': '壁炉', 'walkable': False, 'char': '*', 'color': '#c06030'},
    '}': {'name': '灶台', 'walkable': False, 'char': '#', 'color': '#5a5a5a'},
    'a': {'name': '铁砧', 'walkable': False, 'char': 'A', 'color': '#7a7a7a'},
    's': {'name': '木桶', 'walkable': False, 'char': 'U', 'color': '#6a5a3a'},
    'q': {'name': '酒桶', 'walkable': False, 'char': 'O', 'color': '#7a5a3a'},
    'u': {'name': '柜台', 'walkable': False, 'char': '|', 'color': '#7a6a5a'},
    'n': {'name': '渔网', 'walkable': False, 'char': 'W', 'color': '#5a7a8a'},
    ';': {'name': '烛台', 'walkable': False, 'char': 'i', 'color': '#d0a030'},
    '[': {'name': '窗户', 'walkable': False, 'char': 'O', 'color': '#8ab0d0'},
    ']': {'name': '画框', 'walkable': False, 'char': '=', 'color': '#8a7050'},
    '(': {'name': '坐垫', 'walkable': True, 'char': 'o', 'color': '#a04040'},
    'J': {'name': '床', 'walkable': False, 'char': '=', 'color': '#806050'},
    'D': {'name': '地毯', 'walkable': True, 'char': ':', 'color': '#8a4040'},
    'C': {'name': '箱子', 'walkable': False, 'char': '#', 'color': '#7a6040'},
    'Y': {'name': '武器架', 'walkable': False, 'char': 'X', 'color': '#808080'},
    # ── 洞穴 ──
    '0': {'name': '深渊', 'walkable': False, 'char': ' ', 'color': '#101010'},
    '3': {'name': '蛛网', 'walkable': True, 'char': '%', 'color': '#909090', 'cd_mult': 1.5,
           'concealment': True, 'desc': '冷却×1.5 隐蔽'},
    '4': {'name': '水晶', 'walkable': False, 'char': '*', 'color': '#60b0c0'},
    '&': {'name': '骨堆', 'walkable': True, 'char': '&', 'color': '#c0b8a0', 'cd_mult': 1.3},
    '!': {'name': '陷阱', 'walkable': True, 'char': '.', 'color': '#8a8060', 'damage': 3,
           'desc': '每步3伤'},
    '@': {'name': '宝箱', 'walkable': False, 'char': '#', 'color': '#c0a040'},
    'Z': {'name': '矿石', 'walkable': False, 'char': '*', 'color': '#6080a0'},
    '$': {'name': '祭坛', 'walkable': False, 'char': '#', 'color': '#8060a0'},
    # ── 户外 ──
    'L': {'name': '灯柱', 'walkable': False, 'char': '!', 'color': '#d0b060'},
    'V': {'name': '花盆', 'walkable': False, 'char': 'Y', 'color': '#6a9a4a'},
    'M': {'name': '雕像', 'walkable': False, 'char': '&', 'color': '#b0b0b0'},
    'A': {'name': '旗帜', 'walkable': False, 'char': 'P', 'color': '#c06040'},
    'G': {'name': '墓碑', 'walkable': False, 'char': 'T', 'color': '#707070'},
    'I': {'name': '井', 'walkable': False, 'char': 'O', 'color': '#506080'},
    'U': {'name': '火把', 'walkable': False, 'char': 'i', 'color': '#d09030'},
    'Q': {'name': '帐篷', 'walkable': False, 'char': '^', 'color': '#907060'},
    '>': {'name': '杂物', 'walkable': True, 'char': ',', 'color': '#706050', 'cd_mult': 1.4},
}

_PREVIEW_COLORS: dict[str, tuple[int, int, int]] = {
    ' ': (0, 0, 0),
    # 地面
    '.': (60, 100, 60), 'o': (90, 90, 75), ',': (110, 100, 70),
    ':': (160, 145, 100), '_': (180, 190, 210), 'i': (140, 190, 210),
    'm': (70, 90, 50), 'e': (160, 50, 25), 'j': (110, 105, 75),
    'x': (105, 105, 95), '1': (130, 125, 105), '9': (145, 105, 40),
    '/': (125, 105, 65), '2': (85, 110, 50), 'd': (70, 100, 70),
    # 水体
    '~': (40, 60, 130), 'w': (75, 150, 190), 'l': (190, 60, 25),
    # 墙体
    '#': (120, 120, 120), 'W': (115, 95, 65), 'r': (90, 80, 65),
    '^': (120, 90, 60), 'z': (120, 80, 65), 'X': (80, 65, 65),
    'y': (100, 105, 115), '|': (90, 75, 55), 'h': (90, 105, 65),
    # 植物
    'T': (34, 80, 34), '7': (20, 75, 38), 't': (90, 80, 50),
    '*': (40, 70, 40), 'F': (80, 140, 60), 'g': (55, 110, 40),
    'v': (45, 95, 45), '5': (45, 85, 25), '8': (100, 125, 38),
    'K': (130, 65, 65), '<': (85, 125, 65), 'H': (155, 130, 50),
    '6': (60, 130, 60),
    # 道路
    '=': (130, 130, 100), 'P': (150, 145, 115), 'B': (130, 120, 90),
    'O': (110, 110, 110), 'p': (120, 95, 65), 'k': (120, 120, 110),
    'E': (130, 115, 100), 'R': (110, 105, 90),
    # 室内
    '-': (100, 85, 70), 'c': (85, 70, 55), 'b': (85, 70, 45),
    ')': (130, 115, 100), 'f': (170, 100, 40), '{': (155, 80, 40),
    '}': (72, 72, 72), 'a': (95, 95, 100), 's': (85, 73, 45),
    'q': (100, 73, 45), 'u': (100, 85, 70), 'n': (70, 100, 110),
    ';': (170, 130, 40), '[': (110, 145, 170), ']': (110, 90, 65),
    '(': (130, 50, 50), 'J': (105, 80, 65), 'D': (110, 50, 50),
    'C': (100, 80, 50), 'Y': (105, 105, 105),
    # 洞穴
    '0': (8, 8, 8), '3': (115, 115, 115), '4': (75, 145, 155),
    '&': (155, 150, 130), '!': (110, 105, 75), '@': (155, 130, 50),
    'Z': (80, 105, 130), '$': (105, 75, 130),
    # 户外
    'L': (170, 145, 80), 'V': (85, 125, 60), 'M': (140, 140, 140),
    'A': (155, 80, 55), 'G': (90, 90, 90), 'I': (65, 80, 105),
    'U': (170, 120, 40), 'Q': (115, 90, 75), '>': (90, 78, 65),
    # 功能
    '+': (160, 130, 80), '?': (180, 180, 180), '%': (120, 80, 170),
    'N': (200, 170, 80), 'S': (255, 80, 80),
}

TILE_TABS: list[tuple[str, list[str]]] = [
    ('地面', ['.', 'o', ',', ':', '_', 'i', 'm', 'e', 'j', 'x', '1', '9', '/', '2']),
    ('水体', ['~', 'w', 'l']),
    ('墙体', ['#', 'W', 'r', '^', 'z', 'X', 'y', '|', 'h']),
    ('植物', ['T', '7', 't', '*', 'F', 'g', 'v', '5', '8', 'K', '<', 'H', '6']),
    ('道路', ['=', 'P', 'B', 'O', 'p', 'k', 'E', 'R']),
    ('家具', ['-', 'c', 'b', ')', 'f', '{', '}', 'a', 's', 'q', 'u', 'n']),
    ('陈设', [';', '[', ']', '(', 'J', 'D', 'C', 'Y']),
    ('洞穴', ['d', '0', '3', '4', '&', '!', '@', 'Z', '$']),
    ('户外', ['L', 'V', 'M', 'A', 'G', 'I', 'U', 'Q', '>']),
    ('功能', ['+', '?', '%', 'N', 'S']),
]


def _save_preview(tiles: list[list[str]], out_path: str) -> None:
    h = len(tiles)
    w = len(tiles[0]) if tiles else 0
    sx_s, sy_s = 4, 8
    img = Image.new('RGB', (w * sx_s, h * sy_s))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        for x in range(w):
            c = _PREVIEW_COLORS.get(tiles[y][x], (0, 0, 0))
            draw.rectangle([x * sx_s, y * sy_s,
                            (x + 1) * sx_s - 1, (y + 1) * sy_s - 1], fill=c)
    # 仅在不同地块类型之间画分隔线
    border = (255, 255, 255)
    for y in range(h):
        for x in range(w):
            ch = tiles[y][x]
            # 右侧邻居不同 → 画竖线
            if x + 1 < w and tiles[y][x + 1] != ch:
                bx = (x + 1) * sx_s
                draw.line([(bx, y * sy_s), (bx, (y + 1) * sy_s - 1)], fill=border)
            # 下方邻居不同 → 画横线
            if y + 1 < h and tiles[y + 1][x] != ch:
                by = (y + 1) * sy_s
                draw.line([(x * sx_s, by), ((x + 1) * sx_s - 1, by)], fill=border)
    img.save(out_path, quality=95)


class InputPrompt(Vertical):
    """底部输入栏, 用于门目标/告示牌文本."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._active = False
        self._callback: callable | None = None

    def compose(self) -> ComposeResult:
        yield Input(id='prompt-input', placeholder='')

    def on_mount(self) -> None:
        self.display = False

    def show(self, label: str, callback: callable) -> None:
        self._active = True
        self._callback = callback
        inp = self.query_one('#prompt-input', Input)
        inp.value = ''
        inp.placeholder = f'{label} (Enter确认 / Esc取消)'
        self.display = True
        inp.focus()

    def close(self) -> None:
        self._active = False
        self._callback = None
        self.display = False
        try:
            self.app.query_one('#map-canvas', MapCanvas).focus()
        except Exception:
            pass

    def is_active(self) -> bool:
        return self._active

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cb = self._callback
        val = event.value.strip()
        self.close()
        if cb and val:
            cb(val)

    def on_key(self, event: events.Key) -> None:
        if event.key == 'escape' and self._active:
            self.close()
            event.prevent_default()
            event.stop()


# 空白区域渲染常量
_FADE_CHAR = '░'
_FADE_COLOR = '#404040'
_INSIDE_CHAR = ' '
_INSIDE_COLOR = '#1a1a1a'


def _calc_outside_mask(tiles: list[list[str]]) -> set[tuple[int, int]]:
    """从地图边缘洪水填充, 找出所有与边缘相连的空白(' ')区域."""
    h = len(tiles)
    w = len(tiles[0]) if tiles else 0
    outside: set[tuple[int, int]] = set()
    stack: list[tuple[int, int]] = []
    # 从四条边播种
    for x in range(w):
        if tiles[0][x] == ' ':
            stack.append((x, 0))
        if tiles[h - 1][x] == ' ':
            stack.append((x, h - 1))
    for y in range(h):
        if tiles[y][0] == ' ':
            stack.append((0, y))
        if tiles[y][w - 1] == ' ':
            stack.append((w - 1, y))
    while stack:
        cx, cy = stack.pop()
        if (cx, cy) in outside:
            continue
        if cx < 0 or cx >= w or cy < 0 or cy >= h:
            continue
        if tiles[cy][cx] != ' ':
            continue
        outside.add((cx, cy))
        stack.extend([(cx-1, cy), (cx+1, cy), (cx, cy-1), (cx, cy+1)])
    return outside


class MapCanvas(Widget, can_focus=True):
    cursor_x: reactive[int] = reactive(0)
    cursor_y: reactive[int] = reactive(0)

    def __init__(self, tiles: list[list[str]], **kw) -> None:
        super().__init__(**kw)
        self.tiles = tiles
        self.map_h = len(tiles)
        self.map_w = len(tiles[0]) if tiles else 0
        self._outside_mask: set[tuple[int, int]] = _calc_outside_mask(tiles)

    def invalidate_mask(self) -> None:
        self._outside_mask = _calc_outside_mask(self.tiles)

    def on_key(self, event: events.Key) -> None:
        if event.key == 'ctrl+s':
            return
        app: MapEditorApp = self.app  # type: ignore[assignment]
        # InputPrompt 有自己的 Input 组件处理键盘, 不在这里拦截
        prompt = app.query_one('#input-prompt', InputPrompt)
        if prompt.is_active():
            return
        app.handle_key(event)
        event.prevent_default()
        event.stop()

    def render(self) -> Text:
        w = self.size.width
        h = self.size.height
        if w < 1 or h < 1:
            return Text('')
        vp_x = max(0, min(self.cursor_x - w // 2, self.map_w - w))
        vp_y = max(0, min(self.cursor_y - h // 2, self.map_h - h))
        result = Text()
        for sy in range(h):
            my = vp_y + sy
            for sx in range(w):
                mx = vp_x + sx
                if my < 0 or my >= self.map_h or mx < 0 or mx >= self.map_w:
                    result.append(' ')
                    continue
                ch = self.tiles[my][mx]
                info = TILE_TYPES.get(ch, TILE_TYPES[' '])
                if mx == self.cursor_x and my == self.cursor_y:
                    if ch == ' ':
                        is_out = (mx, my) in self._outside_mask
                        result.append(_FADE_CHAR if is_out else _INSIDE_CHAR,
                                      'bold reverse #ffff00')
                    else:
                        result.append(info['char'], 'bold reverse #ffff00')
                elif ch == ' ':
                    if (mx, my) in self._outside_mask:
                        result.append(_FADE_CHAR, _FADE_COLOR)
                    else:
                        result.append(_INSIDE_CHAR, _INSIDE_COLOR)
                else:
                    result.append(info['char'], info['color'])
            if sy < h - 1:
                result.append('\n')
        return result

    def move_cursor(self, dx: int, dy: int) -> None:
        self.cursor_x = max(0, min(self.cursor_x + dx, self.map_w - 1))
        self.cursor_y = max(0, min(self.cursor_y + dy, self.map_h - 1))

    def set_tile(self, ch: str) -> None:
        if 0 <= self.cursor_y < self.map_h and 0 <= self.cursor_x < self.map_w:
            self.tiles[self.cursor_y][self.cursor_x] = ch
            self.invalidate_mask()
            self.refresh()

    def flood_fill(self, ch: str) -> None:
        """从光标位置开始洪水填充, 将连通的同类型瓦片替换为 ch."""
        x, y = self.cursor_x, self.cursor_y
        if x < 0 or x >= self.map_w or y < 0 or y >= self.map_h:
            return
        old = self.tiles[y][x]
        if old == ch:
            return
        stack = [(x, y)]
        visited = set()
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in visited:
                continue
            if cx < 0 or cx >= self.map_w or cy < 0 or cy >= self.map_h:
                continue
            if self.tiles[cy][cx] != old:
                continue
            visited.add((cx, cy))
            self.tiles[cy][cx] = ch
            stack.extend([(cx-1, cy), (cx+1, cy), (cx, cy-1), (cx, cy+1)])
        self.invalidate_mask()
        self.refresh()

    def get_tile(self) -> str:
        if 0 <= self.cursor_y < self.map_h and 0 <= self.cursor_x < self.map_w:
            return self.tiles[self.cursor_y][self.cursor_x]
        return ' '

    def watch_cursor_x(self) -> None:
        self.refresh()

    def watch_cursor_y(self) -> None:
        self.refresh()


class TilePalette(Static):
    selected_tab: reactive[int] = reactive(0)
    selected_idx: reactive[int] = reactive(0)

    _MAX_VISIBLE = 12  # 面板最多同时显示的条目数

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._open = False
        self._scroll_off = 0

    def _rebuild(self) -> None:
        if not self._open:
            self.update('')
            self.display = False
            return
        self.display = True
        result = Text()
        for i, (name, _) in enumerate(TILE_TABS):
            if i == self.selected_tab:
                result.append(f' {name} ', 'bold reverse #ffffff')
            else:
                result.append(f' {name} ', '#808080')
            result.append(' ')
        result.append('\n')
        result.append('─' * 30 + '\n', '#454545')
        _, items = TILE_TABS[self.selected_tab]
        total = len(items)
        vis = self._MAX_VISIBLE
        # 保证 selected_idx 在可见范围内
        if self.selected_idx < self._scroll_off:
            self._scroll_off = self.selected_idx
        elif self.selected_idx >= self._scroll_off + vis:
            self._scroll_off = self.selected_idx - vis + 1
        start = self._scroll_off
        end = min(start + vis, total)
        if start > 0:
            result.append(f'  ▲ 还有 {start} 项\n', '#606060')
        for i in range(start, end):
            key = items[i]
            info = TILE_TYPES[key]
            prefix = '▸ ' if i == self.selected_idx else '  '
            style = 'bold #ffffff' if i == self.selected_idx else '#b3b3b3'
            result.append(prefix, style)
            result.append(f'{info["char"]} ', info['color'])
            walk = '✓' if info.get('walkable') else '✗'
            desc = info.get('desc', '')
            suffix = f' ({desc})' if desc else ''
            result.append(f'{info["name"]} {walk}{suffix}\n', style)
        if end < total:
            result.append(f'  ▼ 还有 {total - end} 项\n', '#606060')
        result.append('\n', '')
        result.append('h/l 标签  j/k 选择  Enter 确认  f 填充模式  Esc 关闭', '#808080')
        self.update(result)

    def on_mount(self) -> None:
        self.display = False

    def toggle(self) -> None:
        self._open = not self._open
        self.selected_idx = 0
        self._scroll_off = 0
        self._rebuild()

    def is_open(self) -> bool:
        return self._open

    def close(self) -> None:
        self._open = False
        self._rebuild()

    def nav_tab(self, d: int) -> None:
        self.selected_tab = (self.selected_tab + d) % len(TILE_TABS)
        self.selected_idx = 0
        self._scroll_off = 0
        self._rebuild()

    def nav_item(self, d: int) -> None:
        _, items = TILE_TABS[self.selected_tab]
        self.selected_idx = (self.selected_idx + d) % len(items)
        self._rebuild()

    def get_selected_key(self) -> str:
        _, items = TILE_TABS[self.selected_tab]
        return items[self.selected_idx]


class MapEditorApp(App):
    CSS = """
    #editor-main { width: 1fr; height: 1fr; }
    #map-canvas { width: 1fr; height: 1fr; }
    #status-line {
        dock: bottom; height: 1;
        background: #1a1a1a; color: #b3b3b3;
    }
    #tile-palette {
        dock: bottom; height: auto; max-height: 20;
        background: #1a1a1a; border-top: solid #454545;
        overflow-y: auto;
    }
    #input-prompt {
        dock: bottom; height: 3;
        background: #2a2a4a;
    }
    #prompt-input {
        background: #3a3a6a; color: #ffffff;
        border: tall #5a5a8a; height: 3;
    }
    """

    BINDINGS = [Binding('ctrl+s', 'save', '保存'),
                Binding('ctrl+d', 'deploy', '部署到游戏目录')]

    def __init__(self, map_path: str, out_dir: str, game_dir: str,
                 preview_dir: str | None = None) -> None:
        super().__init__()
        self.map_path = map_path
        self.out_dir = out_dir
        self.game_dir = game_dir
        self.preview_dir = preview_dir or out_dir
        with open(map_path, 'r', encoding='utf-8') as f:
            self.map_data: dict = json.load(f)
        self.tiles = [list(row) for row in self.map_data['tiles']]
        self._dirty = False
        self._fill_mode = False
        self._painting = False               # 拖拽绘制模式
        self._last_tile: str | None = None   # 上次放置的 tile key
        self._last_arg: str = ''              # 上次的输入参数（门目标/告示牌文本/NPC id）
        # door_map: {(x,y): {building_id, name}}, sign_map: {(x,y): text}, npc_map: {(x,y): npc_id}
        self._door_map: dict[tuple[int,int], dict] = {}
        self._sign_map: dict[tuple[int,int], str] = {}
        self._npc_map: dict[tuple[int,int], str] = {}
        self._load_metadata()

    def compose(self) -> ComposeResult:
        yield Vertical(
            MapCanvas(self.tiles, id='map-canvas'),
            TilePalette(id='tile-palette'),
            InputPrompt(id='input-prompt'),
            Static(id='status-line'),
            id='editor-main',
        )

    def _load_metadata(self) -> None:
        for bid, bdata in self.map_data.get('buildings', {}).items():
            info = {'building_id': bid, 'name': bdata.get('name', bid)}
            for dx, dy in bdata.get('doors', []):
                self._door_map[(dx, dy)] = info
        for s in self.map_data.get('signs', []):
            pos = s.get('pos', [0, 0])
            self._sign_map[(pos[0], pos[1])] = s.get('text', '')
        for npc in self.map_data.get('npcs', []):
            pos = npc.get('pos', [0, 0])
            self._npc_map[(pos[0], pos[1])] = npc.get('id', '')

    def _find_spawn_pos(self) -> tuple[int, int] | None:
        """在 tiles 中查找 S 地块位置"""
        for y, row in enumerate(self.tiles):
            for x, ch in enumerate(row):
                if ch == 'S':
                    return (x, y)
        return None

    def _is_starter_town(self) -> bool:
        return self.map_data.get('meta', {}).get('id') == 'starter_town'

    def on_mount(self) -> None:
        canvas = self.query_one('#map-canvas', MapCanvas)
        sp = self._find_spawn_pos()
        if sp:
            canvas.cursor_x, canvas.cursor_y = sp
        else:
            spawn = self.map_data.get('spawn', [0, 0])
            canvas.cursor_x = spawn[0]
            canvas.cursor_y = spawn[1]
        canvas.focus()
        self._update_status()

    def handle_key(self, event: events.Key) -> None:
        palette = self.query_one('#tile-palette', TilePalette)
        canvas = self.query_one('#map-canvas', MapCanvas)

        if palette.is_open():
            key = event.key
            if key in ('escape', 'q'):
                palette.close()
                self._fill_mode = False
            elif key in ('h', 'a', 'left'):
                palette.nav_tab(-1)
            elif key in ('l', 'd', 'right'):
                palette.nav_tab(1)
            elif key in ('j', 's', 'down'):
                palette.nav_item(1)
            elif key in ('k', 'w', 'up'):
                palette.nav_item(-1)
            elif key == 'f':
                self._fill_mode = not self._fill_mode
                palette._rebuild()
            elif key == 'enter':
                tile_key = palette.get_selected_key()
                if self._fill_mode:
                    canvas.flood_fill(tile_key)
                    self._fill_mode = False
                    self._dirty = True
                    self._last_tile = tile_key
                    self._last_arg = ''
                    palette.close()
                elif tile_key == '+':
                    palette.close()
                    prompt = self.query_one('#input-prompt', InputPrompt)
                    prompt.show('目标地图名', lambda name: self._place_door(
                        canvas, {'building_id': name, 'name': name}))
                elif tile_key == '?':
                    palette.close()
                    prompt = self.query_one('#input-prompt', InputPrompt)
                    prompt.show('告示牌文本', lambda text: self._place_sign(canvas, text))
                elif tile_key == 'N':
                    palette.close()
                    prompt = self.query_one('#input-prompt', InputPrompt)
                    prompt.show('NPC唯一标识符', lambda nid: self._place_npc(canvas, nid))
                else:
                    if tile_key == 'S':
                        if not self._place_spawn(canvas):
                            palette.close()
                            self._update_status()
                            return
                    else:
                        self._remove_meta(canvas.cursor_x, canvas.cursor_y)
                    canvas.set_tile(tile_key)
                    self._dirty = True
                    self._last_tile = tile_key
                    self._last_arg = ''
                    palette.close()
            self._update_status()
            return

        key = event.key
        moved = False
        if key in ('h', 'a', 'left'):
            canvas.move_cursor(-1, 0); moved = True
        elif key in ('l', 'd', 'right'):
            canvas.move_cursor(1, 0); moved = True
        elif key in ('k', 'w', 'up'):
            canvas.move_cursor(0, -1); moved = True
        elif key in ('j', 's', 'down'):
            canvas.move_cursor(0, 1); moved = True
        elif key in ('H', 'shift+h', 'A', 'shift+a'):
            canvas.move_cursor(-10, 0)
        elif key in ('L', 'shift+l', 'D', 'shift+d'):
            canvas.move_cursor(10, 0)
        elif key in ('K', 'shift+k', 'W', 'shift+w'):
            canvas.move_cursor(0, -10)
        elif key in ('J', 'shift+j', 'S', 'shift+s'):
            canvas.move_cursor(0, 10)
        elif key == 'p':
            self._fill_mode = False
            self._painting = False
            palette.toggle()
        elif key == 'e':
            self._painting = not self._painting
        elif key == 'enter':
            self._repeat_last(canvas)
        elif key == 'f':
            self._fill_mode = True
            self._painting = False
            palette.toggle()
        elif key == 'x':
            self._remove_meta(canvas.cursor_x, canvas.cursor_y)
            canvas.set_tile(' ')
            self._dirty = True
        elif key == 'q':
            self.action_quit()
        # 拖拽绘制: 移动时若有 _last_tile 且为普通地块, 自动放置
        if moved and self._painting and self._last_tile:
            t = self._last_tile
            if t not in ('+', '?', 'N', 'S'):
                self._remove_meta(canvas.cursor_x, canvas.cursor_y)
                canvas.set_tile(t)
                self._dirty = True
        self._update_status()

    def _repeat_last(self, canvas: MapCanvas) -> None:
        """Enter 重复上次放置"""
        if not self._last_tile:
            return
        if self._last_tile == '+':
            prompt = self.query_one('#input-prompt', InputPrompt)
            prompt.show('目标地图名', lambda name: self._place_door(
                canvas, {'building_id': name, 'name': name}))
        elif self._last_tile == '?':
            prompt = self.query_one('#input-prompt', InputPrompt)
            prompt.show('告示牌文本', lambda text: self._place_sign(canvas, text))
        elif self._last_tile == 'N':
            prompt = self.query_one('#input-prompt', InputPrompt)
            prompt.show('NPC唯一标识符', lambda nid: self._place_npc(canvas, nid))
        elif self._last_tile == 'S':
            if self._place_spawn(canvas):
                canvas.set_tile('S')
                self._dirty = True
        else:
            self._remove_meta(canvas.cursor_x, canvas.cursor_y)
            canvas.set_tile(self._last_tile)
            self._dirty = True

    def _place_spawn(self, canvas: MapCanvas) -> bool:
        """放置出生点, 返回是否成功"""
        if not self._is_starter_town():
            self.notify('出生点只能放在 starter_town 地图中')
            return False
        x, y = canvas.cursor_x, canvas.cursor_y
        # 清除旧的出生点
        old = self._find_spawn_pos()
        if old and old != (x, y):
            self.tiles[old[1]][old[0]] = '.'
        self._remove_meta(x, y)
        return True

    def _place_door(self, canvas: MapCanvas, info: dict) -> None:
        x, y = canvas.cursor_x, canvas.cursor_y
        bid = info['building_id']
        # 同一个目标地图只能有一扇门
        for pos, d in self._door_map.items():
            if d['building_id'] == bid and pos != (x, y):
                self.notify(f'已存在指向 {bid} 的门 ({pos[0]},{pos[1]})，每个目标只能一扇门')
                return
        self._remove_meta(x, y)
        canvas.set_tile('+')
        self._door_map[(x, y)] = info
        self._last_tile = '+'
        self._last_arg = info
        self._dirty = True
        self._update_status()

    def _place_sign(self, canvas: MapCanvas, text: str) -> None:
        x, y = canvas.cursor_x, canvas.cursor_y
        self._remove_meta(x, y)
        canvas.set_tile('?')
        self._sign_map[(x, y)] = text
        self._last_tile = '?'
        self._last_arg = text
        self._dirty = True
        self._update_status()

    def _place_npc(self, canvas: MapCanvas, npc_id: str) -> None:
        x, y = canvas.cursor_x, canvas.cursor_y
        self._remove_meta(x, y)
        canvas.set_tile('N')
        self._npc_map[(x, y)] = npc_id
        self._last_tile = 'N'
        self._last_arg = npc_id
        self._dirty = True
        self._update_status()

    def _remove_meta(self, x: int, y: int) -> None:
        self._door_map.pop((x, y), None)
        self._sign_map.pop((x, y), None)
        self._npc_map.pop((x, y), None)

    def _update_status(self) -> None:
        canvas = self.query_one('#map-canvas', MapCanvas)
        x, y = canvas.cursor_x, canvas.cursor_y
        cur_info = TILE_TYPES.get(canvas.get_tile(), {})
        dirty = ' *' if self._dirty else ''
        extra = ''
        if (x, y) in self._door_map:
            d = self._door_map[(x, y)]
            extra = f' → {d["building_id"]}'
        elif (x, y) in self._sign_map:
            extra = f' "{self._sign_map[(x, y)]}"'
        elif (x, y) in self._npc_map:
            extra = f' [NPC: {self._npc_map[(x, y)]}]'
        palette = self.query_one('#tile-palette', TilePalette)
        mode = ' [填充]' if self._fill_mode and palette.is_open() else ''
        paint = ' [绘制中]' if self._painting else ''
        self.query_one('#status-line', Static).update(
            f' ({x},{y}) [{cur_info.get("name", "?")}]{extra}{mode}{paint}'
            f' | p=面板 e=绘制 x=删除 f=填充 q=退出 Ctrl+S=保存 Ctrl+D=部署{dirty}'
        )

    def action_save(self) -> None:
        # starter_town 必须有出生点
        if self._is_starter_town() and not self._find_spawn_pos():
            self.notify('starter_town 必须设置出生点 (S) 才能保存！', timeout=5)
            return
        self.map_data['tiles'] = [''.join(row) for row in self.tiles]
        self.map_data['meta']['width'] = len(self.tiles[0]) if self.tiles else 0
        self.map_data['meta']['height'] = len(self.tiles)
        # 从全局地块库写入地图实际使用的 tile_types
        used = set(ch for row in self.tiles for ch in row)
        self.map_data['tile_types'] = {
            k: dict(v) for k, v in TILE_TYPES.items() if k in used
        }
        # 从 S 地块提取 spawn 坐标
        sp = self._find_spawn_pos()
        if sp:
            self.map_data['spawn'] = list(sp)
        # rebuild buildings from door_map
        buildings: dict[str, dict] = {}
        for (dx, dy), info in self._door_map.items():
            bid = info['building_id']
            if bid not in buildings:
                buildings[bid] = {'name': info.get('name', bid), 'doors': []}
            buildings[bid]['doors'].append([dx, dy])
        self.map_data['buildings'] = buildings
        # rebuild signs from sign_map
        self.map_data['signs'] = [
            {'pos': [sx, sy], 'text': txt}
            for (sx, sy), txt in self._sign_map.items()
        ]
        # rebuild npcs from npc_map
        self.map_data['npcs'] = [
            {'id': nid, 'pos': [nx, ny]}
            for (nx, ny), nid in self._npc_map.items()
        ]
        map_id = self.map_data.get('meta', {}).get('id', 'map')
        json_path = os.path.join(self.out_dir, f'{map_id}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.map_data, f, ensure_ascii=False, indent=2)
        jpeg_path = os.path.join(self.preview_dir, f'{map_id}_preview.jpeg')
        tile_rows = [list(row) for row in self.map_data['tiles']]
        _save_preview(tile_rows, jpeg_path)
        self._dirty = False
        self._update_status()
        self.notify(f'已保存: {json_path}', timeout=3)

    def action_deploy(self) -> None:
        """将当前地图复制到游戏目录."""
        if self._dirty:
            self.notify('请先保存 (Ctrl+S) 再部署', timeout=3)
            return
        map_id = self.map_data.get('meta', {}).get('id', 'map')
        src = os.path.join(self.out_dir, f'{map_id}.json')
        if not os.path.exists(src):
            self.notify('本地文件不存在, 请先保存', timeout=3)
            return
        import shutil
        os.makedirs(self.game_dir, exist_ok=True)
        dst = os.path.join(self.game_dir, f'{map_id}.json')
        shutil.copy2(src, dst)
        self.notify(f'已部署: {dst}', timeout=3)

    def action_quit(self) -> None:
        if self._dirty:
            self.notify('有未保存更改! 再按 q 强制退出', timeout=3)
            self._dirty = False
            return
        self.exit()


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    game_maps_dir = os.path.normpath(
        os.path.join(here, '..', '..', 'Server', 'server',
                     'games', 'world', 'data', 'maps'))
    local_maps_dir = os.path.join(here, 'maps')
    os.makedirs(local_maps_dir, exist_ok=True)
    previews_dir = os.path.join(here, 'previews')
    os.makedirs(previews_dir, exist_ok=True)

    name = input('地图id (不含扩展名): ').strip()
    if not name:
        print('id不能为空')
        sys.exit(1)

    path = os.path.join(local_maps_dir, f'{name}.json')
    # 本地没有则从游戏目录复制一份
    if not os.path.exists(path):
        game_path = os.path.join(game_maps_dir, f'{name}.json')
        if os.path.exists(game_path):
            import shutil
            shutil.copy2(game_path, path)
            print(f'从游戏目录复制: {game_path} → {path}')
    if os.path.exists(path):
        print(f'打开已有地图: {path}')
    else:
        size = input('地图尺寸 (宽x高, 留空=100x50): ').strip() or '100x50'
        try:
            w_str, h_str = size.lower().split('x')
            w, h = int(w_str), int(h_str)
            assert w > 0 and h > 0
        except Exception:
            print('尺寸格式错误, 应为 宽x高')
            sys.exit(1)
        # 地图类型
        print('地图类型: 1=world  2=road  3=building  4=site')
        map_type_input = input('选择 (1-4, 默认1): ').strip() or '1'
        map_type_map = {'1': 'world', '2': 'road', '3': 'building', '4': 'site'}
        map_type = map_type_map.get(map_type_input, 'world')
        # building 需要指定场所类型
        vt = None
        if map_type == 'building':
            # 从 GAME_INFO locations 收集已知 venue_type
            _known_vts: list[str] = []
            _game_init = os.path.normpath(
                os.path.join(here, '..', '..', 'Server', 'server',
                             'games', 'world', '__init__.py'))
            if os.path.exists(_game_init):
                import re as _re
                with open(_game_init, 'r', encoding='utf-8') as _f:
                    _src = _f.read()
                _known_vts = _re.findall(r"'building_(\w+)'", _src)
            # 从地图文件扫描补充 (优先本地, 再游戏目录)
            _scan_dirs = [local_maps_dir]
            if os.path.isdir(game_maps_dir):
                _scan_dirs.append(game_maps_dir)
            _seen_fns: set[str] = set()
            for _sd in _scan_dirs:
              for fn in sorted(os.listdir(_sd)):
                if not fn.endswith('.json') or fn == f'{name}.json' or fn in _seen_fns:
                    continue
                _seen_fns.add(fn)
                try:
                    with open(os.path.join(_sd, fn), 'r', encoding='utf-8') as _f:
                        _meta = json.load(_f).get('meta', {})
                    if _meta.get('map_type') == 'building':
                        _vt = _meta.get('venue_type', '')
                        if _vt and _vt not in _known_vts:
                            _known_vts.append(_vt)
                except Exception:
                    pass
            if _known_vts:
                print('venue_type:')
                for i, vt_name in enumerate(_known_vts, 1):
                    print(f'  {i}={vt_name}')
                print(f'  0=自定义')
                vt_input = input(f'选择 (1-{len(_known_vts)}, 0=自定义, 留空=同id): ').strip()
                if vt_input == '0':
                    vt = input('输入自定义 venue_type: ').strip() or name
                elif vt_input.isdigit() and 1 <= int(vt_input) <= len(_known_vts):
                    vt = _known_vts[int(vt_input) - 1]
                else:
                    vt = name
            else:
                vt = input('venue_type (留空=同id): ').strip() or name
        # 场所/道路可设视野限制
        visibility = None
        if map_type in ('site', 'road'):
            vis = input('视野限制 (留空=无限): ').strip()
            if vis:
                try:
                    visibility = int(vis)
                except ValueError:
                    pass
        # 显示名称放最后
        while True:
            display_name = input('地图显示名称: ').strip()
            if display_name:
                break
            print('名称不能为空')
        meta: dict = {'id': name, 'name': display_name, 'width': w, 'height': h,
                       'map_type': map_type}
        if vt is not None:
            meta['venue_type'] = vt
        if visibility is not None:
            meta['default_visibility'] = visibility
        data = {
            'meta': meta,
            'tile_types': {' ': dict(TILE_TYPES[' '])},
            'buildings': {},
            'tiles': [' ' * w for _ in range(h)],
            'spawn': [w // 2, h // 2],
            'signs': [],
            'teleports': [],
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'已创建新地图: {path} ({w}x{h}, {map_type})')

    MapEditorApp(path, out_dir=local_maps_dir, game_dir=game_maps_dir,
                 preview_dir=previews_dir).run()


if __name__ == '__main__':
    main()
