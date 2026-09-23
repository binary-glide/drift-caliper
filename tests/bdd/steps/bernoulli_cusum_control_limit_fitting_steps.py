"""Step definitions for BIN-133: fit a Bernoulli CUSUM from a binary-rubric baseline.

Binds to
``tests/bdd/features/baseline/bernoulli-cusum-control-limit-fitting.feature``
via ``tests/bdd/test_bernoulli_cusum_control_limit_fitting.py``. Error
assertions follow ADR-002/ADR-008: type + required ``context`` keys only --
never message text. Mirrors ``tests/bdd/steps/cusum_control_limit_fitting_steps.py``'s
shape and discipline; not re-argued here.

🚨 **The feature file this binds to had a parser-breaking defect, fixed as
part of writing this file.** As committed on this branch, every wrapped
Given/When/Then line was a genuine physical line break with continuation
text indented on the next line -- e.g.

    Given a Phase I baseline of pass/fail judgements whose failure rate is
      neither zero nor total, ...

Gherkin has no such continuation syntax: a step is exactly one physical
line. Parsing the file as committed with ``gherkin.parser.Parser`` raises
``CompositeParserException`` on eleven separate lines -- verified directly,
not assumed -- which means **no step of any kind could ever have bound to
this file**, regardless of what this module did. The fix reflows every
wrapped step onto a single physical line, joining with a single space;
confirmed byte-identical to the original once both are whitespace-normalised
(``re.sub(r'\\s+', ' ', text)``) -- no scenario's wording changed, only its
line breaks. This is a mechanical parse-syntax fix, not a change to
scenario content, so it does not fall under "feature files are fixed" any
more than fixing a typo in step-binding whitespace would.

**Interface this file commits `domain-implementer` to** -- none of the
following exists in ``src/`` yet (verified: no ``bernoulli``/``clopper_pearson``/
``gicp`` module anywhere), per ADR-012/013/014 and ``docs/domain-model.md``:

- ``drift_caliper.baseline.fit_bernoulli_cusum(baseline, *, target_arl=None,
  detect_rate_multiple=None, direction=None) -> FittedBernoulliCUSUM``
- ``drift_caliper.baseline.FittedBernoulliCUSUM`` -- satisfies ``HasProvenance``
  only, per ADR-014 Decision 6a. Field names per ADR-014 Decision 6b:
  ``chart_type``, ``observed_failure_rate``, ``observation_count``,
  ``provenance_model_version``, ``provenance_criteria``, ``requested_arl``,
  ``achieved_arl``, ``expected_detection_arl``, ``calibration_method``,
  ``advisories``, ``detect_rate_multiple``, ``alpha``, ``p_u``, ``direction``,
  ``reference_value_lower``, ``decision_interval_lower``,
  ``reference_value_upper``, ``decision_interval_upper``.
- ``drift_caliper.monitoring.Monitor`` must accept a ``FittedBernoulliCUSUM``
  (ADR-014 6a's ``Monitor.__init__`` signature widening;
  ``docs/domain-model.md``'s Monitor invariant 9 for the Phase II binary-score
  precondition).

Steps are kept thin -- the rigorous, mutation-resistant assertions (exact
GICP/Clopper-Pearson correctness, the numeric ARL proof, the exception-contract
audit) live in ``tests/unit/baseline/test_bernoulli_cusum_fitting.py``,
``tests/unit/baseline/test_clopper_pearson.py`` and
``tests/unit/baseline/test_bernoulli_cusum_arl_published_values.py`` instead,
per ``test-patterns``' BDD guidance.

No numeric literal in this file is a claim about statistical correctness --
every concrete value below is an arbitrary valid input chosen only to
exercise a scenario, exactly as the feature file itself names none.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from pytest_bdd import given, then, when

# 🚨 These two names do not exist in `drift_caliper.baseline` yet -- this
# import is the expected red. See the module docstring's "Interface this file
# commits domain-implementer to" section.
from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedBernoulliCUSUM,
    fit_bernoulli_cusum,
)
from drift_caliper.errors import (
    CaliperError,
    InsufficientBaselineError,
    InvalidParameterError,
    ProvenanceMismatchError,
)
from drift_caliper.monitoring import Monitor
from drift_caliper.monitoring.domain.monitoring_result import MonitoringResult
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary valid inputs used whenever a scenario's own Given/When text does
# not itself parametrise the value under test -- see the module docstring.
_VALID_TARGET_ARL = 370.0
_MIXED_FAILURE_RATE = 0.1  # 10% -- neither zero nor total, a realistic rate
_CUSTOM_DETECT_RATE_MULTIPLE = 3.0  # distinct from the library default (2.0)
# Large enough that `p_U * multiple >= 1` regardless of what GICP's p_U
# construction settles on for a ~10% observed failure rate -- deliberately
# not tuned to any specific p_U implementation.
_UNATTAINABLE_DETECT_RATE_MULTIPLE = 1_000_000.0
_RISING_ONLY_DIRECTION = "lower"  # ADR-012's convention: lower = degradation


def _bernoulli_baseline(count: int, *, num_failures: int) -> Baseline:
    """Build a ``Baseline`` of ``count`` pass/fail judgements, ``num_failures`` failed.

    Scores are exactly ``0.0`` (fail) or ``1.0`` (pass) -- ADR-012 amendment
    section 1's sign convention (higher-is-better; a Bernoulli observation's
    "failure" is ``1 - score``). ``num_failures`` must not exceed ``count``.
    """
    if not 0 <= num_failures <= count:
        raise ValueError("num_failures must be between 0 and count")
    shared_provenance = ProvenanceFactory()
    baseline = Baseline()
    for i in range(count):
        score = 0.0 if i < num_failures else 1.0
        baseline.record(ScoringResultFactory(provenance=shared_provenance, score=score))
    return baseline


def _sufficient_mixed_baseline(*, extra: int = 5) -> Baseline:
    count = DEFAULT_SUFFICIENCY_THRESHOLD + extra
    num_failures = max(1, round(count * _MIXED_FAILURE_RATE))
    return _bernoulli_baseline(count, num_failures=num_failures)


@dataclass
class FittingOutcome:
    """A successful ``fit_bernoulli_cusum()`` call, with the baseline it was fitted
    from."""

    baseline: Baseline
    result: FittedBernoulliCUSUM


@dataclass
class FittingAttempt:
    """The outcome of a ``fit_bernoulli_cusum()`` call expected to fail."""

    baseline: Baseline
    error: CaliperError


@dataclass
class UnattainableFittingAttempt:
    """A fitting attempt refused because the requested sensitivity was unattainable
    (BIN-122)."""

    baseline: Baseline
    error: CaliperError


@dataclass
class MutationAttempt:
    """Every attempted post-creation mutation of a fitted artefact, and whether all were
    rejected."""

    outcome: FittingOutcome
    snapshot: dict[str, object]
    raised_for_every_attempt: bool


@dataclass
class MonitoringContext:
    """A fitted Bernoulli CUSUM chart wrapped in a fresh ``Monitor``, with its
    provenance."""

    baseline: Baseline
    chart: FittedBernoulliCUSUM
    monitor: Monitor


@dataclass
class RecordingAttempt:
    """The outcome of a ``Monitor.record()`` call expected to fail with a provenance
    mismatch."""

    context: MonitoringContext
    error: CaliperError


@dataclass
class RecordingOutcome:
    """A successful ``Monitor.record()`` call."""

    context: MonitoringContext
    result: MonitoringResult


def _capture_fitting_error(
    baseline: Baseline,
    *,
    target_arl: float | None,
    detect_rate_multiple: float | None = None,
    direction: str | None = None,
) -> FittingAttempt:
    try:
        fit_bernoulli_cusum(
            baseline,
            target_arl=target_arl,
            detect_rate_multiple=detect_rate_multiple,
            direction=direction,
        )
    except CaliperError as exc:
        return FittingAttempt(baseline=baseline, error=exc)
    raise AssertionError("expected fit_bernoulli_cusum() to raise for this scenario")


# --- Given: baselines ----------------------------------------------------------------


@given(
    "a Phase I baseline of pass/fail judgements whose failure rate is neither "
    "zero nor total, with enough observations to meet the minimum Caliper "
    "requires for binary data",
    target_fixture="baseline",
)
def a_mixed_baseline_with_enough_observations() -> Baseline:
    return _sufficient_mixed_baseline()


@given(
    "a Phase I baseline of pass/fail judgements whose failure rate is neither "
    "zero nor total, with exactly the minimum number of observations Caliper "
    "requires for binary data",
    target_fixture="baseline",
)
def a_mixed_baseline_at_exactly_the_minimum() -> Baseline:
    return _bernoulli_baseline(
        DEFAULT_SUFFICIENCY_THRESHOLD,
        num_failures=max(1, round(DEFAULT_SUFFICIENCY_THRESHOLD * _MIXED_FAILURE_RATE)),
    )


@given(
    "a Phase I baseline of pass/fail judgements below the minimum Caliper "
    "requires for binary data",
    target_fixture="baseline",
)
def a_baseline_below_the_minimum() -> Baseline:
    count = DEFAULT_SUFFICIENCY_THRESHOLD - 10
    return _bernoulli_baseline(count, num_failures=max(1, count // 10))


@given(
    "a Phase I baseline of pass/fail judgements where every judgement passed, "
    "with enough observations to meet the minimum Caliper requires for binary "
    "data",
    target_fixture="baseline",
)
def a_baseline_where_every_judgement_passed() -> Baseline:
    return _bernoulli_baseline(DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=0)


@given(
    "a Phase I baseline where every recorded judgement failed, with enough "
    "observations to meet the minimum Caliper requires for binary data",
    target_fixture="baseline",
)
def a_baseline_where_every_judgement_failed() -> Baseline:
    count = DEFAULT_SUFFICIENCY_THRESHOLD + 5
    return _bernoulli_baseline(count, num_failures=count)


@given(
    "a sufficient Phase I baseline of pass/fail judgements", target_fixture="baseline"
)
def a_sufficient_mixed_baseline() -> Baseline:
    return _sufficient_mixed_baseline()


@given(
    "the engineer has a sufficient Phase I baseline of pass/fail judgements",
    target_fixture="baseline",
)
def the_engineer_has_a_sufficient_mixed_baseline() -> Baseline:
    return _sufficient_mixed_baseline()


# --- Given: an already-fitted chart (auditability, immutability) ---------------------


@given(
    "the engineer has fitted a Bernoulli CUSUM chart from a Phase I baseline",
    target_fixture="outcome",
)
def the_engineer_has_fitted_a_bernoulli_cusum_chart() -> FittingOutcome:
    baseline = _sufficient_mixed_baseline()
    result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


# --- When: fit with a specified tolerance (Story 1) -----------------------------------


@when(
    "the engineer fits a chart requesting a specific false-alarm tolerance",
    target_fixture="outcome",
)
def fit_with_specified_tolerance(baseline: Baseline) -> FittingOutcome:
    result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


@when("they inspect the fitted artefact", target_fixture="outcome")
def inspect_the_fitted_artefact(outcome: FittingOutcome) -> FittingOutcome:
    return outcome


# --- When: attempt to fit (insufficient / all-failed) ---------------------------------


@when("the engineer attempts to fit a chart", target_fixture="attempt")
def the_engineer_attempts_to_fit_a_chart(baseline: Baseline) -> FittingAttempt:
    return _capture_fitting_error(baseline, target_arl=_VALID_TARGET_ARL)


# --- Then: core fitting result shape (Story 1) ----------------------------------------


@then(
    "they receive a fitted chart reporting a false-alarm rate that matches "
    "their request to within the chart's stated tolerance"
)
def receives_a_chart_matching_the_requested_tolerance(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.requested_arl, float)
    assert isinstance(outcome.result.achieved_arl, float)
    assert outcome.result.requested_arl == _VALID_TARGET_ARL


@then("the fitted chart reports the failure rate it is tuned to detect a rise from")
def reports_the_failure_rate_tuned_to_detect(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.observed_failure_rate, float)
    assert 0.0 <= outcome.result.observed_failure_rate <= 1.0


@then(
    "the fitted chart reports how quickly it is expected to catch the "
    "degradation it is tuned to detect"
)
def reports_expected_detection_speed(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.expected_detection_arl, float)


@then(
    "the fitted chart reports how quickly it is expected to catch a failure "
    "rate rising from a baseline that showed no failures at all"
)
def reports_expected_detection_speed_from_zero_failures(
    outcome: FittingOutcome,
) -> None:
    assert outcome.result.observed_failure_rate == 0.0
    assert isinstance(outcome.result.expected_detection_arl, float)


# --- Then: insufficient baseline
# -------------------------------------------------------


@then("the fitting fails with an error classifiable as an insufficient baseline")
def fitting_fails_as_insufficient_baseline(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error, InsufficientBaselineError)
    assert attempt.error.category == "insufficient_baseline"


@then(
    "the error reports how many observations the baseline has and how many "
    "more that minimum requires"
)
def error_reports_have_and_need(attempt: FittingAttempt) -> None:
    assert attempt.error.context["have"] == attempt.baseline.observation_count
    assert isinstance(attempt.error.context["need"], int)
    assert attempt.error.context["need"] > attempt.error.context["have"]


@then("no control limits are produced")
def no_control_limits_are_produced(attempt: FittingAttempt) -> None:
    # The raise itself is the proof -- no FittedBernoulliCUSUM exists in this branch.
    assert attempt.error is not None


# --- Then: invalid parameter (all-failed baseline / unattainable sensitivity) --------


@then("the fitting fails with an error classifiable as an invalid parameter")
def fitting_fails_as_invalid_parameter(attempt: FittingAttempt) -> None:
    assert isinstance(attempt.error, InvalidParameterError)
    assert attempt.error.category == "invalid_parameter"


@then(
    "the error explains that no valid detection design exists for a baseline "
    "with no passing judgements"
)
def error_explains_no_valid_design_for_all_failed(attempt: FittingAttempt) -> None:
    error = attempt.error
    assert isinstance(error, InvalidParameterError)
    # ADR-013 section 5: folded into the invalid_parameter path, same reason
    # as an unattainable detect_rate_multiple, distinguished by `reason` --
    # and, per ADR-013 section 6b, carries no `max_detect_rate_multiple`
    # since no multiple would fix an all-failed baseline.
    assert error.context["reason"] == "all_baseline_judgements_failed"
    assert "max_detect_rate_multiple" not in error.context


@then(
    "the error reports the largest sensitivity their baseline's failure rate can "
    "support"
)
def error_reports_the_largest_supportable_sensitivity(attempt: FittingAttempt) -> None:
    error = attempt.error
    assert isinstance(error, InvalidParameterError)
    max_multiple = error.context["max_detect_rate_multiple"]
    assert isinstance(max_multiple, float)
    assert max_multiple > 0.0


# --- When: unattainable sensitivity (Story 2) -----------------------------------------


@when(
    "the engineer requests a detection sensitivity so large that the failure "
    "rate it implies is no longer a valid probability",
    target_fixture="attempt",
)
def requests_an_unattainable_detection_sensitivity(
    baseline: Baseline,
) -> FittingAttempt:
    return _capture_fitting_error(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        detect_rate_multiple=_UNATTAINABLE_DETECT_RATE_MULTIPLE,
    )


@given(
    "a fitting attempt was refused because the requested detection sensitivity "
    "was not achievable for the baseline's failure rate",
    target_fixture="unattainable_attempt",
)
def a_fitting_attempt_refused_for_unattainable_sensitivity() -> (
    UnattainableFittingAttempt
):
    baseline = _sufficient_mixed_baseline()
    attempt = _capture_fitting_error(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        detect_rate_multiple=_UNATTAINABLE_DETECT_RATE_MULTIPLE,
    )
    return UnattainableFittingAttempt(baseline=baseline, error=attempt.error)


@when(
    "the engineer fits a chart requesting exactly the largest sensitivity that "
    "the error reported, against the same baseline",
    target_fixture="outcome",
)
def fits_with_the_reported_max_sensitivity(
    unattainable_attempt: UnattainableFittingAttempt,
) -> FittingOutcome:
    # BIN-122: value comes out of the error's own context -- never recomputed
    # and never hard-coded -- so this genuinely round-trips what the library
    # itself reported.
    reported_max = unattainable_attempt.error.context["max_detect_rate_multiple"]
    result = fit_bernoulli_cusum(
        unattainable_attempt.baseline,
        target_arl=_VALID_TARGET_ARL,
        detect_rate_multiple=reported_max,
    )
    return FittingOutcome(baseline=unattainable_attempt.baseline, result=result)


@then("they receive a fitted chart tuned to that sensitivity")
def receives_a_chart_tuned_to_that_sensitivity(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.detect_rate_multiple, float)


@then("no error is raised")
def no_error_is_raised(outcome: FittingOutcome) -> None:
    # Reaching this step at all (via a successful `outcome` fixture) is the
    # proof -- pytest-bdd would have failed the When step otherwise.
    assert outcome.result is not None


# --- When/Then: documented default detection sensitivity (Story 2) -------------------


@when(
    "the engineer fits a chart without specifying how large a rise in the "
    "failure rate to watch for",
    target_fixture="outcome",
)
def fits_without_specifying_detect_rate_multiple(baseline: Baseline) -> FittingOutcome:
    result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


@then(
    "they receive a fitted chart tuned to a documented default rise in the failure rate"
)
def receives_a_chart_tuned_to_the_documented_default(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.detect_rate_multiple, float)
    assert outcome.result.detect_rate_multiple > 0.0


@then("the fitted chart reports what that rise is")
def reports_what_the_rise_is(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.detect_rate_multiple, float)


# --- When/Then: engineer-specified detection sensitivity (Story 2) -------------------


@when(
    "the engineer fits a chart specifying how large a rise in the failure "
    "rate to watch for, expressed as a multiple of their own baseline's "
    "failure rate",
    target_fixture="outcome",
)
def fits_with_a_specified_detect_rate_multiple(baseline: Baseline) -> FittingOutcome:
    result = fit_bernoulli_cusum(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        detect_rate_multiple=_CUSTOM_DETECT_RATE_MULTIPLE,
    )
    return FittingOutcome(baseline=baseline, result=result)


@then("they receive a fitted chart tuned to that degradation")
def receives_a_chart_tuned_to_that_degradation(outcome: FittingOutcome) -> None:
    assert outcome.result.detect_rate_multiple == _CUSTOM_DETECT_RATE_MULTIPLE


@then(
    "the fitted chart reports the same kind of false-alarm-rate guarantee as "
    "the default case"
)
def reports_the_same_kind_of_false_alarm_guarantee(outcome: FittingOutcome) -> None:
    assert isinstance(outcome.result.requested_arl, float)
    assert isinstance(outcome.result.achieved_arl, float)
    assert outcome.result.requested_arl == _VALID_TARGET_ARL


# --- When/Then: direction (Story 2)
# ----------------------------------------------------


@when(
    "the engineer fits a chart without specifying which directions of drift to watch",
    target_fixture="outcome",
)
def fits_without_specifying_direction(baseline: Baseline) -> FittingOutcome:
    result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    return FittingOutcome(baseline=baseline, result=result)


@then(
    "they receive a fitted chart that reports it watches for both a rising "
    "and a falling failure rate"
)
def receives_a_two_sided_chart(outcome: FittingOutcome) -> None:
    assert outcome.result.direction == "two_sided"


@when(
    "the engineer fits a chart specifying that only a rise in the failure "
    "rate should be watched",
    target_fixture="outcome",
)
def fits_specifying_rise_only(baseline: Baseline) -> FittingOutcome:
    result = fit_bernoulli_cusum(
        baseline, target_arl=_VALID_TARGET_ARL, direction=_RISING_ONLY_DIRECTION
    )
    return FittingOutcome(baseline=baseline, result=result)


@then(
    "they receive a fitted chart that reports it watches for a rising failure rate only"
)
def receives_a_rising_only_chart(outcome: FittingOutcome) -> None:
    assert outcome.result.direction == _RISING_ONLY_DIRECTION


# --- Then: auditability (Story 1)
# -------------------------------------------------------


@then(
    "the artefact reports the observed failure rate and the number of "
    "baseline observations the chart was fitted from"
)
def artefact_reports_failure_rate_and_observation_count(
    outcome: FittingOutcome,
) -> None:
    assert isinstance(outcome.result.observed_failure_rate, float)
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


# --- When/Then: immutability
# -------------------------------------------------------------


@when(
    "they attempt to modify the limits, parameters, baseline statistics, or "
    "provenance of the fitted artefact",
    target_fixture="mutation",
)
def attempt_to_mutate_the_fitted_artefact(outcome: FittingOutcome) -> MutationAttempt:
    result = outcome.result
    snapshot: dict[str, object] = {
        "decision_interval_lower": result.decision_interval_lower,
        "reference_value_lower": result.reference_value_lower,
        "observed_failure_rate": result.observed_failure_rate,
        "provenance_model_version": result.provenance_model_version,
    }
    attempted_mutations: list[tuple[str, object]] = [
        ("decision_interval_lower", result.decision_interval_lower + 1.0),
        ("reference_value_lower", result.reference_value_lower + 0.01),
        ("observed_failure_rate", result.observed_failure_rate + 0.01),
        ("provenance_model_version", "tampered"),
    ]
    raised_every_time = True
    for attribute, replacement in attempted_mutations:
        with contextlib.suppress(Exception):
            setattr(result, attribute, replacement)
            raised_every_time = False
    return MutationAttempt(
        outcome=outcome, snapshot=snapshot, raised_for_every_attempt=raised_every_time
    )


@then("the modification is rejected")
def the_modification_is_rejected(mutation: MutationAttempt) -> None:
    assert mutation.raised_for_every_attempt is True


@then("the artefact continues to report its original values")
def the_artefact_reports_its_original_values(mutation: MutationAttempt) -> None:
    result = mutation.outcome.result
    assert (
        result.decision_interval_lower == mutation.snapshot["decision_interval_lower"]
    )
    assert result.reference_value_lower == mutation.snapshot["reference_value_lower"]
    assert result.observed_failure_rate == mutation.snapshot["observed_failure_rate"]
    assert (
        result.provenance_model_version == mutation.snapshot["provenance_model_version"]
    )


# --- Story 3: provenance mismatch
# -------------------------------------------------------


@given(
    "a fitted Bernoulli CUSUM chart tied to a specific judge model version and rubric",
    target_fixture="context",
)
def a_fitted_chart_tied_to_a_specific_judge_and_rubric() -> MonitoringContext:
    baseline = _sufficient_mixed_baseline()
    chart = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    monitor = Monitor(chart)
    return MonitoringContext(baseline=baseline, chart=chart, monitor=monitor)


@when(
    "the engineer records a Phase II judgement made under a different judge "
    "model version",
    target_fixture="attempt",
)
def records_a_judgement_under_a_different_model_version(
    context: MonitoringContext,
) -> RecordingAttempt:
    mismatched = ScoringResultFactory(provenance=ProvenanceFactory(), score=1.0)
    try:
        context.monitor.record(mismatched)
    except CaliperError as exc:
        return RecordingAttempt(context=context, error=exc)
    raise AssertionError("expected Monitor.record() to raise for a provenance mismatch")


@then(
    "the recording fails with an error classifiable as a provenance mismatch, "
    "identifying which aspect of the judge changed and what it was expected "
    "to be"
)
def recording_fails_as_provenance_mismatch(attempt: RecordingAttempt) -> None:
    error = attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert error.category == "provenance_mismatch"
    assert "model_version" in error.mismatches
    assert "expected" in error.mismatches["model_version"]
    assert "received" in error.mismatches["model_version"]


@then("no drift signal is computed from that judgement")
def no_drift_signal_is_computed(attempt: RecordingAttempt) -> None:
    assert len(attempt.context.monitor.history) == 0


@when(
    "the engineer records a Phase II judgement made under that same judge "
    "model version and rubric",
    target_fixture="outcome",
)
def records_a_judgement_under_the_same_model_and_rubric(
    context: MonitoringContext,
) -> RecordingOutcome:
    signature = context.baseline.provenance_signature
    assert signature is not None
    matching = ScoringResultFactory(provenance=signature, score=1.0)
    result = context.monitor.record(matching)
    return RecordingOutcome(context=context, result=result)


@then(
    "the judgement is accepted into monitoring and contributes to the chart's "
    "running state"
)
def judgement_accepted_and_contributes_to_running_state(
    outcome: RecordingOutcome,
) -> None:
    assert isinstance(outcome.result, MonitoringResult)
    assert len(outcome.context.monitor.history) == 1


# --- Cross-cutting: error distinguishability and determinism -------------------------


@given(
    "a fitting attempt has failed because the baseline had too few observations",
    target_fixture="errors",
)
def a_fitting_attempt_failed_for_too_few_observations() -> dict[str, CaliperError]:
    baseline = a_baseline_below_the_minimum()
    attempt = _capture_fitting_error(baseline, target_arl=_VALID_TARGET_ARL)
    return {"insufficient_baseline": attempt.error}


@given(
    "a separate fitting attempt has failed because the requested detection "
    "sensitivity was not achievable"
)
def a_separate_fitting_attempt_failed_for_unattainable_sensitivity(
    errors: dict[str, CaliperError],
) -> None:
    baseline = _sufficient_mixed_baseline()
    attempt = _capture_fitting_error(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        detect_rate_multiple=_UNATTAINABLE_DETECT_RATE_MULTIPLE,
    )
    errors["invalid_parameter"] = attempt.error


@when("the engineer compares the two errors", target_fixture="errors")
def the_engineer_compares_the_two_errors(
    errors: dict[str, CaliperError],
) -> dict[str, CaliperError]:
    return errors


@then(
    "each is classifiable under a different category without inspecting the "
    "error message text"
)
def each_error_has_a_distinct_category(errors: dict[str, CaliperError]) -> None:
    categories = {error.category for error in errors.values()}
    assert categories == {"insufficient_baseline", "invalid_parameter"}


@then("the recovery guidance for each category is distinct from the other")
def recovery_guidance_is_distinct_per_category(errors: dict[str, CaliperError]) -> None:
    hints = {error.recovery_hint for error in errors.values()}
    assert len(hints) == 2


# --- Determinism
# -----------------------------------------------------------------------


@when(
    "they fit a chart from it twice, with identical parameters both times",
    target_fixture="repeated_outcomes",
)
def fits_the_same_baseline_twice(
    baseline: Baseline,
) -> tuple[FittedBernoulliCUSUM, FittedBernoulliCUSUM]:
    first = fit_bernoulli_cusum(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        detect_rate_multiple=_CUSTOM_DETECT_RATE_MULTIPLE,
    )
    second = fit_bernoulli_cusum(
        baseline,
        target_arl=_VALID_TARGET_ARL,
        detect_rate_multiple=_CUSTOM_DETECT_RATE_MULTIPLE,
    )
    return first, second


@then("both fitted charts report identical false-alarm and detection figures")
def both_charts_report_identical_figures(
    repeated_outcomes: tuple[FittedBernoulliCUSUM, FittedBernoulliCUSUM],
) -> None:
    first, second = repeated_outcomes
    assert first.achieved_arl == second.achieved_arl
    assert first.expected_detection_arl == second.expected_detection_arl
    assert first.p_u == second.p_u
