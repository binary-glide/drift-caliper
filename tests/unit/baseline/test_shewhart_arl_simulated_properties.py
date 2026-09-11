"""Property-based verification: Shewhart's calibrated ARL0 holds as a general property.

**Part 3 of 3 (BIN-84).** ``test_shewhart_fitting.py`` (Part 1) asserts
shape only; ``test_shewhart_arl_published_values.py`` (Part 2) verifies the
closed-form ``ARL0(L) = 1 / (2 * Phi(-L))`` relationship directly, with no
approximation error and no published table needed at all (see that file's
module docstring). Even an exact closed form needs this file, though: Part
2 checks the *formula*; this checks the *library* end to end through the
real Phase II path, the same distinction
``test_cusum_arl_published_values.py``'s "Fifth link" section draws for its
own hand-run Monte Carlo check. See
``test_ewma_arl_simulated_properties.py``'s module docstring for the full
shared reasoning (AC6 no-shared-algebra discipline, AC7 tolerance
derivation, AC8 distributional scope, AC9 diagnostic separation) -- not
repeated in full here to avoid the three files drifting out of sync in
prose while their code stays independent.

Three properties, one test group each below:

1. **Simulated ARL0 round-trip (AC3).** Fit Shewhart to a target ARL0 from
   a freshly generated Gaussian Phase I baseline, then drive many
   independent, freshly simulated in-control streams through
   ``Monitor.record()`` and check the sample mean run length against the
   artefact's own reported ``achieved_arl``.
2. **Monotonicity (AC4).** A wider ``target_arl`` never narrows
   ``sigma_multiplier`` (and hence ``ucl - lcl``), for any valid baseline.
3. **Invariance under positive affine transform (AC5).** Rescaling/shifting
   the baseline's raw scores and refitting leaves ``sigma_multiplier`` and
   ``achieved_arl`` unchanged, and moves ``ucl``/``lcl``/``cl`` by the
   identical affine map.

**AC6 -- no shared algebra.** Nothing below imports from
``caliper.baseline.domain.shewhart_fitting`` at all. The round-trip's
comparison target is ``achieved_arl`` -- the artefact's own already-reported
value -- checked only against independently simulated run lengths from
``tests.support.spc_simulation``, which itself only calls
``Monitor.record()``.

**AC7 -- tolerance.** Identical derivation and parameters to
``test_ewma_arl_simulated_properties.py``: ``_N_RUNS = 1_500``,
``_CONFIDENCE_Z = 4.0``, giving a ~10.3% relative tolerance at ~99.994%
(two-sided, normal-approximation) confidence -- see that file's docstring
for the full derivation. This is markedly looser than Part 2's ``1e-6``
relative tolerance -- deliberately: Part 2 checks exact closed-form
arithmetic (no sampling involved, so float precision is the only source of
error); this file's tolerance instead bounds Monte Carlo sampling noise,
which dominates by many orders of magnitude regardless of how exact the
underlying calibration is.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, fit_shewhart
from caliper.baseline.domain.ewma_fitting import MIN_MEANINGFUL_ARL
from tests.factories import ProvenanceFactory
from tests.support.baseline_strategies import (
    baseline_from_scores,
    baseline_scores_strategy,
)
from tests.support.spc_simulation import (
    derived_relative_tolerance,
    gaussian_baseline,
    simulate_mean_run_length,
)

# --- Round-trip simulation (AC3) ----------------------------------------------

_ROUND_TRIP_TARGET_ARL = 100.0
_ROUND_TRIP_BASELINE_MEAN = 0.6
_ROUND_TRIP_BASELINE_STD = 0.1
_ROUND_TRIP_BASELINE_SIZE = DEFAULT_SUFFICIENCY_THRESHOLD + 50
_BASELINE_SEED = 84_201
_SIMULATION_SEED = 84_202

_N_RUNS = 1_500
_CONFIDENCE_Z = 4.0  # see test_ewma_arl_simulated_properties.py's module docstring


def test_shewhart_simulated_mean_run_length_matches_achieved_arl() -> None:
    """A chart fitted for ARL0=100 signals, on average, once every 100 in-control steps.

    Verifies the library end to end -- Part 2 already verifies the exact
    tail-probability formula in isolation; this exercises the calibrated
    limits actually wired through ``Monitor.record()``.
    """
    # Arrange
    provenance = ProvenanceFactory()
    baseline = gaussian_baseline(
        provenance,
        mean=_ROUND_TRIP_BASELINE_MEAN,
        std=_ROUND_TRIP_BASELINE_STD,
        n=_ROUND_TRIP_BASELINE_SIZE,
        seed=_BASELINE_SEED,
    )
    artefact = fit_shewhart(baseline, target_arl=_ROUND_TRIP_TARGET_ARL)

    # Act -- in-control means "generated from the process the chart was
    # actually fitted to", i.e. the artefact's OWN estimated cl/sigma_estimate
    # -- see test_ewma_arl_simulated_properties.py's identical note for why
    # using the design mean/std instead would confound this property with
    # Phase I finite-sample estimation error (ADR-005, a separate,
    # already-documented effect).
    simulated_mean_run_length = simulate_mean_run_length(
        artefact,
        provenance,
        mean=artefact.cl,
        std=artefact.sigma_estimate,
        n_runs=_N_RUNS,
        seed=_SIMULATION_SEED,
    )

    # Assert -- tolerance derived per AC7 (see module docstring)
    tolerance = (
        derived_relative_tolerance(_N_RUNS, z=_CONFIDENCE_Z) * artefact.achieved_arl
    )
    assert abs(simulated_mean_run_length - artefact.achieved_arl) <= tolerance, (
        f"simulated mean run length {simulated_mean_run_length!r} is not within "
        f"{tolerance!r} of achieved_arl={artefact.achieved_arl!r}"
    )


# --- Monotonicity (AC4) --------------------------------------------------------

_MONOTONICITY_ARL_LOW_MAX = 1_000.0
_MONOTONICITY_ARL_GAP_MAX = 1_000.0


# BIN-124: both the strategy and `_baseline_from_scores` used to be defined
# here, identically in this file's EWMA/CUSUM siblings (and, for
# `_baseline_from_scores`, this ticket's own meta-test too) -- see
# ``tests/support/baseline_strategies.py`` for the shared definitions and
# the full reasoning behind the strategy's floor (moved there rather than
# paraphrased, so it stays a single source of truth instead of several that
# can drift).
@settings(max_examples=25, deadline=None)
@given(
    scores=baseline_scores_strategy(),
    arl_low=st.floats(
        min_value=MIN_MEANINGFUL_ARL,
        max_value=_MONOTONICITY_ARL_LOW_MAX,
        allow_nan=False,
    ),
    arl_gap=st.floats(
        min_value=1.0, max_value=_MONOTONICITY_ARL_GAP_MAX, allow_nan=False
    ),
)
def test_wider_target_arl_never_narrows_the_shewhart_boundary(
    scores: list[float], arl_low: float, arl_gap: float
) -> None:
    """``sigma_multiplier`` (hence ``ucl - lcl``) is non-decreasing in ``target_arl``.

    Mirrors the EWMA/CUSUM monotonicity tests above; see their docstrings.
    """
    # Arrange
    baseline = baseline_from_scores(scores)
    arl_high = arl_low + arl_gap

    # Act
    fitted_low = fit_shewhart(baseline, target_arl=arl_low)
    fitted_high = fit_shewhart(baseline, target_arl=arl_high)

    # Assert
    assert fitted_high.sigma_multiplier >= fitted_low.sigma_multiplier
    assert (fitted_high.ucl - fitted_high.lcl) >= (fitted_low.ucl - fitted_low.lcl)


# --- Invariance under positive affine transform (AC5) --------------------------

_INVARIANCE_TARGET_ARL = 370.0


@settings(max_examples=25, deadline=None)
@given(
    scores=baseline_scores_strategy(),
    scale=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
    shift=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False),
)
def test_affine_transform_of_the_baseline_scales_shewhart_limits_predictably(
    scores: list[float], scale: float, shift: float
) -> None:
    """``sigma_multiplier``/``achieved_arl`` unchanged; limits transform affinely.

    Mirrors the EWMA/CUSUM invariance tests above; see their docstrings.
    """
    # Arrange
    original_baseline = baseline_from_scores(scores)
    transformed_baseline = baseline_from_scores(
        [scale * score + shift for score in scores]
    )

    # Act
    original = fit_shewhart(original_baseline, target_arl=_INVARIANCE_TARGET_ARL)
    transformed = fit_shewhart(transformed_baseline, target_arl=_INVARIANCE_TARGET_ARL)

    # Assert -- dimensionless quantities unchanged
    assert transformed.achieved_arl == pytest.approx(original.achieved_arl, rel=1e-6)
    assert transformed.sigma_multiplier == pytest.approx(
        original.sigma_multiplier, rel=1e-6
    )

    # Assert -- observation-scale quantities transform by the identical affine map
    assert transformed.cl == pytest.approx(scale * original.cl + shift, rel=1e-6)
    assert transformed.ucl == pytest.approx(scale * original.ucl + shift, rel=1e-6)
    assert transformed.lcl == pytest.approx(scale * original.lcl + shift, rel=1e-6)


__all__: list[str] = []
