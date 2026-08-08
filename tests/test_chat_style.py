"""Player-owned Powerline chat presentation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from rich.cells import cell_len
from rich.markup import render
from textual.app import App, ComposeResult

from client.chat_style import render_chat_groups
from client.config import CHAT_CONNECTOR_GLYPHS, COLOR_FG_TERTIARY
from client.state import ModuleStateManager
from client.state.chat import ChatEntry, ChatState
from client.views.social.chat_style_window import ChatStylePanel
from server.player.chat_style import (
    build_chat_sender,
    chat_style_status,
    enrich_chat_messages,
    validate_chat_style,
)
from server.player.manager import PlayerManager
from server.player.schema import ensure_user_schema, get_default_user_template


def _player_data() -> dict:
    return {
        "name": "alice",
        "level": 7,
        "titles": {
            "owned": ["newcomer", "rank_adept"],
            "displayed": ["newcomer"],
        },
    }


def test_style_validation_accepts_only_catalog_and_owned_title():
    validated = validate_chat_style({
        "title_id": "not-owned",
        "name_fg": "not-a-color",
        "body": "green",
        "left_connector": "soft",
        "inner_connector": "invented",
    }, ["newcomer"])

    assert validated["title_id"] == "newcomer"
    assert validated["name_fg"] == "white"
    assert validated["body"] == "green"
    assert validated["left_connector"] == "angled"
    assert validated["inner_connector"] == "angled"
    assert validated["frame_shape"] == "square"


def test_existing_player_style_is_normalized_during_schema_upgrade():
    player = get_default_user_template("alice", "hash")
    player["chat_style"]["body"] = "arbitrary-rich-markup"

    upgraded, changes = ensure_user_schema(player)

    assert upgraded["chat_style"]["body"] == "white"
    assert "规范化: chat_style" in changes


def test_adjacent_messages_share_frame_and_every_message_keeps_time():
    alice = build_chat_sender(_player_data())
    bob_data = _player_data()
    bob_data["name"] = "bob"
    bob = build_chat_sender(bob_data)
    entries = [
        ChatEntry("alice", "first", "11:10:31"),
        ChatEntry("alice", "second", "11:10:32"),
        ChatEntry("bob", "third", "11:10:33"),
    ]

    markup = render_chat_groups(
        entries, {"alice": alice, "bob": bob}, 44)
    plain = render(markup).plain
    lines = plain.splitlines()

    assert plain.count("┌─") == 2
    assert plain.count("└─") == 2
    assert all(cell_len(line) == 44 for line in lines if line)
    assert all(time in plain for time in (
        "11:10:31", "11:10:32", "11:10:33"))
    assert any(
        line.startswith("└─second") and "11:10:32─┘" in line
        for line in lines
    )


def test_long_message_moves_time_to_its_own_right_aligned_line():
    sender = build_chat_sender(_player_data())
    markup = render_chat_groups(
        [ChatEntry("alice", "x" * 30, "11:10:34")],
        {"alice": sender},
        24,
    )
    lines = render(markup).plain.splitlines()

    assert lines[-1].startswith("└─")
    assert lines[-1].endswith("11:10:34─┘")
    assert all(cell_len(line) == 24 for line in lines)


def test_p10k_connectors_round_frame_and_gray_time_render_together():
    sender = build_chat_sender(_player_data())
    sender["style"].update({
        "left_connector": "blurred",
        "inner_connector": "slanted",
        "right_connector": "angled",
        "frame_shape": "round",
    })

    markup = render_chat_groups(
        [ChatEntry("alice", "hello", "11:10:35")],
        {"alice": sender},
        44,
    )
    plain = render(markup).plain

    assert "░▒▓" in plain
    assert "\ue0bc" in plain
    assert "\ue0b0" in plain
    assert plain.startswith("╭─")
    assert plain.splitlines()[-1].endswith("─╯")
    assert f"[{COLOR_FG_TERTIARY}]11:10:35[/]" in markup


def test_different_background_separators_use_p10k_transition_glyphs():
    assert CHAT_CONNECTOR_GLYPHS["inner"]["vertical"] == ""
    assert CHAT_CONNECTOR_GLYPHS["inner"]["slanted"] == "\ue0bc"
    assert CHAT_CONNECTOR_GLYPHS["inner"]["round"] == "\ue0b4"


def test_chat_state_uses_canonical_sender_for_legacy_history_name():
    state = ChatState()
    sender = build_chat_sender(_player_data())

    state.set_world_history([{
        "name": "[7]alice",
        "text": "legacy",
        "time": "11:10:30",
        "sender": sender,
    }])
    state.update_sender({**sender, "style": {
        **sender["style"],
        "body": "#81c784",
    }})

    assert state.world_messages[0].sender_name == "alice"
    assert state.sender("alice")["style"]["body"] == "#81c784"
    assert "[7]alice" not in state.senders


def test_server_enriches_legacy_level_prefixed_world_sender(monkeypatch):
    player = _player_data()
    monkeypatch.setattr(
        PlayerManager,
        "load_player_data",
        lambda name: player if name == "alice" else None,
    )

    enriched = enrich_chat_messages(
        [{"name": "[7]alice", "text": "legacy"}],
        sender_field="name",
    )

    assert enriched[0]["sender"]["name"] == "alice"


class _StyleApp(App):
    def __init__(self):
        super().__init__()
        self.network = SimpleNamespace(send=Mock())
        self.state = ModuleStateManager()

    def compose(self) -> ComposeResult:
        yield ChatStylePanel()


def test_chat_style_window_previews_by_tab_and_saves_once():
    async def verify():
        app = _StyleApp()
        async with app.run_test(size=(80, 30)) as pilot:
            panel = app.query_one(ChatStylePanel)
            panel.bind_state(app.state, app.network.send)
            player = _player_data()
            player.update({
                "exp": 0,
                "exp_to_next": 10,
                "gold": 100,
                "friends_count": 0,
                "chat_style": chat_style_status(player),
            })
            app.state.status.update_player_info(player)
            await pilot.pause()
            assert "11:10:34" in str(
                panel.query_one("#chat-style-preview").content)

            panel.switch_tab(1)
            panel.selection.select("name_fg")
            panel.nav("enter")
            panel.selection.select("green")
            panel._redraw()
            preview = str(panel.query_one("#chat-style-preview").content)
            assert "#81c784 on #6fa8dc" in preview
            assert panel._draft["name_fg"] != "green"
            panel.selection.select("__return__")
            panel.nav("enter")
            assert panel._choosing_field == ""

            panel.switch_tab(2)
            panel.selection.select("left_connector")
            panel.nav("enter")
            panel.selection.select("blurred")
            panel.nav("enter")
            assert "░▒▓" in str(
                panel.query_one("#chat-style-preview").content)
            app.network.send.assert_not_called()

            preview_widget = panel.query_one("#chat-style-preview")
            old_width = preview_widget.content_region.width
            await pilot.resize_terminal(56, 24)
            await pilot.pause()
            new_width = preview_widget.content_region.width
            resized_lines = render(str(preview_widget.content)).plain.splitlines()
            assert new_width != old_width
            assert all(cell_len(line) == new_width for line in resized_lines)

            panel.switch_tab(3)
            panel.nav("enter")
            panel.selection.select("round")
            panel.nav("enter")
            assert "╭─" in str(
                panel.query_one("#chat-style-preview").content)

            panel.switch_tab(4)
            panel.selection.select("__save__")
            panel.nav("enter")

            app.network.send.assert_called_once()
            payload = app.network.send.call_args.args[0]
            assert payload["type"] == "update_chat_style"
            assert payload["data"]["title_id"] in {
                "newcomer", "rank_adept"}
            assert payload["data"]["left_connector"] == "blurred"
            assert payload["data"]["frame_shape"] == "round"

    asyncio.run(verify())


def test_player_status_keeps_experience_progress_bar():
    from client.views.social.status_panel import _exp_bar

    rendered = _exp_bar(5, 10, width=8)

    assert rendered.count("━") == 8
    assert rendered.index("[/]") > rendered.index("━")
