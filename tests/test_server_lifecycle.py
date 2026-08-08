"""Deterministic server entry-point lifecycle tests."""

from __future__ import annotations

import builtins
import threading

import pytest

import server


@pytest.mark.parametrize("interactive", [False, True])
def test_main_stops_once_and_joins_server_thread(monkeypatch, interactive):
    handlers = {}

    class _Stdin:
        def isatty(self):
            return interactive

    class _Server:
        instance = None

        def __init__(self):
            type(self).instance = self
            self.stop_event = threading.Event()
            self.start_returned = threading.Event()
            self.stop_calls = 0

        def start(self):
            if not interactive:
                handlers[server.signal.SIGTERM]()
            assert self.stop_event.wait(1)
            self.start_returned.set()

        def graceful_stop(self):
            self.stop_calls += 1
            self.stop_event.set()

    monkeypatch.setattr(server, "ChatServer", _Server)
    monkeypatch.setattr(server.sys, "stdin", _Stdin())
    monkeypatch.setattr(
        server.signal, "signal",
        lambda signum, callback: handlers.__setitem__(signum, callback),
    )
    monkeypatch.setattr(builtins, "input", lambda: "quit")

    server.main()

    instance = _Server.instance
    assert instance.stop_calls == 1
    assert instance.start_returned.is_set()
