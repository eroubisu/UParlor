"""
国际象棋 - 指令处理器
继承 BaseRoomCommandHandler 共享基类
"""

from server.base_room_handler import BaseRoomCommandHandler
from .room import ChessRoom
from .game_engine import format_game_result


class ChessCommandHandler(BaseRoomCommandHandler):
    """国际象棋指令处理器"""

    game_key = 'chess'
    game_name = '国际象棋'
    action_prefix = 'chess'
    max_players = 2
    room_location = 'chess_room'
    playing_location = 'chess_playing'

    def _get_match_types(self):
        return ChessRoom.MATCH_TYPES

    def _get_title_checks(self, stats):
        return [
            ('chess_beginner', stats.get('total_games', 0) >= 1),
            ('chess_10wins', stats.get('wins', 0) >= 10),
            ('chess_50wins', stats.get('wins', 0) >= 50),
            ('chess_100wins', stats.get('wins', 0) >= 100),
        ]

    def _get_rank_points_change(self, rank, outcome):
        from server.user_schema import get_chess_rank_points_change
        return get_chess_rank_points_change(rank, outcome)

    def _iter_ranked_players(self, room, result):
        rtype = result.get('type')
        for i in range(2):
            pname = room.players[i]
            if not pname or room.is_bot(pname):
                continue
            if rtype in ('checkmate', 'resign', 'timeout'):
                outcome = 'win' if result.get('winner') == i else 'loss'
            else:
                outcome = 'draw'
            yield pname, outcome

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        """处理国际象棋指令

        Args:
            lobby: LobbyEngine 实例（提供位置、邀请等大厅服务）
            player_name: 玩家名
            player_data: 玩家数据
            cmd: 指令（如 /create）
            args: 参数字符串

        Returns:
            响应消息或 dict，None 表示未匹配
        """
        engine = self.engine
        location = lobby.get_player_location(player_name)

        # 段位场名称快捷方式
        match_shortcuts = {'/yuujin', '/dou', '/gin', '/kin', '/gyoku', '/ouza'}
        if cmd in match_shortcuts:
            return f"你是否想创建房间？请使用 /create {cmd[1:]}"

        # 创建房间
        if cmd == '/create':
            return self._cmd_create(lobby, player_name, player_data, args)

        # 取消操作
        elif cmd == '/cancel':
            return self._cmd_cancel(player_name)

        # 房间列表
        elif cmd == '/rooms':
            return self._cmd_rooms()

        # 查看段位
        elif cmd == '/rank':
            return self._cmd_rank(player_data)

        # 战绩统计
        elif cmd == '/stats':
            return self._cmd_stats(player_data)

        # 加入房间
        elif cmd == '/join':
            return self._cmd_join(lobby, player_name, player_data, args)

        # 邀请玩家
        elif cmd == '/invite':
            return self._cmd_invite(lobby, player_name, player_data, args)

        # 接受邀请
        elif cmd == '/accept':
            if location == 'chess_playing':
                return self._cmd_accept_draw(player_name)
            return self._cmd_accept_invite(lobby, player_name, player_data)

        # 添加机器人
        elif cmd == '/bot':
            return self._cmd_bot(player_name)

        # 踢出玩家
        elif cmd == '/kick':
            return self._cmd_kick(player_name, args)

        # 开始游戏
        elif cmd == '/start':
            return self._cmd_start(lobby, player_name)

        # 走棋
        if cmd in ('/m', '/move'):
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "当前不在对局中。"
            if not args:
                return "用法: /m <走法>\n例: /m e4, /m Nf3, /m O-O\n输入 /moves 查看合法走法。"
            return self._process_move(lobby, player_name, room, args)

        # 显示棋盘
        if cmd in ('/board', '/b'):
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。"
            return {
                'action': 'chess_room_update',
                'message': '棋盘已在右侧面板显示。',
                'room_data': room.get_table_data(),
            }

        # 合法走法
        if cmd == '/moves':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "当前不在对局中。"
            moves = room.get_legal_moves_san()
            if not moves:
                return "没有合法走法。"
            return f"【合法走法】({len(moves)}种)\n" + ', '.join(moves)

        # 走棋历史
        if cmd == '/history':
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。"
            return f"走棋记录:\n{room.format_move_history(20)}"

        # 认输
        if cmd == '/resign':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "当前不在对局中。"

            result, error = room.resign(player_name)
            if result:
                return self._finish_game(lobby, room, result)
            return error or "认输失败。"

        # 提出和棋
        if cmd == '/draw':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "当前不在对局中。"

            pos, error = room.offer_draw(player_name)
            if error:
                return error
            opponent = 1 - pos
            opponent_name = room.players[opponent]
            return {
                'action': 'chess_notify',
                'send_to_caller': [{'type': 'game', 'text': f"已向 {opponent_name} 提出和棋。等待对方回应...\n对方可输入 /accept 或 /decline"}],
                'send_to_players': self._build_game_notify(room, f"{player_name} 提出和棋。输入 /accept 接受，/decline 拒绝。", room.get_table_data(), exclude=player_name),
                'save': True,
            }

        # 拒绝和棋
        if cmd == '/decline':
            room = engine.get_player_room(player_name)
            if not room:
                return "当前不在对局中。"
            if room.decline_draw(player_name):
                return {
                    'action': 'chess_notify',
                    'send_to_caller': [{'type': 'game', 'text': '已拒绝和棋。'}],
                    'send_to_players': self._build_game_notify(room, f"{player_name} 拒绝了和棋。", room.get_table_data(), exclude=player_name),
                    'save': True,
                }
            return "没有待拒绝的和棋提议。"

        # 直接输入走法（不带 /m 前缀）
        if location == 'chess_playing' and not cmd.startswith('/'):
            room = engine.get_player_room(player_name)
            if room and room.state == 'playing':
                pos = room.get_position(player_name)
                if pos == room.current_side():
                    return self._process_move(lobby, player_name, room, cmd + (' ' + args if args else ''))

        return None

    # ==================== 子指令实现 ====================

    def _cmd_create(self, lobby, player_name, player_data, args):
        from server.user_schema import get_rank_name, get_rank_index
        engine = self.engine
        avatar = player_data.get('avatar')
        location = lobby.get_player_location(player_name)

        if location != 'chess':
            return "请先返回国际象棋大厅再创建房间。"

        match_type = None
        time_control = None

        if args:
            parts = args.lower().split()
            for part in parts:
                if part in ['yuujin', 'yuu', 'y', 'friend', 'f']:
                    match_type = 'yuujin'
                elif part in ['dou', 'd', 'bronze', 'copper']:
                    match_type = 'dou'
                elif part in ['gin', 'g', 'silver']:
                    match_type = 'gin'
                elif part in ['kin', 'k', 'gold']:
                    match_type = 'kin'
                elif part in ['gyoku', 'jade']:
                    match_type = 'gyoku'
                elif part in ['ouza', 'o', 'throne']:
                    match_type = 'ouza'
                elif part in ['blitz', 'bl']:
                    time_control = 'blitz'
                elif part in ['rapid', 'ra']:
                    time_control = 'rapid'
                elif part in ['classical', 'cl']:
                    time_control = 'classical'

        if match_type is None or time_control is None:
            engine.pending_confirms[player_name] = ('create_chess_room', {'match_type': match_type, 'time_control': time_control})

            if match_type is None:
                chess_rank = player_data.get('chess', {}).get('rank', 'novice_1')
                chess_rank_idx = get_rank_index(chess_rank)

                text = "请选择段位场  (输入编号，/back 取消)\n\n"
                text += "  /1  友人场      不影响段位\n"

                match_list = [
                    ('铜之间', 'novice_1'),
                    ('银之间', 'adept_1'),
                    ('金之间', 'expert_1'),
                    ('玉之间', 'master_1'),
                    ('王座之间', 'saint_1'),
                ]

                for i, (cn_name, min_rank) in enumerate(match_list, 2):
                    min_rank_idx = get_rank_index(min_rank)
                    can_enter = chess_rank_idx >= min_rank_idx
                    status = "" if can_enter else f"  (需要{get_rank_name(min_rank)})"
                    text += f"  /{i}  {cn_name}{status}\n"

                return text
            else:
                match_info = ChessRoom.MATCH_TYPES.get(match_type, {})
                text = f"✓ 段位场: {match_info.get('name_cn', match_type)}\n\n"
                text += "请选择时间控制  (输入编号，/back 取消)\n\n"
                text += "  /1  闪电战    3分+2秒\n"
                text += "  /2  快棋      10分+5秒\n"
                text += "  /3  慢棋      30分+10秒"
                return text

        # 直接创建（两个参数都已有）
        match_info = ChessRoom.MATCH_TYPES.get(match_type, ChessRoom.MATCH_TYPES['yuujin'])
        if match_info.get('ranked'):
            chess_rank = player_data.get('chess', {}).get('rank', 'novice_1')
            min_rank = match_info.get('min_rank', 'novice_1')
            if get_rank_index(chess_rank) < get_rank_index(min_rank):
                return f"段位不足！{match_info['name_cn']}需要 {get_rank_name(min_rank)} 以上。"

        room, error = engine.create_room(player_name, time_control=time_control, match_type=match_type)
        if error:
            return f"{error}"

        room.set_player_avatar(player_name, avatar)
        chess_rank = player_data.get('chess', {}).get('rank', 'novice_1')
        room.set_player_rank(player_name, chess_rank)
        lobby.set_player_location(player_name, 'chess_room')

        tc_info = ChessRoom.TIME_CONTROLS.get(time_control, {})
        is_ranked = match_info.get('ranked', False)

        ranked_tag = " [段位战]" if is_ranked else ""
        msg = f"✓ 房间已创建{ranked_tag}\n\n"
        msg += f"  房间ID:  {room.room_id}\n"
        msg += f"  段位场:  {match_info.get('name_cn', '友人场')}\n"
        msg += f"  时间:    {tc_info.get('name', '快棋')} ({tc_info.get('desc', '')})\n"
        msg += f"  位置:    白方（房主）\n\n"
        msg += f"  等待对手加入 ({room.get_player_count()}/2)\n"
        msg += f"  /invite @玩家名  邀请\n"
        if not is_ranked:
            msg += "  /bot             添加机器人"
        return {
            'action': 'chess_room_update',
            'location': 'chess_room',
            'message': msg,
            'room_data': room.get_table_data()
        }

    def _cmd_rooms(self):
        """房间列表（国际象棋格式）"""
        rooms = self.engine.list_rooms()
        if not rooms:
            return "当前没有可加入的房间。\n使用 /create 创建新房间。"

        text = "────── 房间列表 ──────\n\n"
        for r in rooms:
            text += f"  {r['room_id']}\n"
            text += f"    房主: {r['host']}  |  {r.get('match_type_name', '友人场')} {r.get('time_control_name', '快棋')}  |  {r['player_count']}/2\n\n"
        text += "/join <房间ID> 加入"
        return text

    def _cmd_stats(self, player_data):
        chess_data = player_data.get('chess', {})
        stats = chess_data.get('stats', {})

        total = stats.get('total_games', 0)
        wins = stats.get('wins', 0)
        losses = stats.get('losses', 0)
        draws = stats.get('draws', 0)

        win_rate = (wins / total * 100) if total > 0 else 0

        text = f"""【国际象棋战绩】

总对局数: {total}
  胜: {wins} ({wins/max(total,1)*100:.1f}%)
  负: {losses} ({losses/max(total,1)*100:.1f}%)
  和: {draws} ({draws/max(total,1)*100:.1f}%)

胜率: {win_rate:.1f}%

【时间分布】
  闪电战: {stats.get('blitz_games', 0)}
  快棋:   {stats.get('rapid_games', 0)}
  慢棋:   {stats.get('classical_games', 0)}
  段位战: {stats.get('ranked_games', 0)}
"""
        return text

    def _cmd_accept_draw(self, player_name):
        room = self.engine.get_player_room(player_name)
        if not room or room.state != 'playing':
            return "当前不在对局中。"
        result = room.accept_draw(player_name)
        if result:
            return self._finish_game(None, room, result)
        return "没有待接受的和棋提议。"

    def _cmd_start(self, lobby, player_name):
        engine = self.engine
        room = engine.get_player_room(player_name)
        if not room:
            return "你不在任何房间中。"
        if room.host != player_name:
            return "只有房主才能开始游戏。"
        if room.state != 'waiting':
            return "游戏已经开始了。"
        if not room.is_full():
            return f"需要2名玩家才能开始。当前: {room.get_player_count()}/2"

        if room.start_game():
            for p in room.players.values():
                if p and not room.is_bot(p):
                    lobby.set_player_location(p, 'chess_playing')

            pos = room.get_position(player_name)
            my_color = room.POSITIONS[pos]
            current_name = room.get_current_player_name()

            msg = f"────── ♟ 对局开始 ──────\n\n"
            msg += f"  你执: {my_color}\n"

            if pos == room.current_side():
                msg += "轮到你走棋 (如 e4, Nf3, O-O)"
            else:
                msg += f"等待 {current_name} 走棋"

            # 如果对方是机器人且白方是机器人，让机器人先走
            if room.is_bot(room.get_current_player_name()):
                san, game_result = room.make_bot_move()
                if san:
                    msg += f"\n\n← {room.get_current_player_name()}: {san}"
                    if game_result and game_result.get('type') == 'check':
                        msg += "  ♚ 将军！"
                    msg += "\n轮到你走棋"

            room_data = room.get_table_data()
            notify_msg = f"♟ 对局开始！\n白方: {room.players[0]}\n黑方: {room.players[1]}"
            return {
                'action': 'chess_game_start',
                'send_to_caller': [
                    {'type': 'game', 'text': msg},
                    {'type': 'room_update', 'room_data': room_data},
                    {'type': 'location_update', 'location': 'chess_playing'},
                ],
                'send_to_players': self._build_game_notify(
                    room, notify_msg, room_data,
                    exclude=player_name, location='chess_playing',
                ),
                'save': True,
            }
        else:
            return "开始游戏失败。"

    # ==================== 走棋 & 结算 ====================

    def _process_move(self, lobby, player_name, room, move_text):
        """处理国际象棋走棋"""
        success, san, result = room.make_move(player_name, move_text.strip())
        if not success:
            return result  # result 是错误信息

        pos = room.get_position(player_name)

        # 对局结束
        if result and result.get('type') not in ('check', None):
            return self._finish_game(lobby, room, result, last_move_san=san, caller_name=player_name)

        msg = f"→ {san}"
        if result and result.get('type') == 'check':
            msg += "  ♚ 将军！"

        notify_msg = f"{player_name} 走了: {san}"

        # 如果对方是机器人，让机器人走
        opponent = 1 - pos
        if room.is_bot(room.players[opponent]) and room.state == 'playing':
            bot_san, bot_result = room.make_bot_move()
            if bot_san:
                msg += f"\n\n← {room.players[opponent]}: {bot_san}"

                if bot_result and bot_result.get('type') not in ('check', None):
                    return self._finish_game(lobby, room, bot_result, last_move_san=bot_san, caller_name=player_name)

                if bot_result and bot_result.get('type') == 'check':
                    msg += "  ♚ 将军！"

                msg += "\n轮到你走棋"
        else:
            msg += f"\n\n轮到 {room.players[opponent]} 走棋"

        room_data = room.get_table_data()
        return {
            'action': 'chess_move',
            'send_to_caller': [
                {'type': 'game', 'text': msg},
                {'type': 'room_update', 'room_data': room_data},
            ],
            'send_to_players': self._build_game_notify(room, notify_msg, room_data, exclude=player_name),
            'save': True,
        }

    def _finish_game(self, lobby, room, result, last_move_san=None, caller_name=None):
        """处理国际象棋对局结束"""
        from server.user_schema import get_rank_name

        result_text = format_game_result(result) or "对局结束"

        msg = ""
        if last_move_san:
            msg += f"  最后一手: {last_move_san}\n"
        msg += f"\n────── 🏁 {result_text} ──────\n\n"
        msg += f"走法: {room.format_move_history(20)}\n"

        # 处理段位变化
        rank_msg = ""
        if room.is_ranked_match():
            rank_changes = self._process_ranked_result(lobby, room, result)
            if rank_changes:
                parts = []
                for pname, info in rank_changes.items():
                    sign = '+' if info['points_change'] > 0 else ''
                    parts.append(f"  {pname}: {sign}{info['points_change']}pt → {info['new_rank_name']} ({info['new_points']}pt)")
                    if info['promoted']:
                        parts.append(f"    🎉 {pname} 升段！→ {info['new_rank_name']}")
                    elif info['demoted']:
                        parts.append(f"    📉 {pname} 降段 → {info['new_rank_name']}")
                rank_msg = "【段位变化】\n" + "\n".join(parts)

        # 处理对局统计
        self._process_game_stats(lobby, room, result)

        if rank_msg:
            msg += rank_msg + "\n"

        msg += "输入 /back 离开房间，或等待新对局"

        # 所有玩家返回房间
        if lobby:
            for p in room.players.values():
                if p and not room.is_bot(p):
                    lobby.set_player_location(p, 'chess_room')

        room_data = room.get_table_data()
        return {
            'action': 'chess_game_end',
            'send_to_caller': [
                {'type': 'game', 'text': msg},
                {'type': 'room_update', 'room_data': room_data},
                {'type': 'location_update', 'location': 'chess_room'},
            ] if caller_name else [],
            'send_to_players': self._build_game_notify(
                room, f"🏁 {result_text}", room_data,
                exclude=caller_name, location='chess_room',
            ),
            'save': True,
        }

    def _process_game_stats(self, lobby, room, result):
        """更新国际象棋对局统计"""
        from server.player_manager import PlayerManager

        rtype = result.get('type')

        for i in range(2):
            pname = room.players[i]
            if not pname or room.is_bot(pname):
                continue

            player_data = self._load_player(lobby, pname)
            if not player_data:
                continue

            chess_data = player_data.get('chess', {})
            stats = chess_data.get('stats', {})

            stats['total_games'] = stats.get('total_games', 0) + 1

            if rtype in ('checkmate', 'resign', 'timeout'):
                if result.get('winner') == i:
                    stats['wins'] = stats.get('wins', 0) + 1
                else:
                    stats['losses'] = stats.get('losses', 0) + 1
            else:
                stats['draws'] = stats.get('draws', 0) + 1

            if room.is_ranked_match():
                stats['ranked_games'] = stats.get('ranked_games', 0) + 1

            tc = room.time_control
            if tc == 'blitz':
                stats['blitz_games'] = stats.get('blitz_games', 0) + 1
            elif tc == 'rapid':
                stats['rapid_games'] = stats.get('rapid_games', 0) + 1
            elif tc == 'classical':
                stats['classical_games'] = stats.get('classical_games', 0) + 1

            chess_data['stats'] = stats
            player_data['chess'] = chess_data
            self._check_titles(player_data, stats)
            PlayerManager.save_player_data(pname, player_data)
