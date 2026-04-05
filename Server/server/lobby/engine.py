"""游戏大厅指令引擎"""

from __future__ import annotations

import threading

from ..config import COMMAND_TABLE, LOCATION_HIERARCHY
from ..config import DEFAULT_LOCATION
from .confirmation import handle_lobby_pending
from .command_registry import find_global_handler
from . import help as lobby_help
from ..games import get_game, GAMES


class LobbyEngine:
    """游戏大厅指令引擎

    多线程环境下由 ChatServer 的各 client handler 线程并发调用，
    通过 _lock 保护共享状态的逻辑一致性。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.game_engines = {}  # 各游戏的引擎实例
        self.player_locations = {}  # {player_name: location}
        self.online_players = {}  # {player_name: player_data}
        self.invite_callback = None  # 邀请回调函数
        self.pending_confirms = {}  # 大厅级待确认 {player_name: {'type':..., 'data':...}}
        self._help_viewers: set[str] = set()  # 正在查看帮助文档的玩家

    def set_invite_callback(self, callback):
        """设置邀请通知回调"""
        self.invite_callback = callback

    def register_player(self, player_name, player_data):
        """注册在线玩家 — 恢复上次位置"""
        with self._lock:
            self.online_players[player_name] = player_data
            saved_location = player_data.get('world', {}).get('location', DEFAULT_LOCATION)
            self.player_locations[player_name] = saved_location
            self.pending_confirms.pop(player_name, None)
            # 自动初始化世界引擎并加载玩家位置
            self._ensure_engine('world', player_name)

    def unregister_player(self, player_name):
        """注销玩家，返回需要通知的房间信息列表"""
        with self._lock:
            notifications = []

            # 委托引擎处理断线
            game_id = self._get_game_for_location(
                self.get_player_location(player_name))
            if game_id:
                engine = self._get_engine(game_id, player_name)
                if engine:
                    notifications = engine.handle_disconnect(self, player_name)
                # per_player 引擎断线后清除实例
                info = self._get_game_info(game_id)
                if info.get('per_player'):
                    self.game_engines.pop(f'{game_id}_{player_name}', None)

            self.pending_confirms.pop(player_name, None)
            self._help_viewers.discard(player_name)
            self.player_locations.pop(player_name, None)
            self.online_players.pop(player_name, None)
            return notifications

    def get_player_location(self, player_name):
        """获取玩家当前位置"""
        return self.player_locations.get(player_name, DEFAULT_LOCATION)

    def set_player_location(self, player_name, location):
        """设置玩家位置"""
        self.player_locations[player_name] = location

    # ── 布局校验 ──

    def _validate_layout(self, data, depth=0):
        """白名单校验布局 JSON，防止注入"""
        if depth > 10:
            return False
        if not isinstance(data, dict):
            return False
        t = data.get('type')
        if t == 'pane':
            mod = data.get('module')
            pid = data.get('id')
            if mod is not None and not isinstance(mod, str):
                return False
            if pid is not None and not isinstance(pid, str):
                return False
            return True
        children = data.get('children')
        weights = data.get('weights')
        if not isinstance(children, list):
            return False
        if weights is not None and not isinstance(weights, list):
            return False
        return all(self._validate_layout(c, depth + 1) for c in children)

    # ── 位置工具 ──

    def get_location_path(self, location, player_name=None):
        """获取位置的完整路径（面包屑导航）
        
        当提供 player_name 且玩家在房间中时，自动附加房间号。
        """
        path = []
        path_keys = []
        current = location
        while current:
            info = LOCATION_HIERARCHY.get(current)
            if info:
                path.append(info[0])
                path_keys.append(current)
                current = info[1]
            else:
                path.append(current)
                path_keys.append(current)
                break
        path.reverse()
        path_keys.reverse()
        if not path:
            return 'HOME'
        # 附加地图名到世界根位置（用城镇地图的 meta.name 替代层级定义）
        if player_name and path_keys and path_keys[0].startswith('world_'):
            game_id = self._get_game_for_location(location)
            if game_id:
                engine = self._get_engine(game_id, player_name)
                if engine and hasattr(engine, 'get_status_extras'):
                    pdata = self.online_players.get(player_name, {})
                    extras = engine.get_status_extras(player_name, pdata)
                    if extras:
                        # 建筑内: 用保存的城镇名; 户外: 用当前地图名
                        if len(path) > 1 and extras.get('town_map_name'):
                            path[0] = extras['town_map_name']
                        elif extras.get('world_map'):
                            path[0] = extras['world_map']
        # 附加房间号到"房间"层级
        if player_name and location and ('_room' in location or '_playing' in location):
            game_id = self._get_game_for_location(location)
            if game_id:
                engine = self._get_engine(game_id, player_name)
                if engine:
                    room = engine.get_player_room(player_name)
                    if room and hasattr(room, 'room_id'):
                        for i, key in enumerate(path_keys):
                            if '_room' in key:
                                path[i] = f"{path[i]}#{room.room_id}"
                                break
        return ' > '.join(path)

    def get_parent_location(self, location):
        """获取父位置"""
        info = LOCATION_HIERARCHY.get(location)
        if info:
            return info[1] or DEFAULT_LOCATION
        return DEFAULT_LOCATION

    def get_online_player_names(self):
        """获取在线玩家名列表"""
        return list(self.online_players.keys())

    def get_commands_for_location(self, location: str, player_data: dict | None = None) -> list[dict]:
        """获取指定位置的全部可用指令（动态注入子菜单）

        优先使用游戏引擎的 get_commands() 动态指令，
        未实现则 fallback 到静态 COMMAND_TABLE。
        """
        import copy
        global_cmds = copy.deepcopy(COMMAND_TABLE.get('*', []))

        # 根位置（parent=None）过滤无意义的导航指令
        loc_info = LOCATION_HIERARCHY.get(location)
        if loc_info and loc_info[1] is None:
            global_cmds = [c for c in global_cmds if c.get('name') != 'home']

        # 世界地图内隐藏 back，必须通过门移动
        if location.startswith('world_') or location.startswith('building_'):
            global_cmds = [c for c in global_cmds if c.get('name') != 'back']

        # 尝试引擎动态指令
        game_id = self._get_game_for_location(location)
        dynamic = None
        if game_id and player_data:
            engine = self._get_engine(game_id, player_data.get('name'))
            if engine:
                dynamic = engine.get_commands(
                    self, location, player_data.get('name', ''), player_data)

        if dynamic is not None:
            game_cmds = dynamic
        else:
            game_cmds = copy.deepcopy(COMMAND_TABLE.get(location, []))

        # 位置指令覆盖同名全局指令
        loc_names = {c.get('name') for c in game_cmds if c.get('name')}
        global_filtered = [c for c in global_cmds if c.get('name') not in loc_names]

        # 在游戏中时，游戏标签页在前；大厅中时，全局在前
        if game_id:
            commands = game_cmds + global_filtered
        else:
            commands = global_filtered + game_cmds

        if player_data:
            self._inject_sub_menus(commands, player_data)
        return commands

    def _inject_sub_menus(self, commands: list[dict], player_data: dict):
        """为需要子菜单的指令动态注入 sub（注册表驱动）"""
        from .command_registry import find_sub_builder
        for cmd in commands:
            builder = find_sub_builder(cmd.get('name', ''))
            if builder:
                cmd['sub'] = builder(self, player_data)

    # ── 游戏路由 helpers ──

    def _get_game_for_location(self, location):
        """根据位置确定玩家在哪个游戏中"""
        for game_id, module in GAMES.items():
            info = getattr(module, 'GAME_INFO', {})
            if location in info.get('locations', {}):
                return game_id
        # 后备: 根据前缀
        for game_id in GAMES:
            if location.startswith(game_id):
                return game_id
        return None

    def _get_game_info(self, game_id):
        """获取游戏的GAME_INFO"""
        module = GAMES.get(game_id)
        if module:
            return getattr(module, 'GAME_INFO', {})
        return {}

    def _get_engine(self, game_id, player_name=None):
        """获取游戏引擎实例（per_player 用带玩家名的 key）"""
        info = self._get_game_info(game_id)
        if info.get('per_player'):
            return self.game_engines.get(f'{game_id}_{player_name}')
        return self.game_engines.get(game_id)

    def _ensure_engine(self, game_id, player_name=None):
        """确保引擎存在，不存在则创建"""
        info = self._get_game_info(game_id)
        if info.get('per_player'):
            key = f'{game_id}_{player_name}'
        else:
            key = game_id

        if key not in self.game_engines:
            create = info.get('create_engine')
            if create:
                self.game_engines[key] = create()

        return self.game_engines.get(key)

    # ── 帮助 / 列表  → lobby_help.py ──

    def get_main_help(self):
        return lobby_help.get_main_help()

    def get_game_help(self, game_id, page=None):
        return lobby_help.get_game_help(game_id, page)

    def get_games_list(self):
        return lobby_help.get_games_list()

    # ── 核心指令处理 ──

    def process_command(self, player_data, command):
        """处理指令"""
        with self._lock:
            return self._process_command_unlocked(player_data, command)

    def _process_command_unlocked(self, player_data, command):
        """处理指令（内部，已持有锁）"""
        player_name = player_data['name']
        parts = command.strip().split(None, 1)
        cmd = parts[0].lower() if parts else ''
        args = parts[1] if len(parts) > 1 else ''
        location = self.get_player_location(player_name)

        # ── 1. 大厅级待确认状态 ──
        pending = self.pending_confirms.get(player_name)
        if pending:
            result = handle_lobby_pending(
                self, player_name, player_data, cmd, command, pending)
            if result is not None:
                return result

        # ── 2. 全局指令（注册表驱动，任何位置有效）──
        global_handler = find_global_handler(cmd)
        if global_handler is not None:
            return global_handler(self, player_name, player_data, args, location)

        # ── 3. 导航指令 /home, /back ──
        if cmd == '/home':
            self._help_viewers.discard(player_name)
            return self._handle_navigation(player_name, player_data, location)
        if cmd == '/back':
            return self._handle_back(player_name, player_data, location)

        # ── 4. 游戏内指令路由 ──
        game_id = self._get_game_for_location(location)
        if game_id:
            engine = self._get_engine(game_id, player_name)
            if engine:
                # 其他游戏指令
                result = engine.handle_command(
                    self, player_name, player_data, cmd, args)
                if result is not None:
                    return result
            return '未知指令。'

        if not cmd.startswith('/'):
            return None

        return '未知指令。'

    # ── 进入游戏 ──

    def _handle_back(self, player_name, player_data, location):
        """处理 /back — 逐级返回（帮助查看中则恢复游戏面板）"""
        if player_name in self._help_viewers:
            self._help_viewers.discard(player_name)
            game_id = self._get_game_for_location(location)
            if game_id:
                engine = self._get_engine(game_id, player_name)
                if engine:
                    from ..msg_types import ROOM_UPDATE
                    rd = engine.get_player_room_data(player_name)
                    if not rd:
                        # lobby 位置：恢复欢迎页
                        from .help import get_help_welcome
                        rd = {'game_type': game_id, 'room_state': 'lobby'}
                        rd['doc'] = get_help_welcome(game_id) or getattr(engine, '_HELP_TEXT', '')
                    return {
                        'send_to_caller': [{'type': ROOM_UPDATE, 'room_data': rd}],
                        'refresh_commands': True,
                    }
        game_id = self._get_game_for_location(location)
        if game_id:
            engine = self._get_engine(game_id, player_name)
            if engine:
                result = engine.handle_back(self, player_name, player_data)
                # 跨游戏过渡: 离开当前游戏后落在另一个游戏内，重新进入父游戏
                new_loc = self.get_player_location(player_name)
                new_game = self._get_game_for_location(new_loc)
                if new_game and new_game != game_id:
                    return self._enter_game(player_name, player_data, new_game)
                return result
        return '无法再返回了。'

    def _handle_navigation(self, player_name, player_data, location):
        """处理 /home 导航"""
        root = LOCATION_HIERARCHY.get(location)
        if root and root[1] is None:
            return '你已经在城镇中了。'

        # 游戏内：委托引擎处理
        game_id = self._get_game_for_location(location)
        if game_id:
            engine = self._get_engine(game_id, player_name)
            if engine:
                result = engine.handle_quit(self, player_name, player_data)
                # 跨游戏过渡: 离开后落在另一个游戏内
                new_loc = self.get_player_location(player_name)
                new_game = self._get_game_for_location(new_loc)
                if new_game and new_game != game_id:
                    return self._enter_game(player_name, player_data, new_game)
                return result

        # 非游戏位置：直接回城镇
        self.set_player_location(player_name, DEFAULT_LOCATION)
        return {
            'action': 'location_update',
            'send_to_caller': [{'type': 'game', 'text': f"已返回{self.get_location_path(DEFAULT_LOCATION)}。"}],
            'location': DEFAULT_LOCATION,
        }

    def _enter_game(self, player_name, player_data, game_id):
        """通用进入游戏"""
        game_module = get_game(game_id)
        if not game_module:
            return f"未找到游戏: {game_id}"

        engine = self._ensure_engine(game_id, player_name)
        if not engine:
            return f"游戏引擎初始化失败: {game_id}"

        info = self._get_game_info(game_id)

        # 设置位置 — 如果当前已在该游戏的某个子位置，保留；否则用根位置
        locations = info.get('locations', {})
        current_loc = self.get_player_location(player_name)
        if current_loc not in locations:
            root_location = game_id  # 默认
            for loc_key, (_, parent) in locations.items():
                if parent is None or parent not in locations:
                    root_location = loc_key
                    break
            self.set_player_location(player_name, root_location)

        # 获取欢迎信息
        result = engine.get_welcome_message(player_data)
        if isinstance(result, dict):
            # 确保客户端收到 location 更新
            if 'location' not in result:
                result['location'] = root_location
        return result

    # ── 背包/头衔指令 ──  → lobby/title_commands.py
    # ── 大厅级待确认处理 ──  → confirmation.py

    # ── 通用服务 ──

    def _track_invite(self, player_name, player_data):
        """记录邀请统计并检查头衔"""
        from ..player.manager import PlayerManager
        from ..systems.titles import check_all_titles

        social_stats = player_data.get('social_stats', {})
        social_stats['invites_sent'] = social_stats.get('invites_sent', 0) + 1
        player_data['social_stats'] = social_stats

        check_all_titles(player_data)
        PlayerManager.save_player_data(player_name, player_data)

    def get_player_room_data(self, player_name):
        """获取玩家所在房间的数据（用于UI更新）— 通用"""
        location = self.get_player_location(player_name)
        game_id = self._get_game_for_location(location)
        if game_id:
            engine = self._get_engine(game_id, player_name)
            if engine:
                return engine.get_player_room_data(player_name)
        return None


