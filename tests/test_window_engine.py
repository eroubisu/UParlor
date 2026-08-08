"""WindowEngine 核心单元测试 — 纯逻辑, 不依赖 textual"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.screen_nav import NavigationMixin
from client.screen_modes import InputModeMixin
from client.window_engine import (
    ConfirmMenu,
    InputSession,
    InputSpec,
    Option,
    OverlayStack,
    SelectList,
    ScrollPolicy,
    WindowEngine,
    WindowSpec,
)
from client.window_engine.registry import WindowRegistry


# ── OverlayStack ──

def test_scroll_policy_reserves_vertical_scrollbar_width():
    content = SimpleNamespace(
        content_region=SimpleNamespace(width=68),
    )
    scroll = SimpleNamespace(
        show_vertical_scrollbar=False,
        styles=SimpleNamespace(scrollbar_size_vertical=1),
    )

    before = ScrollPolicy.content_width(content, scroll)
    content.content_region.width = 67
    scroll.show_vertical_scrollbar = True
    after = ScrollPolicy.content_width(content, scroll)

    assert before == after == 67


def test_overlay_stack_push_pop():
    s = OverlayStack()
    s.push('a'); s.push('b'); s.push('c')
    assert s.snapshot() == ['a', 'b', 'c']
    assert s.top() == 'c'
    assert s.pop_top() == 'c'
    assert s.snapshot() == ['a', 'b']


def test_overlay_stack_lru_push():
    """push 已存在元素时应移到栈顶"""
    s = OverlayStack()
    s.push('a'); s.push('b'); s.push('c'); s.push('a')
    assert s.snapshot() == ['b', 'c', 'a']


def test_overlay_stack_remove():
    s = OverlayStack()
    s.push('a'); s.push('b'); s.push('c')
    assert s.remove('b')
    assert s.snapshot() == ['a', 'c']
    assert not s.remove('xxx')


def test_overlay_stack_empty():
    s = OverlayStack()
    assert s.top() is None
    assert s.pop_top() is None
    assert not s.contains('x')
    assert len(s) == 0


# ── Registry ──

@pytest.fixture
def fresh_registry():
    return WindowRegistry()


def test_registry_register_basic(fresh_registry):
    class W:
        spec = WindowSpec(id='w1', title='One')
    fresh_registry.register(W)
    assert fresh_registry.get('w1') is W
    assert fresh_registry.spec('w1').title == 'One'


def test_registry_rejects_missing_spec(fresh_registry):
    class Bad:
        pass
    with pytest.raises(TypeError):
        fresh_registry.register(Bad)


def test_registry_rejects_id_conflict(fresh_registry):
    class A:
        spec = WindowSpec(id='dup', title='A')
    class B:
        spec = WindowSpec(id='dup', title='B')
    fresh_registry.register(A)
    with pytest.raises(ValueError):
        fresh_registry.register(B)


def test_registry_rejects_invalid_window_mode(fresh_registry):
    class Bad:
        spec = WindowSpec(id='bad', mode='prmary')

    with pytest.raises(ValueError, match="mode"):
        fresh_registry.register(Bad)


def test_registry_accepts_popup_window_mode(fresh_registry):
    class Popup:
        spec = WindowSpec(id='popup', mode='popup')

    fresh_registry.register(Popup)
    assert fresh_registry.spec('popup').mode == 'popup'


def test_registry_by_group_and_menu_entries(fresh_registry):
    class W1:
        spec = WindowSpec(
            id='w1', title='One', menu=True, group='root', order=20)
    class W2:
        spec = WindowSpec(
            id='w2', title='Two', menu=True, group='root', order=10)
    class W3:
        spec = WindowSpec(id='w3', title='Three', group='settings')
    for w in (W1, W2, W3):
        fresh_registry.register(w)
    # by_group 按 order 排序
    root = fresh_registry.by_group('root')
    assert [s.id for s in root] == ['w2', 'w1']
    settings = fresh_registry.by_group('settings')
    assert [s.id for s in settings] == ['w3']
    # menu_entries 仅含显式菜单项
    assert [s.id for s in fresh_registry.menu_entries('root')] == ['w2', 'w1']
    assert fresh_registry.menu_entries('settings') == []


def test_engine_composes_registered_windows_as_inactive():
    class RegisteredWindow:
        spec = WindowSpec(id="registered", title="Registered")

        def __init__(self, *, id):
            self.id = id
            self.active = True

        def set_active(self, active):
            self.active = active

    registry = WindowRegistry()
    registry.register(RegisteredWindow)
    engine = WindowEngine(registry)

    window = next(engine.compose_all())

    assert not window.active


# ── Engine (mocked host) ──

class _FakeWidget:
    def __init__(self, wid):
        self.id = wid
        self._visible = False
        self.active = False
        self.show_calls = 0
        self.bind_calls = []
        self.classes = set()

    def show(self):
        self._visible = True
        self.show_calls += 1

    def hide(self):
        self._visible = False

    def has_class(self, c):
        return c == 'visible' and self._visible

    def set_active(self, active):
        self.active = active

    def add_class(self, class_name):
        self.classes.add(class_name)


class _FakeHost:
    def __init__(self, ids):
        self._widgets = {wid: _FakeWidget(wid) for wid in ids}

    def query_one(self, sel, *_):
        wid = sel.lstrip('#')
        if wid not in self._widgets:
            raise Exception(f'not found: {wid}')
        return self._widgets[wid]


def _make_engine(specs, ctx=None):
    reg = WindowRegistry()
    for s in specs:
        cls = type(f'W_{s.id}', (), {'spec': s})
        reg.register(cls)
    e = WindowEngine(reg)
    host = _FakeHost([s.id for s in specs])
    e.attach(host, lambda: ctx or {})
    return e, host


def test_engine_open_floating():
    e, host = _make_engine([
        WindowSpec(id='w1', title='One'),
    ])
    assert e.open('w1')
    assert e.is_open('w1')
    assert e.active_id() is None
    e._on_presentation_stage('w1', 'presenting')
    assert e.active_id() == 'w1'


def test_engine_preconditions():
    ctx = {'logged_in': False}
    e, _ = _make_engine([
        WindowSpec(id='w1', title='One',
                   preconditions=(lambda c: c['logged_in'],)),
    ], ctx)
    assert not e.open('w1')
    ctx['logged_in'] = True
    assert e.open('w1')


def test_engine_menu_items_are_selection_targets():
    e, _ = _make_engine([
        WindowSpec(id='w1', title='A', menu=True),
        WindowSpec(id='w2', title='B', menu=True),
    ])
    assert e.menu_items('root') == [('A', 'w1'), ('B', 'w2')]
    assert e.open('w2')
    e._on_presentation_stage('w2', 'presenting')
    assert e.active_id() == 'w2'


def test_engine_close_top():
    e, _ = _make_engine([
        WindowSpec(id='w1', title='One'),
        WindowSpec(id='w2', title='Two'),
    ])
    e.open('w1')
    e._on_presentation_stage('w1', 'presenting')
    e.open('w2')
    e._on_presentation_stage('w2', 'presenting')
    assert e.close_top()
    assert e.active_id() is None
    assert not e.close_top()


def test_floating_window_replaces_previous_at_presentation_commit():
    e, _ = _make_engine([
        WindowSpec(id='first', title='First'),
        WindowSpec(id='second', title='Second'),
    ])
    assert e.open('first')
    e._on_presentation_stage('first', 'presenting')
    assert e.open('second')
    assert e.is_open('first')
    assert e.is_open('second')
    assert e.active_id() == 'first'

    e._on_presentation_stage('second', 'presenting')

    assert not e.is_open('first')
    assert e.is_open('second')
    assert e.active_id() == 'second'


def test_new_floating_request_cancels_older_pending_presentation():
    e, host = _make_engine([
        WindowSpec(id='current', title='Current'),
        WindowSpec(id='stale', title='Stale'),
        WindowSpec(id='latest', title='Latest'),
    ])
    assert e.open('current')
    e._on_presentation_stage('current', 'presenting')

    assert e.open('stale')
    assert e.open('latest')
    assert not e.is_open('stale')
    assert e.active_id() == 'current'

    e._on_presentation_stage('stale', 'presenting')
    assert e.active_id() == 'current'
    assert host._widgets['current'].active

    e._on_presentation_stage('latest', 'presenting')
    assert e.active_id() == 'latest'
    assert not e.is_open('current')


def test_popup_covers_floating_without_replacing_it():
    e, _ = _make_engine([
        WindowSpec(id='floating', title='Floating'),
        WindowSpec(id='menu', title='Menu', mode='popup'),
    ])
    assert e.open('floating')
    e._on_presentation_stage('floating', 'presenting')
    assert e.open('menu')
    assert e.active_id() == 'floating'
    e._on_presentation_stage('menu', 'presenting')

    assert e.is_open('floating')
    assert e.is_open('menu')
    assert e.active_id() == 'menu'
    assert e.close_top()
    assert e.active_id() == 'floating'


def test_popup_cover_pauses_sticky_input_without_ending_session():
    from client.widgets.window import Window

    panel = SimpleNamespace(
        leave_insert=Mock(),
        sync_primitives=Mock(),
    )
    window = SimpleNamespace(
        _activation_managed=False,
        _active=True,
        _panels={"panel": panel},
        focused_panel=panel,
        set_class=Mock(),
    )

    Window.set_active(window, False)

    panel.leave_insert.assert_not_called()
    panel.sync_primitives.assert_not_called()


def test_inactive_window_focus_change_keeps_every_panel_inactive():
    from client.widgets.window import Window

    old = SimpleNamespace(
        remove_class=Mock(),
        on_panel_blur=Mock(),
        sync_primitives=Mock(),
    )
    new = SimpleNamespace(
        add_class=Mock(),
        on_panel_focus=Mock(),
        sync_primitives=Mock(),
    )
    window = SimpleNamespace(
        _activation_managed=True,
        _active=False,
        _panels={"old": old, "new": new},
        focused_panel=new,
        sync_primitives=lambda: Window.sync_primitives(window),
    )

    Window._apply_focus_change(window)

    old.sync_primitives.assert_called_once_with(active=False)
    new.sync_primitives.assert_called_once_with(active=False)


def test_managed_window_mount_applies_inactive_state_to_panels():
    from client.widgets.window import Window

    panel = SimpleNamespace(id="panel", add_class=Mock())
    window = SimpleNamespace(
        _focus_pos=(0, 0),
        _default_focus_pos=(0, 0),
        _panels={},
        _activation_managed=True,
        _active=False,
        focus_grid=[["panel"]],
        query=lambda _kind: [panel],
        sync_primitives=Mock(),
    )

    Window.on_mount(window)

    window.sync_primitives.assert_called_once_with()


def test_open_from_popup_commits_popup_and_floating_replacement_together():
    e, _ = _make_engine([
        WindowSpec(id='old', title='Old'),
        WindowSpec(id='menu', title='Menu', mode='popup'),
        WindowSpec(id='new', title='New'),
    ])
    assert e.open('old')
    e._on_presentation_stage('old', 'presenting')
    assert e.open('menu')
    e._on_presentation_stage('menu', 'presenting')
    assert e.open_from_popup('menu', 'new')
    assert e.is_open('old')
    assert e.is_open('menu')
    assert e.active_id() == 'menu'

    e._on_presentation_stage('new', 'presenting')

    assert not e.is_open('old')
    assert not e.is_open('menu')
    assert e.is_open('new')
    assert e.active_id() == 'new'


def test_close_top_never_closes_primary_location_window():
    e, _ = _make_engine([
        WindowSpec(id="waiting", title="Waiting", mode="primary"),
        WindowSpec(id="chat", title="Chat"),
    ])
    assert e.open("waiting")
    e._on_presentation_stage("waiting", "presenting")

    assert not e.close_top()
    assert e.active_id() == "waiting"
    assert e.is_open("waiting")

    assert e.open("chat")
    assert e.active_id() == "waiting"
    assert not e.close_top()
    e._on_presentation_stage("chat", "presenting")
    assert e.close_top()
    assert e.active_id() == "waiting"
    assert e.is_open("waiting")


def test_engine_close_rejects_primary_location_window():
    e, _ = _make_engine([
        WindowSpec(id="waiting", title="Waiting", mode="primary"),
    ])
    assert e.open("waiting")
    e._on_presentation_stage("waiting", "presenting")

    assert not e.close("waiting")
    assert e.active_id() == "waiting"
    assert e.is_open("waiting")


def test_companion_creation_replaces_settings_overlay():
    e, _ = _make_engine([
        WindowSpec(id='companion-window', title='Companion'),
        WindowSpec(id='companion-creation-window', title='Create'),
    ])
    host = type('_NavigationHost', (NavigationMixin,), {'engine': e})()
    event = type('_Event', (), {'stop': lambda self: None})()
    e.open('companion-window')
    e._on_presentation_stage('companion-window', 'presenting')

    host.on_companion_panel_open_creation(event)

    e._on_presentation_stage('companion-creation-window', 'presenting')

    assert not e.is_open('companion-window')
    assert e.is_open('companion-creation-window')
    assert e.active_id() == 'companion-creation-window'


def test_insert_mode_prepares_focused_text_field(monkeypatch):
    from client import ime

    class _Input:
        disabled = True
        focused = False

        def focus(self):
            self.focused = True

    class _Panel:
        prepared = False
        sticky = None
        input = _Input()

        def can_enter_insert(self):
            return True

        def prepare_insert(self):
            self.prepared = True

        def get_input_widget(self):
            return self.input

        def enter_insert(self, *, sticky=False):
            self.sticky = sticky
            self.prepare_insert()
            self.input.disabled = False
            self.input.focus()
            return True

    panel = _Panel()
    indicator = type('_Indicator', (), {
        'update': lambda self, _text: None,
    })()
    host = type('_InputHost', (InputModeMixin,), {
        'engine': type('_Engine', (), {
            'active_focused_panel': lambda self: panel,
            'enter_insert': lambda self, *, sticky=False: panel.enter_insert(
                sticky=sticky),
        })(),
        'query_one': lambda self, *_args: indicator,
        '_mode': 'normal',
    })()
    monkeypatch.setattr(ime, "on_insert_enter", lambda: None)

    host._enter_insert(sticky=True)

    assert panel.prepared
    assert panel.sticky is True
    assert not panel.input.disabled
    assert panel.input.focused
    assert host._mode == "insert"


def test_engine_keeps_only_top_window_visually_active():
    e, host = _make_engine([
        WindowSpec(id='primary', title='Primary', mode='primary'),
        WindowSpec(id='overlay', title='Overlay'),
    ])
    primary = host._widgets['primary']
    overlay = host._widgets['overlay']

    e.set_primary('primary')
    e._on_presentation_stage('primary', 'presenting')
    assert primary.active
    assert not overlay.active

    e.open('overlay')
    assert primary.active
    assert not overlay.active
    e._on_presentation_stage('overlay', 'presenting')
    assert not primary.active
    assert overlay.active

    e.close_top()
    assert primary.active
    assert not overlay.active


def test_engine_set_primary_replaces_old():
    e, host = _make_engine([
        WindowSpec(id='p1', title='P1', mode='primary'),
        WindowSpec(id='p2', title='P2', mode='primary'),
    ])
    assert e.set_primary('p1')
    e._on_presentation_stage('p1', 'presenting')
    assert e.is_open('p1')
    assert e.set_primary('p2')
    assert e.is_open('p1')
    e._on_presentation_stage('p2', 'presenting')
    assert not e.is_open('p1')
    assert e.is_open('p2')
    assert not host._widgets['p1'].active
    assert host._widgets['p2'].active


def test_engine_primary_bind_failure_preserves_current_window():
    def fail_bind(_window, _context):
        raise RuntimeError("bind failed")

    e, host = _make_engine([
        WindowSpec(id='p1', title='P1', mode='primary'),
        WindowSpec(id='p2', title='P2', mode='primary', bind=fail_bind),
    ])
    assert e.set_primary('p1')
    e._on_presentation_stage('p1', 'presenting')

    with pytest.raises(RuntimeError, match="bind failed"):
        e.set_primary('p2')

    assert e.primary_id() == 'p1'
    assert e.active_id() == 'p1'
    assert host._widgets['p1'].active
    assert e.is_open('p1')
    assert not e.is_open('p2')


def test_engine_primary_show_failure_preserves_current_window():
    e, host = _make_engine([
        WindowSpec(id='p1', title='P1', mode='primary'),
        WindowSpec(id='p2', title='P2', mode='primary'),
    ])
    assert e.set_primary('p1')
    e._on_presentation_stage('p1', 'presenting')
    host._widgets['p2'].show = Mock(side_effect=RuntimeError("show failed"))

    with pytest.raises(RuntimeError, match="show failed"):
        e.set_primary('p2')

    assert e.primary_id() == 'p1'
    assert e.active_id() == 'p1'
    assert host._widgets['p1'].active
    assert e.is_open('p1')
    assert not e.is_open('p2')


def test_engine_reopening_active_primary_preserves_window_state():
    e, host = _make_engine([
        WindowSpec(id='waiting', title='Waiting', mode='primary'),
    ])
    waiting = host._widgets['waiting']

    e.set_primary('waiting')
    e._on_presentation_stage('waiting', 'presenting')
    e.set_primary('waiting')

    assert waiting.show_calls == 1


def test_engine_reopening_active_floating_preserves_window_state():
    e, host = _make_engine([
        WindowSpec(id='chat', title='Chat'),
    ])
    chat = host._widgets['chat']

    assert e.open('chat')
    e._on_presentation_stage('chat', 'presenting')
    assert e.open('chat')

    assert chat.show_calls == 1
    assert e.active_id() == 'chat'


def test_engine_listener_fires():
    e, _ = _make_engine([
        WindowSpec(id='w1', title='One'),
    ])
    events = []
    e.add_listener(lambda ev, wid: events.append((ev, wid)))
    e.open('w1')
    assert events == []
    e._on_presentation_stage('w1', 'presenting')
    e.close_top()
    assert events == [('open', 'w1'), ('close', 'w1')]


def test_engine_bind_invoked():
    calls = []
    e, host = _make_engine([
        WindowSpec(id='w1', title='One',
                   bind=lambda w, c: calls.append(('bind', w.id, c))),
    ], ctx={'k': 'v'})
    e.open('w1')
    assert calls == [('bind', 'w1', {'k': 'v'})]


def test_engine_bind_with_kwargs():
    calls = []
    def binder(w, c, **kw):
        calls.append(kw)
    e, _ = _make_engine([
        WindowSpec(id='w1', title='One', bind=binder),
    ])
    e.open('w1', peer='alice')
    assert calls == [{'peer': 'alice'}]


def test_engine_two_arg_bind_ignores_extra_kwargs_once():
    calls = []

    def binder(w, c):
        calls.append((w.id, c))

    e, _ = _make_engine([
        WindowSpec(id='w1', title='One', bind=binder),
    ], ctx={'k': 'v'})
    e.open('w1', peer='alice')
    assert calls == [('w1', {'k': 'v'})]


def test_engine_bind_internal_type_error_propagates_once():
    calls = []

    def binder(w, c, **kw):
        calls.append((w.id, kw))
        raise TypeError("binder defect")

    e, _ = _make_engine([
        WindowSpec(id='w1', title='One', bind=binder),
    ])
    with pytest.raises(TypeError, match="binder defect"):
        e.open('w1', peer='alice')
    assert calls == [('w1', {'peer': 'alice'})]


def test_select_list_preserves_ids_per_context_and_skips_disabled():
    selection = SelectList((
        Option("a", "A"),
        Option("disabled", "Disabled", enabled=False),
        Option("b", "B"),
    ), "root")

    selection.move(1)
    assert selection.selected_id == "b"

    selection.set_options((Option("child", "Child"),), "child")
    selection.set_options((
        Option("a", "A"),
        Option("disabled", "Disabled", enabled=False),
        Option("b", "B renamed"),
    ), "root")
    assert selection.selected_id == "b"


def test_select_list_wraps_across_enabled_rows():
    selection = SelectList((
        Option("a", "A"),
        Option("disabled", "Disabled", enabled=False),
        Option("b", "B"),
    ), "root")

    selection.move(-1)
    assert selection.selected_id == "b"
    selection.move(1)
    assert selection.selected_id == "a"


def test_select_list_does_not_stack_text_before_layout_has_width():
    selection = SelectList((Option("settings", "打开设置"),), "hidden-window")

    rendered = selection.render(1)

    assert rendered.count("\n") == 0
    assert "打开设置" in rendered


def test_select_list_reports_selected_line_after_wrapped_options():
    selection = SelectList((
        Option("long", "一二三四五六七八"),
        Option("target", "目标"),
    ), "wrapped-options")
    selection.select("target")

    assert selection.selected_line(8) == 3


def test_input_session_preserves_drafts_by_context():
    class _Input:
        value = ""
        placeholder = ""
        password = False
        disabled = True

        def focus(self):
            pass

    class _Row:
        display = False

    widget = _Input()
    row = _Row()
    session = InputSession(InputSpec(
        context_id="name", placeholder="输入名字", focus=True))
    session.mount(widget, row)

    assert session.enter()
    widget.value = "岚"
    session.leave(preserve=True)
    session.replace(InputSpec(context_id="personality"))
    session.replace(InputSpec(context_id="name"))

    assert widget.value == "岚"
    assert widget.disabled


def test_sticky_input_session_survives_context_and_disabled_transitions():
    class _Input:
        value = ""
        placeholder = ""
        password = False
        disabled = True
        focused = False

        def focus(self):
            self.focused = True

    widget = _Input()
    session = InputSession(InputSpec(
        context_id="username", enabled=True, focus=True,
    ))
    session.mount(widget)
    assert session.enter(sticky=True)

    session.replace(InputSpec(
        context_id="waiting", enabled=False, focus=True,
    ))
    assert session.editing
    assert session.sticky
    assert widget.disabled

    widget.focused = False
    session.replace(InputSpec(
        context_id="password", enabled=True, password=True, focus=True,
    ))
    assert session.editing
    assert session.sticky
    assert not widget.disabled
    assert widget.password
    assert widget.focused

    session.leave()
    assert not session.editing
    assert not session.sticky


def test_inactive_input_session_keeps_draft_without_enabling_or_focusing():
    class _Input:
        value = "draft"
        placeholder = ""
        password = False
        disabled = True
        focus_calls = 0

        def focus(self):
            self.focus_calls += 1

    widget = _Input()
    session = InputSession(InputSpec(
        context_id="chat", value="draft", focus=True,
    ))
    session.mount(widget)
    assert session.enter(sticky=True)
    assert widget.focus_calls == 1

    session.set_active(False)
    session.replace(InputSpec(context_id="chat", focus=True))

    assert session.editing
    assert session.sticky
    assert widget.value == "draft"
    assert widget.disabled
    assert widget.focus_calls == 1

    session.set_active(True)
    assert not widget.disabled
    assert widget.focus_calls == 2


def test_confirm_menu_requires_enter_on_explicit_no_option():
    confirmation = ConfirmMenu()
    confirmation.open("确认?", context_id="confirm")
    assert confirmation.selection.selected_id == ConfirmMenu.YES_ID

    confirmation.handle("down")
    assert confirmation.handle("enter") == ConfirmMenu.NO_ID

    confirmation.open("确认?", context_id="confirm")
    assert confirmation.selection.selected_id == ConfirmMenu.YES_ID

    confirmation.open("确认?", context_id="confirm-again")
    assert confirmation.handle("escape") is None
    assert confirmation.is_open
    confirmation.handle("down")
    assert confirmation.handle("enter") == ConfirmMenu.NO_ID


def test_global_keys_are_limited_to_five_action_categories():
    from client.input_actions import (
        focus_direction, is_exit_key, is_popup_key, navigation_action,
        text_input_mode,
    )

    for key in ("up", "w", "k"):
        assert navigation_action(key) == "up"
    for key in ("right", "d", "l"):
        assert navigation_action(key) == "tab_next"
    for key in ("enter", "z"):
        assert navigation_action(key) == "enter"
    for key in ("escape", "x", "q", "ctrl+left_square_bracket"):
        assert is_exit_key(key)
    assert is_popup_key("space")
    assert not is_popup_key("c")
    assert text_input_mode("i") is False
    assert text_input_mode("I") is True
    assert navigation_action("delete") is None
    assert navigation_action("c") is None
    assert focus_direction("shift+right") == "l"
    assert focus_direction("D") == "l"
    assert focus_direction("L") == "l"


def test_space_opens_root_menu_but_letters_do_not():
    from client.screen import GameScreen

    engine = SimpleNamespace(
        active_id=lambda: None,
        active_window=lambda: None,
        open=Mock(),
    )
    event = SimpleNamespace(
        key="space",
        prevent_default=Mock(),
        stop=Mock(),
    )
    screen = SimpleNamespace(_mode="normal", mode="game", engine=engine)

    GameScreen.on_key(screen, event)

    engine.open.assert_called_once_with("root-menu-window")

    engine.open.reset_mock()
    event.key = "p"
    GameScreen.on_key(screen, event)
    engine.open.assert_not_called()
