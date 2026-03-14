"""圆角滚动条渲染器"""

from textual.scrollbar import ScrollBar, ScrollBarRender
from rich.segment import Segment, Segments
from rich.style import Style
from rich.color import Color

from ..config import COLOR_BORDER


class RoundedScrollBarRender(ScrollBarRender):
    """药丸形滚动条 — 用半块字符 ▄█▀ 组成圆头圆尾的拇指"""

    @classmethod
    def render_bar(
        cls,
        size: int = 25,
        virtual_size: float = 50,
        window_size: float = 20,
        position: float = 0,
        thickness: int = 1,
        vertical: bool = True,
        back_color: Color = Color.default(),
        bar_color: Color = Color.parse(COLOR_BORDER),
    ) -> Segments:
        result = ScrollBarRender.render_bar(
            size=size, virtual_size=virtual_size, window_size=window_size,
            position=position, thickness=thickness, vertical=vertical,
            back_color=back_color, bar_color=bar_color,
        )
        if not vertical or not result.segments:
            return result

        segs = list(result.segments)
        thumb_indices = [
            i for i, seg in enumerate(segs)
            if seg.style and seg.style.color is not None
        ]
        if not thumb_indices:
            return result

        first, last = thumb_indices[0], thumb_indices[-1]
        meta = {"@mouse.down": "grab"}
        w = thickness
        cap_style = Style(color=bar_color, bgcolor=back_color, meta=meta)
        body_style = Style(color=bar_color, bgcolor=bar_color, meta=meta)

        if first == last:
            segs[first] = Segment("█" * w, cap_style)
        elif last - first == 1:
            segs[first] = Segment("▄" * w, cap_style)
            segs[last] = Segment("▀" * w, cap_style)
        else:
            segs[first] = Segment("▄" * w, cap_style)
            for i in range(first + 1, last):
                segs[i] = Segment("█" * w, body_style)
            segs[last] = Segment("▀" * w, cap_style)

        return Segments(segs, new_lines=True)


# 全局替换滚动条渲染器
ScrollBar.renderer = RoundedScrollBarRender
