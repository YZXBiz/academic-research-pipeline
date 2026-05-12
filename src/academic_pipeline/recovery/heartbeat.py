"""Daemon-thread heartbeat that writes a wall-clock timestamp to disk.

CRITICAL: must be a thread, NOT an asyncio.create_task. When the asyncio
event loop is blocked (e.g., in synchronous socket.recv inside an SDK),
asyncio tasks do not fire — the watchdog would then false-positive on a
stuck-but-trying-to-recover pipeline. A daemon thread runs regardless of
the event loop's state. Ref: Prefect issue #21184 + PR #21276.

Atomic write: writes to .tmp then renames. Watchdog reads stat().mtime;
never sees a half-written file thanks to POSIX-atomic rename.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType
    from typing import Self

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_S = 30.0


class Heartbeat(AbstractContextManager["Heartbeat"]):
    """Background daemon thread writing `path` mtime every `interval_s` seconds."""

    def __init__(self, path: Path, *, interval_s: float = _DEFAULT_INTERVAL_S) -> None:
        """Configure heartbeat to write to ``path`` every ``interval_s`` seconds."""
        self._path = path
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Self:
        """Start the daemon-thread heartbeat loop; create parent dir if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._loop,
            name=f"pipeline-heartbeat-{self._path.name}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Signal the loop to stop; daemon thread dies with the process."""
        self._stop.set()

    def _loop(self) -> None:
        """Tick once immediately, then every interval_s until stop is set."""
        self._tick()
        while not self._stop.wait(timeout=self._interval_s):
            self._tick()

    def _tick(self) -> None:
        """Write current wall-clock time to ``path`` atomically."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(f"{time.time():.6f}")
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("Heartbeat write failed: %s", exc)
