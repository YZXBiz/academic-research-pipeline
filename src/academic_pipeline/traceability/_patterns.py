"""Shared regex patterns for the traceability layer.

Single source of truth — imported by both validators.py (gate) and substitution.py (renderer).
Keeping these in one file prevents the two consumers from drifting.
"""

from __future__ import annotations


# Matches ⟨num:label⟩ where label is a valid Python identifier
NUM_TOKEN_PATTERN = r"⟨num:(?P<label>[a-zA-Z_][a-zA-Z0-9_]*)⟩"
