"""ContextSpec — declares which state slice + numerical labels an agent is allowed to see.

Each agent that reads from PipelineState declares a ContextSpec. The build_curated_context
function (Task 13) uses the spec to construct a curated prompt context, preventing context
bleed across agents.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ContextSpec(BaseModel):
    """Curated context spec for one agent invocation."""

    model_config = ConfigDict(frozen=True)

    allowed_products: list[str]
    """State field paths this agent may read (e.g., 'research.synthesis')."""

    allowed_numerical_labels: list[str] | Literal["all"]
    """Numerical labels this agent may cite. 'all' = full store; list = filtered subset."""
