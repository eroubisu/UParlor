"""指令注册表 — 服务端下发，客户端纯缓存（含标签页分组）

SSOT：服务端 commands.json + 游戏引擎 get_commands() → 客户端此模块唯一缓存。
指令菜单、补全、hint bar 全部从此模块读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict


# ── 指令信息 ──

@dataclass
class CommandInfo:
    """游戏指令描述"""
    command: str        # 带 / 前缀，如 "/help", "/back"
    label: str          # 如 "帮助", "返回"
    description: str = ""  # 详细说明
    tab: str = "其他"      # 标签页分组
    scope: str = "cmd"     # 归属面板: cmd=指令面板, inventory=物品栏
    sub: list | None = None  # 子菜单项列表（递归 CommandInfo）


# ── 当前位置指令集（唯一缓存）──

_commands: list[CommandInfo] = []
_tabs: list[tuple[str, list[CommandInfo]]] = []


def _parse_command(c: dict) -> CommandInfo:
    """将服务端 dict 转换为 CommandInfo（递归解析 sub）"""
    sub = None
    raw_sub = c.get('sub')
    if raw_sub is not None:
        sub = [_parse_command(s) for s in raw_sub]
    name = c.get('name', '')
    if name and not name.startswith('/'):
        name = '/' + name
    return CommandInfo(
        command=name,
        label=c.get('label', ''),
        description=c.get('desc', ''),
        tab=c.get('tab', '其他'),
        scope=c.get('scope', 'cmd'),
        sub=sub,
    )


def set_commands(commands: list[dict]) -> None:
    """接收服务端下发的指令列表，替换当前缓存并按 tab 分组

    scope='inventory' 的指令不在指令菜单显示。
    """
    global _commands, _tabs
    all_cmds = [_parse_command(c) for c in commands]
    _commands = [c for c in all_cmds if c.scope != 'inventory']
    tabs: OrderedDict[str, list[CommandInfo]] = OrderedDict()
    for cmd in _commands:
        tabs.setdefault(cmd.tab, []).append(cmd)
    _tabs = list(tabs.items())


def get_command_tabs() -> list[tuple[str, list[CommandInfo]]]:
    """获取按标签页分组的指令列表"""
    return list(_tabs)


def get_game_tabs() -> list[tuple[str, list[CommandInfo]]]:
    """获取游戏指令标签页（同 get_command_tabs，保持接口兼容）"""
    return list(_tabs)


def filter_commands(prefix: str) -> list[CommandInfo]:
    """根据输入前缀过滤可用指令（prefix 应带 / 前缀）"""
    if not prefix:
        return list(_commands)
    p = prefix if prefix.startswith('/') else '/' + prefix
    return [c for c in _commands if c.command.startswith(p)]
