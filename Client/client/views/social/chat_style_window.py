"""Separate categorized editor for the player's chat presentation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Callable

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from ...chat_style import render_chat_groups
from ...config import COLOR_BORDER
from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import Divider, Option, WindowSpec, register_window
from ...window_specs import bind_chat_style, logged_in


_COLOR_FIELDS = (
    ("name_fg", "玩家名前景"),
    ("name_bg", "玩家名背景"),
    ("title_fg", "称号前景"),
    ("title_bg", "称号背景"),
    ("level_fg", "等级前景"),
    ("level_bg", "等级背景"),
    ("frame", "外框颜色"),
    ("body", "正文颜色"),
)
_CONNECTOR_FIELDS = (
    ("left_connector", "标题左端", "edge_connectors"),
    ("inner_connector", "板块之间", "separators"),
    ("right_connector", "标题右端", "edge_connectors"),
)


class ChatStylePanel(Panel):
    """Edit catalog IDs while keeping a fixed live preview below the tabs."""

    tabs = ["身份", "颜色", "连接", "外框", "确认"]
    full_width_content = True

    class Finished(Message):
        def __init__(self, saved: bool) -> None:
            super().__init__()
            self.saved = saved

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._status_state = None
        self._send: Callable[[dict], None] | None = None
        self._player_data: dict = {}
        self._style_data: dict = {}
        self._draft: dict = {}
        self._choosing_field = ""
        self._choosing_source = ""

    def compose_content(self) -> ComposeResult:
        for index in range(len(self.tabs)):
            with VerticalScroll(classes="tab style-editor", id=f"t{index}"):
                yield Static("", classes="content", markup=True)
        yield Divider(style=COLOR_BORDER, id="chat-style-divider")
        yield Static("", id="chat-style-preview", markup=True)

    def bind_state(
        self,
        state,
        send: Callable[[dict], None],
    ) -> None:
        self._status_state = state.status
        self._send = send
        state.status.add_listener(self._on_status_event)
        self._load_player_data(state.status.player_data)

    def _on_status_event(self, event: str, *args) -> None:
        if event == "update_player_info" and args:
            self._load_player_data(args[0])

    def _load_player_data(self, player_data: dict) -> None:
        self._player_data = player_data if isinstance(player_data, dict) else {}
        style_data = self._player_data.get("chat_style")
        self._style_data = style_data if isinstance(style_data, dict) else {}
        config = self._style_data.get("config")
        if not self._draft and isinstance(config, dict):
            self._draft = dict(config)
        if self.is_mounted:
            self.call_after_refresh(self._redraw)

    def on_mount(self) -> None:
        super().on_mount()
        self.call_after_refresh(self._redraw)

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._choosing_field = ""
        self._choosing_source = ""
        config = self._style_data.get("config")
        self._draft = dict(config) if isinstance(config, dict) else {}
        if self._active:
            self.switch_tab(0)
        self._redraw()

    def _catalog(self, source: str) -> list[dict]:
        items = self._style_data.get(source)
        return [
            item for item in items
            if isinstance(item, dict) and item.get("id")
        ] if isinstance(items, list) else []

    def _value_label(self, source: str, value: object) -> str:
        return next((
            str(item.get("label", ""))
            for item in self._catalog(source)
            if item.get("id") == value
        ), "未设置")

    def _field_options(
        self,
        fields: tuple[tuple[str, str, str], ...],
    ) -> tuple[Option, ...]:
        return tuple(
            Option(
                key,
                label,
                self._value_label(source, self._draft.get(key)),
                data=source,
                description_align="right",
            )
            for key, label, source in fields
        )

    def _choice_options(self) -> tuple[Option, ...]:
        return (
            *(
            Option(str(item["id"]), str(item.get("label", item["id"])))
            for item in self._catalog(self._choosing_source)
            ),
            Option("__return__", "返回"),
        )

    def _preview_draft(self) -> dict:
        draft = dict(self._draft)
        selected = self.selected_option
        if (
            self._choosing_field
            and selected is not None
            and selected.id != "__return__"
        ):
            draft[self._choosing_field] = selected.id
        return draft

    def _resolved_draft(self, draft: dict) -> dict:
        colors = {
            item.get("id"): item.get("value")
            for item in self._catalog("colors")
        }
        resolved = {}
        for key, _ in _COLOR_FIELDS:
            value = colors.get(draft.get(key))
            if isinstance(value, str):
                resolved[key] = value
        for key, _, _ in _CONNECTOR_FIELDS:
            value = draft.get(key)
            if isinstance(value, str):
                resolved[key] = value
        frame_shape = draft.get("frame_shape")
        if isinstance(frame_shape, str):
            resolved["frame_shape"] = frame_shape
        return resolved

    def _preview(self) -> str:
        name = str(self._player_data.get("name") or "玩家")
        draft = self._preview_draft()
        title_id = draft.get("title_id")
        title = self._value_label("titles", title_id)
        sender = {
            "name": name,
            "title": title,
            "level": self._player_data.get("level", 1),
            "style": self._resolved_draft(draft),
        }
        entry = SimpleNamespace(
            sender_name=name,
            text="这是一条聊天样式预览",
            time="11:10:34",
        )
        preview = self.query_one("#chat-style-preview", Static)
        width = preview.content_region.width
        if width <= 1:
            width = 1
        return render_chat_groups([entry], {name: sender}, width)

    def _tab_fields(self) -> tuple[tuple[str, str, str], ...]:
        if self._active == 0:
            return (("title_id", "聊天称号", "titles"),)
        if self._active == 1:
            return tuple(
                (key, label, "colors") for key, label in _COLOR_FIELDS)
        if self._active == 2:
            return _CONNECTOR_FIELDS
        if self._active == 3:
            return (("frame_shape", "外框形状", "frames"),)
        return ()

    def _redraw(self) -> None:
        if not self.is_mounted:
            return
        if self._choosing_field:
            self.set_options(
                self._choice_options(),
                f"chat-style-choice:{self._choosing_field}",
            )
            content = self.render_options()
        elif self._active == 4:
            self.set_options((
                Option("__save__", "确认并保存"),
                Option("__discard__", "放弃修改"),
                Option("__reset__", "恢复进入窗口时的样式"),
            ), "chat-style-confirm")
            content = self.render_options()
        else:
            self.set_options(
                self._field_options(self._tab_fields()),
                f"chat-style-fields:{self._active}",
            )
            content = self.render_options()
        self.update(content)
        self.query_one("#chat-style-preview", Static).update(self._preview())

    def switch_tab(self, index: int) -> None:
        self._choosing_field = ""
        self._choosing_source = ""
        super().switch_tab(index)
        self._redraw()

    def _choose(self) -> None:
        selected = self.selected_option
        if selected is None:
            return
        if selected.id == "__return__":
            self._choosing_field = ""
            self._choosing_source = ""
            self._redraw()
            return
        self._draft[self._choosing_field] = selected.id
        self._choosing_field = ""
        self._choosing_source = ""
        self._redraw()

    def _open_field(self) -> None:
        selected = self.selected_option
        if selected is None:
            return
        self._choosing_field = selected.id
        self._choosing_source = str(selected.data)
        self._redraw()
        current = self._draft.get(self._choosing_field)
        if isinstance(current, str):
            self.selection.select(current)
            self._redraw()

    def nav(self, action: str) -> None:
        if action in ("tab_prev", "tab_next"):
            super().nav(action)
            return
        if action in ("up", "down"):
            if self.selection.move(-1 if action == "up" else 1):
                self._redraw()
            return
        if action != "enter":
            super().nav(action)
            return
        if self._choosing_field:
            self._choose()
            return
        if self._active != 4:
            self._open_field()
            return
        selected = self.selected_option
        if selected is None:
            return
        if selected.id == "__save__":
            if self._send is not None:
                self._send({
                    "type": "update_chat_style",
                    "data": dict(self._draft),
                })
            self.post_message(self.Finished(saved=True))
        elif selected.id == "__discard__":
            self.post_message(self.Finished(saved=False))
        elif selected.id == "__reset__":
            config = self._style_data.get("config")
            self._draft = dict(config) if isinstance(config, dict) else {}
            self._redraw()

    def reflow_content(self) -> None:
        self._redraw()


class ChatStyleWindow(Window):
    DEFAULT_CSS = """
    ChatStyleWindow {
        layer: floating;
        width: 72%;
        height: 72%;
    }
    ChatStyleWindow > #chat-style-panel {
        width: 1fr;
        height: 1fr;
    }
    ChatStylePanel > .style-editor {
        height: 1fr;
    }
    ChatStylePanel > #chat-style-divider {
        height: 1;
    }
    ChatStylePanel > #chat-style-preview {
        height: 5;
        padding: 0 1;
    }
    """

    focus_grid = [["chat-style-panel"]]
    primary_panel = "chat-style-panel"
    spec = WindowSpec(
        id="chat-style-window",
        title="聊天样式",
        group="profile",
        order=10,
        preconditions=(logged_in,),
        bind=bind_chat_style,
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bound = False

    def compose(self) -> ComposeResult:
        yield ChatStylePanel(id="chat-style-panel")

    def bind_state(self, state, send: Callable[[dict], None]) -> None:
        if self._bound:
            return
        self._bound = True
        self.query_one("#chat-style-panel", ChatStylePanel).bind_state(
            state, send)


register_window(ChatStyleWindow)
