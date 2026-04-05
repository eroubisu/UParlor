"""大厅帮助文本 & 游戏列表生成 + 子菜单构建器注册"""

from __future__ import annotations

import re

from ..config import COMMAND_TABLE
from .command_registry import register_sub_builder
from ..games import get_game, get_all_games


# ── 帮助文本 — 分节解析 ──

_SECTION_RE = re.compile(r'^##\s+(\w+)\s*(.*?)\s*$')


def _parse_sections(text: str) -> list[tuple[str, str, str]]:
    """解析 help.txt 的分节结构。

    格式: ``## section_id 标题`` 开头的行为分节标记。
    返回 [(section_id, title, content), ...]
    """
    sections: list[tuple[str, str, str]] = []
    cur_id = ''
    cur_title = ''
    lines: list[str] = []

    for line in text.split('\n'):
        m = _SECTION_RE.match(line)
        if m:
            if cur_id:
                sections.append((cur_id, cur_title, '\n'.join(lines).strip()))
            cur_id, cur_title = m.group(1), m.group(2)
            lines = []
        else:
            lines.append(line)

    if cur_id:
        sections.append((cur_id, cur_title, '\n'.join(lines).strip()))

    return sections


def _load_help_raw(game_id: str) -> str | None:
    """读取游戏帮助原始文本"""
    game_module = get_game(game_id)
    if not game_module:
        return None
    import os
    base = os.path.dirname(game_module.__file__)
    # 优先 data/ 子目录，再是模块根目录
    for directory in (os.path.join(base, 'data'), base):
        for filename in ('help.md', 'help.txt'):
            try:
                path = os.path.join(directory, filename)
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            except (OSError, AttributeError):
                pass
    return None


def get_help_sections(game_id: str) -> list[tuple[str, str, str]] | None:
    """获取游戏帮助分节列表。无分节标记时返回 None。"""
    raw = _load_help_raw(game_id)
    if not raw:
        return None
    sections = _parse_sections(raw)
    return sections if sections else None


def get_help_section(game_id: str, section_id: str) -> str | None:
    """获取指定分节的内容文本。"""
    sections = get_help_sections(game_id)
    if not sections:
        return None
    for sid, title, content in sections:
        if sid == section_id:
            return content
    return None


def get_help_welcome(game_id: str) -> str | None:
    """获取 welcome 分节作为进入游戏的欢迎文档。"""
    return get_help_section(game_id, 'welcome')


# ── 帮助文本生成 ──

def get_main_help():
    """获取主帮助文本（从 commands.json 自动生成）"""
    from .text_utils import pad_left

    all_cmds = COMMAND_TABLE.get('*', []) + COMMAND_TABLE.get('lobby', [])
    lines = ['HOME 指令', '']
    for c in all_cmds:
        name = c['name']
        label = c.get('label', name)
        lines.append(f"  {pad_left(name, 14)}{label}")

    # 动态游戏列表（排除主世界等 per_player 引擎）
    games = [g for g in get_all_games() if not g.get('per_player')]
    if games:
        lines.append('')
        lines.append('可用游戏')
        lines.append('')
        for game in games:
            icon = game.get('icon', '◆')
            name = game.get('name', game.get('id', '???'))
            lines.append(f"  {icon} {name}")

    lines.append('')
    return '\n'.join(lines)


_GAME_NAV_PREFIX = "  back → 返回大厅    home → 回到首页\n"


def get_game_help_text(game_id) -> str | None:
    """获取游戏帮助原始文本（用于游戏面板内显示，不含导航前缀）

    如果文件使用分节格式，拼接所有非 welcome 分节。
    """
    game_module = get_game(game_id)
    if not game_module:
        return None

    get_help = getattr(game_module, 'get_help_text', None)
    if get_help:
        return get_help()

    raw = _load_help_raw(game_id)
    if not raw:
        return None

    sections = _parse_sections(raw)
    if not sections:
        return raw  # 无分节标记 → 原样返回

    # 拼接所有非 welcome 分节
    parts = []
    for sid, title, content in sections:
        if sid == 'welcome':
            continue
        if title:
            parts.append(f'◆ {title}\n')
        parts.append(content)
    return '\n\n'.join(parts) if parts else raw


def get_game_help(game_id, page=None):
    """获取游戏帮助文本（通用）"""
    game_module = get_game(game_id)
    if not game_module:
        return f"未找到游戏: {game_id}"

    # 优先: 模块提供的 get_help_text(page)
    get_help = getattr(game_module, 'get_help_text', None)
    if get_help:
        content = get_help(page)
        return _GAME_NAV_PREFIX + '\n' + content

    raw = _load_help_raw(game_id)
    if raw:
        return _GAME_NAV_PREFIX + '\n' + raw

    # 回退到基本信息
    info = getattr(game_module, 'GAME_INFO', {})
    desc = info.get('description', '暂无描述')
    min_p = info.get('min_players', '?')
    max_p = info.get('max_players', '?')
    content = f"{name}\n{desc}\n\n玩家人数: {min_p}-{max_p}人\n"
    return _GAME_NAV_PREFIX + '\n' + content


def get_games_list():
    """获取游戏列表"""
    from .text_utils import pad_left
    games = [g for g in get_all_games() if not g.get('per_player')]
    if not games:
        return '暂无可用游戏'
    lines = ['可用游戏', '']
    for game in games:
        icon = game.get('icon', '◆')
        name = game.get('name', game.get('id', '???'))
        min_p = game.get('min_players', '?')
        max_p = game.get('max_players', '?')
        desc = game.get('description', '')
        lines.append(f"  {icon} {pad_left(name, 12)}{min_p}-{max_p}人")
        if desc:
            lines.append(f"    {desc}")
    lines.append('')
    return '\n'.join(lines)


# ── 子菜单构建器 ──

@register_sub_builder('play')
def _sub_play(lobby, player_data):
    """生成 play 子菜单：当前建筑可用的游戏"""
    from ..games.world.building_handlers import _BUILDING_GAMES
    player_name = player_data.get('name', '')
    location = lobby.get_player_location(player_name)
    allowed_ids = _BUILDING_GAMES.get(location, [])
    if not allowed_ids:
        return []
    result = []
    for g in get_all_games():
        if g['id'] in allowed_ids:
            result.append(
                {'name': f"play {g['id']}", 'label': g['id'],
                 'desc': g.get('name', g['id'])})
    return result


@register_sub_builder('settitle')
def _sub_settitle(lobby, player_data):
    """生成 settitle 子菜单：玩家已拥有的头衔"""
    from ..systems.titles import TITLE_LIBRARY
    from ..player.schema import default_titles
    titles = player_data.get('titles', default_titles())
    owned = titles.get('owned', [])
    displayed = titles.get('displayed', [])
    sub = []
    for i, title_id in enumerate(owned, 1):
        info = TITLE_LIBRARY.get(title_id, {})
        name = info.get('name', title_id)
        mark = ' [显示中]' if title_id in displayed else ''
        sub.append({'name': f'settitle {i}', 'label': name, 'desc': mark})
    sub.append({'name': 'settitle clear', 'label': '清除全部', 'desc': '清除所有显示'})
    return sub


@register_sub_builder('exit')
def _sub_exit(lobby, player_data):
    return [
        {'name': 'exit y', 'label': 'y', 'desc': '确认关闭'},
        {'name': 'exit n', 'label': 'n', 'desc': '取消'},
    ]

