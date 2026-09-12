"""Step definitions for BIN-95: fit Shewhart I-chart control limits from the baseline.

Binds to
``tests/bdd/features/baseline/shewhart-control-limit-fitting.feature`` via
``tests/bdd/test_shewhart_control_limit_fitting.py``. Error assertions
follow ADR-002/ADR-008: type + required ``context`` keys only -- never
message text. See ``tests/unit/baseline/test_shewhart_fitting.py``'s module
docstring for the design decisions this story required -- they apply
identically here, mirroring
``tests/bdd/steps/cusum_control_limit_fitting_steps.py``'s and
``tests/bdd/steps/ewma_control_limit_fitting_steps.py``'s own structure; not
re-argued in this file to avoid duplication.

Steps are kept thin (no business-rule assertions beyond what a single
Gherkin line states) -- the rigorous, mutation-resistant assertions (exact
sets, the boundary property, the closed-form numeric proof) live in
``tests/unit/baseline/test_shewhart_fitting.py`` and
``tests/unit/baseline/test_shewhart_arl_published_values.py`` instead, per
``test-patterns``' BDD guidance.

No numeric literal in this file is a claim about statistical correctness --
every concrete value below is an arbitrary valid input chosen only to
exercise a scenario, exactly as the feature file itself names none.

**Decision specific to this file:** the shared "Given ... passes the
sufficiency check" step below builds baselines from a fixed, deliberately
non-monotonic score pattern rather than independently-random factory scores
(unlike the CUSUM/EWMA equivalents). This is what lets the two
observation-order scenarios (BR-7) reorder a *known* sequence and be certain
the reordering changes at least one consecutive difference, without a
separate baseline builder just for those two scenarios -- and it does not
weaken any other scenario reusing the same step, since a fixed non-monotonic
pattern has non-zero variance exactly as well as random scores do.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from pytest_bdd import given, parsers, then, when

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedShewhart,
    fit_shewhart,
)

# MIN_*/MAX_* validation bounds are internal (BIN-110 P2) -- no longer
# re-exported from caliper.baseline, so steps that need the exact bound
# values import them from the owning submodule directly.
#
# MIN_TARGET_ARL (100, ADR-011's hard floor) replaces MIN_MEANINGFUL_ARL (now
# MIN_COHERENT_ARL, 1.0, no longer a legal target_arl) as the smallest legal
# value -- see tests/unit/baseline/test_shewhart_fitting.py's identical note.
from caliper.baseline.domain.shewhart_fitting import (
    MAX_MEANINGFUL_ARL,
    MIN_TARGET_ARL,
)
from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)
from caliper.measurement import Provenance
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary valid input used whenever a scenario's own Given/When text does
# not itself parametrise the value under test -- see the module docstring.
_VALID_TARGET_ARL = 370.0

_IDENTICAL_SCORE = 0.62
_ZERO_VARIANCE_REASON = "zero_variance"

_INVALID_TARGET_ARL_VALUES = {
    "zero": 0.0,
    "negative": -10.0,
    "outside the meaningful range": MAX_MEANINGFUL_ARL * 2,
}
_TARGET_ARL_BOUNDARIES = {
    "the smallest meaningful value": MIN_TARGET_ARL,
    "the largest meaningful value": MAX_MEANINGFUL_ARL,
}

# A deliberately non-monotonic, non-sorted pattern of distinct scores (BR-7):
# consecutive differences vary, and no two adjacent scores are ever equal,
# so sorting it is guaranteed to change at least one consecutive difference
# -- required for the two observation-order scenarios below to be
# meaningful rather than coincidentally order-invariant.
_SCORE_PATTERN = [0.10, 0.90, 0.30, 0.70, 0.20, 0.80, 0.40, 0.60]


def _ordered_scores(count: int) -> list[float]:
    return [_SCORE_PATTERN[i % len(_SCORE_PATTERN)] for i in range(count)]


def _baseline_from_scores(scores: list[float], provenance: Provenance) -> Baseline:
    baseline = Baseline()
    for score in scores:
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))
    return baseline


def _baseline_with_observations(count: int, *, score: float | None = None) -> Baseline:
    """Build a ``Baseline`` with ``count`` observations under shared provenance.

    Non-zero-variance baselines use the fixed ``_SCORE_PATTERN`` (see module
    docstring) rather than independently-random factory scores.
    """
    provenance = ProvenanceFactory()
    if score is None:
        return _baseline_from_scores(_ordered_scores(count), provenance)
    return _baseline_from_scores([score] * count, provenance)


@dataclass
class FittingOutcome:
    """A successful ``fit_shewhart()`` call, with the baseline it was fitted from."""

    baseline: Baseline
    result: FittedShewhart


@dataclass
class FittingAttempt:
    """The outcome of a ``fit_shewhart()`` call expected to fail."""

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


@dataclass
class TwoFits:
    """The results of fitting the same set of scores in two different orders (BR-7)."""

    first: FittedShewhart
    second: FittedShewhart


def _capture_fitting_error(
    baseline: Baseline, *, target_arl: float | None
) -> FittingAttempt:
    try:
        fit_shewhart(baseline, target_arl=target_arl)
    except CaliperError as exc:
        return FittingAttempt(baseline=baseline, error=exc)
    raise AssertionError("expected fit_shewhart() to raise for this scenario")


# --- Given: a baseline that passes the sufficiency check, with variance ------------


@given(
    "the engineer has a Phase I baseline that passes the sufficiency check",
    target_fixture="baseline",
)
def a_baseline_passing_the_sufficiency_check() -> Baseline:
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)


@given("the baseline scores show non-zero variance")
def baseline_scores_show_non_zero_variance(baseline: Baseline) -> None:
    # The fixed score pattern already gives the baseline non-zero variance.
    # Nothing further to do; this step exists so the scenario's Gherkin
    # line has a bound implementation.
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
    "the engineer has fitted Shewhart I-chart control limits from a Phase I baseline",
    target_fixture="outcome",
)
def a_baseline_already_fitted() -> FittingOutcome:
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    result = fit_shewhart(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


# --- When: fit with a specified tolerance (SC1, SC3) --------------------------------


@when(
    "they fit Shewhart I-chart control limits with a specified false alarm tolerance",
    target_fixture="outcome",
)
def fit_with_specified_tolerance(baseline: Baseline) -> FittingOutcome:
    result = fit_shewhart(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


# --- When: inspect the already-fitted artefact (auditability) ----------------------


@when("they inspect the fitted artefact", target_fixture="outcome")
def inspect_the_fitted_artefact(outcome: FittingOutcome) -> FittingOutcome:
    return outcome


# --- When: attempt to fit (reused by insufficient and degenerate scenarios) --------


@when("they attempt to fit Shewhart I-chart control limits", target_fixture="attempt")
def attempt_to_fit(baseline: Baseline) -> FittingAttempt:
    return _capture_fitting_error(baseline, target_arl=_VALID_TARGET_ARL)


# --- When: attempt to fit with an invalid false alarm tolerance --------------------


@when(
    parsers.parse(
        "they attempt to fit Shewhart I-chart control limits with a false alarm "
        "tolerance that is {invalid_case}"
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
    "they attempt to fit Shewhart I-chart control limits without specifying a false "
    "alarm tolerance",
    target_fixture="attempt",
)
def attempt_to_fit_without_target_arl(baseline: Baseline) -> FittingAttempt:
    return _capture_fitting_error(baseline, target_arl=None)


# --- Given: three failed fitting attempts, one per category (distinguishability) ---


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
        "ucl": result.ucl,
        "sigma_multiplier": result.sigma_multiplier,
        "baseline_mean": result.baseline_mean,
        "provenance_model_version": result.provenance_model_version,
    }
    attempted_mutations: list[tuple[str, object]] = [
        ("ucl", result.ucl + 1.0),
        ("sigma_multiplier", result.sigma_multiplier + 0.01),
        ("baseline_mean", result.baseline_mean + 1.0),
        ("provenance_model_version", "tampered"),
    ]
    raised_every_time = True
    for attribute, replacement in attempted_mutations:
        # Any raise means the mutation was correctly rejected -- that is the
        # assertion, recorded in `raised_every_time` rather than swallowed.
        with contextlib.suppress(Exception):
            setattr(result, attribute, replacement)
            raised_every_time = False
    return MutationAttempt(
        outcome=outcome, snapshot=snapshot, raised_for_every_attempt=raised_every_time
    )


# --- When: fit with a false alarm tolerance at a named boundary --------------------


@when(
    parsers.parse(
        "they fit Shewhart I-chart control limits with a false alarm tolerance at "
        "{boundary}"
    ),
    target_fixture="outcome",
)
def fit_with_target_arl_at_boundary(
    baseline: Baseline, boundary: str
) -> FittingOutcome:
    boundary_value = _TARGET_ARL_BOUNDARIES[boundary]
    result = fit_shewhart(baseline, target_arl=boundary_value)
    return FittingOutcome(baseline=baseline, result=result)


# --- When: fit in recorded order, and reordered (BR-7) ------------------------------


@when(
    "they fit Shewhart I-chart control limits from the baseline in its recorded "
    "observation order",
    target_fixture="outcome",
)
def fit_in_recorded_order(baseline: Baseline) -> FittingOutcome:
    result = fit_shewhart(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


@when(
    "they fit Shewhart I-chart control limits from that baseline",
    target_fixture="first_outcome",
)
def fit_from_that_baseline(baseline: Baseline) -> FittingOutcome:
    result = fit_shewhart(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


@when(
    "they fit again from the same scores reordered so that the consecutive "
    "differences change",
    target_fixture="two_fits",
)
def fit_again_reordered(first_outcome: FittingOutcome) -> TwoFits:
    original_scores = [
        observation.score for observation in first_outcome.baseline.observations
    ]
    provenance = first_outcome.baseline.provenance_signature
    assert provenance is not None
    reordered_baseline = _baseline_from_scores(sorted(original_scores), provenance)
    second_result = fit_shewhart(reordered_baseline, target_arl=_VALID_TARGET_ARL)
    return TwoFits(first=first_outcome.result, second=second_result)


# --- Then: core fitting result shape (SC1, boundary outlines) ----------------------


@then("the result contains upper and lower control limits and a centre line")
def result_contains_control_limits_and_centre_line(outcome: FittingOutcome) -> None:
    result = outcome.result
    assert isinstance(result.ucl, float)
    assert isinstance(result.lcl, float)
    assert isinstance(result.cl, float)


@then("the result reports the sigma estimate derived from the baseline")
def result_reports_sigma_estimate(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.sigma_estimate, float)


@then("the result reports the sigma multiplier used to derive the control limits")
def result_reports_sigma_multiplier(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.sigma_multiplier, float)


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


@then(
    "the artefact reports the baseline mean and the sigma estimate used to compute "
    "the limits"
)
def artefact_reports_baseline_mean_and_sigma_estimate(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.baseline_mean, float)
    assert isinstance(outcome.result.sigma_estimate, float)


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


# --- Then: sigma estimation method (SC3) ---------------------------------------------


@then(
    "the fitted artefact reports that sigma was estimated using the moving-range method"
)
def artefact_reports_moving_range_method(outcome: FittingOutcome) -> None:
    assert outcome.result.sigma_estimation_method == "moving_range"


# --- Then: observation order dependency (BR-7) ----------------------------------------


@then(
    "the control limits reflect the consecutive-observation differences in that order"
)
def control_limits_reflect_consecutive_differences(outcome: FittingOutcome) -> None:
    # The mutation-resistant, independently-computed assertion lives in
    # test_shewhart_fitting.py (module docstring, point 6); this step
    # demonstrates the same property holds through the public scenario
    # language -- the fitted sigma is a real, finite number derived from
    # this specific baseline, not a placeholder.
    assert isinstance(outcome.result.sigma_estimate, float)
    assert outcome.result.sigma_estimate > 0.0


@then("the limits are not determined by the set of scores alone")
def limits_not_determined_by_the_set_of_scores_alone(outcome: FittingOutcome) -> None:
    original_scores = [
        observation.score for observation in outcome.baseline.observations
    ]
    provenance = outcome.baseline.provenance_signature
    assert provenance is not None
    reordered_baseline = _baseline_from_scores(sorted(original_scores), provenance)

    reordered_result = fit_shewhart(reordered_baseline, target_arl=_VALID_TARGET_ARL)

    assert reordered_result.sigma_estimate != outcome.result.sigma_estimate


@then("the two fits report different sigma estimates")
def two_fits_report_different_sigma_estimates(two_fits: TwoFits) -> None:
    assert two_fits.first.sigma_estimate != two_fits.second.sigma_estimate


@then("the two fits report different control limits")
def two_fits_report_different_control_limits(two_fits: TwoFits) -> None:
    assert (two_fits.first.ucl, two_fits.first.lcl) != (
        two_fits.second.ucl,
        two_fits.second.lcl,
    )


# --- Then: insufficient baseline ----------------------------------------------------


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


# --- Then: degenerate baseline --------------------------------------------------------


@then("the fitting fails with an error classifiable as a degenerate baseline")
def fitting_fails_as_degenerate_baseline(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error, DegenerateBaselineError)
    assert attempt.error.category == "degenerate_baseline"


@then(
    "the error explains that I-chart control limits require score variation in the "
    "baseline"
)
def error_explains_score_variation_required(attempt: FittingAttempt) -> None:
    assert attempt.error.context["reason"] == _ZERO_VARIANCE_REASON


@then("the error carries recovery guidance for addressing the zero-variance condition")
def error_carries_recovery_guidance_for_zero_variance(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error.recovery_hint, str)
    assert attempt.error.recovery_hint != ""


# --- Then: invalid parameter (target_arl outlines, missing) ------------------------


@then("the fitting fails with an error classifiable as an invalid parameter")
def fitting_fails_as_invalid_parameter(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error, InvalidParameterError)
    assert attempt.error.category == "invalid_parameter"


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
    # The raise itself is the proof -- no FittedShewhart exists in this branch.
    assert attempt.error is not None


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
    assert result.ucl == mutation.snapshot["ucl"]
    assert result.sigma_multiplier == mutation.snapshot["sigma_multiplier"]
    assert result.baseline_mean == mutation.snapshot["baseline_mean"]
    assert (
        result.provenance_model_version == mutation.snapshot["provenance_model_version"]
    )
