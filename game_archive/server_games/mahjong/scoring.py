"""
麻将游戏 - 结算计分模块
"""


class ScoringMixin:
    """结算计分相关方法的Mixin类"""
    
    def process_win(self, winner_pos, win_tile, is_tsumo, loser_pos=None):
        """处理胡牌结算
        
        Args:
            winner_pos: 胡牌玩家位置
            win_tile: 和牌的牌
            is_tsumo: 是否自摸
            loser_pos: 放铳玩家位置（荣和时）
            
        Returns:
            dict: 胡牌结果信息
        """
        from .yaku import analyze_hand, calculate_score
        
        hand = self.hands[winner_pos].copy()
        if not is_tsumo and win_tile not in hand:
            hand.append(win_tile)
        
        # 分析役种（宝牌通过指示牌传入，库自动计算）
        player_wind = self.get_player_wind(winner_pos)
        ura_indicators = self.ura_dora_indicators if self.riichi[winner_pos] else None
        
        yaku_result = analyze_hand(
            hand_tiles=hand,
            melds=self.melds[winner_pos],
            win_tile=win_tile,
            is_tsumo=is_tsumo,
            is_riichi=self.riichi[winner_pos],
            is_ippatsu=self.ippatsu[winner_pos],
            is_rinshan=self.rinshan,
            is_chankan=self.chankan_tile is not None,
            is_haitei=is_tsumo and self.is_haitei(),
            is_houtei=not is_tsumo and self.is_haitei(),
            is_tenhou=is_tsumo and self.first_turn[winner_pos] and winner_pos == self.dealer,
            is_chihou=is_tsumo and self.first_turn[winner_pos] and winner_pos != self.dealer,
            is_double_riichi=self.double_riichi[winner_pos],
            player_wind=player_wind,
            round_wind=self.round_wind,
            dora_indicators=self.dora_indicators,
            ura_dora_indicators=ura_indicators,
        )
        
        # 检查是否有役
        if not yaku_result.yakus:
            return {'success': False, 'error': '无役'}
        
        # 番数和符数（已由库计算）
        if yaku_result.is_yakuman:
            han = 13
            fu = 0
        else:
            han = yaku_result.total_han
            fu = yaku_result.fu
        
        # 计算点数
        is_dealer = winner_pos == self.dealer
        score_info = calculate_score(han, fu, is_dealer, is_tsumo)
        
        # 点数转移
        if is_tsumo:
            # 自摸 - 检查包牌
            pao = self.pao_responsibility[winner_pos]
            if pao and pao['type'] in ['daisangen', 'daisuushi']:
                # 大三元/大四喜包牌：自摸时包牌者全额支付
                self.scores[pao['feeder']] -= score_info['total']
            else:
                # 正常自摸
                for i in range(4):
                    if i != winner_pos:
                        if i == self.dealer:
                            self.scores[i] -= score_info.get('from_dealer', score_info.get('from_non_dealer', 0))
                        else:
                            self.scores[i] -= score_info.get('from_non_dealer', 0)
            self.scores[winner_pos] += score_info['total']
        else:
            # 荣和
            if loser_pos is not None:
                # 检查包牌
                pao = self.pao_responsibility[winner_pos]
                if pao and pao['type'] in ['daisangen', 'daisuushi']:
                    # 大三元/大四喜包牌：荣和时包牌者与放铳者各付一半
                    half_score = score_info['total'] // 2
                    self.scores[loser_pos] -= half_score
                    self.scores[pao['feeder']] -= (score_info['total'] - half_score)  # 避免奇数问题
                else:
                    self.scores[loser_pos] -= score_info['total']
            self.scores[winner_pos] += score_info['total']
        
        # 收取立直棒
        self.scores[winner_pos] += self.riichi_sticks * 1000
        self.riichi_sticks = 0
        
        # 本场
        self.scores[winner_pos] += self.honba * 300
        
        # 设置连庄状态（庄家胡牌则连庄）
        if winner_pos == self.dealer:
            self._renchan = True
            self.honba += 1  # 连庄本场+1
        else:
            self._renchan = False
            self.honba = 0  # 轮庄本场归零
        
        # 从役列表中提取宝牌数（用于显示）
        dora_count = sum(h for name, h, _ in yaku_result.yakus if name == '宝牌')
        ura_dora_count = sum(h for name, h, _ in yaku_result.yakus if name == '里宝牌')
        red_dora_count = sum(h for name, h, _ in yaku_result.yakus if name == '赤宝牌')
        
        result = {
            'success': True,
            'winner': self.players[winner_pos],
            'winner_pos': winner_pos,
            'win_tile': win_tile,
            'is_tsumo': is_tsumo,
            'hand': hand,
            'melds': self.melds[winner_pos],
            'yakus': yaku_result.yakus,
            'han': han,
            'fu': fu,
            'score': score_info['total'],
            'is_yakuman': yaku_result.is_yakuman,
            'dora_count': dora_count,
            'ura_dora_count': ura_dora_count,
            'red_dora_count': red_dora_count
        }
        
        return result
    
    def process_ryuukyoku(self, ryuukyoku_type='exhaustive'):
        """处理流局结算
        
        Args:
            ryuukyoku_type: 流局类型
                - 'exhaustive': 荒牌流局（牌山摸完）
                - 'kyuushu': 九种九牌
                - 'suufon': 四风连打
                - 'suucha': 四家立直
                - 'suukaikan': 四杠散了
                - 'sanchahou': 三家和
        
        Returns:
            dict: 流局结果，包含听牌情况和点数变化
        """
        result = {
            'type': ryuukyoku_type,
            'tenpai': [],  # 听牌的玩家
            'noten': [],   # 未听牌的玩家
            'score_changes': [0, 0, 0, 0],  # 点数变化
            'hands': {},   # 各玩家手牌（用于展示）
            'waiting_tiles': {}  # 听牌玩家的待牌
        }
        
        # 检查每个玩家是否听牌
        for i in range(4):
            waiting = self.get_tenpai_tiles(i)
            result['hands'][i] = self.hands[i][:]
            # 立直的玩家一定是听牌状态（立直必须听牌才能宣言）
            if waiting or self.riichi[i]:
                result['tenpai'].append(i)
                result['waiting_tiles'][i] = waiting if waiting else []
            else:
                result['noten'].append(i)
        
        # 荒牌流局时计算听牌罚符
        if ryuukyoku_type == 'exhaustive':
            tenpai_count = len(result['tenpai'])
            noten_count = len(result['noten'])
            
            # 按雀魂规则：
            # 1听3不听：听牌者+3000，不听者各-1000
            # 2听2不听：听牌者各+1500，不听者各-1500
            # 3听1不听：听牌者各+1000，不听者-3000
            # 0听或4听：不罚符
            if tenpai_count == 1 and noten_count == 3:
                for i in result['tenpai']:
                    result['score_changes'][i] = 3000
                for i in result['noten']:
                    result['score_changes'][i] = -1000
            elif tenpai_count == 2 and noten_count == 2:
                for i in result['tenpai']:
                    result['score_changes'][i] = 1500
                for i in result['noten']:
                    result['score_changes'][i] = -1500
            elif tenpai_count == 3 and noten_count == 1:
                for i in result['tenpai']:
                    result['score_changes'][i] = 1000
                for i in result['noten']:
                    result['score_changes'][i] = -3000
        
        # 应用点数变化
        for i in range(4):
            self.scores[i] += result['score_changes'][i]
        
        # 流局后的处理：
        # - 如果庄家听牌，连庄（本场+1）
        # - 如果庄家未听牌，轮庄
        dealer_tenpai = self.dealer in result['tenpai']
        result['dealer_tenpai'] = dealer_tenpai
        
        if dealer_tenpai:
            # 庄家听牌，连庄，本场+1
            self.honba += 1
            result['next_dealer'] = self.dealer
            result['renchan'] = True
            self._renchan = True  # 保存连庄状态
        else:
            # 庄家未听牌，轮庄
            self.honba += 1  # 流局也要加本场
            next_dealer = (self.dealer + 1) % 4
            result['next_dealer'] = next_dealer
            result['renchan'] = False
            self._renchan = False  # 保存连庄状态
            
            # 检查是否需要进入下一个场风
            if next_dealer == 0:
                # 回到东家，进入下一个场风
                wind_order = ['东', '南', '西', '北']
                current_idx = wind_order.index(self.round_wind)
                if current_idx < 3:
                    result['next_round_wind'] = wind_order[current_idx + 1]
                    result['next_round_number'] = 0
                else:
                    result['game_over'] = True
            else:
                result['next_round_number'] = self.round_number + 1 if not dealer_tenpai else self.round_number
        
        # 设置游戏状态为已结束，等待下一局
        self.state = 'finished'
        
        # 清理等待状态
        self.waiting_for_action = False
        self.action_players = []
        
        return result
    
    def next_round(self, dealer_won=False, is_draw=False, tenpai_players=None):
        """进入下一局
        
        Args:
            dealer_won: 庄家是否胡牌
            is_draw: 是否流局
            tenpai_players: 流局时听牌的玩家列表
        """
        if is_draw:
            # 流局处理
            if tenpai_players is None:
                tenpai_players = []
            
            # 不听罚符
            tenpai_count = len(tenpai_players)
            if 0 < tenpai_count < 4:
                no_tenpai_penalty = 3000 // (4 - tenpai_count)
                tenpai_bonus = 3000 // tenpai_count
                for i in range(4):
                    if i in tenpai_players:
                        self.scores[i] += tenpai_bonus
                    else:
                        self.scores[i] -= no_tenpai_penalty
            
            # 庄家听牌则连庄
            if self.dealer in tenpai_players:
                self.honba += 1
                return self._start_new_round()
        
        # 正常胡牌
        if dealer_won:
            # 庄家连庄
            self.honba += 1
        else:
            # 轮庄
            self.honba = 0
            self.dealer = (self.dealer + 1) % 4
            
            # 检查是否进入下一场
            if self.dealer == 0:
                self.round_number += 1
                if self.round_number > 3:  # 0-3，超过3表示4局打完
                    # 东风结束 or 南风结束
                    if self.game_type == 'east':
                        return self._end_game()
                    elif self.round_wind == '东':
                        self.round_wind = '南'
                        self.round_number = 0  # 南1局
                    else:
                        return self._end_game()
        
        return self._start_new_round()
    
    def _start_new_round(self):
        """开始新的一局"""
        # 重置牌局状态
        self.deck = []
        self.dead_wall = []
        self.hands = {0: [], 1: [], 2: [], 3: []}
        self.discards = {0: [], 1: [], 2: [], 3: []}
        self.melds = {0: [], 1: [], 2: [], 3: []}
        self.dora_indicators = []
        self.ura_dora_indicators = []
        self.kan_count = 0
        
        for i in range(4):
            self.riichi[i] = False
            self.double_riichi[i] = False
            self.ippatsu[i] = False
            self.furiten[i] = False
            self.temp_furiten[i] = False
            self.first_turn[i] = True
            self.riichi_turn[i] = -1
        
        self.last_discard = None
        self.last_discarder = None
        self.waiting_for_action = False
        self.action_players = []
        self.just_drew = False
        self.rinshan = False
        self.chankan_tile = None
        self.turn_count = 0
        
        return {'status': 'continue', 'round': f'{self.round_wind}{self.round_number + 1}局'}
    
    def _end_game(self):
        """结束游戏，计算最终得分（包括顺位马）"""
        self.state = 'finished'
        
        # 先计算返点（与30000点的差距，单位：千点）
        final_scores = {}
        for i in range(4):
            # 点数 - 30000 原点，转换为千点
            final_scores[i] = (self.scores[i] - 30000) / 1000
        
        # 排名（点数相同时，位置靠前的排名靠前）
        rankings = sorted(range(4), key=lambda i: (-self.scores[i], i))
        
        # 顺位马（雀魂规则）: 1位+15, 2位+5, 3位-5, 4位-15
        uma = {0: 15, 1: 5, 2: -5, 3: -15}
        
        final_pts = {}
        for rank, player_pos in enumerate(rankings):
            final_pts[player_pos] = final_scores[player_pos] + uma[rank]
        
        return {
            'status': 'end',
            'rankings': [(self.players[i], self.scores[i], final_pts[i]) for i in rankings],
            'uma': uma,
            'final_pts': final_pts
        }
    
    def check_game_end(self):
        """检查游戏是否应该结束"""
        # 有人破产（点数<0）
        for i in range(4):
            if self.scores[i] < 0:
                return True
        
        return False
