"""
麻将游戏 - 吃碰杠胡操作模块
"""


class ActionsMixin:
    """吃碰杠胡等操作相关方法的Mixin类"""
    
    def check_actions(self, position, discarded_tile):
        """检查玩家可以对打出的牌执行什么操作
        
        Args:
            position: 检查的玩家位置
            discarded_tile: 被打出的牌
            
        Returns:
            dict: {可用操作类型: 操作详情}
        """
        if self.state != 'playing':
            return {}
        
        actions = {}
        hand = self.hands[position]
        
        from .game_data import normalize_tile
        norm_tile = normalize_tile(discarded_tile)
        
        # 统计手牌中相同牌的数量（考虑赤宝牌）
        matching_count = sum(1 for t in hand if normalize_tile(t) == norm_tile)
        
        # 检查胡牌 - 优先级最高（立直后也可以荣和）
        if self.can_win(hand, discarded_tile):
            actions['win'] = {
                'tile': discarded_tile,
                'display': f'胡 {discarded_tile}'
            }
        
        # 立直后不能吃、碰、杠
        if self.riichi[position]:
            return actions
        
        # 检查碰 - 手里有2张相同的牌（考虑赤宝牌）
        if matching_count >= 2:
            actions['pong'] = {
                'tile': discarded_tile,
                'display': f'碰 {discarded_tile}'
            }
        
        # 检查明杠 - 手里有3张相同的牌（考虑赤宝牌）
        if matching_count >= 3:
            actions['kong'] = {
                'tile': discarded_tile,
                'display': f'杠 {discarded_tile}'
            }
        
        # 检查吃 - 只有下家可以吃，且只能吃数牌（万、条、筒）
        if position == self.current_turn:  # 当前玩家是下家
            chow_options = self._get_chow_options(hand, discarded_tile)
            if chow_options:
                actions['chow'] = {
                    'tile': discarded_tile,
                    'options': chow_options,
                    'display': f'吃 {discarded_tile}'
                }
        
        return actions
    
    def _get_chow_options(self, hand, tile):
        """获取吃牌的选项（支持赤宝牌）"""
        from .game_data import normalize_tile, get_tile_suit, get_tile_number, get_tile_by_suit_number
        
        norm_tile = normalize_tile(tile)
        suit = get_tile_suit(norm_tile)
        num = get_tile_number(norm_tile)
        
        if suit == 'zi' or num is None:
            return []  # 字牌不能吃
        
        options = []
        
        # 辅助函数：检查手牌中是否有某张牌（考虑赤牌）
        def has_tile(target_tile):
            target_norm = normalize_tile(target_tile)
            return any(normalize_tile(h) == target_norm for h in hand)
        
        # 辅助函数：从手牌中获取实际的牌（可能是赤牌）
        def get_actual_tile(target_tile):
            target_norm = normalize_tile(target_tile)
            for h in hand:
                if normalize_tile(h) == target_norm:
                    return h
            return target_tile
        
        # 检查三种吃法：
        # 1. tile作为顺子的第一张 (tile, tile+1, tile+2)
        if num <= 7:
            t1 = get_tile_by_suit_number(suit, num+1)
            t2 = get_tile_by_suit_number(suit, num+2)
            if t1 and t2 and has_tile(t1) and has_tile(t2):
                options.append([tile, get_actual_tile(t1), get_actual_tile(t2)])
        
        # 2. tile作为顺子的第二张 (tile-1, tile, tile+1)
        if 2 <= num <= 8:
            t0 = get_tile_by_suit_number(suit, num-1)
            t2 = get_tile_by_suit_number(suit, num+1)
            if t0 and t2 and has_tile(t0) and has_tile(t2):
                options.append([get_actual_tile(t0), tile, get_actual_tile(t2)])
        
        # 3. tile作为顺子的第三张 (tile-2, tile-1, tile)
        if num >= 3:
            t0 = get_tile_by_suit_number(suit, num-2)
            t1 = get_tile_by_suit_number(suit, num-1)
            if t0 and t1 and has_tile(t0) and has_tile(t1):
                options.append([get_actual_tile(t0), get_actual_tile(t1), tile])
        
        return options
    
    def check_self_kong(self, position):
        """检查玩家是否可以暗杠或加杠
        
        Returns:
            list: 可以杠的牌列表
        """
        if self.state != 'playing':
            return []
        
        hand = self.hands[position]
        kong_tiles = []
        
        from .game_data import normalize_tile
        
        # 检查暗杠 - 手里有4张相同的牌（考虑赤牌）
        tile_counts = {}
        for tile in hand:
            norm = normalize_tile(tile)
            tile_counts[norm] = tile_counts.get(norm, 0) + 1
        
        for norm_tile, count in tile_counts.items():
            if count >= 4:
                # 立直后暗杠需要检查是否改变听牌
                if self.riichi[position]:
                    if not self._can_riichi_ankan(position, norm_tile):
                        continue  # 这个暗杠会改变听牌，不允许
                
                # 找出手牌中的实际牌（可能包含赤牌）
                actual_tiles = [t for t in hand if normalize_tile(t) == norm_tile][:4]
                kong_tiles.append({
                    'type': 'concealed', 
                    'tile': norm_tile, 
                    'actual_tiles': actual_tiles,
                    'display': f'暗杠 {norm_tile}'
                })
        
        # 立直后不能加杠
        if self.riichi[position]:
            return kong_tiles
        
        # 检查加杠 - 已碰的牌，手里还有1张
        for meld in self.melds[position]:
            if meld['type'] == 'pong':
                pong_tile = normalize_tile(meld['tiles'][0])
                # 检查手牌中是否有这张牌
                for tile in hand:
                    if normalize_tile(tile) == pong_tile:
                        kong_tiles.append({
                            'type': 'added',
                            'tile': pong_tile,
                            'actual_tile': tile,
                            'display': f'加杠 {pong_tile}'
                        })
                        break
        
        return kong_tiles
    
    def _can_riichi_ankan(self, position, kong_tile):
        """检查立直后暗杠是否合法（不改变听牌形式）
        
        立直后暗杠条件：
        1. 暗杠的牌必须是手牌中已有的暗刻
        2. 暗杠后听的牌必须完全相同
        
        Args:
            position: 玩家位置
            kong_tile: 要暗杠的牌（标准化后）
            
        Returns:
            bool: 是否可以暗杠
        """
        from .game_data import normalize_tile
        
        hand = self.hands[position]
        
        # 获取当前听牌
        original_tenpai = set(self.get_tenpai_tiles(position))
        if not original_tenpai:
            return False
        
        # 模拟暗杠后的手牌（移除4张牌）
        temp_hand = hand.copy()
        removed = 0
        for tile in hand:
            if normalize_tile(tile) == kong_tile and removed < 4:
                temp_hand.remove(tile)
                removed += 1
        
        if removed != 4:
            return False
        
        # 临时修改手牌检查听牌
        original_hand = self.hands[position]
        self.hands[position] = temp_hand
        new_tenpai = set(self.get_tenpai_tiles(position))
        self.hands[position] = original_hand
        
        # 听牌必须完全相同
        return original_tenpai == new_tenpai
    
    def do_pong(self, position, tile):
        """执行碰操作
        
        Args:
            position: 碰牌的玩家位置
            tile: 要碰的牌
            
        Returns:
            bool: 是否成功
        """
        from .game_data import normalize_tile
        
        hand = self.hands[position]
        norm_tile = normalize_tile(tile)
        
        # 检查手里有2张（考虑赤牌）
        matching = [t for t in hand if normalize_tile(t) == norm_tile]
        if len(matching) < 2:
            return False
        
        # 获取打牌人的位置
        discarder_pos = self.last_discarder if self.last_discarder is not None else (position - 1) % 4
        
        # 检查包牌条件（在碰之前检查已有的副露）
        self._check_pao_before_meld(position, norm_tile, discarder_pos)
        
        # 从手里移除2张
        for t in matching[:2]:
            hand.remove(t)
        
        # 从打牌人弃牌堆移除最后一张
        if self.discards[discarder_pos] and normalize_tile(self.discards[discarder_pos][-1]) == norm_tile:
            discarded = self.discards[discarder_pos].pop()
        else:
            discarded = tile
        
        # 记录副露
        self.melds[position].append({
            'type': 'pong',
            'tiles': [matching[0], matching[1], discarded],
            'from': discarder_pos
        })
        
        # 清除最后打出的牌和等待状态
        self.last_discard = None
        self.last_discarder = None
        self.waiting_for_action = False
        self.action_players = []
        
        # 副露发生，所有玩家第一巡结束（影响天和/地和/双立直）
        for i in range(4):
            self.first_turn[i] = False
        
        # 轮到碰的人出牌
        self.current_turn = position
        
        # 手牌排序
        hand.sort(key=self._tile_sort_key)
        
        return True
    
    def do_kong(self, position, tile):
        """执行明杠操作
        
        Args:
            position: 杠牌的玩家位置
            tile: 要杠的牌
            
        Returns:
            (success, need_draw): 是否成功, 是否需要补牌
        """
        from .game_data import normalize_tile
        
        hand = self.hands[position]
        norm_tile = normalize_tile(tile)
        
        # 检查手里有3张（考虑赤牌）
        matching = [t for t in hand if normalize_tile(t) == norm_tile]
        if len(matching) < 3:
            return False, False
        
        # 获取打牌人的位置
        discarder_pos = self.last_discarder if self.last_discarder is not None else (position - 1) % 4
        
        # 检查包牌条件
        self._check_pao_before_meld(position, norm_tile, discarder_pos)
        
        # 从手里移除3张
        for t in matching[:3]:
            hand.remove(t)
        
        # 从打牌人的弃牌堆移除最后一张
        if self.discards[discarder_pos] and normalize_tile(self.discards[discarder_pos][-1]) == norm_tile:
            discarded = self.discards[discarder_pos].pop()
        else:
            discarded = tile
        
        # 记录副露
        self.melds[position].append({
            'type': 'kong',
            'tiles': [matching[0], matching[1], matching[2], discarded],
            'from': discarder_pos
        })
        
        # 翻杠宝牌
        self._reveal_kan_dora()
        
        # 清除最后打出的牌和等待状态
        self.last_discard = None
        self.last_discarder = None
        self.waiting_for_action = False
        self.action_players = []
        
        # 副露发生，所有玩家第一巡结束
        for i in range(4):
            self.first_turn[i] = False
        
        # 一发失效
        for i in range(4):
            self.ippatsu[i] = False
        
        self.kan_count += 1
        
        # 轮到杠的人（杠完需要补牌然后出牌）
        self.current_turn = position
        
        # 手牌排序
        hand.sort(key=self._tile_sort_key)
        
        return True, True  # 需要从岭上摸牌
    
    def do_concealed_kong(self, position, tile):
        """执行暗杠操作
        
        Args:
            position: 杠牌的玩家位置
            tile: 要暗杠的牌（标准化后的牌名）
            
        Returns:
            (success, need_draw): 是否成功，是否需要补牌
        """
        from .game_data import normalize_tile
        
        hand = self.hands[position]
        
        # 找出4张相同的牌（考虑赤牌）
        actual_tiles = [t for t in hand if normalize_tile(t) == tile]
        if len(actual_tiles) < 4:
            return False, False
        
        # 从手牌移除4张
        for t in actual_tiles[:4]:
            hand.remove(t)
        
        # 记录副露（暗杠）
        self.melds[position].append({
            'type': 'concealed_kong',
            'tiles': actual_tiles[:4],
            'concealed': True
        })
        
        # 翻杠宝牌
        self._reveal_kan_dora()
        
        # 手牌排序
        hand.sort(key=self._tile_sort_key)
        
        # 一发失效
        for i in range(4):
            self.ippatsu[i] = False
        
        self.kan_count += 1
        
        # 暗杠后仍然是自己的回合
        self.current_turn = position
        
        return True, True  # 需要从岭上摸牌
    
    def do_added_kong(self, position, tile):
        """执行加杠操作
        
        Args:
            position: 加杠的玩家位置
            tile: 要加杠的牌（标准化后的牌名）
            
        Returns:
            (success, can_chankan, need_draw): 是否成功，是否可被抢杠，是否需要补牌
        """
        from .game_data import normalize_tile
        
        hand = self.hands[position]
        
        # 找到手牌中的这张牌
        actual_tile = None
        for t in hand:
            if normalize_tile(t) == tile:
                actual_tile = t
                break
        
        if not actual_tile:
            return False, False, False
        
        # 找到对应的碰
        pong_meld = None
        for meld in self.melds[position]:
            if meld['type'] == 'pong' and normalize_tile(meld['tiles'][0]) == tile:
                pong_meld = meld
                break
        
        if not pong_meld:
            return False, False, False
        
        # 从手牌移除
        hand.remove(actual_tile)
        
        # 更新副露：碰变成杠
        pong_meld['type'] = 'kong'
        pong_meld['tiles'].append(actual_tile)
        
        # 设置抢杠牌（其他玩家可能抢杠胡）
        self.chankan_tile = tile
        
        # 检查是否有人可以抢杠
        can_chankan = False
        for i in range(4):
            if i != position:
                if self.can_win(self.hands[i], tile):
                    can_chankan = True
                    break
        
        # 翻杠宝牌
        self._reveal_kan_dora()
        
        # 手牌排序
        hand.sort(key=self._tile_sort_key)
        
        # 一发失效
        for i in range(4):
            self.ippatsu[i] = False
        
        self.kan_count += 1
        
        # 加杠后仍然是自己的回合
        self.current_turn = position
        
        return True, can_chankan, True  # 需要从岭上摸牌
    
    def do_chow(self, position, tile, chow_tiles):
        """执行吃操作
        
        Args:
            position: 吃牌的玩家位置
            tile: 被吃的牌
            chow_tiles: 组成的顺子 [tile1, tile2, tile3]
            
        Returns:
            bool: 是否成功
        """
        from .game_data import normalize_tile, get_tile_suit, get_tile_number, get_tile_by_suit_number
        
        hand = self.hands[position]
        
        # 获取打牌人的位置（吃牌一定是上家打的）
        discarder_pos = self.last_discarder if self.last_discarder is not None else (position - 1) % 4
        
        # 从手牌移除吃牌需要的2张牌
        other_tiles = [t for t in chow_tiles if t != tile]
        for t in other_tiles:
            if t not in hand:
                return False
            hand.remove(t)
        
        # 从上家弃牌堆移除
        if self.discards[discarder_pos] and self.discards[discarder_pos][-1] == tile:
            self.discards[discarder_pos].pop()
        
        # 记录副露
        self.melds[position].append({
            'type': 'chow',
            'tiles': chow_tiles,
            'from': discarder_pos
        })
        
        # 计算吃换禁止的牌
        # 1. 不能打出吃进的牌本身
        # 2. 不能打出与顺子两端相邻的牌（如吃456后不能打3或7）
        self.kuikae_forbidden[position] = []
        self.just_chowed[position] = True
        
        # 吃进的牌本身不能打
        self.kuikae_forbidden[position].append(normalize_tile(tile))
        
        # 计算顺子的范围，找出两端相邻的牌
        norm_tiles = sorted([get_tile_number(normalize_tile(t)) for t in chow_tiles])
        suit = get_tile_suit(normalize_tile(chow_tiles[0]))
        min_num = norm_tiles[0]
        max_num = norm_tiles[2]
        
        # 如果吃的是边张，另一端相邻的牌也禁止
        chowed_num = get_tile_number(normalize_tile(tile))
        if chowed_num == min_num and max_num < 9:
            # 吃的是最小的那张，另一端+1禁止打
            forbidden_tile = get_tile_by_suit_number(suit, max_num + 1)
            if forbidden_tile:
                self.kuikae_forbidden[position].append(normalize_tile(forbidden_tile))
        elif chowed_num == max_num and min_num > 1:
            # 吃的是最大的那张，另一端-1禁止打
            forbidden_tile = get_tile_by_suit_number(suit, min_num - 1)
            if forbidden_tile:
                self.kuikae_forbidden[position].append(normalize_tile(forbidden_tile))
        
        # 清除最后打出的牌和等待状态
        self.last_discard = None
        self.last_discarder = None
        self.waiting_for_action = False
        self.action_players = []
        
        # 副露发生，所有玩家第一巡结束
        for i in range(4):
            self.first_turn[i] = False
        
        # 一发失效
        for i in range(4):
            self.ippatsu[i] = False
        
        # 轮到吃的人出牌
        self.current_turn = position
        
        # 手牌排序
        hand.sort(key=self._tile_sort_key)
        
        return True
    
    def _check_pao_before_meld(self, position, norm_tile, feeder_pos):
        """检查碰/杠前是否形成包牌条件
        
        Args:
            position: 鸣牌者位置
            norm_tile: 被鸣的牌（规范化形式）
            feeder_pos: 供牌者位置
        """
        dragons = {'中', '发', '白'}
        winds = {'东', '南', '西', '北'}
        
        # 统计当前已有的三元牌/风牌副露数量
        current_dragons = 0
        current_winds = 0
        
        for meld in self.melds[position]:
            if meld['type'] in ['pong', 'kong', 'concealed_kong', 'added_kong']:
                meld_tile = meld['tiles'][0]
                from .game_data import normalize_tile
                meld_norm = normalize_tile(meld_tile)
                if meld_norm in dragons:
                    current_dragons += 1
                elif meld_norm in winds:
                    current_winds += 1
        
        # 检查大三元包牌：已有2副三元牌，现在碰/杠第3副
        if norm_tile in dragons and current_dragons == 2:
            self.pao_responsibility[position] = {
                'type': 'daisangen',
                'feeder': feeder_pos
            }
        
        # 检查大四喜包牌：已有3副风牌，现在碰/杠第4副
        if norm_tile in winds and current_winds == 3:
            self.pao_responsibility[position] = {
                'type': 'daisuushi',
                'feeder': feeder_pos
            }
    
    def _reveal_kan_dora(self):
        """翻开杠宝牌"""
        # 每次杠翻开一张新的宝牌指示牌
        # 宝牌指示牌位置: dead_wall[4], [6], [8], [10]
        dora_positions = [4, 6, 8, 10]
        ura_positions = [5, 7, 9, 11]
        
        idx = len(self.dora_indicators)  # 当前是第几个宝牌
        if idx < 4 and idx < len(dora_positions):
            pos = dora_positions[idx]
            if pos < len(self.dead_wall):
                self.dora_indicators.append(self.dead_wall[pos])
            ura_pos = ura_positions[idx]
            if ura_pos < len(self.dead_wall):
                self.ura_dora_indicators.append(self.dead_wall[ura_pos])
    
    def discard_tile(self, position, tile, force=False):
        """打牌 - 打完后剩余手牌排序
        
        Args:
            position: 玩家位置
            tile: 要打出的牌
            force: 是否强制打出（忽略吃换禁止检查）
            
        Returns:
            bool 或 tuple: 成功返回True，吃换禁止时返回(False, 'kuikae')
        """
        from .game_data import normalize_tile
        
        if tile not in self.hands[position]:
            return False
        
        # 检查吃换禁止
        if self.just_chowed[position] and not force:
            norm_tile = normalize_tile(tile)
            if norm_tile in self.kuikae_forbidden[position]:
                return (False, 'kuikae')  # 返回吃换禁止标记
        
        self.hands[position].remove(tile)
        # 打完牌后排序剩余手牌
        self.hands[position].sort(key=self._tile_sort_key)
        self.discards[position].append(tile)
        self.last_discard = tile
        self.last_discarder = position  # 记录打牌人
        self.current_turn = (position + 1) % 4
        self.just_drew = False
        
        # 永久振听检查：打出的牌是自己听的牌 → 永久振听
        if not self.furiten[position]:
            tenpai_tiles = self.get_tenpai_tiles(position)
            if normalize_tile(tile) in [normalize_tile(t) for t in tenpai_tiles]:
                self.furiten[position] = True
        
        # 清除吃换禁止状态（打出任何牌后都清除）
        self.just_chowed[position] = False
        self.kuikae_forbidden[position] = []
        
        # 第一巡结束检查：打牌的玩家第一巡结束
        self.first_turn[position] = False
        
        # 打牌后一发失效
        self.ippatsu[position] = False
        # 其他人的一发也失效（有人鸣牌时）
        self.last_action = 'discard'
        
        # 检查是否有人可以吃碰杠胡
        self.action_players = []
        for i in range(4):
            if i != position:  # 不检查自己
                actions = self.check_actions(i, tile)
                if actions:
                    self.action_players.append(i)
        
        # 如果有人可以操作，设置等待状态
        if self.action_players:
            self.waiting_for_action = True
        else:
            self.waiting_for_action = False
        
        return True
    
    def get_kuikae_forbidden(self, position):
        """获取吃换禁止的牌列表（用于UI显示灰色）
        
        Returns:
            list: 被禁止打出的牌的规范化形式列表
        """
        if not self.just_chowed[position]:
            return []
        return self.kuikae_forbidden[position].copy()
    
    def declare_ron(self, position):
        """声明荣和
        
        Args:
            position: 声明荣和的玩家位置
            
        Returns:
            str: 'waiting' 等待其他玩家, 'triple_ron' 三家和了流局, 'process' 可以处理荣和
        """
        if position not in self.action_players:
            return None
        
        tile = self.last_discard
        self.pending_rons[position] = tile
        self.ron_responses[position] = True
        
        # 检查是否所有可以荣和的玩家都响应了
        can_ron_players = []
        for p in self.action_players:
            actions = self.check_actions(p, tile)
            if 'win' in actions:
                can_ron_players.append(p)
        
        # 检查是否所有可荣和玩家都响应
        all_responded = True
        for p in can_ron_players:
            if p not in self.ron_responses:
                all_responded = False
                break
        
        if not all_responded:
            return 'waiting'
        
        # 统计荣和人数
        ron_count = sum(1 for p, resp in self.ron_responses.items() if resp and p in can_ron_players)
        
        if ron_count >= 3:
            # 三家和了流局
            return 'triple_ron'
        
        return 'process'
    
    def pass_ron(self, position):
        """放弃荣和
        
        Args:
            position: 放弃荣和的玩家位置
        """
        if position in self.action_players:
            self.ron_responses[position] = False
    
    def get_ron_winners(self):
        """获取所有声明荣和的玩家（按照顺序：从放铳者开始逆时针）
        
        Returns:
            list: [(position, tile), ...]
        """
        if not self.pending_rons:
            return []
        
        # 按照从放铳者开始逆时针的顺序排列
        discarder = self.last_discarder
        winners = []
        for i in range(1, 4):
            pos = (discarder + i) % 4
            if pos in self.pending_rons:
                winners.append((pos, self.pending_rons[pos]))
        
        return winners
    
    def clear_ron_state(self):
        """清除荣和相关状态"""
        self.pending_rons = {}
        self.ron_responses = {}
    
    def player_pass(self, position):
        """玩家选择过（跳过吃碰杠胡）"""
        if position in self.action_players:
            self.action_players.remove(position)
            
            # 如果过掉了胡牌，设置同巡振听
            if self.last_discard and self.can_win(self.hands[position], self.last_discard):
                self.temp_furiten[position] = True
                # 立直中过掉荣和 → 永久振听（直到局结束）
                if self.riichi[position]:
                    self.furiten[position] = True
        
        # 如果所有人都pass了，清除等待状态
        if not self.action_players:
            self.waiting_for_action = False
    
    def clear_action_state(self):
        """清除吃碰杠等待状态"""
        self.waiting_for_action = False
        self.action_players = []
        self.last_discard = None
        self.last_discarder = None
