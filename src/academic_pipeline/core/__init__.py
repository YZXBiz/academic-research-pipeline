"""State dataclasses for the academic pipeline.

- pipeline.py: PipelineState (orchestrator)
- research.py, writing.py, review.py, integrity.py: Per-subgraph state
- enums.py: StrEnums (Stage, Verdict, etc.)
- deps.py: PipelineDeps (dependency injection)
"""

from __future__ import annotations
