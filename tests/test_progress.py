from __future__ import annotations

import io
import sys
import time

from git_branch_list.progress import Spinner


class _FakeErr(io.StringIO):
    def isatty(self):  # noqa: D401
        return True


def test_spinner_manual_render(monkeypatch):
    fake = _FakeErr()
    monkeypatch.setattr(sys, "stderr", fake)
    sp = Spinner("Working...", enabled=True, interval=0.001)
    # call private render to avoid thread flakiness and still cover rendering
    sp._render("⠋ Working...")  # noqa: SLF001
    s = fake.getvalue()
    assert "Working..." in s


def test_spinner_start_stop_thread(monkeypatch):
    fake = _FakeErr()
    monkeypatch.setattr(sys, "stderr", fake)
    # Make sleep yield once to allow one loop iteration
    calls = {"n": 0}

    def _sleep(_):
        calls["n"] += 1
        # Stop after first loop
        time_original(0)

    time_original = time.sleep
    try:
        monkeypatch.setattr(time, "sleep", _sleep)
        sp = Spinner("Tick", enabled=True, interval=0.0001)
        sp.start()
        # Let thread run at least once
        time_original(0.01)
        sp.stop()
        assert calls["n"] >= 1
    finally:
        time.sleep = time_original  # type: ignore[assignment]
