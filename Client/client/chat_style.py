"""Powerline-style framed chat group rendering."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from rich.markup import escape

from .config import (
    CHAT_CONNECTOR_GLYPHS,
    CHAT_FRAME_GLYPHS,
    COLOR_BORDER_LIGHT,
    COLOR_FG_PRIMARY,
    COLOR_FG_TERTIARY,
)
from .window_engine.text import cell_width, fit_cells, wrap_cells


LineFormatter = Callable[[Any, str, str], str]

_DEFAULT_STYLE = {
    "name_fg": COLOR_FG_PRIMARY,
    "name_bg": "#6fa8dc",
    "title_fg": COLOR_FG_PRIMARY,
    "title_bg": "#b39ddb",
    "level_fg": COLOR_FG_PRIMARY,
    "level_bg": "#454545",
    "frame": COLOR_BORDER_LIGHT,
    "body": COLOR_FG_PRIMARY,
    "left_connector": "round",
    "inner_connector": "angled",
    "right_connector": "round",
    "frame_shape": "square",
}


def _style(sender: dict) -> dict:
    result = dict(_DEFAULT_STYLE)
    raw = sender.get("style")
    if isinstance(raw, dict):
        for key in result:
            value = raw.get(key)
            if isinstance(value, str) and value:
                result[key] = value
    return result


def _labels(sender: dict) -> list[str]:
    explicit = sender.get("labels")
    if isinstance(explicit, list):
        return [str(label) for label in explicit if str(label)]
    level = sender.get("level")
    return [
        str(sender.get("name", "")),
        str(sender.get("title", "")) or "无称号",
        f"Lv.{level}" if level not in (None, "") else "",
    ]


def _connector(position: str, connector_id: str) -> str:
    choices = CHAT_CONNECTOR_GLYPHS[position]
    defaults = {"left": "round", "inner": "angled", "right": "round"}
    return choices.get(connector_id, choices[defaults[position]])


def _title_line(
    sender: dict,
    width: int,
    top_left: str = "┌",
    top_right: str = "┐",
) -> str:
    style = _style(sender)
    labels = _labels(sender)
    labels = labels or [str(sender.get("name", ""))]
    color_pairs = [
        (style["name_fg"], style["name_bg"]),
        (style["title_fg"], style["title_bg"]),
        (style["level_fg"], style["level_bg"]),
    ][:len(labels)]
    frame = style["frame"]

    left = _connector("left", style["left_connector"])
    inner = _connector("inner", style["inner_connector"])
    right = _connector("right", style["right_connector"])
    connector_width = (
        cell_width(left)
        + cell_width(right)
        + max(0, len(labels) - 1) * cell_width(inner)
    )
    available = max(
        width - 3 - connector_width - 2 * len(labels),
        len(labels),
    )
    label_width = max(1, available // len(labels))
    fitted = [
        fit_cells(label, label_width, crop=True).rstrip()
        for label in labels
    ]

    plain_width = 2 + cell_width(left) + cell_width(right)
    plain_width += sum(cell_width(label) + 2 for label in fitted)
    plain_width += max(0, len(fitted) - 1) * cell_width(inner)
    fill = "─" * max(0, width - plain_width - 1)

    parts = [f"[{frame}]{top_left}─[/]"]
    first_bg = color_pairs[0][1]
    parts.append(f"[{first_bg}]{left}[/]")
    for index, (label, colors) in enumerate(zip(fitted, color_pairs)):
        foreground, background = colors
        parts.append(
            f"[{foreground} on {background}] {escape(label)} [/]")
        if index < len(fitted) - 1:
            next_background = color_pairs[index + 1][1]
            parts.append(
                f"[{background} on {next_background}]{inner}[/]")
    last_bg = color_pairs[-1][1]
    parts.append(f"[{last_bg}]{right}[/]")
    parts.append(f"[{frame}]{fill}{top_right}[/]")
    return "".join(parts)


def _default_line_formatter(entry: Any, line: str, body_color: str) -> str:
    del entry
    return f"[{body_color}]{escape(line)}[/]"


def _message_rows(
    entry: Any,
    content_width: int,
    body_color: str,
    line_formatter: LineFormatter,
) -> list[tuple[str, str]]:
    text = str(entry.text)
    logical_rows = []
    for logical_line in text.splitlines() or [""]:
        logical_rows.extend(wrap_cells(logical_line, content_width))
    rows = logical_rows or [""]
    time = str(entry.time)
    last = rows.pop()
    if time and cell_width(last) + cell_width(time) + 1 <= content_width:
        padding = " " * (
            content_width - cell_width(last) - cell_width(time))
        final_plain = last + padding + time
        final_markup = (
            line_formatter(entry, last, body_color)
            + padding
            + f"[{COLOR_FG_TERTIARY}]{escape(time)}[/]"
        )
    elif time:
        rows.append(last)
        final_plain = fit_cells(time, content_width, "right", crop=True)
        final_markup = (
            " " * (content_width - cell_width(final_plain.lstrip()))
            + f"[{COLOR_FG_TERTIARY}]{escape(final_plain.lstrip())}[/]"
        )
    else:
        final_plain = fit_cells(last, content_width, crop=True)
        final_markup = line_formatter(entry, final_plain.rstrip(), body_color)

    rendered = [
        (
            fit_cells(row, content_width, crop=True),
            line_formatter(entry, row, body_color)
            + " " * max(0, content_width - cell_width(row)),
        )
        for row in rows
    ]
    rendered.append((final_plain, final_markup))
    return rendered


def render_chat_groups(
    entries: Sequence[Any],
    senders: dict[str, dict],
    width: int,
    *,
    line_formatter: LineFormatter | None = None,
) -> str:
    """Render adjacent messages from one sender in one closed frame."""
    if not entries:
        return ""
    formatter = line_formatter or _default_line_formatter
    width = max(width, 12)
    content_width = width - 4
    groups: list[list[Any]] = []
    for entry in entries:
        if groups and groups[-1][-1].sender_name == entry.sender_name:
            groups[-1].append(entry)
        else:
            groups.append([entry])

    rendered_groups = []
    for group in groups:
        sender_name = group[0].sender_name
        sender = senders.get(sender_name, {"name": sender_name})
        style = _style(sender)
        frame = style["frame"]
        corners = CHAT_FRAME_GLYPHS.get(
            style["frame_shape"], CHAT_FRAME_GLYPHS["square"])
        top_left, top_right, bottom_left, bottom_right = corners
        lines = [_title_line(sender, width, top_left, top_right)]
        for message_index, entry in enumerate(group):
            rows = _message_rows(
                entry, content_width, style["body"], formatter)
            is_last_message = message_index == len(group) - 1
            for row_index, (_, markup) in enumerate(rows):
                is_group_end = (
                    is_last_message and row_index == len(rows) - 1)
                if is_group_end:
                    lines.append(
                        f"[{frame}]{bottom_left}─[/]"
                        f"{markup}[{frame}]─{bottom_right}[/]")
                else:
                    lines.append(
                        f"[{frame}]│ [/]{markup}[{frame}] │[/]")
        rendered_groups.append("\n".join(lines))
    return "\n\n".join(rendered_groups)
