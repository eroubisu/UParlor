"""开放世界地图渲染器

收到 room_data(game_type='world') 后：
  1. 从 room_data['map'] 读取可见区域瓦片
  2. 渲染瓦片网格 + NPC + 玩家位置
  3. 荒野/越界区域使用字符密度渐变（█▓▒░）按到地图边界距离淡出
  4. 显示门口提示
"""

from __future__ import annotations

from rich.text import Text
from rich.console import RenderableType

from ...protocol.renderer import register_renderer

# 荒野区域统一字符和颜色（最淡的一档）
_FADE_CHAR = '░'
_FADE_COLOR = '#404040'

_DOC_COMMANDS = {
    'h', 'j', 'k', 'l', 'enter', 'interact', 'fish', 'pull',
    'recall', 'talk', 'user', 'buy', 'sell', 'forge', 'brew',
    'rest', 'rumor', 'play', 'back', 'help',
}


class WorldRenderer:
    """开放世界地图渲染器"""

    game_type = 'world'
    no_scroll = True
    server_viewport = True

    def render_board(self, room_data: dict) -> RenderableType:
        """构建地图 Text 对象

        服务端 get_visible_region 已将玩家置于视口中央（player_vy ≈ view_h//2），
        CSS content-align: center middle 将视口中央行对齐到面板中央，
        因此玩家始终在面板正中。客户端不做二次裁剪。
        """
        # /help 仅有 doc 字段时，渲染帮助文档
        doc = room_data.get('doc')
        if doc and not room_data.get('map'):
            from ...protocol.renderer import render_doc
            return render_doc(doc, _DOC_COMMANDS)

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

        # 隐蔽状态: 自己半透明
        concealed = map_view.get('concealed', False)

        # 逐行构建
        result = Text()
        for vy, row in enumerate(tiles):
            if vy > 0:
                result.append("\n")
            for vx, char in enumerate(row):
                if vx == player_vx and vy == player_vy:
                    if concealed:
                        result.append("@", style="dim #808080")
                    else:
                        result.append("@", style="bold #ffffff")
                elif (other := player_at.get((vx, vy))):
                    rel = other.get('rel', '')
                    if rel == 'friend':
                        result.append("@", style="bold #6ac8a0")
                    else:
                        result.append("@", style="#c0b0a0")
                elif (npc := npc_at.get((vx, vy))):
                    result.append(npc['char'],
                                  style=f"bold {npc['color']}")
                elif char == ' ':
                    result.append(_FADE_CHAR, style=_FADE_COLOR)
                else:
                    tile_info = tile_types.get(char)
                    if tile_info:
                        if tile_info.get('fade'):
                            result.append(_FADE_CHAR, style=_FADE_COLOR)
                        else:
                            result.append(
                                tile_info.get('char', char),
                                style=tile_info.get('color', '#808080'))
                    else:
                        result.append(_FADE_CHAR, style=_FADE_COLOR)

        return result


# 自动注册
register_renderer(WorldRenderer())
