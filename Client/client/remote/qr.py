"""把 URL 渲染成终端可扫描的二维码文本（半块字符）。

用 ``qrcode`` 库生成模块矩阵，再用上半块 / 下半块字符把纵向高度压缩一半。
配合白底黑字的显示区域（CSS ``background: #ffffff; color: #000000``）即可扫描。
"""

from __future__ import annotations


def render_qr(text: str) -> str:
    """生成二维码文本；深色模块用 ``█/▀/▄``，浅色模块用空格。"""
    import qrcode

    qr = qrcode.QRCode(
        border=2,
        box_size=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
    )
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()  # list[list[bool]]，True 为深色模块

    if not matrix:
        return ""

    rows = len(matrix)
    cols = len(matrix[0])
    lines: list[str] = []
    for y in range(0, rows, 2):
        chars: list[str] = []
        for x in range(cols):
            dark_top = matrix[y][x]
            dark_bottom = matrix[y + 1][x] if y + 1 < rows else False
            if dark_top and dark_bottom:
                chars.append("█")
            elif dark_top:
                chars.append("▀")
            elif dark_bottom:
                chars.append("▄")
            else:
                chars.append(" ")
        lines.append("".join(chars))
    return "\n".join(lines)
