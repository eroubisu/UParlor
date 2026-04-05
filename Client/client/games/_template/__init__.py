"""
客户端游戏模板 — 复制整个 _template/ 目录并重命名

注册步骤:
  1. 复制 _template/ → games/your_game/
  2. 替换 renderer.py 和 handler.py 中的所有 TODO
  3. 在 games/__init__.py 添加:
       from . import your_game  # noqa: F401
  4. 在 your_game/__init__.py 中确保导入了 renderer 和 handler
"""

from . import renderer  # noqa: F401
from . import handler   # noqa: F401
