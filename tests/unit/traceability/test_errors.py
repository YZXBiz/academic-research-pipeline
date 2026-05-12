"""Tests for traceability typed exceptions."""

from __future__ import annotations

from academic_pipeline.traceability.errors import (
    CopilotTimeout,
    DialogueExhaustion,
    NumericValidatorAbort,
    NumericValidatorRetry,
    StoreIntegrityError,
    SubstitutionFailure,
    TraceabilityError,
)


def test_all_errors_inherit_traceability_error():
    for cls in (
        NumericValidatorRetry,
        NumericValidatorAbort,
        SubstitutionFailure,
        StoreIntegrityError,
        CopilotTimeout,
        DialogueExhaustion,
    ):
        assert issubclass(cls, TraceabilityError)


def test_error_codes_are_stable():
    assert NumericValidatorRetry.error_code == "TRC001"
    assert NumericValidatorAbort.error_code == "TRC002"
    assert SubstitutionFailure.error_code == "TRC003"
    assert StoreIntegrityError.error_code == "TRC004"
    assert CopilotTimeout.error_code == "TRC005"
    assert DialogueExhaustion.error_code == "TRC006"


def test_substitution_failure_carries_label_detail():
    err = SubstitutionFailure("missing token", label="foo", section_name="results", store_label_count=10)
    assert err.label == "foo"
    assert err.section_name == "results"
    assert err.store_label_count == 10


def test_store_integrity_error_carries_invariant_detail():
    err = StoreIntegrityError("duplicate", invariant_name="unique_label", offending_label="x")
    assert err.invariant_name == "unique_label"
    assert err.offending_label == "x"
