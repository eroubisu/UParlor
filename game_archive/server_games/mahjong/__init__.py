"""
麻将游戏模块

模块结构:
- engine.py: 游戏引擎 (MahjongEngine - 房间管理)
- room.py: 房间类 (MahjongRoom - 组合各模块)
- tenpai.py: 听牌分析 (TenpaiMixin)
- actions.py: 吃碰杠胡操作 (ActionsMixin)
- scoring.py: 结算计分 (ScoringMixin)
- game_data.py: 牌数据定义和工具函数
- yaku.py: 役种判定
- bot_ai.py: 机器人 AI

旧模块 game_engine.py 仍保留用于向后兼容
"""

# 新的模块化导入
from .engine import MahjongEngine
from .room import MahjongRoom
from .tenpai import TenpaiMixin
from .actions import ActionsMixin
from .scoring import ScoringMixin
from .game_data import MahjongData
from .bot_ai import BotAI, get_bot_discard, get_bot_action, get_bot_self_action

def _create_bot_scheduler(server):
    from .bot_scheduler import MahjongBotScheduler
    return MahjongBotScheduler(
        engine_provider=lambda: server.lobby_engine.game_engines.get('mahjong'),
        server=server,
    )

# 游戏信息
GAME_INFO = {
    'id': 'mahjong',
    'name': '麻将',
    'description': '四人麻将游戏',
    'min_players': 4,
    'max_players': 4,
    'icon': '🀄',
    'has_rooms': True,
    'has_bot': True,
    'per_player': False,
    'rank_key': 'mahjong',
    'locations': {
        'mahjong': ('麻将', 'lobby'),
        'mahjong_room': ('房间', 'mahjong'),
        'mahjong_playing': ('对局中', 'mahjong_room'),
    },
    'create_engine': lambda: MahjongEngine(MahjongData()),
    'create_bot_scheduler': _create_bot_scheduler,
    'help_commands': [
        ('/create', '创建房间 (交互式选择)'),
        ('/rooms', '查看房间列表'),
        ('/join <房间ID>', '加入房间'),
        ('/rank', '查看段位详情'),
        ('/stats', '查看战绩统计'),
    ],
}


def get_entry_message(player_data):
    """生成进入麻将时的欢迎信息"""
    from server.user_schema import get_rank_name
    rank_id = player_data.get('mahjong', {}).get('rank', 'novice_1')
    rank_name = get_rank_name(rank_id)
    rank_points = player_data.get('mahjong', {}).get('rank_points', 0)
    info = GAME_INFO
    cmds = '\n'.join(f'  {c:<14s} - {d}' for c, d in info['help_commands'])
    return f"""
{info['icon']} 进入 {info['name']}

你的段位: {rank_name} ({rank_points}pt)

【麻将指令】
{cmds}
  /quit          - 离开麻将
  /back          - 返回上一级

输入 /help mahjong 查看完整说明
"""


def get_help_text(page=None):
    """获取麻将分页帮助"""
    pages = {
        '1': ('麻将帮助 - 房间指令\n\n'
              '【创建/加入】\n'
              '  /create [类型]  创建房间\n'
              '    类型: 东风/南风/铜/银/金/玉/王座\n'
              '  /rooms         查看房间列表\n'
              '  /join <ID>     加入指定房间\n\n'
              '【段位系统】\n'
              '  /rank          查看段位详情\n'
              '  /stats         查看战绩统计\n\n'
              '【房间管理】\n'
              '  /bot           添加机器人（房主）\n'
              '  /start         开始游戏（房主）\n'
              '  /room          查看房间状态\n'
              '  /invite @名    邀请玩家\n'
              '  /accept        接受邀请\n\n'
              '【导航】\n'
              '  /quit          离开麻将游戏\n'
              '  /back          返回上一级\n'
              '  /home          返回大厅\n\n'
              '返回目录: /help mahjong'),
        '2': ('麻将帮助 - 游戏操作\n\n'
              '【手牌】\n'
              '  /h /hand       查看手牌\n'
              '  /d <n>         打第n张牌\n'
              '  /dora          查看宝牌\n'
              '  /tenpai /t     听牌分析\n\n'
              '【鸣牌】\n'
              '  /pong          碰\n'
              '  /kong          明杠\n'
              '  /chow [n]      吃（下家专用）\n'
              '  /pass          过\n\n'
              '【杠】\n'
              '  /ankan [n]     暗杠\n'
              '  /kakan [n]     加杠\n\n'
              '【和牌】\n'
              '  /ron /hu       荣和\n'
              '  /tsumo         自摸\n'
              '  /chankan       抢杠\n\n'
              '【特殊】\n'
              '  /riichi <n>    立直\n'
              '  /kyuushu /9    九种九牌\n\n'
              '返回目录: /help mahjong'),
        '3': ('麻将帮助 - 役种表\n\n'
              '【1番】\n'
              '立直 一发 门清自摸 断幺九 平和\n'
              '一杯口 役牌 岭上开花 抢杠\n'
              '海底摸月 河底捞鱼\n\n'
              '【2番】\n'
              '双立直 三色同顺 一气通贯\n'
              '混全 七对子 对对和 三暗刻\n'
              '三杠子 小三元 三色同刻 混老头\n\n'
              '【3番】混一色 纯全 二杯口\n'
              '【6番】清一色\n\n'
              '【役满】\n'
              '天和 地和 四暗刻 国士无双\n'
              '大三元 小四喜 大四喜 字一色\n'
              '清老头 绿一色 九莲宝灯 四杠子\n\n'
              '返回目录: /help mahjong'),
        '4': ('麻将帮助 - 规则说明\n\n'
              '【基本规则】\n'
              '・4人对战，东风战/半庄战\n'
              '・初始25000点，返点30000点\n'
              '・支持吃/碰/杠/立直\n\n'
              '【宝牌系统】\n'
              '・表宝牌：指示牌的下一张\n'
              '・杠宝牌：每杠翻开1张\n'
              '・里宝牌：立直和牌可翻\n'
              '・赤宝牌：赤5万/条/筒各1张\n\n'
              '【流局类型】\n'
              '・荒牌流局：牌山摸完\n'
              '・九种九牌：第一巡9种幺九牌\n'
              '・四风连打：第一巡四家同风\n'
              '・四杠散了：两人以上开4杠\n'
              '・四家立直：四人都立直\n\n'
              '返回目录: /help mahjong'),
    }

    if page and page in pages:
        return pages[page]

    return ('麻将帮助\n\n'
            '【目录】\n'
            '  /help mahjong 1   房间指令\n'
            '  /help mahjong 2   游戏操作\n'
            '  /help mahjong 3   役种表\n'
            '  /help mahjong 4   规则说明\n\n'
            '【快速开始】\n'
            '  /create    创建房间\n'
            '  /bot       添加机器人\n'
            '  /start     开始游戏\n'
            '  /d <n>     打第n张牌\n\n'
            '输入对应指令查看详细内容')
