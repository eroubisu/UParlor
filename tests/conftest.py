"""共享 pytest fixture / 路径配置

让 tests/ 既能跑客户端单测又能跑服务端单测,
同时不需要 pip install 也能 import client/* server/*
"""

import sys
from pathlib import Path

# 加入 src 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "Client"))
sys.path.insert(0, str(ROOT / "Server"))
