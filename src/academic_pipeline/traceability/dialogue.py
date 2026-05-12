"""Writer↔reviewer dialogue using PydanticAI's native message_history.

Replaces the parallel-scorer eval pattern for section reviews with an N-turn
structured conversation. Terminates on reviewer's termination_phrase or when
max_turns is hit (DialogueExhaustion logged).

Used by SectionDialogueNode (added to writing/graph.py in a future task).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from academic_pipeline.traceability.validators import (
    ABORTING_PHRASES,
    FORBIDDEN_PHRASES,
    make_numeric_output_validator,
)


if TYPE_CHECKING:
    from academic_pipeline.models.numerical import NumericalStore


DEFAULT_TERMINATION_PHRASE = "The section does not require any changes"

logger = logging.getLogger(__name__)


async def run_writer_reviewer_dialogue(
    *,
    writer: Any,
    reviewer: Any,
    prompt: str,
    deps: Any,
    store: NumericalStore,
    max_turns: int = 3,
    termination_phrase: str = DEFAULT_TERMINATION_PHRASE,
    section_name: str = "section",
) -> Any:
    """Run an N-turn writer↔reviewer dialogue. Returns the final writer result.

    Each writer turn applies the numeric output validator to the writer's output
    (full mode means validation is always on within the dialogue). On validator
    failure, the exception propagates — caller handles retry policy.
    """
    history: list[Any] = []
    current_prompt = prompt
    last_writer_result: Any = None
    validator = make_numeric_output_validator(store, FORBIDDEN_PHRASES, ABORTING_PHRASES)

    for _turn in range(max_turns):
        writer_result = await writer.run(current_prompt, message_history=history, deps=deps)
        # Apply validator to writer output (full mode = always on within dialogue)
        # Validator may raise ModelRetry / UnexpectedModelBehavior; let it propagate.
        validator(writer_result.output)
        last_writer_result = writer_result
        history = writer_result.all_messages()

        review_prompt = f"Review this {section_name}:\n{writer_result.output.text}"
        review_result = await reviewer.run(review_prompt, deps=deps)
        if termination_phrase.lower() in review_result.output.text.lower():
            return writer_result

        # Reviewer feedback becomes the next iteration's prompt
        current_prompt = (
            f"Reviewer feedback:\n{review_result.output.text}\n\n"
            f"Revise the {section_name} accordingly."
        )

    logger.warning(
        "DialogueExhaustion: section=%s, max_turns=%d hit without termination",
        section_name, max_turns,
    )
    return last_writer_result
