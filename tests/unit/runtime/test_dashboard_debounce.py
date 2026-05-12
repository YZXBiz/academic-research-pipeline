"""Tests for DashboardDebouncer (PRD §6.8.T4).

Caps dashboard.txt writes at ≤4 Hz (250ms minimum interval). Inline utility
in runtime/dashboard.py — NOT runtime/throttle.py per PRD AP84 (that module
is the PydanticAI Hooks-based agent throttle, wrong API surface).
"""

from __future__ import annotations

from academic_pipeline.runtime.dashboard import DashboardDebouncer


def test_first_acquire_is_always_allowed() -> None:
    """A debouncer with no prior write must permit the very first write."""
    deb = DashboardDebouncer(min_interval_s=0.25)
    assert deb.acquire(now=100.0) is True


def test_acquire_within_min_interval_is_blocked() -> None:
    deb = DashboardDebouncer(min_interval_s=0.25)
    deb.acquire(now=100.0)
    # 200ms later — still inside the 250ms window
    assert deb.acquire(now=100.2) is False


def test_acquire_after_min_interval_is_allowed() -> None:
    deb = DashboardDebouncer(min_interval_s=0.25)
    deb.acquire(now=100.0)
    # 250ms later — boundary inclusive
    assert deb.acquire(now=100.25) is True


def test_acquire_well_after_min_interval_is_allowed() -> None:
    deb = DashboardDebouncer(min_interval_s=0.25)
    deb.acquire(now=100.0)
    # 1s later — definitely allowed
    assert deb.acquire(now=101.0) is True


def test_blocked_acquire_does_not_advance_last_write_ts() -> None:
    """A blocked attempt must not reset the clock — otherwise rapid callers
    could indefinitely defer writes."""
    deb = DashboardDebouncer(min_interval_s=0.25)
    deb.acquire(now=100.0)  # allowed, anchors at 100.0
    deb.acquire(now=100.10)  # blocked
    deb.acquire(now=100.20)  # blocked
    # 250ms after the FIRST allowed write, not after the blocked attempts
    assert deb.acquire(now=100.25) is True


def test_default_min_interval_is_quarter_second() -> None:
    """Default 250ms = 4Hz cap per PRD §6.8.T4."""
    deb = DashboardDebouncer()
    assert deb.min_interval_s == 0.25


def test_custom_min_interval_is_honored() -> None:
    deb = DashboardDebouncer(min_interval_s=1.0)
    deb.acquire(now=100.0)
    assert deb.acquire(now=100.5) is False
    assert deb.acquire(now=101.0) is True


def test_burst_of_50_calls_yields_at_most_four_per_second() -> None:
    """Stress: simulate 50 calls evenly spaced over 1 second.

    50 calls at 20Hz with a 250ms debounce should pass at most 5 (one at
    t=0, 0.25, 0.5, 0.75, 1.0).
    """
    deb = DashboardDebouncer(min_interval_s=0.25)
    allowed = 0
    for i in range(50):
        if deb.acquire(now=i * 0.02):  # 50ms apart = 20Hz call rate
            allowed += 1
    # Boundary-inclusive: t=0.0, 0.26, 0.52, 0.78, 1.04 → but 1.04 is
    # i=52 (out of range). Actually 50ms cadence i=0..49 spans 0..0.98,
    # so allowed = at t=0.0, t=0.26 (i=13), t=0.52 (i=26), t=0.78 (i=39).
    assert allowed == 4
