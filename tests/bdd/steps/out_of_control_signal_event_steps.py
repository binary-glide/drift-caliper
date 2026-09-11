"""Step definitions for BIN-75: signal content and delivery.

Binds to
``tests/bdd/features/monitoring/out-of-control-signal-event.feature`` via
``tests/bdd/test_out_of_control_signal_event.py``, the same shape every
other feature file in this repo uses (see
``tests/bdd/test_phase_ii_observation_signal_check.py``).

A prior pass flagged a Gherkin syntax defect in the feature file (the last
scenario's step wrapped its text onto a second, un-keyworded physical
line, which is not valid Gherkin and broke collection for all nine
scenarios in the file, not only the affected one -- verified directly
with ``pytest_bdd.parser.FeatureParser``). That defect was the
coordinator's own and has since been fixed (commit ``a686f63``); the file
now parses cleanly and all nine scenarios collect and bind against the
step definitions below with no missing-step error.

Error assertions follow ADR-002/ADR-008: type + required ``context`` keys
only, never message text. Mirrors
``tests/bdd/steps/phase_ii_observation_signal_check_steps.py``'s own
fixture-override conventions (a base ``artefact`` fixture, overridden per
scenario by whichever ``Given`` step establishes one).

``Monitor(..., receivers=...)``/``MonitoringResult.direction`` etc. do not
exist yet -- importing them fails until ``domain-implementer`` extends
``src/caliper/monitoring/``. That ``ImportError`` is the correct red state
for this ticket.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from pytest_bdd import given, then, when

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedShewhart,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from caliper.monitoring import Monitor, MonitoringResult
from tests.factories import ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."

# Arbitrary, sufficiently-large target ARL0 -- carries no statistical
# meaning here, matching every sibling fitting test/step file's own
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


def _fitted_shewhart(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedShewhart:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


class _FailingReceiver:
    """A receiver that always raises when notified -- SC9's "will fail" receiver."""

    def __call__(self, result: MonitoringResult) -> None:
        raise RuntimeError("receiver exploded")


@dataclass
class DeliveryLog:
    """Captures everything delivered to the engineer's own receiver, in
    order -- the test double for "being told" independently of the
    recording call's own return value."""

    delivered: list[MonitoringResult] = field(default_factory=list)


@dataclass
class RecordResult:
    """Outcome of one ``Monitor.record()`` call, plus a flag proving the
    call returned control to the caller (SC8's "program continues")."""

    outcome: MonitoringResult
    program_continued: bool


# --- Base fixtures, overridden per scenario by the Given steps below -------------


@pytest.fixture
def artefact() -> FittedShewhart:
    """Default fitted artefact -- overridden by scenario-specific Given
    steps that need one with different properties."""
    return _fitted_shewhart()


@pytest.fixture
def delivery_log() -> DeliveryLog:
    """Default: nothing delivered -- overridden implicitly whenever a Given
    step below arranges a receiver that appends into this."""
    return DeliveryLog()


@pytest.fixture
def receivers(delivery_log: DeliveryLog) -> list[Callable[[MonitoringResult], None]]:
    """Default: no receivers configured -- overridden by the "arranged to
    be told" Given steps below."""
    return []


@pytest.fixture
def monitor(
    artefact: FittedShewhart,
    receivers: list[Callable[[MonitoringResult], None]],
) -> Monitor:
    return Monitor(artefact, receivers=receivers)


# --- Given: establishing a fitted artefact (SC1, SC2, SC8) ------------------------


@given(
    "the engineer has fitted control limits and is recording Phase II observations "
    "against them",
    target_fixture="artefact",
)
def fitted_control_limits_and_recording() -> FittedShewhart:
    return _fitted_shewhart()


@given(
    "the engineer has not arranged to be told about signals through any other means",
    target_fixture="artefact",
)
def not_arranged_to_be_told() -> FittedShewhart:
    return _fitted_shewhart()


# --- Given: the observation (breaching or in-control) -----------------------------


@given(
    "a newly recorded observation represents a genuine departure from the process "
    "the baseline describes",
    target_fixture="phase_ii_observation",
)
def a_breaching_observation(artefact: FittedShewhart) -> ScoringResult:
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    return _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=breach_score,
    )


@given(
    "a newly recorded observation's value falls within the calibrated boundaries",
    target_fixture="phase_ii_observation",
)
def an_in_control_observation(artefact: FittedShewhart) -> ScoringResult:
    return _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=artefact.baseline_mean,
    )


# --- Given: arranging to be told (SC4, SC5, SC6) -----------------------------------


@given(
    "the engineer has arranged to be told when a signal occurs",
    target_fixture="receivers",
)
def arranged_to_be_told(
    delivery_log: DeliveryLog,
) -> list[Callable[[MonitoringResult], None]]:
    return [delivery_log.delivered.append]


@given(
    "the engineer has arranged to be told about signals through a receiver that "
    "will fail when it is notified",
    target_fixture="receivers",
)
def arranged_with_a_failing_receiver() -> list[Callable[[MonitoringResult], None]]:
    return [_FailingReceiver()]


# --- When: the shared single-observation recording step ---------------------------


@when("they record that observation", target_fixture="record_result")
def record_the_observation(
    monitor: Monitor, phase_ii_observation: ScoringResult
) -> RecordResult:
    outcome = monitor.record(phase_ii_observation)
    return RecordResult(outcome=outcome, program_continued=True)


# --- Then: SC1 -- direction, boundaries, observation -------------------------------


@then("the resulting signal identifies the direction the process departed in")
def signal_identifies_direction(record_result: RecordResult) -> None:
    assert record_result.outcome.direction in ("upper", "lower")


@then(
    "it identifies the calibrated boundaries that were in force when the departure "
    "was detected"
)
def signal_identifies_calibrated_boundaries(
    record_result: RecordResult, artefact: FittedShewhart
) -> None:
    assert record_result.outcome.fitted_artefact is artefact


@then("it identifies the observation that triggered it")
def signal_identifies_the_observation(
    record_result: RecordResult, phase_ii_observation: ScoringResult
) -> None:
    assert record_result.outcome.observation == phase_ii_observation


# --- Then: SC2 -- no signal for a routine observation -------------------------------


@then("no signal is produced for it")
def no_signal_is_produced(record_result: RecordResult) -> None:
    assert record_result.outcome.is_in_control is True
    assert record_result.outcome.direction is None


# --- Scenario: SC3 -- consistent form across chart types ---------------------------


@given(
    "the engineer has fitted control limits using each of the three available chart "
    "types from the same Phase I baseline",
    target_fixture="artefacts",
)
def three_chart_types_from_the_same_baseline() -> list[FittedControlLimits]:
    baseline = _baseline_with_provenance(count=DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    return [
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL, smoothing_param=1.0),
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
    ]


@given(
    "they have a departing observation that triggers a signal under each fitted "
    "artefact in turn",
    target_fixture="phase_ii_observation",
)
def a_departing_observation_for_every_chart_type(
    artefacts: list[FittedControlLimits],
) -> ScoringResult:
    reference = artefacts[0]
    breach_score = reference.baseline_mean + 1000.0 * reference.sigma_estimate
    return _result(
        model_version=reference.provenance_model_version,
        criteria=reference.provenance_criteria,
        score=breach_score,
    )


@when(
    "they record that observation against each fitted artefact",
    target_fixture="record_results",
)
def record_against_each_fitted_artefact(
    artefacts: list[FittedControlLimits], phase_ii_observation: ScoringResult
) -> list[MonitoringResult]:
    outcomes = []
    for artefact_under_test in artefacts:
        monitor_for_artefact = Monitor(artefact_under_test)
        outcome = monitor_for_artefact.record(phase_ii_observation)
        assert outcome.is_in_control is False, (
            "expected the shared departing observation to signal under "
            f"{artefact_under_test.chart_type!r}"
        )
        outcomes.append(outcome)
    return outcomes


@then(
    "each resulting signal identifies its own direction and its own chart's "
    "calibrated boundaries, in the same form regardless of which chart type "
    "produced it"
)
def each_signal_identifies_its_own_content(
    record_results: list[MonitoringResult], artefacts: list[FittedControlLimits]
) -> None:
    for outcome, artefact_under_test in zip(record_results, artefacts, strict=True):
        assert outcome.direction in ("upper", "lower")
        assert outcome.fitted_artefact is artefact_under_test


# --- Then: SC4 -- told about the signal without polling -----------------------------


@then(
    "they are told about the signal without needing to separately inspect the "
    "outcome of that recording call"
)
def told_about_the_signal_without_inspecting_the_result(
    delivery_log: DeliveryLog, record_result: RecordResult
) -> None:
    assert delivery_log.delivered == [record_result.outcome]


# --- Then: SC5 -- not told for routine observations ----------------------------------


@then("they are not told anything for it")
def not_told_anything_for_it(delivery_log: DeliveryLog) -> None:
    assert delivery_log.delivered == []


# --- Scenario: SC6 -- multiple signals delivered, in order ---------------------------


@given(
    "they record more than one observation that each represents a genuine "
    "departure from the process",
    target_fixture="phase_ii_observations",
)
def multiple_breaching_observations(
    artefact: FittedShewhart,
) -> list[ScoringResult]:
    breach_scores = [
        artefact.ucl + 10.0 * artefact.sigma_estimate,
        artefact.ucl + 20.0 * artefact.sigma_estimate,
        artefact.lcl - 10.0 * artefact.sigma_estimate,
    ]
    return [
        _result(
            model_version=artefact.provenance_model_version,
            criteria=artefact.provenance_criteria,
            score=score,
        )
        for score in breach_scores
    ]


@when(
    "those observations are recorded, one after another",
    target_fixture="record_results",
)
def record_observations_in_sequence(
    monitor: Monitor, phase_ii_observations: list[ScoringResult]
) -> list[MonitoringResult]:
    return [monitor.record(observation) for observation in phase_ii_observations]


@then("the engineer is told about every one of them, in the order they occurred")
def told_about_every_signal_in_order(
    delivery_log: DeliveryLog, record_results: list[MonitoringResult]
) -> None:
    assert delivery_log.delivered == record_results


# --- Then: SC7 -- still gets the determination without arranging anything -----------


@then(
    "they can still learn the determination directly from that recording call's own "
    "result, exactly as before this story existed"
)
def still_learns_the_determination_from_the_result(record_result: RecordResult) -> None:
    assert record_result.outcome.is_in_control is False


# --- Then: SC8 -- completes and returns normally -------------------------------------


@then("the recording call completes and returns the signal as a normal result")
def recording_call_completes_and_returns_signal(record_result: RecordResult) -> None:
    assert record_result.outcome.is_in_control is False


@then("their program continues running without an unhandled exception")
def program_continues_running(record_result: RecordResult) -> None:
    assert record_result.program_continued is True


# --- Then: SC9 -- absorb, but surface -------------------------------------------------


@then(
    "the recording call still completes and returns the signal determination as normal"
)
def recording_call_still_completes(record_result: RecordResult) -> None:
    assert record_result.outcome.is_in_control is False


@then(
    "the engineer can determine, through Caliper's public interface, both that "
    "delivery to that receiver failed and why"
)
def engineer_can_determine_delivery_failed_and_why(record_result: RecordResult) -> None:
    assert len(record_result.outcome.delivery_failures) == 1
    failure = record_result.outcome.delivery_failures[0]
    assert isinstance(failure.error_type, str)
    assert failure.error_type != ""
    assert isinstance(failure.error_message, str)
    assert failure.error_message != ""


@then("that information does not depend on the receiver mechanism that just failed")
def information_does_not_depend_on_the_receiver_mechanism(
    record_result: RecordResult,
) -> None:
    """The failure is populated by `Monitor` itself (a public field on the
    result), never by asking the failed receiver to report on itself --
    the unit-level version of this assertion
    (``tests/unit/monitoring/test_signal_delivery.py``'s
    ``test_delivery_failure_content_comes_from_monitors_own_exception_handling_not_the_receiver``)
    is what actually proves this; this step confirms the public carrier
    exists and was populated.
    """
    failure = record_result.outcome.delivery_failures[0]
    assert failure.receiver != ""
