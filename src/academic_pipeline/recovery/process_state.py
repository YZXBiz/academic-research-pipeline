"""Context manager that writes the running pipeline's PID + PGID to disk.

Used by the watchdog to find the right process group to kill on hang.
File lifecycle is bounded by `with ProcessLock(...)`: created on enter,
removed on exit (clean OR exception). Uses POSIX-atomic write (.tmp +
rename) so a watchdog reading mid-write never sees a half-written PID.
"""

from __future__ import annotations

import logging
import os
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType
    from typing import Self

logger = logging.getLogger(__name__)


class ProcessLock(AbstractContextManager["ProcessLock"]):
    """Atomic PID + PGID files for the duration of a pipeline run."""

    def __init__(self, persistence_dir: Path, thread_id: str) -> None:
        """Set up file paths under persistence_dir for the given thread_id."""
        self._pid_file = persistence_dir / f"{thread_id}.pid"
        self._pgid_file = persistence_dir / f"{thread_id}.pgid"

    def __enter__(self) -> Self:
        """Write PID and PGID files atomically; create parent dir if needed."""
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self._pid_file, str(os.getpid()))
        try:
            pgid = os.getpgid(0)
        except OSError:
            # Best-effort: write own PID as PGID. Watchdog will fall back to
            # single-process kill, which still works for the common case.
            pgid = os.getpid()
        self._atomic_write(self._pgid_file, str(pgid))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Remove PID + PGID files; tolerates missing files."""
        self._pid_file.unlink(missing_ok=True)
        self._pgid_file.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Write content atomically via tmp + POSIX rename."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(path)
