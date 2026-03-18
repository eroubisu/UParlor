"""游戏大厅指令引擎"""

from ..config import COMMAND_TABLE, LOCATION_HIERARCHY, SERVER_VERSION
from .confirmation import handle_lobby_pending
from .command_registry import find_global_handler
from . import help as lobby_help
from ..games import get_game, get_all_games, GAMES


class LobbyEngine:
    """游戏大厅指令引擎"""

    def __init__(self):
        self.game_engines = {}  # 各游戏的引擎实例
        self.player_locations = {}  # {player_name: location}
        self.online_players = {}  # {player_name: player_data}
        self.invite_callback = None  # 邀请回调函数
        self.pending_confirms = {}  # 大厅级待确认 {player_name: {'type':..., 'data':...}}

    def set_invite_callback(self, callback):
        """设置邀请通知回调"""
        self.invite_callback = callback

    def register_player(self, player_name, player_data):
        """注册在线玩家 — 默认进入世界城镇"""
        self.online_players[player_name] = player_data
        self.player_locations[player_name] = 'world_town'
        self.pending_confirms.pop(player_name, None)
        # 自动初始化世界引擎并加载玩家位置
        self._ensure_engine('world', player_name)

    def unregister_player(self, player_name):
        """注销玩家，返回需要通知的房间信息列表"""
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
        self.player_locations.pop(player_name, None)
        self.online_players.pop(player_name, None)
        return notifications

    def get_player_location(self, player_name):
        """获取玩家当前位置"""
        return self.player_locations.get(player_name, 'world_town')

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
        # 附加地图名到世界根位置
        if player_name:
            game_id = self._get_game_for_location(location)
            if game_id:
                engine = self._get_engine(game_id, player_name)
                if engine and hasattr(engine, 'get_status_extras'):
                    extras = engine.get_status_extras(player_name,
                        self.online_players.get(player_name, {}))
                    map_name = extras.get('world_map') if extras else None
                    if map_name:
                        path[0] = map_name
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
            return info[1] or 'world_town'
        return 'world_town'

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

        # 在游戏中时，游戏标签页在前；大厅中时，全局在前
        if game_id:
            commands = game_cmds + global_cmds
        else:
            commands = global_cmds + game_cmds

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

    # ══════════════════════════════════════════════════
    #  核心指令处理
    # ══════════════════════════════════════════════════

    def process_command(self, player_data, command):
        """处理指令"""
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

        # ── 3. 导航指令 /back, /home ──
        if cmd in ('/back', '/home'):
            return self._handle_navigation(player_name, player_data, cmd, location)

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

    def _handle_navigation(self, player_name, player_data, cmd, location):
        """统一处理 /back 和 /home 导航"""
        # 城镇根位置是最顶层
        root = LOCATION_HIERARCHY.get(location)
        if root and root[1] is None:
            return '你已经在城镇中了。'

        # 游戏内：委托引擎处理（引擎可能需要清理房间等）
        game_id = self._get_game_for_location(location)
        if game_id:
            engine = self._get_engine(game_id, player_name)
            if engine:
                if cmd == '/back':
                    return engine.handle_back(self, player_name, player_data)
                return engine.handle_quit(self, player_name, player_data)

        # 非游戏位置：按层级回退
        if cmd == '/home':
            self.set_player_location(player_name, 'world_town')
            return {
                'action': 'location_update',
                'message': f"已返回{self.get_location_path('world_town')}。"
            }
        parent = self.get_parent_location(location)
        self.set_player_location(player_name, parent)
        return {
            'action': 'location_update',
            'message': f"已返回{self.get_location_path(parent)}。"
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

        # 设置位置 — 用游戏根位置
        locations = info.get('locations', {})
        root_location = game_id  # 默认
        for loc_key in locations:
            parent = locations[loc_key][1]
            if parent == 'lobby':
                root_location = loc_key
                break
        self.set_player_location(player_name, root_location)

        # 获取欢迎信息
        result = engine.get_welcome_message(player_data)
        # 确保客户端收到 location 更新
        if isinstance(result, dict) and 'location' not in result:
            result['location'] = root_location
        return result

    # ── 背包/头衔指令 ──  → title_commands.py
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


