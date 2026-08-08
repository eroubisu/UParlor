"""Terminal text measurement shared by the window system and game renderers."""

from __future__ import annotations

from typing import Literal

import regex
from rich.cells import cell_len


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


def uses_emoji_presentation(text: str) -> bool:
    """Detect sequences that request emoji presentation or emoji composition."""
    if _EMOJI_PRESENTATION_PATTERN.search(text):
        return True
    for char in text:
        codepoint = ord(char)
        if codepoint in _EMOJI_SEQUENCE_CODEPOINTS:
            return True
    return False
