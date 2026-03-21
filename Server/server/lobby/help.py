"""大厅帮助文本 & 游戏列表生成 + 子菜单构建器注册"""

from ..config import COMMAND_TABLE
from .command_registry import register_sub_builder
from ..games import get_game, get_all_games


# ── 帮助文本生成 ──

def get_main_help():
    """获取主帮助文本（从 commands.json 自动生成）"""
    from ..storage.text_utils import pad_left

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
    """获取游戏帮助原始文本（用于游戏面板内显示，不含导航前缀）"""
    game_module = get_game(game_id)
    if not game_module:
        return None

    get_help = getattr(game_module, 'get_help_text', None)
    if get_help:
        return get_help()

    import os
    for filename in ('help.md', 'help.txt'):
        try:
            help_path = os.path.join(
                os.path.dirname(game_module.__file__), filename)
            with open(help_path, 'r', encoding='utf-8') as f:
                return f.read()
        except (OSError, AttributeError):
            pass
    return None


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

    info = getattr(game_module, 'GAME_INFO', {})

    # 尝试从帮助文件读取
    import os
    for filename in ('help.md', 'help.txt'):
        try:
            help_path = os.path.join(
                os.path.dirname(game_module.__file__), filename)
            with open(help_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return _GAME_NAV_PREFIX + '\n' + content
        except (OSError, AttributeError):
            pass

    # 回退到基本信息
    name = info.get('name', game_id)
    desc = info.get('description', '暂无描述')
    min_p = info.get('min_players', '?')
    max_p = info.get('max_players', '?')
    content = f"{name}\n{desc}\n\n玩家人数: {min_p}-{max_p}人\n"
    return _GAME_NAV_PREFIX + '\n' + content


def get_games_list():
    """获取游戏列表"""
    from ..storage.text_utils import pad_left
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
    """生成 play 子菜单：当前位置可用的游戏"""
    player_name = player_data.get('name', '')
    location = lobby.get_player_location(player_name)
    # 只列出根位置 parent 为当前 location 的游戏
    available = []
    for g in get_all_games():
        if g.get('per_player'):
            continue
        for _loc_key, (_, parent) in g.get('locations', {}).items():
            if parent == location:
                available.append(g)
                break
    if not available:
        available = [g for g in get_all_games() if not g.get('per_player')]
    return [
        {'name': f"play {g['id']}", 'label': g.get('name', g['id']),
         'desc': f"{g.get('min_players','?')}-{g.get('max_players','?')}人"}
        for g in available
    ]


@register_sub_builder('settitle')
def _sub_settitle(lobby, player_data):
    """生成 settitle 子菜单：玩家已拥有的头衔"""
    from ..systems.titles import TITLE_LIBRARY
    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
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

