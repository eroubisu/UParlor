"""系统检测只有一个入口；各后端按它选，没适配的系统降级成什么都不做。"""

from __future__ import annotations

import socket
import sys

import pytest

from client import hostplatform, ime
from client.net import connection


@pytest.mark.parametrize("raw, expected", [
    ("win32", hostplatform.WINDOWS),
    ("darwin", hostplatform.MACOS),
    ("linux", hostplatform.LINUX),
    ("linux2", hostplatform.LINUX),
    ("freebsd13", hostplatform.OTHER),
])
def test_current_names_the_operating_system(monkeypatch, raw, expected):
    monkeypatch.setattr(sys, "platform", raw)

    assert hostplatform.current() == expected


class _Sock:
    def __init__(self):
        self.options = []
        self.ioctls = []

    def setsockopt(self, level, name, value):
        self.options.append((name, value))

    def ioctl(self, code, values):
        self.ioctls.append((code, values))


def test_keepalive_uses_the_backend_of_the_detected_system(monkeypatch):
    monkeypatch.setattr(socket, "TCP_KEEPIDLE", 4, raising=False)
    monkeypatch.setattr(socket, "TCP_KEEPINTVL", 5, raising=False)
    monkeypatch.setattr(socket, "TCP_KEEPCNT", 6, raising=False)
    monkeypatch.setattr(socket, "SIO_KEEPALIVE_VALS", 99, raising=False)

    def keepalive(system):
        monkeypatch.setattr(hostplatform, "current", lambda: system)
        sock = _Sock()
        connection._enable_keepalive(sock, idle=60, interval=10, count=5)
        return sock

    linux = keepalive(hostplatform.LINUX)
    assert [name for name, _ in linux.options] == [socket.SO_KEEPALIVE, 4, 5, 6]
    mac = keepalive(hostplatform.MACOS)
    assert (0x10, 60) in mac.options
    windows = keepalive(hostplatform.WINDOWS)
    assert windows.ioctls == [(99, (1, 60000, 10000))]
    other = keepalive(hostplatform.OTHER)
    assert [name for name, _ in other.options] == [socket.SO_KEEPALIVE]


def test_ime_does_nothing_on_an_unsupported_system(monkeypatch):
    monkeypatch.setattr(hostplatform, "current", lambda: hostplatform.OTHER)

    assert ime._create_switcher() is None
    monkeypatch.setattr(ime, "_switcher", None)
    ime.on_insert_enter()
    ime.on_insert_leave()
    ime.on_app_blur()
    ime.on_app_focus()


def test_only_hostplatform_reads_the_operating_system():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "Client" / "client"
    offenders = [
        path.name for path in root.rglob("*.py")
        if path.name != "hostplatform.py"
        and any(needle in path.read_text(encoding="utf-8")
                for needle in ("sys.platform", "platform.system(", "os.name"))
    ]

    assert offenders == []
