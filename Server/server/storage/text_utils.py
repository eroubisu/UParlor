"""显示宽度工具 — 处理 CJK 双宽字符的对齐问题"""

import unicodedata


def _char_width(ch):
    """单个字符的终端显示宽度"""
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ('F', 'W') else 1


def display_width(text):
    """计算文本的终端显示宽度（CJK/全角字符算2列）"""
    return sum(_char_width(ch) for ch in text)


def pad_center(text, width, fillchar=' '):
    """基于显示宽度居中对齐"""
    tw = display_width(text)
    if tw >= width:
        return text
    left = (width - tw) // 2
    right = width - tw - left
    return fillchar * left + text + fillchar * right


def pad_left(text, width, fillchar=' '):
    """基于显示宽度左对齐（右侧填充）"""
    tw = display_width(text)
    if tw >= width:
        return text
    return text + fillchar * (width - tw)


def truncate(text, width):
    """截断文本使其不超过指定显示宽度"""
    w = 0
    for i, ch in enumerate(text):
        cw = _char_width(ch)
        if w + cw > width:
            return text[:i]
        w += cw
    return text
