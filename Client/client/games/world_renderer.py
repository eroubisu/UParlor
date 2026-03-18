"""开放世界地图渲染器

收到 room_data(game_type='world') 后：
  1. 从 room_data['map'] 读取可见区域瓦片
  2. 渲染瓦片网格 + NPC + 玩家位置
  3. 显示门口提示
"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ..protocol.renderer import register_renderer


class WorldRenderer:
    """开放世界地图渲染器"""

    game_type = 'world'

    def render_board(self, room_data: dict) -> RenderableType:
        """构建地图 Text 对象

        服务端 get_visible_region 已将玩家置于视口中央（player_vy ≈ view_h//2），
        CSS content-align: center middle 将视口中央行对齐到面板中央，
        因此玩家始终在面板正中。客户端不做二次裁剪。
        """
        map_view = room_data.get('map')
        if not map_view:
            return Text("地图加载中...", style="#808080")

        tiles = map_view.get('tiles', [])
        tile_types = map_view.get('tile_types', {})
        player_vx = map_view.get('player_vx', 0)
        player_vy = map_view.get('player_vy', 0)
        npcs = map_view.get('npcs', [])

        # NPC 位置快查表
        npc_at: dict[tuple[int, int], dict] = {}
        for npc in npcs:
            npc_at[(npc['x'], npc['y'])] = npc

        # 其他玩家位置快查表
        players = map_view.get('players', [])
        player_at: dict[tuple[int, int], dict] = {}
        for p in players:
            player_at[(p['x'], p['y'])] = p

        # 逐行构建
        result = Text()
        for vy, row in enumerate(tiles):
            if vy > 0:
                result.append("\n")
            for vx, char in enumerate(row):
                if vx == player_vx and vy == player_vy:
                    result.append("@", style="bold #ffffff")
                elif (other := player_at.get((vx, vy))):
                    rel = other.get('rel', '')
                    if rel == 'friend':
                        result.append("@", style="bold #6ac8a0")
                    else:
                        result.append("@", style="#c0b0a0")
                elif (npc := npc_at.get((vx, vy))):
                    result.append(npc['char'], style=f"bold {npc['color']}")
                else:
                    tile_info = tile_types.get(char)
                    if tile_info:
                        result.append(tile_info.get('char', char),
                                      style=tile_info.get('color', '#808080'))
                    else:
                        result.append(char, style="#808080")

        # 门口提示
        door = room_data.get('door')
        if door:
            result.append(f"\n [{door['name']}] /enter 进入", style="#b8b8b8")

        return result


# 自动注册
register_renderer(WorldRenderer())
