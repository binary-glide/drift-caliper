"""Simulated ARL0 through ``Monitor``: the Bernoulli CUSUM's calibration, end to end.

Decision 18 item 2, extended by item 17 (ADR-014 Amendment 2 / Decision 19).
Follows the three continuous charts' ``*_arl_simulated_properties``
convention exactly: ``_N_RUNS = 1_500``, ``_CONFIDENCE_Z = 4.0`` and
``tests.support.spc_simulation.derived_relative_tolerance`` (a ~10.3%
relative band at ~99.994% two-sided normal-approximation confidence -- see
``test_ewma_arl_simulated_properties.py``'s module docstring for the
derivation); every run drives the real ``Monitor.record()``; no formula is
imported from production.

**What each stream is drawn at** -- the rate the artefact's ``achieved_arl``
is defined at (Decision 19.1, the ``achieved_arl`` row of the domain model):

- ``"lower"``: failures at ``p_U``; the mean run length should equal
  ``achieved_arl``.
- ``"upper"``: failures at ``p_L`` (success rate ``1 - p_L``); the same.
- ``"two_sided"``: ``achieved_arl`` is ``B``, a guaranteed *floor* over every
  true rate in ``[p_L, p_U]`` (Decision 19.4). Item 17: driven at ``p_hat``
  and at both bounds, asserting the simulated mean ``>= B`` within tolerance
  at each -- a one-sided check, because at every such rate the true joint ARL
  is at or above ``B`` (at m=300 f=3 T=100 the independent reference gives
  145.7 / 180.6 / 152.0 against ``B`` = 100.4).
- the floored lower arm (m=1,000 f=0, Decision 12): ``achieved_arl = 1/p_U``
  = 434.79 -- the run length is the waiting time to the first failure.

⚠️ **This test alone would not have caught defect 3** (Decision 18 item 2):
the float path's bias at m=300 f=3 was inside any honest tolerance. The
precise check is ``test_monitor_bernoulli_cusum_differential.py``; this one
guards the calibration end to end.

``T = 100``, the continuous charts' ``_ROUND_TRIP_TARGET_ARL``: the ADR fixes
the cells, not the target, and a smaller target keeps 1,500 runs affordable
(~25 us per ``Monitor.record``, measured).
"""

from __future__ import annotations

import numpy as np
import pytest

from drift_caliper.baseline import FittedBernoulliCUSUM, fit_bernoulli_cusum
from drift_caliper.measurement import Provenance, ScoringResult
from drift_caliper.monitoring import Monitor
from tests.support.bernoulli_surface import p_l
from tests.support.binary_baselines import binary_baseline
from tests.support.spc_simulation import derived_relative_tolerance

_N_RUNS = 1_500
_CONFIDENCE_Z = 4.0  # see test_ewma_arl_simulated_properties.py's module docstring
_TARGET_ARL = 100.0
_SIMULATION_SEED = 133_002
# A runaway-loop valve only, as in tests.support.spc_simulation: a run is cut
# off at 50 x achieved_arl, which an in-control geometric-like run length
# exceeds with probability ~exp(-50).
_RUN_LENGTH_SAFETY_CAP_MULTIPLE = 50


def _fit(m: int, f: int, direction: str) -> tuple[FittedBernoulliCUSUM, Provenance]:
    baseline, provenance = binary_baseline(m, f)
    chart = fit_bernoulli_cusum(baseline, target_arl=_TARGET_ARL, direction=direction)
    return chart, provenance


def _mean_run_length(
    chart: FittedBernoulliCUSUM, provenance: Provenance, failure_rate: float
) -> float:
    """Mean steps to first signal over ``_N_RUNS`` fresh Monitors, i.i.d.
    Bernoulli(``failure_rate``) failures, one seeded generator throughout."""
    rng = np.random.default_rng(_SIMULATION_SEED)
    passed = ScoringResult(score=1.0, reasoning="", provenance=provenance)
    failed = ScoringResult(score=0.0, reasoning="", provenance=provenance)
    cap = int(_RUN_LENGTH_SAFETY_CAP_MULTIPLE * chart.achieved_arl) + 1
    total = 0
    for _ in range(_N_RUNS):
        monitor = Monitor(chart, retain_history=False)
        step = cap
        for index in range(1, cap + 1):
            observation = failed if rng.random() < failure_rate else passed
            if not monitor.record(observation).is_in_control:
                step = index
                break
        total += step
    return total / _N_RUNS


_TOLERANCE = derived_relative_tolerance(_N_RUNS, z=_CONFIDENCE_Z)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("m", "f", "direction", "rate_name"),
    [
        (200, 20, "lower", "p_u"),
        (300, 3, "upper", "p_l"),
        (1000, 0, "lower", "p_u"),
    ],
    ids=["lower_m200_f20", "upper_m300_f3_at_p_l", "floored_lower_m1000_f0"],
)
# Budget: 1,500 runs x mean run length (110 / 100 / 435, independent
# reference) x ~25 us per Monitor.record = 4 s / 4 s / 16 s locally; x3 = 48 s
# at worst. 180 s hard stop.
@pytest.mark.timeout(180)
def test_one_sided_simulated_mean_run_length_matches_achieved_arl(
    m: int, f: int, direction: str, rate_name: str
) -> None:
    chart, provenance = _fit(m, f, direction)
    rate = chart.p_u if rate_name == "p_u" else p_l(chart)

    simulated = _mean_run_length(chart, provenance, rate)

    tolerance = _TOLERANCE * chart.achieved_arl
    assert abs(simulated - chart.achieved_arl) <= tolerance, (
        f"simulated {simulated!r} vs achieved_arl {chart.achieved_arl!r} "
        f"(tolerance {tolerance!r}) at failure rate {rate!r}"
    )


def test_the_floored_arm_reports_one_over_p_u() -> None:
    """The floored cell's premise (Decision 12), checked so the simulation
    above is known to exercise the floor rather than a coincidental value."""
    chart, _ = _fit(1000, 0, "lower")

    assert chart.achieved_arl == pytest.approx(1.0 / chart.p_u, rel=1e-9)


@pytest.mark.slow
@pytest.mark.parametrize("rate_name", ["p_l", "p_hat", "p_u"])
# Budget: 1,500 runs x true joint ARL (145.7 / 180.6 / 152.0, independent
# reference) x ~25 us = 5.5 s / 6.8 s / 5.7 s locally; x3 = 20 s. 180 s stop.
@pytest.mark.timeout(180)
def test_two_sided_simulated_mean_run_length_is_at_least_the_coupled_bound(
    rate_name: str,
) -> None:
    """Decision 18 item 17 at m=300 f=3: ``B`` is a floor at ``p_L``, ``p_hat``
    and ``p_U`` (Decision 19.4's coupling argument)."""
    chart, provenance = _fit(300, 3, "two_sided")
    rate = {"p_l": p_l(chart), "p_hat": 3 / 300, "p_u": chart.p_u}[rate_name]

    simulated = _mean_run_length(chart, provenance, rate)

    assert simulated >= chart.achieved_arl * (1.0 - _TOLERANCE), (
        f"simulated {simulated!r} below B={chart.achieved_arl!r} at {rate_name}"
    )
