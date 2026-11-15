"""Terminal text measurement shared by the window system and game renderers.

This module is the only place that measures or wraps terminal text; there are two vocabularies:

* plain text: ``cell_width`` / ``fit_cells`` / ``wrap_cells``;
* Rich markup: ``plain_text`` (strip the tags) / ``wrap_markup`` (wrap by the visible width and
  keep each row's styles). Never hand plain-text helpers a markup string: its tags would count
  as visible cells.
"""

from __future__ import annotations

from typing import Literal

import regex
from rich.cells import cell_len
from rich.errors import MarkupError
from rich.text import Text


Alignment = Literal["left", "center", "right"]

_EMOJI_SEQUENCE_CODEPOINTS = frozenset({
    0x200D,  # ZERO WIDTH JOINER
    0x20E3,  # COMBINING ENCLOSING KEYCAP
    0xFE0F,  # VARIATION SELECTOR-16
})
_GRAPHEME_PATTERN = regex.compile(r"\X")
_EMOJI_PRESENTATION_PATTERN = regex.compile(
    r"[\p{Emoji_Presentation}\p{Emoji_Modifier}]"
)


def cell_width(text: str) -> int:
    """Return rendered terminal width in cells."""
    return cell_len(text)


def plain_text(markup: str) -> str:
    """把 Rich markup 转成纯文本；解析失败时原样返回（best-effort）。"""
    try:
        return Text.from_markup(markup).plain
    except Exception:
        return markup


def grapheme_clusters(text: str) -> list[str]:
    """Split text into Unicode extended grapheme clusters (UAX #29)."""
    return _GRAPHEME_PATTERN.findall(text)


def fit_cells(
    text: str,
    width: int,
    align: Alignment = "left",
    *,
    crop: bool = False,
) -> str:
    """Pad text to a cell width, optionally cropping at grapheme boundaries."""
    if width <= 0:
        return ""

    current = cell_width(text)
    if current > width:
        if not crop:
            return text
        kept: list[str] = []
        used = 0
        for cluster in grapheme_clusters(text):
            cluster_width = cell_width(cluster)
            if used + cluster_width > width:
                break
            kept.append(cluster)
            used += cluster_width
        text = "".join(kept)
        current = used

    padding = width - current
    if align == "right":
        return " " * padding + text
    if align == "center":
        left = padding // 2
        return " " * left + text + " " * (padding - left)
    if align != "left":
        raise ValueError(f"unsupported alignment: {align}")
    return text + " " * padding


def wrap_cells(text: str, width: int) -> list[str]:
    """Wrap text to terminal cells without splitting grapheme clusters."""
    if width <= 0:
        raise ValueError("width must be positive")

    wrapped: list[str] = []
    for logical_line in text.split("\n"):
        if not logical_line:
            wrapped.append("")
            continue
        line: list[str] = []
        line_width = 0
        for cluster in grapheme_clusters(logical_line):
            cluster_width = cell_width(cluster)
            if line and line_width + cluster_width > width:
                wrapped.append("".join(line))
                line = []
                line_width = 0
            line.append(cluster)
            line_width += cluster_width
        wrapped.append("".join(line))
    return wrapped


def wrap_markup(markup: str, width: int) -> list[str]:
    """Wrap Rich markup by the cells of its visible text, keeping styles on every row."""
    try:
        text = Text.from_markup(markup)
    except MarkupError:
        return wrap_cells(markup, width)

    rows: list[str] = []
    for line in text.split("\n", allow_blank=True):
        offsets: list[int] = []
        position = 0
        for row in wrap_cells(line.plain, width)[:-1]:
            position += len(row)
            offsets.append(position)
        rows.extend(piece.markup for piece in line.divide(offsets))
    return rows


def uses_emoji_presentation(text: str) -> bool:
    """Detect sequences that request emoji presentation or emoji composition."""
    if _EMOJI_PRESENTATION_PATTERN.search(text):
        return True
    for char in text:
        codepoint = ord(char)
        if codepoint in _EMOJI_SEQUENCE_CODEPOINTS:
            return True
    return False
