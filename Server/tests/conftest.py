"""共享 fixtures — 为纯函数测试提供通用构造器"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保 Server/ 在 sys.path 中，以便直接 import server.*
_server_root = Path(__file__).resolve().parent.parent
if str(_server_root) not in sys.path:
    sys.path.insert(0, str(_server_root))
