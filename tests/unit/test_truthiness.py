"""Truthiness contract for Caliper's result and fitted-artefact types (BIN-110).

## The P0 this file exists to catch

    >>> s = Baseline().check_sufficiency()   # empty baseline
    >>> s.is_sufficient
    False
    >>> bool(s)
    True                                     # object-identity truthiness

``SufficiencyResult`` is a frozen Pydantic ``BaseModel`` with no
``__bool__`` -- Python falls back to ``object.__bool__``, which is
unconditionally ``True`` for any object. So this fits control limits from
an empty baseline, silently:

    if baseline.check_sufficiency():
        fit_ewma(baseline, target_arl=370)

``fit_ewma`` enforces sufficiency internally and does raise
``InsufficientBaselineError`` -- but only after the engineer's own guard
clause has already told them it was safe to call it. See ``CLAUDE.md``
("Developer experience is a first-class constraint") and ``BIN-110``.

## The general ruling this file pins

``BIN-110`` delegates a design decision: should truthiness be *meaningful*
on every public result type, or *forbidden* where it has no obvious
meaning? This file rules **forbidden by default, meaningful only where a
field already carries an unambiguous yes/no semantic**:

- ``SufficiencyResult`` gets a real ``__bool__`` mirroring
  ``is_sufficient`` -- the type already *is* a yes/no answer to "is this
  baseline ready?", so ``bool(result)`` disagreeing with
  ``result.is_sufficient`` would itself be a footgun.
- ``ScoringResult``, ``FittedEWMA``, ``FittedCUSUM`` and ``FittedShewhart``
  have no such field -- there is no "unsuccessful" ``ScoringResult`` or
  "unfitted" ``FittedEWMA``; if an engineer holds one, the operation that
  produced it already succeeded (or raised on the way there). These four
  **forbid** ``bool()`` outright, raising ``TypeError``, rather than
  leaving Pydantic's silent always-``True`` default in place. A
  ``TypeError`` at the first place an engineer writes
  ``if scoring_result:`` is loud and immediate; the always-``True``
  default is exactly the trap this file's P0 test reproduces --
  inheriting it on four more types would just relocate the same defect
  rather than fix its cause.

Choosing "forbidden" over inventing a meaning (e.g. "truthy if
``score > 0``") also protects the project's integrity rule: SPC results
and fitted artefacts have no correct/incorrect notion of "worked" separate
from raising -- manufacturing one for ``bool()`` would be exactly the kind
of hand-waved statistical meaning ADR-001 forbids elsewhere.

``Baseline`` is deliberately out of scope here -- it is a genuine mutable
*collection*, so "empty is falsy" (the natural consequence of adding
``__len__``, BIN-110 P1) is the correct, unambiguous meaning, not the trap
these four immutable result/artefact types have. See
``tests/unit/baseline/test_baseline.py``.
"""

from __future__ import annotations

import pytest

from caliper.baseline import Baseline, fit_cusum, fit_ewma, fit_shewhart
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria
from caliper.monitoring import Monitor
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary target ARL0 shared by the three fit_* calls below -- a DX/shape
# concern only, no statistical claim (mirrors
# tests/unit/baseline/test_ewma_fitting.py's _SHAPE_TEST_TARGET_ARL).
_SHAPE_TEST_TARGET_ARL = 370.0

# Comfortably above DEFAULT_SUFFICIENCY_THRESHOLD (100, ADR-005) so every
# fit_* call below is unambiguously sufficient regardless of the margin
# chosen elsewhere.
_SUFFICIENT_OBSERVATION_COUNT = 105


def _sufficient_baseline() -> Baseline:
    """A baseline that is sufficient and non-degenerate, for fitting.

    Mirrors the identically-named helper in
    ``tests/unit/baseline/test_ewma_fitting.py`` -- duplicated here rather
    than imported, since this file only needs a fitted artefact to test
    ``bool()`` against, not any of that file's fitting-behaviour setup.
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(_SUFFICIENT_OBSERVATION_COUNT):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))
    return baseline


# --- P0: the exact reproduction from BIN-110 ----------------------------------


def test_empty_baseline_sufficiency_result_is_falsy() -> None:
    """The literal BIN-110 P0 repro: an empty baseline's result must be falsy."""
    # Arrange
    baseline = Baseline()

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.is_sufficient is False
    assert bool(result) is False
    assert not result


def test_sufficient_baseline_result_is_truthy() -> None:
    """The positive partition: a sufficient result must be truthy."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = baseline.check_sufficiency()

    # Assert
    assert result.is_sufficient is True
    assert bool(result) is True
    assert result


def test_guard_clause_on_an_empty_baseline_does_not_enter_the_fitting_branch() -> None:
    """The exact engineer-written guard from BIN-110 must actually guard.

    Reproduces the failure mode end-to-end rather than only at the
    ``bool()`` unit level: an engineer writes the natural guard clause
    around a fitting call, and it must not let fitting be attempted on an
    empty baseline.
    """
    # Arrange
    baseline = Baseline()
    fitting_was_attempted = False

    # Act -- the exact shape of code BIN-110 quotes an engineer typing
    if baseline.check_sufficiency():
        fitting_was_attempted = True
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert fitting_was_attempted is False


@pytest.mark.parametrize(
    ("count", "threshold"),
    [(0, 100), (99, 100), (100, 100), (101, 100), (1, 1)],
    ids=["empty", "one_short", "at_threshold", "one_over", "threshold_of_one"],
)
def test_bool_matches_is_sufficient_for_every_combination(
    count: int, threshold: int
) -> None:
    """``bool(result)`` must never disagree with ``result.is_sufficient``."""
    # Arrange
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(count):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))

    # Act
    result = baseline.check_sufficiency(threshold=threshold)

    # Assert
    assert bool(result) == result.is_sufficient


# --- The general ruling: forbidden where there is no yes/no field ------------


def test_bool_is_forbidden_on_scoring_result() -> None:
    """``ScoringResult`` has no success/failure field -- ``bool()`` must raise."""
    # Arrange
    result = ScoringResultFactory()

    # Act / Assert
    with pytest.raises(TypeError):
        bool(result)


def test_bool_is_forbidden_on_fitted_ewma() -> None:
    """A ``FittedEWMA`` that exists already succeeded -- ``bool()`` must raise."""
    # Arrange
    fitted = fit_ewma(_sufficient_baseline(), target_arl=_SHAPE_TEST_TARGET_ARL)

    # Act / Assert
    with pytest.raises(TypeError):
        bool(fitted)


def test_bool_is_forbidden_on_fitted_cusum() -> None:
    # Arrange
    fitted = fit_cusum(_sufficient_baseline(), target_arl=_SHAPE_TEST_TARGET_ARL)

    # Act / Assert
    with pytest.raises(TypeError):
        bool(fitted)


def test_bool_is_forbidden_on_fitted_shewhart() -> None:
    # Arrange
    fitted = fit_shewhart(_sufficient_baseline(), target_arl=_SHAPE_TEST_TARGET_ARL)

    # Act / Assert
    with pytest.raises(TypeError):
        bool(fitted)


# --- MonitoringResult (BIN-69, ADR-009 section 4) -----------------------------
#
# `MonitoringResult` *does* have an explicit yes/no field (`is_in_control`),
# unlike the four types above -- but `__bool__` still raises. This is not an
# inconsistency: it is domain-modeller's explicit, engaged-with-both-options
# decision (docs/domain-model.md, Value Object Inventory -- MonitoringResult,
# "Truthiness decision"), because "is everything still fine?" and "did
# something notable just happen?" are opposite readings of
# `if monitor.record(observation):`, and the field name only disambiguates
# one of them. Returning `is_in_control` from `__bool__` would risk a
# **silently inverted** monitoring loop -- alerting on the boring in-control
# majority and staying quiet on genuine signals -- which is worse than the
# always-`True` P0 this file's other tests catch, because it does not look
# broken. See CLAUDE.md's "🚨 `MonitoringResult.__bool__` raises `TypeError`"
# note for the full reasoning this test pins.


def test_bool_is_forbidden_on_monitoring_result() -> None:
    """`MonitoringResult` has an explicit `is_in_control` field -- `bool()` raises.

    Obtained via `Monitor.record()`, never constructed directly, mirroring
    the convention every other result/artefact type in this file follows.
    """
    # Arrange
    fitted = fit_shewhart(_sufficient_baseline(), target_arl=_SHAPE_TEST_TARGET_ARL)
    monitor = Monitor(fitted)
    matching_provenance = Provenance(
        model_version=ModelVersion(value=fitted.provenance_model_version),
        scoring_criteria=ScoringCriteria(value=fitted.provenance_criteria),
    )
    observation = ScoringResultFactory(provenance=matching_provenance)

    # Act
    result = monitor.record(observation)

    # Assert
    with pytest.raises(TypeError):
        bool(result)
