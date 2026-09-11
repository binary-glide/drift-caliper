"""Property-based verification: EWMA's calibrated ARL0 holds as a general property.

**Part 3 of 3 (BIN-84).** ``test_ewma_fitting.py`` (Part 1) asserts shape
only; ``test_ewma_arl_published_values.py`` (Part 2) verifies specific
``(smoothing_param, target_arl)`` points against Lucas & Saccucci (1990)
Table 3. Both leave a gap this story closes: a calibration that is correct
at every checked point but wrong somewhere in between would ship
undetected by either layer, because neither generalises beyond its fixed
checkpoints. A failure in *this* file reads unambiguously as "a
generalised statistical property is violated" (AC9) -- distinct from "the
API contract changed" (Part 1) or "a specific verified point regressed"
(Part 2).

Three properties, one test group each below:

1. **Simulated ARL0 round-trip (AC1).** Fit EWMA to a target ARL0 from a
   freshly generated Gaussian Phase I baseline, then drive many
   independent, freshly simulated in-control streams through
   ``Monitor.record()`` -- the real Phase II path an engineer uses, never
   a calibration helper (AC6) -- and check the sample mean run length
   against the artefact's own reported ``achieved_arl``.
2. **Monotonicity (AC4).** A wider ``target_arl`` never narrows the fitted
   boundary (``ucl - lcl``), for any valid baseline.
3. **Invariance under positive affine transform (AC5).** Rescaling and
   shifting the baseline's raw scores (``x -> a*x + b``, ``a > 0``) and
   refitting leaves every dimensionless calibration parameter and
   ``achieved_arl`` unchanged, and moves the observation-scale limits by
   the identical affine map.

**AC6 -- no shared algebra.** Nothing below imports from
``caliper.baseline.domain.ewma_fitting`` except the public ``fit_ewma``.
The round-trip's comparison target is ``achieved_arl`` -- the artefact's
own already-reported value -- never a value this file computes from the
Markov-chain helper (``_in_control_arl``) or the limit-multiplier solver.
The independent evidence is entirely the simulated run lengths from
``tests.support.spc_simulation``, which itself only calls
``Monitor.record()``.

**AC8 -- distributional scope.** The round-trip's in-control process is
i.i.d. Gaussian -- the same assumption the Markov-chain calibration itself
makes (Lucas & Saccucci 1990). See
``tests.support.spc_simulation``'s module docstring for why this is
deliberate scope, not an oversight.

**AC7 -- the round-trip's tolerance, derived, not chosen.**

``_N_RUNS = 1_500`` independent simulated streams, ``_CONFIDENCE_Z = 4.0``
standard errors either side of the true mean. Per
``tests.support.spc_simulation.derived_relative_tolerance``'s docstring:
the in-control run length is approximately geometric (mean ``ARL0``,
std dev ``~= ARL0``), so the sample mean of ``_N_RUNS`` draws has standard
error ``SE ~= ARL0 / sqrt(_N_RUNS)``, and a band of ``_CONFIDENCE_Z``
standard errors has (two-sided, normal approximation) confidence
``2 * Phi(4) - 1 ~= 99.994%`` -- a per-run designed-in flake probability of
about ``6.3e-5`` (roughly 1 in 15,800). The resulting RELATIVE tolerance is
``_CONFIDENCE_Z / sqrt(_N_RUNS) ~= 4 / 38.73 ~= 10.3%`` -- wide enough to
absorb pure sampling noise at that confidence level, tight enough that a
wiring bug (wrong sign, using ``requested_arl`` instead of the fitted
result, an inverted comparison) -- which moves the simulated mean by tens
of percent or more, not single digits -- still fails loudly. This is not
the 2% tolerance the published-value files use: those check an
approximation formula against an external reference value: this checks an
empirical Monte Carlo estimate against the SAME implementation's own
report, so its tolerance is a statistical sampling-error bound, not an
approximation-accuracy budget.

**Runtime.** ``_N_RUNS`` (1,500) times a target ARL0 of 100 is
~150,000 simulated ``Monitor.record()`` calls for the round-trip test
alone. Not marked ``slow`` -- measured at implementation time to fall
comfortably within the existing suite's per-test budget; see this story's
completion report for the measured wall-clock figure. If a future change
to this file raises ``_N_RUNS`` materially, re-measure and mark ``slow``
per BR-5 rather than letting the default suite balloon silently.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, fit_ewma
from caliper.baseline.domain.ewma_fitting import (
    MIN_MEANINGFUL_ARL,
    # Formula only, not the Markov-chain calibration helper -- see below.
    _ewma_asymptotic_std_ratio,
)
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.spc_simulation import (
    derived_relative_tolerance,
    gaussian_baseline,
    simulate_mean_run_length,
)

# --- Round-trip simulation (AC1) ----------------------------------------------

_ROUND_TRIP_TARGET_ARL = 100.0
_ROUND_TRIP_BASELINE_MEAN = 0.6
_ROUND_TRIP_BASELINE_STD = 0.1
_ROUND_TRIP_BASELINE_SIZE = DEFAULT_SUFFICIENCY_THRESHOLD + 50
_BASELINE_SEED = 84_001  # arbitrary, fixed -- see module docstring "Runtime"
_SIMULATION_SEED = 84_002  # distinct from the baseline seed, deliberately

_N_RUNS = 1_500
_CONFIDENCE_Z = 4.0  # see module docstring's "AC7" section for the derivation


def test_ewma_simulated_mean_run_length_matches_achieved_arl() -> None:
    """A chart fitted for ARL0=100 signals, on average, once every 100 in-control steps.

    The single strongest test in this file: an entirely independent
    measurement (Monte Carlo through the real Phase II path) checked
    against the calibration's own report, with a tolerance derived from
    first principles rather than picked to make the test pass (AC7).
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
    artefact = fit_ewma(baseline, target_arl=_ROUND_TRIP_TARGET_ARL)

    # Act -- in-control means "generated from the process the chart was
    # actually fitted to", i.e. the artefact's OWN estimated cl/sigma_estimate,
    # not the design mean/std used to draw the finite-sample baseline. Using
    # the design parameters instead would confound this property (does the
    # calibration's own maths hold, given its stated parameters?) with Phase
    # I finite-sample estimation error (ADR-005's separately documented,
    # already-accepted caveat) -- a different effect this story is not
    # trying to measure.
    simulated_mean_run_length = simulate_mean_run_length(
        artefact,
        provenance,
        mean=artefact.cl,
        std=artefact.sigma_estimate,
        n_runs=_N_RUNS,
        seed=_SIMULATION_SEED,
    )

    # Assert -- tolerance derived per AC7, stated in the module docstring.
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

    Fixed size (``min_size == max_size``) so every generated example
    already satisfies ``check_sufficiency()`` -- the property under test is
    about the calibration, not about baseline sufficiency, which Part 1
    already covers. ``.filter`` excludes the (measure-zero-in-practice, but
    not impossible) all-identical draw, since a zero-variance baseline is a
    ``DegenerateBaselineError`` -- a different, already-covered code path
    (Part 1), not this property.
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
        min_value=MIN_MEANINGFUL_ARL,
        max_value=_MONOTONICITY_ARL_LOW_MAX,
        allow_nan=False,
    ),
    arl_gap=st.floats(
        min_value=1.0, max_value=_MONOTONICITY_ARL_GAP_MAX, allow_nan=False
    ),
)
def test_wider_target_arl_never_narrows_the_ewma_boundary(
    scores: list[float], arl_low: float, arl_gap: float
) -> None:
    """``ucl - lcl`` is non-decreasing in ``target_arl``, for any valid baseline.

    ``arl_high = arl_low + arl_gap`` with ``arl_gap >= 1.0`` guarantees
    ``arl_high > arl_low`` strictly (no float-equality edge case to guard
    against), and both stay comfortably inside
    ``[MIN_MEANINGFUL_ARL, MAX_MEANINGFUL_ARL]``.
    """
    # Arrange
    baseline = _baseline_from_scores(scores)
    arl_high = arl_low + arl_gap

    # Act
    fitted_low = fit_ewma(baseline, target_arl=arl_low)
    fitted_high = fit_ewma(baseline, target_arl=arl_high)

    # Assert
    assert (fitted_high.ucl - fitted_high.lcl) >= (fitted_low.ucl - fitted_low.lcl)


# --- Invariance under positive affine transform (AC5) --------------------------

_INVARIANCE_TARGET_ARL = 370.0


def _implied_limit_multiplier(
    ucl: float, cl: float, sigma_estimate: float, smoothing_param: float
) -> float:
    """Recover L from reported limits -- inverts ``ucl = cl + L*sigma*ratio(lambda)``.

    Written fresh from the asymptotic EWMA form (Lucas & Saccucci 1990) for
    THIS file's own invariance check; ``_ewma_asymptotic_std_ratio`` is a
    pure formula (``sqrt(lambda / (2 - lambda))``, Roberts 1959) with no
    calibration logic in it -- not the Markov-chain helper AC6 forbids
    sharing.
    """
    sigma_z = sigma_estimate * _ewma_asymptotic_std_ratio(smoothing_param)
    return (ucl - cl) / sigma_z


@settings(max_examples=25, deadline=None)
@given(
    scores=_baseline_scores_strategy(),
    scale=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
    shift=st.floats(min_value=-50.0, max_value=50.0, allow_nan=False),
)
def test_affine_transform_of_the_baseline_scales_ewma_limits_predictably(
    scores: list[float], scale: float, shift: float
) -> None:
    """Rescaling/shifting the baseline moves limits by the same map; ratios unchanged.

    ``x -> scale * x + shift`` with ``scale > 0`` (a positive affine map,
    per AC5) is applied to every raw score, and the chart is refit from
    scratch on the transformed baseline. ``achieved_arl`` and the implied
    limit multiplier are dimensionless and must be unchanged;
    ``sigma_estimate``/``ucl``/``lcl``/``cl`` are on the observation scale
    and must transform by the identical map.
    """
    # Arrange
    original_baseline = _baseline_from_scores(scores)
    transformed_baseline = _baseline_from_scores(
        [scale * score + shift for score in scores]
    )

    # Act
    original = fit_ewma(original_baseline, target_arl=_INVARIANCE_TARGET_ARL)
    transformed = fit_ewma(transformed_baseline, target_arl=_INVARIANCE_TARGET_ARL)

    # Assert -- dimensionless quantities unchanged
    assert transformed.achieved_arl == pytest.approx(original.achieved_arl, rel=1e-6)
    original_multiplier = _implied_limit_multiplier(
        original.ucl, original.cl, original.sigma_estimate, original.smoothing_param
    )
    transformed_multiplier = _implied_limit_multiplier(
        transformed.ucl,
        transformed.cl,
        transformed.sigma_estimate,
        transformed.smoothing_param,
    )
    assert transformed_multiplier == pytest.approx(original_multiplier, rel=1e-6)

    # Assert -- observation-scale quantities transform by the identical affine map
    assert transformed.sigma_estimate == pytest.approx(
        scale * original.sigma_estimate, rel=1e-6
    )
    assert transformed.cl == pytest.approx(scale * original.cl + shift, rel=1e-6)
    assert transformed.ucl == pytest.approx(scale * original.ucl + shift, rel=1e-6)
    assert transformed.lcl == pytest.approx(scale * original.lcl + shift, rel=1e-6)


__all__: list[str] = []
