from client import ime


class _FakeSources:
    def __init__(self, current, chinese_sources=("pinyin",)):
        self.selected = current
        self.chinese_sources = list(chinese_sources)
        self.log = []
        self.live = 0

    def _new(self, source):
        self.live += 1
        return source

    def current(self):
        return self._new(self.selected)

    def ascii_capable(self):
        return self._new("abc")

    def retain(self, source):
        return self._new(source)

    def release(self, source):
        self.live -= 1

    def select(self, source):
        self.log.append(source)
        self.selected = source

    def is_chinese(self, source):
        return source in self.chinese_sources

    def enabled_chinese(self):
        return self._new(self.chinese_sources[0]) if self.chinese_sources else None


def test_mac_switcher_restores_the_remembered_chinese_source():
    sources = _FakeSources("wubi", chinese_sources=("pinyin", "wubi"))
    switcher = ime._MacSwitcher(sources)

    switcher.to_english()
    assert sources.selected == "abc"
    switcher.to_chinese()

    assert sources.log == ["abc", "wubi"]


def test_mac_switcher_falls_back_to_first_enabled_chinese_source():
    sources = _FakeSources("abc")
    switcher = ime._MacSwitcher(sources)

    switcher.to_english()
    switcher.to_chinese()

    assert sources.log == ["abc", "pinyin"]


def test_mac_switcher_still_selects_when_the_reported_source_may_be_stale():
    sources = _FakeSources("abc", chinese_sources=())
    switcher = ime._MacSwitcher(sources)

    switcher.to_english()
    switcher.to_chinese()

    assert sources.log == ["abc"]


def test_mac_switcher_releases_every_reference_it_does_not_keep():
    sources = _FakeSources("pinyin")
    switcher = ime._MacSwitcher(sources)

    for _ in range(3):
        switcher.to_english()
        switcher.to_chinese()

    assert sources.live == 1


def test_english_ime_insert_enters_english_even_when_chinese_is_remembered(monkeypatch):
    sources = _FakeSources("pinyin")
    switcher = ime._MacSwitcher(sources)
    monkeypatch.setattr(ime, "_switcher", switcher)

    ime.on_insert_enter(english_ime=True)
    assert sources.selected == "abc"

    ime.on_insert_enter()
    assert sources.selected == "pinyin"


def _use(monkeypatch, current, **kw):
    sources = _FakeSources(current, **kw)
    monkeypatch.setattr(ime, "_switcher", ime._MacSwitcher(sources))
    monkeypatch.setattr(ime, "_chinese_preferred", True)
    return sources


def test_first_insert_uses_chinese_when_nothing_is_remembered(monkeypatch):
    sources = _use(monkeypatch, "abc")

    ime.on_insert_enter()

    assert sources.selected == "pinyin"


def test_insert_remembers_whether_the_player_ended_in_english(monkeypatch):
    sources = _use(monkeypatch, "abc")

    ime.on_insert_enter()
    sources.selected = "abc"                  # 玩家在输入框里自己切到了英文
    ime.on_insert_leave()
    assert sources.selected == "abc"          # NORMAL 一律英文

    ime.on_insert_enter()
    assert sources.selected == "abc"          # 下次进入输入框还是英文

    sources.selected = "pinyin"               # 这次又切回中文
    ime.on_insert_leave()
    ime.on_insert_enter()
    assert sources.selected == "pinyin"


def test_english_only_fields_neither_switch_to_chinese_nor_rewrite_the_memory(monkeypatch):
    sources = _use(monkeypatch, "abc")
    ime.on_insert_enter()
    sources.selected = "pinyin"
    ime.on_insert_leave()                     # 记成中文

    ime.on_insert_enter(english_ime=True)     # 登录框
    assert sources.selected == "abc"
    ime.on_insert_leave(english_ime=True)

    ime.on_insert_enter()
    assert sources.selected == "pinyin"       # 登录框没有把记录改成英文


def test_regaining_focus_while_typing_restores_the_typing_method_not_english(monkeypatch):
    sources = _use(monkeypatch, "abc")
    ime.on_insert_enter()                     # 中文

    ime.on_app_blur(in_insert=True)
    sources.selected = "abc"                  # 切走期间别的软件把输入法改了
    ime.on_app_focus(normal_mode=False)

    assert sources.selected == "pinyin"


def test_regaining_focus_in_normal_mode_selects_english(monkeypatch):
    sources = _use(monkeypatch, "pinyin")

    ime.on_app_focus(normal_mode=True)

    assert sources.selected == "abc"


def test_blur_in_insert_remembers_an_english_choice(monkeypatch):
    sources = _use(monkeypatch, "abc")
    ime.on_insert_enter()
    sources.selected = "abc"

    ime.on_app_blur(in_insert=True)
    ime.on_app_focus(normal_mode=False)

    assert sources.selected == "abc"
