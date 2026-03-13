"""
国际象棋游戏引擎 - 房间管理
实现 GameEngine 标准接口
"""

import time
from .room import ChessRoom
from .command_handler import ChessCommandHandler


class ChessEngine:
    """国际象棋引擎 - 管理所有房间"""

    def __init__(self):
        self.rooms = {}          # {room_id: ChessRoom}
        self.player_rooms = {}   # {player_name: room_id}
        self.invites = {}        # {target_name: {'from': host, 'room_id': id, 'time': ts}}
        self.pending_confirms = {}  # {player_name: (type, data)} 游戏内待确认状态
        self._cmd_handler = ChessCommandHandler(self)

    # ==================== 标准接口 ====================

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        """处理国际象棋指令（含待确认状态）"""
        # 先处理引擎级别的待确认状态
        pending = self.pending_confirms.get(player_name)
        if pending:
            result = self._handle_pending(lobby, player_name, player_data, cmd, args, pending)
            if result is not None:
                return result
        return self._cmd_handler.handle_command(lobby, player_name, player_data, cmd, args)

    def handle_disconnect(self, lobby, player_name):
        """处理玩家断线"""
        notifications = []
        self.pending_confirms.pop(player_name, None)
        room = self.get_player_room(player_name)
        if not room:
            return notifications

        pos = room.get_position(player_name)
        other_pos = 1 - pos if pos >= 0 else -1
        other = room.players.get(other_pos) if other_pos >= 0 else None

        if room.state == 'playing':
            # 对局中断线：处理判负
            result, error = room.resign(player_name)
            if result:
                self._cmd_handler._finish_game(lobby, room, result)
                if other and not other.startswith('机器人'):
                    room_data = room.get_table_data()
                    notifications.append({
                        'send_to_players': {
                            other: [
                                {'type': 'game', 'text': f"{player_name} 离开了房间（下线）\n{result['message']}"},
                                {'type': 'room_update', 'room_data': room_data},
                            ]
                        }
                    })
        else:
            if other and not other.startswith('机器人'):
                notifications.append({
                    'send_to_players': {
                        other: [{'type': 'game', 'text': f"{player_name} 离开了房间（下线）"}]
                    }
                })

        self.leave_room(player_name)
        return notifications

    def handle_back(self, lobby, player_name, player_data):
        """处理 /back"""
        location = lobby.get_player_location(player_name)

        # 对局中 → 确认提示
        if location == 'chess_playing':
            room = self.get_player_room(player_name)
            if room and room.state == 'playing':
                self.pending_confirms[player_name] = ('back_playing', None)
                return {
                    'action': 'confirm_prompt',
                    'message': '⚠ 对局进行中！退出将判负。\n输入 /y 确认，其他任意键取消。'
                }

        # 房间中 → 离开房间
        if location == 'chess_room':
            room = self.get_player_room(player_name)
            if room:
                pos = room.get_position(player_name)
                other = room.players.get(1 - pos) if pos >= 0 else None
                self.leave_room(player_name)
                lobby.set_player_location(player_name, 'chess')
                if other and not other.startswith('机器人'):
                    return {
                        'action': 'location_update',
                        'location': 'chess',
                        'send_to_caller': [{'type': 'game', 'text': '已离开房间'}],
                        'send_to_players': {
                            other: [{'type': 'game', 'text': f"{player_name} 离开了房间"}]
                        },
                    }
            lobby.set_player_location(player_name, 'chess')
            return {'action': 'back_to_game', 'location': 'chess', 'message': '已离开房间'}

        # 游戏根位置 → 返回大厅
        if location == 'chess':
            room = self.get_player_room(player_name)
            if room:
                self.leave_room(player_name)
            lobby.set_player_location(player_name, 'lobby')
            return {
                'action': 'location_update',
                'location': 'lobby',
                'message': '已返回游戏大厅。\n输入 /games 查看可用游戏。'
            }

        return None

    def handle_quit(self, lobby, player_name, player_data):
        """处理 /quit 或 /home"""
        location = lobby.get_player_location(player_name)

        if 'playing' in location:
            return '⚠ 对局进行中！请先输入 /resign 认输或 /back 退出。'

        room = self.get_player_room(player_name)
        if room:
            self.leave_room(player_name)

        lobby.set_player_location(player_name, 'lobby')
        return {
            'action': 'location_update',
            'location': 'lobby',
            'message': '已返回游戏大厅。\n输入 /games 查看可用游戏。'
        }

    def get_welcome_message(self, player_data):
        """获取进入国际象棋时的欢迎信息"""
        from server.user_schema import get_rank_name
        chess_data = player_data.get('chess', {})
        rank_name = get_rank_name(chess_data.get('rank', 'novice_1'))
        rank_points = chess_data.get('rank_points', 0)

        return {
            'action': 'location_update',
            'icon': '♟',
            'message': (
                f"────── ♟ 国际象棋 ──────\n\n"
                f"  段位: {rank_name} ({rank_points}pt)\n\n"
                "  /create        创建房间\n"
                "  /rooms         房间列表\n"
                "  /join <ID>     加入房间\n"
                "  /rank          段位详情\n"
                "  /stats         战绩统计\n"
                "  /back          返回大厅\n\n"
                "  输入 /help chess 查看完整说明\n"
            )
        }

    def get_profile_extras(self, player_data):
        """返回个人资料附加行"""
        from server.user_schema import get_rank_name
        chess_data = player_data.get('chess', {})
        rank_name = get_rank_name(chess_data.get('rank', 'novice_1'))
        return f"象棋段位: {rank_name}"

    def get_player_room_data(self, player_name):
        """获取玩家所在房间的数据（用于UI更新）"""
        room = self.get_player_room(player_name)
        if room:
            return room.get_table_data()
        return None

    # ==================== 待确认状态处理 ====================

    def _handle_pending(self, lobby, player_name, player_data, cmd, args, pending):
        """处理引擎内的待确认状态"""
        pending_type = pending[0] if isinstance(pending, tuple) else pending
        pending_data = pending[1] if isinstance(pending, tuple) and len(pending) > 1 else None

        # 创建房间 — 选择段位场/时间控制
        if pending_type == 'create_chess_room':
            self.pending_confirms.pop(player_name, None)
            return self._handle_create_pending(lobby, player_name, player_data, cmd, pending_data)

        # 对局中 /back 确认
        if pending_type == 'back_playing':
            self.pending_confirms.pop(player_name, None)
            if cmd == '/y':
                return self._do_back_confirm(lobby, player_name)
            return '已取消。'

        return None

    def _handle_create_pending(self, lobby, player_name, player_data, cmd, data):
        """处理创建房间的多步交互"""
        from server.user_schema import get_rank_name, get_rank_index

        match_type = data.get('match_type') if data else None
        time_control = data.get('time_control') if data else None

        # 未选段位场 → 等待选择段位场
        if match_type is None:
            match_types = {'/1': 'yuujin', '/2': 'dou', '/3': 'gin',
                           '/4': 'kin', '/5': 'gyoku', '/6': 'ouza'}
            selected = match_types.get(cmd)
            if not selected:
                return f"无效选择 '{cmd}'，请输入 1-6。"

            if selected != 'yuujin':
                chess_rank = player_data.get('chess', {}).get('rank', 'novice_1')
                match_info = ChessRoom.MATCH_TYPES.get(selected, {})
                min_rank = match_info.get('min_rank')
                if min_rank and get_rank_index(chess_rank) < get_rank_index(min_rank):
                    return f"段位不足！{match_info.get('name_cn', '')}需要 {get_rank_name(min_rank)} 以上。"

            # 继续选择时间控制
            self.pending_confirms[player_name] = ('create_chess_room', {
                'match_type': selected,
                'time_control': None
            })
            match_info = ChessRoom.MATCH_TYPES.get(selected, {})
            text = f"✓ 段位场: {match_info.get('name_cn', selected)}\n\n"
            text += "请选择时间控制  (输入编号，/back 取消)\n\n"
            text += "  /1  闪电战    3分+2秒\n"
            text += "  /2  快棋      10分+5秒\n"
            text += "  /3  慢棋      30分+10秒"
            return text

        # 已选段位场，未选时间 → 等待选择时间
        if time_control is None:
            tc_map = {'/1': 'blitz', '/2': 'rapid', '/3': 'classical'}
            selected = tc_map.get(cmd)
            if not selected:
                return f"无效选择 '{cmd}'，请输入 1-3。"

            avatar = player_data.get('avatar')
            is_ranked = match_type != 'yuujin'
            room, error = self.create_room(player_name, time_control=selected, match_type=match_type)
            if error:
                return error

            room.set_player_avatar(player_name, avatar)
            chess_rank = player_data.get('chess', {}).get('rank', 'novice_1')
            room.set_player_rank(player_name, chess_rank)
            lobby.set_player_location(player_name, 'chess_room')

            tc_info = ChessRoom.TIME_CONTROLS.get(selected, {})
            match_info = ChessRoom.MATCH_TYPES.get(match_type, {})
            ranked_tag = ' [段位战]' if is_ranked else ''
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

        return None

    def _do_back_confirm(self, lobby, player_name):
        """确认退出对局（判负）"""
        room = self.get_player_room(player_name)
        if room and room.state == 'playing':
            result, error = room.resign(player_name)
            if result:
                self._cmd_handler._finish_game(lobby, room, result)
        if room:
            self.leave_room(player_name)

        lobby.set_player_location(player_name, 'chess')
        return {'action': 'back_to_game', 'message': '已退出对局，返回国际象棋。'}

    def create_room(self, host_name, time_control='rapid', match_type='yuujin'):
        """创建房间"""
        if host_name in self.player_rooms:
            return None, "你已经在一个房间中了"

        room_id = f"chess_{len(self.rooms) + 1}_{int(time.time()) % 10000}"
        room = ChessRoom(room_id, host_name, time_control=time_control, match_type=match_type)
        self.rooms[room_id] = room
        self.player_rooms[host_name] = room_id
        return room, None

    def get_room(self, room_id):
        return self.rooms.get(room_id)

    def get_player_room(self, player_name):
        room_id = self.player_rooms.get(player_name)
        if room_id:
            return self.rooms.get(room_id)
        return None

    def join_room(self, room_id, player_name):
        if player_name in self.player_rooms:
            return None, "你已经在一个房间中了"

        room = self.rooms.get(room_id)
        if not room:
            return None, "房间不存在"
        if room.is_full():
            return None, "房间已满"
        if room.state != 'waiting':
            return None, "游戏已开始，无法加入"

        pos = room.add_player(player_name)
        if pos >= 0:
            self.player_rooms[player_name] = room_id
            return room, None
        return None, "加入失败"

    def leave_room(self, player_name):
        room_id = self.player_rooms.get(player_name)
        if not room_id:
            return None, "你不在任何房间中"

        room = self.rooms.get(room_id)
        if room:
            room.remove_player(player_name)
            del self.player_rooms[player_name]

            if room.get_player_count() == 0:
                del self.rooms[room_id]
                return None, "已离开房间（房间已解散）"

            # 转移房主
            if room.host == player_name:
                for i in range(2):
                    if room.players[i]:
                        room.host = room.players[i]
                        break

            return room, None

        del self.player_rooms[player_name]
        return None, "已离开房间"

    def remove_room(self, room_id):
        if room_id in self.rooms:
            room = self.rooms[room_id]
            for player in room.players.values():
                if player and player in self.player_rooms:
                    del self.player_rooms[player]
            del self.rooms[room_id]

    def list_rooms(self):
        waiting_rooms = []
        for room_id, room in self.rooms.items():
            if room.state == 'waiting':
                waiting_rooms.append(room.get_status())
        return waiting_rooms

    # ==================== 邀请系统 ====================

    def send_invite(self, from_name, to_name, room_id):
        self.invites[to_name] = {
            'from': from_name,
            'room_id': room_id,
            'time': time.time()
        }

    def get_invite(self, player_name):
        invite = self.invites.get(player_name)
        if invite:
            if time.time() - invite['time'] < 300:
                return invite
            else:
                del self.invites[player_name]
        return None

    def clear_invite(self, player_name):
        if player_name in self.invites:
            del self.invites[player_name]
