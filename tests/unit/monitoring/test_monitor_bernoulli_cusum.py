"""`Monitor` extended for `FittedBernoulliCUSUM` -- ADR-014 Decision 2, domain-model.md
invariant 9.

Covers the two things
``tests/bdd/features/baseline/bernoulli-cusum-control-limit-fitting.feature``
deliberately does not: whether `Monitor` accepts a `FittedBernoulliCUSUM` at
all (widened from the three concrete continuous types, ADR-014 section 6a),
and the Phase II binary-score precondition (ADR-014 Decision 2) -- the
feature file's own "Decision made while writing these scenarios" note routes
this exact question here rather than to a scenario, applying the project's
"type-boundary defects do not need a scenario" rule.

🚨 **A consequence ADR-014/domain-model.md do not spell out, found while
verifying this file against a throwaway stub during authoring:**
`MonitoringResult.fitted_artefact`
(``src/drift_caliper/monitoring/domain/monitoring_result.py``)
is typed ``FittedControlLimits`` -- the same protocol `Monitor.__init__`'s
own parameter used to be typed before ADR-014 widened it. Since `record()`
builds `MonitoringResult(..., fitted_artefact=self._artefact)`, Pydantic's
`arbitrary_types_allowed` `isinstance` check against that Protocol rejects a
`FittedBernoulliCUSUM` there too (it satisfies only `HasProvenance`,
ADR-014 Decision 6a) -- a `pydantic_core.ValidationError` at construction,
confirmed directly by running the tests below against a real fitted chart.
**`MonitoringResult.fitted_artefact`'s type must widen alongside
`Monitor.__init__`'s artefact parameter, not only the latter** -- this file
does not assert on `MonitoringResult.fitted_artefact`'s type directly (that
would be asserting an implementation detail), but every test below that
calls `monitor.record()` against a `FittedBernoulliCUSUM` chart will fail
until this is fixed, which is the intended, correct way for this gap to
surface.
"""

from __future__ import annotations

from typing import Any

import pytest

# 🚨 Does not exist in `drift_caliper.baseline` yet -- the expected red.
from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    fit_bernoulli_cusum,
)
from drift_caliper.errors import InvalidObservationError
from drift_caliper.measurement import Provenance
from drift_caliper.monitoring import Monitor
from tests.factories import ProvenanceFactory, ScoringResultFactory

_VALID_TARGET_ARL = 370.0


def _fitted_bernoulli_chart() -> tuple[Baseline, Provenance, Any]:
    provenance = ProvenanceFactory()
    baseline = Baseline()
    count = DEFAULT_SUFFICIENCY_THRESHOLD + 5
    for i in range(count):
        score = 0.0 if i < 10 else 1.0
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))
    chart = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
    return baseline, provenance, chart


class TestMonitorAcceptsAFittedBernoulliCUSUM:
    """ADR-014 section 6a: `Monitor.__init__`'s accepted-type union widens, not
    narrows."""

    def test_construction_succeeds(self) -> None:
        _, _, chart = _fitted_bernoulli_chart()
        Monitor(chart)  # must not raise


class TestPhaseIIObservationMustBeExactlyBinary:
    """ADR-014 Decision 2: `InvalidObservationError`, no tolerance band."""

    def test_accepts_an_exact_pass_score(self) -> None:
        _, provenance, chart = _fitted_bernoulli_chart()
        monitor = Monitor(chart)
        observation = ScoringResultFactory(provenance=provenance, score=1.0)
        result = monitor.record(observation)
        assert result.is_in_control in (True, False)

    def test_accepts_an_exact_fail_score(self) -> None:
        _, provenance, chart = _fitted_bernoulli_chart()
        monitor = Monitor(chart)
        observation = ScoringResultFactory(provenance=provenance, score=0.0)
        result = monitor.record(observation)
        assert result.is_in_control in (True, False)

    def test_rejects_a_legal_continuous_score(self) -> None:
        """0.42 is a perfectly legal ScoringResult.score for every OTHER chart type."""
        _, provenance, chart = _fitted_bernoulli_chart()
        monitor = Monitor(chart)
        observation = ScoringResultFactory(provenance=provenance, score=0.42)

        with pytest.raises(InvalidObservationError) as excinfo:
            monitor.record(observation)

        error = excinfo.value
        assert error.category == "invalid_observation"
        assert error.context["reason"] == "score_not_binary"
        # "nothing is missing; the value present is simply outside the
        # domain this chart can interpret" (domain-model.md Monitor invariant 9).
        assert error.context["missing_fields"] == ()

    def test_no_tolerance_band_near_one(self) -> None:
        """0.999 must NOT be silently accepted as "close enough" to 1.0 -- ADR-014
        Decision 2."""
        _, provenance, chart = _fitted_bernoulli_chart()
        monitor = Monitor(chart)
        observation = ScoringResultFactory(provenance=provenance, score=0.999)
        with pytest.raises(InvalidObservationError) as excinfo:
            monitor.record(observation)
        assert excinfo.value.context["reason"] == "score_not_binary"

    def test_rejected_observation_does_not_enter_history(self) -> None:
        _, provenance, chart = _fitted_bernoulli_chart()
        monitor = Monitor(chart)
        observation = ScoringResultFactory(provenance=provenance, score=0.42)
        with pytest.raises(InvalidObservationError):
            monitor.record(observation)
        assert len(monitor.history) == 0

    def test_this_precondition_does_not_apply_to_continuous_charts(self) -> None:
        """`FittedEWMA` et al. must still accept a continuous score (0.42) as before.

        Guards against a regression where the new precondition is applied
        to every artefact type instead of only `FittedBernoulliCUSUM`
        (domain-model.md: "This precondition applies only when
        self._artefact is a FittedBernoulliCUSUM").
        """
        from drift_caliper.baseline import fit_ewma

        provenance = ProvenanceFactory()
        baseline = Baseline()
        for _ in range(DEFAULT_SUFFICIENCY_THRESHOLD + 5):
            baseline.record(ScoringResultFactory(provenance=provenance))
        ewma_chart = fit_ewma(baseline, target_arl=_VALID_TARGET_ARL)
        monitor = Monitor(ewma_chart)
        observation = ScoringResultFactory(provenance=provenance, score=0.42)
        result = monitor.record(observation)  # must not raise
        assert result.is_in_control in (True, False)
