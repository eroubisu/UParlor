"""客户端游戏模块 — 导入即注册渲染器和处理器

每个游戏子包的 __init__.py 负责导入自身的 renderer / handler，
此处只需导入各游戏子包即可触发注册。
"""

from . import world      # noqa: F401
from . import wordle     # noqa: F401
from . import mahjong    # noqa: F401
from . import chess       # noqa: F401
from . import blackjack   # noqa: F401
from . import holdem      # noqa: F401
from . import doudizhu    # noqa: F401
