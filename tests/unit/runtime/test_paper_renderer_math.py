"""_convert_inline_math contracts for scientific notation + broken-tail repair.

The historic failure mode (visible in
output/latest/02-writing/artifacts/paper_p1validated.pdf) was that the
section writer emitted ``$p = 7$.6 \\times 10^{-6}$``: math closed too
early, the trailing ``.6 \\times 10^{-6}`` ended up in TEXT mode, and
the PDF rendered ``$p = 7$ Œ10ˆ{-6}`` with literal `$` glyphs.

Two layers of defense:
1. The expanded ``_MATH_PATTERNS`` table catches scientific notation
   (``p = 7.6e-16``, ``p = 7.6 × 10^-6``) and wraps the WHOLE expression.
2. ``_BROKEN_MATH_TAIL`` repairs the ``$X$.digit`` pattern even if a
   downstream agent slips and emits the broken form.
"""
from __future__ import annotations

from academic_pipeline.runtime.paper_renderer import _convert_inline_math


class TestScientificNotation:
    def test_e_notation_wrapped_as_full_math_expr(self) -> None:
        out = _convert_inline_math("Friedman omnibus p = 6.8e-16 reflects power")
        assert "$p = 6.8 \\times 10^{-16}$" in out
        assert "$p = 6$.8" not in out  # historic broken pattern

    def test_unicode_times_form_wrapped(self) -> None:
        out = _convert_inline_math("Holm-adjusted Wilcoxon p = 7.6 × 10^-6 confirms")
        assert "$p = 7.6 \\times 10^{-6}$" in out

    def test_latex_times_with_braces_form_wrapped(self) -> None:
        out = _convert_inline_math("p = 7.6 \\times 10^{-6} significant")
        assert "$p = 7.6 \\times 10^{-6}$" in out

    def test_plain_decimal_p_value(self) -> None:
        out = _convert_inline_math("contrast p = 0.622 not significant")
        assert "$p = 0.622$" in out


class TestBrokenMathTailRepair:
    def test_simple_broken_tail_repaired(self) -> None:
        """The exact failure mode from the offending PDF."""
        broken = r"Wilcoxon $p = 7$.6 confirms"
        out = _convert_inline_math(broken)
        assert "$p = 7.6$" in out
        assert "$p = 7$.6" not in out

    def test_multiple_broken_tails_in_one_paragraph(self) -> None:
        broken = r"K-means vs random $p = 7$.6 and vs GMM $p = 9$.5 emerged"
        out = _convert_inline_math(broken)
        assert "$p = 7.6$" in out
        assert "$p = 9.5$" in out

    def test_already_well_formed_math_unchanged(self) -> None:
        good = r"With $p = 0.05$ as the threshold."
        out = _convert_inline_math(good)
        assert out == good


class TestNoRegressionOnExistingPatterns:
    def test_unicode_geq_still_wrapped(self) -> None:
        out = _convert_inline_math("require n ≥ 100 entities")
        assert "$\\geq$" in out

    def test_unicode_times_standalone_still_wrapped(self) -> None:
        out = _convert_inline_math("a 5 × 3 grid")
        assert "$\\times$" in out

    def test_n_equals_integer_still_wrapped(self) -> None:
        out = _convert_inline_math("on n = 25 entities")
        assert "$n = 25$" in out
