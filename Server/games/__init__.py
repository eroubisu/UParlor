"""
游戏模块 — 自动注册 + 全量 JSON 自动注入

register_game() 自动从游戏目录加载所有 JSON 数据文件：
  - commands.json     → config.COMMAND_TABLE
  - ranks.json        → 游戏专属段位体系
  - titles.json       → user_schema.TITLE_LIBRARY / TITLE_SOURCES
  - items.json        → user_schema.ITEM_LIBRARY / ITEM_SOURCES
  - player_data.json  → 用户模板默认值

GAME_INFO 只保留代码级配置（locations, create_engine 等）。
"""

import json
import os

from server.config import register_game_locations, COMMAND_TABLE
from server.user_schema import register_game_player_defaults
from server.rank_system import register_game_ranks, register_rank_titles
from server.title_system import register_game_titles, register_game_title_sources
from server.item_system import register_game_items, register_game_item_sources

# 注册的游戏列表
GAMES = {}


def _load_game_json(module_dir, filename):
    """加载游戏目录下的 JSON 文件，不存在则返回 None"""
    path = os.path.join(module_dir, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def register_game(game_id, game_module):
    """注册游戏并自动注入所有元数据到框架全局注册表"""
    GAMES[game_id] = game_module
    info = getattr(game_module, 'GAME_INFO', {})
    module_dir = os.path.dirname(game_module.__file__)

    # ── 位置层级 ──
    if info.get('locations'):
        register_game_locations(info)

    # ── 指令（commands.json） ──
    data = _load_game_json(module_dir, 'commands.json')
    if data:
        info['commands'] = data
        for loc, cmds in data.items():
            COMMAND_TABLE.setdefault(loc, []).extend(cmds)

    # ── 段位（ranks.json） ──
    data = _load_game_json(module_dir, 'ranks.json')
    if data:
        register_game_ranks(game_id, data['ranks'], data['rank_order'])
        if 'rank_to_title' in data:
            register_rank_titles(data['rank_to_title'])

    # ── 头衔（titles.json） ──
    data = _load_game_json(module_dir, 'titles.json')
    if data:
        register_game_titles(data.get('titles', {}))
        register_game_title_sources(data.get('sources', {}))

    # ── 物品（items.json） ──
    data = _load_game_json(module_dir, 'items.json')
    if data:
        register_game_items(data.get('items', {}))
        register_game_item_sources(data.get('sources', {}))

    # ── 默认玩家数据（player_data.json） ──
    data = _load_game_json(module_dir, 'player_data.json')
    if data:
        register_game_player_defaults(game_id, data)


def get_game(game_id):
    """获取游戏模块"""
    return GAMES.get(game_id)


def get_all_games():
    """获取所有游戏信息"""
    result = []
    for game_id, module in GAMES.items():
        info = getattr(module, 'GAME_INFO', {})
        result.append(info)
    return result


# 注册所有游戏（添加新游戏只需在此添加两行）
# from . import xxx
# register_game('xxx', xxx)
#
# 游戏模块目录结构（JSON 文件均为可选，存在即自动注入）:
#   games/chess/
#       __init__.py        — GAME_INFO（id, name, icon, locations, create_engine）
#       commands.json      — 各位置指令集
#       ranks.json         — 游戏专属段位体系（可选，不提供则用框架默认）
#       titles.json        — 游戏头衔 + 来源分类
#       items.json         — 游戏物品 + 来源分类
#       player_data.json   — 默认玩家数据（注册时自动写入用户档案）
#       engine.py          — 游戏引擎
