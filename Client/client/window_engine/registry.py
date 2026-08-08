"""WindowRegistry — 全局窗口类注册表

约定:
- 任何窗口类有 `spec: WindowSpec` 类属性即可注册
- 用 register_window(cls) 模块导入时执行 (函数风格，与 register_game() 一致)
- 引擎从此表读取所有窗口元数据，自动 compose / 路由

线程模型:
- 单进程单 UI 线程使用，不加锁
"""

from __future__ import annotations

from typing import Type

from .spec import WindowSpec


class WindowRegistry:
    """窗口类注册表 (单例)"""

    def __init__(self):
        self._classes: dict[str, Type] = {}    # id → cls
        self._order: list[str] = []            # 注册顺序

    def register(self, cls: Type) -> Type:
        spec = getattr(cls, "spec", None)
        if not isinstance(spec, WindowSpec):
            raise TypeError(
                f"{cls.__name__} 必须有类属性 `spec: WindowSpec` 才能注册"
            )
        if spec.mode not in ("floating", "popup", "primary"):
            raise ValueError(
                f"窗口 {spec.id} 的 mode 无效: {spec.mode!r}"
            )
        if spec.id in self._classes:
            existing = self._classes[spec.id]
            if existing is cls:
                return cls
            raise ValueError(
                f"窗口 id 冲突: {spec.id} 已被 {existing.__name__} 注册"
            )
        self._classes[spec.id] = cls
        self._order.append(spec.id)
        return cls

    def get(self, window_id: str) -> Type | None:
        return self._classes.get(window_id)

    def spec(self, window_id: str) -> WindowSpec | None:
        cls = self._classes.get(window_id)
        return getattr(cls, "spec", None) if cls else None

    def all_classes(self) -> list[Type]:
        return [self._classes[i] for i in self._order]

    def all_specs(self) -> list[WindowSpec]:
        return [self._classes[i].spec for i in self._order]

    def by_group(self, group: str) -> list[WindowSpec]:
        """同组窗口按 (order, 注册顺序) 排序"""
        items = [s for s in self.all_specs() if s.group == group]
        items.sort(key=lambda s: (s.order, self._order.index(s.id)))
        return items

    def menu_entries(self, group: str) -> list[WindowSpec]:
        """Return selectable windows declared for one menu."""
        return [spec for spec in self.by_group(group) if spec.menu]

    def clear(self):
        """仅供测试用"""
        self._classes.clear()
        self._order.clear()


# 全局单例
_REGISTRY = WindowRegistry()


def register_window(cls: Type) -> Type:
    """注册窗口类。模块导入时执行。

    用法:
        class ChatWindow(Window):
            spec = WindowSpec(id="chat-window", title="聊天", menu=True)
            ...

        register_window(ChatWindow)
    """
    return _REGISTRY.register(cls)


def get_registry() -> WindowRegistry:
    return _REGISTRY
