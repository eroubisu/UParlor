"""指令注册表 — 服务端下发，客户端纯缓存（含标签页分组）"""

from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict


# ── 指令信息 ──

@dataclass
class CommandInfo:
    """游戏指令描述"""
    command: str        # 如 "/d", "/pong"
    label: str          # 如 "打牌", "碰"
    description: str = ""  # 详细说明
    tab: str = "其他"      # 标签页分组
    sub: list | None = None  # 子菜单项列表（递归 CommandInfo）


# ── 服务端下发的当前位置指令集 ──

_current_commands: list[CommandInfo] = []
_current_tabs: list[tuple[str, list[CommandInfo]]] = []  # [(tab_name, [cmds])]


def _parse_command(c: dict) -> CommandInfo:
    """将服务端 dict 转换为 CommandInfo（递归解析 sub）"""
    sub = None
    raw_sub = c.get('sub')
    if raw_sub is not None:
        sub = [_parse_command(s) for s in raw_sub]
    return CommandInfo(
        command=c.get('name', ''),
        label=c.get('label', ''),
        description=c.get('desc', ''),
        tab=c.get('tab', '其他'),
        sub=sub,
    )


def set_commands(commands: list[dict]) -> None:
    """接收服务端下发的指令列表，替换当前缓存并按 tab 分组"""
    global _current_commands, _current_tabs
    _current_commands = [_parse_command(c) for c in commands]
    # 按 tab 字段分组（保持服务端顺序）
    tabs: OrderedDict[str, list[CommandInfo]] = OrderedDict()
    for cmd in _current_commands:
        tabs.setdefault(cmd.tab, []).append(cmd)
    _current_tabs = list(tabs.items())


def get_command_tabs() -> list[tuple[str, list[CommandInfo]]]:
    """获取按标签页分组的指令列表"""
    return list(_current_tabs)


def filter_commands(prefix: str) -> list[CommandInfo]:
    """根据输入前缀过滤可用指令"""
    if not prefix:
        return list(_current_commands)
    return [c for c in _current_commands if c.command.startswith(prefix)]
