"""全局指令处理器注册表

将全局指令（任何位置都有效的指令）从 lobby_engine.process_command() 的
if/elif 链中提取出来，通过注册表驱动路由。
新增全局指令只需在本文件中添加 handler 并注册，无需修改核心框架。
"""

from __future__ import annotations

from typing import Callable

from ..config import SERVER_VERSION


# ── 全局指令处理器注册表 ──

# handler 签名: (lobby, player_name, player_data, args, location) -> dict | str | None
GlobalHandler = Callable[..., dict | str | None]
_GLOBAL_HANDLERS: dict[str, GlobalHandler] = {}


def register_global(cmd_name: str, handler: GlobalHandler | None = None):
    """注册全局指令处理器。

    装饰器: @register_global('help')
    函数调用: register_global('use', cmd_use)
    """
    if handler is not None:
        _GLOBAL_HANDLERS[cmd_name] = handler
        return handler

    def decorator(fn: GlobalHandler) -> GlobalHandler:
        _GLOBAL_HANDLERS[cmd_name] = fn
        return fn
    return decorator


def find_global_handler(cmd: str) -> GlobalHandler | None:
    """查找全局指令处理器。cmd 含 '/' 前缀。"""
    name = cmd.lstrip('/')
    return _GLOBAL_HANDLERS.get(name)


# ── 子菜单构建器注册表 ──

# builder 签名: (lobby, player_data) -> list[dict]
SubBuilder = Callable[..., list[dict]]
_SUB_BUILDERS: dict[str, SubBuilder] = {}


def register_sub_builder(cmd_name: str, builder: SubBuilder | None = None):
    """注册子菜单构建器。

    装饰器: @register_sub_builder('exit')
    函数调用: register_sub_builder('play', _sub_play)
    """
    if builder is not None:
        _SUB_BUILDERS[cmd_name] = builder
        return builder

    def decorator(fn: SubBuilder) -> SubBuilder:
        _SUB_BUILDERS[cmd_name] = fn
        return fn
    return decorator


def find_sub_builder(cmd_name: str) -> SubBuilder | None:
    """查找子菜单构建器。"""
    return _SUB_BUILDERS.get(cmd_name)


# ── 全局指令 handler ──

@register_global('games')
def _handle_games(lobby, player_name, player_data, args, location):
    return lobby.get_games_list()


@register_global('play')
def _handle_play(lobby, player_name, player_data, args, location):
    game_id = args.strip()
    if not game_id:
        return '请指定游戏: /play <游戏ID>'
    return lobby._enter_game(player_name, player_data, game_id)


@register_global('create')
def _handle_create(lobby, player_name, player_data, args, location):
    """创建房间（全局指令）

    格式: /create <game_id> [settings_json]
    """
    parts = args.strip().split(' ', 1)
    game_id = parts[0] if parts else ''
    if not game_id:
        return '请指定游戏: /create <游戏ID>'
    settings_str = parts[1] if len(parts) > 1 else ''

    engine = lobby._ensure_engine(game_id, player_name)
    if not engine:
        return f'游戏引擎初始化失败: {game_id}'
    return engine.handle_command(
        lobby, player_name, player_data, '/create', settings_str)


@register_global('clear')
def _handle_clear(lobby, player_name, player_data, args, location):
    return {'action': 'clear'}


@register_global('version')
def _handle_version(lobby, player_name, player_data, args, location):
    return {'action': 'version', 'server_version': SERVER_VERSION}


@register_global('exit')
def _handle_exit(lobby, player_name, player_data, args, location):
    arg = args.strip()
    if arg == 'y':
        return {'action': 'exit'}
    if arg == 'n':
        return '已取消退出。'
    return '输入 exit y 确认退出。'


@register_global('passwd')
def _handle_passwd(lobby, player_name, player_data, args, location):
    lobby.pending_confirms[player_name] = {'type': 'password_start'}
    return '请输入新密码（6-20个字符）：'


@register_global('help')
def _handle_help(lobby, player_name, player_data, args, location):
    """上下文感知帮助：在游戏中显示该游戏帮助（分节子菜单），否则显示主帮助"""
    from .help import (
        get_main_help, get_game_help_text,
        get_help_sections, get_help_section,
    )
    from ..msg_types import ROOM_UPDATE, COMMANDS_UPDATE

    game_id = lobby._get_game_for_location(location) if location else None

    if game_id:
        sections = get_help_sections(game_id)

        if sections:
            non_welcome = [(sid, title) for sid, title, _ in sections if sid != 'welcome']
            # 查看分节后的 hint bar: 只保留 help（重新弹子菜单）+ back
            help_cmds = [
                {'name': 'help', 'label': '帮助', 'tab': '帮助'},
                {'name': 'back', 'label': '返回', 'tab': '导航'},
            ]
            cmds_msg = {'type': COMMANDS_UPDATE, 'commands': help_cmds}

            if args:
                # 子菜单选中 → 返回该分节
                section_id = args.strip()
                text = get_help_section(game_id, section_id)
                if text:
                    lobby._help_viewers.add(player_name)
                    return {
                        'action': 'game_help',
                        'send_to_caller': [
                            {'type': ROOM_UPDATE, 'room_data': {'game_type': game_id, 'doc': text}},
                            cmds_msg,
                        ],
                    }

            # 无参数：弹出分节选择子菜单
            if non_welcome:
                from ..core.protocol import build_select_menu
                items = [
                    {'label': title, 'command': f'/help {sid}'}
                    for sid, title in non_welcome
                ]
                items.append({'label': '返回', 'command': '/back'})
                return build_select_menu('帮助', items)

        # 无分节或 world 等 → 整段显示
        help_text = get_game_help_text(game_id)
        if help_text:
            lobby._help_viewers.add(player_name)
            return {
                'action': 'game_help',
                'send_to_caller': [{
                    'type': ROOM_UPDATE,
                    'room_data': {'game_type': game_id, 'doc': help_text},
                }],
            }

    return get_main_help()






