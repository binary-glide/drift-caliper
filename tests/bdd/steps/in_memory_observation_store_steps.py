"""Step definitions for BIN-72: persist Phase II observations to an in-memory store.

Binds to
``tests/bdd/features/monitoring/in-memory-observation-store.feature`` via
``tests/bdd/test_in_memory_observation_store.py``. Error assertions follow
ADR-002/ADR-008: type + required ``context`` keys only, never message text.

``Monitor``/``MonitoringResult`` do not exist yet -- importing them from
``drift_caliper.monitoring`` fails until ``domain-implementer`` adds
``src/drift_caliper/monitoring/``. That ``ImportError`` is the correct red state
for this ticket (TDD red phase).

**Decision this file makes, flagged rather than guessed silently:**

"Does not carry over between separate runs of the engineer's program" (SC5)
is bound as: a **second, independently-constructed `Monitor`** built from
the same fitted artefact starts with empty history, even though a first
`Monitor` (standing in for "the previous run") already has recorded
observations. There is no real process boundary to cross inside a test
process -- ``docs/domain-model.md``'s own glossary entry for "Session"
makes this explicit ("a new process constructing a new `Monitor` starts
with empty history by construction"), so this is the faithful in-process
analogue of the scenario, not a weakening of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from pytest_bdd import given, then, when

from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedShewhart,
    fit_shewhart,
)
from drift_caliper.errors import ProvenanceMismatchError
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


@dataclass
class MonitoringSession:
    """A `Monitor` plus the exact `ScoringResult`s recorded into it, in order.

    The recorded list lets `Then` steps assert against the exact objects
    passed to `record()` -- e.g. ordering -- without re-deriving them from
    `.history`, which would make the assertion trivially circular.
    """

    monitor: Monitor
    artefact: FittedShewhart
    recorded_observations: list[ScoringResult] = field(default_factory=list)


def _record_all(session: MonitoringSession, observations: list[ScoringResult]) -> None:
    for observation in observations:
        session.monitor.record(observation)
        session.recorded_observations.append(observation)


# --- Scenario: ordered review (SC1) / single observation (SC2) ----------------


@given(
    "the engineer has recorded more than one Phase II observation during "
    "their running program",
    target_fixture="session",
)
def more_than_one_observation_recorded() -> MonitoringSession:
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    observations = [
        _result(
            model_version=artefact.provenance_model_version,
            criteria=artefact.provenance_criteria,
            score=artefact.baseline_mean + offset * artefact.sigma_estimate,
        )
        for offset in (0.0, 0.1, -0.1)
    ]
    _record_all(session, observations)
    return session


@given(
    "the engineer has recorded a single Phase II observation during their "
    "running program",
    target_fixture="session",
)
def a_single_observation_recorded() -> MonitoringSession:
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    _record_all(
        session,
        [
            _result(
                model_version=artefact.provenance_model_version,
                criteria=artefact.provenance_criteria,
                score=artefact.baseline_mean,
            )
        ],
    )
    return session


@when("they review their session's monitoring history", target_fixture="history")
def review_session_history(session: MonitoringSession) -> tuple[MonitoringResult, ...]:
    return session.monitor.history


@then("they see the observations in the order they were recorded")
def sees_observations_in_recorded_order(
    history: tuple[MonitoringResult, ...], session: MonitoringSession
) -> None:
    assert [entry.observation for entry in history] == session.recorded_observations


@then("they see that one observation as the entirety of their recorded history")
def sees_one_observation_as_entire_history(
    history: tuple[MonitoringResult, ...], session: MonitoringSession
) -> None:
    assert len(history) == 1
    assert history[0].observation == session.recorded_observations[0]


# --- Scenario: outcome visible alongside observation (SC3) --------------------


@given(
    "the engineer has recorded a Phase II observation that was checked "
    "against fitted control limits",
    target_fixture="session",
)
def a_checked_observation() -> MonitoringSession:
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    breach = _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=artefact.ucl + 100.0 * artefact.sigma_estimate,
    )
    _record_all(session, [breach])
    return session


@when(
    "they review that observation in their session's monitoring history",
    target_fixture="history",
)
def review_that_observation_in_history(
    session: MonitoringSession,
) -> tuple[MonitoringResult, ...]:
    return session.monitor.history


@then(
    "they can see whether it was in control or out of control at the time it "
    "was recorded"
)
def can_see_the_recorded_determination(history: tuple[MonitoringResult, ...]) -> None:
    assert len(history) == 1
    assert isinstance(history[0].is_in_control, bool)


# --- Scenario: empty history (SC4) ---------------------------------------------


@given(
    "the engineer has not yet recorded any Phase II observations in their "
    "running program",
    target_fixture="session",
)
def no_observations_recorded_yet() -> MonitoringSession:
    artefact = _fitted_shewhart()
    return MonitoringSession(monitor=Monitor(artefact), artefact=artefact)


@then("they see that no observations have been recorded yet")
def sees_no_observations_recorded_yet(history: tuple[MonitoringResult, ...]) -> None:
    assert history == ()


# --- Scenario: session lifetime (SC5) -------------------------------------------


@given(
    "the engineer recorded Phase II observations during a previous run of "
    "their program",
    target_fixture="session",
)
def observations_recorded_in_a_previous_run() -> MonitoringSession:
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    _record_all(
        session,
        [
            _result(
                model_version=artefact.provenance_model_version,
                criteria=artefact.provenance_criteria,
                score=artefact.baseline_mean,
            )
        ],
    )
    return session


@when(
    "they start a new run and review their session's monitoring history",
    target_fixture="history",
)
def start_a_new_run_and_review_history(
    session: MonitoringSession,
) -> tuple[MonitoringResult, ...]:
    """A fresh `Monitor` from the same artefact stands in for "a new run"

    -- see file docstring's decision note.
    """
    new_run_monitor = Monitor(session.artefact)
    return new_run_monitor.history


@then("they see no observations from the previous run")
def sees_no_observations_from_the_previous_run(
    history: tuple[MonitoringResult, ...],
) -> None:
    assert history == ()


# --- Scenario: repeatable, non-destructive review (SC6) ------------------------


@given(
    "the engineer has recorded Phase II observations during their session",
    target_fixture="session",
)
def observations_recorded_during_the_session() -> MonitoringSession:
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    observations = [
        _result(
            model_version=artefact.provenance_model_version,
            criteria=artefact.provenance_criteria,
            score=artefact.baseline_mean + offset * artefact.sigma_estimate,
        )
        for offset in (0.0, 0.1)
    ]
    _record_all(session, observations)
    return session


@when(
    "they review their session's monitoring history more than once",
    target_fixture="history_reads",
)
def review_history_more_than_once(
    session: MonitoringSession,
) -> tuple[tuple[MonitoringResult, ...], tuple[MonitoringResult, ...]]:
    return (session.monitor.history, session.monitor.history)


@then("each review shows the same recorded observations in the same order")
def each_review_shows_the_same_recorded_observations(
    history_reads: tuple[tuple[MonitoringResult, ...], tuple[MonitoringResult, ...]],
) -> None:
    first_read, second_read = history_reads
    assert first_read == second_read


# --- Scenario: immutability (SC7) -----------------------------------------------


@given(
    "the engineer has recorded a Phase II observation into their session's "
    "monitoring history",
    target_fixture="session",
)
def an_observation_recorded_into_history() -> MonitoringSession:
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    _record_all(
        session,
        [
            _result(
                model_version=artefact.provenance_model_version,
                criteria=artefact.provenance_criteria,
                score=artefact.baseline_mean,
            )
        ],
    )
    return session


@when(
    "they attempt to change that recorded observation",
    target_fixture="mutation_attempt",
)
def attempt_to_change_a_recorded_observation(session: MonitoringSession) -> Exception:
    entry = session.monitor.history[0]
    try:
        entry.is_in_control = not entry.is_in_control  # ty: ignore[invalid-assignment]
    except Exception as exc:
        return exc
    raise AssertionError("expected mutating a recorded MonitoringResult to fail")


@then("the attempt does not succeed and the original observation is unchanged")
def the_attempt_fails_and_the_original_is_unchanged(
    mutation_attempt: Exception, session: MonitoringSession
) -> None:
    assert isinstance(mutation_attempt, Exception)
    assert len(session.monitor.history) == 1
    assert session.monitor.history[0].observation == session.recorded_observations[0]


# --- Scenario: refused attempts are not recorded (SC8) -------------------------


@given(
    "the engineer attempted to record a Phase II observation that Phase II "
    "recording refused, for example because of a measurement provenance "
    "mismatch",
    target_fixture="session",
)
def a_refused_recording_attempt() -> MonitoringSession:
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    mismatched = _result(
        model_version=_DIFFERENT_MODEL_VERSION, criteria=artefact.provenance_criteria
    )
    with pytest.raises(ProvenanceMismatchError):
        session.monitor.record(mismatched)
    return session


@then("the refused attempt does not appear among the recorded observations")
def the_refused_attempt_does_not_appear(history: tuple[MonitoringResult, ...]) -> None:
    assert history == ()


# --- Scenario: does not overlap with Phase I's Baseline (SC9) ------------------


@given(
    "the engineer has recorded observations into a Phase I baseline during "
    "their session",
    target_fixture="phase_i_baseline",
)
def phase_i_observations_recorded() -> Baseline:
    baseline = Baseline()
    baseline.record(_result())
    baseline.record(_result())
    return baseline


@given(
    "they have also recorded Phase II observations during the same session",
    target_fixture="session",
)
def phase_ii_observations_also_recorded(
    phase_i_baseline: Baseline,
) -> MonitoringSession:
    del phase_i_baseline  # not read -- Phase I and Phase II are unrelated collections
    artefact = _fitted_shewhart()
    session = MonitoringSession(monitor=Monitor(artefact), artefact=artefact)
    _record_all(
        session,
        [
            _result(
                model_version=artefact.provenance_model_version,
                criteria=artefact.provenance_criteria,
                score=artefact.baseline_mean,
            )
        ],
    )
    return session


@then(
    "they see only the Phase II observations, and none of the Phase I "
    "baseline observations"
)
def sees_only_phase_ii_observations(
    history: tuple[MonitoringResult, ...],
    phase_i_baseline: Baseline,
    session: MonitoringSession,
) -> None:
    assert len(history) == len(session.recorded_observations)
    assert all(isinstance(entry, MonitoringResult) for entry in history)
    assert phase_i_baseline.observation_count == 2
    baseline_observation_ids = {
        id(observation) for observation in phase_i_baseline.observations
    }
    assert all(
        id(entry.observation) not in baseline_observation_ids for entry in history
    )
