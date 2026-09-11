"""Unit tests for ``Monitor.history``/``Monitor.clear_history()`` (BIN-72).

Pins the nine acceptance scenarios in
``tests/bdd/features/monitoring/in-memory-observation-store.feature`` at the
unit level. See ``docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md``
section 6-7 and ``docs/domain-model.md`` Object Map -- Monitor.

``Monitor``/``MonitoringResult`` do not exist yet -- importing them from
``caliper.monitoring`` fails until ``domain-implementer`` adds
``src/caliper/monitoring/``. That ``ImportError`` is the correct red state
for this ticket (TDD red phase).

**Decisions this file makes, flagged rather than guessed silently:**

1. **"Does not carry over between runs" (BR-5) is tested as "a second,
   independently-constructed `Monitor` starts empty even though a first
   `Monitor` already has history."** There is no real process boundary to
   cross inside a test process (``docs/domain-model.md``'s own glossary
   entry for "Session" makes this explicit: "not a domain type... a new
   process constructing a new `Monitor` starts with empty history by
   construction"), so this is the faithful in-process analogue, not a
   weakening of the scenario.
2. **Immutability of a recorded entry is tested at two levels**: the
   returned ``.history`` tuple itself cannot be mutated in place (no
   ``append``/item-assignment), and a second ``.history`` call after a
   failed mutation attempt still shows the original entries unchanged.
3. **No test in this file exercises OQ-2 (a bounding/eviction mechanism)**
   -- ADR-009 section 7 explicitly ships none in R1 (``clear_history()`` is
   the only escape hatch). Asserting the *absence* of a bounding mechanism
   would pin something the ADR deliberately left unbuilt as though it were
   a contract; this file tests only what ships (`retain_history=False`,
   `clear_history()`).

Uses the same helper shape (`_result`, `_fitted_shewhart`) as
``tests/unit/monitoring/test_monitor.py`` and
``tests/unit/baseline/test_compare_provenance.py``, duplicated here rather
than imported -- mirrors this codebase's established convention of each
test file owning its own literal-construction helpers.
"""

from __future__ import annotations

import pytest

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedShewhart,
    fit_shewhart,
)
from caliper.errors import InvalidObservationError, ProvenanceMismatchError
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from caliper.monitoring import Monitor, MonitoringResult
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
    """Build a ``Baseline`` of ``count`` observations sharing one literal provenance."""
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


# --- Boundary: empty history -----------------------------------------------------


def test_a_new_monitor_has_an_empty_history() -> None:
    """A session with no recorded observations has an empty monitoring history."""
    # Arrange
    monitor = Monitor(_fitted_shewhart())

    # Act / Assert
    assert monitor.history == ()


def test_history_is_a_tuple() -> None:
    """`Monitor.history` is a plain tuple, not a bespoke type (ADR-009 section 6)."""
    # Arrange
    monitor = Monitor(_fitted_shewhart())

    # Act / Assert
    assert isinstance(monitor.history, tuple)


# --- Boundary: a single recorded observation -------------------------------------


def test_a_single_recorded_observation_is_the_entirety_of_history() -> None:
    """A single recorded observation appears in the session's monitoring history."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    observation = _result(score=artefact.baseline_mean)

    # Act
    monitor.record(observation)

    # Assert
    assert len(monitor.history) == 1
    assert monitor.history[0].observation == observation


# --- Happy path: ordered review ---------------------------------------------------


def test_recorded_observations_appear_in_the_order_they_were_recorded() -> None:
    """The engineer reviews the observations recorded during their session, in order."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    scores = [
        artefact.baseline_mean,
        artefact.baseline_mean + 0.1 * artefact.sigma_estimate,
        artefact.baseline_mean - 0.1 * artefact.sigma_estimate,
    ]
    observations = [_result(score=score) for score in scores]

    # Act
    for observation in observations:
        monitor.record(observation)

    # Assert
    assert [entry.observation for entry in monitor.history] == observations


def test_reviewing_history_shows_each_observations_in_control_determination() -> None:
    """The engineer sees what a reviewed observation's monitoring outcome was."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    in_control_observation = _result(score=artefact.baseline_mean)
    out_of_control_observation = _result(
        score=artefact.ucl + 100.0 * artefact.sigma_estimate
    )

    # Act
    monitor.record(in_control_observation)
    monitor.record(out_of_control_observation)

    # Assert
    assert monitor.history[0].is_in_control is True
    assert monitor.history[1].is_in_control is False


# --- Edge: repeatable, non-destructive review -------------------------------------


def test_reviewing_history_repeatedly_returns_the_same_recorded_observations() -> None:
    """Reviewing history is repeatable and does not change what was recorded."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    monitor.record(_result(score=artefact.baseline_mean))
    monitor.record(
        _result(score=artefact.baseline_mean + 0.1 * artefact.sigma_estimate)
    )

    # Act
    first_read = monitor.history
    second_read = monitor.history

    # Assert
    assert first_read == second_read


# --- Sad path: immutability --------------------------------------------------------


def test_a_recorded_entry_cannot_be_altered_after_the_fact() -> None:
    """A recorded observation in monitoring history cannot be altered after the fact."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    monitor.record(_result(score=artefact.baseline_mean))
    original = monitor.history

    # Act -- a tuple has no in-place mutation method
    with pytest.raises(AttributeError):
        monitor.history.append(  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            _result(score=artefact.baseline_mean)
        )

    # Assert -- the original recorded history is unchanged
    assert monitor.history == original
    assert len(monitor.history) == 1


def test_a_history_entry_itself_is_frozen() -> None:
    """The `MonitoringResult` entries within history are immutable value objects."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    monitor.record(_result(score=artefact.baseline_mean))
    entry = monitor.history[0]

    # Act / Assert
    with pytest.raises(Exception):  # noqa: B017 -- pydantic_core.ValidationError, ADR-002 section 7
        entry.is_in_control = False  # ty: ignore[invalid-assignment]


# --- Sad path: refused attempts are not recorded ----------------------------------


def test_a_provenance_mismatch_refusal_does_not_appear_in_history() -> None:
    """An observation refused for provenance mismatch leaves no trace in history."""
    # Arrange
    artefact = _fitted_shewhart(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    monitor = Monitor(artefact)
    mismatched = _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)

    # Act
    with pytest.raises(ProvenanceMismatchError):
        monitor.record(mismatched)

    # Assert
    assert monitor.history == ()


def test_an_invalid_observation_refusal_does_not_appear_in_history() -> None:
    """An observation Phase II recording refused (incomplete input) leaves no trace."""
    # Arrange
    monitor = Monitor(_fitted_shewhart())

    # Act
    with pytest.raises(InvalidObservationError):
        monitor.record(None)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    assert monitor.history == ()


# --- Sad path: does not overlap with Phase I's Baseline ---------------------------


def test_phase_i_baseline_observations_do_not_appear_in_monitor_history() -> None:
    """This store is not a second `Baseline` -- Phase I and Phase II never mix."""
    # Arrange
    artefact = _fitted_shewhart()
    baseline = Baseline()
    baseline.record(_result(score=artefact.baseline_mean))
    monitor = Monitor(artefact)
    phase_ii_observation = _result(score=artefact.baseline_mean)

    # Act
    monitor.record(phase_ii_observation)

    # Assert
    assert len(monitor.history) == 1
    assert all(isinstance(entry, MonitoringResult) for entry in monitor.history)
    assert baseline.observation_count == 1


# --- Session lifetime (BR-5) --------------------------------------------------------


def test_a_new_monitor_instance_does_not_carry_over_a_prior_monitors_history() -> None:
    """Monitoring history does not carry over between separate runs of the program.

    There is no real process boundary inside a test -- see file docstring
    point 1. A second, independently-constructed `Monitor` starting empty
    while a first `Monitor` (built from the same artefact) already has
    history is the faithful in-process analogue.
    """
    # Arrange
    artefact = _fitted_shewhart()
    first_run_monitor = Monitor(artefact)
    first_run_monitor.record(_result(score=artefact.baseline_mean))
    first_run_monitor.record(_result(score=artefact.baseline_mean))

    # Act -- a new "run" constructs a fresh Monitor from the same artefact
    new_run_monitor = Monitor(artefact)

    # Assert
    assert new_run_monitor.history == ()
    assert len(first_run_monitor.history) == 2


# --- Escape hatches (ADR-009 section 7) ---------------------------------------------


def test_clear_history_resets_to_empty() -> None:
    """`clear_history()` is the manual escape hatch for unbounded growth."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    monitor.record(_result(score=artefact.baseline_mean))
    monitor.record(_result(score=artefact.baseline_mean))
    assert len(monitor.history) == 2

    # Act
    monitor.clear_history()

    # Assert
    assert monitor.history == ()  # type: ignore[comparison-overlap]


def test_retain_history_false_opts_out_of_retention_entirely() -> None:
    """`retain_history=False` means nothing is retained, however much is recorded."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, retain_history=False)

    # Act
    monitor.record(_result(score=artefact.baseline_mean))
    monitor.record(_result(score=artefact.baseline_mean))

    # Assert
    assert monitor.history == ()


def test_retain_history_defaults_to_true() -> None:
    """Zero-config default: retained unless the engineer opts out (ADR-009 §7)."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)

    # Act
    monitor.record(_result(score=artefact.baseline_mean))

    # Assert
    assert len(monitor.history) == 1
