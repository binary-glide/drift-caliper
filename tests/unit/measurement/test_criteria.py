"""Unit tests for ScoringCriteria (BIN-58).

Pins the seven acceptance scenarios in
``tests/bdd/features/measurement/scoring-criteria-text-rubric.feature`` at
the unit level. Error assertions follow ADR-002: type + required
``context`` keys only -- never message text.

OQ-3 (whether criteria attach at judge creation, monitoring setup,
per-call, or some combination) is open. These tests exercise
``ScoringCriteria`` directly and do not wire it to ``Judge`` -- doing so
would silently decide OQ-3, which is not this story's job.

There is no "missing" case for this value object: every scenario in the
feature file supplies a value (including the empty string and
whitespace-only cases), so every ``InvalidParameterError`` raised here has
``context["kind"] == "invalid"``. Contrast with BIN-57's ``Judge.create``,
whose optional ``model_version`` parameter makes a genuine "missing" case
reachable.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from caliper.errors import InvalidParameterError
from caliper.measurement import ScoringCriteria


def test_accepts_text_rubric_and_reports_it_when_inspected() -> None:
    """SC1: criteria configured with a text rubric report it back."""
    rubric = "Evaluate the response for factual accuracy and helpfulness."

    criteria = ScoringCriteria(value=rubric)

    assert criteria.value == rubric


def test_raises_invalid_parameter_error_when_criteria_is_empty_string() -> None:
    """SC2: empty-string criteria fail as a classifiable invalid parameter."""
    with pytest.raises(InvalidParameterError) as exc_info:
        ScoringCriteria(value="")

    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "scoring_criteria"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == ""
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


def test_raises_invalid_parameter_error_when_criteria_is_whitespace_only() -> None:
    """SC3: whitespace-only criteria fail as a classifiable invalid parameter."""
    whitespace_only = "   \t  \n "

    with pytest.raises(InvalidParameterError) as exc_info:
        ScoringCriteria(value=whitespace_only)

    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "scoring_criteria"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == whitespace_only
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


def test_missing_and_invalid_criteria_share_message_free_context_shape() -> None:
    """SC2 vs SC3: both invalid-kind failures, distinguishable only by ``provided``."""
    with pytest.raises(InvalidParameterError) as empty_info:
        ScoringCriteria(value="")
    with pytest.raises(InvalidParameterError) as whitespace_info:
        ScoringCriteria(value="   ")

    assert type(empty_info.value) is type(whitespace_info.value)
    assert empty_info.value.context["kind"] == "invalid"
    assert whitespace_info.value.context["kind"] == "invalid"
    empty_provided = empty_info.value.context["provided"]
    whitespace_provided = whitespace_info.value.context["provided"]
    assert empty_provided != whitespace_provided


def test_preserves_criteria_with_whitespace_and_punctuation() -> None:
    """SC4: the reported criteria match the original text exactly."""
    rubric = "  Score for: (a) tone, (b) correctness -- no exceptions!  "

    criteria = ScoringCriteria(value=rubric)

    assert criteria.value == rubric


def test_accepts_multiline_rubric_and_preserves_full_text_when_inspected() -> None:
    """SC5: a multi-line rubric with dimensions and anchors is preserved fully."""
    rubric = (
        "Evaluate on two dimensions:\n"
        "1. Correctness -- does the answer match the reference?\n"
        "2. Tone -- is the response professional and concise?\n"
        "Example of a 5/5 response: concise, correct, and courteous.\n"
        "Example of a 1/5 response: incorrect and dismissive."
    )

    criteria = ScoringCriteria(value=rubric)

    assert criteria.value == rubric
    assert "\n" in criteria.value


def test_accepts_minimal_single_sentence_rubric_and_reports_it_when_inspected() -> None:
    """SC6: a brief single-sentence rubric is accepted and inspectable."""
    rubric = "Score how helpful the response is on a scale of 0 to 1."

    criteria = ScoringCriteria(value=rubric)

    assert criteria.value == rubric


def test_accepts_and_preserves_criteria_with_surrounding_whitespace() -> None:
    """SC7: surrounding whitespace is accepted and preserved, not trimmed."""
    padded_rubric = "  Evaluate for helpfulness and correctness.  "

    criteria = ScoringCriteria(value=padded_rubric)

    assert criteria.value == padded_rubric
    assert criteria.value != padded_rubric.strip()


@given(st.text(min_size=1).filter(lambda s: s.strip() != ""))
def test_preserves_any_non_blank_criteria_character_for_character(rubric: str) -> None:
    """Property: any string with non-whitespace content round-trips exactly."""
    criteria = ScoringCriteria(value=rubric)

    assert criteria.value == rubric
