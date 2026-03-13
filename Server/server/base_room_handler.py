"""房间制游戏共享指令处理器基类"""

from server.player_manager import PlayerManager


class BaseRoomCommandHandler:
    """房间制游戏指令处理器基类

    子类需实现:
        game_key, game_name, action_prefix, max_players,
        room_location, playing_location,
        _get_match_types(), _get_title_checks(stats),
        _get_rank_points_change(rank, result_data),
        _format_stats(player_data), _format_room_list(rooms)
    """

    def __init__(self, engine):
        self.engine = engine

    def _iter_room_players(self, room, exclude=None):
        """迭代房间内的真人玩家（排除 bots 和 exclude）"""
        for i in range(self.max_players):
            p = room.players[i]
            if not p or p == exclude:
                continue
            if hasattr(room, 'is_bot') and room.is_bot(p):
                continue
            yield p

    def _build_notify_players(self, room, message, room_data, exclude=None, location=None):
        """给房间内其他玩家发送嵌入消息的 room_update"""
        players = {}
        for p in self._iter_room_players(room, exclude):
            msgs = [{'type': 'room_update', 'message': message, 'room_data': room_data}]
            if location:
                msgs.append({'type': 'location_update', 'location': location})
            players[p] = msgs
        return players

    def _build_game_notify(self, room, message, room_data, exclude=None, location=None, update_last=False):
        """给房间内其他玩家发送独立的文字+room_update"""
        players = {}
        for p in self._iter_room_players(room, exclude):
            msgs = []
            if message:
                msgs.append({'type': 'game', 'text': message, 'update_last': update_last})
            msgs.append({'type': 'room_update', 'room_data': room_data})
            if location:
                msgs.append({'type': 'location_update', 'location': location})
            players[p] = msgs
        return players

    # ==================== 共享指令 ====================

    def _cmd_cancel(self, player_name):
        """取消待处理操作"""
        if player_name in self.engine.pending_confirms:
            del self.engine.pending_confirms[player_name]
            return "已取消。"
        return "没有待处理的操作。"

    def _cmd_rank(self, player_data):
        """显示段位信息"""
        from server.rank_system import get_rank_info, get_rank_index

        game_data = player_data.get(self.game_key, {})
        rank_id = game_data.get('rank', 'novice_1')
        rank_points = game_data.get('rank_points', 0)
        max_rank = game_data.get('max_rank', 'novice_1')
        rank_info = get_rank_info(rank_id, self.game_key)
        max_rank_info = get_rank_info(max_rank, self.game_key)

        points_up = rank_info.get('points_up')
        if points_up:
            progress = min(100, int(rank_points / points_up * 100))
            progress_bar = '█' * (progress // 10) + '░' * (10 - progress // 10)
        else:
            progress_bar = '████████████ MAX'
            progress = 100

        text = f"【{self.game_name}段位】\n\n"
        text += f"当前段位: {rank_info['name']}\n"
        text += f"段位点数: {rank_points}pt"
        if points_up:
            text += f" / {points_up}pt"
        text += f"\n升段进度: [{progress_bar}] {progress}%\n"
        text += f"历史最高: {max_rank_info['name']}\n"
        return text

    def _cmd_invite(self, lobby, player_name, player_data, args):
        """邀请玩家"""
        engine = self.engine
        if not args or not args.startswith('@'):
            return "用法: /invite @玩家名"

        target = args[1:].strip()
        room = engine.get_player_room(player_name)
        if not room:
            return "你还没有创建或加入房间。"
        if target not in lobby.online_players:
            return f"玩家 {target} 不在线。"
        if target == player_name:
            return "不能邀请自己。"
        if engine.get_player_room(target):
            return f"{target} 已经在一个房间中了。"

        engine.send_invite(player_name, target, room.room_id)
        lobby._track_invite(player_name, player_data)

        if lobby.invite_callback:
            lobby.invite_callback(target, {
                'type': 'game_invite',
                'from': player_name,
                'game': self.game_key,
                'room_id': room.room_id,
                'message': f" {player_name} 邀请你加入{self.game_name}房间！\n输入 /play {self.game_key} 然后 /accept 接受邀请"
            })

        return f"已向 {target} 发送邀请"

    def _cmd_accept_invite(self, lobby, player_name, player_data):
        """接受邀请"""
        engine = self.engine
        invite = engine.get_invite(player_name)
        if not invite:
            return "你没有收到邀请，或邀请已过期。"

        room_id = invite['room_id']
        engine.clear_invite(player_name)

        room, error = engine.join_room(room_id, player_name)
        if error:
            return f"{error}"


        player_rank = player_data.get(self.game_key, {}).get('rank', 'novice_1')
        room.set_player_rank(player_name, player_rank)
        lobby.set_player_location(player_name, self.room_location)
        pos = room.get_position(player_name)

        table_data = room.get_table_data()
        return {
            'action': f'{self.action_prefix}_room_update',
            'send_to_caller': [
                {'type': 'game', 'text': f"✓ 接受邀请加入成功\n\n  房间ID: {room.room_id}\n  位置:   {room.POSITIONS[pos]}\n\n  等待开始 ({room.get_player_count()}/{self.max_players})"},
                {'type': 'room_update', 'room_data': table_data},
                {'type': 'location_update', 'location': self.room_location},
            ],
            'send_to_players': self._build_notify_players(
                room, f"{player_name} 接受邀请加入了房间", table_data, exclude=player_name),
            'save': True,
        }

    def _cmd_join(self, lobby, player_name, player_data, args):
        """加入房间"""
        from server.rank_system import get_rank_name, get_rank_index
        _gk = self.game_key
        engine = self.engine
        location = lobby.get_player_location(player_name)

        if location != self.game_key:
            return f"请先返回{self.game_name}大厅再加入房间。"

        if not args:
            return "用法: /join <房间ID>\n使用 /rooms 查看房间列表。"

        room_id = args.strip()
        room = engine.get_room(room_id)
        if not room:
            return "房间不存在。"

        # 检查段位要求
        match_types = self._get_match_types()
        match_info = match_types.get(room.match_type, {})

        if match_info.get('ranked'):
            player_rank = player_data.get(self.game_key, {}).get('rank', 'novice_1')
            min_rank = match_info.get('min_rank', 'novice_1')
            if get_rank_index(player_rank, _gk) < get_rank_index(min_rank, _gk):
                return f"段位不足！{match_info.get('name_cn', '')}需要 {get_rank_name(min_rank, _gk)} 以上。"

        room, error = engine.join_room(room_id, player_name)
        if error:
            return f"{error}"

        player_rank = player_data.get(self.game_key, {}).get('rank', 'novice_1')
        room.set_player_rank(player_name, player_rank)
        lobby.set_player_location(player_name, self.room_location)
        pos = room.get_position(player_name)

        join_msg = f"✓ 加入房间成功\n\n"
        join_msg += f"  房间ID:  {room.room_id}\n"
        join_msg += f"  位置:    {room.POSITIONS[pos]}\n"
        join_msg += f"  房主:    {room.host}\n\n"
        join_msg += f"  等待开始 ({room.get_player_count()}/{self.max_players})"

        notify_msg = f"{player_name} 加入了房间"
        if room.is_full():
            notify_msg += "\n人已齐！房主可以输入 /start 开始游戏"

        table_data = room.get_table_data()
        return {
            'action': f'{self.action_prefix}_room_update',
            'send_to_caller': [
                {'type': 'game', 'text': join_msg},
                {'type': 'room_update', 'room_data': table_data},
                {'type': 'location_update', 'location': self.room_location},
            ],
            'send_to_players': self._build_notify_players(
                room, notify_msg, table_data, exclude=player_name),
            'save': True,
        }

    def _cmd_bot(self, player_name, args=None):
        """添加机器人"""
        engine = self.engine
        room = engine.get_player_room(player_name)
        if not room:
            return "你不在任何房间中。"
        if room.host != player_name:
            return "只有房主才能添加机器人。"
        if room.state != 'waiting':
            return "游戏已开始，无法添加机器人。"
        if room.is_ranked_match():
            return "段位场不能添加机器人。"

        count = 1
        if args:
            try:
                count = max(1, min(self.max_players - 1, int(args.strip())))
            except ValueError:
                count = 1

        added_bots = []
        for _ in range(count):
            if room.is_full():
                break
            success, result = room.add_bot()
            if success:
                added_bots.append(result)
            else:
                break

        if not added_bots:
            return "无法添加机器人，房间可能已满。"

        bot_names = ', '.join(added_bots)
        notify_msg = f"机器人 {bot_names} 加入了房间"
        if room.is_full():
            notify_msg += f"\n人已齐！房主可以输入 /start 开始"

        table_data = room.get_table_data()
        return {
            'action': f'{self.action_prefix}_room_update',
            'send_to_caller': [
                {'type': 'game', 'text': f"✓ 已添加机器人: {bot_names}" + ("\n人已齐，输入 /start 开始" if room.is_full() else "")},
                {'type': 'room_update', 'room_data': table_data},
            ],
            'send_to_players': self._build_notify_players(
                room, notify_msg, table_data, exclude=player_name),
            'save': True,
        }

    def _cmd_kick(self, player_name, args):
        """踢出玩家或机器人"""
        engine = self.engine
        room = engine.get_player_room(player_name)
        if not room:
            return "你不在任何房间中。"
        if room.host != player_name:
            return "只有房主才能踢出玩家。"
        if room.state != 'waiting':
            return "游戏已开始，无法踢出玩家。"

        if not args:
            players_list = []
            for i in range(self.max_players):
                p = room.players[i]
                if p and p != player_name:
                    mark = " (bot)" if room.is_bot(p) else ""
                    players_list.append(f"  {i+1}. {p}{mark}")
            if not players_list:
                return "房间里没有其他玩家可以踢出。"
            return "用法: /kick <编号> 或 /kick @名字\n\n当前玩家:\n" + '\n'.join(players_list)

        target = args.strip()
        target_name = None

        try:
            idx = int(target) - 1
            if 0 <= idx < self.max_players and room.players[idx] and room.players[idx] != player_name:
                target_name = room.players[idx]
        except ValueError:
            pass

        if not target_name and target.startswith('@'):
            name = target[1:]
            for i in range(self.max_players):
                p = room.players[i]
                if p and p != player_name and (p == name or p.lower() == name.lower()):
                    target_name = p
                    break

        if not target_name:
            return f"找不到玩家: {target}\n用法: /kick <编号> 或 /kick @名字"

        is_bot = room.is_bot(target_name)
        pos = room.remove_player(target_name)
        if pos < 0:
            return "踢出失败。"

        if is_bot:
            room.bots.discard(target_name)

        table_data = room.get_table_data()
        return {
            'action': f'{self.action_prefix}_player_kick',
            'send_to_caller': [
                {'type': 'game', 'text': f"已踢出: {target_name}"},
                {'type': 'room_update', 'room_data': table_data},
            ],
            'send_to_players': self._build_notify_players(
                room, f"{target_name} 被踢出了房间", table_data, exclude=player_name),
        }

    # ==================== 段位 & 统计 ====================

    def _process_ranked_result(self, lobby, room, result_data):
        """处理段位场结果，返回 rank_changes dict"""
        from server.rank_system import (
            get_rank_info, get_rank_name, get_rank_index,
            get_title_id_from_rank, get_rank_order
        )

        _gk = self.game_key
        rank_order = get_rank_order(_gk)
        rank_changes = {}

        for player_name, outcome_data in self._iter_ranked_players(room, result_data):
            player_data = self._load_player(lobby, player_name)
            if not player_data:
                continue

            game_data = player_data.get(_gk, {})
            current_rank = game_data.get('rank', rank_order[0])
            current_points = game_data.get('rank_points', 0)

            points_change = self._get_rank_points_change(current_rank, outcome_data)
            new_points = max(0, current_points + points_change)

            rank_info = get_rank_info(current_rank, _gk)
            new_rank = current_rank
            promoted = False
            demoted = False

            # 升段检查
            points_up = rank_info.get('points_up')
            if points_up and new_points >= points_up:
                idx = get_rank_index(current_rank, _gk)
                if idx < len(rank_order) - 1:
                    new_rank = rank_order[idx + 1]
                    new_points = 0
                    promoted = True

            # 降段检查
            points_down = rank_info.get('points_down')
            if points_down is not None and current_points + points_change < 0:
                idx = get_rank_index(current_rank, _gk)
                if idx > 0:
                    prev_rank = rank_order[idx - 1]
                    prev_info = get_rank_info(prev_rank, _gk)
                    if rank_info['tier'] > 2 or (rank_info['tier'] == 2 and prev_info['tier'] == 2):
                        new_rank = prev_rank
                        new_points = prev_info.get('points_up', 40) // 2
                        demoted = True

            game_data['rank'] = new_rank
            game_data['rank_points'] = new_points

            if get_rank_index(new_rank, _gk) > get_rank_index(game_data.get('max_rank', rank_order[0]), _gk):
                game_data['max_rank'] = new_rank

            if promoted:
                title_id = get_title_id_from_rank(new_rank)
                if title_id:
                    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
                    if title_id not in titles['owned']:
                        titles['owned'].append(title_id)
                    player_data['titles'] = titles

            player_data[_gk] = game_data
            PlayerManager.save_player_data(player_name, player_data)

            rank_changes[player_name] = {
                'points_change': points_change,
                'new_points': new_points,
                'old_rank': current_rank,
                'new_rank': new_rank,
                'new_rank_name': get_rank_name(new_rank, _gk),
                'promoted': promoted,
                'demoted': demoted,
            }

        return rank_changes

    def _check_titles(self, player_data, stats):
        """根据统计检查并授予头衔"""
        titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
        owned = titles['owned']

        for title_id, condition in self._get_title_checks(stats):
            if condition and title_id not in owned:
                owned.append(title_id)

        player_data['titles'] = titles

    def _load_player(self, lobby, player_name):
        """加载玩家数据（优先在线缓存）"""
        if lobby:
            pd = lobby.online_players.get(player_name)
            if pd:
                return pd
        return PlayerManager.load_player_data(player_name)

    # ==================== 子类必须实现的钩子 ====================

    def _get_match_types(self):
        """返回段位场类型字典"""
        raise NotImplementedError

    def _get_title_checks(self, stats):
        """返回 [(title_id, condition_bool), ...]"""
        raise NotImplementedError

    def _get_rank_points_change(self, rank, outcome_data):
        """计算段位点变化"""
        raise NotImplementedError

    def _iter_ranked_players(self, room, result_data):
        """迭代参与段位结算的 (player_name, outcome_data)"""
        raise NotImplementedError
