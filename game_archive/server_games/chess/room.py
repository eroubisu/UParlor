"""
国际象棋 - 房间类
管理棋局状态、双方玩家、计时器
"""

import random
import time
import chess

from .bot_ai import get_best_move


class ChessRoom:
    """国际象棋房间"""

    POSITIONS = ['白方', '黑方']

    # 时间控制（类似麻将的游戏模式）
    TIME_CONTROLS = {
        'blitz':     {'name': '闪电战', 'base': 180,  'increment': 2,  'desc': '3分+2秒'},
        'rapid':     {'name': '快棋',   'base': 600,  'increment': 5,  'desc': '10分+5秒'},
        'classical': {'name': '慢棋',   'base': 1800, 'increment': 10, 'desc': '30分+10秒'},
    }

    # 段位场类型（与麻将共享段位系统）
    MATCH_TYPES = {
        'yuujin': {'name': '友人場', 'name_cn': '友人场', 'ranked': False, 'min_rank': None},
        'dou':    {'name': '銅の間', 'name_cn': '铜之间', 'ranked': True, 'min_rank': 'novice_1'},
        'gin':    {'name': '銀の間', 'name_cn': '银之间', 'ranked': True, 'min_rank': 'adept_1'},
        'kin':    {'name': '金の間', 'name_cn': '金之间', 'ranked': True, 'min_rank': 'expert_1'},
        'gyoku':  {'name': '玉の間', 'name_cn': '玉之间', 'ranked': True, 'min_rank': 'master_1'},
        'ouza':   {'name': '王座の間', 'name_cn': '王座之间', 'ranked': True, 'min_rank': 'saint_1'},
    }

    # Bot AI 难度（根据段位场调整）
    MATCH_AI_DEPTH = {
        'yuujin': 3,
        'dou': 3,
        'gin': 3,
        'kin': 4,
        'gyoku': 4,
        'ouza': 4,
    }

    def __init__(self, room_id, host_name, time_control='rapid', match_type='yuujin'):
        self.room_id = room_id
        self.host = host_name
        self.players = {0: host_name, 1: None}  # 0=白方, 1=黑方
        self.player_avatars = {0: None, 1: None}
        self.player_ranks = {0: None, 1: None}
        self.state = 'waiting'  # waiting, playing, finished

        self.time_control = time_control
        self.match_type = match_type

        # 棋盘
        self.board = chess.Board()

        # 计时器
        tc = self.TIME_CONTROLS.get(time_control, self.TIME_CONTROLS['rapid'])
        self.time_remaining = {0: tc['base'], 1: tc['base']}  # 秒
        self.increment = tc['increment']
        self.last_move_time = None  # 上次走棋的时间戳

        # 走棋历史（SAN 格式）
        self.move_history = []  # [(move_san, move_uci), ...]

        # 求和
        self.draw_offer_from = None  # 提出和棋的一方 (0 or 1)

        # 机器人
        self.bots = set()

    # ==================== 玩家管理 ====================

    def add_player(self, name, avatar=None):
        """加入玩家，返回位置 (0 或 1)，失败返回 -1"""
        for i in range(2):
            if self.players[i] is None:
                self.players[i] = name
                self.player_avatars[i] = avatar
                return i
        return -1

    def remove_player(self, name):
        """移除玩家"""
        for i in range(2):
            if self.players[i] == name:
                self.players[i] = None
                self.player_avatars[i] = None
                self.player_ranks[i] = None
                return i
        return -1

    def set_player_avatar(self, name, avatar):
        for i in range(2):
            if self.players[i] == name:
                self.player_avatars[i] = avatar
                return True
        return False

    def set_player_rank(self, name, rank_id):
        for i in range(2):
            if self.players[i] == name:
                self.player_ranks[i] = rank_id
                return True
        return False

    def get_position(self, name):
        for i in range(2):
            if self.players[i] == name:
                return i
        return -1

    def get_player_count(self):
        return sum(1 for p in self.players.values() if p is not None)

    def is_full(self):
        return self.get_player_count() >= 2

    def is_bot(self, player_name):
        return player_name in self.bots

    def add_bot(self):
        """添加机器人（仅友人场可用）"""
        if self.is_full():
            return False, "房间已满"
        if self.state != 'waiting':
            return False, "游戏已开始"

        used_names = set(self.players.values()) | self.bots
        bot_name = None
        for i in range(1, 10):
            name = f"bot{i}"
            if name not in used_names:
                bot_name = name
                break
        if not bot_name:
            bot_name = f"bot{int(time.time()) % 1000}"

        bot_avatar = self._generate_bot_avatar()
        pos = self.add_player(bot_name, avatar=bot_avatar)
        if pos >= 0:
            self.bots.add(bot_name)
            return True, bot_name
        return False, "加入失败"

    def _generate_bot_avatar(self):
        import json
        AVATAR_SIZE = 16
        PALETTE = [
            '#000000', '#FFFFFF', '#FF0000', '#00FF00', '#0000FF',
            '#FFFF00', '#FF00FF', '#00FFFF', '#FFA500', '#800080',
            '#008000', '#000080', '#808080', '#C0C0C0', '#800000'
        ]
        pixels = [[None for _ in range(AVATAR_SIZE)] for _ in range(AVATAR_SIZE)]
        colors = random.sample(PALETTE[:10], 3)
        bg_color = random.choice(['#FFFFFF', '#F0F0F0', '#E0E0E0', '#D0D0D0'])
        for y in range(AVATAR_SIZE):
            for x in range(AVATAR_SIZE):
                pixels[y][x] = bg_color
        half = AVATAR_SIZE // 2
        for y in range(2, AVATAR_SIZE - 2):
            for x in range(2, half + 1):
                if random.random() < 0.4:
                    color = random.choice(colors)
                    pixels[y][x] = color
                    pixels[y][AVATAR_SIZE - 1 - x] = color
        return json.dumps(pixels)

    # ==================== 游戏流程 ====================

    def start_game(self):
        """开始对局"""
        if not self.is_full():
            return False

        # 随机分配黑白方（有bot时不打乱，房主始终白方）
        if not self.bots:
            players_list = [(self.players[i], self.player_avatars[i], self.player_ranks[i]) for i in range(2)]
            random.shuffle(players_list)
            for i in range(2):
                self.players[i] = players_list[i][0]
                self.player_avatars[i] = players_list[i][1]
                self.player_ranks[i] = players_list[i][2]

        self.board = chess.Board()
        self.move_history = []
        self.draw_offer_from = None

        tc = self.TIME_CONTROLS.get(self.time_control, self.TIME_CONTROLS['rapid'])
        self.time_remaining = {0: tc['base'], 1: tc['base']}
        self.increment = tc['increment']
        self.last_move_time = time.time()

        self.state = 'playing'
        return True

    def current_side(self):
        """当前该走棋的一方 (0=白, 1=黑)"""
        return 0 if self.board.turn == chess.WHITE else 1

    def get_current_player_name(self):
        side = self.current_side()
        return self.players[side]

    def make_move(self, player_name, san_or_uci):
        """走棋，返回 (success, san_str, result_info)"""
        pos = self.get_position(player_name)
        if pos < 0:
            return False, None, "你不在这个房间中"
        if self.state != 'playing':
            return False, None, "当前不在对局中"
        if pos != self.current_side():
            return False, None, "还没轮到你走棋"

        # 先验证走法，无效走法不扣时间
        move = self._parse_move(san_or_uci)
        if move is None:
            return False, None, f"无效走法: {san_or_uci}\n输入 /moves 查看合法走法"

        # 走法有效，更新计时
        self._update_clock()

        # 记录 SAN（在 push 之前获取）
        san = self.board.san(move)
        self.board.push(move)

        # 走完后加时间
        self.time_remaining[pos] += self.increment
        self.last_move_time = time.time()

        self.move_history.append((san, move.uci()))
        self.draw_offer_from = None  # 走棋后自动撤销和棋提议

        # 检查局面结果
        result = self._check_game_over()
        return True, san, result

    def make_bot_move(self):
        """机器人走棋，返回 (san, result_info)"""
        side = self.current_side()
        player_name = self.players[side]
        if player_name not in self.bots:
            return None, None

        depth = self.MATCH_AI_DEPTH.get(self.match_type, 2)
        move = get_best_move(self.board, depth)
        if move is None:
            return None, None

        # Bot 走法有效，更新计时
        self._update_clock()

        san = self.board.san(move)
        self.board.push(move)
        self.time_remaining[side] += self.increment
        self.last_move_time = time.time()
        self.move_history.append((san, move.uci()))
        self.draw_offer_from = None

        result = self._check_game_over()
        return san, result

    def resign(self, player_name):
        """认输，返回 (result, error)"""
        pos = self.get_position(player_name)
        if pos < 0:
            return None, "你不在这个房间中"
        if self.state != 'playing':
            return None, "当前不在对局中"
        self.state = 'finished'
        winner = 1 - pos
        return {
            'type': 'resign',
            'winner': winner,
            'winner_name': self.players[winner],
            'loser_name': player_name,
        }, None

    def offer_draw(self, player_name):
        """提出和棋"""
        pos = self.get_position(player_name)
        if pos < 0 or self.state != 'playing':
            return None, "当前不在对局中"
        if self.draw_offer_from is not None:
            return None, "已经有和棋提议了"
        opponent = 1 - pos
        if self.is_bot(self.players[opponent]):
            # 机器人拒绝和棋（简化处理）
            return None, "对手拒绝了和棋提议"
        self.draw_offer_from = pos
        return pos, None

    def accept_draw(self, player_name):
        """接受和棋"""
        pos = self.get_position(player_name)
        if pos < 0 or self.state != 'playing':
            return None
        if self.draw_offer_from is None or self.draw_offer_from == pos:
            return None
        self.state = 'finished'
        return {'type': 'draw', 'reason': 'agreement'}

    def decline_draw(self, player_name):
        """拒绝和棋"""
        pos = self.get_position(player_name)
        if pos < 0:
            return False
        if self.draw_offer_from is not None and self.draw_offer_from != pos:
            self.draw_offer_from = None
            return True
        return False

    # ==================== 计时器 ====================

    def _update_clock(self):
        """更新当前走棋方的剩余时间"""
        if self.last_move_time is None:
            return
        now = time.time()
        elapsed = now - self.last_move_time
        side = self.current_side()
        self.time_remaining[side] -= elapsed
        self.last_move_time = now

    def check_timeout(self):
        """检查是否超时，返回结果或 None"""
        if self.state != 'playing' or self.last_move_time is None:
            return None
        self._update_clock()
        for side in (0, 1):
            if self.time_remaining[side] <= 0:
                self.time_remaining[side] = 0
                self.state = 'finished'
                winner = 1 - side
                return {
                    'type': 'timeout',
                    'winner': winner,
                    'winner_name': self.players[winner],
                    'loser_name': self.players[side],
                }
        return None

    def get_time_display(self):
        """获取双方剩余时间的显示字符串"""
        def fmt(seconds):
            s = max(0, int(seconds))
            m, sec = divmod(s, 60)
            return f"{m}:{sec:02d}"
        return {0: fmt(self.time_remaining[0]), 1: fmt(self.time_remaining[1])}

    # ==================== 棋盘渲染 ====================

    def render_board(self, perspective_white=True):
        """渲染棋盘为文字，带坐标标注"""
        PIECE_SYMBOLS = {
            'R': '♜', 'N': '♞', 'B': '♝', 'Q': '♛', 'K': '♚', 'P': '♟',
            'r': '♖', 'n': '♘', 'b': '♗', 'q': '♕', 'k': '♔', 'p': '♙',
        }

        lines = []
        ranks = range(7, -1, -1) if perspective_white else range(8)
        files = range(8) if perspective_white else range(7, -1, -1)

        lines.append('  ┌───┬───┬───┬───┬───┬───┬───┬───┐')
        for i, rank in enumerate(ranks):
            row = f'{rank + 1} │'
            for f in files:
                sq = chess.square(f, rank)
                piece = self.board.piece_at(sq)
                if piece:
                    sym = PIECE_SYMBOLS.get(piece.symbol(), piece.symbol())
                else:
                    sym = '·' if (rank + f) % 2 == 0 else ' '
                row += f' {sym} │'
            lines.append(row)
            if i < 7:
                lines.append('  ├───┼───┼───┼───┼───┼───┼───┼───┤')
        lines.append('  └───┴───┴───┴───┴───┴───┴───┴───┘')

        if perspective_white:
            lines.append('    a   b   c   d   e   f   g   h')
        else:
            lines.append('    h   g   f   e   d   c   b   a')
        return '\n'.join(lines)

    def format_move_history(self, last_n=10):
        """格式化走棋记录（SAN格式，最近N步）"""
        if not self.move_history:
            return '(无)'
        recent = self.move_history[-last_n:]
        start_idx = len(self.move_history) - len(recent)
        parts = []
        for i, (san, _uci) in enumerate(recent):
            ply = start_idx + i
            if ply % 2 == 0:
                parts.append(f'{ply // 2 + 1}.')
            parts.append(san)
        return ' '.join(parts)

    def get_legal_moves_san(self):
        """获取所有合法走法的SAN表示"""
        return [self.board.san(m) for m in self.board.legal_moves]

    # ==================== 房间数据 ====================

    def get_table_data(self):
        """获取房间数据（用于UI渲染）"""
        tc_info = self.TIME_CONTROLS.get(self.time_control, self.TIME_CONTROLS['rapid'])
        match_info = self.MATCH_TYPES.get(self.match_type, self.MATCH_TYPES['yuujin'])
        time_display = self.get_time_display()

        # 构建棋盘格子数据 (8x8)，每格: piece symbol or None
        board_squares = []
        for rank in range(7, -1, -1):  # 8->1
            row = []
            for file in range(8):      # a->h
                sq = chess.square(file, rank)
                piece = self.board.piece_at(sq)
                row.append(piece.symbol() if piece else None)
            board_squares.append(row)

        # 最后一步走棋的起止格（用于高亮）
        last_move_squares = None
        if self.move_history:
            uci = self.move_history[-1][1]
            if len(uci) >= 4:
                last_move_squares = [uci[:2], uci[2:4]]

        return {
            'game_type': 'chess',
            'room_id': self.room_id,
            'host': self.host,
            'state': self.state,
            'players': self.players,
            'player_avatars': self.player_avatars,
            'player_ranks': self.player_ranks,
            'player_count': self.get_player_count(),
            'is_full': self.is_full(),
            'time_control': self.time_control,
            'time_control_name': tc_info['name'],
            'time_control_desc': tc_info['desc'],
            'match_type': self.match_type,
            'match_type_name': match_info['name_cn'],
            'is_ranked': match_info.get('ranked', False),
            'current_turn': self.current_side() if self.state == 'playing' else None,
            'time_remaining': {0: self.time_remaining[0], 1: self.time_remaining[1]},
            'time_display': time_display,
            'move_count': len(self.move_history),
            'last_move': self.move_history[-1][0] if self.move_history else None,
            'last_move_squares': last_move_squares,
            'draw_offer_from': self.draw_offer_from,
            'board': board_squares,
            'bots': list(self.bots),
            'move_history': [(san, uci) for san, uci in self.move_history[-20:]],
        }

    def get_status(self):
        """获取房间简要状态（用于房间列表）"""
        tc_info = self.TIME_CONTROLS.get(self.time_control, self.TIME_CONTROLS['rapid'])
        match_info = self.MATCH_TYPES.get(self.match_type, self.MATCH_TYPES['yuujin'])
        return {
            'room_id': self.room_id,
            'host': self.host,
            'players': self.players,
            'state': self.state,
            'player_count': self.get_player_count(),
            'time_control': self.time_control,
            'time_control_name': tc_info['name'],
            'match_type': self.match_type,
            'match_type_name': match_info['name_cn'],
            'is_ranked': match_info.get('ranked', False),
            'player_ranks': self.player_ranks,
        }

    def is_ranked_match(self):
        match_info = self.MATCH_TYPES.get(self.match_type, {})
        return match_info.get('ranked', False)

    # ==================== 内部方法 ====================

    def _parse_move(self, text):
        """尝试解析 SAN 或 UCI 走法"""
        text = text.strip()
        # 先尝试 SAN
        try:
            return self.board.parse_san(text)
        except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
            pass
        # 再尝试 UCI
        try:
            move = chess.Move.from_uci(text)
            if move in self.board.legal_moves:
                return move
        except (ValueError, chess.InvalidMoveError):
            pass
        return None

    def _check_game_over(self):
        """检查对局是否结束"""
        if self.board.is_checkmate():
            # 被将杀的是当前走棋方（因为已经 push 过了，轮到对方）
            loser = self.current_side()
            winner = 1 - loser
            self.state = 'finished'
            return {
                'type': 'checkmate',
                'winner': winner,
                'winner_name': self.players[winner],
                'loser_name': self.players[loser],
            }
        if self.board.is_stalemate():
            self.state = 'finished'
            return {'type': 'draw', 'reason': 'stalemate'}
        if self.board.is_insufficient_material():
            self.state = 'finished'
            return {'type': 'draw', 'reason': 'insufficient_material'}
        if self.board.is_fifty_moves():
            self.state = 'finished'
            return {'type': 'draw', 'reason': 'fifty_moves'}
        if self.board.is_repetition(3):
            self.state = 'finished'
            return {'type': 'draw', 'reason': 'repetition'}
        # 将军提示
        if self.board.is_check():
            return {'type': 'check'}
        return None
