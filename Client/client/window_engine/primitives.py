"""Shared visual and interaction primitives for registered windows.

The classes in this module deliberately keep selection and input state out of
individual views.  They are small enough to be used by a Textual widget, a
modal screen, or a pure unit test.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable

from textual.geometry import Size
from textual.widgets import Input, Static
from rich.markup import escape

from .text import cell_width, grapheme_clusters, wrap_cells


@dataclass(frozen=True)
class Option:
    """One selectable row with a stable identity.

    ``id`` is intentionally separate from the display label: refreshes in the
    same interaction context retain the selected id even when labels change.
    Disabled rows remain visible but are skipped by keyboard navigation.
    """

    id: str
    label: str
    description: str = ""
    enabled: bool = True
    data: Any = None
    markup: bool = False
    description_align: str = "inline"


class SelectList:
    """Keyboard selection state shared by lists, submenus, and modal choices."""

    def __init__(self, options: Iterable[Option] = (), context_id: str = ""):
        self._options: tuple[Option, ...] = ()
        self._context_id = ""
        self._selected_id: str | None = None
        self._selections: dict[str, str] = {}
        self.set_options(options, context_id)

    @property
    def options(self) -> tuple[Option, ...]:
        return self._options

    @property
    def context_id(self) -> str:
        return self._context_id

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def selected(self) -> Option | None:
        if self._selected_id is None:
            return None
        return next(
            (option for option in self._options if option.id == self._selected_id),
            None,
        )

    @property
    def index(self) -> int:
        selected = self.selected
        if selected is None:
            return -1
        return self._options.index(selected)

    def set_options(
        self,
        options: Iterable[Option],
        context_id: str,
    ) -> None:
        """Replace rows, preserving selection only in the same context."""
        new_options = tuple(options)
        if self._context_id and self._selected_id:
            self._selections[self._context_id] = self._selected_id
        selected_id = (
            self._selected_id
            if context_id == self._context_id
            else self._selections.get(context_id)
        )
        self._options = new_options
        self._context_id = context_id
        if selected_id and any(
            option.id == selected_id and option.enabled for option in new_options
        ):
            self._selected_id = selected_id
            self._selections[context_id] = selected_id
            return
        self._selected_id = next(
            (option.id for option in new_options if option.enabled),
            None,
        )
        if self._selected_id is not None:
            self._selections[context_id] = self._selected_id

    def reset(self) -> None:
        """Reset to the first actionable row in the existing context."""
        self._selected_id = next(
            (option.id for option in self._options if option.enabled),
            None,
        )

    def select(self, option_id: str) -> bool:
        option = next(
            (item for item in self._options if item.id == option_id and item.enabled),
            None,
        )
        if option is None:
            return False
        self._selected_id = option.id
        self._selections[self._context_id] = option.id
        return True

    def move(self, delta: int) -> bool:
        """Move with wrapping while skipping disabled rows."""
        if not self._options or delta == 0:
            return False
        current = self.index
        if current < 0:
            self.reset()
            return self.selected is not None
        step = 1 if delta > 0 else -1
        for distance in range(1, len(self._options) + 1):
            index = (current + step * distance) % len(self._options)
            if self._options[index].enabled:
                self._selected_id = self._options[index].id
                self._selections[self._context_id] = self._selected_id
                return index != current
        return False

    def handle(self, action: str) -> Option | None:
        if action == "up":
            self.move(-1)
        elif action == "down":
            self.move(1)
        elif action == "enter":
            return self.selected
        return None

    def render(
        self,
        width: int,
        *,
        selected_prefix: str = "> ",
        idle_prefix: str = "  ",
        selected_style: str = "bold",
        idle_style: str = "dim",
        disabled_style: str = "dim",
    ) -> str:
        """Render fixed-prefix, cell-aware rows for a Textual ``Static``.

        The optional description starts after a stable prefix and is wrapped to
        the same text column.  Callers may supply Rich styles but never need to
        measure Unicode text themselves.
        """
        lines: list[str] = []
        for option in self._options:
            lines.extend(self.render_option(
                option,
                width,
                selected_prefix=selected_prefix,
                idle_prefix=idle_prefix,
                selected_style=selected_style,
                idle_style=idle_style,
                disabled_style=disabled_style,
            ))
        return "\n".join(lines)

    def selected_line(self, width: int, **styles: str) -> int:
        """Return the rendered start line of the selected option."""
        if self.index < 0:
            return -1
        return sum(
            len(self.render_option(option, width, **styles))
            for option in self._options[:self.index]
        )

    def render_option(
        self,
        option: Option,
        width: int,
        *,
        selected_prefix: str = "> ",
        idle_prefix: str = "  ",
        selected_style: str = "bold",
        idle_style: str = "dim",
        disabled_style: str = "dim",
    ) -> list[str]:
        """Render one option with the same prefix and wrapping contract."""
        prefix_width = max(cell_width(selected_prefix), cell_width(idle_prefix))
        text_width = max(1, width - prefix_width)
        selected = option.id == self._selected_id
        prefix = selected_prefix if selected else idle_prefix
        prefix += " " * max(0, prefix_width - cell_width(prefix))
        content = option.label if option.markup else escape(option.label)
        if option.description:
            description = escape(option.description)
            if option.description_align == "right":
                gap = max(
                    2,
                    text_width
                    - cell_width(option.label)
                    - cell_width(option.description),
                )
                content = f"{content}{' ' * gap}{description}"
            else:
                content = f"{content}  {description}"
        # Hidden windows have no measured width yet. Leave their rows unwrapped;
        # Textual can lay them out safely until the window's post-show reflow.
        rows = (
            wrap_cells(content, text_width) or [""]
            if width > prefix_width
            else [content]
        )
        style = (
            selected_style
            if selected
            else idle_style
            if option.enabled
            else disabled_style
        )
        rendered = [f"[{style}]{prefix}{rows[0]}[/]"]
        indent = " " * prefix_width
        rendered.extend(
            f"[{style}]{indent}{row}[/]" for row in rows[1:])
        return rendered


def move_option_index(
    options: Iterable[Option],
    current: int,
    delta: int,
) -> int:
    """Apply the shared non-wrapping option navigation to an index state."""
    selection = SelectList(options, "indexed-options")
    selection.select(str(current))
    selection.move(delta)
    return max(selection.index, 0)


class ConfirmMenu:
    """Two-action confirmation menu backed by the same selection contract."""

    YES_ID = "yes"
    NO_ID = "no"

    def __init__(self) -> None:
        self.message = ""
        self._open = False
        self._list = SelectList()

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def selection(self) -> SelectList:
        return self._list

    def open(
        self,
        message: str,
        *,
        context_id: str,
        yes_label: str = "是",
        no_label: str = "否",
    ) -> None:
        self.message = message
        self._open = True
        self._list.set_options(
            (
                Option(self.YES_ID, yes_label),
                Option(self.NO_ID, no_label),
            ),
            context_id,
        )
        self._list.select(self.YES_ID)

    def close(self) -> None:
        self._open = False
        self.message = ""

    def handle(self, action: str) -> str | None:
        """Return ``yes`` or ``no`` after Enter confirms the selected row."""
        if not self._open:
            return None
        selected = self._list.handle(action)
        if selected is None:
            return None
        result = selected.id
        self.close()
        return result

    def render(self, width: int, **styles: str) -> str:
        if not self._open:
            return ""
        rendered = self._list.render(width, **styles)
        return f"{self.message}\n\n{rendered}" if rendered else self.message


@dataclass
class InputSpec:
    """Declared input intent for one panel context or tab."""

    context_id: str = "default"
    placeholder: str = ""
    visible: bool = True
    enabled: bool = True
    password: bool = False
    value: str = ""
    focus: bool = False
    on_submit: Callable[[str], None] | None = None
    on_cancel: Callable[[str], None] | None = None


class InputSession:
    """Owns an Input widget's visible, editable, and IME-facing lifecycle."""

    def __init__(self, spec: InputSpec | None = None) -> None:
        self._spec = spec or InputSpec()
        self._widget = None
        self._row = None
        self._divider = None
        self._region = None
        self._editing = False
        self._sticky = False
        self._active = True
        self._drafts: dict[str, str] = {}

    @property
    def spec(self) -> InputSpec:
        return self._spec

    @property
    def editing(self) -> bool:
        return self._editing

    @property
    def sticky(self) -> bool:
        return self._sticky

    @property
    def value(self) -> str:
        if self._widget is not None:
            return self._widget.value
        return self._spec.value

    def mount(self, widget, row=None, divider=None, region=None) -> None:
        self._widget = widget
        self._row = row
        self._divider = divider
        self._region = region
        self.sync()

    def configure(self, **changes: Any) -> None:
        allowed = {
            "context_id",
            "placeholder",
            "visible",
            "enabled",
            "password",
            "value",
            "focus",
            "on_submit",
            "on_cancel",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown input properties: {sorted(unknown)}")
        for name, value in changes.items():
            setattr(self._spec, name, value)
        self.sync()

    def replace(self, spec: InputSpec) -> None:
        current_context = self._spec.context_id
        current_value = self.value
        if current_context:
            self._drafts[current_context] = current_value
        context_changed = spec.context_id != current_context
        if context_changed:
            spec.value = self._drafts.get(spec.context_id, spec.value)
        else:
            spec.value = current_value
        self._spec = spec
        if context_changed and not self._sticky:
            self._editing = False
        self.sync()

    def enter(self, *, sticky: bool = False) -> bool:
        if not self._spec.visible or not self._spec.enabled or self._widget is None:
            return False
        self._editing = True
        self._sticky = sticky
        self.sync()
        return True

    def leave(self, *, preserve: bool = True) -> None:
        was_editing = self._editing
        current = self.value
        if preserve:
            self._spec.value = current
            self._drafts[self._spec.context_id] = current
        elif self._widget is not None:
            self._widget.value = ""
            self._spec.value = ""
        self._editing = False
        self._sticky = False
        if was_editing and self._spec.on_cancel is not None:
            self._spec.on_cancel(self._spec.value)
        self.sync()

    def submit(self, value: str | None = None, *, clear: bool = False) -> str:
        submitted = self.value if value is None else value
        self._spec.value = submitted
        if self._spec.on_submit is not None:
            self._spec.on_submit(submitted)
        if clear:
            self.clear()
        return submitted

    def clear(self) -> None:
        self._spec.value = ""
        if self._widget is not None:
            self._widget.value = ""
        self._drafts[self._spec.context_id] = ""

    def set_active(self, active: bool) -> None:
        """Gate editing and focus without discarding the input session."""
        self._active = active
        self.sync()

    def sync(self) -> None:
        if self._region is not None:
            self._region.display = self._spec.visible
        if self._row is not None:
            self._row.display = self._spec.visible
        if self._divider is not None:
            self._divider.display = self._spec.visible
        if self._widget is None:
            return
        self._widget.placeholder = self._spec.placeholder
        self._widget.password = self._spec.password
        self._widget.disabled = not (
            self._active
            and self._spec.visible
            and self._spec.enabled
            and self._editing
        )
        if self._widget.value != self._spec.value:
            self._widget.value = self._spec.value
        if self._active and self._editing and self._spec.focus:
            self._widget.focus()


class EngineInput(Input):
    """Single-line input that always keeps its cell-aware cursor in view."""

    DEFAULT_CSS = """
    EngineInput {
        overflow-x: hidden;
        scrollbar-size-horizontal: 0;
    }
    """

    def _watch_value(self, value: str) -> None:
        super()._watch_value(value)
        self.virtual_size = Size(self.content_width + 2, 1)

    def _watch_selection(self, selection) -> None:
        super()._watch_selection(selection)
        self.call_after_refresh(self._sync_cursor_viewport)

    def _sync_cursor_viewport(self) -> None:
        width = self.scrollable_content_region.width
        if width <= 0:
            return
        cursor = self._cursor_offset
        current = self.scroll_offset.x
        if cursor < current:
            target = cursor
        elif cursor >= current + width:
            target = cursor - width + 1
        else:
            target = current
        target = self._grapheme_cell_boundary(target)
        self.scroll_to(
            x=max(0, target),
            animate=False,
            force=True,
            immediate=True,
        )

    def _grapheme_cell_boundary(self, target: int) -> int:
        if target <= 0 or self.password:
            return max(0, target)
        offset = 0
        for cluster in grapheme_clusters(self.value):
            if offset >= target:
                return offset
            offset += cell_width(cluster)
        return offset


class ScrollPolicy:
    """Keep scroll position and text layout stable as scrollbars change."""

    @staticmethod
    def content_width(content, scroll) -> int:
        """Return text width with the configured vertical scrollbar reserved."""
        width = content.content_region.width
        if width <= 0:
            return 0
        if not scroll.show_vertical_scrollbar:
            width -= scroll.styles.scrollbar_size_vertical
        return max(width, 1)

    @staticmethod
    def set_vertical_visible(scroll, visible: bool) -> None:
        """Declare whether a scroll surface reserves a vertical scrollbar."""
        scroll.styles.scrollbar_size_vertical = 1 if visible else 0

    @staticmethod
    def at_bottom(scroll) -> bool:
        return scroll.scroll_offset.y >= scroll.max_scroll_y - 1

    @classmethod
    def update(cls, scroll, update: Callable[[], None], defer: Callable | None = None) -> None:
        at_bottom = cls.at_bottom(scroll)
        update()
        if at_bottom:
            if defer is not None:
                defer(scroll.scroll_end, animate=False)
            else:
                scroll.scroll_end(animate=False)


class SurfaceKind(str, Enum):
    CONTENT = "content"
    LOADING = "loading"
    EMPTY = "empty"
    ERROR = "error"


@dataclass(frozen=True)
class SurfaceState:
    """Shared loading/empty/error state for panel content."""

    kind: SurfaceKind = SurfaceKind.CONTENT
    message: str = ""
    detail: str = ""

    @classmethod
    def loading(cls, message: str = "正在加载…") -> "SurfaceState":
        return cls(SurfaceKind.LOADING, message)

    @classmethod
    def empty(cls, message: str = "暂无内容") -> "SurfaceState":
        return cls(SurfaceKind.EMPTY, message)

    @classmethod
    def error(cls, message: str, detail: str = "") -> "SurfaceState":
        return cls(SurfaceKind.ERROR, message, detail)

    def render(self, indent: str = "") -> str:
        suffix = f"\n{indent}{self.detail}" if self.detail else ""
        return f"{indent}{self.message}{suffix}"


class Divider(Static):
    """A width-aware layout separator; never synthesize horizontal-rule text."""

    DEFAULT_CSS = """
    Divider {
        width: 1fr;
        height: 1;
        border-top: solid $foreground 30%;
        background: transparent;
    }
    """

    def __init__(self, *, style: str | None = None, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._divider_style = style

    def on_mount(self) -> None:
        if self._divider_style:
            self.styles.border_top = ("solid", self._divider_style)
