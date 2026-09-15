"""Step definitions for BIN-69: record a Phase II observation and check for a signal.

Binds to
``tests/bdd/features/monitoring/phase-ii-observation-signal-check.feature``
via ``tests/bdd/test_phase_ii_observation_signal_check.py``. Error
assertions follow ADR-002/ADR-008: type + required ``context`` keys only,
never message text.

``Monitor``/``MonitoringResult`` do not exist yet -- importing them from
``drift_caliper.monitoring`` fails until ``domain-implementer`` adds
``src/drift_caliper/monitoring/``. That ``ImportError`` is the correct red state
for this ticket (TDD red phase).

**Decisions this file makes, flagged rather than guessed silently:**

1. **The "EWMA or CUSUM" scenario binds to EWMA only.** The scenario's own
   Given step reads "the engineer has fitted an EWMA **or** CUSUM artefact"
   -- deliberately disjunctive so either chart type satisfies it (see the
   feature file's own header: "none of them names... any particular shape
   for carried-forward chart state"). EWMA's accumulation arithmetic is
   simpler to derive deterministically; CUSUM's is unit-tested separately
   in ``tests/unit/monitoring/test_monitor.py``
   (``test_cusum_accumulates_evidence_across_a_sustained_small_shift``), so
   the accumulation *contract* is covered for both chart types even though
   only one is exercised at the BDD layer.
2. **Every fitted artefact used here is EWMA** (``_fitted_ewma()``), even
   for scenarios that only need a boundary-based in-control/out-of-control
   determination (SC1, SC2, SC6-SC8) -- mirrors
   ``tests/bdd/steps/provenance_mismatch_between_phases_steps.py``'s own
   default choice of artefact for chart-type-agnostic scenarios, and gives
   every scenario access to ``ucl``/``lcl``/``baseline_mean`` uniformly
   (``FittedCUSUM`` has no such fields -- see ADR-004 section 3). SC4
   (memorylessness) and SC9 (uniformity across chart types) explicitly
   need Shewhart/all three chart types respectively, and use their own
   dedicated artefacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from pytest_bdd import given, then, when

from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedEWMA,
    FittedShewhart,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from drift_caliper.errors import (
    CaliperError,
    InvalidObservationError,
    ProvenanceMismatchError,
)
from drift_caliper.measurement import (
    ModelVersion,
    Provenance,
    ScoringCriteria,
    ScoringResult,
)
from drift_caliper.monitoring import Monitor, MonitoringResult
from tests.factories import ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."
_DIFFERENT_MODEL_VERSION = "claude-opus-4-5-20260101"

# Arbitrary, sufficiently-large target ARL0 -- carries no statistical
# meaning here, matching every sibling fitting test/step file's own
# `_SHAPE_TEST_TARGET_ARL`.
_SHAPE_TEST_TARGET_ARL = 370.0

# Explicit smoothing_param giving a comfortable, deterministic margin for
# both the boundary-based single-shot scenarios (huge breach clears the
# limit regardless of lambda's exact value) and the accumulation scenario
# (see ``_ewma_first_call_in_control_shift``'s derivation in
# ``tests/unit/monitoring/test_monitor.py``, which this file mirrors).
_SMOOTHING_PARAM = 0.3

# Generous cap on repeated recordings while waiting for the accumulating
# chart to signal -- see ``tests/unit/monitoring/test_monitor.py``'s
# identical constant and its derivation comment.
_MAX_ACCUMULATION_ITERATIONS = 200


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
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA, count: int
) -> Baseline:
    baseline = Baseline()
    provenance = Provenance(
        model_version=ModelVersion(value=model_version),
        scoring_criteria=ScoringCriteria(value=criteria),
    )
    for _ in range(count):
        baseline.record(ScoringResultFactory(provenance=provenance))
    return baseline


def _fitted_ewma(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
    smoothing_param: float = _SMOOTHING_PARAM,
) -> FittedEWMA:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_ewma(
        baseline, target_arl=_SHAPE_TEST_TARGET_ARL, smoothing_param=smoothing_param
    )


def _fitted_shewhart(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedShewhart:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _ewma_first_call_in_control_shift(
    artefact: FittedEWMA, *, fraction: float = 0.01
) -> float:
    """See the identical helper in
    ``tests/unit/monitoring/test_monitor.py`` for the derivation.
    """
    return artefact.ucl + fraction * (artefact.ucl - artefact.baseline_mean)


@dataclass
class RecordAttempt:
    """Outcome of one ``Monitor.record()`` call -- success or a captured error."""

    outcome: MonitoringResult | None
    error: CaliperError | None
    monitor: Monitor


def _attempt_record(monitor: Monitor, observation: ScoringResult) -> RecordAttempt:
    try:
        outcome = monitor.record(observation)
    except CaliperError as exc:
        return RecordAttempt(outcome=None, error=exc, monitor=monitor)
    return RecordAttempt(outcome=outcome, error=None, monitor=monitor)


# --- Scenario: in control (SC1) / out of control (SC2) / provenance mismatch
# (SC6) / signal does not raise (SC8) -- shared "Given a fitted artefact" ------


@given(
    "the engineer has a fitted control limit artefact from a Phase I baseline",
    target_fixture="artefact",
)
def a_fitted_artefact_from_a_phase_i_baseline() -> FittedEWMA:
    return _fitted_ewma()


@given(
    "they have a newly scored Phase II observation that shares the artefact's "
    "measurement provenance",
    target_fixture="observation_provenance",
)
def a_matching_provenance(artefact: FittedControlLimits) -> Provenance:
    return Provenance(
        model_version=ModelVersion(value=artefact.provenance_model_version),
        scoring_criteria=ScoringCriteria(value=artefact.provenance_criteria),
    )


@given(
    "the observation's value falls within the calibrated boundaries",
    target_fixture="phase_ii_observation",
)
def observation_within_boundaries(
    artefact: FittedControlLimits, observation_provenance: Provenance
) -> ScoringResult:
    return ScoringResult(
        score=artefact.baseline_mean,
        reasoning="Accurate and concise.",
        provenance=observation_provenance,
    )


@given(
    "the observation represents a genuine departure from the process the "
    "baseline describes",
    target_fixture="phase_ii_observation",
)
def observation_breaches_boundaries(
    artefact: FittedEWMA, observation_provenance: Provenance
) -> ScoringResult:
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    return ScoringResult(
        score=breach_score,
        reasoning="Sharp regression from the baseline process.",
        provenance=observation_provenance,
    )


@given(
    "they have a newly scored Phase II observation that represents a genuine "
    "departure from the process",
    target_fixture="phase_ii_observation",
)
def a_breaching_observation_for_signal_continuity(
    artefact: FittedEWMA,
) -> ScoringResult:
    """SC8's own Given, phrased as one line rather than SC2's two-step build."""
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    return _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=breach_score,
    )


@given(
    "they have a newly scored Phase II observation produced under a different "
    "judge model version or scoring criteria than the artefact",
    target_fixture="phase_ii_observation",
)
def a_mismatched_provenance_observation(artefact: FittedControlLimits) -> ScoringResult:
    return _result(
        model_version=_DIFFERENT_MODEL_VERSION, criteria=artefact.provenance_criteria
    )


@when(
    "they record the observation against the fitted artefact",
    target_fixture="record_attempt",
)
@when(
    "they attempt to record the observation against the fitted artefact",
    target_fixture="record_attempt",
)
def record_the_observation(
    artefact: FittedControlLimits, phase_ii_observation: ScoringResult
) -> RecordAttempt:
    return _attempt_record(Monitor(artefact), phase_ii_observation)


@then("they see that the process remains in control")
def process_remains_in_control(record_attempt: RecordAttempt) -> None:
    assert record_attempt.error is None
    assert record_attempt.outcome is not None
    assert record_attempt.outcome.is_in_control is True


@then("they see that the process is now out of control")
def process_is_now_out_of_control(record_attempt: RecordAttempt) -> None:
    assert record_attempt.error is None
    assert record_attempt.outcome is not None
    assert record_attempt.outcome.is_in_control is False


@then("what they see identifies the observation that triggered it")
def identifies_the_triggering_observation(
    record_attempt: RecordAttempt, phase_ii_observation: ScoringResult
) -> None:
    assert record_attempt.outcome is not None
    assert record_attempt.outcome.observation == phase_ii_observation


@then(
    "they see the same provenance mismatch failure already established for "
    "comparing measurement systems across the Phase I to Phase II boundary"
)
def sees_the_established_provenance_mismatch_failure(
    record_attempt: RecordAttempt,
) -> None:
    assert isinstance(record_attempt.error, ProvenanceMismatchError)
    assert record_attempt.error.category == "provenance_mismatch"


@then("they do not receive an in-control or out-of-control answer for that observation")
def receives_no_determination(record_attempt: RecordAttempt) -> None:
    assert record_attempt.outcome is None


@then("they receive the out-of-control determination as a normal result of the call")
def receives_a_normal_out_of_control_result(record_attempt: RecordAttempt) -> None:
    assert record_attempt.error is None
    assert record_attempt.outcome is not None
    assert record_attempt.outcome.is_in_control is False


@then("their program continues running without an unhandled exception")
def program_continues_without_an_unhandled_exception(
    record_attempt: RecordAttempt,
) -> None:
    # If Monitor.record() had let a genuine signal raise, the When step
    # itself would already have failed this scenario -- this assertion
    # re-confirms no CaliperError was captured either (i.e. nothing was
    # silently swallowed and re-surfaced as a captured error).
    assert record_attempt.error is None


# --- Scenario: accumulation vs memorylessness (SC3, SC4) ----------------------


@dataclass
class AccumulationContext:
    """Carries a `Monitor` and the sustained shift value across Given/When steps."""

    monitor: Monitor
    shifted_score: float
    provenance: Provenance


@given(
    "the engineer has fitted an EWMA or CUSUM artefact from a Phase I baseline",
    target_fixture="artefact",
)
def a_fitted_ewma_or_cusum_artefact() -> FittedEWMA:
    """Binds to EWMA -- see file docstring decision 1."""
    return _fitted_ewma()


@given(
    "they have already recorded one or more prior Phase II observations against "
    "this artefact, each individually within the calibrated boundaries",
    target_fixture="accumulation_context",
)
def prior_in_control_observations(artefact: FittedEWMA) -> AccumulationContext:
    provenance = Provenance(
        model_version=ModelVersion(value=artefact.provenance_model_version),
        scoring_criteria=ScoringCriteria(value=artefact.provenance_criteria),
    )
    monitor = Monitor(artefact)
    shifted_score = _ewma_first_call_in_control_shift(artefact)
    prior_outcome = monitor.record(
        ScoringResult(
            score=shifted_score, reasoning="Slight uptick.", provenance=provenance
        )
    )
    assert prior_outcome.is_in_control is True
    return AccumulationContext(
        monitor=monitor, shifted_score=shifted_score, provenance=provenance
    )


@when(
    "they record a further observation continuing the same small, sustained shift",
    target_fixture="eventually_signalled",
)
def record_a_further_observation_continuing_the_shift(
    accumulation_context: AccumulationContext,
) -> bool:
    for _ in range(_MAX_ACCUMULATION_ITERATIONS):
        outcome = accumulation_context.monitor.record(
            ScoringResult(
                score=accumulation_context.shifted_score,
                reasoning="Slight uptick, continuing.",
                provenance=accumulation_context.provenance,
            )
        )
        if outcome.is_in_control is False:
            return True
    return False


@then(
    "whether the process is now out of control reflects the pattern across "
    "the recorded sequence, not the latest observation considered alone"
)
def reflects_the_accumulated_pattern(eventually_signalled: bool) -> None:
    assert eventually_signalled, (
        "expected the sustained shift to eventually signal within "
        f"{_MAX_ACCUMULATION_ITERATIONS} repeats of the same in-control-alone score"
    )


@given(
    "the engineer has fitted a Shewhart control limit artefact from a Phase I baseline",
    target_fixture="artefact",
)
def a_fitted_shewhart_artefact() -> FittedShewhart:
    return _fitted_shewhart()


@given(
    "a prior Phase II observation recorded against this artefact was reported "
    "as out of control",
    target_fixture="monitor",
)
def a_prior_out_of_control_observation(artefact: FittedShewhart) -> Monitor:
    monitor = Monitor(artefact)
    breach = _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=artefact.ucl + 100.0 * artefact.sigma_estimate,
    )
    outcome = monitor.record(breach)
    assert outcome.is_in_control is False
    return monitor


@when(
    "they record a further observation whose own value falls within the "
    "calibrated boundaries",
    target_fixture="record_attempt",
)
def record_a_further_in_control_observation(
    monitor: Monitor, artefact: FittedShewhart
) -> RecordAttempt:
    observation = _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=artefact.baseline_mean,
    )
    return _attempt_record(monitor, observation)


@then(
    "they see that this observation is in control, regardless of the prior "
    "observation's outcome"
)
def sees_in_control_regardless_of_prior_outcome(record_attempt: RecordAttempt) -> None:
    assert record_attempt.error is None
    assert record_attempt.outcome is not None
    assert record_attempt.outcome.is_in_control is True


# --- Scenario: first observation needs no prior history (SC5) -----------------


@given(
    "the engineer has just fitted control limits and has not yet recorded any "
    "Phase II observations",
    target_fixture="artefact",
)
def a_freshly_fitted_artefact() -> FittedEWMA:
    return _fitted_ewma()


@when("they record their first production observation", target_fixture="record_attempt")
def record_the_first_production_observation(artefact: FittedEWMA) -> RecordAttempt:
    observation = _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=artefact.baseline_mean,
    )
    return _attempt_record(Monitor(artefact), observation)


@then(
    "they see whether that single observation is in control, without needing "
    "any other observation to have been recorded first"
)
def sees_the_first_observations_determination(record_attempt: RecordAttempt) -> None:
    assert record_attempt.error is None
    assert record_attempt.outcome is not None
    assert isinstance(record_attempt.outcome.is_in_control, bool)


# --- Scenario: incomplete observation (SC7) ------------------------------------


@when(
    "they attempt to record something that is not a complete scored observation",
    target_fixture="record_attempt",
)
def attempt_to_record_an_incomplete_observation(
    artefact: FittedControlLimits,
) -> RecordAttempt:
    monitor = Monitor(artefact)
    try:
        monitor.record(None)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    except CaliperError as exc:
        return RecordAttempt(outcome=None, error=exc, monitor=monitor)
    raise AssertionError(
        "expected Monitor.record() to raise for an incomplete observation"
    )


@then(
    "the recording fails with an error that is programmatically classifiable, "
    "rather than being silently treated as in control"
)
def fails_with_a_classifiable_error(record_attempt: RecordAttempt) -> None:
    assert isinstance(record_attempt.error, InvalidObservationError)
    assert record_attempt.error.category == "invalid_observation"


@then("what they see identifies what was missing or invalid")
def identifies_what_was_missing_or_invalid(record_attempt: RecordAttempt) -> None:
    error = record_attempt.error
    assert isinstance(error, InvalidObservationError)
    assert isinstance(error.context["reason"], str)
    assert error.context["reason"] != ""
    assert error.context["missing_fields"]


# --- Scenario: consistency across chart types (SC9) ----------------------------


@given(
    "the engineer has fitted control limits using each of the three available "
    "chart types from the same Phase I baseline",
    target_fixture="artefacts",
)
def three_chart_types_from_the_same_baseline() -> list[FittedControlLimits]:
    baseline = _baseline_with_provenance(count=DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    return [
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
    ]


@given(
    "they have the same newly scored Phase II observation for each",
    target_fixture="phase_ii_observation",
)
def a_shared_phase_ii_observation(
    artefacts: list[FittedControlLimits],
) -> ScoringResult:
    reference = artefacts[0]
    return _result(
        model_version=reference.provenance_model_version,
        criteria=reference.provenance_criteria,
        score=reference.baseline_mean,
    )


@when(
    "they record that observation against each fitted artefact in turn",
    target_fixture="record_attempts",
)
def record_against_each_fitted_artefact(
    artefacts: list[FittedControlLimits], phase_ii_observation: ScoringResult
) -> list[RecordAttempt]:
    return [
        _attempt_record(Monitor(artefact), phase_ii_observation)
        for artefact in artefacts
    ]


@then("in every case they can determine whether the process is in control")
def can_determine_in_every_case(record_attempts: list[RecordAttempt]) -> None:
    for attempt in record_attempts:
        assert attempt.error is None
        assert attempt.outcome is not None
        assert isinstance(attempt.outcome.is_in_control, bool)
