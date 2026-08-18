"""网页手柄（uremote）连接支持。

- keys.py    按键白名单与校验（纯逻辑，可单测）
- manager.py RemoteController：本地 HTTP 服务 + 配对 + 按键回调
- page.py    网页手柄页面（HTML/JS）
- qr.py      终端二维码渲染
"""

from .keys import (
    ALLOWED_KEYS,
    MAX_TEXT_LEN,
    key_event_args,
    sanitize_text,
    validate_key,
)
from .manager import RemoteController
from .qr import render_qr

__all__ = [
    'ALLOWED_KEYS',
    'MAX_TEXT_LEN',
    'key_event_args',
    'sanitize_text',
    'validate_key',
    'RemoteController',
    'render_qr',
]
