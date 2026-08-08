"""客户端游戏模块 — 导入即注册渲染器和处理器

每个游戏子包的 __init__.py 负责导入自身的 renderer / handler，
此处只需导入各游戏子包即可触发注册。

添加游戏时在此导入其子包。
"""

from . import uno  # noqa: F401
from . import ludo  # noqa: F401
