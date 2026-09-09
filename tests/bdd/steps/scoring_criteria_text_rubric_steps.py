"""Step definitions for BIN-58: scoring criteria as a text rubric.

Binds to
``tests/bdd/features/measurement/scoring-criteria-text-rubric.feature`` via
``tests/bdd/test_scoring_criteria_text_rubric.py``. Error assertions follow
ADR-002: type + required ``context`` keys only -- never message text.

OQ-3 (criteria attachment point) is open. These steps exercise
``ScoringCriteria`` directly -- "configuring" criteria means constructing a
``ScoringCriteria``, with no wiring to ``Judge`` or any other attachment
point.
"""

from __future__ import annotations

from dataclasses import dataclass

from pytest_bdd import given, then, when

from caliper.errors import CaliperError, InvalidParameterError
from caliper.measurement import ScoringCriteria


@dataclass
class ConfigurationAttempt:
    """Outcome of an attempted scoring criteria configuration."""

    criteria: ScoringCriteria | None
    error: CaliperError | None


# --- Scenario: happy path ---------------------------------------------------


@given(
    "the engineer has a text rubric describing what to evaluate",
    target_fixture="rubric_input",
)
def a_text_rubric() -> str:
    """A realistic, valid text rubric."""
    return "Evaluate the response for factual accuracy and helpfulness."


@when(
    "they configure scoring criteria with that rubric",
    target_fixture="configured_criteria",
)
def configure_criteria_with_rubric(rubric_input: str) -> ScoringCriteria:
    """Configure scoring criteria with the given rubric."""
    return ScoringCriteria(value=rubric_input)


@then("the criteria should be accepted")
def criteria_should_be_accepted(configured_criteria: ScoringCriteria) -> None:
    """The configuration call returned a ScoringCriteria instance."""
    assert isinstance(configured_criteria, ScoringCriteria)


@then("the engineer should be able to inspect the configured criteria")
def engineer_can_inspect_configured_criteria(
    configured_criteria: ScoringCriteria, rubric_input: str
) -> None:
    """The configured criteria match what was specified."""
    assert configured_criteria.value == rubric_input


# --- Scenarios: empty / whitespace-only criteria ----------------------------


@given(
    "the engineer provides an empty string as criteria",
    target_fixture="rubric_input",
)
def empty_string_criteria() -> str:
    """An empty string, which carries no anchoring guarantee."""
    return ""


@given(
    "the engineer provides a string containing only whitespace as criteria",
    target_fixture="rubric_input",
)
def whitespace_only_criteria() -> str:
    """A whitespace-only string, which carries no anchoring guarantee."""
    return "   \t  "


@when(
    "they attempt to configure scoring criteria",
    target_fixture="configuration_attempt",
)
def attempt_configure_criteria(rubric_input: str) -> ConfigurationAttempt:
    """Attempt to configure criteria, capturing success or a Caliper error."""
    try:
        criteria = ScoringCriteria(value=rubric_input)
    except CaliperError as exc:
        return ConfigurationAttempt(criteria=None, error=exc)
    return ConfigurationAttempt(criteria=criteria, error=None)


@then("the configuration fails with an error classifiable as an invalid parameter")
def configuration_fails_as_invalid_parameter(
    configuration_attempt: ConfigurationAttempt,
) -> None:
    """No criteria were configured; the error is classifiable as invalid_parameter."""
    assert configuration_attempt.criteria is None
    assert isinstance(configuration_attempt.error, InvalidParameterError)
    assert configuration_attempt.error.category == "invalid_parameter"


@then("the error identifies that non-empty criteria are required")
def error_identifies_non_empty_criteria_required(
    configuration_attempt: ConfigurationAttempt,
) -> None:
    """The error's context names the invalid scoring_criteria parameter."""
    error = configuration_attempt.error
    assert isinstance(error, InvalidParameterError)
    assert error.context["parameter"] == "scoring_criteria"
    assert error.context["kind"] == "invalid"
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Scenario: preservation --------------------------------------------------


@given(
    "the engineer has configured scoring criteria with specific text "
    "including whitespace and punctuation",
    target_fixture="criteria_and_original",
)
def configure_criteria_with_whitespace_and_punctuation() -> tuple[ScoringCriteria, str]:
    """Configure criteria with text including whitespace and punctuation."""
    raw_rubric = "  Score for: (a) tone, (b) correctness -- no exceptions!  "
    return ScoringCriteria(value=raw_rubric), raw_rubric


@when(
    "they inspect the configured criteria",
    target_fixture="inspected_criteria",
)
def inspect_configured_criteria(
    criteria_and_original: tuple[ScoringCriteria, str],
) -> str:
    """Read back the configured criteria."""
    criteria, _ = criteria_and_original
    return criteria.value


@then(
    "the reported criteria should match the text they originally provided "
    "character for character"
)
def reported_criteria_matches_original(
    inspected_criteria: str,
    criteria_and_original: tuple[ScoringCriteria, str],
) -> None:
    """The reported criteria are byte-for-byte identical to the original."""
    _, raw_rubric = criteria_and_original
    assert inspected_criteria == raw_rubric


# --- Scenario: multi-line rubric ---------------------------------------------


@given(
    "the engineer has a multi-line rubric including dimensions and example anchors",
    target_fixture="rubric_input",
)
def a_multiline_rubric() -> str:
    """A multi-line rubric with dimensions and example anchors."""
    return (
        "Evaluate on two dimensions:\n"
        "1. Correctness -- does the answer match the reference?\n"
        "2. Tone -- is the response professional and concise?\n"
        "Example of a 5/5 response: concise, correct, and courteous.\n"
        "Example of a 1/5 response: incorrect and dismissive."
    )


@then("the full multi-line text should be preserved when inspected")
def full_multiline_text_preserved(
    configured_criteria: ScoringCriteria, rubric_input: str
) -> None:
    """The multi-line rubric, including newlines, is preserved exactly."""
    assert configured_criteria.value == rubric_input
    assert "\n" in configured_criteria.value


# --- Scenario: minimal single-sentence rubric --------------------------------


@given(
    "the engineer has a brief single-sentence rubric",
    target_fixture="rubric_input",
)
def a_brief_single_sentence_rubric() -> str:
    """A brief, single-sentence rubric."""
    return "Score how helpful the response is on a scale of 0 to 1."


# --- Scenario: surrounding whitespace ----------------------------------------


@given(
    "the engineer provides criteria with leading and trailing spaces "
    "around meaningful text",
    target_fixture="rubric_input",
)
def criteria_with_surrounding_whitespace() -> str:
    """Criteria padded with leading and trailing spaces."""
    return "  Evaluate for helpfulness and correctness.  "


@when(
    "they configure scoring criteria with that text",
    target_fixture="configured_criteria",
)
def configure_criteria_with_text(rubric_input: str) -> ScoringCriteria:
    """Configure scoring criteria with the given (possibly padded) text."""
    return ScoringCriteria(value=rubric_input)


@then("the reported criteria should include the surrounding spaces exactly as provided")
def reported_criteria_includes_surrounding_spaces(
    configured_criteria: ScoringCriteria, rubric_input: str
) -> None:
    """Surrounding whitespace is preserved, not trimmed."""
    assert configured_criteria.value == rubric_input
    assert configured_criteria.value != rubric_input.strip()
