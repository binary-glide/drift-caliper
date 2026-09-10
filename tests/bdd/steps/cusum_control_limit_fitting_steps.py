"""Step definitions for BIN-94: fit CUSUM control limits from the baseline.

Binds to
``tests/bdd/features/baseline/cusum-control-limit-fitting.feature`` via
``tests/bdd/test_cusum_control_limit_fitting.py``. Error assertions follow
ADR-002/ADR-008: type + required ``context`` keys only -- never message
text. See ``tests/unit/baseline/test_cusum_fitting.py``'s module docstring
for the design decisions this story required (pinning
``DegenerateBaselineError.context["reason"]``, pinning
``InvalidParameterError.context["parameter"]`` to the exact Python
parameter name, and why OQ-3 is deliberately left untested as a
mechanism) -- they apply identically here, mirroring
``tests/bdd/steps/ewma_control_limit_fitting_steps.py``; not re-argued in
this file to avoid duplication.

Steps are kept thin (no business-rule assertions beyond what a single
Gherkin line states) -- the rigorous, mutation-resistant assertions (exact
sets, the boundary property, the published-ARL numeric proof) live in
``tests/unit/baseline/test_cusum_fitting.py`` and
``tests/unit/baseline/test_cusum_arl_published_values.py`` instead, per
``test-patterns``' BDD guidance.

No numeric literal in this file is a claim about statistical correctness --
every concrete value below is an arbitrary valid input chosen only to
exercise a scenario, exactly as the feature file itself names none.
"""

from __future__ import annotations

from dataclasses import dataclass

from pytest_bdd import given, parsers, then, when

from caliper.baseline import (
    DEFAULT_REFERENCE_VALUE,
    DEFAULT_SUFFICIENCY_THRESHOLD,
    MAX_MEANINGFUL_ARL,
    MAX_REFERENCE_VALUE,
    MIN_MEANINGFUL_ARL,
    MIN_REFERENCE_VALUE,
    Baseline,
    FittedCUSUM,
    fit_cusum,
)
from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary valid inputs used whenever a scenario's own Given/When text does
# not itself parametrise the value under test -- see the module docstring.
_VALID_TARGET_ARL = 370.0
_VALID_REFERENCE_VALUE = 0.4
_CUSTOM_REFERENCE_VALUE = 0.8  # distinct from DEFAULT_REFERENCE_VALUE, on purpose

_IDENTICAL_SCORE = 0.62
_ZERO_VARIANCE_REASON = "zero_variance"

# An arbitrary string outside the direction parameter's valid set
# (ADR-004 section 6: "two_sided", "lower", "upper") -- not a plausible
# near-miss of any valid member.
_INVALID_DIRECTION = "sideways"

_INVALID_REFERENCE_VALUE_VALUES = {
    "zero": 0.0,
    "negative": -0.1,
    "above the valid upper bound": MAX_REFERENCE_VALUE * 2,
}
_INVALID_TARGET_ARL_VALUES = {
    "zero": 0.0,
    "negative": -10.0,
    "outside the meaningful range": MAX_MEANINGFUL_ARL * 2,
}
_REFERENCE_VALUE_BOUNDARIES = {
    "the smallest valid value": MIN_REFERENCE_VALUE,
    "the largest valid value": MAX_REFERENCE_VALUE,
}
_TARGET_ARL_BOUNDARIES = {
    "the smallest meaningful value": MIN_MEANINGFUL_ARL,
    "the largest meaningful value": MAX_MEANINGFUL_ARL,
}


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
class FittingOutcome:
    """A successful ``fit_cusum()`` call, with the baseline it was fitted from."""

    baseline: Baseline
    result: FittedCUSUM


@dataclass
class FittingAttempt:
    """The outcome of a ``fit_cusum()`` call expected to fail."""

    baseline: Baseline
    error: CaliperError


@dataclass
class MutationAttempt:
    """Every attempted post-creation mutation of a fitted artefact.

    Also records whether every one of them was rejected.
    """

    outcome: FittingOutcome
    snapshot: dict[str, object]
    raised_for_every_attempt: bool


def _capture_fitting_error(
    baseline: Baseline,
    *,
    target_arl: float | None,
    reference_value: float | None = None,
    direction: str | None = None,
) -> FittingAttempt:
    try:
        fit_cusum(
            baseline,
            target_arl=target_arl,
            reference_value=reference_value,
            direction=direction,
        )
    except CaliperError as exc:
        return FittingAttempt(baseline=baseline, error=exc)
    raise AssertionError("expected fit_cusum() to raise for this scenario")


# --- Given: a baseline that passes the sufficiency check, with variance ------------


@given(
    "the engineer has a Phase I baseline that passes the sufficiency check",
    target_fixture="baseline",
)
def a_baseline_passing_the_sufficiency_check() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)


@given("the baseline scores show non-zero variance")
def baseline_scores_show_non_zero_variance(baseline: Baseline) -> None:
    # ScoringResultFactory's default gives each observation an independently
    # varying score, so the baseline built above already has non-zero
    # variance. Nothing further to do; this step exists so the scenario's
    # Gherkin line has a bound implementation.
    del baseline


# --- Given: a baseline that does NOT pass the sufficiency check --------------------


@given(
    "the engineer has a Phase I baseline that does not pass the sufficiency check",
    target_fixture="baseline",
)
def a_baseline_not_passing_the_sufficiency_check() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 10)


# --- Given: a baseline meeting the count threshold, then rebuilt as zero-variance ---


@given(
    "the engineer has a Phase I baseline that passes the sufficiency count threshold",
    target_fixture="baseline",
)
def a_baseline_passing_the_sufficiency_count_threshold() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)


@given(
    "every observation in the baseline has an identical numeric score",
    target_fixture="baseline",
)
def every_observation_has_an_identical_score(baseline: Baseline) -> Baseline:
    """Rebuild ``baseline`` at the same observation count, with one shared score.

    pytest-bdd matches Gherkin ``But``/``And`` against whichever decorator
    registered the same step text -- keyword type is not part of the match.
    """
    count = baseline.observation_count
    return _baseline_with_observations(count, score=_IDENTICAL_SCORE)


# --- Given: a baseline already fitted (auditability, immutability) -----------------


@given(
    "the engineer has fitted CUSUM control limits from a Phase I baseline",
    target_fixture="outcome",
)
def a_baseline_already_fitted() -> FittingOutcome:
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    result = fit_cusum(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        reference_value=_VALID_REFERENCE_VALUE,
    )
    return FittingOutcome(baseline=baseline, result=result)


# --- When: fit with a specified tolerance (SC1) -------------------------------------


@when(
    "they fit CUSUM control limits with a specified false alarm tolerance",
    target_fixture="outcome",
)
def fit_with_specified_tolerance(baseline: Baseline) -> FittingOutcome:
    result = fit_cusum(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        reference_value=_VALID_REFERENCE_VALUE,
    )
    return FittingOutcome(baseline=baseline, result=result)


# --- When: inspect the already-fitted artefact (auditability) ----------------------


@when("they inspect the fitted artefact", target_fixture="outcome")
def inspect_the_fitted_artefact(outcome: FittingOutcome) -> FittingOutcome:
    return outcome


# --- When: fit with a custom reference value ------------------------------------


@when(
    "they fit CUSUM control limits with a specified false alarm tolerance and a "
    "custom reference value",
    target_fixture="outcome",
)
def fit_with_custom_reference_value(baseline: Baseline) -> FittingOutcome:
    result = fit_cusum(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        reference_value=_CUSTOM_REFERENCE_VALUE,
    )
    return FittingOutcome(baseline=baseline, result=result)


# --- When: fit without specifying a reference value -----------------------------


@when(
    "they fit CUSUM control limits with a specified false alarm tolerance without "
    "specifying a reference value",
    target_fixture="outcome",
)
def fit_without_reference_value(baseline: Baseline) -> FittingOutcome:
    result = fit_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


# --- When: attempt to fit (reused by SC5 insufficient and SC6 degenerate) ----------


@when("they attempt to fit CUSUM control limits", target_fixture="attempt")
def attempt_to_fit(baseline: Baseline) -> FittingAttempt:
    return _capture_fitting_error(baseline, target_arl=_VALID_TARGET_ARL)


# --- When: attempt to fit with an invalid reference value ----------------------


@when(
    parsers.parse(
        "they attempt to fit CUSUM control limits with a reference value that "
        "is {invalid_case}"
    ),
    target_fixture="attempt",
)
def attempt_to_fit_with_invalid_reference_value(
    baseline: Baseline, invalid_case: str
) -> FittingAttempt:
    invalid_value = _INVALID_REFERENCE_VALUE_VALUES[invalid_case]
    return _capture_fitting_error(
        baseline, target_arl=_VALID_TARGET_ARL, reference_value=invalid_value
    )


# --- When: attempt to fit with an invalid false alarm tolerance --------------------


@when(
    parsers.parse(
        "they attempt to fit CUSUM control limits with a false alarm tolerance "
        "that is {invalid_case}"
    ),
    target_fixture="attempt",
)
def attempt_to_fit_with_invalid_target_arl(
    baseline: Baseline, invalid_case: str
) -> FittingAttempt:
    invalid_value = _INVALID_TARGET_ARL_VALUES[invalid_case]
    return _capture_fitting_error(baseline, target_arl=invalid_value)


# --- When: attempt to fit without a false alarm tolerance ---------------------------


@when(
    "they attempt to fit CUSUM control limits without specifying a false alarm "
    "tolerance",
    target_fixture="attempt",
)
def attempt_to_fit_without_target_arl(baseline: Baseline) -> FittingAttempt:
    return _capture_fitting_error(baseline, target_arl=None)


# --- When: attempt to fit with an unrecognised direction ----------------------------


@when(
    "they attempt to fit CUSUM control limits with a direction specification "
    "that is not recognised",
    target_fixture="attempt",
)
def attempt_to_fit_with_unrecognised_direction(baseline: Baseline) -> FittingAttempt:
    return _capture_fitting_error(
        baseline, target_arl=_VALID_TARGET_ARL, direction=_INVALID_DIRECTION
    )


# --- Given: three failed fitting attempts, one per category (SC: distinguishability)


@given(
    "a fitting attempt has failed with an insufficient baseline error",
    target_fixture="errors",
)
def an_insufficient_baseline_error() -> dict[str, CaliperError]:
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 1)
    attempt = _capture_fitting_error(baseline, target_arl=_VALID_TARGET_ARL)
    return {"insufficient_baseline": attempt.error}


@given("a separate fitting attempt has failed with a degenerate baseline error")
def a_degenerate_baseline_error(errors: dict[str, CaliperError]) -> None:
    baseline = _baseline_with_observations(
        DEFAULT_SUFFICIENCY_THRESHOLD, score=_IDENTICAL_SCORE
    )
    attempt = _capture_fitting_error(baseline, target_arl=_VALID_TARGET_ARL)
    errors["degenerate_baseline"] = attempt.error


@given("a third fitting attempt has failed with an invalid parameter error")
def a_third_invalid_parameter_error(errors: dict[str, CaliperError]) -> None:
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD)
    attempt = _capture_fitting_error(baseline, target_arl=0.0)
    errors["invalid_parameter"] = attempt.error


@when("the engineer compares the three errors", target_fixture="errors")
def the_engineer_compares_the_three_errors(
    errors: dict[str, CaliperError],
) -> dict[str, CaliperError]:
    return errors


# --- When: attempt to mutate the fitted artefact (immutability) --------------------


@when(
    "they attempt to modify the limits, parameters, baseline statistics, or "
    "provenance of the fitted artefact",
    target_fixture="mutation",
)
def attempt_to_mutate_the_fitted_artefact(outcome: FittingOutcome) -> MutationAttempt:
    result = outcome.result
    snapshot: dict[str, object] = {
        "decision_interval": result.decision_interval,
        "reference_value": result.reference_value,
        "baseline_mean": result.baseline_mean,
        "provenance_model_version": result.provenance_model_version,
    }
    attempted_mutations: list[tuple[str, object]] = [
        ("decision_interval", result.decision_interval + 1.0),
        ("reference_value", result.reference_value + 0.01),
        ("baseline_mean", result.baseline_mean + 1.0),
        ("provenance_model_version", "tampered"),
    ]
    raised_every_time = True
    for attribute, replacement in attempted_mutations:
        try:
            setattr(result, attribute, replacement)
            raised_every_time = False
        except Exception:  # any raise here means the attempt was correctly rejected
            pass
    return MutationAttempt(
        outcome=outcome, snapshot=snapshot, raised_for_every_attempt=raised_every_time
    )


# --- When: fit with a reference value at a named boundary ----------------------


@when(
    parsers.parse(
        "they fit CUSUM control limits with a specified false alarm tolerance and "
        "a reference value at {boundary}"
    ),
    target_fixture="outcome",
)
def fit_with_reference_value_at_boundary(
    baseline: Baseline, boundary: str
) -> FittingOutcome:
    boundary_value = _REFERENCE_VALUE_BOUNDARIES[boundary]
    result = fit_cusum(
        baseline, target_arl=_VALID_TARGET_ARL, reference_value=boundary_value
    )
    return FittingOutcome(baseline=baseline, result=result)


# --- When: fit with a false alarm tolerance at a named boundary --------------------


@when(
    parsers.parse(
        "they fit CUSUM control limits with a false alarm tolerance at {boundary}"
    ),
    target_fixture="outcome",
)
def fit_with_target_arl_at_boundary(
    baseline: Baseline, boundary: str
) -> FittingOutcome:
    boundary_value = _TARGET_ARL_BOUNDARIES[boundary]
    result = fit_cusum(baseline, target_arl=boundary_value)
    return FittingOutcome(baseline=baseline, result=result)


# --- Then: core fitting result shape (SC1, boundary outlines) ----------------------


@then("the result contains the decision interval and target value for CUSUM monitoring")
def result_contains_decision_interval_and_target_value(outcome: FittingOutcome) -> None:
    result = outcome.result
    assert isinstance(result.decision_interval, float)
    assert isinstance(result.target_value, float)


@then("the result reports the reference value that was used")
def result_reports_the_reference_value(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.reference_value, float)


@then("the result reports which direction or directions of drift are monitored")
def result_reports_the_direction(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.direction, str)
    assert outcome.result.direction != ""


@then("the result reports the false alarm tolerance that was requested")
def result_reports_the_requested_tolerance(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.requested_arl, float)


@then(
    "the result reports the false alarm tolerance that was achieved by the calibration"
)
def result_reports_the_achieved_tolerance(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.achieved_arl, float)


@then("the result reports the calibration method that was used")
def result_reports_the_calibration_method(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.calibration_method, str)
    assert outcome.result.calibration_method != ""


# --- Then: auditability -------------------------------------------------------------


@then("the artefact reports the baseline mean and variance used to compute the limits")
def artefact_reports_baseline_mean_and_variance(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.baseline_mean, float)
    assert isinstance(outcome.result.baseline_spread, float)


@then(
    "the artefact reports the number of baseline observations the limits were "
    "fitted from"
)
def artefact_reports_observation_count(outcome: FittingOutcome) -> None:
    assert outcome.result.observation_count == outcome.baseline.observation_count


@then("the artefact reports the judge model version from the baseline provenance")
def artefact_reports_model_version(outcome: FittingOutcome) -> None:
    signature = outcome.baseline.provenance_signature
    assert signature is not None
    assert outcome.result.provenance_model_version == signature.model_version.value


@then("the artefact reports the scoring criteria from the baseline provenance")
def artefact_reports_scoring_criteria(outcome: FittingOutcome) -> None:
    signature = outcome.baseline.provenance_signature
    assert signature is not None
    assert outcome.result.provenance_criteria == signature.scoring_criteria.value


# --- Then: custom vs. default reference value -----------------------------------


@then(
    "the result uses the engineer's specified reference value rather than the "
    "library default"
)
def result_uses_the_custom_reference_value(outcome: FittingOutcome) -> None:
    assert outcome.result.reference_value == _CUSTOM_REFERENCE_VALUE
    assert outcome.result.reference_value != DEFAULT_REFERENCE_VALUE


@then("the result uses the library's default reference value")
def result_uses_the_default_reference_value(outcome: FittingOutcome) -> None:
    assert outcome.result.reference_value == DEFAULT_REFERENCE_VALUE


@then("the result reports which reference value was used")
def result_reports_which_reference_value(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.reference_value, float)


# --- Then: decision interval derived, not specified (SC: A5) -----------------------


@then("the result reports the decision interval that was derived by the calibration")
def result_reports_the_derived_decision_interval(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.decision_interval, float)


@then("the engineer did not need to specify the decision interval directly")
def engineer_did_not_specify_decision_interval_directly(
    outcome: FittingOutcome,
) -> None:
    # The proof is structural, not behavioural: fit_cusum()'s signature
    # (ADR-004 section 5) has no decision_interval parameter at all -- the
    # outcome above was reached without one, which is the only way it could
    # have been reached.
    assert isinstance(outcome.result.decision_interval, float)


# --- Then: insufficient baseline (SC5) ----------------------------------------------


@then("the fitting fails with an error classifiable as an insufficient baseline")
def fitting_fails_as_insufficient_baseline(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error, InsufficientBaselineError)
    assert attempt.error.category == "insufficient_baseline"


@then(
    "the error reports how many observations the baseline has and how many are needed"
)
def error_reports_have_and_need(attempt: FittingAttempt) -> None:
    assert attempt.error.context["have"] == attempt.baseline.observation_count
    assert isinstance(attempt.error.context["need"], int)
    assert attempt.error.context["need"] > attempt.error.context["have"]


@then("the error carries recovery guidance to collect more observations before fitting")
def error_carries_recovery_guidance_for_insufficiency(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error.recovery_hint, str)
    assert attempt.error.recovery_hint != ""


# --- Then: degenerate baseline (SC6) ------------------------------------------------


@then("the fitting fails with an error classifiable as a degenerate baseline")
def fitting_fails_as_degenerate_baseline(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error, DegenerateBaselineError)
    assert attempt.error.category == "degenerate_baseline"


@then(
    "the error explains that CUSUM control limits require score variation in the "
    "baseline"
)
def error_explains_score_variation_required(attempt: FittingAttempt) -> None:
    assert attempt.error.context["reason"] == _ZERO_VARIANCE_REASON


@then("the error carries recovery guidance for addressing the zero-variance condition")
def error_carries_recovery_guidance_for_zero_variance(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error.recovery_hint, str)
    assert attempt.error.recovery_hint != ""


# --- Then: invalid parameter (reference value / target_arl outlines, missing) ------


@then("the fitting fails with an error classifiable as an invalid parameter")
def fitting_fails_as_invalid_parameter(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error, InvalidParameterError)
    assert attempt.error.category == "invalid_parameter"


@then("the error identifies which parameter is invalid and what the valid range is")
def error_identifies_invalid_reference_value(attempt: FittingAttempt) -> None:
    error = attempt.error
    assert isinstance(error, InvalidParameterError)
    assert error.context["parameter"] == "reference_value"
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


@then(
    "the error identifies what was invalid about the false alarm tolerance and "
    "what values are acceptable"
)
def error_identifies_invalid_target_arl(attempt: FittingAttempt) -> None:
    error = attempt.error
    assert isinstance(error, InvalidParameterError)
    assert error.context["parameter"] == "target_arl"
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


@then("the error identifies that a false alarm tolerance parameter is required")
def error_identifies_target_arl_required(attempt: FittingAttempt) -> None:
    error = attempt.error
    assert isinstance(error, InvalidParameterError)
    assert error.context["kind"] == "missing"
    assert error.context["parameter"] == "target_arl"


@then("no control limits are produced")
def no_control_limits_are_produced(attempt: FittingAttempt) -> None:
    # The raise itself is the proof -- no FittedCUSUM exists in this branch.
    assert attempt.error is not None


@then("the error identifies that the direction parameter is unrecognised")
def error_identifies_direction_unrecognised(attempt: FittingAttempt) -> None:
    error = attempt.error
    assert isinstance(error, InvalidParameterError)
    assert error.context["kind"] == "invalid"
    assert error.context["parameter"] == "direction"


# --- Then: error distinguishability --------------------------------------------------


@then(
    "each is classifiable under a different category without inspecting the "
    "error message text"
)
def each_error_has_a_distinct_category(errors: dict[str, CaliperError]) -> None:
    categories = {error.category for error in errors.values()}
    assert categories == {
        "insufficient_baseline",
        "degenerate_baseline",
        "invalid_parameter",
    }


@then("the recovery guidance for each category is distinct from the others")
def recovery_guidance_is_distinct_per_category(errors: dict[str, CaliperError]) -> None:
    hints = {error.recovery_hint for error in errors.values()}
    assert len(hints) == 3


# --- Then: immutability ---------------------------------------------------------------


@then("the modification is rejected")
def the_modification_is_rejected(mutation: MutationAttempt) -> None:
    assert mutation.raised_for_every_attempt is True


@then("the artefact continues to report its original values")
def the_artefact_reports_its_original_values(mutation: MutationAttempt) -> None:
    result = mutation.outcome.result
    assert result.decision_interval == mutation.snapshot["decision_interval"]
    assert result.reference_value == mutation.snapshot["reference_value"]
    assert result.baseline_mean == mutation.snapshot["baseline_mean"]
    assert (
        result.provenance_model_version == mutation.snapshot["provenance_model_version"]
    )
