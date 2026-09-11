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

**AC6 -- no shared algebra.** Nothing below imports from
``caliper.baseline.domain.cusum_fitting`` at all -- unlike the EWMA file,
this file needs no formula helper even for its invariance check, because
``decision_interval``/``reference_value`` are already reported in
sigma-standardised units with nothing further to invert. The round-trip's
comparison target is ``achieved_arl`` -- the artefact's own already-reported
value -- checked only against independently simulated run lengths from
``tests.support.spc_simulation``, which itself only calls
``Monitor.record()``.

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
from caliper.baseline.domain.ewma_fitting import MIN_MEANINGFUL_ARL
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


def _baseline_from_scores(scores: list[float]) -> Baseline:
    """Build a ``Baseline`` from an explicit list of scores, one shared provenance."""
    baseline = Baseline()
    provenance = ProvenanceFactory()
    for score in scores:
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))
    return baseline


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
    ).filter(lambda scores: len(set(scores)) > 1)


@settings(max_examples=25, deadline=None)
@given(
    scores=_baseline_scores_strategy(),
    arl_low=st.floats(
        min_value=MIN_MEANINGFUL_ARL,
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
