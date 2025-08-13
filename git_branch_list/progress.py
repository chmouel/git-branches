from __future__ import annotations

import sys
import threading
import time


class Spinner:
    """Lightweight stderr spinner for long operations.

    Usage:
        with Spinner("Fetching PRs...") as sp:
            # do work
            sp.update("Fetching page 2...")
    """

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, text: str, enabled: bool | None = None, interval: float = 0.08) -> None:
        self.text = text
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_idx = 0
        if enabled is None:
            # Default: only show on TTY stderr
            enabled = sys.stderr.isatty()
        self.enabled = enabled
        self._last_len = 0

    def __enter__(self) -> Spinner:  # noqa: D401
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        self.stop()

    def start(self) -> None:
        if not self.enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        # Clear line
        sys.stderr.write("\r" + " " * max(self._last_len, 0) + "\r")
        sys.stderr.flush()

    def update(self, text: str) -> None:
        self.text = text

    def _run(self) -> None:
        while not self._stop.is_set():
            frame = self.FRAMES[self._frame_idx % len(self.FRAMES)]
            msg = f"{frame} {self.text}"
            self._render(msg)
            self._frame_idx += 1
            time.sleep(self.interval)

    def _render(self, msg: str) -> None:
        self._last_len = len(msg)
        sys.stderr.write("\r" + msg)
        sys.stderr.flush()
