import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from client.views.system import tutorial
from client.window_engine import Divider


class _TutorialApp(App):
    def compose(self) -> ComposeResult:
        yield tutorial.TutorialWindow(id="tutorial-window")


def _run(scenario):
    async def runner():
        app = _TutorialApp()
        async with app.run_test(size=(88, 32)) as pilot:
            window = app.query_one(tutorial.TutorialWindow)
            window.add_class("visible")
            await pilot.pause()
            panel = window.query_one(tutorial.TutorialPanel)
            await scenario(pilot, panel)

    asyncio.run(runner())


def test_key_preference_row_stays_on_one_line_when_selected():
    async def scenario(pilot, panel):
        panel._goto_page(1)
        await pilot.pause()
        await pilot.pause()
        panel.nav("enter")
        await pilot.pause()
        await pilot.pause()

        text = str(panel.query_one("#tutorial-after-0", Static).render())
        assert "Vim 键位" in text
        assert "( j / k / h / l )" in text

    _run(scenario)


def test_scroll_page_renders_every_template_separator():
    async def scenario(pilot, panel):
        panel._goto_page(tutorial._P_SCROLL)
        await pilot.pause()
        await pilot.pause()

        separators = sum(kind in (tutorial.SEP, tutorial.RULE)
                         for kind, _ in tutorial._page_scroll())
        assert len(panel.query(Divider)) >= separators

        panel._goto_page(tutorial._P_TAB)
        await pilot.pause()
        await pilot.pause()
        assert len(panel.query(".tutorial-extra")) == 0

    _run(scenario)


# ── 布局：整个教程同一个大小、面板不动 ──


def test_every_page_occupies_the_same_area_and_the_focus_page_splits_it():
    """整个教程占同一块区域；第 5 页分成两个小面板，加起来和别的页一样大（用户 2026-11-15 定）。"""
    async def scenario(pilot, panel, sent=None):
        target = panel.parent.query_one("#focus-target")
        areas = set()
        for page in range(tutorial._TOTAL):
            panel._goto_page(page)
            await pilot.pause()
            await pilot.pause()
            regions = [panel.region] + ([target.region] if target.display else [])
            left = min(r.x for r in regions)
            right = max(r.x + r.width for r in regions)
            areas.add((left, right, panel.region.y, panel.region.height))
            assert target.display is (page == tutorial._P_FOCUS)
        assert len(areas) == 1
        left, right, _, height = areas.pop()
        assert (right - left, height) == (tutorial._PANEL_WIDTH, 18)

    _run(scenario)


def test_the_tutorial_area_is_centered_on_the_real_screen():
    import asyncio
    from unittest import mock

    from client.app import UParlorApp

    async def run():
        with mock.patch.object(UParlorApp, "connect_to_server", lambda s, h: None):
            app = UParlorApp()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                screen = app.screen
                screen._open_tutorial()
                for _ in range(10):
                    await pilot.pause()
                panel = screen.query_one("#tutorial-panel")
                assert panel.region.x == (120 - tutorial._PANEL_WIDTH) // 2
                assert panel.region.height == 18      # 不再铺满终端高度

    asyncio.run(run())


# ── GitHub 地址 ──


def test_first_and_last_pages_link_to_the_project_page():
    for items in (tutorial._page_intro(), tutorial._page_done(True)):
        lines = [label for kind, label in items if kind == tutorial.TEXT]
        assert any('请访问：[link="https://github.com/eroubisu/UParlor"]项目地址[/link]'
                   in line for line in lines)


# ── 最后一页的"记住" ──


def test_remember_option_is_a_circle_item_shown_only_when_logged_in():
    logged_in = tutorial._page_done(True)
    anonymous = tutorial._page_done(False)

    assert (tutorial.PRACTICE, "下次登录不再显示教程") in logged_in
    assert all(kind != tutorial.PRACTICE for kind, _ in anonymous)


def test_leaving_the_last_page_remembers_only_when_the_circle_is_selected(monkeypatch):
    async def scenario(pilot, panel, sent=None):
        monkeypatch.setattr(tutorial.TutorialPanel, "_is_logged_in", lambda self: True)
        panel._goto_page(tutorial._TOTAL - 1)
        await pilot.pause()
        await pilot.pause()
        assert panel.remember_choice() is False       # 默认没选，直接 Esc 不记住

        panel.nav("enter")                            # 光标一开始就在这个圆上
        await pilot.pause()
        assert panel.remember_choice() is True
        panel.nav("enter")
        assert panel.remember_choice() is False       # 再按取消

    _run(scenario)


def test_remember_choice_is_false_on_every_other_page():
    async def scenario(pilot, panel, sent=None):
        for page in range(tutorial._TOTAL - 1):
            panel._goto_page(page)
            await pilot.pause()
            assert panel.remember_choice() is False

    _run(scenario)


# ── 登录页输入框里的暗色提示 ──


def test_the_username_box_hint_tells_new_players_how_to_start():
    from client.views.login import LoginPanel

    panel = LoginPanel.__new__(LoginPanel)
    panel._submitted, panel._auth_state, panel._step = False, None, "username"
    panel._placeholder_override = ""
    hints = {}
    for tab in ("login", "register"):
        panel._tab = tab
        hints[tab] = panel.input_spec().placeholder

    assert "按 i 输入用户名" in hints["login"] and "注册" in hints["login"]
    assert "按 i 输入新用户名" in hints["register"]
