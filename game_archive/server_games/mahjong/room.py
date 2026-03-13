"""
麻将游戏 - 房间类
组合各个Mixin模块，形成完整的MahjongRoom类
"""

import random

from .tenpai import TenpaiMixin
from .actions import ActionsMixin
from .scoring import ScoringMixin


class MahjongRoom(TenpaiMixin, ActionsMixin, ScoringMixin):
    """麻将房间 - 通过Mixin组合各模块功能"""
    
    POSITIONS = ['东', '南', '西', '北']
    WINDS = ['东', '南', '西', '北']
    
    # 游戏模式（日语读法）
    GAME_MODES = {
        'tonpu': {'name': '東風戦', 'name_cn': '东风战', 'rounds': 1},
        'hanchan': {'name': '半荘戦', 'name_cn': '半庄战', 'rounds': 2},
    }
    
    # 段位场类型（日语读法）
    MATCH_TYPES = {
        'yuujin': {'name': '友人場', 'name_cn': '友人场', 'ranked': False, 'min_rank': None},
        'dou': {'name': '銅の間', 'name_cn': '铜之间', 'ranked': True, 'min_rank': 'novice_1'},
        'gin': {'name': '銀の間', 'name_cn': '银之间', 'ranked': True, 'min_rank': 'adept_1'},
        'kin': {'name': '金の間', 'name_cn': '金之间', 'ranked': True, 'min_rank': 'expert_1'},
        'gyoku': {'name': '玉の間', 'name_cn': '玉之间', 'ranked': True, 'min_rank': 'master_1'},
        'ouza': {'name': '王座の間', 'name_cn': '王座之间', 'ranked': True, 'min_rank': 'saint_1'},
    }
    
    def __init__(self, room_id, host_name, game_mode='hanchan', match_type='yuujin'):
        """初始化麻将房间
        
        Args:
            room_id: 房间ID
            host_name: 房主名称
            game_mode: 游戏模式 'tonpu'=东风战, 'hanchan'=半庄战
            match_type: 段位场类型 'yuujin'=友人场, 'dou'=铜之间, etc.
        """
        self.room_id = room_id
        self.host = host_name
        self.players = {0: host_name, 1: None, 2: None, 3: None}  # 4个位置
        self.player_avatars = {0: None, 1: None, 2: None, 3: None}  # 玩家头像
        self.player_ranks = {0: None, 1: None, 2: None, 3: None}  # 玩家段位
        self.state = 'waiting'  # waiting, playing, finished
        
        # 游戏模式和段位场
        self.game_mode = game_mode  # tonpu / hanchan
        self.match_type = match_type  # yuujin / dou / gin / kin / gyoku / ouza
        
        # game_type 标识（客户端渲染器查表用）
        mode_info = self.GAME_MODES.get(game_mode, self.GAME_MODES['hanchan'])
        self.game_type = 'mahjong'
        
        # 牌相关
        self.deck = []  # 牌堆
        self.dead_wall = []  # 王牌区（最后14张，包含宝牌指示牌和岭上牌）
        self.hands = {0: [], 1: [], 2: [], 3: []}  # 各玩家手牌
        self.discards = {0: [], 1: [], 2: [], 3: []}  # 各玩家弃牌
        self.melds = {0: [], 1: [], 2: [], 3: []}  # 副露（碰、杠、吃）
        
        # 回合相关
        self.current_turn = 0  # 当前轮到谁
        self.last_discard = None  # 最后打出的牌
        self.last_discarder = None  # 最后打出牌的人
        self.just_drew = False  # 刚刚摸牌（用于判断自摸）
        self.pending_action = None  # 待处理的吃碰杠动作
        self.waiting_for_action = False  # 是否在等待吃碰杠操作
        self.action_players = []  # 可以执行操作的玩家列表
        self.first_turn = {0: True, 1: True, 2: True, 3: True}  # 是否第一巡（用于天和/地和/双立直）
        
        # 立直相关
        self.riichi = {0: False, 1: False, 2: False, 3: False}  # 是否立直
        self.riichi_turn = {0: -1, 1: -1, 2: -1, 3: -1}  # 立直的回合数
        self.double_riichi = {0: False, 1: False, 2: False, 3: False}  # 是否双立直
        self.ippatsu = {0: False, 1: False, 2: False, 3: False}  # 一发有效
        self.riichi_sticks = 0  # 场上立直棒数量
        
        # 振听相关
        self.furiten = {0: False, 1: False, 2: False, 3: False}  # 振听状态
        self.temp_furiten = {0: False, 1: False, 2: False, 3: False}  # 同巡振听
        
        # 宝牌相关
        self.dora_indicators = []  # 宝牌指示牌（翻开的）
        self.ura_dora_indicators = []  # 里宝牌指示牌（立直胡牌时翻开）
        self.kan_count = 0  # 杠的次数（用于翻杠宝牌）
        
        # 局数相关
        self.round_wind = '东'  # 场风（东风/南风）
        self.round_number = 0  # 第几局（0-3，对应1-4局显示时+1）
        self.honba = 0  # 本场数
        self.dealer = 0  # 庄家位置
        self.scores = {0: 25000, 1: 25000, 2: 25000, 3: 25000}  # 各玩家点数
        # game_type 已在上面设置
        
        # 特殊状态
        self.rinshan = False  # 岭上开花
        self.chankan_tile = None  # 抢杠的牌
        self.turn_count = 0  # 总回合数
        self.last_action = None  # 最后一个动作（用于判断一发失效）
        self.bots = set()  # 机器人玩家名称集合
        
        # 吃换禁止相关
        self.kuikae_forbidden = {0: [], 1: [], 2: [], 3: []}  # 各玩家吃牌后禁止打出的牌
        self.just_chowed = {0: False, 1: False, 2: False, 3: False}  # 是否刚吃牌
        
        # 三家和了相关
        self.pending_rons = {}  # {position: tile} 声明荣和的玩家
        self.ron_responses = {}  # {position: True/False} 所有可荣和玩家的响应
        
        # 包牌相关
        # pao_responsibility[position] = {'type': 'daisangen'/'daisuushi'/'suukantsu', 'feeder': feeder_pos}
        self.pao_responsibility = {0: None, 1: None, 2: None, 3: None}
    
    # ==================== 玩家管理 ====================
    
    def add_bot(self):
        """添加一个机器人玩家
        
        Returns:
            (success, bot_name): 是否成功，机器人名称
        """
        if self.is_full():
            return False, "房间已满"
        
        if self.state != 'waiting':
            return False, "游戏已开始"
        
        # 使用简单的 bot1, bot2, bot3 命名
        used_names = set(self.players.values()) | self.bots
        
        bot_name = None
        for i in range(1, 10):
            name = f"bot{i}"
            if name not in used_names:
                bot_name = name
                break
        
        if not bot_name:
            import time
            bot_name = f"bot{int(time.time()) % 1000}"
        
        # 生成随机头像
        bot_avatar = self._generate_bot_avatar()
        
        # 加入房间
        pos = self.add_player(bot_name, avatar=bot_avatar)
        if pos >= 0:
            self.bots.add(bot_name)
            return True, bot_name
        
        return False, "加入失败"
    
    def _generate_bot_avatar(self):
        """生成机器人随机像素头像"""
        import json
        # 生成简单的像素头像（16x16）
        AVATAR_SIZE = 16
        PALETTE = [
            '#000000', '#FFFFFF', '#FF0000', '#00FF00', '#0000FF',
            '#FFFF00', '#FF00FF', '#00FFFF', '#FFA500', '#800080',
            '#008000', '#000080', '#808080', '#C0C0C0', '#800000'
        ]
        
        # 用对称设计让头像更好看
        pixels = [[None for _ in range(AVATAR_SIZE)] for _ in range(AVATAR_SIZE)]
        
        # 随机选择几个颜色
        colors = random.sample(PALETTE[:10], 3)
        bg_color = random.choice(['#FFFFFF', '#F0F0F0', '#E0E0E0', '#D0D0D0'])
        
        # 填充背景
        for y in range(AVATAR_SIZE):
            for x in range(AVATAR_SIZE):
                pixels[y][x] = bg_color
        
        # 生成左半边，然后镜像到右边（水平对称）
        half = AVATAR_SIZE // 2
        for y in range(2, AVATAR_SIZE - 2):
            for x in range(2, half + 1):
                if random.random() < 0.4:
                    color = random.choice(colors)
                    pixels[y][x] = color
                    pixels[y][AVATAR_SIZE - 1 - x] = color  # 镜像
        
        return json.dumps(pixels)
    
    def is_bot(self, player_name):
        """检查是否是机器人"""
        return player_name in self.bots
    
    def get_player_count(self):
        """获取玩家数量"""
        return sum(1 for p in self.players.values() if p is not None)
    
    def is_full(self):
        """房间是否满员"""
        return self.get_player_count() >= 4
    
    def add_player(self, name, avatar=None):
        """加入玩家"""
        for i in range(4):
            if self.players[i] is None:
                self.players[i] = name
                self.player_avatars[i] = avatar
                return i
        return -1
    
    def remove_player(self, name):
        """移除玩家"""
        for i in range(4):
            if self.players[i] == name:
                self.players[i] = None
                self.player_avatars[i] = None
                return i
        return -1
    
    def set_player_avatar(self, name, avatar):
        """设置玩家头像"""
        for i in range(4):
            if self.players[i] == name:
                self.player_avatars[i] = avatar
                return True
        return False
    
    def set_player_rank(self, name, rank_id):
        """设置玩家段位"""
        for i in range(4):
            if self.players[i] == name:
                self.player_ranks[i] = rank_id
                return True
        return False
    
    def get_position(self, name):
        """获取玩家位置"""
        for i in range(4):
            if self.players[i] == name:
                return i
        return -1
    
    def get_current_player_name(self):
        """获取当前回合玩家名字"""
        if self.current_turn >= 0 and self.current_turn < 4:
            return self.players[self.current_turn]
        return None
    
    # ==================== 游戏流程 ====================
    
    def start_game(self, game_data):
        """开始游戏"""
        if not self.is_full():
            return False
        
        # 随机分配座位（打乱玩家位置）
        players_list = [(self.players[i], self.player_avatars[i]) for i in range(4)]
        random.shuffle(players_list)
        for i in range(4):
            self.players[i] = players_list[i][0]
            self.player_avatars[i] = players_list[i][1]
        
        # 随机选择庄家
        self.dealer = random.randint(0, 3)
        
        self.state = 'playing'
        
        # 洗牌（使用赤宝牌）
        self.deck = game_data.get_all_tiles(use_red_dora=True)
        random.shuffle(self.deck)
        
        # 王牌区（最后14张）
        self.dead_wall = [self.deck.pop() for _ in range(14)]
        
        # 设置宝牌指示牌（第5张翻开）
        self.dora_indicators = [self.dead_wall[4]]
        self.ura_dora_indicators = [self.dead_wall[5]]  # 里宝牌（立直胡牌时翻开）
        
        # 发牌（每人13张）
        for i in range(4):
            self.hands[i] = [self.deck.pop() for _ in range(13)]
            self.hands[i].sort(key=self._tile_sort_key)
        
        # 庄家多摸一张（放最后，不排序）
        self.hands[self.dealer].append(self.deck.pop())
        
        self.current_turn = self.dealer
        self.just_drew = True  # 庄家已经摸牌了
        self.turn_count = 0
        
        # 重置一发/振听等状态
        for i in range(4):
            self.first_turn[i] = True
            self.riichi[i] = False
            self.ippatsu[i] = False
            self.furiten[i] = False
            self.temp_furiten[i] = False
        
        return True
    
    def start_next_round(self):
        """开始下一局
        
        Returns:
            bool: True表示成功开始下一局，False表示游戏结束
        """
        if self.state != 'finished':
            return False
        
        # 检查游戏是否应该结束
        wind_order = ['东', '南', '西', '北']
        current_wind_idx = wind_order.index(self.round_wind)
        
        # 检查是否有人分数归零（被飞）
        for score in self.scores.values():
            if score < 0:
                return False  # 游戏结束
        
        # 检查是否完成南4局
        if self.round_wind == '南' and self.round_number >= 3:
            # 南4局结束，检查是否有人30000点以上
            if any(s >= 30000 for s in self.scores.values()):
                return False  # 游戏结束
        
        # 更新局数和庄家
        if not hasattr(self, '_renchan') or not self._renchan:
            # 轮庄
            self.dealer = (self.dealer + 1) % 4
            if self.dealer == 0:
                # 回到东家，进入下一个场风
                if current_wind_idx < len(wind_order) - 1:
                    self.round_wind = wind_order[current_wind_idx + 1]
                    self.round_number = 0
                else:
                    return False  # 游戏结束
            else:
                self.round_number = self.dealer
        
        # 重置游戏状态
        self.state = 'playing'
        
        # 洗牌
        from .game_data import MahjongData
        game_data = MahjongData()
        self.deck = game_data.get_all_tiles(use_red_dora=True)
        random.shuffle(self.deck)
        
        # 重置手牌、副露、弃牌
        for i in range(4):
            self.hands[i] = []
            self.melds[i] = []
            self.discards[i] = []
        
        # 王牌区
        self.dead_wall = [self.deck.pop() for _ in range(14)]
        self.dora_indicators = [self.dead_wall[4]]
        self.ura_dora_indicators = [self.dead_wall[5]]
        
        # 发牌
        for i in range(4):
            self.hands[i] = [self.deck.pop() for _ in range(13)]
            self.hands[i].sort(key=self._tile_sort_key)
        
        # 庄家多摸一张
        self.hands[self.dealer].append(self.deck.pop())
        
        self.current_turn = self.dealer
        self.just_drew = True
        self.turn_count = 0
        self.kan_count = 0
        
        # 重置所有状态
        self.last_discard = None
        self.last_discarder = None
        self.waiting_for_action = False
        self.action_players = []
        self.rinshan = False
        self.chankan_tile = None
        self.last_action = None
        
        for i in range(4):
            self.first_turn[i] = True
            self.riichi[i] = False
            self.double_riichi[i] = False
            self.riichi_turn[i] = -1
            self.ippatsu[i] = False
            self.furiten[i] = False
            self.temp_furiten[i] = False
            self.kuikae_forbidden[i] = []
            self.just_chowed[i] = False
            self.pao_responsibility[i] = None
        
        # 清除荣和相关状态
        self.pending_rons = {}
        self.ron_responses = {}
        
        return True
    
    def get_player_wind(self, position):
        """获取玩家自风"""
        # 庄家是东，逆时针分配
        return self.WINDS[(position - self.dealer) % 4]
    
    def draw_tile(self, position, from_dead_wall=False):
        """摸牌 - 新摸的牌放最后，其他牌排序（雀魂风格）"""
        if from_dead_wall:
            # 岭上摸牌（杠后）
            if len(self.dead_wall) <= 4:  # 保留宝牌指示牌
                return None
            tile = self.dead_wall.pop(0)
            self.rinshan = True
        else:
            if not self.deck:
                return None
            tile = self.deck.pop()
            self.rinshan = False
        
        # 先排序现有手牌，再把新牌加到最后
        self.hands[position].sort(key=self._tile_sort_key)
        self.hands[position].append(tile)
        self.just_drew = True
        
        # 岭上摸牌不增加回合数
        if not from_dead_wall:
            self.turn_count += 1
        
        # 清除同巡振听
        self.temp_furiten[position] = False
        
        return tile
    
    def is_haitei(self):
        """是否是海底（最后一张牌）"""
        return len(self.deck) == 0
    
    def check_ryuukyoku(self):
        """检查是否流局"""
        return len(self.deck) == 0
    
    def check_kyuushu_kyuuhai(self, position):
        """检查九种九牌（配牌时有9种以上幺九牌可选择流局）"""
        # 只能在第一巡、自己的第一次摸牌时使用
        if not self.first_turn[position]:
            return False
        
        # 不能有任何副露发生
        for i in range(4):
            if self.melds[i]:
                return False
        
        hand = self.hands[position]
        from .game_data import is_yaojiu
        
        # 统计不同种类的幺九牌
        yaojiu_types = set()
        for tile in hand:
            if is_yaojiu(tile):
                yaojiu_types.add(tile)
        
        return len(yaojiu_types) >= 9
    
    def check_suufon_renda(self):
        """检查四风连打（第一巡四家打出相同风牌）"""
        # 必须是第一巡
        if self.turn_count > 4:
            return False
        
        # 检查是否每个人都只打了一张牌
        for i in range(4):
            if len(self.discards[i]) != 1:
                return False
        
        # 检查是否都是同一张风牌
        first_discard = self.discards[0][0]
        if first_discard not in ['东', '南', '西', '北']:
            return False
        
        for i in range(1, 4):
            if self.discards[i][0] != first_discard:
                return False
        
        return True
    
    def check_suucha_riichi(self):
        """检查四家立直"""
        return all(self.riichi)
    
    def check_suukaikan(self):
        """检查四杠散了（两人以上共开4杠则流局）"""
        if self.kan_count < 4:
            return False
        
        # 统计每个人的杠数
        players_with_kan = 0
        for i in range(4):
            player_kans = sum(1 for m in self.melds[i] if m['type'] in ('kong', 'concealed_kong'))
            if player_kans > 0:
                players_with_kan += 1
        
        # 两人以上开了杠，且总共4杠，则流局
        return players_with_kan >= 2
    
    def check_furiten(self, position):
        """检查振听状态"""
        # 临时振听
        if self.temp_furiten[position]:
            return True
        
        # 永久振听（打出过听的牌）
        if self.furiten[position]:
            return True
        
        return False
    
    # ==================== 立直相关 ====================
    
    def can_declare_riichi(self, position):
        """检查是否可以立直（返回可以立直打出的牌列表）
        
        Returns:
            list: 可以打出并立直的牌列表，空列表表示不能立直
        """
        # 已经立直
        if self.riichi[position]:
            return []
        
        # 点数不足
        if self.scores[position] < 1000:
            return []
        
        # 检查是否门清
        for m in self.melds[position]:
            if m['type'] != 'concealed_kong':
                return []
        
        # 检查牌山剩余张数（至少要有4张）
        if len(self.deck) < 4:
            return []
        
        # 检查打哪些牌可以听牌
        riichi_tiles = []
        hand = self.hands[position]
        checked = set()
        
        from .game_data import normalize_tile
        for tile in hand:
            norm_tile = normalize_tile(tile)
            if norm_tile in checked:
                continue
            checked.add(norm_tile)
            
            # 临时移除这张牌
            temp_hand = hand.copy()
            temp_hand.remove(tile)
            
            # 检查是否听牌
            original_hand = self.hands[position]
            self.hands[position] = temp_hand
            tenpai_tiles = self.get_tenpai_tiles(position)
            self.hands[position] = original_hand
            
            if tenpai_tiles:
                riichi_tiles.append(tile)
        
        return riichi_tiles
    
    def declare_riichi(self, position, discard_tile):
        """宣告立直
        
        Returns:
            (success, error_msg)
        """
        # 检查条件
        if self.riichi[position]:
            return False, "已经立直了"
        
        if self.scores[position] < 1000:
            return False, "点数不足"
        
        # 检查是否门清
        for m in self.melds[position]:
            if m['type'] != 'concealed_kong':
                return False, "副露后不能立直"
        
        # 检查打掉这张牌后是否听牌
        temp_hand = self.hands[position].copy()
        if discard_tile in temp_hand:
            temp_hand.remove(discard_tile)
        else:
            return False, "没有这张牌"
        
        # 临时移除牌后检查听牌
        original_hand = self.hands[position]
        self.hands[position] = temp_hand
        tenpai_tiles = self.get_tenpai_tiles(position)
        self.hands[position] = original_hand
        
        if not tenpai_tiles:
            return False, "打这张牌不能听牌"
        
        # 扣除立直棒
        self.scores[position] -= 1000
        self.riichi_sticks += 1
        
        # 设置立直状态
        self.riichi[position] = True
        self.riichi_turn[position] = self.turn_count
        self.ippatsu[position] = True  # 一发有效
        
        # 检查双立直
        if self.first_turn[position]:
            self.double_riichi[position] = True
        
        return True, None
    
    # ==================== 工具方法 ====================
    
    def _tile_sort_key(self, tile):
        """牌排序的key函数 - 万>条>筒>字，赤牌排在普通5之前"""
        order = {
            # 万子
            '一万': 10, '二万': 11, '三万': 12, '四万': 13, 
            '赤五万': 14, '五万': 15, '六万': 16, '七万': 17, '八万': 18, '九万': 19,
            # 条子
            '一条': 20, '二条': 21, '三条': 22, '四条': 23,
            '赤五条': 24, '五条': 25, '六条': 26, '七条': 27, '八条': 28, '九条': 29,
            # 筒子
            '一筒': 30, '二筒': 31, '三筒': 32, '四筒': 33,
            '赤五筒': 34, '五筒': 35, '六筒': 36, '七筒': 37, '八筒': 38, '九筒': 39,
            # 字牌
            '东': 40, '南': 41, '西': 42, '北': 43,
            '中': 44, '发': 45, '白': 46,
        }
        return order.get(tile, 99)
    
    # ==================== 显示/状态获取 ====================
    
    def get_hand_display(self, position):
        """获取手牌显示"""
        return ' '.join(self.hands[position])
    
    def get_table_display(self):
        """获取牌桌显示（用于右上角面板）"""
        from server.text_utils import pad_center, truncate
        lines = []
        lines.append("┌─────────────────┐")
        lines.append(f"│    {self.POSITIONS[2]}:{pad_center(self.players[2] or '空位', 8)}  │")
        lines.append("│  ┌───────────┐  │")
        lines.append(f"│{self.POSITIONS[3]}│           │{self.POSITIONS[1]}│")
        lines.append(f"│  │  🀄牌桌   │  │")
        lines.append(f"│{pad_center(truncate(self.players[3] or '空', 2), 2)}│           │{pad_center(truncate(self.players[1] or '空', 2), 2)}│")
        lines.append("│  └───────────┘  │")
        lines.append(f"│    {self.POSITIONS[0]}:{pad_center(self.players[0] or '空位', 8)}  │")
        lines.append("└─────────────────┘")
        return lines
    
    def _get_sorted_positions(self):
        """按自风东南西北顺序返回玩家位置数据"""
        wind_order = {'东': 0, '南': 1, '西': 2, '北': 3}
        
        positions = []
        for i in range(4):
            wind = self.get_player_wind(i)
            positions.append({
                'position': i,
                'wind': wind,
                'wind_order': wind_order.get(wind, i),
                'name': self.players[i],
                'avatar': self.player_avatars[i],
                'is_turn': self.state == 'playing' and self.current_turn == i,
                'is_dealer': i == self.dealer,
                'is_riichi': self.riichi[i],
                'score': self.scores[i],
                'discards': self.discards[i],
                'melds': self.melds[i]
            })
        
        # 按自风顺序排序（东南西北）
        positions.sort(key=lambda p: p['wind_order'])
        return positions
    
    def get_table_data(self):
        """获取牌桌数据（用于UI渲染）"""
        # 计算宝牌
        dora_tiles = []
        from .game_data import DORA_NEXT, normalize_tile
        for indicator in self.dora_indicators:
            dora = DORA_NEXT.get(normalize_tile(indicator), indicator)
            dora_tiles.append(dora)
        
        # 检查各玩家的役满确定状态
        yakuman_certain = {}
        for i in range(4):
            if self.players[i]:
                yakuman_certain[i] = self.check_yakuman_certain(i)
        
        # 获取游戏模式和段位场信息
        mode_info = self.GAME_MODES.get(self.game_mode, self.GAME_MODES['hanchan'])
        match_info = self.MATCH_TYPES.get(self.match_type, self.MATCH_TYPES['yuujin'])
        
        return {
            'room_id': self.room_id,
            'host': self.host,
            'state': self.state,
            'current_turn': self.current_turn,
            'deck_remaining': len(self.deck),
            'round_wind': self.round_wind,
            'round_number': self.round_number,
            'honba': self.honba,
            'riichi_sticks': self.riichi_sticks,
            'dora_indicators': self.dora_indicators,
            'dora_tiles': dora_tiles,
            'positions': self._get_sorted_positions(),
            'player_count': self.get_player_count(),
            'is_full': self.is_full(),
            'last_discard': self.last_discard,
            'game_mode': self.game_mode,
            'match_type': self.match_type,
            'game_mode_name': mode_info['name_cn'],
            'match_type_name': match_info['name_cn'],
            'is_ranked': match_info.get('ranked', False),
            'player_ranks': self.player_ranks,
            'yakuman_certain': yakuman_certain,
            # 兼容旧代码
            'game_type': self.game_type,
            'game_type_name': f"{match_info['name_cn']} {mode_info['name_cn']}"
        }
    
    def get_status(self):
        """获取房间状态"""
        mode_info = self.GAME_MODES.get(self.game_mode, self.GAME_MODES['hanchan'])
        match_info = self.MATCH_TYPES.get(self.match_type, self.MATCH_TYPES['yuujin'])
        return {
            'room_id': self.room_id,
            'host': self.host,
            'players': self.players,
            'state': self.state,
            'player_count': self.get_player_count(),
            'game_mode': self.game_mode,
            'match_type': self.match_type,
            'game_mode_name': mode_info['name_cn'],
            'match_type_name': match_info['name_cn'],
            'is_ranked': match_info.get('ranked', False),
            'min_rank': match_info.get('min_rank'),
            'player_ranks': self.player_ranks,
            # 兼容旧代码
            'game_type': self.game_type,
            'game_type_name': f"{match_info['name_cn']} {mode_info['name_cn']}"
        }
    
    def is_ranked_match(self):
        """是否为段位场"""
        match_info = self.MATCH_TYPES.get(self.match_type, {})
        return match_info.get('ranked', False)
    
    def get_min_rank_requirement(self):
        """获取最低段位要求"""
        match_info = self.MATCH_TYPES.get(self.match_type, {})
        return match_info.get('min_rank')
