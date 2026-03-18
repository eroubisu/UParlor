"""全局指令处理器注册表

将全局指令（任何位置都有效的指令）从 lobby_engine.process_command() 的
if/elif 链中提取出来，通过注册表驱动路由。
新增全局指令只需在本文件中添加 handler 并注册，无需修改核心框架。
"""

from __future__ import annotations

from typing import Callable

from ..config import SERVER_VERSION
from ..systems.item_commands import cmd_use, cmd_gift, cmd_drop
from ..systems.title_commands import cmd_alltitle, cmd_title


# ══════════════════════════════════════════════════
#  全局指令处理器注册表
# ══════════════════════════════════════════════════

# handler 签名: (lobby, player_name, player_data, args, location) -> dict | str | None
GlobalHandler = Callable[..., dict | str | None]
_GLOBAL_HANDLERS: dict[str, GlobalHandler] = {}


def register_global(cmd_name: str, handler: GlobalHandler) -> None:
    """注册全局指令处理器。cmd_name 不含 '/' 前缀。"""
    _GLOBAL_HANDLERS[cmd_name] = handler


def find_global_handler(cmd: str) -> GlobalHandler | None:
    """查找全局指令处理器。cmd 含 '/' 前缀。"""
    name = cmd.lstrip('/')
    return _GLOBAL_HANDLERS.get(name)


# ══════════════════════════════════════════════════
#  子菜单构建器注册表
# ══════════════════════════════════════════════════

# builder 签名: (lobby, player_data) -> list[dict]
SubBuilder = Callable[..., list[dict]]
_SUB_BUILDERS: dict[str, SubBuilder] = {}


def register_sub_builder(cmd_name: str, builder: SubBuilder) -> None:
    """注册子菜单构建器。指令的 sub 字段将由此函数动态生成。"""
    _SUB_BUILDERS[cmd_name] = builder


def find_sub_builder(cmd_name: str) -> SubBuilder | None:
    """查找子菜单构建器。"""
    return _SUB_BUILDERS.get(cmd_name)


# ── 全局指令 handler ──

def _handle_help(lobby, player_name, player_data, args, location):
    if args:
        parts = args.split(None, 1)
        game_id = parts[0].lower()
        page = parts[1] if len(parts) > 1 else None
        return lobby.get_game_help(game_id, page)
    game_id = lobby._get_game_for_location(location)
    if game_id:
        return lobby.get_game_help(game_id)
    return lobby.get_main_help()


def _handle_games(lobby, player_name, player_data, args, location):
    return lobby.get_games_list()


def _handle_clear(lobby, player_name, player_data, args, location):
    return {'action': 'clear'}


def _handle_version(lobby, player_name, player_data, args, location):
    return {'action': 'version', 'server_version': SERVER_VERSION}


def _handle_exit(lobby, player_name, player_data, args, location):
    arg = args.strip()
    if arg == 'y':
        return {'action': 'exit'}
    if arg == 'n':
        return '已取消退出。'
    return '输入 /exit y 确认退出。'


def _exit_sub_builder(lobby, player_data):
    return [
        {'name': 'exit y', 'label': '确认退出', 'desc': '关闭程序'},
        {'name': 'exit n', 'label': '取消', 'desc': '返回'},
    ]


def _handle_title(lobby, player_name, player_data, args, location):
    return cmd_alltitle(player_data, args)


def _handle_settitle(lobby, player_name, player_data, args, location):
    return cmd_title(player_name, player_data, args)


def _handle_passwd(lobby, player_name, player_data, args, location):
    lobby.pending_confirms[player_name] = {'type': 'password_start'}
    return '请输入新密码（6-20个字符）：'





# ── 注册 ──

register_global('help', _handle_help)
register_global('games', _handle_games)
register_global('clear', _handle_clear)
register_global('version', _handle_version)
register_global('exit', _handle_exit)
register_sub_builder('exit', _exit_sub_builder)
register_global('passwd', _handle_passwd)
register_global('title', _handle_title)
register_global('settitle', _handle_settitle)
register_global('use', cmd_use)
register_global('gift', cmd_gift)
register_global('drop', cmd_drop)

