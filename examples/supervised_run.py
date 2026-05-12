"""Programmatic supervised-run — wraps Pipeline in watchdog + heartbeat.

Equivalent to `make run-experiment TOPIC=...` but invoked from Python.
The supervisor forks the pipeline as a subprocess + a watchdog as a sibling
so a hung pipeline auto-recovers without operator intervention.
"""

from __future__ import annotations

from academic_pipeline.recovery.supervisor import supervised_run


def main() -> int:
    return supervised_run(
        "Hang-recovery demonstration topic",
        "--force-experiment",
        output_dir="/tmp/example-output",
        no_watchdog=False,
        verbose=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
