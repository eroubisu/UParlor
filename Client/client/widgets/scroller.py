"""虚拟滚动 — 光标 + 视窗偏移量管理"""

from __future__ import annotations


class VirtualScroller:
    """追踪光标位置和滚动偏移量，保证光标始终在可视窗口内。

    使用方式：
        scroller = VirtualScroller()
        scroller.move_down(total)
        scroller.ensure_visible(visible_height, extra_height=len(actions))
        start, end = scroller.visible_range(visible_height)
    """

    __slots__ = ('cursor', 'offset')

    def __init__(self):
        self.cursor: int = 0
        self.offset: int = 0

    def reset(self):
        self.cursor = 0
        self.offset = 0

    def clamp(self, total: int):
        """将 cursor 夹到 [0, total-1]。"""
        if total <= 0:
            self.cursor = 0
        elif self.cursor >= total:
            self.cursor = total - 1

    def move_down(self, total: int):
        if total > 0:
            self.cursor = (self.cursor + 1) % total

    def move_up(self, total: int):
        if total > 0:
            self.cursor = (self.cursor - 1) % total

    def ensure_visible(self, visible_height: int, extra_height: int = 0):
        """调整 offset 使 cursor 及其附属内容（展开菜单等）在窗口内。"""
        vh = max(1, visible_height)
        need = 1 + extra_height
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor + need > self.offset + vh:
            self.offset = self.cursor + need - vh
        self.offset = max(0, self.offset)

    def visible_range(self, visible_height: int, total: int | None = None) -> tuple[int, int]:
        """返回 (start, end) 切片索引。"""
        start = self.offset
        end = start + max(1, visible_height)
        if total is not None:
            end = min(end, total)
        return start, end
