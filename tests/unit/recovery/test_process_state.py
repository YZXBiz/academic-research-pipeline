"""Tests for the ProcessLock context manager (PID + PGID files)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from academic_pipeline.recovery.process_state import ProcessLock


if TYPE_CHECKING:
    from pathlib import Path


def test_process_lock_creates_pid_and_pgid_files(tmp_path: Path) -> None:
    with ProcessLock(tmp_path, "test-run"):
        assert (tmp_path / "test-run.pid").exists()
        assert (tmp_path / "test-run.pgid").exists()


def test_process_lock_writes_current_pid(tmp_path: Path) -> None:
    with ProcessLock(tmp_path, "t"):
        assert (tmp_path / "t.pid").read_text().strip() == str(os.getpid())


def test_process_lock_pgid_is_an_integer(tmp_path: Path) -> None:
    with ProcessLock(tmp_path, "t"):
        pgid = int((tmp_path / "t.pgid").read_text().strip())
        assert pgid > 0


def test_process_lock_removes_files_on_clean_exit(tmp_path: Path) -> None:
    with ProcessLock(tmp_path, "t"):
        pass
    assert not (tmp_path / "t.pid").exists()
    assert not (tmp_path / "t.pgid").exists()


def test_process_lock_removes_files_on_exception(tmp_path: Path) -> None:
    class _Marker(Exception):  # noqa: N818
        pass

    try:
        with ProcessLock(tmp_path, "t"):
            raise _Marker
    except _Marker:
        pass
    assert not (tmp_path / "t.pid").exists()
    assert not (tmp_path / "t.pgid").exists()


def test_process_lock_atomic_write_no_temp_left_behind(tmp_path: Path) -> None:
    with ProcessLock(tmp_path, "t"):
        files = list(tmp_path.iterdir())
        names = {f.name for f in files}
    assert ".tmp" not in "".join(names), f"Temp file leaked: {names}"
