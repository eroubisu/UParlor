"""
麻将游戏引擎 - 房间管理
实现 GameEngine 标准接口
"""

import time
from .room import MahjongRoom
from .command_handler import MahjongCommandHandler


class MahjongEngine:
    """麻将游戏引擎 - 管理所有房间"""
    
    def __init__(self, game_data):
        self.game_data = game_data
        self.rooms = {}  # {room_id: MahjongRoom}
        self.player_rooms = {}  # {player_name: room_id} 玩家所在房间
        self.invites = {}  # {target_name: {'from': host, 'room_id': room_id, 'time': timestamp}}
        self.pending_confirms = {}  # {player_name: (type, data)} 游戏内待确认状态
        self._cmd_handler = MahjongCommandHandler(self)

    # ==================== 标准接口 ====================

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        """处理麻将指令（含待确认状态）"""
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

        members = [p for p in room.players.values()
                   if p and isinstance(p, str) and p != player_name
                   and not p.startswith('机器人')]
        self.leave_room(player_name)
        for m in members:
            notifications.append({
                'send_to_players': {
                    m: [{'type': 'game', 'text': f"{player_name} 离开了房间（下线）"}]
                }
            })
        return notifications

    def handle_back(self, lobby, player_name, player_data):
        """处理 /back"""
        location = lobby.get_player_location(player_name)

        # 对局中 → 确认提示
        if location == 'mahjong_playing':
            room = self.get_player_room(player_name)
            if room and room.state == 'playing':
                self.pending_confirms[player_name] = ('back_playing', None)
                return {
                    'action': 'confirm_prompt',
                    'message': '⚠ 游戏进行中！确定要退出吗？（会被记为逃跑）\n输入 /y 确认，其他任意键取消。'
                }

        # 房间中 → 离开房间
        if location == 'mahjong_room':
            room = self.get_player_room(player_name)
            if room:
                members = [p for p in room.players.values()
                           if p and isinstance(p, str) and p != player_name
                           and not p.startswith('机器人')]
                self.leave_room(player_name)
                lobby.set_player_location(player_name, 'mahjong')
                return {
                    'action': 'location_update',
                    'location': 'mahjong',
                    'send_to_caller': [{'type': 'game', 'text': '已返回房间。'}],
                    'send_to_players': {
                        m: [{'type': 'game', 'text': f"{player_name} 离开了房间"}]
                        for m in members
                    },
                }
            lobby.set_player_location(player_name, 'mahjong')
            return {'action': 'back_to_game', 'location': 'mahjong', 'message': '已离开房间'}

        # 游戏根位置 → 返回大厅
        if location == 'mahjong':
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

        if location == 'mahjong_playing':
            room = self.get_player_room(player_name)
            if room and room.state == 'playing':
                self.pending_confirms[player_name] = ('quit_playing', None)
                return {
                    'action': 'confirm_prompt',
                    'message': '⚠ 游戏进行中！确定要退出吗？（会被记为逃跑）\n输入 /y 确认，其他任意键取消。'
                }

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
        """获取进入麻将时的欢迎信息"""
        from server.user_schema import get_rank_name
        mahjong_data = player_data.get('mahjong', {})
        rank_name = get_rank_name(mahjong_data.get('rank', 'novice_1'))
        rank_points = mahjong_data.get('rank_points', 0)

        return {
            'action': 'location_update',
            'icon': '🀄',
            'message': (
                f"────── 🀄 麻将 ──────\n\n"
                f"  段位: {rank_name} ({rank_points}pt)\n\n"
                "  /create        创建房间\n"
                "  /rooms         房间列表\n"
                "  /join <ID>     加入房间\n"
                "  /rank          段位详情\n"
                "  /stats         战绩统计\n"
                "  /back          返回大厅\n\n"
                "  输入 /help mahjong 查看完整说明\n"
            )
        }

    def get_profile_extras(self, player_data):
        """返回个人资料附加行"""
        from server.user_schema import get_rank_name
        mahjong_data = player_data.get('mahjong', {})
        rank_name = get_rank_name(mahjong_data.get('rank', 'novice_1'))
        return f"麻将段位: {rank_name}"

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

        # 创建房间 — 选择段位场/游戏模式
        if pending_type == 'create_room':
            self.pending_confirms.pop(player_name, None)
            return self._handle_create_pending(lobby, player_name, player_data, cmd, pending_data)

        # 游戏模式选择
        if pending_type == 'game_mode':
            self.pending_confirms.pop(player_name, None)
            return self._handle_game_mode_pending(lobby, player_name, player_data, cmd, pending_data)

        # 对局中 /back 确认
        if pending_type == 'back_playing':
            self.pending_confirms.pop(player_name, None)
            if cmd == '/y':
                return self._do_back_confirm(lobby, player_name)
            return '已取消。'

        # 对局中 /quit 确认
        if pending_type == 'quit_playing':
            self.pending_confirms.pop(player_name, None)
            if cmd == '/y':
                return self._do_quit_confirm(lobby, player_name)
            return '已取消。'

        return None

    def _handle_create_pending(self, lobby, player_name, player_data, cmd, data):
        """处理创建房间 — 选择段位场"""
        from server.user_schema import get_rank_name, get_rank_index

        game_mode = data.get('game_mode') if data else None
        match_type = data.get('match_type') if data else None

        # 未选段位场 → 等待选择
        if match_type is None:
            if not cmd.startswith('/'):
                return '已取消。'
            match_types = {'/1': 'yuujin', '/2': 'dou', '/3': 'gin',
                           '/4': 'kin', '/5': 'gyoku', '/6': 'ouza'}
            selected = match_types.get(cmd)
            if not selected:
                return f"无效选择 '{cmd}'，请输入 1-6。"

            if selected != 'yuujin':
                match_info = MahjongRoom.MATCH_TYPES.get(selected, {})
                min_rank = match_info.get('min_rank')
                if min_rank:
                    mahjong_data = player_data.get('mahjong', {})
                    player_rank = mahjong_data.get('rank', 'novice_1')
                    if get_rank_index(player_rank) < get_rank_index(min_rank):
                        return f"段位不足！\n{match_info.get('name_cn', '')}需要 {get_rank_name(min_rank)} 以上。"

            # 如果已有 game_mode，直接创建
            if game_mode:
                return self._create_room_final(lobby, player_name, player_data, game_mode, selected)

            # 继续选择游戏模式
            is_ranked = selected != 'yuujin'
            self.pending_confirms[player_name] = ('game_mode', {
                'match_type': selected,
                'ranked': is_ranked
            })
            msg = f"已选择: {selected}\n\n"
            msg += "请选择游戏模式:  (输入编号，或其他任意指令取消)\n\n"
            msg += "  1. tonpu (東風戦/东风战) - 4局\n"
            msg += "  2. hanchan (半荘戦/半庄战) - 8局"
            return msg

        # 已选段位场，未选模式 → 等待选择模式
        if game_mode is None:
            # 继续选择游戏模式
            self.pending_confirms[player_name] = ('game_mode', {
                'match_type': match_type,
                'ranked': match_type != 'yuujin'
            })
            msg = f"已选择: {match_type}\n\n"
            msg += "请选择游戏模式:  (输入编号，或其他任意指令取消)\n\n"
            msg += "  1. tonpu (東風戦/东风战) - 4局\n"
            msg += "  2. hanchan (半荘戦/半庄战) - 8局"
            return msg

        return None

    def _handle_game_mode_pending(self, lobby, player_name, player_data, cmd, data):
        """处理创建房间 — 选择游戏模式"""
        modes = {'/1': 'tonpu', '/2': 'hanchan'}
        game_mode = modes.get(cmd)
        if not game_mode:
            return f"无效选择 '{cmd}'，请输入 1 或 2。"

        match_type = data.get('match_type', 'yuujin') if data else 'yuujin'
        return self._create_room_final(lobby, player_name, player_data, game_mode, match_type)

    def _create_room_final(self, lobby, player_name, player_data, game_mode, match_type):
        """最终创建房间"""
        avatar = player_data.get('avatar')
        room, error = self.create_room(player_name, game_mode=game_mode, match_type=match_type)
        if error:
            return error
        if avatar:
            room.set_player_avatar(player_name, avatar)

        player_rank = player_data.get('mahjong', {}).get('rank', 'novice_1')
        room.set_player_rank(player_name, player_rank)
        lobby.set_player_location(player_name, 'mahjong_room')

        match_info = MahjongRoom.MATCH_TYPES.get(match_type, {})
        mode_info = MahjongRoom.GAME_MODES.get(game_mode, {})
        is_ranked = match_info.get('ranked', False)

        msg = f"\n房间创建成功！\n\n房间ID: {room.room_id}"
        msg += f"\n段位场: {match_info.get('name_cn', '友人场')}"
        msg += f"\n模式: {mode_info.get('name_cn', '半庄战')}"
        if is_ranked:
            msg += "\n类型: 段位战"
        msg += f"\n你的位置: 东（房主）\n\n【邀请其他玩家】\n  /invite @玩家名  - 邀请在线玩家\n\n【等待中...】 {room.get_player_count()}/4\n"

        return {
            'action': 'mahjong_room_update',
            'message': msg,
            'room_data': room.get_table_data()
        }

    def _do_back_confirm(self, lobby, player_name):
        """确认退出对局"""
        room = self.get_player_room(player_name)
        if room:
            self.leave_room(player_name)

        lobby.set_player_location(player_name, 'mahjong')
        return {'action': 'back_to_game', 'message': '已退出对局，返回麻将游戏。'}

    def _do_quit_confirm(self, lobby, player_name):
        """确认退出对局并返回大厅"""
        room = self.get_player_room(player_name)
        if room:
            self.leave_room(player_name)

        lobby.set_player_location(player_name, 'lobby')
        return {
            'action': 'location_update',
            'location': 'lobby',
            'message': '已退出对局，返回游戏大厅。\n输入 /games 查看可用游戏。'
        }
    
    def create_room(self, host_name, game_mode='hanchan', match_type='yuujin'):
        """创建房间
        
        Args:
            host_name: 房主名称
            game_mode: 游戏模式 'tonpu'=东风战, 'hanchan'=半庄战
            match_type: 段位场类型 'yuujin'=友人场, 'dou'=铜之间, etc.
            
        Returns:
            (room, error): 房间对象和错误信息
        """
        if host_name in self.player_rooms:
            return None, "你已经在一个房间中了"
        
        room_id = f"room_{len(self.rooms) + 1}_{int(time.time()) % 10000}"
        room = MahjongRoom(room_id, host_name, game_mode=game_mode, match_type=match_type)
        self.rooms[room_id] = room
        self.player_rooms[host_name] = room_id
        return room, None
    
    def get_room(self, room_id):
        """获取房间"""
        return self.rooms.get(room_id)
    
    def get_player_room(self, player_name):
        """获取玩家所在房间"""
        room_id = self.player_rooms.get(player_name)
        if room_id:
            return self.rooms.get(room_id)
        return None
    
    def join_room(self, room_id, player_name):
        """加入房间"""
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
        """离开房间"""
        room_id = self.player_rooms.get(player_name)
        if not room_id:
            return None, "你不在任何房间中"
        
        room = self.rooms.get(room_id)
        if room:
            room.remove_player(player_name)
            del self.player_rooms[player_name]
            
            # 房间空了就删除
            if room.get_player_count() == 0:
                del self.rooms[room_id]
                return None, "已离开房间（房间已解散）"
            
            # 转移房主
            if room.host == player_name:
                for i in range(4):
                    if room.players[i]:
                        room.host = room.players[i]
                        break
            
            return room, None
        
        del self.player_rooms[player_name]
        return None, "已离开房间"
    
    def remove_room(self, room_id):
        """删除房间"""
        if room_id in self.rooms:
            room = self.rooms[room_id]
            for player in room.players.values():
                if player and player in self.player_rooms:
                    del self.player_rooms[player]
            del self.rooms[room_id]
    
    def list_rooms(self):
        """列出所有等待中的房间"""
        waiting_rooms = []
        for room_id, room in self.rooms.items():
            if room.state == 'waiting':
                waiting_rooms.append(room.get_status())
        return waiting_rooms
    
    # ==================== 邀请系统 ====================
    
    def send_invite(self, from_name, to_name, room_id):
        """发送邀请"""
        self.invites[to_name] = {
            'from': from_name,
            'room_id': room_id,
            'time': time.time()
        }
    
    def get_invite(self, player_name):
        """获取玩家收到的邀请（5分钟过期）"""
        invite = self.invites.get(player_name)
        if invite:
            if time.time() - invite['time'] < 300:
                return invite
            else:
                del self.invites[player_name]
        return None
    
    def clear_invite(self, player_name):
        """清除邀请"""
        if player_name in self.invites:
            del self.invites[player_name]
