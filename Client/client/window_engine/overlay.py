"""OverlayStack — 浮窗 LIFO 栈

职责:
- 维护已打开的浮窗 id 序列 (LIFO)
- 提供 push / pop_top / remove / top / contains 操作
- 不持有窗口实例本身，只持有 id；窗口查找由调用方 (Engine) 完成

为什么独立?
- 单一职责：只管"栈"这件事，可单独测试
- 与 Textual 解耦：纯 list 操作，无 widget 依赖
"""

from __future__ import annotations


class OverlayStack:
    """浮窗 id 的 LIFO 栈"""

    def __init__(self):
        self._stack: list[str] = []

    def push(self, window_id: str) -> None:
        """压栈。若已存在则移到栈顶 (LRU 风格)"""
        if window_id in self._stack:
            self._stack.remove(window_id)
        self._stack.append(window_id)

    def pop_top(self) -> str | None:
        """弹出栈顶 id (无则 None)"""
        return self._stack.pop() if self._stack else None

    def remove(self, window_id: str) -> bool:
        """从任意位置移除 id, 返回是否成功"""
        if window_id in self._stack:
            self._stack.remove(window_id)
            return True
        return False

    def top(self) -> str | None:
        return self._stack[-1] if self._stack else None

    def contains(self, window_id: str) -> bool:
        return window_id in self._stack

    def __iter__(self):
        """从底到顶迭代"""
        return iter(self._stack)

    def __reversed__(self):
        """从顶到底迭代"""
        return reversed(self._stack)

    def __len__(self) -> int:
        return len(self._stack)

    def clear(self) -> None:
        self._stack.clear()

    def snapshot(self) -> list[str]:
        return list(self._stack)
