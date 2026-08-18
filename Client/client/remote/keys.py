"""uremote 按键协议 — 纯逻辑，无副作用。"""

from __future__ import annotations

# 允许注入的按键集合。iPhone 端已把 shift 组合转成大写字母，
# 游戏端只需校验后原样注入为 Textual Key 事件。
ALLOWED_KEYS = frozenset({
    # 方向键（小写 = 移动光标，大写 = 切换面板聚焦）
    "h", "j", "k", "l",
    "H", "J", "K", "L",
    # 输入模式
    "i", "I",
    # 确认 / 返回 / 快捷菜单
    "enter", "escape", "space",
})

# 粘贴文本的最大长度（单行）
MAX_TEXT_LEN = 500


def validate_key(key: str) -> bool:
    """校验手柄按键是否在允许注入的白名单内。"""
    return key in ALLOWED_KEYS


def key_event_args(key: str) -> tuple[str, str | None]:
    """把白名单按键转成 Textual ``events.Key`` 的构造参数。

    单字符键的 character 就是自身；具名键（enter/escape/space）的
    character 为 None，与真实终端按键事件一致。
    """
    return (key, key if len(key) == 1 else None)


def sanitize_text(text: str) -> str:
    """把粘贴文本限制为单行并截断到最大长度。"""
    lines = text.splitlines()
    line = lines[0] if lines else ""
    return line[:MAX_TEXT_LEN]
