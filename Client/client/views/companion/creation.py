"""Stepwise companion creation window."""

from __future__ import annotations

import time

from rich.markup import escape
from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Input

from ...companion import CompanionController
from ...companion.character import (
    CHARACTER_FIELDS,
    CHARACTER_FIELD_LABELS,
    Character,
    generate_char_id,
    save_character,
)
from ...config import (
    COLOR_FG_TERTIARY,
    ICON_INDENT,
)
from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import WindowSpec, register_window
from ...window_engine import InputSpec, Option
from ...window_specs import bind_state, logged_in

_PAGES = (
    ("description", "描述"),
    *[(field, CHARACTER_FIELD_LABELS[field]) for field in CHARACTER_FIELDS],
    ("confirm", "确认"),
)


class CompanionCreationPanel(Panel):
    """Gate a companion draft through description and five AI-assisted fields."""

    tabs = [label for _, label in _PAGES]
    has_input = True
    placeholder = "输入描述"
    icon_align = True

    class Created(Message):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._controller: CompanionController | None = None
        self._description = ""
        self._selected: dict[str, str] = {}
        self._options: dict[str, list[str]] = {}
        self._unlocked_page = 0
        self._generating_field: str | None = None
        self._error = ""
        self._draft_revision = 0

    def bind_controller(self, controller: CompanionController) -> None:
        self._controller = controller
        self._render_page()

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._draft_revision += 1
        self._description = ""
        self._selected = {}
        self._options = {}
        self._unlocked_page = 0
        self._generating_field = None
        self._error = ""
        if self._active:
            super().switch_tab(0)
        self._render_page()

    def can_enter_insert(self) -> bool:
        return 0 <= self._active <= len(CHARACTER_FIELDS)

    def input_spec(self) -> InputSpec:
        if self._active == 0:
            field = "description"
            label = "旅伴描述"
            value = self._description
        elif 1 <= self._active <= len(CHARACTER_FIELDS):
            field = CHARACTER_FIELDS[self._active - 1]
            label = CHARACTER_FIELD_LABELS[field]
            value = ""
        else:
            field = "confirm"
            label = ""
            value = ""
        return InputSpec(
            context_id=f"companion-creation:{field}",
            placeholder=f"输入{label}" if label else "",
            visible=field != "confirm",
            enabled=field != "confirm",
            value=value,
            focus=True,
        )

    def prepare_insert(self) -> None:
        self.activate_input_context()

    def nav(self, action: str) -> None:
        if action == "tab_prev":
            if self._active > 0:
                self._switch_page(self._active - 1)
            return
        if action == "tab_next":
            if self._active < self._unlocked_page:
                self._switch_page(self._active + 1)
                self._ensure_active_page_options()
            return
        if self._active == 0:
            return
        if 1 <= self._active <= len(CHARACTER_FIELDS):
            field = CHARACTER_FIELDS[self._active - 1]
            if self._generating_field == field:
                return
            self._nav_options(action)
            return
        if self._active == len(_PAGES) - 1 and action == "enter":
            self._create_companion()

    def _switch_page(self, index: int) -> None:
        if index < 0 or index > self._unlocked_page:
            return
        super().switch_tab(index)
        if 1 <= index <= len(CHARACTER_FIELDS):
            field = CHARACTER_FIELDS[index - 1]
            self._set_field_options(field)
            selected = self._selected.get(field)
            if selected:
                self.selection.select(selected)
        self._render_page()

    def _ensure_active_page_options(self) -> None:
        if 1 <= self._active <= len(CHARACTER_FIELDS):
            self._ensure_options(CHARACTER_FIELDS[self._active - 1])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.can_enter_insert():
            return
        field = (
            "description"
            if self._active == 0
            else CHARACTER_FIELDS[self._active - 1]
        )
        value = self.submit_input(event, clear=True).strip()
        if self._generating_field is not None:
            self._error = "正在生成选项，本次输入无效。"
            self._render_page()
            return
        if not value:
            self._error = "输入不能为空。"
            self._render_page()
            return
        if field != "description":
            options = self._options.setdefault(field, [])
            if value not in options:
                options.append(value)
            self._set_field_options(field)
            self.selection.select(value)
            self._error = ""
            self._render_page()
            return
        self._description = value
        self._draft_revision += 1
        self._error = ""
        self._unlocked_page = max(self._unlocked_page, 1)
        self._switch_page(1)
        self._ensure_options(CHARACTER_FIELDS[0])

    def _nav_options(self, action: str) -> None:
        field = CHARACTER_FIELDS[self._active - 1]
        self._set_field_options(field)
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._render_page()
        elif selected is not None:
            if selected.id == "regenerate":
                self._generate_options(field)
            else:
                self._select_value(field, selected.id)

    def _select_value(self, field: str, value: str) -> None:
        self._selected[field] = value
        page = CHARACTER_FIELDS.index(field) + 1
        next_page = page + 1
        self._unlocked_page = max(self._unlocked_page, next_page)
        self._switch_page(next_page)
        if next_page <= len(CHARACTER_FIELDS):
            self._ensure_options(CHARACTER_FIELDS[next_page - 1])

    def _ensure_options(self, field: str) -> None:
        if (
            field not in self._options
            and self._generating_field != field
        ):
            self._generate_options(field)

    def _set_field_options(self, field: str) -> None:
        options = self._options.get(field, [])
        self.set_options(
            [*(Option(value, value) for value in options),
             Option("regenerate", "重新生成")],
            f"companion-creation:{field}",
        )

    def _generate_options(self, field: str) -> None:
        controller = self._controller
        if controller is None or self._generating_field == field:
            return
        self._generating_field = field
        self._draft_revision += 1
        revision = self._draft_revision
        self._error = ""
        self._render_page()
        self._generate_options_worker(field, revision)

    @work(exclusive=True, group="companion-character-options")
    async def _generate_options_worker(
        self, field: str, revision: int,
    ) -> None:
        controller = self._controller
        if controller is None:
            self._finish_generation(
                field, [], "旅伴服务不可用。", revision)
            return
        try:
            options = await controller.generate_character_options(
                self._description,
                dict(self._selected),
                field,
            )
        except Exception as exc:
            self._finish_generation(
                field, [], f"生成失败：{exc}", revision)
            return
        self._finish_generation(field, options, "", revision)

    def _finish_generation(
        self,
        field: str,
        options: list[str],
        error: str,
        revision: int,
    ) -> None:
        if revision != self._draft_revision:
            return
        self._generating_field = None
        if options:
            self._options[field] = options
        self._error = error
        if (
            1 <= self._active <= len(CHARACTER_FIELDS)
            and CHARACTER_FIELDS[self._active - 1] == field
        ):
            self._render_page()

    def _render_page(self) -> None:
        if not self.is_mounted:
            return
        if self._active == 0:
            text = (
                f"当前描述\n{ICON_INDENT}{escape(self._description)}"
                if self._description
                else "按 i 输入旅伴描述。"
            )
            if self._error:
                text += f"\n\n{escape(self._error)}"
            self.update(f"[{COLOR_FG_TERTIARY}]{text}[/]")
            return
        if 1 <= self._active <= len(CHARACTER_FIELDS):
            self._render_options()
            return
        self._render_confirmation()

    def reflow_content(self) -> None:
        self._render_page()

    def _render_options(self) -> None:
        field = CHARACTER_FIELDS[self._active - 1]
        if self._generating_field == field:
            lines = [
                f"[{COLOR_FG_TERTIARY}]正在生成"
                f"{CHARACTER_FIELD_LABELS[field]}选项。[/]",
            ]
            if self._error:
                lines.extend(("", f"[{COLOR_FG_TERTIARY}]"
                                  f"{escape(self._error)}[/]"))
            self.update("\n".join(lines))
            return
        parts = []
        selected = self._selected.get(field, "")
        if selected:
            parts.extend([
                f"[{COLOR_FG_TERTIARY}]"
                f"当前选择：{escape(selected)}[/]",
                "",
            ])
        self._set_field_options(field)
        parts.append(Text.from_markup(self.render_options()))
        if self._error:
            parts.extend([
                "",
                f"[{COLOR_FG_TERTIARY}]{escape(self._error)}[/]",
            ])
        self.query_one(f"#t{self._active} .content").update(Group(*parts))

    def _render_confirmation(self) -> None:
        lines = [
            f"[{COLOR_FG_TERTIARY}]"
            f"初始描述：{escape(self._description)}[/]",
            "",
        ]
        for field in CHARACTER_FIELDS:
            lines.append(
                f"[{COLOR_FG_TERTIARY}]"
                f"{CHARACTER_FIELD_LABELS[field]}："
                f"{escape(self._selected.get(field, ''))}[/]")
        self.set_options(
            (Option("create", "创建旅伴"),),
            "companion-creation:confirm",
        )
        lines.extend(["", self.render_options()])
        self.update("\n".join(lines))

    def _create_companion(self) -> None:
        if any(not self._selected.get(field) for field in CHARACTER_FIELDS):
            return
        character = Character(
            id=generate_char_id(),
            name=self._selected["name"],
            personality=self._selected["personality"],
            speech_style=self._selected["speech_style"],
            appearance=self._selected["appearance"],
            backstory=self._selected["backstory"],
            custom_rules=[],
            created_at=time.time(),
        )
        save_character(character)
        controller = self._controller
        if controller:
            controller.load_character(character.id)
        self.post_message(self.Created(character.name))


class CompanionCreationWindow(Window):
    DEFAULT_CSS = """
    CompanionCreationWindow {
        layer: floating;
        width: 72%;
        height: 72%;
    }
    CompanionCreationWindow > #companion-creation-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["companion-creation-panel"]]
    primary_panel = "companion-creation-panel"
    spec = WindowSpec(
        id="companion-creation-window",
        title="创建旅伴",
        group="companion",
        order=10,
        preconditions=(logged_in,),
        bind=bind_state,
    )

    def compose(self) -> ComposeResult:
        yield CompanionCreationPanel(id="companion-creation-panel")

    def bind_state(self, state) -> None:
        panel = self.query_one(
            "#companion-creation-panel", CompanionCreationPanel)
        panel.bind_controller(CompanionController.instance(state))

register_window(CompanionCreationWindow)
