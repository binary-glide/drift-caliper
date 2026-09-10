"""Step definitions for BIN-64: check whether the baseline has sufficient
observations.

Binds to
``tests/bdd/features/baseline/baseline-sufficiency-check.feature`` via
``tests/bdd/test_baseline_sufficiency_check.py``. Error assertions follow
ADR-002/ADR-008: type + required ``context`` keys only -- never message
text. See ``tests/unit/baseline/test_baseline_sufficiency.py``'s module
docstring for the two design decisions this story required (the
per-chart-type mechanism, and pinning ``DataQualityConcern.kind ==
"zero_variance"``) -- they apply identically here; not re-argued in this
file to avoid duplication.

Steps are kept thin (no business-rule assertions beyond what a single
Gherkin line states) -- the rigorous, mutation-resistant assertions
(exact sequence comparisons, the count/threshold/gap arithmetic property)
live in the unit test module instead, per ``test-patterns``' BDD guidance.
"""

from __future__ import annotations

from dataclasses import dataclass

from pytest_bdd import given, parsers, then, when

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, SufficiencyResult
from caliper.errors import CaliperError, InvalidParameterError
from caliper.measurement import ScoringResult
from tests.factories import ProvenanceFactory, ScoringResultFactory

# The only DataQualityConcern.kind this story introduces -- see
# test_baseline_sufficiency.py's module docstring for why this is pinned.
_ZERO_VARIANCE_CONCERN_KIND = "zero_variance"

_IDENTICAL_SCORE = 0.62

# Fixed chart type used throughout SC8 -- the scenario tests the mechanism
# (an explicit threshold tied to a chart type governs), not that any
# particular chart type's threshold differs from another's.
_CHART_TYPE_UNDER_TEST = "ewma"

_INVALID_THRESHOLD_VALUES = {"zero": 0, "a negative number": -1}


def _baseline_with_observations(count: int, *, score: float | None = None) -> Baseline:
    """Build a ``Baseline`` with ``count`` observations under shared provenance."""
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(count):
        if score is None:
            baseline.record(ScoringResultFactory(provenance=shared_provenance))
        else:
            baseline.record(
                ScoringResultFactory(provenance=shared_provenance, score=score)
            )
    return baseline


@dataclass
class SufficiencyCheck:
    """A sufficiency check's outcome, plus the baseline's pre-check snapshot.

    The snapshot exists only so SC9 (read-only inspection) can prove
    ``check_sufficiency()`` left the baseline exactly as it was -- every
    other scenario's Then steps use ``.result`` only.
    """

    baseline: Baseline
    result: SufficiencyResult
    observation_count_before: int
    observations_before: tuple[ScoringResult, ...]


@dataclass
class SufficiencyErrorCheck:
    """Outcome of an attempt to check sufficiency that is expected to fail."""

    baseline: Baseline
    error: CaliperError | None


def _check(
    baseline: Baseline,
    *,
    threshold: int | None = None,
    chart_type: str | None = None,
) -> SufficiencyCheck:
    """Call ``check_sufficiency`` on ``baseline``, capturing the pre-check snapshot."""
    observation_count_before = baseline.observation_count
    observations_before = tuple(baseline.observations)
    result = baseline.check_sufficiency(threshold=threshold, chart_type=chart_type)
    return SufficiencyCheck(
        baseline=baseline,
        result=result,
        observation_count_before=observation_count_before,
        observations_before=observations_before,
    )


# --- Scenario: baseline meets or exceeds the minimum (SC1) -------------------


@given(
    "the engineer has a Phase I baseline with observations meeting or exceeding "
    "the required minimum",
    target_fixture="baseline",
)
def a_baseline_meeting_or_exceeding_the_minimum() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 8)


@then("the result reports that no additional observations are needed")
def result_reports_no_additional_observations_needed(check: SufficiencyCheck) -> None:
    assert check.result.gap == 0


# --- Scenario: baseline has fewer than the minimum (SC2, reused by SC12) -----


@given(
    "the engineer has a Phase I baseline with fewer observations than the "
    "required minimum",
    target_fixture="baseline",
)
def a_baseline_with_fewer_observations_than_the_minimum() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 15)


@then("the result reports how many more observations are needed to reach the minimum")
def result_reports_the_gap(check: SufficiencyCheck) -> None:
    assert check.result.gap == check.result.threshold - check.result.observation_count


# --- Scenario: exactly the minimum (SC3) --------------------------------------


@given(
    "the engineer has a Phase I baseline with exactly the minimum required "
    "number of observations",
    target_fixture="baseline",
)
def a_baseline_with_exactly_the_minimum() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)


@then("the remaining observations needed is zero")
def remaining_observations_needed_is_zero(check: SufficiencyCheck) -> None:
    assert check.result.gap == 0


# --- Scenario: empty baseline (SC4) -------------------------------------------


@given(
    "the engineer has a Phase I baseline with no recorded observations",
    target_fixture="baseline",
)
def an_empty_baseline() -> Baseline:
    return Baseline()


@then("the result reports zero as the current observation count")
def result_reports_zero_observation_count(check: SufficiencyCheck) -> None:
    assert check.result.observation_count == 0


@then(
    "the result reports the full minimum threshold as the number of "
    "observations still needed"
)
def result_reports_full_threshold_as_gap(check: SufficiencyCheck) -> None:
    assert check.result.gap == check.result.threshold


# --- Shared When: check for fitting control limits (SC1,2,3,4,7,9,10,12) ----


@when(
    "they check whether the baseline is sufficient for fitting control limits",
    target_fixture="check",
)
def check_sufficiency_for_fitting(baseline: Baseline) -> SufficiencyCheck:
    return _check(baseline)


# --- Shared Then: count / threshold reporting (SC1, SC2) --------------------


@then("the result reports the baseline as sufficient")
def result_reports_sufficient(check: SufficiencyCheck) -> None:
    assert check.result.is_sufficient is True


@then("the result reports the baseline as insufficient")
def result_reports_insufficient(check: SufficiencyCheck) -> None:
    assert check.result.is_sufficient is False


@then("the result reports the current observation count")
def result_reports_current_observation_count(check: SufficiencyCheck) -> None:
    assert check.result.observation_count == check.baseline.observation_count


@then("the result reports the minimum threshold that was applied")
def result_reports_the_threshold_applied(check: SufficiencyCheck) -> None:
    assert check.result.threshold == DEFAULT_SUFFICIENCY_THRESHOLD


# --- Scenario: configurable threshold (SC5) -----------------------------------


@given(
    "the engineer has configured a specific minimum observation count for the "
    "sufficiency determination",
    target_fixture="custom_threshold",
)
def a_configured_custom_threshold() -> int:
    return DEFAULT_SUFFICIENCY_THRESHOLD // 2


@given("they have a Phase I baseline with observations", target_fixture="baseline")
def a_baseline_with_some_observations() -> Baseline:
    """Shared setup for SC5 and SC8 -- count is not tied to any specific threshold."""
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)


@when("they check whether the baseline is sufficient", target_fixture="check")
def check_sufficiency_with_custom_threshold(
    baseline: Baseline, custom_threshold: int
) -> SufficiencyCheck:
    return _check(baseline, threshold=custom_threshold)


@then(
    "the determination uses the engineer's configured minimum rather than the "
    "library default"
)
def determination_uses_configured_minimum(
    check: SufficiencyCheck, custom_threshold: int
) -> None:
    assert check.result.threshold == custom_threshold
    assert check.result.threshold != DEFAULT_SUFFICIENCY_THRESHOLD


@then("the result reports the configured minimum as the threshold that was applied")
def result_reports_configured_minimum(
    check: SufficiencyCheck, custom_threshold: int
) -> None:
    assert check.result.threshold == custom_threshold


# --- Scenario: temporal -- reflects recent recordings (SC6) ------------------


@dataclass
class PreviousCheck:
    baseline: Baseline
    first_result: SufficiencyResult


_ADDITIONAL_OBSERVATIONS_RECORDED = 4


@given(
    "the engineer has previously checked a baseline and it was insufficient",
    target_fixture="previous_check",
)
def a_previously_insufficient_baseline() -> PreviousCheck:
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 10)
    first_result = baseline.check_sufficiency()
    assert first_result.is_sufficient is False  # scenario precondition
    return PreviousCheck(baseline=baseline, first_result=first_result)


@given("they have since recorded additional observations into the baseline")
def additional_observations_are_recorded(previous_check: PreviousCheck) -> None:
    for _ in range(_ADDITIONAL_OBSERVATIONS_RECORDED):
        previous_check.baseline.record(
            ScoringResultFactory(
                provenance=previous_check.baseline.provenance_signature
            )
        )


@when("they check the baseline for sufficiency again", target_fixture="second_result")
def check_sufficiency_again(previous_check: PreviousCheck) -> SufficiencyResult:
    return previous_check.baseline.check_sufficiency()


@then("the result reports the updated observation count")
def result_reports_updated_count(
    second_result: SufficiencyResult, previous_check: PreviousCheck
) -> None:
    assert (
        second_result.observation_count
        == previous_check.first_result.observation_count
        + _ADDITIONAL_OBSERVATIONS_RECORDED
    )


@then("the number of remaining observations needed has decreased accordingly")
def gap_decreased_accordingly(
    second_result: SufficiencyResult, previous_check: PreviousCheck
) -> None:
    assert (
        second_result.gap
        == previous_check.first_result.gap - _ADDITIONAL_OBSERVATIONS_RECORDED
    )


# --- Scenario: zero variance flagged (SC7, reused by SC12) -------------------


@given(
    "the engineer has a Phase I baseline meeting the minimum observation count",
    target_fixture="baseline",
)
def a_baseline_meeting_the_minimum() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)


@given(
    "every observation in the baseline has an identical numeric score",
    target_fixture="baseline",
)
def every_observation_has_an_identical_score(baseline: Baseline) -> Baseline:
    """Rebuilds ``baseline`` at the same observation count, with one shared score.

    pytest-bdd matches Gherkin ``But``/``And`` against whichever decorator
    registered the same step text -- keyword type is not part of the match.
    """
    count = baseline.observation_count
    return _baseline_with_observations(count, score=_IDENTICAL_SCORE)


@then("the result reports that the observation count meets the minimum threshold")
def result_reports_count_meets_threshold(check: SufficiencyCheck) -> None:
    assert check.result.is_sufficient is True


@then(
    "the result indicates a data quality concern alongside the count-based "
    "determination"
)
def result_indicates_concern_alongside_determination(check: SufficiencyCheck) -> None:
    # `>= 1` would not catch a bogus second concern being added (OQ-1).
    assert len(check.result.data_quality_concerns) == 1


@then("the concern identifies that the scores show no variation")
def concern_identifies_zero_variation(check: SufficiencyCheck) -> None:
    # Exact set, not membership. `any(...)` passes even when the implementation
    # returns extra unexpected concerns alongside the real one -- which is the
    # SufficiencyResult scope creep OQ-1 exists to prevent.
    concerns = check.result.data_quality_concerns
    assert len(concerns) == 1
    assert concerns[0].kind == _ZERO_VARIANCE_CONCERN_KIND


# --- Scenario: per-chart-type threshold (SC8) ---------------------------------


@given(
    "the engineer has configured distinct minimum thresholds for different chart types",
    target_fixture="chart_type_thresholds",
)
def configured_distinct_chart_type_thresholds() -> dict[str, int]:
    return {
        "ewma": DEFAULT_SUFFICIENCY_THRESHOLD + 25,
        "shewhart": DEFAULT_SUFFICIENCY_THRESHOLD + 50,
    }


@when(
    "they check whether the baseline is sufficient for a specific chart type",
    target_fixture="check",
)
def check_sufficiency_for_a_specific_chart_type(
    baseline: Baseline, chart_type_thresholds: dict[str, int]
) -> SufficiencyCheck:
    threshold = chart_type_thresholds[_CHART_TYPE_UNDER_TEST]
    return _check(baseline, threshold=threshold, chart_type=_CHART_TYPE_UNDER_TEST)


@then("the result reports the threshold configured for that chart type")
def result_reports_the_chart_types_threshold(
    check: SufficiencyCheck, chart_type_thresholds: dict[str, int]
) -> None:
    assert check.result.threshold == chart_type_thresholds[_CHART_TYPE_UNDER_TEST]


@then(
    "the determination uses that chart type's threshold rather than the general default"
)
def determination_uses_the_chart_types_threshold(check: SufficiencyCheck) -> None:
    assert check.result.threshold != DEFAULT_SUFFICIENCY_THRESHOLD


# --- Scenario: read-only inspection (SC9) -------------------------------------


@given(
    "the engineer has a Phase I baseline with recorded observations",
    target_fixture="baseline",
)
def a_baseline_with_recorded_observations() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD // 3)


@then("the baseline contains the same number of observations as before the check")
def baseline_count_unchanged(check: SufficiencyCheck) -> None:
    assert check.baseline.observation_count == check.observation_count_before


@then("the observations in the baseline are unchanged")
def baseline_observations_unchanged(check: SufficiencyCheck) -> None:
    assert tuple(check.baseline.observations) == check.observations_before


# --- Scenario: one fewer than the minimum (SC10) ------------------------------


@given(
    "the engineer has a Phase I baseline with one fewer observation than the "
    "configured minimum",
    target_fixture="baseline",
)
def a_baseline_with_one_fewer_than_the_minimum() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 1)


@then("the result reports that exactly one more observation is needed")
def result_reports_exactly_one_more_observation_needed(check: SufficiencyCheck) -> None:
    assert check.result.gap == 1


# --- Scenario Outline: non-positive threshold (SC11) --------------------------


@given(
    parsers.parse(
        "the engineer has configured a minimum observation count that is "
        "{invalid_value}"
    ),
    target_fixture="invalid_threshold",
)
def a_configured_invalid_threshold(invalid_value: str) -> int:
    return _INVALID_THRESHOLD_VALUES[invalid_value]


@when(
    "they attempt to check whether the baseline is sufficient", target_fixture="attempt"
)
def attempt_check_sufficiency_with_invalid_threshold(
    invalid_threshold: int,
) -> SufficiencyErrorCheck:
    baseline = Baseline()
    try:
        baseline.check_sufficiency(threshold=invalid_threshold)
    except CaliperError as exc:
        return SufficiencyErrorCheck(baseline=baseline, error=exc)
    raise AssertionError(
        "expected check_sufficiency() to raise for a non-positive threshold"
    )


@then("the check fails with an error classifiable as an invalid parameter")
def check_fails_as_invalid_parameter(attempt: SufficiencyErrorCheck) -> None:
    assert isinstance(attempt.error, InvalidParameterError)
    assert attempt.error.category == "invalid_parameter"


@then("the error identifies which parameter is invalid and what the valid range is")
def error_identifies_parameter_and_range(attempt: SufficiencyErrorCheck) -> None:
    error = attempt.error
    assert isinstance(error, InvalidParameterError)
    assert isinstance(error.context["parameter"], str)
    assert error.context["parameter"] != ""
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Scenario: combined insufficient + zero variance (SC12) ------------------


@then("the result indicates a data quality concern")
def result_indicates_a_data_quality_concern(check: SufficiencyCheck) -> None:
    # `>= 1` would not catch a bogus second concern being added (OQ-1).
    assert len(check.result.data_quality_concerns) == 1
