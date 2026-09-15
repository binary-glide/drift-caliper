"""Phase II simulation harness for BIN-84's property-based SPC verification.

Shared by ``tests/unit/baseline/test_{ewma,cusum,shewhart}_arl_simulated_properties.py``
-- the three "Part 3" files that verify each chart's calibrated ARL0 holds as
a *general property* under freshly simulated in-control data, not only at
the fixed points ``test_{ewma,cusum,shewhart}_arl_published_values.py``
(Part 2) already check. See ``docs/domain-model.md``, ADR-001, and
``vault/projects/caliper/tickets/BIN-84-.../PRD.md`` (BR-1, AC1-3, AC6-AC8).

**Everything here drives ``Monitor.record()`` -- the real Phase II
production code path an engineer actually calls -- never a chart's internal
calibration helper (``_in_control_arl``, ``_cusum_arl0``,
``_shewhart_arl0``, or either chart's decision-interval/limit-multiplier
solver).** That is BIN-84's central discipline (BR-1, AC6): this project has
four prior defects where a helper both calibrated a value and checked it,
so the error divided out and became unfalsifiable, caught only by mutation
testing at ~98% line coverage (see ``CLAUDE.md``). Nothing in this module
imports from ``drift_caliper.baseline.domain.{ewma,cusum,shewhart}_fitting`` --
only the public ``Baseline``/``Monitor``/``ScoringResult``/``Provenance``
surface an engineer would use.

**Distributional scope (AC8): in-control data is drawn i.i.d. Gaussian.**
This is deliberate scope, not an oversight -- it is exactly the assumption
each chart's own calibration makes (Lucas & Saccucci 1990 for EWMA;
Siegmund 1985 for CUSUM; the two-sided normal-tail closed form for
Shewhart). Testing against a distribution the calibration does not claim to
handle would not verify the claim this story exists to verify; non-normal /
judge-score-like distributional robustness is explicitly deferred
post-v0.1 (PRD Non-Goals, alongside ADR-003's deferred work).
"""

from __future__ import annotations

import math

import numpy as np

from drift_caliper.baseline import Baseline, FittedControlLimits
from drift_caliper.measurement import Provenance, ScoringResult
from drift_caliper.monitoring import Monitor

# A run that has not signalled after this many multiples of the artefact's
# own reported achieved_arl is cut off rather than simulated indefinitely.
# Purely a runaway-loop safety valve, not a statistical choice: the
# in-control run length is approximately geometric with parameter
# p = 1 / achieved_arl, so P(run length > 50 * achieved_arl) =
# (1 - p) ** (50 * achieved_arl) ~= exp(-50) ~= 2e-22 -- astronomically
# below any probability this module's simulated run counts could ever
# sample. Hitting the cap censors that one run's contribution to the mean
# (undercounting it), which is a negligible, one-sided bias at that
# probability -- not a tolerance decision.
_RUN_LENGTH_SAFETY_CAP_MULTIPLE = 50


def gaussian_baseline(
    provenance: Provenance,
    *,
    mean: float,
    std: float,
    n: int,
    seed: int,
) -> Baseline:
    """Build a ``Baseline`` of ``n`` i.i.d. ``Normal(mean, std)`` observations.

    Every observation shares ``provenance``, so ``Baseline.record()`` never
    raises ``ProvenanceMismatchError``. Deterministic given ``seed`` --
    required so a failing property-based example is reproducible and no
    simulation test in this suite is flaky by construction.
    """
    rng = np.random.default_rng(seed)
    baseline = Baseline()
    for value in rng.normal(loc=mean, scale=std, size=n):
        baseline.record(
            ScoringResult(score=float(value), reasoning="", provenance=provenance)
        )
    return baseline


def simulate_run_length(
    artefact: FittedControlLimits,
    provenance: Provenance,
    rng: np.random.Generator,
    *,
    mean: float,
    std: float,
) -> int:
    """Run one independent, freshly simulated in-control stream to first signal.

    Constructs a fresh ``Monitor`` (history retention off -- nothing here
    needs it, and retaining it would be pure overhead across many runs),
    then records ``ScoringResult``s drawn i.i.d. from
    ``Normal(mean, std)`` -- the same in-control distribution the baseline
    itself was drawn from -- through ``Monitor.record()`` until the first
    out-of-control determination. Returns the 1-indexed step at which that
    happened: the realised run length for this one run.

    A fresh ``Monitor`` per call is required, not incidental: EWMA's
    smoothed statistic and CUSUM's two running sums are per-``Monitor``
    accumulator state (``docs/architecture/adr/009-...md`` section 1), and
    a run-to-first-signal measurement must start from the chart's own
    defined zero-state -- the same zero-state each chart's calibration
    itself assumes (Brook & Evans 1972's "zero-state ARL", Siegmund's
    (1985) sums initialised at zero).
    """
    monitor = Monitor(artefact, retain_history=False)
    cap = int(_RUN_LENGTH_SAFETY_CAP_MULTIPLE * artefact.achieved_arl) + 1
    for step in range(1, cap + 1):
        score = float(rng.normal(loc=mean, scale=std))
        observation = ScoringResult(score=score, reasoning="", provenance=provenance)
        result = monitor.record(observation)
        if not result.is_in_control:
            return step
    return cap  # pragma: no cover -- see _RUN_LENGTH_SAFETY_CAP_MULTIPLE's docstring


def simulate_mean_run_length(
    artefact: FittedControlLimits,
    provenance: Provenance,
    *,
    mean: float,
    std: float,
    n_runs: int,
    seed: int,
) -> float:
    """The sample mean run length over ``n_runs`` independent simulated streams.

    One ``np.random.Generator`` seeded once and threaded through every run
    -- not re-seeded per run -- so ``n_runs`` independent draws come from
    one reproducible stream rather than ``n_runs`` correlated ones sharing
    a seed.
    """
    rng = np.random.default_rng(seed)
    total_steps = 0
    for _ in range(n_runs):
        total_steps += simulate_run_length(
            artefact, provenance, rng, mean=mean, std=std
        )
    return total_steps / n_runs


def derived_relative_tolerance(n_runs: int, *, z: float) -> float:
    """The relative tolerance a round-trip test should apply, derived per AC7.

    The in-control run length is approximately geometrically distributed
    with parameter ``p = 1 / ARL0``: mean ``ARL0``, standard deviation
    ``ARL0 * sqrt(1 - p) ~= ARL0`` for the ARL0 magnitudes this suite uses
    (``p`` small, e.g. ``ARL0 = 100 => p = 0.01 => sqrt(1 - p) ~= 0.995``).
    By the CLT, the sample mean of ``n_runs`` i.i.d. draws has standard
    error ``SE ~= ARL0 / sqrt(n_runs)``, so a band of ``z`` standard errors
    around the true mean has (two-sided, normal-approximation) confidence
    ``2 * Phi(z) - 1`` and RELATIVE half-width ``z / sqrt(n_runs)`` --
    independent of ARL0 itself, which is why this function takes no ARL0
    argument. See each calling test module's docstring for the specific
    ``(n_runs, z)`` pair used and the resulting confidence level and
    designed-in flake probability.
    """
    return z / math.sqrt(n_runs)
