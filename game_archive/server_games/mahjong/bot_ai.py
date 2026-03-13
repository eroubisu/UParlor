"""
麻将机器人 AI 模块
实现智能出牌、吃碰杠决策
"""

from .game_data import (
    normalize_tile, get_tile_suit, get_tile_number, 
    is_number_tile, is_honor_tile, is_terminal, is_yaojiu,
    YAOJIU, SANGENPAI, KAZEHAI, get_tile_by_suit_number
)


class BotAI:
    """麻将机器人 AI"""
    
    def __init__(self, room, position):
        """
        Args:
            room: MahjongRoom 实例
            position: 机器人在房间中的位置 (0-3)
        """
        self.room = room
        self.position = position
    
    def decide_discard(self):
        """决定打哪张牌
        
        Returns:
            str: 要打出的牌
        """
        hand = self.room.hands[self.position]
        if not hand:
            return None
        
        # 如果立直了，必须摸切（打最后摸到的牌）
        if self.room.riichi[self.position]:
            return hand[-1]
        
        # 计算每张牌的评分（越低越应该打出）
        tile_scores = {}
        checked = set()
        
        for tile in hand:
            norm = normalize_tile(tile)
            if norm in checked:
                continue
            checked.add(norm)
            
            score = self._evaluate_tile(tile, hand)
            tile_scores[tile] = score
        
        # 找到评分最低的牌
        if tile_scores:
            worst_tile = min(tile_scores.keys(), key=lambda t: tile_scores[t])
            return worst_tile
        
        # fallback: 打最后一张
        return hand[-1]
    
    def _evaluate_tile(self, tile, hand):
        """评估一张牌的价值（越高越不应该打）
        
        评分规则：
        - 刻子（3张相同）: +30
        - 对子（2张相同）: +15
        - 搭子（相邻2张可组顺子）: +12
        - 两面搭子: +15
        - 嵌张搭子: +10
        - 边张搭子: +8
        - 孤张字牌（役牌）: +5
        - 孤张字牌（客风）: +2
        - 孤张老头牌: +3
        - 孤张中张牌: +6
        - 赤宝牌加成: +5
        """
        norm_tile = normalize_tile(tile)
        suit = get_tile_suit(norm_tile)
        num = get_tile_number(norm_tile)
        
        # 统计手牌中相同牌的数量
        same_count = sum(1 for t in hand if normalize_tile(t) == norm_tile)
        
        score = 0
        
        # 刻子/对子加分
        if same_count >= 3:
            score += 30  # 刻子
        elif same_count == 2:
            score += 15  # 对子
        
        # 数牌检查搭子
        if is_number_tile(norm_tile):
            # 检查是否有相邻牌（形成搭子）
            has_adj = False
            adj_type = None
            
            for other in hand:
                other_norm = normalize_tile(other)
                if other_norm == norm_tile:
                    continue
                other_suit = get_tile_suit(other_norm)
                other_num = get_tile_number(other_norm)
                
                if other_suit == suit:
                    diff = abs(other_num - num)
                    if diff == 1:
                        has_adj = True
                        # 判断搭子类型
                        min_num = min(num, other_num)
                        max_num = max(num, other_num)
                        if min_num == 1 or max_num == 9:
                            adj_type = 'edge'  # 边张
                        else:
                            adj_type = 'ryanmen'  # 两面
                    elif diff == 2:
                        has_adj = True
                        adj_type = 'kanchan'  # 嵌张
            
            if has_adj:
                if adj_type == 'ryanmen':
                    score += 15
                elif adj_type == 'kanchan':
                    score += 10
                elif adj_type == 'edge':
                    score += 8
            else:
                # 孤张
                if is_terminal(norm_tile):
                    score += 3  # 老头牌价值低
                else:
                    score += 6  # 中张孤张稍有价值
        else:
            # 字牌
            if same_count == 1:
                # 孤张字牌
                player_wind = self._get_player_wind()
                round_wind = self.room.round_wind
                
                if norm_tile in SANGENPAI:
                    score += 5  # 三元牌
                elif norm_tile == player_wind or norm_tile == round_wind:
                    score += 5  # 自风/场风
                else:
                    score += 2  # 客风，价值很低
        
        # 赤宝牌加分
        if tile != norm_tile:  # 赤牌
            score += 5
        
        return score
    
    def _get_player_wind(self):
        """获取玩家自风"""
        winds = ['东', '南', '西', '北']
        return winds[(self.position - self.room.dealer) % 4]
    
    def decide_action(self, tile, available_actions):
        """决定是否执行吃碰杠等操作
        
        Args:
            tile: 被打出的牌
            available_actions: 可用的操作 dict {'win': True, 'pong': True, ...}
            
        Returns:
            str or None: 'win', 'kong', 'pong', 'chow', None (pass)
        """
        # 能胡就胡
        if available_actions.get('win'):
            return 'win'
        
        hand = self.room.hands[self.position]
        norm_tile = normalize_tile(tile)
        
        # 明杠判断：手里有3张相同的
        if available_actions.get('kong'):
            same_count = sum(1 for t in hand if normalize_tile(t) == norm_tile)
            if same_count >= 3:
                # 一般不推荐明杠普通牌，役牌可以考虑
                if norm_tile in SANGENPAI:
                    return 'kong'
                # 50% 概率杠风牌
                if norm_tile in KAZEHAI:
                    import random
                    if random.random() < 0.5:
                        return 'kong'
        
        # 碰判断
        if available_actions.get('pong'):
            # 役牌优先碰
            if norm_tile in SANGENPAI:
                return 'pong'
            
            player_wind = self._get_player_wind()
            round_wind = self.room.round_wind
            if norm_tile == player_wind or norm_tile == round_wind:
                return 'pong'
            
            # 其他牌：检查向听数变化
            # 简化：不主动碰普通牌（保持门清）
        
        # 吃判断
        if available_actions.get('chow'):
            # 简化：不主动吃（保持门清）
            pass
        
        return None  # 默认过
    
    def decide_self_action(self, available_actions):
        """决定是否执行立直、暗杠、加杠、自摸等操作
        
        Args:
            available_actions: dict {'tsumo': True, 'riichi': [...], 'ankan': [...], ...}
            
        Returns:
            tuple: (action, param) 如 ('tsumo', None), ('riichi', tile), ('ankan', tile), None
        """
        # 能自摸就自摸
        if available_actions.get('tsumo'):
            return ('tsumo', None)
        
        # 能立直就立直（选择第一个可立直的牌）
        riichi_tiles = available_actions.get('riichi', [])
        if riichi_tiles:
            return ('riichi', riichi_tiles[0])
        
        # 暗杠判断
        ankan_tiles = available_actions.get('ankan', [])
        if ankan_tiles:
            # 只杠役牌
            for tile in ankan_tiles:
                norm = normalize_tile(tile)
                if norm in SANGENPAI:
                    return ('ankan', tile)
        
        return None


def get_bot_discard(room, position):
    """获取机器人应该打出的牌
    
    Args:
        room: MahjongRoom 实例
        position: 机器人位置
        
    Returns:
        str: 要打出的牌
    """
    ai = BotAI(room, position)
    return ai.decide_discard()


def get_bot_action(room, position, tile, available_actions):
    """获取机器人对别人打牌的响应
    
    Args:
        room: MahjongRoom 实例
        position: 机器人位置
        tile: 被打出的牌
        available_actions: 可用操作
        
    Returns:
        str or None: 操作类型
    """
    ai = BotAI(room, position)
    return ai.decide_action(tile, available_actions)


def get_bot_self_action(room, position, available_actions):
    """获取机器人的自摸/立直/暗杠等决策
    
    Args:
        room: MahjongRoom 实例
        position: 机器人位置
        available_actions: 可用操作
        
    Returns:
        tuple or None: (action, param)
    """
    ai = BotAI(room, position)
    return ai.decide_self_action(available_actions)
