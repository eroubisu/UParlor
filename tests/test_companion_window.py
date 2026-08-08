"""Companion window interaction tests without a real LLM."""

from __future__ import annotations

import asyncio
import importlib
from collections import deque
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from client.companion import config as cfg
from client.companion.character import Character, save_character
from client.companion.provider import (
    DEEPSEEK_BASE_URL,
    OpenAIProvider,
    create_provider,
    provider_kwargs,
)
from client.views.companion.creation import CompanionCreationPanel
from client.views.companion.window import (
    CompanionPanel,
    _split_action_and_speech,
)
from client.views.companion.window import CompanionWindow


@pytest.fixture
def isolated_companion_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    importlib.reload(cfg)
    return fake_home


class _FakeController:
    player = "alice"
    generation = 1

    def __init__(self):
        self.enabled = False
        self.proactive = True
        self.input_callback = None

    def set_on_proactive(self, callback):
        self.input_callback = callback

    def has_api_key(self):
        return bool(cfg.load_global_config().get("api_key"))

    def has_character(self):
        from client.companion.character import list_characters
        return bool(list_characters())

    def is_enabled(self):
        return self.enabled

    def is_ready(self):
        config = cfg.load_global_config()
        return (
            self.has_api_key()
            and bool(config.get("model"))
            and self.has_character()
        )

    def set_enabled(self, enabled):
        self.enabled = enabled

    def set_background_proactive(self, enabled):
        self.proactive = enabled
        player_config = cfg.load_player_config()
        player_config["background_proactive"] = enabled
        cfg.save_player_config(player_config)

    def clear_visible_history(self):
        return True

    async def validate_api(self, provider_name, api_key):
        assert provider_name == "gemini"
        assert api_key == "test-secret"
        return True, "", [{"name": "gemini-test", "display": "Gemini Test"}]

    async def list_models(self, provider_name, api_key):
        assert provider_name == "gemini"
        assert api_key
        return [{"name": "gemini-test", "display": "Gemini Test"}]

    def apply_api_config(self, provider_name, api_key, model=""):
        config = cfg.load_global_config()
        config.update({
            "provider": provider_name,
            "api_key": api_key,
            "model": model,
        })
        cfg.save_global_config(config)

    def set_model(self, model):
        config = cfg.load_global_config()
        config["model"] = model
        cfg.save_global_config(config)

    def load_character(self, char_id):
        player_config = cfg.load_player_config()
        player_config["last_character_id"] = char_id
        cfg.save_player_config(player_config)

    def delete_character(self, char_id):
        from client.companion.character import delete_character
        delete_character(char_id)
        player_config = cfg.load_player_config()
        if player_config.get("last_character_id") == char_id:
            player_config["last_character_id"] = ""
            cfg.save_player_config(player_config)

    def visible_history(self):
        return []

    def public_status(self):
        return {
            "relationship": {
                "stage": "朋友",
                "intimacy": 40,
                "trust": 50,
                "familiarity": 60,
            },
            "mood": {
                "primary": "开心",
                "secondary": "",
                "intensity": 70,
                "source": "刚刚获胜",
            },
        }

    async def generate_character_options(
        self, description, selected, field,
    ):
        assert description
        assert isinstance(selected, dict)
        return [f"{field}-{index}" for index in range(4)]


class _CompanionApp(App):
    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        yield CompanionPanel(id="companion-panel")


class _CreationApp(App):
    def __init__(self):
        super().__init__()
        self.created_name = ""

    def compose(self) -> ComposeResult:
        yield CompanionCreationPanel(id="companion-creation-panel")

    def on_companion_creation_panel_created(
        self, event: CompanionCreationPanel.Created,
    ) -> None:
        event.stop()
        self.created_name = event.name


class _CompanionWindowApp(App):
    def compose(self) -> ComposeResult:
        yield CompanionWindow(id="companion-window")


class _EscapeEvent:
    key = "escape"

    def __init__(self):
        self.prevented = False
        self.stopped = False

    def prevent_default(self):
        self.prevented = True

    def stop(self):
        self.stopped = True


@pytest.mark.usefixtures("isolated_companion_home")
def test_companion_defaults_to_chat_and_blocks_unconfigured_input(
):
    cfg.set_current_player("alice")

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FakeController())
            await pilot.pause()

            assert panel._active == 0
            assert panel.get_input_widget().disabled
            assert "AI 服务未配置" in str(
                panel.query_one("#t0 .content").content)
            panel.switch_tab(-1)
            assert panel._active == 1
            panel.switch_tab(panel._active + 1)
            assert panel._active == 0

    asyncio.run(verify())


def test_companion_window_does_not_override_textual_refresh():
    async def verify():
        app = _CompanionWindowApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            window = app.query_one(CompanionWindow)
            window.refresh(layout=True)

    asyncio.run(verify())


def test_companion_message_layout_splits_and_distinguishes_action():
    assistant = _split_action_and_speech(
        "*她抬起手* 你好。*她偏过头* 再见。")
    action = CompanionPanel._format_companion_frame_line(
        SimpleNamespace(role="assistant"), "  *她抬起手*", "#ffffff")
    speech = CompanionPanel._format_companion_frame_line(
        SimpleNamespace(role="assistant"), "你好。", "#ffffff")

    assert assistant == "*她抬起手* 你好。*她偏过头* 再见。"
    assert action == "[italic #808080]  *她抬起手*[/]"
    assert speech == "[#ffffff]你好。[/]"


def test_companion_reply_reveals_complete_grapheme_clusters(monkeypatch):
    from client.views.companion import window as window_module

    revealed = []

    async def no_delay(_seconds):
        return None

    async def verify():
        panel = object.__new__(CompanionPanel)
        panel._stream_ai = lambda _slot, chunk: revealed.append(chunk)
        monkeypatch.setattr(window_module.asyncio, "sleep", no_delay)

        await panel._reveal_ai_chunk(0, "你好👨‍👩‍👧‍👦")

    asyncio.run(verify())
    assert revealed == ["你", "好", "👨‍👩‍👧‍👦"]


def test_companion_frame_keeps_long_player_content_inside_border():
    async def verify():
        app = _CompanionApp()
        async with app.run_test(size=(70, 16)) as pilot:
            panel = app.query_one(CompanionPanel)
            content = panel.query_one("#t0 .content")
            panel.bind_controller(_FakeController())
            panel._append_user("a" * 90)
            panel.refresh(layout=True)
            await pilot.pause(0.1)

            rendered = [
                "".join(segment.text for segment in content.render_line(y)._segments)
                for y in range(content.virtual_size.height)
            ]
            raw_content = str(content.content)
            assert any("┌─" in line for line in rendered)
            assert any("a" * 20 in line for line in rendered)
            assert raw_content.count(":") >= 2
            assert "┘" in raw_content

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_existing_companion_status_tab_is_visible_on_first_bind():
    cfg.set_current_player("alice")
    save_character(Character(id="guide", name="引路人"))
    player_config = cfg.load_player_config()
    player_config["last_character_id"] = "guide"
    cfg.save_player_config(player_config)

    async def verify():
        app = _CompanionApp()
        async with app.run_test():
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FakeController())

            assert "状态" in str(panel.border_title)

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_companion_tabs_remain_navigable_while_reply_streams():
    cfg.set_current_player("alice")
    save_character(Character(id="guide", name="引路人"))
    player_config = cfg.load_player_config()
    player_config["last_character_id"] = "guide"
    cfg.save_player_config(player_config)

    async def verify():
        app = _CompanionApp()
        async with app.run_test():
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FakeController())
            panel._streaming = True

            panel.switch_tab(2)

            assert panel._active == 2
            assert "心情" in str(panel.query_one("#t2 .content").content)

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_consecutive_messages_keep_independent_reply_slots():
    cfg.set_current_player("alice")

    class _QueuedController(_FakeController):
        def __init__(self):
            super().__init__()
            self.enabled = True
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = []

        def is_ready(self):
            return True

        async def chat(self, text):
            self.calls.append(text)
            yield f"{text}-回复一"
            if text == "第一条":
                self.started.set()
                await self.release.wait()
                yield "-回复二"

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            controller = _QueuedController()
            panel.bind_controller(controller)

            panel._enqueue_chat("第一条")
            await controller.started.wait()
            panel._enqueue_chat("第二条")
            await pilot.pause()

            assert panel.input_spec().enabled
            assert panel._chat_lines[0] == "第一条"
            assert "第一条-回复一" in panel._chat_lines[1]
            assert panel._chat_lines[2] == "第二条"
            assert panel._chat_lines[3] == ""
            assert controller.calls == ["第一条"]

            controller.release.set()
            await pilot.pause(0.3)

            assert controller.calls == ["第一条", "第二条"]
            assert "第一条-回复一-回复二" in panel._chat_lines[1]
            assert "第二条-回复一" in panel._chat_lines[3]
            assert not panel._streaming

    asyncio.run(verify())


def test_chat_blocks_have_one_blank_line_without_empty_slot_gaps():
    async def verify():
        app = _CompanionApp()
        async with app.run_test():
            panel = app.query_one(CompanionPanel)
            panel._chat_lines = [
                "第一条",
                "",
                "第二条",
                "",
            ]
            panel._chat_meta = [
                ("user", "10:00:00"),
                ("assistant", "10:00:01"),
                ("user", "10:00:02"),
                ("assistant", "10:00:03"),
            ]

            panel._flush_chat()

            content = str(panel.query_one("#t0 .content").content)
            assert "\n\n\n" not in content
            assert content.count("\n\n") == 0

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_companion_settings_key_edit_uses_input_and_validates_before_save(
):
    cfg.set_current_player("alice")

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FakeController())
            panel.open_settings()
            panel.selection.select("api_key")
            panel.nav("enter")
            await pilot.pause()

            assert panel._editing == ""
            assert "按 i 输入 API Key" in panel._status
            assert panel.enter_insert()
            assert panel.get_input_widget().password
            assert cfg.load_global_config()["api_key"] == ""

            await pilot.press(*"test-secret", "enter")
            assert cfg.load_global_config()["api_key"] == ""

            panel.selection.select("validate")
            panel.nav("enter")
            await pilot.pause(0.1)

            config = cfg.load_global_config()
            assert config["api_key"] == "test-secret"
            assert config["model"] == ""
            assert "验证成功" in panel._status

            panel.selection.select("model")
            panel.nav("enter")
            assert panel._settings_menu == "model"
            panel.nav("enter")
            assert cfg.load_global_config()["model"] == "gemini-test"

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_escape_cancels_edit_and_bubbles_to_screen_input_mode():
    cfg.set_current_player("alice")

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FakeController())
            panel.open_settings()
            panel.selection.select("api_key")
            assert panel.enter_insert()
            input_widget = panel.get_input_widget()
            assert input_widget is not None
            input_widget.value = "draft-key"

            panel.leave_insert(preserve=True)
            await pilot.pause()

            assert panel._editing == ""
            assert input_widget.disabled
            panel.selection.select("api_key")
            assert panel.enter_insert()
            assert input_widget.value == "draft-key"

    asyncio.run(verify())


def test_deepseek_uses_fixed_api_endpoint():
    assert isinstance(create_provider("deepseek"), OpenAIProvider)
    assert provider_kwargs("deepseek") == {
        "base_url": DEEPSEEK_BASE_URL,
    }
    with pytest.raises(ValueError):
        create_provider("openai")


@pytest.mark.usefixtures("isolated_companion_home")
def test_stale_api_validation_does_not_persist_old_draft():
    cfg.set_current_player("alice")

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FakeController())
            panel.open_settings()
            revision = panel._api_revision
            panel._draft_provider = "deepseek"
            panel._api_revision += 1

            panel._finish_api_validation(
                True,
                "",
                [{"name": "old-model", "display": "Old"}],
                "gemini",
                "stale-key",
                revision,
            )
            await pilot.pause()

            assert cfg.load_global_config()["api_key"] == ""

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_stale_model_failure_does_not_replace_current_status():
    cfg.set_current_player("alice")
    config = cfg.load_global_config()
    config.update({
        "provider": "gemini",
        "api_key": "current-key",
        "model": "gemini-test",
    })
    cfg.save_global_config(config)

    class _FailingController(_FakeController):
        async def list_models(self, provider_name, api_key):
            raise RuntimeError(f"{provider_name}:{api_key}")

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FailingController())
            panel.open_settings()
            panel._status = "当前状态"
            panel._draft_provider = "deepseek"

            panel._load_models("gemini", "current-key")
            await pilot.pause(0.1)

            assert panel._status == "当前状态"

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_current_companion_opens_submenu_and_appears_in_chat_subtitle(
):
    cfg.set_current_player("alice")
    save_character(Character(id="guide", name="引路人"))

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            controller = _FakeController()
            panel.bind_controller(controller)
            panel.open_settings()
            assert panel.border_subtitle == ""
            assert not panel.query_one("#input-row").display
            panel.selection.select("character")
            panel.nav("enter")
            await pilot.pause()

            assert panel._settings_menu == "character"
            assert "引路人" in str(panel.query_one("#t1 .content").content)

            panel.nav("enter")
            assert panel._settings_menu == "character_action"
            panel.nav("enter")
            panel.switch_tab(0)
            await pilot.pause()

            assert panel.border_subtitle == "引路人"
            assert "状态" in str(panel.border_title)
            panel.switch_tab(2)
            assert panel.border_subtitle == ""
            assert not panel.query_one("#input-row").display
            status = str(panel.query_one("#t2 .content").content)
            assert "朋友" in status
            assert "开心" in status

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_selected_companion_can_be_deleted_after_confirmation():
    cfg.set_current_player("alice")
    save_character(Character(id="guide", name="引路人"))

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_FakeController())
            panel.open_settings()
            panel.selection.select("character")
            panel.nav("enter")
            panel.nav("enter")
            assert panel._settings_menu == "character_action"
            panel.nav("down")
            panel.nav("enter")
            assert panel._settings_menu == "delete_confirm"
            assert "删除 引路人" in str(
                panel.query_one("#t1 .content").content)
            panel.nav("enter")
            await pilot.pause()

            assert not cfg.char_dir("guide").exists()
            assert "旅伴已删除" in panel._status

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_companion_chat_history_can_be_cleared_after_confirmation():
    cfg.set_current_player("alice")

    class _Controller(_FakeController):
        cleared = False

        def clear_visible_history(self):
            self.cleared = True
            return True

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            controller = _Controller()
            panel.bind_controller(controller)
            panel._chat_lines = ["旧消息"]
            panel._chat_meta = [("user", "12:00:00")]
            panel.open_settings()

            assert panel.selection.select("clear_history")
            panel.nav("enter")
            assert panel._settings_menu == "clear_history_confirm"
            assert "确认清空聊天记录" in str(
                panel.query_one("#t1 .content").content)

            panel.nav("enter")
            await pilot.pause()

            assert controller.cleared
            assert panel._chat_lines == []
            assert panel._chat_meta == []
            assert panel._settings_menu == ""
            assert "聊天记录已清空" in panel._status

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_persisted_history_is_restored_when_window_rebinds():
    cfg.set_current_player("alice")

    class _HistoryController(_FakeController):
        def visible_history(self):
            return [
                {"role": "user", "content": "上次的问题[/]"},
                {"role": "assistant", "content": "[bold]上次的回答"},
            ]

    async def verify():
        app = _CompanionApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionPanel)
            panel.bind_controller(_HistoryController())
            await pilot.pause()

            content = str(panel.query_one("#t0 .content").content)
            assert "上次的问题" in content
            assert "上次的回答" in content

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_companion_window_reveals_history_at_current_width():
    from rich.markup import render
    from textual.widgets import Static

    from client.window_engine.text import cell_width

    cfg.set_current_player("alice")

    class _HistoryController(_FakeController):
        enabled = True

        def visible_history(self):
            return [
                {
                    "role": "assistant",
                    "content": (
                        f"*他脚步一顿* 第{index}段用于验证中文宽字符首次布局，"
                        "窗口显示时不能先出现错误宽度的框线。"
                    ),
                    "time": "14:53:36",
                }
                for index in range(12)
            ]

        def player_chat_sender(self):
            return {
                "name": "alice",
                "title": "新人",
                "level": 3,
                "style": {},
            }

    async def verify():
        app = _CompanionWindowApp()
        async with app.run_test(size=(106, 40)) as pilot:
            window = app.query_one(CompanionWindow)
            panel = app.query_one(CompanionPanel)
            panel._selected_character_name = lambda: "蒋介石"
            panel.bind_controller(_HistoryController())

            measured_frames = []
            prepare = window._prepare_after_show

            def capture_measured_frame(revision: int) -> None:
                measured_frames.append(
                    "验证中文宽字符" in app.export_screenshot()
                )
                prepare(revision)

            window._prepare_after_show = capture_measured_frame
            window.show()
            await pilot.pause()
            await pilot.pause()

            content = panel.query_one("#t0 .content", Static)
            scroll = panel.query_one("#t0", VerticalScroll)
            plain = render(str(content.content)).plain
            first_width = panel._content_width(0)
            assert measured_frames == [False]
            assert not window.has_class("-layout-pending")
            assert scroll.show_vertical_scrollbar
            assert max(cell_width(line) for line in plain.splitlines()) == first_width

            await pilot.resize_terminal(130, 40)
            await pilot.pause()

            resized_plain = render(str(content.content)).plain
            resized_width = panel._content_width(0)
            assert resized_width > first_width
            assert max(
                cell_width(line) for line in resized_plain.splitlines()
            ) == resized_width

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_stale_character_options_do_not_enter_reset_draft():
    cfg.set_current_player("alice")

    async def verify():
        app = _CreationApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionCreationPanel)
            panel.bind_controller(_FakeController())
            old_revision = panel._draft_revision
            panel.reset_cursor()

            panel._finish_generation(
                "name",
                ["旧一", "旧二", "旧三", "旧四"],
                "",
                old_revision,
            )
            await pilot.pause()

            assert "name" not in panel._options

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_creation_pages_are_gated_and_custom_values_keep_later_choices():
    cfg.set_current_player("alice")

    async def verify():
        app = _CreationApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionCreationPanel)
            controller = _FakeController()
            panel.bind_controller(controller)

            panel.nav("tab_next")
            assert panel._active == 0

            panel.nav("enter")
            assert panel.can_enter_insert()
            assert panel.enter_insert()
            await pilot.press(*"想要一位可靠的旅伴", "enter")
            await pilot.pause(0.1)

            assert panel._active == 1
            assert len(panel._options["name"]) == 4
            panel.nav("tab_next")
            assert panel._active == 1

            async def add_and_select(value):
                assert panel.enter_insert()
                await pilot.press(*value, "enter")
                await pilot.pause()
                field = CHARACTER_FIELDS[panel._active - 1]
                assert value in panel._options[field]
                panel.nav("enter")
                await pilot.pause(0.1)

            from client.companion.character import CHARACTER_FIELDS
            await add_and_select("岚")
            await add_and_select("沉稳可靠")
            await add_and_select("言简意赅")
            await add_and_select("银发灰眼")
            await add_and_select("来自远方的引路人")

            assert panel._active == 6
            panel._switch_page(1)
            await add_and_select("新名字")

            assert panel._selected["backstory"] == "来自远方的引路人"
            assert panel._active == 2

            panel._switch_page(6)
            panel.nav("enter")
            await pilot.pause()

            assert app.created_name == "新名字"

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_generation_allows_input_but_rejects_submission():
    cfg.set_current_player("alice")

    async def verify():
        app = _CreationApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionCreationPanel)
            panel.bind_controller(_FakeController())
            panel._generating_field = "name"

            assert panel.can_enter_insert()
            assert panel.enter_insert()
            await pilot.press(*"生成期间修改", "enter")
            await pilot.pause()

            assert panel._description == ""
            assert panel._error == "正在生成选项，本次输入无效。"

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_creation_back_navigation_preserves_choices_without_regeneration():
    cfg.set_current_player("alice")

    class _DelayedController(_FakeController):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.release = asyncio.Event()

        async def generate_character_options(
            self, description, selected, field,
        ):
            self.calls.append(field)
            await self.release.wait()
            return [f"{field}-{index}" for index in range(4)]

    async def verify():
        app = _CreationApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionCreationPanel)
            controller = _DelayedController()
            panel.bind_controller(controller)
            panel._description = "可靠的旅伴"
            panel._options["name"] = ["岚", "澄", "遥", "宁"]
            panel._selected["name"] = "岚"
            panel._unlocked_page = 2
            panel._switch_page(2)
            panel._generate_options("personality")
            await pilot.pause()

            panel.nav("tab_prev")

            assert panel._active == 1
            assert panel._selected["name"] == "岚"
            assert panel.selection.selected_id == "岚"
            assert controller.calls == ["personality"]

            panel.nav("tab_next")
            assert panel._active == 2
            assert controller.calls == ["personality"]

            controller.release.set()
            await pilot.pause(0.1)

            assert panel._options["personality"] == [
                "personality-0",
                "personality-1",
                "personality-2",
                "personality-3",
            ]
            assert panel._selected["name"] == "岚"

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_creation_escape_cancels_input_and_restores_option_navigation():
    cfg.set_current_player("alice")

    async def verify():
        app = _CreationApp()
        async with app.run_test():
            panel = app.query_one(CompanionCreationPanel)
            panel.bind_controller(_FakeController())
            panel._unlocked_page = 1
            panel._options["name"] = ["一", "二"]
            panel._switch_page(1)

            assert panel.enter_insert()
            input_widget = panel.get_input_widget()
            assert input_widget is not None
            input_widget.value = "未提交"
            panel.leave_insert(preserve=True)

            assert input_widget.value == "未提交"
            assert input_widget.disabled
            panel.nav("down")
            assert panel.selection.index == 1

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_creation_input_placeholder_tracks_selected_page():
    cfg.set_current_player("alice")

    async def verify():
        app = _CreationApp()
        async with app.run_test():
            panel = app.query_one(CompanionCreationPanel)
            panel.bind_controller(_FakeController())
            panel._unlocked_page = 1
            panel._options["name"] = ["岚"]
            panel._options["personality"] = ["沉稳"]
            panel._switch_page(1)
            input_widget = panel.get_input_widget()
            assert input_widget is not None
            assert input_widget.placeholder == "输入名字"

            panel.nav("enter")

            assert panel._active == 2
            assert input_widget.placeholder == "输入性格"

    asyncio.run(verify())


@pytest.mark.usefixtures("isolated_companion_home")
def test_wrapped_creation_options_share_fixed_prefix_column():
    cfg.set_current_player("alice")

    async def verify():
        app = _CreationApp()
        async with app.run_test() as pilot:
            panel = app.query_one(CompanionCreationPanel)
            panel.bind_controller(_FakeController())
            panel._unlocked_page = 1
            panel._switch_page(1)
            panel._options["name"] = ["很长的候选名字描述" * 8]
            panel._render_page()
            await pilot.pause()

            rendered = panel.selection.render(24).splitlines()
            assert any("> " in line for line in rendered)
            assert all(
                line.startswith("[") and "]" in line
                for line in rendered
            )

    asyncio.run(verify())
