"""MenuNav — 栈式菜单导航器（纯数据，不绑定 UI）"""

from __future__ import annotations


class MenuNav:
    """栈式菜单导航 — 纯逻辑，不绑定任何 Widget。

    管理一个无限深度的菜单栈，每层有自己的项目列表和光标位置。
    项目可以是任意类型，MenuNav 不解释项目内容。

    用法示例::

        nav = MenuNav(["选项A", "选项B"])
        nav.nav_down()          # 光标移到 "选项B"
        nav.push(["子1", "子2"]) # 进入子菜单
        nav.pop()               # 返回上层
    """

    __slots__ = ('_items', '_cursor', '_stack')

    def __init__(self, items: list | None = None):
        self._items: list = list(items) if items else []
        self._cursor: int = 0
        self._stack: list[tuple[list, int]] = []

    # ── 查询 ──

    @property
    def cursor(self) -> int:
        return self._cursor

    @cursor.setter
    def cursor(self, value: int):
        if self._items:
            self._cursor = max(0, min(value, len(self._items) - 1))
        else:
            self._cursor = 0

    @property
    def items(self) -> list:
        return self._items

    @property
    def depth(self) -> int:
        """当前栈深度，0 = 根层"""
        return len(self._stack)

    @property
    def selected(self):
        """当前光标选中的项目，列表为空时返回 None"""
        if self._items and 0 <= self._cursor < len(self._items):
            return self._items[self._cursor]
        return None

    # ── 更新 ──

    def set_items(self, items: list):
        """替换当前层的项目列表，光标自动钳位"""
        self._items = items
        if items:
            self._cursor = min(self._cursor, len(items) - 1)
        else:
            self._cursor = 0

    # ── 导航 ──

    def nav_down(self) -> bool:
        if not self._items:
            return False
        self._cursor = (self._cursor + 1) % len(self._items)
        return True

    def nav_up(self) -> bool:
        if not self._items:
            return False
        self._cursor = (self._cursor - 1) % len(self._items)
        return True

    def push(self, items: list):
        """压栈进入子级，光标归零"""
        self._stack.append((self._items, self._cursor))
        self._items = items
        self._cursor = 0

    def pop(self) -> bool:
        """弹栈返回上级。返回 False 表示已在根层。"""
        if not self._stack:
            return False
        self._items, self._cursor = self._stack.pop()
        return True

    def reset(self, items: list[str] | None = None):
        """弹回根层，光标归零。可选替换根层数据。"""
        while self._stack:
            self._items, self._cursor = self._stack.pop()
        if items is not None:
            self._items = list(items)
        self._cursor = 0


def render_menu_lines(labels: list[str], cursor: int,
                      color_marker: str, color_active: str,
                      color_normal: str) -> list[str]:
    """生成带光标高亮的菜单行列表（Rich markup）。

    参数:
        labels: 每项的显示文本
        cursor: 当前光标索引
        color_marker: 选中标记 ● 的颜色
        color_active: 选中行文本颜色
        color_normal: 未选中行文本颜色

    返回 Rich markup 字符串列表，每项一行。
    """
    lines: list[str] = []
    for i, label in enumerate(labels):
        if i == cursor:
            lines.append(f" [{color_marker}]●[/] [{color_active}]{label}[/]")
        else:
            lines.append(f"   [{color_normal}]{label}[/]")
    return lines
