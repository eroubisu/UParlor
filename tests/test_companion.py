"""Companion 模块的纯逻辑单元测试 (不调真 LLM)"""

import asyncio
import json
import threading
import time
from collections import deque
from types import SimpleNamespace

import pytest


@pytest.fixture
def isolated_companion_home(monkeypatch, tmp_path):
    """每个测试用临时 home 目录, 不污染真实 ~/.uparlor/"""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))   # Windows
    monkeypatch.setenv("HOME", str(fake_home))           # Unix
    # 重新加载 companion.config 让 COMPANION_DIR 指向新位置
    import importlib
    from client.companion import config as cfg
    importlib.reload(cfg)
    return fake_home


def test_set_current_player(isolated_companion_home):
    from client.companion import config as cfg
    assert cfg.get_current_player() == ""
    cfg.set_current_player("alice")
    assert cfg.get_current_player() == "alice"


def test_background_start_does_not_wait_for_thread_ready(monkeypatch):
    from client.companion.controller import CompanionController

    class _Thread:
        daemon = True

        def start(self):
            pass

    class _Ready:
        def wait(self, timeout=None):
            raise AssertionError(f"UI startup waited for worker: {timeout}")

    controller = object.__new__(CompanionController)
    controller._bg_running = False
    controller._service = SimpleNamespace(
        char_id="guide",
        rebind_state=lambda _state: None,
    )
    controller._generation = 1
    controller._state = SimpleNamespace()
    controller._player = "alice"
    controller._bg_ready = None
    monkeypatch.setattr(
        "client.companion.controller.cfg.load_player_config",
        lambda: {"background_proactive": True},
    )
    monkeypatch.setattr(
        "client.companion.controller.snapshot_state",
        lambda _state, _player: {},
    )
    monkeypatch.setattr(
        "client.companion.controller.threading.Event",
        lambda: _Ready(),
    )
    monkeypatch.setattr(
        "client.companion.controller.threading.Thread",
        lambda **_kwargs: _Thread(),
    )

    controller._start_background()

    assert controller._bg_running


def test_companion_writes_are_atomic(isolated_companion_home):
    from client.companion import config as cfg

    cfg.set_current_player("alice")
    path = cfg.player_dir() / "state.json"
    cfg.save_json(path, {"value": "完整"})

    assert cfg.load_json(path) == {"value": "完整"}
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_player_config_persists(isolated_companion_home):
    from client.companion import config as cfg
    cfg.set_current_player("alice")
    pc = cfg.load_player_config()
    pc["enabled"] = True
    pc["attention_level"] = "talkative"
    cfg.save_player_config(pc)
    # reload
    pc2 = cfg.load_player_config()
    assert pc2["enabled"] is True
    assert pc2["attention_level"] == "talkative"


def test_unsafe_legacy_provider_config_drops_key(isolated_companion_home):
    from client.companion import config as cfg

    cfg.ensure_dir()
    config_path = cfg.COMPANION_DIR / "config.json"
    config_path.write_text(json.dumps({
        "provider": "openai",
        "base_url": "https://untrusted.example/v1",
        "api_key": "must-not-be-used",
        "model": "legacy-model",
    }), encoding="utf-8")

    loaded = cfg.load_global_config()

    assert loaded["provider"] == "gemini"
    assert loaded["base_url"] == ""
    assert loaded["api_key"] == ""
    assert loaded["model"] == ""


def test_provider_error_redaction_removes_api_credentials():
    from client.companion.provider import redact_sensitive_text

    gemini_key = "AIza" + "A" * 32
    openai_key = "sk-" + "b" * 24
    message = (
        f"request failed: key={gemini_key} "
        f"Authorization: Bearer {openai_key}"
    )

    redacted = redact_sensitive_text(message, gemini_key, openai_key)

    assert gemini_key not in redacted
    assert openai_key not in redacted
    assert redacted.count("[REDACTED]") >= 2


def test_social_state_apply_delta_clamping():
    from client.companion.social import SocialState
    s = SocialState()
    s.apply_delta(intimacy=200, trust=200, familiarity=200)
    assert s.intimacy <= 100
    assert s.trust <= 100
    assert s.familiarity <= 100


def test_social_state_stage_label():
    from client.companion.social import SocialState
    s = SocialState()
    assert s.stage_label  # 不为空 (默认陌生人)


def test_mood_state_set_and_text():
    from client.companion.mood import MoodState
    m = MoodState()
    m.set_mood("joyful", 0.8, source="test")
    text = m.to_prompt_text()
    assert "开心" in text
    assert "test" in text


def test_observed_chat_is_labeled_as_other_people_conversation():
    from client.companion.attention import look_world_chat

    state = SimpleNamespace(chat=SimpleNamespace(world_messages=[
        SimpleNamespace(sender_name="bob", text="你好", time="10:00:00"),
    ]))

    text = look_world_chat(state)

    assert "不是对旅伴说的话" in text
    assert "bob: 你好" in text


def test_structured_companion_reply_formats_one_action_and_speech():
    from client.companion.persona import format_companion_reply

    assert format_companion_reply({
        "action": "她抬起手",
        "speech": "我看到了。确实如此。",
    }) == "*她抬起手*\n我看到了。确实如此。"
    assert format_companion_reply({
        "action": "",
        "speech": "我看到了。",
    }) == "我看到了。"
    assert format_companion_reply({
        "action": "她点头",
        "speech": "",
    }) == "*她点头*"


@pytest.mark.parametrize("arguments", [
    {"action": "她抬手*她点头", "speech": "我看到了。"},
    {"action": "她抬手", "speech": "我看到了。\n再说一次。"},
    {"action": "", "speech": ""},
])
def test_structured_companion_reply_rejects_protocol_violations(arguments):
    from client.companion.persona import format_companion_reply

    with pytest.raises(ValueError):
        format_companion_reply(arguments)


def test_service_requires_and_formats_provider_reply_tool():
    from client.companion.provider import (
        COMPANION_REPLY_TOOL,
        ToolCall,
    )
    from client.companion.service import AIService

    class _Service(AIService):
        @property
        def model(self):
            return "test-model"

        @property
        def attention_level(self):
            return "normal"

    class _Provider:
        async def stream_with_tools(self, _messages, **kwargs):
            assert kwargs["final_tool"] is COMPANION_REPLY_TOOL
            yield ToolCall(COMPANION_REPLY_TOOL["name"], {
                "action": "她抬起手",
                "speech": "我看到了。确实如此。",
            })

    async def verify():
        service = object.__new__(_Service)
        service._provider = _Provider()
        service._active = True
        service._consecutive_errors = 0
        service._add_tokens = lambda _count: None
        chunks = [
            chunk async for chunk in service._stream(
                [], max_tokens=128, temperature=0.5, use_tools=True,
            )
        ]
        assert chunks == ["*她抬起手*\n我看到了。确实如此。"]

    asyncio.run(verify())


def test_clear_visible_history_hides_projection_without_deleting_memory():
    from client.companion.service import AIService

    service = object.__new__(AIService)
    service._recent = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好。"},
    ]
    service._display_from = 0
    service._save_all = lambda: None

    service.clear_visible_history()

    assert service.visible_history() == []
    assert len(service._recent) == 2
    service._recent.append({"role": "user", "content": "新消息"})
    assert service.visible_history() == [
        {"role": "user", "content": "新消息"},
    ]

    assert service.restore_visible_history()
    assert service.visible_history()[0]["content"] == "你好"
    assert not service.restore_visible_history()


def test_service_rejects_reply_tool_with_second_action_in_speech():
    from client.companion.provider import (
        COMPANION_REPLY_TOOL,
        ToolCall,
    )
    from client.companion.service import AIService

    class _Service(AIService):
        @property
        def model(self):
            return "test-model"

        @property
        def attention_level(self):
            return "normal"

    class _Provider:
        async def stream_with_tools(self, _messages, **_kwargs):
            yield ToolCall(COMPANION_REPLY_TOOL["name"], {
                "action": "她抬起手",
                "speech": "我看到了。*她点头*确实如此。",
            })

    async def verify():
        service = object.__new__(_Service)
        service._provider = _Provider()
        service._active = True
        service._consecutive_errors = 0
        service._add_tokens = lambda _count: None
        with pytest.raises(ValueError, match="台词"):
            async for _ in service._stream(
                [], max_tokens=128, temperature=0.5, use_tools=True,
            ):
                pass

    asyncio.run(verify())


def test_gemini_forces_structured_final_reply_tool():
    from client.companion.provider import (
        COMPANION_REPLY_TOOL,
        GoogleProvider,
        ToolCall,
    )

    class _Response:
        async def __aiter__(self):
            yield SimpleNamespace(
                usage_metadata=None,
                candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                    SimpleNamespace(
                        text=None,
                        function_call=SimpleNamespace(
                            name=COMPANION_REPLY_TOOL["name"],
                            args={"action": "她点头", "speech": "好。"},
                        ),
                    ),
                ]))],
            )

    class _Models:
        async def generate_content_stream(self, **kwargs):
            config = kwargs["config"]
            assert config.tool_config.function_calling_config.mode.value == "ANY"
            declarations = config.tools[0].function_declarations
            assert declarations[-1].name == COMPANION_REPLY_TOOL["name"]
            return _Response()

    async def verify():
        provider = GoogleProvider()
        provider._client = SimpleNamespace(
            aio=SimpleNamespace(models=_Models()),
        )
        results = [
            item async for item in provider.stream_with_tools(
                [{"role": "user", "content": "你好"}],
                model="test-model",
                max_tokens=128,
                temperature=0.5,
                tools=[],
                execute_tool=lambda _name, _args: "",
                final_tool=COMPANION_REPLY_TOOL,
            )
        ]
        assert len(results) == 1
        assert isinstance(results[0], ToolCall)
        assert results[0].args == {"action": "她点头", "speech": "好。"}

    asyncio.run(verify())


def test_deepseek_forces_structured_final_reply_tool():
    from client.companion.provider import (
        COMPANION_REPLY_TOOL,
        OpenAIProvider,
        ToolCall,
    )

    class _Response:
        async def __aiter__(self):
            yield SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(delta=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(
                        index=0,
                        id="reply-call",
                        function=SimpleNamespace(
                            name=COMPANION_REPLY_TOOL["name"],
                            arguments=(
                                '{"action":"她点头","speech":"好。"}'
                            ),
                        ),
                    )],
                ))],
            )

    class _Completions:
        async def create(self, **kwargs):
            assert kwargs["tool_choice"] == "required"
            assert kwargs["extra_body"] == {
                "thinking": {"type": "disabled"},
            }
            assert (
                kwargs["tools"][-1]["function"]["name"]
                == COMPANION_REPLY_TOOL["name"]
            )
            return _Response()

    async def verify():
        provider = OpenAIProvider()
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=_Completions()),
        )
        results = [
            item async for item in provider.stream_with_tools(
                [{"role": "user", "content": "你好"}],
                model="test-model",
                max_tokens=128,
                temperature=0.5,
                tools=[],
                execute_tool=lambda _name, _args: "",
                final_tool=COMPANION_REPLY_TOOL,
            )
        ]
        assert len(results) == 1
        assert isinstance(results[0], ToolCall)
        assert results[0].args == {"action": "她点头", "speech": "好。"}

    asyncio.run(verify())


def test_interaction_state_is_evaluated_by_provider():
    from client.companion.service import AIService

    async def verify():
        class _Service(AIService):
            @property
            def model(self):
                return "test-model"

        class _Provider:
            async def generate(self, messages, **kwargs):
                assert "玩家互动" in messages[0]["content"]
                context = json.loads(messages[1]["content"])
                assert context["interaction"] == "测试互动"
                assert context["reply"] == "测试回复"
                assert kwargs["temperature"] == 0.1
                return (
                    '{"mood":{"primary":"annoyed","intensity":0.6},'
                    '"social_delta":{"intimacy":-1,"trust":-2}}',
                    12,
                )

        service = object.__new__(_Service)
        service._provider = _Provider()
        service._character = None
        service._mood = __import__(
            "client.companion.mood", fromlist=["MoodState"]).MoodState()
        service._social = __import__(
            "client.companion.social", fromlist=["SocialState"]).SocialState()
        service._cognitive = SimpleNamespace(update=lambda _data: None)
        service._impression = SimpleNamespace(update=lambda _data: None)
        service._save_all = lambda: None
        service._add_tokens = lambda tokens, **_kwargs: None

        await service._evaluate_interaction("测试互动", "测试回复")

        assert service._mood.primary == "calm"
        assert service._pending_mood_primary == "annoyed"
        await service._evaluate_interaction("测试互动", "测试回复")
        assert service._mood.primary == "annoyed"
        assert service._mood.intensity == 0.4
        assert service._social.intimacy < 0
        assert service._social.trust < 0

    asyncio.run(verify())


def test_zero_state_evaluation_does_not_invent_positive_change():
    from client.companion.service import AIService
    from client.companion.mood import MoodState
    from client.companion.social import SocialState

    service = object.__new__(AIService)
    service._mood = MoodState()
    service._social = SocialState()
    service._cognitive = SimpleNamespace(update=lambda _data: None)
    service._impression = SimpleNamespace(update=lambda _data: None)
    service._save_all = lambda: None

    service._apply_state_evaluation({
        "mood": {"primary": "calm", "intensity": 0.3},
        "social_delta": {"intimacy": 0, "trust": 0, "familiarity": 0},
    })

    assert service._mood.primary == "calm"
    assert service._social.intimacy == 0
    assert service._social.trust == 0
    assert service._social.familiarity == 0


def test_cognitive_update():
    from client.companion.cognitive import CognitiveState
    c = CognitiveState()
    c.update({"on_mind": "今天天气真好"})
    assert c.on_mind == "今天天气真好"
    assert "今天天气真好" in c.to_prompt_text()


def test_impression_update():
    from client.companion.impression import ImpressionState
    imp = ImpressionState()
    imp.update({"portrait": "热爱编程的玩家", "patterns": ["夜猫子"]})
    text = imp.to_prompt_text()
    assert "热爱编程" in text
    assert "夜猫子" in text


def test_character_option_generation_requires_four_distinct_values(
        monkeypatch):
    from client.companion import character
    from client.companion import provider

    class _Provider:
        def init_client(self, api_key, **kwargs):
            assert api_key == "key"
            assert kwargs["model"] == "model"

        async def generate(self, messages, **kwargs):
            assert "待生成属性：名字" in messages[-1]["content"]
            assert kwargs["model"] == "model"
            return '{"options":["岚","澄","朔","凛"]}', 10

    monkeypatch.setattr(provider, "create_provider", lambda _name: _Provider())

    options = asyncio.run(character.generate_character_options(
        "可靠的旅伴",
        {},
        "name",
        "key",
        "gemini",
        model="model",
    ))

    assert options == ["岚", "澄", "朔", "凛"]


def test_character_ids_do_not_collide(isolated_companion_home):
    from client.companion import config as cfg
    from client.companion.character import generate_char_id

    cfg.set_current_player("alice")
    ids = {generate_char_id() for _ in range(20)}

    assert len(ids) == 20


def test_attention_tools_with_minimal_state():
    """LLM tools 在最小 state 下应安全降级, 不抛异常"""
    from client.companion.attention import TOOLS

    class _MinState:
        class chat:
            world_messages = []
            room_messages = []
        class status:
            player_data = {}
            location = ''
        class online:
            users = []
            friends = []
        class notify:
            system_notifications = []
            unread_count = 0

    state = _MinState()
    for name, fn in TOOLS.items():
        result = fn(state)
        assert isinstance(result, str), f"{name} 返回非字符串"


def test_companion_can_inspect_current_game_on_demand():
    from client.companion.attention import look_game, snapshot_state

    state = SimpleNamespace(
        chat=None,
        status=None,
        online=None,
        notify=None,
        game_board=SimpleNamespace(room_data={
            "game_type": "uno",
            "room_state": "playing",
            "current_player": "alice",
            "discard_top": "R7",
        }),
    )

    snapshot = snapshot_state(state, "alice")
    result = json.loads(look_game(snapshot))

    assert result["game_type"] == "uno"
    assert result["current_player"] == "alice"
    assert result["discard_top"] == "R7"


def test_proactive_trigger_context_is_never_added_to_history():
    from client.companion.service import AIService

    class _Service(AIService):
        async def _stream(self, messages, **_kwargs):
            assert "UNO 对局结束" in messages[0]["content"]
            yield "这局打得不错。"

        async def _evaluate_interaction(self, interaction, reply):
            assert interaction == "UNO 对局结束"
            assert reply == "这局打得不错。"

    async def verify():
        service = object.__new__(_Service)
        service._active = True
        service._recent = [{"role": "user", "content": "之前的消息"}]
        service._summary = ""
        service._state = SimpleNamespace()
        service._attention = None
        service._character = None
        service._social = SimpleNamespace(to_prompt_text=lambda: "")
        service._mood = SimpleNamespace(
            decay=lambda: None,
            to_prompt_text=lambda: "",
        )
        service._cognitive = SimpleNamespace(to_prompt_text=lambda: "")
        service._impression = SimpleNamespace(to_prompt_text=lambda: "")
        service._cached_static_prompt = ""
        service._save_recent = lambda: None

        chunks = [
            chunk async for chunk in service.proactive_chat("UNO 对局结束")
        ]

        assert chunks == ["这局打得不错。"]
        assert [
            (item["role"], item["content"])
            for item in service._recent
        ] == [
            ("user", "之前的消息"),
            ("assistant", "这局打得不错。"),
        ]
        assert service._recent[-1]["time"].count(":") == 2

    asyncio.run(verify())


def test_loading_character_removes_legacy_system_context(
        isolated_companion_home, monkeypatch):
    from client.companion import config as cfg
    from client.companion import service as service_module
    from client.companion.character import Character, save_character

    cfg.set_current_player("alice")
    save_character(Character(id="guide", name="引路人"))
    character_dir = cfg.char_dir("guide")
    cfg.save_json(character_dir / "recent.json", [
        {"role": "user", "content": "普通消息"},
        {"role": "user", "content": "[系统: UNO 轮到玩家行动]"},
        {"role": "assistant", "content": "主动回复"},
    ])
    monkeypatch.setattr(
        service_module,
        "load_global_config",
        lambda: {"api_key": "", "model": "", "provider": "gemini"},
    )
    service = service_module.AIService(SimpleNamespace())

    service.load_character("guide")

    assert service.visible_history() == [
        {"role": "user", "content": "普通消息"},
        {"role": "assistant", "content": "主动回复"},
    ]
    assert cfg.load_json(character_dir / "recent.json") == service._recent


def test_important_events_are_prioritized_and_coalesced(
        isolated_companion_home, monkeypatch):
    from client.companion import service as service_module

    monkeypatch.setattr(
        service_module, "load_global_config",
        lambda: {"api_key": "key", "model": "model", "provider": "gemini"},
    )
    monkeypatch.setattr(
        service_module, "load_player_config",
        lambda: {"activity_level": "normal"},
    )
    service = service_module.AIService(SimpleNamespace())
    service._ready = True
    service.observe_event("收到好友申请")
    service.observe_event("UNO 轮到玩家行动")

    assert service.tick() == "收到好友申请；UNO 轮到玩家行动"


def test_important_events_wait_in_queue_during_cooldown(
        isolated_companion_home, monkeypatch):
    from client.companion import service as service_module

    monkeypatch.setattr(
        service_module, "load_global_config",
        lambda: {"api_key": "key", "model": "model", "provider": "gemini"},
    )
    monkeypatch.setattr(
        service_module, "load_player_config",
        lambda: {"activity_level": "normal"},
    )
    service = service_module.AIService(SimpleNamespace())
    service._ready = True
    service._last_proactive = time.time()
    service.observe_event("先到事件")

    assert service.tick() is None
    service.observe_event("后到事件")
    service._last_proactive = 0

    assert service.tick() == "先到事件；后到事件"


def test_user_chat_consumes_pending_proactive_event_once():
    from client.companion.service import AIService

    class _Service(AIService):
        async def _stream(self, messages, **_kwargs):
            assert "UNO 对局结束" in messages[0]["content"]
            yield "*她抬手*\n我看到了。确实如此。"

        async def _evaluate_interaction(self, _interaction, reply):
            assert reply == "*她抬手*\n我看到了。确实如此。"

    async def verify():
        service = object.__new__(_Service)
        service._active = True
        service._char_id = ""
        service._last_user_msg = 0
        service._recent = []
        service._pending_events = deque(["UNO 对局结束"], maxlen=10)
        service._event_lock = threading.Lock()
        service._attention = __import__(
            "client.companion.attention",
            fromlist=["AttentionBuffer"],
        ).AttentionBuffer()
        service._attention.push("UNO 对局结束")
        service._character = None
        service._social = SimpleNamespace(to_prompt_text=lambda: "")
        service._mood = SimpleNamespace(
            decay=lambda: None,
            to_prompt_text=lambda: "",
        )
        service._cognitive = SimpleNamespace(to_prompt_text=lambda: "")
        service._impression = SimpleNamespace(to_prompt_text=lambda: "")
        service._summary = ""
        service._state = SimpleNamespace()
        service._cached_static_prompt = ""
        service._save_recent = lambda: None

        chunks = [chunk async for chunk in service.chat("你看到了吗")]

        assert chunks == ["*她抬手*\n我看到了。确实如此。"]
        assert service._take_events() == []
        assert [item["role"] for item in service._recent] == [
            "user", "assistant",
        ]
        assert service._recent[-1]["content"] == (
            "*她抬手*\n我看到了。确实如此。"
        )

    asyncio.run(verify())


def test_chat_evaluates_mood_before_exposing_reply():
    from client.companion.service import AIService

    class _Service(AIService):
        async def _stream(self, _messages, **_kwargs):
            yield "回复"

        async def _evaluate_interaction(self, _interaction, _reply):
            self.evaluated = True

        def _build_messages(self, _user_text=""):
            return []

    async def verify():
        service = object.__new__(_Service)
        service._active = True
        service._char_id = ""
        service._last_user_msg = 0
        service._recent = []
        service._pending_events = deque(maxlen=10)
        service._event_lock = threading.Lock()
        service._attention = __import__(
            "client.companion.attention",
            fromlist=["AttentionBuffer"],
        ).AttentionBuffer()
        service._mood = SimpleNamespace(
            primary="joyful", secondary="", intensity=0.4, source="",
        )
        service._save_recent = lambda: None
        service.evaluated = False

        iterator = service.chat("你好").__aiter__()
        reply = await iterator.__anext__()

        assert service.evaluated
        assert reply == "回复"
        assert service._recent[-1]["mood"]["primary"] == "joyful"

    asyncio.run(verify())


def test_user_chat_invalidates_proactive_reply_waiting_for_ui_delivery():
    from client.companion.controller import CompanionController

    class _Service:
        char_id = "guide"

        def __init__(self):
            self.discarded = []

        def rebind_state(self, _state):
            pass

        async def chat(self, _text):
            yield "直接回复"

        def discard_proactive_reply(self, text):
            self.discarded.append(text)

    async def verify():
        controller = CompanionController(SimpleNamespace())
        controller._player = "alice"
        service = _Service()
        controller._service = service
        scheduled = []
        delivered = []
        controller.set_on_proactive(
            lambda text, revision: scheduled.append(
                lambda: controller.deliver_proactive(
                    text, revision, delivered.append)))

        revision = controller.proactive_revision
        controller._emit_proactive(
            "旧主动回复", controller.generation, revision, service)
        chunks = [chunk async for chunk in controller.chat("玩家消息")]
        scheduled[0]()

        assert chunks == ["直接回复"]
        assert delivered == []
        assert service.discarded == ["旧主动回复"]

    asyncio.run(verify())


def test_cancelled_proactive_stream_does_not_persist_partial_reply():
    from client.companion.service import AIService

    started = asyncio.Event()

    class _Service(AIService):
        async def _stream(self, _messages, **_kwargs):
            yield "半截主动回复"
            started.set()
            await asyncio.Event().wait()

        async def _evaluate_interaction(self, _interaction, _reply):
            raise AssertionError("cancelled proactive reply must not be evaluated")

    async def verify():
        service = object.__new__(_Service)
        service._active = True
        service._recent = []
        service._summary = ""
        service._state = SimpleNamespace()
        service._attention = None
        service._character = None
        service._social = SimpleNamespace(to_prompt_text=lambda: "")
        service._mood = SimpleNamespace(
            decay=lambda: None,
            to_prompt_text=lambda: "",
        )
        service._cognitive = SimpleNamespace(to_prompt_text=lambda: "")
        service._impression = SimpleNamespace(to_prompt_text=lambda: "")
        service._cached_static_prompt = ""
        service._save_recent = lambda: None

        async def consume():
            async for _chunk in service.proactive_chat("事件"):
                pass

        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert service._recent == []

    asyncio.run(verify())


def test_attention_buffer_does_not_clear_concurrent_push():
    from client.companion.attention import AttentionBuffer

    snapshot_taken = threading.Event()
    release_snapshot = threading.Event()

    class _BlockingSnapshotDeque(deque):
        def __iter__(self):
            snapshot = list(super().__iter__())
            snapshot_taken.set()
            assert release_snapshot.wait(timeout=1)
            return iter(snapshot)

    buffer = AttentionBuffer()
    buffer._events = _BlockingSnapshotDeque(["first"], maxlen=10)
    drained = []
    drain_thread = threading.Thread(
        target=lambda: drained.extend(buffer.drain()))
    drain_thread.start()
    assert snapshot_taken.wait(timeout=1)
    push_thread = threading.Thread(target=lambda: buffer.push("second"))
    push_thread.start()
    release_snapshot.set()
    drain_thread.join(timeout=1)
    push_thread.join(timeout=1)

    assert drained == ["first"]
    assert buffer.drain() == ["second"]


def test_game_handlers_declare_their_important_events():
    from client.games.ludo.handler import LudoHandler
    from client.games.uno.handler import UnoHandler

    assert UnoHandler().companion_events(
        {"room_state": "waiting"},
        {"room_state": "playing", "current_player": "alice"},
        "alice",
    ) == []
    assert UnoHandler().companion_events(
        {"room_state": "playing", "current_player": "bob"},
        {"room_state": "playing", "current_player": "alice"},
        "alice",
    ) == []
    assert LudoHandler().companion_events(
        {"room_state": "playing", "current_player": "bob"},
        {
            "room_state": "finished",
            "current_player": "",
            "rankings": ["alice", "bob"],
        },
        "alice",
    ) == ["玩家获得飞行棋第一名"]


def test_companion_unread_state_is_session_only():
    from client.state.notification import NotificationState

    state = NotificationState()
    state.add_companion_unread()
    state.add_companion_unread()
    assert state.companion_unread_count == 2
    state.clear_companion_unread()
    assert state.companion_unread_count == 0


def test_footer_renders_distinct_companion_unread_badge():
    from client.config import NF_COMPANION
    from client.screen import GameScreen

    class _Badge:
        content = ""

        def update(self, text):
            self.content = text

        def refresh(self):
            pass

    badge = _Badge()
    screen = SimpleNamespace(
        state=SimpleNamespace(
            notify=SimpleNamespace(
                badge_seen=True,
                unread_count=0,
                unread_game_count=0,
                companion_unread_count=2,
            ),
            chat=SimpleNamespace(dm_unread={}),
        ),
        query_one=lambda *_args: badge,
    )

    GameScreen.update_badges(screen)

    assert badge.content == f" {NF_COMPANION} 2 "


def test_controller_deletes_active_character_and_selects_next(
        isolated_companion_home, monkeypatch):
    from client.companion import config as cfg
    from client.companion.character import (
        Character, list_characters, save_character,
    )
    from client.companion import controller as controller_module

    cfg.set_current_player("alice")
    save_character(Character(id="first", name="甲"))
    save_character(Character(id="second", name="乙"))
    player_config = cfg.load_player_config()
    player_config["last_character_id"] = "first"
    cfg.save_player_config(player_config)
    monkeypatch.setattr(controller_module, "AIService", _FakeService)
    ctrl = controller_module.CompanionController(_state("alice", "state"))
    ctrl.set_player("alice")
    assert ctrl.get_service().char_id == "first"

    ctrl.delete_character("first")

    assert [item.id for item in list_characters()] == ["second"]
    assert cfg.load_player_config()["last_character_id"] == "second"
    assert ctrl.get_service().char_id == "second"
    ctrl.shutdown()


class _FakeService:
    def __init__(self, state):
        self._state = state
        self.char_id = ""
        self.character = None
        self.closed = False
        self.release = None

    def load_character(self, char_id):
        self.char_id = char_id

    def rebind_state(self, state):
        self._state = state

    def visible_history(self):
        return [
            {"role": "user", "content": "saved question"},
            {"role": "assistant", "content": "saved answer"},
        ]

    def on_exit(self):
        self.closed = True

    async def chat(self, _text):
        if self.release:
            await self.release.wait()
        yield "stale result"

    def tick(self):
        return None

    async def proactive_chat(self, _reason):
        yield "proactive"


@pytest.fixture
def isolated_controller(monkeypatch, isolated_companion_home):
    from client.companion import character
    from client.companion import config as cfg
    from client.companion import controller

    monkeypatch.setattr(controller, "AIService", _FakeService)
    monkeypatch.setattr(
        character, "list_characters",
        lambda: [SimpleNamespace(id="guide")],
    )
    monkeypatch.setattr(
        cfg, "load_player_config",
        lambda: {"enabled": False, "background_proactive": False},
    )
    monkeypatch.setattr(cfg, "save_player_config", lambda _data: None)
    controller.CompanionController._instance = None
    yield controller.CompanionController
    if controller.CompanionController._instance is not None:
        controller.CompanionController._instance.shutdown()
    controller.CompanionController._instance = None


def _state(name, secret):
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    state.status.update_player_info({"name": name, "level": 1})
    state.chat.set_player_name(name)
    state.chat.add_private_message(name, "peer", secret, "10:00")
    return state


def test_controller_rebinds_from_account_a_to_b(isolated_controller):
    from client.companion.attention import look_messages, look_self

    state_a = _state("alice", "alice-only")
    ctrl = isolated_controller.instance(state_a)
    ctrl.set_player("alice")
    service_a = ctrl.get_service()
    assert "alice" in look_self(service_a._state)
    assert "alice-only" in look_messages(service_a._state)

    ctrl.clear_session()
    state_b = _state("bob", "bob-only")
    isolated_controller.instance(state_b).set_player("bob")
    service_b = ctrl.get_service()

    assert service_a.closed
    assert service_b is not service_a
    assert "bob-only" in look_messages(service_b._state)
    assert "alice-only" not in look_messages(service_b._state)


def test_controller_exposes_selected_companion_history(isolated_controller):
    ctrl = isolated_controller.instance(_state("alice", "state"))
    ctrl.set_player("alice")

    assert ctrl.visible_history() == [
        {"role": "user", "content": "saved question"},
        {"role": "assistant", "content": "saved answer"},
    ]


def test_same_name_new_state_replaces_service(isolated_controller):
    state_a = _state("alice", "old-state")
    ctrl = isolated_controller.instance(state_a)
    ctrl.set_player("alice")
    service_a = ctrl.get_service()

    state_b = _state("alice", "new-state")
    isolated_controller.instance(state_b)
    assert ctrl.player == ""
    ctrl.set_player("alice")
    service_b = ctrl.get_service()

    assert service_a.closed
    assert service_b is not service_a
    assert service_b._state.chat.dm_entries["peer"][0].text == "new-state"


def test_stale_async_chat_result_is_rejected(isolated_controller):
    async def run():
        state_a = _state("alice", "old-state")
        ctrl = isolated_controller.instance(state_a)
        ctrl.set_player("alice")
        service_a = ctrl.get_service()
        service_a.release = asyncio.Event()
        chunks = []

        async def collect():
            async for chunk in ctrl.chat("hello"):
                chunks.append(chunk)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        ctrl.rebind_state(_state("bob", "new-state"))
        service_a.release.set()
        await task
        return chunks

    chunks = asyncio.run(run())
    assert chunks == []


def test_foreground_chat_stops_and_restarts_background(isolated_controller):
    async def run():
        ctrl = isolated_controller.instance(_state("alice", "state"))
        ctrl.set_player("alice")
        ctrl._bg_running = True
        events = []

        def stop():
            events.append("stop")
            ctrl._bg_running = False

        def start():
            events.append("start")
            ctrl._bg_running = True

        ctrl._stop_background = stop
        ctrl._start_background = start
        ctrl.is_enabled = lambda: True
        ctrl.is_ready = lambda: True

        chunks = []
        async for chunk in ctrl.chat("hello"):
            events.append("chunk")
            chunks.append(chunk)
        return chunks, events

    chunks, events = asyncio.run(run())

    assert chunks == ["stale result"]
    assert events == ["stop", "chunk", "start"]


def test_session_clear_stops_and_joins_background(
        isolated_controller, monkeypatch):
    from client.companion import config as cfg
    from client.companion import controller as controller_module

    monkeypatch.setattr(
        cfg, "load_player_config",
        lambda: {"enabled": True, "background_proactive": True},
    )
    monkeypatch.setattr(controller_module, "_TICK_INTERVAL", 0.01)
    ctrl = isolated_controller.instance(_state("alice", "state"))
    ctrl.set_player("alice")
    thread = ctrl._bg_thread
    assert thread is not None and thread.is_alive()

    ctrl.clear_session()

    assert not thread.is_alive()
    assert ctrl.player == ""
    assert cfg.get_current_player() == ""


def test_background_stop_timeout_preserves_thread_and_service(
        isolated_controller):
    ctrl = isolated_controller.instance(_state("alice", "state"))
    ctrl.set_player("alice")
    service = ctrl.get_service()

    class _StuckThread:
        def join(self, timeout):
            assert timeout == 3.0

        def is_alive(self):
            return True

    thread = _StuckThread()
    ctrl._bg_thread = thread
    ctrl._bg_running = True

    with pytest.raises(RuntimeError, match="did not stop"):
        ctrl._stop_background()

    assert ctrl._bg_thread is thread
    assert ctrl._service is service

    ctrl._bg_thread = None
