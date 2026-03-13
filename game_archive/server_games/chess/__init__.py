"""
国际象棋游戏模块
使用 python-chess 库实现棋盘逻辑
支持双人房间对战（含机器人）、段位系统、计时器
"""

from .engine import ChessEngine
from .room import ChessRoom
from .game_data import ChessData

# 游戏信息
GAME_INFO = {
    'id': 'chess',
    'name': '国际象棋',
    'description': '经典国际象棋，双人房间对战，支持段位系统',
    'min_players': 2,
    'max_players': 2,
    'icon': '♟',
    'has_rooms': True,
    'has_bot': True,
    'per_player': False,
    'rank_key': 'chess',
    'locations': {
        'chess': ('国际象棋', 'lobby'),
        'chess_room': ('房间', 'chess'),
        'chess_playing': ('对局中', 'chess_room'),
    },
    'create_engine': lambda: ChessEngine(),
    'help_commands': [
        ('/create', '创建房间'),
        ('/rooms', '房间列表'),
        ('/join <ID>', '加入房间'),
        ('/rank', '段位详情'),
        ('/stats', '战绩统计'),
    ],
}


def get_entry_message(player_data):
    """生成进入国际象棋时的欢迎信息"""
    from server.user_schema import get_rank_name
    chess_data = player_data.get('chess', {})
    rank_id = chess_data.get('rank', 'novice_1')
    rank_name = get_rank_name(rank_id)
    rank_points = chess_data.get('rank_points', 0)
    info = GAME_INFO
    cmds = '\n'.join(f'  {c:<14s} {d}' for c, d in info['help_commands'])
    return f"""────── {info['icon']} {info['name']} ──────

  段位: {rank_name} ({rank_points}pt)

{cmds}
  /back          返回大厅

  输入 /help chess 查看完整说明
"""
