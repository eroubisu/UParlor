"""大厅帮助文本 & 游戏列表生成 + 子菜单构建器注册"""

from .config import COMMAND_TABLE
from .command_registry import register_sub_builder
from games import get_game, get_all_games


# ── 帮助文本生成 ──

def get_main_help():
    """获取主帮助文本（从 commands.json 自动生成）"""
    from .text_utils import pad_left
    from collections import OrderedDict

    # 收集全局 + 大厅指令，按 tab 分组
    all_cmds = COMMAND_TABLE.get('*', []) + COMMAND_TABLE.get('lobby', [])
    tab_order = ['导航', '个人', '系统']  # 固定显示顺序
    tab_labels = {'导航': '基础指令', '个人': '个人中心', '系统': '其他指令'}
    groups: dict[str, list] = OrderedDict()
    for tab in tab_order:
        groups[tab] = []
    for cmd in all_cmds:
        tab = cmd.get('tab', '系统')
        groups.setdefault(tab, []).append(cmd)

    # 生成指令文本
    text = '\n========== 游戏大厅 ==========\n\n'
    for tab, cmds in groups.items():
        if not cmds:
            continue
        label = tab_labels.get(tab, tab)
        text += f'【{label}】\n'
        for c in cmds:
            text += f"  {pad_left(c['name'], 14)} - {c['desc']}\n"
        text += '\n'

    # 动态游戏列表
    games = get_all_games()
    if games:
        text += '【可用游戏】\n'
        for game in games:
            icon = game.get('icon', '🎮')
            name = game.get('name', game.get('id', '???'))
            game_id = game.get('id', '???')
            text += f"  {icon} {pad_left(name, 12)} play {game_id}\n"
        text += '\n'

    text += '==============================\n'
    return text


def get_game_help(game_id, page=None):
    """获取游戏帮助文本（通用）"""
    game_module = get_game(game_id)
    if not game_module:
        return f"未找到游戏: {game_id}"

    # 优先: 模块提供的 get_help_text(page)
    get_help = getattr(game_module, 'get_help_text', None)
    if get_help:
        return get_help(page)

    info = getattr(game_module, 'GAME_INFO', {})

    # 尝试从帮助文件读取
    import os
    for filename in ('help.md', 'help.txt'):
        try:
            help_path = os.path.join(
                os.path.dirname(game_module.__file__), filename)
            with open(help_path, 'r', encoding='utf-8') as f:
                return f.read()
        except (OSError, AttributeError):
            pass

    # 回退到基本信息
    name = info.get('name', game_id)
    desc = info.get('description', '暂无描述')
    min_p = info.get('min_players', '?')
    max_p = info.get('max_players', '?')
    return f"{name}\n{desc}\n\n玩家人数: {min_p}-{max_p}人\n"


def get_games_list():
    """获取游戏列表"""
    games = get_all_games()
    text = "【游戏列表】\n\n"
    for game in games:
        icon = game.get('icon', '🎮')
        name = game.get('name', game.get('id', '???'))
        game_id = game.get('id', '???')
        min_p = game.get('min_players', '?')
        max_p = game.get('max_players', '?')
        desc = game.get('description', '')
        text += f"  {icon} {name}\n"
        text += f"     ID: {game_id}\n"
        text += f"     人数: {min_p}-{max_p}人\n"
        if desc:
            text += f"     {desc}\n"
        text += "\n"
    text += "使用 play <游戏ID> 进入游戏"
    return text


# ── 子菜单构建器注册 ──

def _sub_play(lobby, player_data):
    """生成 play 子菜单：可用游戏列表"""
    games = get_all_games()
    return [
        {'name': f"play {g['id']}", 'label': g.get('name', g['id']),
         'desc': f"{g.get('min_players','?')}-{g.get('max_players','?')}人"}
        for g in games
    ]


def _sub_title(lobby, player_data):
    """生成 title 子菜单：玩家已拥有的头衔"""
    from .title_system import TITLE_LIBRARY
    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
    owned = titles.get('owned', [])
    displayed = titles.get('displayed', [])
    sub = []
    for i, title_id in enumerate(owned, 1):
        info = TITLE_LIBRARY.get(title_id, {})
        name = info.get('name', title_id)
        mark = ' [显示中]' if title_id in displayed else ''
        sub.append({'name': f'title {i}', 'label': name, 'desc': mark})
    sub.append({'name': 'title clear', 'label': '清除全部', 'desc': '清除所有显示'})
    return sub


def _sub_exit(lobby, player_data):
    return [
        {'name': 'exit y', 'label': 'y', 'desc': '确认关闭'},
        {'name': 'exit n', 'label': 'n', 'desc': '取消'},
    ]


register_sub_builder('play', _sub_play)
register_sub_builder('title', _sub_title)
register_sub_builder('exit', _sub_exit)
