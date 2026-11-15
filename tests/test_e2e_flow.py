"""End to end: a real server process and the real client screen, driven by key presses.

Isolated widget tests missed bugs that only appear with the real message order and the real
full-screen layout (the tutorial not opening after registration, not being centered).
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from client import app as client_app
from client import screen as client_screen
from client import storage
from client.views.system.tutorial import _TOTAL

ROOT = Path(__file__).resolve().parent.parent
SIZES = ((88, 32), (120, 40), (160, 50))
PASSWORD = "e2e-pass-123"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("e2e")
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(ROOT / "Server"), str(ROOT / "Client"))),
        "UPARLOR_PORT": str(port),
        "UPARLOR_DATA_DIR": str(tmp_path / "data"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "server"], cwd=ROOT / "Server", env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("server did not start")
    yield port, tmp_path
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture
def client(server, monkeypatch):
    port, tmp_path = server
    monkeypatch.setattr(client_app, "PORT", port)
    monkeypatch.setattr(client_screen, "DEFAULT_HOST", "127.0.0.1")
    monkeypatch.setattr(storage, "_DIR", tmp_path / "client")
    monkeypatch.setattr(storage, "_FILE", tmp_path / "client" / "config.json")


async def _until(pilot, condition, what: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await pilot.pause(0.1)
    pytest.fail(f"timed out waiting for {what}")


async def _type_line(pilot, text: str) -> None:
    await pilot.press("i")
    await pilot.press(*text, "enter")


async def _log_in(pilot, screen, user: str, *, register: bool) -> None:
    login = screen.get_module("login")
    await _until(pilot, lambda: screen.engine.active_window() is not None, "login window")
    await _until(pilot, lambda: screen.app.network.connected, "connection")
    if register:
        await pilot.press("right")
    await _until(pilot, lambda: login._step == "username", "username prompt")
    await _type_line(pilot, user)
    await _until(pilot, lambda: login._step == "password", "password prompt")
    await _type_line(pilot, PASSWORD)


async def _finish_tutorial(pilot, screen, *, remember: bool) -> None:
    panel = screen.query_one("#tutorial-panel")
    panel._goto_page(_TOTAL - 1)
    await pilot.pause(0.3)
    if remember:
        await pilot.press("enter")
        assert panel.remember_choice()
    await pilot.press("x")
    await _until(pilot, lambda: screen.mode != "tutorial", "tutorial closed")


def test_registering_opens_a_centered_fixed_size_tutorial(client):
    async def run() -> None:
        app = client_app.UParlorApp()
        async with app.run_test(size=SIZES[0]) as pilot:
            screen = app.screen
            await _log_in(pilot, screen, "centered", register=True)
            await _until(pilot, lambda: screen.mode == "tutorial", "tutorial")
            for width, height in SIZES:
                await pilot.resize_terminal(width, height)
                await pilot.pause(0.3)
                region = screen.query_one("#tutorial-panel").region

                assert (region.width, region.height) == (60, 18), (width, height)
                assert region.x == width - (region.x + region.width), (width, height)

    asyncio.run(run())


def test_remembering_on_the_last_page_skips_the_tutorial_next_login(client):
    async def session(register: bool) -> str:
        app = client_app.UParlorApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            await _log_in(pilot, screen, "rememberer", register=register)
            await _until(pilot, lambda: screen.logged_in, "login to finish")
            await pilot.pause(0.5)
            mode = screen.mode
            if mode == "tutorial":
                await _finish_tutorial(pilot, screen, remember=True)
            return mode

    assert asyncio.run(session(True)) == "tutorial"
    assert asyncio.run(session(False)) != "tutorial"


def test_leaving_without_remembering_shows_the_tutorial_again(client):
    async def session(register: bool) -> str:
        app = client_app.UParlorApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            await _log_in(pilot, screen, "forgetter", register=register)
            await _until(pilot, lambda: screen.logged_in, "login to finish")
            await pilot.pause(0.5)
            mode = screen.mode
            if mode == "tutorial":
                await _finish_tutorial(pilot, screen, remember=False)
            return mode

    assert asyncio.run(session(True)) == "tutorial"
    assert asyncio.run(session(False)) == "tutorial"
