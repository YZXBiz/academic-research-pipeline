"""Tests for score trajectory utility functions."""

from __future__ import annotations

from academic_pipeline.runtime.score_trajectory import (
    DIMENSIONS,
    check_early_stop,
    compute_deltas,
    detect_regression,
    parse_scores_from_review,
)


class TestComputeDeltas:
    def test_basic_deltas(self) -> None:
        current = {"argument_strength": 80, "evidence_quality": 70, "overall": 75}
        previous = {"argument_strength": 60, "evidence_quality": 75, "overall": 65}
        deltas = compute_deltas(current, previous)
        assert deltas == {"argument_strength": 20, "evidence_quality": -5, "overall": 10}

    def test_only_shared_dimensions(self) -> None:
        """Only dimensions in DIMENSIONS and present in both dicts are included."""
        current = {"argument_strength": 80, "originality": 50}
        previous = {"argument_strength": 70, "writing_clarity": 60}
        deltas = compute_deltas(current, previous)
        assert deltas == {"argument_strength": 10}

    def test_empty_inputs(self) -> None:
        assert compute_deltas({}, {}) == {}

    def test_no_overlap(self) -> None:
        current = {"argument_strength": 80}
        previous = {"evidence_quality": 70}
        assert compute_deltas(current, previous) == {}

    def test_all_dimensions(self) -> None:
        current = dict.fromkeys(DIMENSIONS, 80)
        previous = dict.fromkeys(DIMENSIONS, 70)
        deltas = compute_deltas(current, previous)
        assert all(v == 10 for v in deltas.values())
        assert len(deltas) == len(DIMENSIONS)

    def test_zero_delta(self) -> None:
        scores = {"overall": 50, "originality": 60}
        assert compute_deltas(scores, scores) == {"overall": 0, "originality": 0}


class TestDetectRegression:
    def test_no_regression(self) -> None:
        deltas = {"argument_strength": 5, "evidence_quality": 0, "overall": -3}
        assert detect_regression(deltas) == []

    def test_boundary_no_regression(self) -> None:
        """Delta of exactly -3 should NOT trigger regression (threshold is <, not <=)."""
        deltas = {"argument_strength": -3}
        assert detect_regression(deltas) == []

    def test_regression_at_minus_four(self) -> None:
        """Delta of -4 should trigger regression."""
        deltas = {"argument_strength": -4, "evidence_quality": 2}
        assert detect_regression(deltas) == ["argument_strength"]

    def test_multiple_regressions(self) -> None:
        deltas = {"argument_strength": -5, "evidence_quality": -10, "overall": 3}
        result = detect_regression(deltas)
        assert "argument_strength" in result
        assert "evidence_quality" in result
        assert "overall" not in result
        assert len(result) == 2

    def test_custom_threshold(self) -> None:
        deltas = {"overall": -2}
        assert detect_regression(deltas, threshold=-1) == ["overall"]
        assert detect_regression(deltas, threshold=-2) == []

    def test_empty_deltas(self) -> None:
        assert detect_regression({}) == []


class TestCheckEarlyStop:
    def test_all_below_threshold_no_p0(self) -> None:
        deltas = {"argument_strength": 1, "evidence_quality": 2, "overall": 0}
        assert check_early_stop(deltas, has_p0=False) is True

    def test_one_at_threshold(self) -> None:
        """Delta equal to threshold should NOT trigger early stop (< not <=)."""
        deltas = {"argument_strength": 3, "evidence_quality": 1}
        assert check_early_stop(deltas, threshold=3, has_p0=False) is False

    def test_one_above_threshold(self) -> None:
        deltas = {"argument_strength": 5, "evidence_quality": 1}
        assert check_early_stop(deltas, threshold=3, has_p0=False) is False

    def test_has_p0_blocks_early_stop(self) -> None:
        deltas = {"argument_strength": 1, "evidence_quality": 0}
        assert check_early_stop(deltas, has_p0=True) is False

    def test_empty_deltas(self) -> None:
        assert check_early_stop({}, has_p0=False) is False

    def test_negative_deltas_converge(self) -> None:
        """Negative deltas are below threshold so they indicate convergence."""
        deltas = {"argument_strength": -1, "overall": 0}
        assert check_early_stop(deltas, has_p0=False) is True

    def test_custom_threshold(self) -> None:
        deltas = {"overall": 4}
        assert check_early_stop(deltas, threshold=5, has_p0=False) is True
        assert check_early_stop(deltas, threshold=4, has_p0=False) is False


class TestParseScoresFromReview:
    def test_colon_format_with_slash(self) -> None:
        review = "Argument Strength: 75/100\nEvidence Quality: 80/100\nOverall: 78/100\n"
        scores = parse_scores_from_review(review)
        assert scores["argument_strength"] == 75
        assert scores["evidence_quality"] == 80
        assert scores["overall"] == 78

    def test_colon_format_without_slash(self) -> None:
        review = "argument_strength: 65\nwriting_clarity: 70\n"
        scores = parse_scores_from_review(review)
        assert scores["argument_strength"] == 65
        assert scores["writing_clarity"] == 70

    def test_table_format(self) -> None:
        review = "| Argument Strength | 75 |\n| Evidence Quality | 80/100 |\n| Originality | 60 |\n"
        scores = parse_scores_from_review(review)
        assert scores["argument_strength"] == 75
        assert scores["evidence_quality"] == 80
        assert scores["originality"] == 60

    def test_table_format_snake_case(self) -> None:
        review = "| argument_strength | 72/100 |\n| overall | 68 |\n"
        scores = parse_scores_from_review(review)
        assert scores["argument_strength"] == 72
        assert scores["overall"] == 68

    def test_empty_input(self) -> None:
        assert parse_scores_from_review("") == {}

    def test_no_matching_dimensions(self) -> None:
        review = "Random Text: 50/100\nSomething Else: 30\n"
        assert parse_scores_from_review(review) == {}

    def test_malformed_input(self) -> None:
        review = "This is a review without any scores at all. Just text."
        assert parse_scores_from_review(review) == {}

    def test_mixed_formats(self) -> None:
        review = "## Scores\nArgument Strength: 75/100\n| Evidence Quality | 80 |\nMethodological Rigor: 65\n"
        scores = parse_scores_from_review(review)
        assert scores["argument_strength"] == 75
        assert scores["evidence_quality"] == 80
        assert scores["methodological_rigor"] == 65

    def test_score_out_of_range_ignored(self) -> None:
        review = "Argument Strength: 150/100\nOverall: 50\n"
        scores = parse_scores_from_review(review)
        assert "argument_strength" not in scores
        assert scores["overall"] == 50

    def test_first_match_wins(self) -> None:
        """If a dimension appears multiple times, the first match wins."""
        review = "Overall: 70\nOverall: 90\n"
        scores = parse_scores_from_review(review)
        assert scores["overall"] == 70

    def test_all_dimensions_parseable(self) -> None:
        lines = [f"| {dim.replace('_', ' ').title()} | {50 + i * 5} |" for i, dim in enumerate(DIMENSIONS)]
        review = "\n".join(lines)
        scores = parse_scores_from_review(review)
        assert len(scores) == len(DIMENSIONS)


# PRD §6.11.T1 — per-thread score-trajectory persistence.


class TestScoreTrajectoryPersistence:
    """Round-trip + missing-file behavior for save/load helpers."""

    def test_save_then_load_round_trips(self, tmp_path) -> None:
        from academic_pipeline.runtime.score_trajectory import (
            load_score_trajectory,
            save_score_trajectory,
        )

        history = [
            {"round": 1, "overall": 60, "argument_strength": 65},
            {"round": 2, "overall": 72, "argument_strength": 70},
        ]
        flags = ["round_2_regression: writing_clarity"]

        save_score_trajectory(
            thread_id="t-roundtrip",
            score_history=history,
            score_trajectory_flags=flags,
            persistence_dir=tmp_path,
        )

        loaded_history, loaded_flags = load_score_trajectory(
            thread_id="t-roundtrip",
            persistence_dir=tmp_path,
        )
        assert loaded_history == history
        assert loaded_flags == flags

    def test_save_creates_per_thread_file_at_documented_path(self, tmp_path) -> None:
        """File lands at <persistence_dir>/<thread-id>_scores.json (PRD §6.11.T1)."""
        from academic_pipeline.runtime.score_trajectory import save_score_trajectory

        save_score_trajectory(
            thread_id="t-path",
            score_history=[{"round": 1, "overall": 55}],
            score_trajectory_flags=[],
            persistence_dir=tmp_path,
        )
        assert (tmp_path / "t-path_scores.json").is_file()

    def test_load_returns_empty_when_file_absent(self, tmp_path) -> None:
        """Missing file ⇒ ([], []) (no exception)."""
        from academic_pipeline.runtime.score_trajectory import load_score_trajectory

        history, flags = load_score_trajectory(
            thread_id="never-saved",
            persistence_dir=tmp_path,
        )
        assert history == []
        assert flags == []

    def test_save_overwrites_existing_file(self, tmp_path) -> None:
        """Repeated saves replace the previous payload (latest wins)."""
        from academic_pipeline.runtime.score_trajectory import (
            load_score_trajectory,
            save_score_trajectory,
        )

        save_score_trajectory(
            thread_id="t-over",
            score_history=[{"round": 1, "overall": 50}],
            score_trajectory_flags=[],
            persistence_dir=tmp_path,
        )
        save_score_trajectory(
            thread_id="t-over",
            score_history=[{"round": 1, "overall": 50}, {"round": 2, "overall": 80}],
            score_trajectory_flags=["round_2_early_stop"],
            persistence_dir=tmp_path,
        )

        history, flags = load_score_trajectory(
            thread_id="t-over",
            persistence_dir=tmp_path,
        )
        assert len(history) == 2
        assert history[1]["overall"] == 80
        assert flags == ["round_2_early_stop"]

    def test_per_thread_isolation(self, tmp_path) -> None:
        """Two thread_ids write to disjoint files."""
        from academic_pipeline.runtime.score_trajectory import (
            load_score_trajectory,
            save_score_trajectory,
        )

        save_score_trajectory(
            thread_id="t-A",
            score_history=[{"round": 1, "overall": 70}],
            score_trajectory_flags=["a"],
            persistence_dir=tmp_path,
        )
        save_score_trajectory(
            thread_id="t-B",
            score_history=[{"round": 1, "overall": 90}],
            score_trajectory_flags=["b"],
            persistence_dir=tmp_path,
        )

        ha, fa = load_score_trajectory("t-A", persistence_dir=tmp_path)
        hb, fb = load_score_trajectory("t-B", persistence_dir=tmp_path)
        assert ha[0]["overall"] == 70
        assert hb[0]["overall"] == 90
        assert fa == ["a"]
        assert fb == ["b"]
