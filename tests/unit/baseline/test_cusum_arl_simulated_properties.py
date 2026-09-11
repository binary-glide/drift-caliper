"""Property-based verification: CUSUM's calibrated ARL0 holds as a general property.

**Part 3 of 3 (BIN-84).** ``test_cusum_fitting.py`` (Part 1) asserts shape
only; ``test_cusum_arl_published_values.py`` (Part 2) verifies specific
``(reference_value, decision_interval)`` design points against Siegmund
(1985)/Montgomery (2013) and a hand-run, one-off, docstring-only Monte
Carlo table (see that file's own module docstring, "Fifth link"). **This
file is that Monte Carlo check, automated and generalised**, exactly as
that docstring itself names as BIN-84's job: "this is the shape a
property-based test should take for all three charts -- fit, simulate,
compare -- rather than only checking published tables." See
``test_ewma_arl_simulated_properties.py``'s module docstring for the full
shared reasoning (AC6 no-shared-algebra discipline, AC7 tolerance
derivation, AC8 distributional scope, AC9 diagnostic separation) -- not
repeated in full here to avoid the two files drifting out of sync in
prose while their code stays independent.

Three properties, one test group each below:

1. **Simulated ARL0 round-trip (AC2).** Fit a two-sided CUSUM to a target
   ARL0 from a freshly generated Gaussian Phase I baseline, then drive many
   independent, freshly simulated in-control streams through
   ``Monitor.record()`` and check the sample mean run length against the
   artefact's own reported ``achieved_arl``.
2. **Monotonicity (AC4).** A wider ``target_arl`` never narrows the
   decision interval, for any valid baseline, at a fixed reference value
   and direction.
3. **Invariance under positive affine transform (AC5).** Rescaling/shifting
   the baseline's raw scores and refitting leaves ``decision_interval``,
   ``reference_value``, and ``achieved_arl`` unchanged (all already
   sigma-standardised -- see ``cusum_fitting.py``'s module docstring), and
   moves ``target_value`` by the identical affine map.

**AC6 -- no shared algebra, with one narrow exception (BIN-117).** This
file's own checks -- the round-trip comparison and the invariance check --
import no formula helper from ``caliper.baseline.domain.cusum_fitting``:
unlike the EWMA file, the invariance check needs no formula even to invert,
because ``decision_interval``/``reference_value`` are already reported in
sigma-standardised units with nothing further to invert, and the
round-trip's comparison target is ``achieved_arl`` -- the artefact's own
already-reported value -- checked only against independently simulated run
lengths from ``tests.support.spc_simulation``, which itself only calls
``Monitor.record()``. The one exception is the monotonicity property's
``arl_low`` Hypothesis strategy (BIN-117): since ``fit_cusum`` now rejects
a ``target_arl`` below the minimum ARL0 actually attainable for a given
``(reference_value, direction)``, this file's fixed
``_MONOTONICITY_REFERENCE_VALUE``/``_MONOTONICITY_DIRECTION`` need that
same floor to bound the strategy so Hypothesis only ever draws attainable
inputs -- importing production's own ``_min_attainable_arl0`` directly for
that one purpose (not for the properties' own assertions), rather than
re-deriving it. An earlier draft of this fix re-derived it locally via
``_cusum_arl0``/``_combine_two_sided_arl0`` evaluated at the mathematical
(open, unattained) limit ``h = 0`` -- the same mistake a second review pass
found in production's own pre-check (see ``cusum_fitting.py``'s
``_min_attainable_arl0`` docstring). Importing the fixed function directly
removes that drift risk rather than requiring this file to independently
track which basis production uses.

**AC7 -- tolerance.** Identical derivation and parameters to
``test_ewma_arl_simulated_properties.py``: ``_N_RUNS = 1_500``,
``_CONFIDENCE_Z = 4.0``, giving a ~10.3% relative tolerance at ~99.994%
(two-sided, normal-approximation) confidence -- see that file's docstring
for the full derivation, which is chart-agnostic (a property of run-length
sampling, not of any one chart's calibration).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, fit_cusum
from caliper.baseline.domain.cusum_fitting import _min_attainable_arl0
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.spc_simulation import (
    derived_relative_tolerance,
    gaussian_baseline,
    simulate_mean_run_length,
)

# --- Round-trip simulation (AC2) ----------------------------------------------

_ROUND_TRIP_TARGET_ARL = 100.0
_ROUND_TRIP_REFERENCE_VALUE = 0.5  # DEFAULT_REFERENCE_VALUE, held fixed and explicit
_ROUND_TRIP_DIRECTION = "two_sided"
_ROUND_TRIP_BASELINE_MEAN = 0.6
_ROUND_TRIP_BASELINE_STD = 0.1
_ROUND_TRIP_BASELINE_SIZE = DEFAULT_SUFFICIENCY_THRESHOLD + 50
_BASELINE_SEED = 84_101
_SIMULATION_SEED = 84_102

_N_RUNS = 1_500
_CONFIDENCE_Z = 4.0  # see test_ewma_arl_simulated_properties.py's module docstring


def test_cusum_simulated_mean_run_length_matches_achieved_arl() -> None:
    """A two-sided CUSUM fitted for ARL0=100 signals, on average, about every 100 steps.

    Automates what ``test_cusum_arl_published_values.py``'s "Fifth link"
    section only ever ran once by hand.
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
    artefact = fit_cusum(
        baseline,
        target_arl=_ROUND_TRIP_TARGET_ARL,
        reference_value=_ROUND_TRIP_REFERENCE_VALUE,
        direction=_ROUND_TRIP_DIRECTION,
    )

    # Act -- in-control means "generated from the process the chart was
    # actually fitted to", i.e. the artefact's OWN estimated
    # target_value/sigma_estimate, not the design mean/std used to draw the
    # finite-sample baseline -- see
    # test_ewma_arl_simulated_properties.py's identical note for why using
    # the design parameters would confound this property with Phase I
    # finite-sample estimation error (a separate, already-documented effect,
    # ADR-005).
    simulated_mean_run_length = simulate_mean_run_length(
        artefact,
        provenance,
        mean=artefact.target_value,
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

_PROPERTY_BASELINE_SIZE = DEFAULT_SUFFICIENCY_THRESHOLD
_MONOTONICITY_ARL_LOW_MAX = 1_000.0
_MONOTONICITY_ARL_GAP_MAX = 1_000.0
_MONOTONICITY_REFERENCE_VALUE = 0.5
_MONOTONICITY_DIRECTION = "two_sided"

# BIN-117: fit_cusum() now rejects a target_arl below the minimum ARL0
# actually attainable for a given (reference_value, direction) -- see
# cusum_fitting.py's `_min_attainable_arl0` docstring. Below this floor, at
# the fixed _MONOTONICITY_REFERENCE_VALUE/_MONOTONICITY_DIRECTION this
# property uses, every draw would raise rather than fit -- a change to
# which inputs are legal, not a weakening of the monotonicity property
# itself. No margin above the floor: `_min_attainable_arl0` (imported from
# production, not re-derived -- see the module docstring's AC6 note) is
# itself genuinely attainable, evaluated at the same
# `_MIN_DECISION_INTERVAL` `_calibrate_decision_interval` searches from, so
# using it directly as `min_value` lets Hypothesis draw the exact boundary
# too -- a stronger property test than a value some margin away, and the
# one an earlier draft of this fix (margin = infimum * 1.001, against the
# wrong, open h=0 basis) did not exercise.
_MONOTONICITY_ARL_LOW_MIN = _min_attainable_arl0(
    _MONOTONICITY_REFERENCE_VALUE, _MONOTONICITY_DIRECTION
)


def _baseline_from_scores(scores: list[float]) -> Baseline:
    """Build a ``Baseline`` from an explicit list of scores, one shared provenance."""
    baseline = Baseline()
    provenance = ProvenanceFactory()
    for score in scores:
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))
    return baseline


# BIN-123: `len(set(scores)) > 1` is no longer a sufficient definition of
# "non-degenerate". BIN-119 added a second rejection -- a baseline whose
# *moving-range aggregate* underflows to zero -- and `[0.0] * 149 + [5e-324]`
# satisfies the old filter (two distinct values) while the library now
# correctly refuses to fit it.
#
# That made this strategy generate inputs that are illegal by construction,
# so the property test failed whenever Hypothesis happened to find one.
# It is a latent flake rather than a constant failure: a fresh run passes,
# and the counterexample only replays deterministically once it is in
# `.hypothesis/examples`. CI starts with an empty database, which is why
# PR #46 went green.
#
# The floor below is a *test-side sufficient condition*, deliberately not a
# reimplementation of `_moving_range_sigma` -- duplicating production
# arithmetic here is the self-cancelling-helper pattern this project has
# hit five times. It only has to be strict enough that no drawn baseline can
# underflow, not to agree with the library's exact threshold.
#
# Margin, so the constant is not a magic number: by the triangle inequality
# the sum of consecutive absolute differences is at least `max - min`, so a
# spread of `1e-6` forces a mean moving range of at least
# `1e-6 / (n - 1)` -- about `6.7e-9` here, some 300 orders of magnitude above
# the underflow floor near `4.9e-324`. It does not meaningfully shrink the
# `[-10.0, 10.0]` space the properties explore.
#
# ⚠️ Why a floor rather than catching `DegenerateBaselineError` in the test
# body and calling `assume(False)`: that alternative defers to the library's
# own definition of degenerate, which sounds better and is worse. It would
# silently discard any future case where the library *over-rejects valid
# data* -- which is exactly the BIN-123 failure class, and exactly what this
# project most needs to stay visible. An independent floor turns that into a
# test failure instead of a filtered-away example.
# (Raised by code-reviewer on BIN-123, 2026-09-11.)
#
# ⚠️ Generalisable: every new rejection in `src/` can turn an existing
# Hypothesis strategy into a generator of illegal inputs. BIN-117 taught
# this once (its `arl_low` strategy) and BIN-119 repeated it here.
_MIN_FITTABLE_SPREAD = 1e-6


def _is_fittable(scores: list[float]) -> bool:
    """Reject draws the library legitimately refuses to fit.

    Excludes both the all-identical (zero-variance) draw and the
    vanishing-spread draw whose mean moving range underflows to zero.
    """
    return max(scores) - min(scores) >= _MIN_FITTABLE_SPREAD


def _baseline_scores_strategy() -> st.SearchStrategy[list[float]]:
    """Hypothesis strategy for a fixed-size, non-degenerate list of baseline scores.

    See ``test_ewma_arl_simulated_properties.py``'s identical helper for
    the full reasoning (fixed size satisfies sufficiency by construction;
    ``.filter`` excludes the all-identical, zero-variance draw).
    """
    return st.lists(
        st.floats(
            min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
        min_size=_PROPERTY_BASELINE_SIZE,
        max_size=_PROPERTY_BASELINE_SIZE,
    ).filter(_is_fittable)


@settings(max_examples=25, deadline=None)
@given(
    scores=_baseline_scores_strategy(),
    arl_low=st.floats(
        min_value=_MONOTONICITY_ARL_LOW_MIN,
        max_value=_MONOTONICITY_ARL_LOW_MAX,
        allow_nan=False,
    ),
    arl_gap=st.floats(
        min_value=1.0, max_value=_MONOTONICITY_ARL_GAP_MAX, allow_nan=False
    ),
)
def test_wider_target_arl_never_narrows_the_cusum_decision_interval(
    scores: list[float], arl_low: float, arl_gap: float
) -> None:
    """``decision_interval`` is non-decreasing in ``target_arl``, reference value fixed.

    A wider false-alarm tolerance must demand at least as large a decision
    interval -- otherwise the chart would signal in-control observations
    MORE often for a LARGER requested ARL0, which is the calibration
    working backwards.

    **Updated for BIN-117.** ``arl_low`` previously drew from
    ``[MIN_MEANINGFUL_ARL, _MONOTONICITY_ARL_LOW_MAX]`` -- a range that, at
    this test's fixed reference value (0.5), partially overlapped the zone
    ``fit_cusum`` now (correctly) rejects as unattainable
    (``MIN_MEANINGFUL_ARL=1.0`` is below the two-sided minimum attainable
    ARL0 of ~1.0431 at ``k=0.5``). Bounding the strategy at
    ``_MONOTONICITY_ARL_LOW_MIN`` -- the exact, genuinely-attainable floor
    -- keeps every drawn ``arl_low`` legal post-fix -- this is a correction
    to what inputs the strategy generates, not a change to what the
    property itself asserts.
    """
    # Arrange
    baseline = _baseline_from_scores(scores)
    arl_high = arl_low + arl_gap

    # Act
    fitted_low = fit_cusum(
        baseline,
        target_arl=arl_low,
        reference_value=_MONOTONICITY_REFERENCE_VALUE,
        direction=_MONOTONICITY_DIRECTION,
    )
    fitted_high = fit_cusum(
        baseline,
        target_arl=arl_high,
        reference_value=_MONOTONICITY_REFERENCE_VALUE,
        direction=_MONOTONICITY_DIRECTION,
    )

    # Assert
    assert fitted_high.decision_interval >= fitted_low.decision_interval


# --- Invariance under positive affine transform (AC5) --------------------------

_INVARIANCE_TARGET_ARL = 370.0
_INVARIANCE_REFERENCE_VALUE = 0.5
_INVARIANCE_DIRECTION = "two_sided"


@settings(max_examples=25, deadline=None)
@given(
    scores=_baseline_scores_strategy(),
    scale=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
    shift=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False),
)
def test_affine_transform_of_the_baseline_leaves_cusum_decision_interval_unchanged(
    scores: list[float], scale: float, shift: float
) -> None:
    """Sigma-standardised fields are unchanged; only ``target_value`` transforms.

    ``decision_interval`` and ``reference_value`` are already dimensionless
    (sigma units -- ``cusum_fitting.py`` module docstring) so a positive
    affine transform of the raw baseline must leave them exactly where they
    were; only ``target_value`` (== ``baseline_mean``) is on the
    observation scale and moves by the same map.
    """
    # Arrange
    original_baseline = _baseline_from_scores(scores)
    transformed_baseline = _baseline_from_scores(
        [scale * score + shift for score in scores]
    )

    # Act
    original = fit_cusum(
        original_baseline,
        target_arl=_INVARIANCE_TARGET_ARL,
        reference_value=_INVARIANCE_REFERENCE_VALUE,
        direction=_INVARIANCE_DIRECTION,
    )
    transformed = fit_cusum(
        transformed_baseline,
        target_arl=_INVARIANCE_TARGET_ARL,
        reference_value=_INVARIANCE_REFERENCE_VALUE,
        direction=_INVARIANCE_DIRECTION,
    )

    # Assert -- dimensionless quantities unchanged
    assert transformed.achieved_arl == pytest.approx(original.achieved_arl, rel=1e-6)
    assert transformed.decision_interval == pytest.approx(
        original.decision_interval, rel=1e-6
    )
    assert transformed.reference_value == original.reference_value

    # Assert -- observation-scale quantity transforms by the identical affine map
    assert transformed.target_value == pytest.approx(
        scale * original.target_value + shift, rel=1e-6
    )


__all__: list[str] = []
