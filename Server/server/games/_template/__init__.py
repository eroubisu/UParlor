"""
游戏模块模板 — 复制此目录并替换所有 TODO 标记

注册步骤:
  1. 复制 _template/ → games/your_game/
  2. 替换所有 TODO
  3. 在 games/__init__.py 添加:
       from . import your_game
       register_game('your_game', your_game)
  4. 创建 commands.json 定义游戏指令
  5. (可选) 创建 items.json / ranks.json / titles.json
"""

from .engine import GameEngine as _Engine  # noqa: F401

GAME_INFO = {
    'id': 'TODO_game_id',           # 唯一标识符（英文小写）
    'name': 'TODO 游戏名称',         # 显示名称
    'icon': '?',                     # 单字符图标
    'per_player': False,             # True=每玩家独立引擎, False=共享房间引擎
    'create_engine': _Engine,        # 引擎类（框架自动实例化）
    # 'locations': {                 # 位置层级（per_player 游戏需要）
    #     'game_main': ('主界面', None),
    # },
}
