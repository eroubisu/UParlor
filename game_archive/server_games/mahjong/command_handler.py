"""
麻将 - 指令处理器
继承 BaseRoomCommandHandler 共享基类
"""

from server.base_room_handler import BaseRoomCommandHandler
from server.player_manager import PlayerManager
from .room import MahjongRoom
from .messages import (build_room_broadcast, build_hands_broadcast,
                       build_discard_broadcast, build_win_broadcast,
                       build_draw_messages)


class MahjongCommandHandler(BaseRoomCommandHandler):
    """麻将指令处理器"""

    game_key = 'mahjong'
    game_name = '麻将'
    action_prefix = 'mahjong'
    max_players = 4
    room_location = 'mahjong_room'
    playing_location = 'mahjong_playing'

    def _get_match_types(self):
        return MahjongRoom.MATCH_TYPES

    def _get_title_checks(self, stats):
        return [
            ('mahjong_beginner', stats.get('total_games', 0) >= 1),
            ('riichi_master', stats.get('riichi_count', 0) >= 100),
            ('tsumo_king', stats.get('tsumo_count', 0) >= 100),
            ('first_place_hunter', stats.get('wins', 0) >= 50),
            ('yakuman_holder', stats.get('yakuman_count', 0) >= 1),
        ]

    def _get_rank_points_change(self, rank, place_data):
        from server.user_schema import get_rank_points_change
        place, game_type_base = place_data
        return get_rank_points_change(rank, place, game_type_base)

    def _iter_ranked_players(self, room, rankings):
        game_type_base = 'south' if room.game_type in ['bronze', 'silver', 'gold', 'jade', 'throne'] else room.game_type
        for place, pos in enumerate(rankings, 1):
            player_name = room.players[pos]
            if not player_name or room.is_bot(player_name):
                continue
            yield player_name, (place, game_type_base)

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        """处理麻将游戏指令

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
        avatar = player_data.get('avatar')
        location = lobby.get_player_location(player_name)

        # 段位场名称提示
        match_shortcuts = {'/yuujin', '/dou', '/gin', '/kin', '/gyoku', '/ouza'}
        if cmd in match_shortcuts:
            return f"你是否想创建房间？请使用 /create {cmd[1:]}"

        # 创建房间
        if cmd == '/create':
            if location != 'mahjong':
                return "请先返回麻将大厅再创建房间。"

            from server.user_schema import get_rank_name, get_rank_index

            game_mode = None
            match_type = None

            if args:
                parts = args.lower().split()
                for part in parts:
                    if part in ['tonpu', 'ton', 't', 'east', 'e']:
                        game_mode = 'tonpu'
                    elif part in ['hanchan', 'han', 'h', 'south', 's']:
                        game_mode = 'hanchan'
                    elif part in ['yuujin', 'yuu', 'y', 'friend', 'f']:
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

            if game_mode is None or match_type is None:
                engine.pending_confirms[player_name] = ('create_room', {'game_mode': game_mode, 'match_type': match_type})

                if match_type is None:
                    player_rank = player_data.get('mahjong', {}).get('rank', 'novice_1')
                    player_rank_idx = get_rank_index(player_rank)

                    text = "请选择段位场:  (输入编号，或其他任意指令取消)\n\n"
                    text += "  1. yuujin (友人场) - 不影响段位\n"

                    match_list = [
                        ('dou', '銅の間', '铜之间', 'novice_1'),
                        ('gin', '銀の間', '银之间', 'adept_1'),
                        ('kin', '金の間', '金之间', 'expert_1'),
                        ('gyoku', '玉の間', '玉之间', 'master_1'),
                        ('ouza', '王座の間', '王座之间', 'saint_1'),
                    ]

                    for i, (key, jp_name, cn_name, min_rank) in enumerate(match_list, 2):
                        min_rank_idx = get_rank_index(min_rank)
                        can_enter = player_rank_idx >= min_rank_idx
                        status = "" if can_enter else f" (需要{get_rank_name(min_rank)})"
                        text += f"  {i}. {key} ({cn_name}){status}\n"

                    return text
                else:
                    match_info = MahjongRoom.MATCH_TYPES.get(match_type, {})
                    text = f"已选择: {match_info.get('name_cn', match_type)}\n\n"
                    text += "请选择游戏模式:  (输入编号，或其他任意指令取消)\n\n"
                    text += "  1. tonpu (東風戦/东风战) - 4局\n"
                    text += "  2. hanchan (半荘戦/半庄战) - 8局"
                    return text

            match_info = MahjongRoom.MATCH_TYPES.get(match_type, MahjongRoom.MATCH_TYPES['yuujin'])
            if match_info.get('ranked'):
                player_rank = player_data.get('mahjong', {}).get('rank', 'novice_1')
                min_rank = match_info.get('min_rank', 'novice_1')
                player_rank_idx = get_rank_index(player_rank)
                min_rank_idx = get_rank_index(min_rank)
                if player_rank_idx < min_rank_idx:
                    return f"段位不足！{match_info['name_cn']}需要 {get_rank_name(min_rank)} 以上。\n你的段位: {get_rank_name(player_rank)}"

            room, error = engine.create_room(player_name, game_mode=game_mode, match_type=match_type)
            if error:
                return f"{error}"

            room.set_player_avatar(player_name, avatar)
            player_rank = player_data.get('mahjong', {}).get('rank', 'novice_1')
            room.set_player_rank(player_name, player_rank)
            lobby.set_player_location(player_name, 'mahjong_room')

            mode_info = MahjongRoom.GAME_MODES.get(game_mode, {})
            is_ranked = match_info.get('ranked', False)

            msg = f"""
房间创建成功！

房间ID: {room.room_id}
段位场: {match_info.get('name_cn', '友人场')}
模式: {mode_info.get('name_cn', '半庄战')}"""

            if is_ranked:
                msg += f"\n类型: 段位战"

            msg += f"""
你的位置: 东（房主）

【邀请其他玩家】
  /invite @玩家名  - 邀请在线玩家

【等待中...】 {room.get_player_count()}/4
"""

            return {
                'action': 'mahjong_room_update',
                'send_to_caller': [
                    {'type': 'game', 'text': msg},
                    {'type': 'room_update', 'room_data': room.get_table_data()},
                    {'type': 'location_update', 'location': 'mahjong_room'},
                ],
                'save': True,
            }

        # 取消操作
        elif cmd == '/cancel':
            return self._cmd_cancel(player_name)

        # 查看房间列表
        elif cmd == '/rooms':
            return self._cmd_rooms()

        # 查看段位
        elif cmd == '/rank':
            return self._cmd_rank(player_data)

        # 查看战绩统计
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
            return self._cmd_accept_invite(lobby, player_name, player_data)

        # 添加机器人
        elif cmd == '/bot':
            return self._cmd_bot(player_name, args)

        # 踢出玩家或机器人
        elif cmd == '/kick':
            return self._cmd_kick(player_name, args)

        # 开始游戏（仅房主可用）
        elif cmd == '/start':
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。"

            if room.host != player_name:
                return "只有房主才能开始游戏。"

            if room.state != 'waiting':
                return "游戏已经开始了。"

            if not room.is_full():
                return f"需要4名玩家才能开始游戏。当前: {room.get_player_count()}/4"

            if room.start_game(engine.game_data):
                return self._build_game_start_result(
                    lobby, room, player_name,
                    " 游戏开始！座位已随机分配\n\n",
                    " 游戏开始！座位已随机分配\n"
                )
            else:
                return "开始游戏失败。"

        # 开始下一局（流局或和牌后）
        elif cmd == '/next':
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。"

            if room.state != 'finished':
                return "当前局还未结束。"

            next_round_result = room.start_next_round()

            if next_round_result:
                round_wind = room.round_wind
                round_number = room.round_number + 1
                honba = room.honba
                prefix = f" {round_wind}{round_number}局 {honba}本场 开始！\n"
                return self._build_game_start_result(
                    lobby, room, player_name,
                    prefix + "\n",
                    prefix
                )
            else:
                # 游戏结束 - 所有玩家返回房间
                for p in room.players.values():
                    if p and isinstance(p, str) and not p.startswith('机器人'):
                        lobby.set_player_location(p, 'mahjong_room')

                scores = room.scores
                players = room.players
                result_lines = ["游戏结束！最终结果："]
                rankings = sorted(range(4), key=lambda i: scores[i], reverse=True)
                for rank, i in enumerate(rankings):
                    result_lines.append(f"  {rank+1}. {players[i]}: {scores[i]}点")

                self._process_game_stats(lobby, room, rankings)

                rank_changes = None
                if room.is_ranked_match():
                    rank_changes = self._process_ranked_result(lobby, room, rankings)
                    if rank_changes:
                        result_lines.append("")
                        result_lines.append("【段位点数变化】")
                        for pos in rankings:
                            player = players[pos]
                            if player and not room.is_bot(player):
                                change_info = rank_changes.get(player, {})
                                pts = change_info.get('points_change', 0)
                                sign = '+' if pts >= 0 else ''
                                result_lines.append(f"  {player}: {sign}{pts}pt")
                                if change_info.get('promoted'):
                                    result_lines.append(f"    升段！→ {change_info.get('new_rank_name', '')}")
                                elif change_info.get('demoted'):
                                    result_lines.append(f"    降段... → {change_info.get('new_rank_name', '')}")

                result_lines.append("")
                result_lines.append("输入 /start 再来一局，/quit 或 /back 离开房间")

                msg = '\n'.join(result_lines)
                room_data = room.get_table_data()
                broadcast = build_room_broadcast(room, msg, room_data,
                                                  exclude_player=player_name,
                                                  location='mahjong_room')
                return {
                    'action': 'mahjong_game_end',
                    'send_to_caller': [
                        {'type': 'game', 'text': msg},
                        {'type': 'room_update', 'room_data': room_data},
                        {'type': 'location_update', 'location': 'mahjong_room'},
                    ],
                    **broadcast,
                    'save': True,
                }

        # 查看当前房间状态
        elif cmd == '/room' or cmd == '/status':
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。\n使用 /create 创建房间或 /rooms 查看房间列表。"

            pos = room.get_position(player_name)
            text = f"""
【房间状态】
房间ID: {room.room_id}
房主: {room.host}
状态: {'等待中' if room.state == 'waiting' else '游戏中'}
你的位置: {room.POSITIONS[pos]}

【座位】
"""
            for i in range(4):
                player = room.players[i] or "(空位)"
                mark = " ← 你" if i == pos else ""
                text += f"  {room.POSITIONS[i]}: {player}{mark}\n"

            text += f"\n人数: {room.get_player_count()}/4"

            if room.is_full() and room.host == player_name and room.state == 'waiting':
                text += "\n\n人已齐！输入 /start 开始游戏"

            return {
                'action': 'mahjong_room_update',
                'send_to_caller': [
                    {'type': 'game', 'text': text},
                    {'type': 'room_update', 'room_data': room.get_table_data()},
                ],
                'save': True,
            }

        # 查看宝牌
        elif cmd == '/dora':
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。"
            if room.state != 'playing':
                return "游戏还未开始。"

            from games.mahjong.game_data import DORA_NEXT, normalize_tile

            text = "【宝牌信息】\n\n"
            text += f"📍 场风: {room.round_wind}场 第{room.round_number + 1}局\n"
            text += f"📍 本场数: {room.honba}\n\n"

            text += "宝牌指示牌:\n"
            for i, indicator in enumerate(room.dora_indicators):
                dora = DORA_NEXT.get(normalize_tile(indicator), indicator)
                text += f"  {i+1}. [{indicator}] → 宝牌: [{dora}]\n"

            text += f"\n💎 赤宝牌: 赤五万、赤五条、赤五筒 (各1张)\n"
            text += f"\n📊 剩余牌数: {len(room.deck)} 张\n"
            text += f"📊 杠次数: {room.kan_count}\n"

            pos = room.get_position(player_name)
            if room.riichi[pos]:
                text += "\n🔒 你已立直，和牌时可翻开里宝牌！"

            return text

        # ========== 游戏中指令 ==========

        # 查看手牌
        elif cmd == '/hand' or cmd == '/h':
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。"
            if room.state != 'playing':
                return "游戏还未开始。"

            pos = room.get_position(player_name)

            tenpai_analysis = room.get_tenpai_analysis(pos)

            return {
                'action': 'mahjong_hand_update',
                'send_to_caller': [
                    {'type': 'hand_update', 'hand': room.hands[pos],
                     'tenpai_analysis': tenpai_analysis},
                    {'type': 'room_update', 'room_data': room.get_table_data()},
                ],
            }

        # 打牌
        elif cmd == '/d' or cmd == '/discard':
            room = engine.get_player_room(player_name)
            if not room:
                return "你不在任何房间中。"
            if room.state != 'playing':
                return "游戏还未开始。"

            pos = room.get_position(player_name)
            if room.current_turn != pos:
                current_player = room.players[room.current_turn]
                return f"还没轮到你，当前轮到 {current_player}。"

            if not args:
                return "用法: /d <编号>\n例如: /d 1 (打第1张牌)"

            arg = args.strip()
            hand = room.hands[pos]

            if room.waiting_for_action:
                return "⏳ 等待玩家操作中（吃/碰/杠）..."

            if arg.isdigit():
                idx = int(arg) - 1
                if idx < 0 or idx >= len(hand):
                    return f"无效编号，手牌共 {len(hand)} 张 (1-{len(hand)})"
                tile = hand[idx]
            else:
                tile = arg
                if tile not in hand:
                    return f"你没有这张牌: {tile}\n输入 /h 查看手牌"

            if room.riichi[pos]:
                drawn_tile = hand[-1] if hand else None
                if drawn_tile and tile != drawn_tile:
                    drawn_idx = len(hand)
                    return f"🔒 立直中只能摸切！请输入 /d {drawn_idx}"

            if room.discard_tile(pos, tile):
                next_pos = room.current_turn
                next_player = room.players[next_pos]

                if room.waiting_for_action:
                    my_new_hand = room.hands[pos]
                    action_count = len(room.action_players)
                    action_hint = f" [等待操作({action_count})]" if action_count > 0 else ""
                    room_data = room.get_table_data()
                    broadcast = build_discard_broadcast(
                        room, room.room_id, player_name, tile, next_player,
                        drawn_tile=None, waiting_action=True,
                        exclude_player=player_name)
                    return {
                        'action': 'mahjong_discard',
                        'send_to_caller': [
                            {'type': 'game', 'text': f"打出 [{tile}]，轮到 {next_player}{action_hint}"},
                            {'type': 'hand_update', 'hand': my_new_hand},
                            {'type': 'room_update', 'room_data': room_data},
                        ],
                        **broadcast,
                    }

                drawn = room.draw_tile(next_pos)

                if drawn is None:
                    ryuukyoku_result = room.process_ryuukyoku('exhaustive')
                    room.state = 'finished'
                    msg = self._build_ryuukyoku_msg(room, ryuukyoku_result)
                    room_data = room.get_table_data()
                    broadcast = build_room_broadcast(room, msg, room_data,
                                                     exclude_player=player_name)
                    return {
                        'action': 'mahjong_ryuukyoku',
                        'send_to_caller': [
                            {'type': 'game', 'text': msg},
                            {'type': 'hand_update', 'hand': room.hands[pos]},
                            {'type': 'room_update', 'room_data': room_data},
                        ],
                        **broadcast,
                        'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                                      'room_id': room.room_id}],
                    }

                next_player = room.players[next_pos]
                my_new_hand = room.hands[pos]
                room_data = room.get_table_data()
                broadcast = build_discard_broadcast(
                    room, room.room_id, player_name, tile, next_player,
                    drawn_tile=drawn, waiting_action=False,
                    exclude_player=player_name)

                return {
                    'action': 'mahjong_discard',
                    'send_to_caller': [
                        {'type': 'game', 'text': f"打出 [{tile}]，轮到 {next_player}"},
                        {'type': 'hand_update', 'hand': my_new_hand},
                        {'type': 'room_update', 'room_data': room_data},
                    ],
                    **broadcast,
                }
            else:
                return f"你没有这张牌: {tile}\n输入 /h 查看手牌"

        # 碰
        elif cmd == '/pong':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)
            last_tile = room.last_discard

            if not last_tile:
                return "没有可以碰的牌"

            actions = room.check_actions(pos, last_tile)
            if 'pong' not in actions:
                return f"你没有足够的 [{last_tile}] 来碰"

            if room.do_pong(pos, last_tile):
                tenpai_analysis = room.get_tenpai_analysis(pos)
                room_data = room.get_table_data()
                broadcast = build_room_broadcast(room, f"{player_name} 碰 [{last_tile}]",
                                                  room_data, exclude_player=player_name)
                return {
                    'action': 'mahjong_pong',
                    'send_to_caller': [
                        {'type': 'game', 'text': f"碰 [{last_tile}]，请出牌"},
                        {'type': 'hand_update', 'hand': room.hands[pos],
                         'tenpai_analysis': tenpai_analysis},
                        {'type': 'room_update', 'room_data': room_data},
                    ],
                    **broadcast,
                }
            return "碰失败"

        # 杠
        elif cmd == '/kong':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)
            last_tile = room.last_discard

            if not last_tile:
                return "没有可以杠的牌"

            actions = room.check_actions(pos, last_tile)
            if 'kong' not in actions:
                return f"你没有足够的 [{last_tile}] 来杠"

            success, need_draw = room.do_kong(pos, last_tile)
            if success:
                drawn = room.draw_tile(pos, from_dead_wall=True) if need_draw else None
                tenpai_analysis = room.get_tenpai_analysis(pos)
                room_data = room.get_table_data()
                broadcast = build_room_broadcast(room, f"{player_name} 杠 [{last_tile}]",
                                                  room_data, exclude_player=player_name)
                return {
                    'action': 'mahjong_kong',
                    'send_to_caller': [
                        {'type': 'game', 'text': f"杠 [{last_tile}]" + (f"，岭上牌 [{drawn}]" if drawn else "") + "，请出牌"},
                        {'type': 'hand_update', 'hand': room.hands[pos], 'drawn': drawn,
                         'tenpai_analysis': tenpai_analysis},
                        {'type': 'room_update', 'room_data': room_data},
                    ],
                    **broadcast,
                }
            return "杠失败"

        # 吃
        elif cmd == '/chow':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)

            if pos != room.current_turn:
                return "只有下家才能吃牌"

            last_tile = room.last_discard
            if not last_tile:
                return "没有可以吃的牌"

            actions = room.check_actions(pos, last_tile)
            if 'chow' not in actions:
                return f"你没有能和 [{last_tile}] 组成顺子的牌"

            chow_options = actions['chow'].get('options', [])

            choice = 0
            if args:
                try:
                    choice = int(args) - 1
                except:
                    pass

            if choice < 0 or choice >= len(chow_options):
                if len(chow_options) > 1:
                    opts = ", ".join([f"{i+1}: {' '.join(opt)}" for i, opt in enumerate(chow_options)])
                    return f"请选择吃法: {opts}\n输入 /chow 编号"
                choice = 0

            selected = chow_options[choice]
            if room.do_chow(pos, last_tile, selected):
                tenpai_analysis = room.get_tenpai_analysis(pos)
                room_data = room.get_table_data()
                broadcast = build_room_broadcast(room, f"{player_name} 吃 [{' '.join(selected)}]",
                                                  room_data, exclude_player=player_name)
                return {
                    'action': 'mahjong_chow',
                    'send_to_caller': [
                        {'type': 'game', 'text': f"吃 [{' '.join(selected)}]，请出牌"},
                        {'type': 'hand_update', 'hand': room.hands[pos],
                         'tenpai_analysis': tenpai_analysis},
                        {'type': 'room_update', 'room_data': room_data},
                    ],
                    **broadcast,
                }
            return "吃失败"

        # 过（放弃吃碰杠）
        elif cmd == '/pass':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)

            if pos not in room.action_players:
                return "当前无需操作"

            actions = room.check_actions(pos, room.last_discard) if room.last_discard else {}
            if 'win' in actions:
                room.pass_ron(pos)

            room.player_pass(pos)

            if not room.waiting_for_action:
                next_pos = room.current_turn
                drawn = room.draw_tile(next_pos)

                if drawn is None:
                    ryuukyoku_result = room.process_ryuukyoku('exhaustive')
                    room.state = 'finished'
                    msg = self._build_ryuukyoku_msg(room, ryuukyoku_result, prefix_lines=["过"])
                    msg += "\n\n输入 /next 开始下一局"
                    notify_msg = self._build_ryuukyoku_msg(room, ryuukyoku_result)
                    notify_msg += "\n\n输入 /next 开始下一局"
                    room_data = room.get_table_data()
                    broadcast = build_room_broadcast(room, notify_msg, room_data,
                                                     exclude_player=player_name)
                    return {
                        'action': 'mahjong_ryuukyoku',
                        'send_to_caller': [
                            {'type': 'game', 'text': msg},
                            {'type': 'room_update', 'room_data': room_data},
                        ],
                        **broadcast,
                        'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                                      'room_id': room.room_id}],
                    }

                next_player = room.players[next_pos]
                room_data = room.get_table_data()

                # Build messages for other players
                send_to_players = {}
                schedule = []
                for pos_i in range(len(room.players)):
                    pname = room.players[pos_i]
                    if not pname or pname == player_name:
                        continue
                    if room.is_bot(pname):
                        continue
                    msgs = [
                        {'type': 'game', 'text': f"等待操作(0)，轮到 {next_player}"},
                        {'type': 'room_update', 'room_data': room_data},
                    ]
                    if pname == next_player:
                        draw_msgs, draw_sched = build_draw_messages(
                            room, room.room_id, pos_i, pname, drawn)
                        msgs.extend(draw_msgs)
                        schedule.extend(draw_sched)
                    send_to_players[pname] = msgs

                # Caller messages
                caller_msgs = [
                    {'type': 'game', 'text': f"过，轮到 {next_player}"},
                    {'type': 'room_update', 'room_data': room_data},
                ]
                if player_name == next_player:
                    pos_c = room.get_position(player_name)
                    draw_msgs, draw_sched = build_draw_messages(
                        room, room.room_id, pos_c, player_name, drawn)
                    caller_msgs.extend(draw_msgs)
                    schedule.extend(draw_sched)

                # Bot scheduling
                if next_player and room.is_bot(next_player):
                    schedule.append({
                        'game_id': 'mahjong', 'action': 'bot_play',
                        'room_id': room.room_id, 'player': next_player,
                    })

                return {
                    'action': 'mahjong_pass_complete',
                    'send_to_caller': caller_msgs,
                    'send_to_players': send_to_players,
                    'schedule': schedule,
                }

            remaining = len(room.action_players)
            next_pos = room.current_turn
            next_player = room.players[next_pos]
            room_data = room.get_table_data()
            broadcast = build_room_broadcast(room, f"[等待操作({remaining})]，轮到 {next_player}",
                                              room_data, exclude_player=player_name,
                                              update_last=True)
            return {
                'action': 'mahjong_pass',
                'send_to_caller': [
                    {'type': 'game', 'text': f"过 [等待操作({remaining})]"},
                ],
                **broadcast,
            }

        # 九种九牌流局
        elif cmd == '/kyuushu' or cmd == '/9':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)

            if room.current_turn != pos:
                return "还没轮到你"

            if not room.check_kyuushu_kyuuhai(pos):
                return "不满足九种九牌条件（需要第一巡、手牌有9种以上幺九牌、无人鸣牌）"

            room.state = 'finished'
            room_data = room.get_table_data()
            broadcast = build_room_broadcast(room, f"{player_name} 宣告九种九牌！流局",
                                              room_data, exclude_player=player_name)
            return {
                'action': 'mahjong_ryuukyoku',
                'send_to_caller': [
                    {'type': 'game', 'text': '九种九牌！流局'},
                    {'type': 'room_update', 'room_data': room_data},
                ],
                **broadcast,
                'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                              'room_id': room.room_id}],
            }

        # 查看听牌
        elif cmd == '/tenpai' or cmd == '/t':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)
            hand = room.hands[pos]

            if len(hand) == 14 or (len(hand) - 1) % 3 == 0:
                results = []
                checked = set()
                for tile in hand:
                    if tile in checked:
                        continue
                    checked.add(tile)

                    temp_hand = hand.copy()
                    temp_hand.remove(tile)

                    original = room.hands[pos]
                    room.hands[pos] = temp_hand
                    waiting = room.get_tenpai_tiles(pos)
                    room.hands[pos] = original

                    if waiting:
                        results.append(f"打 [{tile}] → 听 {', '.join([f'[{w}]' for w in waiting])}")

                if results:
                    return "听牌分析:\n" + "\n".join(results)
                else:
                    return "当前无法听牌"
            else:
                waiting = room.get_tenpai_tiles(pos)
                if waiting:
                    return f"你正在听: {', '.join([f'[{w}]' for w in waiting])}"
                else:
                    return "你还没有听牌"

        # 胡牌（荣和）
        elif cmd == '/hu' or cmd == '/ron':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)
            last_tile = room.last_discard

            if not last_tile:
                return "没有可以胡的牌"

            if room.check_furiten(pos):
                return "振听状态，不能荣和（只能自摸）"

            actions = room.check_actions(pos, last_tile)
            if 'win' not in actions:
                return "你不能和这张牌"

            ron_result = room.declare_ron(pos)

            if ron_result == 'waiting':
                return {
                    'action': 'mahjong_ron_waiting',
                    'send_to_caller': [
                        {'type': 'game', 'text': '荣和宣言！等待其他玩家...'},
                        {'type': 'room_update', 'room_data': room.get_table_data()},
                    ],
                }

            if ron_result == 'triple_ron':
                room.state = 'finished'
                room.waiting_for_action = False
                room.action_players = []
                room.clear_ron_state()
                room_data = room.get_table_data()
                broadcast = build_room_broadcast(
                    room, "三家和了！流局\n\n三人同时宣告荣和，本局流局。\n\n输入 /next 开始下一局",
                    room_data, exclude_player=player_name)
                return {
                    'action': 'mahjong_ryuukyoku',
                    'send_to_caller': [
                        {'type': 'game', 'text': '三家和了！流局\n\n三人同时宣告荣和，本局流局。'},
                        {'type': 'room_update', 'room_data': room_data},
                    ],
                    **broadcast,
                    'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                                  'room_id': room.room_id}],
                }

            winners = room.get_ron_winners()
            discarder_pos = room.last_discarder
            discarder_name = room.players[discarder_pos] if discarder_pos is not None else "?"

            all_results = []
            all_win_animations = []

            for winner_pos, tile in winners:
                result = room.process_win(winner_pos, tile, is_tsumo=False, loser_pos=discarder_pos)

                if result.get('success'):
                    all_results.append(result)
                    winner_name = room.players[winner_pos]
                    if not room.is_bot(winner_name):
                        self._update_mahjong_stat(winner_name, 'ron_count')
                        if result.get('is_yakuman'):
                            self._update_mahjong_stat(winner_name, 'yakuman_count')
                    all_win_animations.append({
                        'winner': winner_name,
                        'win_type': 'ron',
                        'tile': tile,
                        'loser': discarder_name,
                        'yakus': result['yakus'],
                        'han': result['han'],
                        'fu': result['fu'],
                        'score': result['score'],
                        'is_yakuman': result['is_yakuman']
                    })

            room.clear_ron_state()

            if not all_results:
                return f"无役"

            if discarder_pos is not None and not room.is_bot(discarder_name):
                self._update_mahjong_stat(discarder_name, 'deal_in_count')

            room.state = 'finished'
            room.waiting_for_action = False
            room.action_players = []

            if discarder_pos is not None and room.discards[discarder_pos]:
                if room.discards[discarder_pos][-1] == last_tile:
                    room.discards[discarder_pos].pop()

            anim = all_win_animations[0] if len(all_win_animations) == 1 else all_win_animations
            room_data = room.get_table_data()
            anims = anim if isinstance(anim, list) else [anim]
            caller_msgs = [{'type': 'win_animation', **a} for a in anims]
            caller_msgs.append({'type': 'room_update', 'room_data': room_data})
            broadcast = build_win_broadcast(room, anim, room_data,
                                             exclude_player=player_name)
            return {
                'action': 'mahjong_win',
                'send_to_caller': caller_msgs,
                **broadcast,
                'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                              'room_id': room.room_id}],
            }

        # 自摸
        elif cmd == '/tsumo':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)

            if room.current_turn != pos:
                return "还没轮到你"

            if not room.just_drew:
                return "需要先摸牌才能自摸"

            hand = room.hands[pos]
            if not hand:
                return "无法自摸"

            tsumo_tile = hand[-1]

            if not room.can_win(hand[:-1], tsumo_tile):
                return "你不能自摸"

            result = room.process_win(pos, tsumo_tile, is_tsumo=True)

            if not result.get('success'):
                return f"{result.get('error', '无役')}"

            self._update_mahjong_stat(player_name, 'tsumo_count')
            if result.get('is_yakuman'):
                self._update_mahjong_stat(player_name, 'yakuman_count')

            room.state = 'finished'
            room.waiting_for_action = False

            anim = {
                'winner': player_name, 'win_type': 'tsumo', 'tile': tsumo_tile,
                'yakus': result['yakus'], 'han': result['han'], 'fu': result['fu'],
                'score': result['score'], 'is_yakuman': result['is_yakuman']
            }
            room_data = room.get_table_data()
            broadcast = build_win_broadcast(room, anim, room_data,
                                             exclude_player=player_name)
            return {
                'action': 'mahjong_win',
                'send_to_caller': [
                    {'type': 'win_animation', **anim},
                    {'type': 'room_update', 'room_data': room_data},
                ],
                **broadcast,
                'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                              'room_id': room.room_id}],
            }

        # 立直
        elif cmd == '/riichi':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)

            if room.current_turn != pos:
                return "还没轮到你"

            if not args:
                return "用法: /riichi <要打的牌编号>\n例如: /riichi 1"

            arg = args.strip()
            hand = room.hands[pos]

            if arg.isdigit():
                idx = int(arg) - 1
                if idx < 0 or idx >= len(hand):
                    return f"无效编号，手牌共 {len(hand)} 张"
                discard_tile = hand[idx]
            else:
                discard_tile = arg
                if discard_tile not in hand:
                    return f"你没有这张牌: {discard_tile}"

            success, error = room.declare_riichi(pos, discard_tile)
            if not success:
                return f"{error}"

            self._update_mahjong_stat(player_name, 'riichi_count')

            room.discard_tile(pos, discard_tile)

            next_pos = room.current_turn
            next_player = room.players[next_pos]

            if room.waiting_for_action:
                action_count = len(room.action_players)
                action_hint = f" [等待操作({action_count})]" if action_count > 0 else ""
                room_data = room.get_table_data()
                broadcast = build_discard_broadcast(
                    room, room.room_id, player_name, discard_tile, next_player,
                    drawn_tile=None, waiting_action=True, is_riichi=True,
                    exclude_player=player_name)
                return {
                    'action': 'mahjong_discard',
                    'send_to_caller': [
                        {'type': 'game', 'text': f"立直！打出 [{discard_tile}]{action_hint}"},
                        {'type': 'hand_update', 'hand': room.hands[pos]},
                        {'type': 'room_update', 'room_data': room_data},
                    ],
                    **broadcast,
                }

            drawn = room.draw_tile(next_pos)

            if drawn is None:
                ryuukyoku_result = room.process_ryuukyoku('exhaustive')
                room_data = room.get_table_data()
                broadcast = build_room_broadcast(room, '', room_data,
                                                 exclude_player=player_name)
                return {
                    'action': 'mahjong_ryuukyoku',
                    'send_to_caller': [
                        {'type': 'game', 'text': f"立直！打出 [{discard_tile}]"},
                        {'type': 'hand_update', 'hand': room.hands[pos]},
                        {'type': 'room_update', 'room_data': room_data},
                    ],
                    **broadcast,
                    'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                                  'room_id': room.room_id}],
                }

            room_data = room.get_table_data()
            broadcast = build_discard_broadcast(
                room, room.room_id, player_name, discard_tile, next_player,
                drawn_tile=drawn, waiting_action=False, is_riichi=True,
                exclude_player=player_name)
            return {
                'action': 'mahjong_discard',
                'send_to_caller': [
                    {'type': 'game', 'text': f"立直！打出 [{discard_tile}]"},
                    {'type': 'hand_update', 'hand': room.hands[pos]},
                    {'type': 'room_update', 'room_data': room_data},
                ],
                **broadcast,
            }

        # 暗杠
        elif cmd == '/ankan':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)

            if room.current_turn != pos:
                return "还没轮到你"

            kong_options = room.check_self_kong(pos)
            concealed_kongs = [k for k in kong_options if k['type'] == 'concealed']

            if not concealed_kongs:
                return "没有可以暗杠的牌"

            choice = 0
            if args:
                try:
                    choice = int(args) - 1
                except:
                    for i, k in enumerate(concealed_kongs):
                        if k['tile'] == args.strip():
                            choice = i
                            break

            if choice < 0 or choice >= len(concealed_kongs):
                if len(concealed_kongs) > 1:
                    opts = ", ".join([f"{i+1}: {k['tile']}" for i, k in enumerate(concealed_kongs)])
                    return f"请选择暗杠: {opts}\n输入 /ankan 编号"
                choice = 0

            tile = concealed_kongs[choice]['tile']
            success, need_draw = room.do_concealed_kong(pos, tile)

            if not success:
                return "暗杠失败"

            drawn = None
            if need_draw:
                drawn = room.draw_tile(pos, from_dead_wall=True)

            tenpai_analysis = room.get_tenpai_analysis(pos)
            room_data = room.get_table_data()
            broadcast = build_room_broadcast(room, f"{player_name} 暗杠！",
                                              room_data, exclude_player=player_name)
            return {
                'action': 'mahjong_ankan',
                'send_to_caller': [
                    {'type': 'game', 'text': f"暗杠！[{tile}]\n" + (f"岭上牌: [{drawn}]" if drawn else "") + "\n请出牌"},
                    {'type': 'hand_update', 'hand': room.hands[pos], 'drawn': drawn,
                     'tenpai_analysis': tenpai_analysis},
                    {'type': 'room_update', 'room_data': room_data},
                ],
                **broadcast,
            }

        # 加杠
        elif cmd == '/kakan':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)

            if room.current_turn != pos:
                return "还没轮到你"

            kong_options = room.check_self_kong(pos)
            added_kongs = [k for k in kong_options if k['type'] == 'added']

            if not added_kongs:
                return "没有可以加杠的牌"

            choice = 0
            if args:
                try:
                    choice = int(args) - 1
                except:
                    for i, k in enumerate(added_kongs):
                        if k['tile'] == args.strip():
                            choice = i
                            break

            if choice < 0 or choice >= len(added_kongs):
                if len(added_kongs) > 1:
                    opts = ", ".join([f"{i+1}: {k['tile']}" for i, k in enumerate(added_kongs)])
                    return f"请选择加杠: {opts}\n输入 /kakan 编号"
                choice = 0

            tile = added_kongs[choice]['tile']
            success, can_chankan, need_draw = room.do_added_kong(pos, tile)

            if not success:
                return "加杠失败"

            if can_chankan:
                room.waiting_for_action = True
                room.action_players = []
                for i in range(4):
                    if i != pos and room.can_win(room.hands[i], tile):
                        room.action_players.append(i)

                if room.action_players:
                    room_data = room.get_table_data()
                    broadcast = build_room_broadcast(
                        room, f"{player_name} 加杠 [{tile}]\n⚠ 可抢杠！",
                        room_data, exclude_player=player_name)
                    return {
                        'action': 'mahjong_kakan',
                        'send_to_caller': [
                            {'type': 'game', 'text': f"加杠！[{tile}]\n⚠ 可能被抢杠..."},
                            {'type': 'hand_update', 'hand': room.hands[pos]},
                            {'type': 'room_update', 'room_data': room_data},
                        ],
                        **broadcast,
                    }

            drawn = None
            if need_draw:
                drawn = room.draw_tile(pos, from_dead_wall=True)

            room.chankan_tile = None

            tenpai_analysis = room.get_tenpai_analysis(pos)
            room_data = room.get_table_data()
            broadcast = build_room_broadcast(room, f"{player_name} 加杠 [{tile}]",
                                              room_data, exclude_player=player_name)
            return {
                'action': 'mahjong_kakan',
                'send_to_caller': [
                    {'type': 'game', 'text': f"加杠！[{tile}]\n" + (f"岭上牌: [{drawn}]" if drawn else "") + "\n请出牌"},
                    {'type': 'hand_update', 'hand': room.hands[pos], 'drawn': drawn,
                     'tenpai_analysis': tenpai_analysis},
                    {'type': 'room_update', 'room_data': room_data},
                ],
                **broadcast,
            }

        # 抢杠
        elif cmd == '/chankan':
            room = engine.get_player_room(player_name)
            if not room or room.state != 'playing':
                return "游戏未开始"

            pos = room.get_position(player_name)
            tile = room.chankan_tile

            if not tile:
                return "没有可以抢杠的牌"

            if pos not in room.action_players:
                return "你不能抢杠"

            if not room.can_win(room.hands[pos], tile):
                return "你不能和这张牌"

            kakan_pos = room.current_turn
            result = room.process_win(pos, tile, is_tsumo=False, loser_pos=kakan_pos)

            if not result.get('success'):
                return f"{result.get('error', '无役')}"

            self._update_mahjong_stat(player_name, 'ron_count')
            if result.get('is_yakuman'):
                self._update_mahjong_stat(player_name, 'yakuman_count')
            kakan_name = room.players[kakan_pos]
            if not room.is_bot(kakan_name):
                self._update_mahjong_stat(kakan_name, 'deal_in_count')

            yaku_text = "\n".join([f"  {y[0]} ({y[1]}番)" if not y[2] else f"  ★{y[0]} (役满)" for y in result['yakus']])

            room.state = 'finished'
            room.waiting_for_action = False
            room.chankan_tile = None

            score_text = f"{result['han']}番{result['fu']}符 {result['score']}点" if not result['is_yakuman'] else f"役满 {result['score']}点"

            room_data = room.get_table_data()
            broadcast = build_room_broadcast(
                room, f"{player_name} 抢杠和！[{tile}]\n\n【役种】\n{yaku_text}\n\n【点数计算】\n{score_text}",
                room_data, exclude_player=player_name)
            return {
                'action': 'mahjong_win',
                'send_to_caller': [
                    {'type': 'game', 'text': f"抢杠和！[{tile}]\n\n【役种】\n{yaku_text}\n\n【点数计算】\n{score_text}"},
                    {'type': 'room_update', 'room_data': room_data},
                ],
                **broadcast,
                'schedule': [{'game_id': 'mahjong', 'action': 'cancel_timer',
                              'room_id': room.room_id}],
            }

        return None

    # ==================== 辅助方法 ====================

    def _update_mahjong_stat(self, player_name, stat_key, increment=1):
        """更新麻将统计数据并检查头衔"""
        player_data = PlayerManager.load_player_data(player_name)
        if not player_data:
            return

        mahjong_data = player_data.get('mahjong', {})
        stats = mahjong_data.get('stats', {})
        stats[stat_key] = stats.get(stat_key, 0) + increment
        mahjong_data['stats'] = stats
        player_data['mahjong'] = mahjong_data

        self._check_titles(player_data, stats)
        PlayerManager.save_player_data(player_name, player_data)

    def _process_game_stats(self, lobby, room, rankings):
        """更新所有玩家的对局统计（每局结束时调用，不区分段位/非段位）"""
        game_mode = getattr(room, 'game_mode', 'hanchan')

        place_keys = ['wins', 'second', 'third', 'fourth']
        for place, pos in enumerate(rankings, 1):
            player_name = room.players[pos]
            if not player_name or room.is_bot(player_name):
                continue

            player_data = self._load_player(lobby, player_name)
            if not player_data:
                continue

            mahjong_data = player_data.get('mahjong', {})
            stats = mahjong_data.get('stats', {})

            stats['total_games'] = stats.get('total_games', 0) + 1
            stats[place_keys[place - 1]] = stats.get(place_keys[place - 1], 0) + 1

            if game_mode == 'tonpu':
                stats['east_games'] = stats.get('east_games', 0) + 1
            else:
                stats['south_games'] = stats.get('south_games', 0) + 1

            if room.is_ranked_match():
                stats['ranked_games'] = stats.get('ranked_games', 0) + 1

            mahjong_data['stats'] = stats
            player_data['mahjong'] = mahjong_data

            self._check_titles(player_data, stats)
            PlayerManager.save_player_data(player_name, player_data)

    def _cmd_rooms(self):
        """房间列表（麻将格式）"""
        rooms = self.engine.list_rooms()
        if not rooms:
            return "当前没有可加入的房间。\n使用 /create 创建新房间。"

        text = "────── 房间列表 ──────\n\n"
        for r in rooms:
            text += f"  {r['room_id']}\n"
            text += f"    房主: {r['host']}  |  {r.get('match_type_name', '友人场')} {r.get('game_mode_name', '半庄')}  |  {r['player_count']}/4\n\n"
        text += "/join <房间ID> 加入"
        return text

    def _cmd_stats(self, player_data):
        """麻将战绩统计"""
        mahjong_data = player_data.get('mahjong', {})
        stats = mahjong_data.get('stats', {})

        total = stats.get('total_games', 0)
        w1 = stats.get('wins', 0)
        w2 = stats.get('second', 0)
        w3 = stats.get('third', 0)
        w4 = stats.get('fourth', 0)

        avg = (w1 * 1 + w2 * 2 + w3 * 3 + w4 * 4) / total if total > 0 else 0

        text = f"""【麻将战绩】\n\n总对局数: {total}\n  1位: {w1} ({w1/max(total,1)*100:.1f}%)\n  2位: {w2} ({w2/max(total,1)*100:.1f}%)\n  3位: {w3} ({w3/max(total,1)*100:.1f}%)\n  4位: {w4} ({w4/max(total,1)*100:.1f}%)\n\n平均顺位: {avg:.2f}\n\n【和牌统计】\n  荣和: {stats.get('ron_count', 0)}\n  自摸: {stats.get('tsumo_count', 0)}\n  放铳: {stats.get('deal_in_count', 0)}\n  立直: {stats.get('riichi_count', 0)}\n  役满: {stats.get('yakuman_count', 0)}\n\n【对局分布】\n  东风战: {stats.get('east_games', 0)}\n  半庄战: {stats.get('south_games', 0)}\n  段位战: {stats.get('ranked_games', 0)}\n"""
        return text

    def _build_game_start_result(self, lobby, room, player_name, msg_prefix, notify_prefix):
        """构建游戏开始/下一局的返回结果"""
        for p in room.players.values():
            if p and isinstance(p, str) and not p.startswith('机器人'):
                lobby.set_player_location(p, 'mahjong_playing')
        pos = room.get_position(player_name)
        my_hand = room.hands[pos]
        dealer_pos = room.dealer
        dealer_name = room.players[dealer_pos]
        drawn_tile = my_hand[-1] if pos == dealer_pos and len(my_hand) == 14 else None
        my_wind = room.get_player_wind(pos)

        msg = msg_prefix + f"庄家: {dealer_name}\n你的位置: {my_wind}家\n\n"
        if pos == dealer_pos:
            msg += "🎲 你是庄家，请出牌！\n输入 /d 编号 打出一张牌"
        else:
            msg += f"轮到 {dealer_name} 出牌\n输入 /h 查看手牌"

        room_data = room.get_table_data()
        notify_msg = f"{notify_prefix}庄家: {dealer_name}\n输入 /h 查看手牌"
        hands_broadcast = build_hands_broadcast(room, notify_msg, room_data,
                                                 location='mahjong_playing',
                                                 exclude_player=player_name)
        schedule = []
        if room.is_bot(dealer_name):
            schedule.append({
                'game_id': 'mahjong', 'action': 'bot_play',
                'room_id': room.room_id, 'player': dealer_name,
            })

        result = {
            'action': 'mahjong_game_start',
            'send_to_caller': [
                {'type': 'game', 'text': msg},
                {'type': 'hand_update', 'hand': my_hand, 'drawn': drawn_tile,
                 'tenpai_analysis': room.get_tenpai_analysis(pos)},
                {'type': 'room_update', 'room_data': room_data},
                {'type': 'location_update', 'location': 'mahjong_playing'},
            ],
            **hands_broadcast,
            'save': True,
        }
        if schedule:
            result['schedule'] = schedule
        return result

    def _build_ryuukyoku_msg(self, room, ryuukyoku_result, prefix_lines=None):
        """构建流局消息文本"""
        tenpai_names = [room.players[i] for i in ryuukyoku_result['tenpai']]
        noten_names = [room.players[i] for i in ryuukyoku_result['noten']]
        lines = list(prefix_lines or [])
        lines.append("荒牌流局！牌山已摸完")
        if tenpai_names:
            lines.append(f"📗 听牌: {', '.join(tenpai_names)}")
        if noten_names:
            lines.append(f"📕 未听: {', '.join(noten_names)}")
        for i in range(4):
            change = ryuukyoku_result['score_changes'][i]
            if change != 0:
                sign = '+' if change > 0 else ''
                lines.append(f"  {room.players[i]}: {sign}{change}")
        if ryuukyoku_result.get('renchan'):
            lines.append(f"🔄 {room.players[room.dealer]} 连庄")
        else:
            lines.append("➡ 轮庄")
        return '\n'.join(lines)
