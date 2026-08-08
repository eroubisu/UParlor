"""Validated player chat presentation and sender identity payloads."""

from __future__ import annotations

import copy
import json
import os
import re

from ..systems.titles import get_title_name


_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "chat_styles.json")
with open(_DATA_PATH, "r", encoding="utf-8") as _file:
    _CATALOG = json.load(_file)

CHAT_STYLE_DEFAULT = _CATALOG["default"]
_COLOR_VALUES = {
    item["id"]: item["value"] for item in _CATALOG["colors"]
}
_COLOR_KEYS = (
    "name_fg", "name_bg", "title_fg", "title_bg",
    "level_fg", "level_bg", "frame", "body",
)
_CONNECTOR_CATALOGS = {
    "left_connector": "edge_connectors",
    "inner_connector": "separators",
    "right_connector": "edge_connectors",
}
_LEGACY_CONNECTORS = {
    "powerline": "angled",
    "soft": "angled",
    "square": "vertical",
    "round": "round",
}
_LEGACY_WORLD_SENDER = re.compile(r"^\[\d+\]([A-Za-z0-9]{2,12})$")


def _catalog_ids(section: str) -> set[str]:
    return {item["id"] for item in _CATALOG[section]}


def default_chat_style() -> dict:
    return copy.deepcopy(CHAT_STYLE_DEFAULT)


def validate_chat_style(raw: object, owned_titles: list[str]) -> dict:
    """Return a complete style containing only catalog and owned-title IDs."""
    source = raw if isinstance(raw, dict) else {}
    style = default_chat_style()
    for key in _COLOR_KEYS:
        value = source.get(key)
        if isinstance(value, str) and value in _COLOR_VALUES:
            style[key] = value
    for key, section in _CONNECTOR_CATALOGS.items():
        value = source.get(key)
        if isinstance(value, str):
            value = _LEGACY_CONNECTORS.get(value, value)
        if isinstance(value, str) and value in _catalog_ids(section):
            style[key] = value
    frame_shape = source.get("frame_shape")
    if (
        isinstance(frame_shape, str)
        and frame_shape in _catalog_ids("frames")
    ):
        style["frame_shape"] = frame_shape

    available_titles = [
        title for title in owned_titles if isinstance(title, str)
    ]
    requested_title = source.get("title_id")
    if isinstance(requested_title, str) and requested_title in available_titles:
        style["title_id"] = requested_title
    elif style["title_id"] not in available_titles:
        style["title_id"] = available_titles[0] if available_titles else ""
    return style


def resolve_chat_style(style: dict) -> dict:
    """Resolve persisted catalog IDs into a client render payload."""
    resolved = {
        key: _COLOR_VALUES[style[key]]
        for key in _COLOR_KEYS
    }
    resolved.update({
        key: style[key] for key in _CONNECTOR_CATALOGS
    })
    resolved["frame_shape"] = style["frame_shape"]
    return resolved


def chat_style_status(player_data: dict) -> dict:
    titles = player_data.get("titles", {})
    owned = titles.get("owned", [])
    config = validate_chat_style(player_data.get("chat_style"), owned)
    return {
        "config": config,
        "resolved": resolve_chat_style(config),
        "colors": copy.deepcopy(_CATALOG["colors"]),
        "edge_connectors": copy.deepcopy(_CATALOG["edge_connectors"]),
        "separators": copy.deepcopy(_CATALOG["separators"]),
        "frames": copy.deepcopy(_CATALOG["frames"]),
        "titles": [
            {"id": title_id, "label": get_title_name(title_id)}
            for title_id in owned
            if isinstance(title_id, str)
        ],
    }


def build_chat_sender(player_data: dict, name: str = "") -> dict:
    titles = player_data.get("titles", {})
    style = validate_chat_style(
        player_data.get("chat_style"), titles.get("owned", []))
    title_id = style["title_id"]
    return {
        "name": str(player_data.get("name") or name),
        "title": get_title_name(title_id) if title_id else "",
        "level": int(player_data.get("level", 1)),
        "style": resolve_chat_style(style),
    }


def enrich_chat_messages(
    messages: list[dict],
    *,
    sender_field: str,
) -> list[dict]:
    """Attach each sender's current presentation without changing stored logs."""
    from .manager import PlayerManager

    senders: dict[str, dict | None] = {}
    enriched = []
    for message in messages:
        sender_name = str(message.get(sender_field, ""))
        if sender_name not in senders:
            player_data = PlayerManager.load_player_data(sender_name)
            legacy_match = _LEGACY_WORLD_SENDER.fullmatch(sender_name)
            if player_data is None and legacy_match is not None:
                player_data = PlayerManager.load_player_data(
                    legacy_match.group(1))
            senders[sender_name] = (
                build_chat_sender(player_data) if player_data else None)
        current = dict(message)
        sender = senders[sender_name]
        if sender is not None:
            current["sender"] = sender
        enriched.append(current)
    return enriched
