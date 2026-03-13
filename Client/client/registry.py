"""模块注册表 — 动态管理面板模块类型"""

from __future__ import annotations

from typing import Any

# 注册表：name → {'label': str, 'class': WidgetClass, 'scope': str}
# scope: 'global' = 通用模块（Space+e）, 'game' = 游戏模块（Space+g）
_REGISTRY: dict[str, dict[str, Any]] = {}

# 旧名称 → 新名称映射（兼容已保存的布局）
_COMPAT: dict[str, str] = {
    'info_table': 'status',
    'game': 'status',
    'board': 'status',
}


def register_module(name: str, label: str, widget_class: type,
                    scope: str = 'global') -> None:
    """注册一个面板模块类型

    scope: 'global' = 通用模块, 'game' = 游戏模块
    """
    _REGISTRY[name] = {
        'label': label,
        'class': widget_class,
        'scope': scope,
    }


def get_module_names(scope: str | None = None) -> list[str]:
    """返回已注册模块名称列表，可按 scope 过滤"""
    if scope is None:
        return list(_REGISTRY.keys())
    return [k for k, v in _REGISTRY.items() if v.get('scope') == scope]


def get_module_labels(scope: str | None = None) -> dict[str, str]:
    """返回 {模块名: 显示标签} 字典，可按 scope 过滤"""
    if scope is None:
        return {k: v['label'] for k, v in _REGISTRY.items()}
    return {k: v['label'] for k, v in _REGISTRY.items()
            if v.get('scope') == scope}


def get_module_info(name: str) -> dict | None:
    """返回模块注册信息，未找到返回 None"""
    return _REGISTRY.get(name)


def resolve_compat_name(name: str) -> str:
    """旧名称映射到新名称"""
    return _COMPAT.get(name, name)


def is_known_module(name: str) -> bool:
    """检查模块是否已注册"""
    return name in _REGISTRY
