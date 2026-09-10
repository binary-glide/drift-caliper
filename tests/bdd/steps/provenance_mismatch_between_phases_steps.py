"""Step definitions for BIN-68: compare a Phase II scoring result's

provenance against a fitted control limit artefact's provenance.

Binds to
``tests/bdd/features/baseline/provenance-mismatch-between-phases.feature``
via ``tests/bdd/test_provenance_mismatch_between_phases.py``. Error
assertions follow ADR-002/ADR-008, as amended 2026-09-10:
``ProvenanceMismatchError.context["mismatches"]`` (a ``dict[str, dict[str,
str]]`` keyed by dimension name) plus its ``.mismatches`` sugar property --
type and required context keys only, never message text.

``compare_provenance()`` does not exist yet -- importing it from
``caliper.baseline`` fails until ``domain-implementer`` adds it. That
``ImportError`` is the correct red state for this ticket (TDD red phase).

Fitted artefacts are obtained by calling ``fit_ewma``/``fit_cusum``/
``fit_shewhart`` on a sufficient, literal-provenance baseline -- never
constructed directly -- mirroring the convention
``tests/unit/baseline/test_compare_provenance.py`` and ``FittedEWMA``'s own
docstring establish.
"""

from __future__ import annotations

from dataclasses import dataclass

from pytest_bdd import given, then, when

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    compare_provenance,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.errors import CaliperError, ProvenanceMismatchError
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from tests.factories import ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."
_DIFFERENT_MODEL_VERSION = "claude-opus-4-5-20260101"
_DIFFERENT_CRITERIA = "Evaluate the response for tone and empathy."

# Arbitrary, sufficiently-large target ARL0 -- carries no statistical
# meaning here, matching the sibling fitting step/test files' own
# `_SHAPE_TEST_TARGET_ARL`.
_SHAPE_TEST_TARGET_ARL = 370.0


def _result(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
    score: float = 0.9,
    reasoning: str = "Accurate and concise.",
) -> ScoringResult:
    """Build a ``ScoringResult`` with an explicit, literal provenance."""
    return ScoringResult(
        score=score,
        reasoning=reasoning,
        provenance=Provenance(
            model_version=ModelVersion(value=model_version),
            scoring_criteria=ScoringCriteria(value=criteria),
        ),
    )


def _baseline_with_provenance(
    *, model_version: str, criteria: str, count: int
) -> Baseline:
    """Build a ``Baseline`` of ``count`` observations sharing one literal provenance."""
    baseline = Baseline()
    provenance = Provenance(
        model_version=ModelVersion(value=model_version),
        scoring_criteria=ScoringCriteria(value=criteria),
    )
    for _ in range(count):
        baseline.record(ScoringResultFactory(provenance=provenance))
    return baseline


def _fitted_ewma(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedEWMA:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _fitted_cusum(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedCUSUM:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _fitted_shewhart(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedShewhart:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


@dataclass
class ComparisonAttempt:
    """Outcome of one ``compare_provenance()`` call -- success or a captured error."""

    result: ScoringResult
    artefact: FittedControlLimits
    error: CaliperError | None


def _attempt_comparison(
    result: ScoringResult, artefact: FittedControlLimits
) -> ComparisonAttempt:
    """Call ``compare_provenance()``, capturing any ``CaliperError`` rather

    than raising.
    """
    try:
        compare_provenance(result, artefact)
    except CaliperError as exc:
        return ComparisonAttempt(result=result, artefact=artefact, error=exc)
    return ComparisonAttempt(result=result, artefact=artefact, error=None)


def _capture_comparison_error(
    result: ScoringResult, artefact: FittedControlLimits
) -> CaliperError:
    """Call ``compare_provenance()`` expecting it to raise, and return the

    raised error.
    """
    try:
        compare_provenance(result, artefact)
    except CaliperError as exc:
        return exc
    raise AssertionError("expected compare_provenance() to raise a CaliperError")


# --- Scenario: provenance matches (SC1) ---------------------------------------


@given(
    "the engineer has a fitted control limit artefact from a Phase I baseline",
    target_fixture="artefact",
)
def a_fitted_artefact_from_a_phase_i_baseline() -> FittedEWMA:
    """A fitted EWMA artefact -- the comparison is chart-type agnostic (BR-6)."""
    return _fitted_ewma()


@given(
    "they have a Phase II scoring result produced with the same judge model "
    "version and scoring criteria as the baseline",
    target_fixture="phase_ii_result",
)
def a_matching_phase_ii_scoring_result(
    artefact: FittedControlLimits,
) -> ScoringResult:
    """A scoring result whose provenance matches the fitted artefact's exactly."""
    return _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
    )


@when(
    "they compare the scoring result's provenance against the fitted "
    "artefact's provenance",
    target_fixture="comparison_attempt",
)
def compare_the_scoring_result_against_the_artefact(
    phase_ii_result: ScoringResult, artefact: FittedControlLimits
) -> ComparisonAttempt:
    """Attempt the comparison, capturing any raised error rather than propagating it."""
    return _attempt_comparison(phase_ii_result, artefact)


@then("the comparison confirms the provenances are compatible")
def the_comparison_confirms_compatibility(
    comparison_attempt: ComparisonAttempt,
) -> None:
    """No error was raised -- the provenances are compatible."""
    assert comparison_attempt.error is None


# --- Scenario: model version differs (SC2) ------------------------------------


@given(
    "the engineer has a fitted control limit artefact carrying a specific "
    "judge model version in its provenance",
    target_fixture="artefact",
)
def a_fitted_artefact_with_a_specific_model_version() -> FittedEWMA:
    return _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)


@given(
    "they have a Phase II scoring result produced by a different judge model version",
    target_fixture="phase_ii_result",
)
def a_phase_ii_result_with_a_different_model_version(
    artefact: FittedControlLimits,
) -> ScoringResult:
    return _result(
        model_version=_DIFFERENT_MODEL_VERSION, criteria=artefact.provenance_criteria
    )


@then(
    "the comparison fails with an error that is programmatically "
    "classifiable as a provenance mismatch"
)
def the_comparison_fails_as_a_provenance_mismatch(
    comparison_attempt: ComparisonAttempt,
) -> None:
    assert isinstance(comparison_attempt.error, ProvenanceMismatchError)
    assert comparison_attempt.error.category == "provenance_mismatch"


@then("the error identifies the differing dimension as model version")
def the_error_identifies_model_version_as_differing(
    comparison_attempt: ComparisonAttempt,
) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert "model_version" in error.mismatches


@then("the error identifies the fitted artefact's model version as the expected value")
def the_error_reports_the_artefacts_model_version_as_expected(
    comparison_attempt: ComparisonAttempt,
) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert (
        error.mismatches["model_version"]["expected"]
        == comparison_attempt.artefact.provenance_model_version
    )


@then("the error identifies the scoring result's model version as the received value")
def the_error_reports_the_results_model_version_as_received(
    comparison_attempt: ComparisonAttempt,
) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert (
        error.mismatches["model_version"]["received"]
        == comparison_attempt.result.provenance.model_version.value
    )


# --- Scenario: scoring criteria differs (SC3) ---------------------------------


@given(
    "the engineer has a fitted control limit artefact carrying specific "
    "scoring criteria in its provenance",
    target_fixture="artefact",
)
def a_fitted_artefact_with_specific_criteria() -> FittedEWMA:
    return _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)


@given(
    "they have a Phase II scoring result produced against different criteria",
    target_fixture="phase_ii_result",
)
def a_phase_ii_result_with_different_criteria(
    artefact: FittedControlLimits,
) -> ScoringResult:
    return _result(
        model_version=artefact.provenance_model_version, criteria=_DIFFERENT_CRITERIA
    )


@then("the error identifies the differing dimension as criteria")
def the_error_identifies_criteria_as_differing(
    comparison_attempt: ComparisonAttempt,
) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert "scoring_criteria" in error.mismatches


@then("the error identifies the fitted artefact's criteria as the expected value")
def the_error_reports_the_artefacts_criteria_as_expected(
    comparison_attempt: ComparisonAttempt,
) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert (
        error.mismatches["scoring_criteria"]["expected"]
        == comparison_attempt.artefact.provenance_criteria
    )


@then("the error identifies the scoring result's criteria as the received value")
def the_error_reports_the_results_criteria_as_received(
    comparison_attempt: ComparisonAttempt,
) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert (
        error.mismatches["scoring_criteria"]["received"]
        == comparison_attempt.result.provenance.scoring_criteria.value
    )


# --- Scenario: dual mismatch (SC4) --------------------------------------------


@given(
    "the engineer has a fitted control limit artefact with specific provenance",
    target_fixture="artefact",
)
def a_fitted_artefact_with_specific_provenance() -> FittedEWMA:
    return _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)


@given(
    "they have a Phase II scoring result where both the judge model version "
    "and the scoring criteria differ from the fitted artefact",
    target_fixture="phase_ii_result",
)
def a_phase_ii_result_where_both_dimensions_differ(
    artefact: FittedControlLimits,
) -> ScoringResult:
    del artefact  # not read -- both dimensions differ unconditionally
    return _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_DIFFERENT_CRITERIA)


@then("the error identifies that both provenance dimensions differ")
def the_error_identifies_both_dimensions(comparison_attempt: ComparisonAttempt) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert set(error.mismatches.keys()) == {"model_version", "scoring_criteria"}


@then("the error reports the expected and received values for each differing dimension")
def the_error_reports_expected_and_received_for_each_dimension(
    comparison_attempt: ComparisonAttempt,
) -> None:
    error = comparison_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    for values in error.mismatches.values():
        assert set(values.keys()) == {"expected", "received"}


# --- Scenario: chart-type independence (SC5) ----------------------------------


@given(
    "the engineer has fitted artefacts from different chart types, each "
    "carrying the same baseline provenance",
    target_fixture="artefacts",
)
def fitted_artefacts_from_different_chart_types() -> list[FittedControlLimits]:
    return [
        _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA),
        _fitted_cusum(model_version=_MODEL_VERSION, criteria=_CRITERIA),
        _fitted_shewhart(model_version=_MODEL_VERSION, criteria=_CRITERIA),
    ]


@given(
    "they have a Phase II scoring result with a different judge model version",
    target_fixture="phase_ii_result",
)
def a_phase_ii_result_with_only_a_different_model_version(
    artefacts: list[FittedControlLimits],
) -> ScoringResult:
    return _result(
        model_version=_DIFFERENT_MODEL_VERSION,
        criteria=artefacts[0].provenance_criteria,
    )


@when(
    "they compare the scoring result against any of the fitted artefacts",
    target_fixture="comparison_attempts",
)
def compare_the_result_against_each_artefact(
    phase_ii_result: ScoringResult, artefacts: list[FittedControlLimits]
) -> list[ComparisonAttempt]:
    return [_attempt_comparison(phase_ii_result, artefact) for artefact in artefacts]


@then(
    "each comparison fails with an error that is programmatically "
    "classifiable as a provenance mismatch"
)
def each_comparison_fails_as_a_provenance_mismatch(
    comparison_attempts: list[ComparisonAttempt],
) -> None:
    for attempt in comparison_attempts:
        assert isinstance(attempt.error, ProvenanceMismatchError)
        assert attempt.error.category == "provenance_mismatch"


@then("the structured context follows the same shape for all chart types")
def the_structured_context_has_the_same_shape_across_chart_types(
    comparison_attempts: list[ComparisonAttempt],
) -> None:
    errors = [attempt.error for attempt in comparison_attempts]
    assert all(isinstance(error, ProvenanceMismatchError) for error in errors)
    provenance_errors = [
        error for error in errors if isinstance(error, ProvenanceMismatchError)
    ]
    context_key_sets = {frozenset(error.context.keys()) for error in provenance_errors}
    mismatch_key_sets = {
        frozenset(error.mismatches.keys()) for error in provenance_errors
    }
    assert len(context_key_sets) == 1
    assert len(mismatch_key_sets) == 1


# --- Scenario: category consistency with Phase I (SC6) -----------------------


@given(
    "the engineer has encountered a provenance mismatch error from recording "
    "an observation with inconsistent provenance into a Phase I baseline",
    target_fixture="phase_i_error",
)
def a_phase_i_provenance_mismatch_error() -> ProvenanceMismatchError:
    baseline = Baseline()
    baseline.record(_result(model_version=_MODEL_VERSION, criteria=_CRITERIA))
    try:
        baseline.record(
            _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)
        )
    except ProvenanceMismatchError as exc:
        return exc
    raise AssertionError(
        "expected Baseline.record() to raise a ProvenanceMismatchError"
    )


@given(
    "they have encountered a provenance mismatch error from comparing a "
    "Phase II scoring result against a fitted artefact",
    target_fixture="phase_ii_error",
)
def a_phase_ii_provenance_mismatch_error() -> ProvenanceMismatchError:
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    error = _capture_comparison_error(
        _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA), artefact
    )
    assert isinstance(error, ProvenanceMismatchError)
    return error


@when("they compare the two errors programmatically")
def compare_the_two_errors_programmatically() -> None:
    """No-op: both errors were already produced while building the Given

    fixtures above. The Then steps below read `phase_i_error`/
    `phase_ii_error` directly -- there is no further action to take here.
    """


@then("both are classifiable as the same provenance mismatch category")
def both_errors_share_the_same_category(
    phase_i_error: ProvenanceMismatchError, phase_ii_error: ProvenanceMismatchError
) -> None:
    assert phase_i_error.category == phase_ii_error.category == "provenance_mismatch"


@then("both carry structured context with the same required fields")
def both_errors_carry_the_same_required_context_fields(
    phase_i_error: ProvenanceMismatchError, phase_ii_error: ProvenanceMismatchError
) -> None:
    assert (
        set(phase_i_error.context.keys())
        == set(phase_ii_error.context.keys())
        == {"mismatches"}
    )
