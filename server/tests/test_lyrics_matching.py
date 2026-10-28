"""
منطق مشترکِ تطبیق (`app/lyrics/matching.py`).

همه‌چیز اینجا خالص است — نه شبکه، نه mock. قفل‌کننده‌ی اصلی همان تفکیکی است
که باگِ قبلی را می‌ساخت: «مدتِ نامعلوم» با «مدتِ متناقض» یکی نیست.
"""

from __future__ import annotations

import pytest

from app.lyrics import matching


class TestNormalize:
    def test_case_and_punctuation_are_ignored(self):
        assert matching.normalize("Barf (Remastered)!") == {"barf", "remastered"}

    def test_none_becomes_an_empty_set(self):
        assert matching.normalize(None) == frozenset()


class TestSpellingSimilarity:
    def test_a_romanisation_drift_scores_high(self):
        assert matching.spelling_similarity("Mordi", "Moordi") >= 0.8

    def test_a_different_word_scores_low(self):
        assert matching.spelling_similarity("Mordi", "Mahdi") < 0.8

    def test_an_empty_side_scores_zero(self):
        assert matching.spelling_similarity("", "Mordi") == 0.0


class TestDurationMatches:
    """
    سه حالتِ عمدی: هم‌خوان (True)، متناقض (False)، بی‌سیگنال (None).
    """

    def test_a_close_duration_is_accepted(self):
        assert matching.duration_matches(180_000, 181_000) is True

    def test_the_tolerance_boundary_is_inclusive_in_seconds(self):
        tol = matching.DEFAULT_DURATION_TOLERANCE_S
        assert matching.duration_matches((180 + tol) * 1000, 180_000) is True
        assert matching.duration_matches((180 + tol) * 1000 + 1, 180_000) is False

    def test_a_far_duration_is_rejected(self):
        assert matching.duration_matches(300_000, 180_000) is False

    def test_a_zero_candidate_duration_is_no_signal_not_a_rejection(self):
        """قاعده‌ی کلیدی: نبودِ مدت چیزی را رد نمی‌کند."""
        assert matching.duration_matches(0, 180_000) is None

    def test_a_none_candidate_duration_is_no_signal(self):
        assert matching.duration_matches(None, 180_000) is None

    def test_an_unknown_wanted_duration_is_no_signal(self):
        assert matching.duration_matches(180_000, 0) is None
        assert matching.duration_matches(180_000, None) is None

    def test_the_tolerance_is_configurable(self):
        assert matching.duration_matches(184_000, 180_000, tolerance_s=3) is False
        assert matching.duration_matches(184_000, 180_000, tolerance_s=5) is True


class TestUnwantedVersionMarkers:
    @pytest.mark.parametrize(
        "marker",
        ["live", "remix", "acoustic", "instrumental", "slowed", "sped", "karaoke", "cover"],
    )
    def test_a_version_marker_is_detected(self, marker):
        got = matching.unwanted_version_markers(f"Barf ({marker})", "Barf")
        assert got == {marker}

    def test_a_remaster_is_not_a_version_marker(self):
        """ریمستر همان ضبط است؛ متنش عوض نشده."""
        assert matching.unwanted_version_markers("Barf (Remastered)", "Barf") == frozenset()
        assert "remaster" in matching.SAME_RECORDING_MARKERS

    def test_a_marker_the_caller_wanted_is_not_unwanted(self):
        assert matching.unwanted_version_markers("Barf (Live)", "Barf (Live)") == frozenset()

    def test_a_clean_title_has_no_markers(self):
        assert matching.unwanted_version_markers("Barf", "Barf") == frozenset()


class TestScoreCandidate:
    def test_an_exact_match_is_acceptable(self):
        score = matching.score_candidate(
            want_title="Barf", want_artist="Farhad", got_title="Barf", got_artist="Farhad"
        )
        assert score.acceptable is True
        assert score.unwanted_markers == frozenset()

    def test_a_conflicting_duration_makes_it_unacceptable(self):
        score = matching.score_candidate(
            want_title="Barf",
            want_artist="Farhad",
            got_title="Barf",
            got_artist="Farhad",
            candidate_duration_ms=300_000,
            wanted_duration_ms=180_000,
        )
        assert score.duration is False
        assert score.acceptable is False

    def test_an_unknown_duration_still_accepts(self):
        score = matching.score_candidate(
            want_title="Barf",
            want_artist="Farhad",
            got_title="Barf",
            got_artist="Farhad",
            candidate_duration_ms=None,
            wanted_duration_ms=180_000,
        )
        assert score.duration is None
        assert score.acceptable is True

    def test_a_wrong_artist_makes_it_unacceptable(self):
        score = matching.score_candidate(
            want_title="Barf", want_artist="Farhad", got_title="Barf", got_artist="Someone"
        )
        assert score.acceptable is False

    def test_an_unrelated_title_is_unacceptable(self):
        score = matching.score_candidate(
            want_title="Barf", want_artist="Farhad", got_title="Totally Other", got_artist="Farhad"
        )
        assert score.acceptable is False

    def test_a_version_marker_alone_does_not_reject(self):
        """آخرین چاره است، نه رد — منطق ترجیح در `rank_candidates` است."""
        score = matching.score_candidate(
            want_title="Barf", want_artist="Farhad", got_title="Barf (Live)", got_artist="Farhad"
        )
        assert score.unwanted_markers == {"live"}
        assert score.acceptable is True

    def test_no_artist_expected_means_nobody_to_mismatch(self):
        score = matching.score_candidate(
            want_title="Barf", want_artist="", got_title="Barf", got_artist="Whoever"
        )
        assert score.artist_expected is False
        assert score.acceptable is True

    def test_a_romanisation_drift_is_accepted_on_spelling(self):
        score = matching.score_candidate(
            want_title="Mordi", want_artist="Tlkhoon", got_title="Moordi", got_artist="Tlkhoon"
        )
        assert score.spelling >= 0.8
        assert score.acceptable is True


class TestRankCandidates:
    def _score(self, **kwargs) -> matching.MatchScore:
        return matching.score_candidate(
            want_title=kwargs.pop("want_title", "Barf"),
            want_artist=kwargs.pop("want_artist", "Farhad"),
            got_title=kwargs.pop("got_title", "Barf"),
            got_artist=kwargs.pop("got_artist", "Farhad"),
            **kwargs,
        )

    def test_an_unmarked_candidate_beats_a_marked_one(self):
        scored = [
            (0, self._score(got_title="Barf (Live)")),
            (1, self._score(got_title="Barf")),
        ]
        assert matching.rank_candidates(scored)[0] == 1

    def test_a_duration_match_beats_an_unknown_duration(self):
        scored = [
            (0, self._score(candidate_duration_ms=None, wanted_duration_ms=180_000)),
            (1, self._score(candidate_duration_ms=180_000, wanted_duration_ms=180_000)),
        ]
        assert matching.rank_candidates(scored)[0] == 1

    def test_a_marked_candidate_is_still_ranked_last_not_dropped(self):
        scored = [(0, self._score(got_title="Barf (Live)"))]
        assert matching.rank_candidates(scored) == [0]

    def test_a_better_spelling_wins_the_tie(self):
        scored = [
            (0, self._score(want_title="Mordi", got_title="Moordi")),
            (1, self._score(want_title="Mordi", got_title="Mordi")),
        ]
        assert matching.rank_candidates(scored)[0] == 1
