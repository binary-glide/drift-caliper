"""BIN-121 (part 1) -- widened Hypothesis strategies for extreme values.

Property-based tests asserting that fitting with extreme-but-finite
baseline scores either raises ``CaliperError`` (a legitimate rejection)
or returns a valid artefact with finite, well-formed fields. The
governing property, from BIN-121's ticket:

    Every public operation either returns an object satisfying all
    documented invariants or raises a documented domain exception --
    never a raw implementation exception and never a silently unusable
    result.

**Why these strategies are separate from ``tests/support/baseline_strategies.py``.**
That module's ``baseline_scores_strategy()`` draws from ``[-10, 10]`` -- a
realistic score range that exercises calibration correctness (BIN-84). These
strategies draw from the extremes of float64: values near ``+/-1e308``
whose pairwise differences overflow, subnormal values whose differences
underflow to zero, and signed zero. They are hostile inputs in BIN-121's
sense, not realistic baselines, and they must not pollute the shared
strategy the BIN-124 contract guard polices. ``baseline_from_scores`` is
imported from the shared module (not reimplemented) per BIN-124's one-
definition rule.

**What these tests cover that the exception-contract audit (part 2) does
not.** Part 2's registry exercises each entry point once with specific
hostile inputs. These property tests generate *many* inputs from a
parametric space and assert the same invariant across all of them, so a
future regression at a different point in the space is caught
automatically. The two are complementary, not overlapping.

**Runtime.** ``max_examples=50`` per test, ``derandomize=True`` for
deterministic runs. Six property tests (three charts x two strategy
categories) plus two direct edge-case tests and two confirmations = ~10
tests. Total runtime on a modern laptop: under 10 seconds.

**Expected outcome.** All tests are expected to PASS against current
``src/`` -- the BIN-119 fix handles the overflow and underflow cases
these strategies exercise. They serve as regression guards: a future
change to ``_moving_range_sigma``, ``_overflow_safe_mean``, or any
fitting function that weakens or removes those guards will make these
tests fail.

See also:

- ``tests/unit/baseline/test_baseline_scores_strategy_contract.py`` --
  BIN-124's guard, which polices the *shared* strategies, not these.
- ``tests/unit/baseline/test_joint_parameter_validity.py`` -- BIN-122,
  which covers legal-but-extreme *parameters*. This file covers
  extreme *baseline scores*.
- ``tests/unit/baseline/test_fitted_artefact_sigma_invariant.py`` --
  BIN-119's sigma invariant at the artefact level.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from drift_caliper.errors import CaliperError
from drift_caliper.measurement import ScoringResult
from tests.support.baseline_strategies import baseline_from_scores

# ---------------------------------------------------------------------------
# Target ARL shared across all property tests -- its value carries no
# statistical meaning here, matching the convention established by
# test_ewma_fitting.py / test_cusum_fitting.py / test_shewhart_fitting.py.
# ---------------------------------------------------------------------------

_SHAPE_TEST_TARGET_ARL = 370.0

# ---------------------------------------------------------------------------
# Extreme-value strategies
#
# Each builds a list of DEFAULT_SUFFICIENCY_THRESHOLD finite floats
# designed to exercise a specific numerical edge case. None of these
# values are NaN or inf -- those are already rejected at the
# ScoringResult boundary (ADR-006), confirmed below.
# ---------------------------------------------------------------------------


@st.composite
def overflow_prone_scores(
    draw: st.DrawFn,
    size: int = DEFAULT_SUFFICIENCY_THRESHOLD,
) -> list[float]:
    """Scores near the extremes of float64 whose pairwise differences overflow.

    Alternating large-positive and large-negative values produce
    consecutive differences that exceed ``sys.float_info.max``, so the
    moving-range aggregate overflows to ``inf``. BIN-119 catches this
    and raises ``DegenerateBaselineError`` -- these tests assert that
    guarantee holds property-wide, not just at the two hand-picked
    values in the regression test.
    """
    scores: list[float] = []
    for _ in range(size):
        score = draw(
            st.one_of(
                st.floats(
                    min_value=1e300,
                    max_value=sys.float_info.max,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                st.floats(
                    min_value=-sys.float_info.max,
                    max_value=-1e300,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            )
        )
        scores.append(score)
    return scores


@st.composite
def underflow_prone_scores(
    draw: st.DrawFn,
    size: int = DEFAULT_SUFFICIENCY_THRESHOLD,
) -> list[float]:
    """Scores with pairwise differences that underflow to zero.

    A baseline of mostly-identical values with a few subnormal
    perturbations produces consecutive differences so small that the
    mean moving range underflows to exactly ``0.0`` in float64
    arithmetic. BIN-119 catches this and raises
    ``DegenerateBaselineError``.
    """
    # Anchor: the value most scores share (may be zero or non-zero).
    anchor = draw(st.sampled_from([0.0, -0.0, 1.0, -1.0, 1e-100]))
    # How many perturbations to inject (1..5 out of `size`).
    n_perturbed = draw(st.integers(min_value=1, max_value=min(5, size)))
    # The perturbation magnitude: subnormal or near-subnormal.
    perturbation = draw(
        st.floats(
            min_value=5e-324,
            max_value=1e-308,
            allow_nan=False,
            allow_infinity=False,
            allow_subnormal=True,
        )
    )

    scores = [anchor] * size
    # Inject perturbations at random positions.
    positions = draw(
        st.lists(
            st.integers(min_value=0, max_value=size - 1),
            min_size=n_perturbed,
            max_size=n_perturbed,
            unique=True,
        )
    )
    for pos in positions:
        scores[pos] = anchor + perturbation

    return scores


@st.composite
def signed_zero_scores(
    draw: st.DrawFn,
    size: int = DEFAULT_SUFFICIENCY_THRESHOLD,
) -> list[float]:
    """Scores mixing ``0.0`` and ``-0.0``.

    In IEEE 754, ``0.0 == -0.0`` is ``True`` and ``abs(0.0 - (-0.0))``
    is ``0.0``, so a baseline of mixed signed zeros has zero moving
    range. This should be caught by the zero-variance or sigma-underflow
    guard. One non-zero score is optionally injected so the test also
    exercises the near-degenerate case.
    """
    n_nonzero = draw(st.integers(min_value=0, max_value=min(3, size)))
    scores: list[float] = []
    for i in range(size):
        if i < n_nonzero:
            scores.append(
                draw(
                    st.floats(
                        min_value=1e-310,
                        max_value=1e-300,
                        allow_nan=False,
                        allow_infinity=False,
                        allow_subnormal=True,
                    )
                )
            )
        else:
            scores.append(draw(st.sampled_from([0.0, -0.0])))
    # Shuffle so the non-zero values aren't always at the front.
    draw(st.randoms(use_true_random=False)).shuffle(scores)
    return scores


# ---------------------------------------------------------------------------
# The fit-or-CaliperError property
# ---------------------------------------------------------------------------


def _assert_fit_or_caliper_error(
    fit_fn: Callable[[Baseline], FittedControlLimits],
    scores: list[float],
) -> None:
    """Assert the fit-or-CaliperError property for one chart and one baseline.

    Either the fit raises ``CaliperError`` (a legitimate rejection -- any
    subtype is acceptable), or the returned artefact satisfies the
    documented invariants on its shared-core fields:

    * ``sigma_estimate`` is finite and positive (BIN-119 artefact invariant)
    * ``achieved_arl`` is finite and positive
    * ``baseline_mean`` is finite

    A non-``CaliperError`` exception (``OverflowError``,
    ``ZeroDivisionError``, ``ValueError``, etc.) is the failure this
    property exists to catch. It propagates as a test error.
    """
    baseline = baseline_from_scores(scores)
    try:
        artefact = fit_fn(baseline)
    except CaliperError:
        return  # Legitimate rejection -- any subtype

    # ⚠️ This early return is what makes the property vacuous if every draw
    # is rejected: the postconditions below would never run and the test
    # would degrade to "no raw exception escaped", while reading as though
    # it also checked the artefact. Measured 2026-09-13 (50 examples,
    # derandomised, identical across all three charts because the rejection
    # happens at sigma estimation, before any chart-specific work):
    #
    #     overflow      2/50 fit,  48 DegenerateBaselineError
    #     underflow    21/50 fit,  29 DegenerateBaselineError
    #     signed_zero  42/50 fit,   8 DegenerateBaselineError
    #
    # All three exercise both branches, so the postconditions have power.
    # `overflow` is the thin one -- if a future rejection in `src/` narrows
    # the legal space further it could reach zero, and this property would
    # weaken silently rather than fail. Re-measure before trusting it after
    # any such change (the BIN-124 class of drift, in a different guise).

    # If the fit succeeded, verify the artefact is well-formed.
    assert math.isfinite(artefact.sigma_estimate), (
        f"sigma_estimate is {artefact.sigma_estimate}, not finite"
    )
    assert artefact.sigma_estimate > 0, (
        f"sigma_estimate is {artefact.sigma_estimate}, not positive"
    )
    assert math.isfinite(artefact.achieved_arl), (
        f"achieved_arl is {artefact.achieved_arl}, not finite"
    )
    assert artefact.achieved_arl > 0, (
        f"achieved_arl is {artefact.achieved_arl}, not positive"
    )
    assert math.isfinite(artefact.baseline_mean), (
        f"baseline_mean is {artefact.baseline_mean}, not finite"
    )


# ---------------------------------------------------------------------------
# Overflow-prone baselines -- all three charts
# ---------------------------------------------------------------------------


@given(scores=overflow_prone_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_ewma_handles_overflow_prone_scores(scores: list[float]) -> None:
    """EWMA: overflow-prone baseline → fit or CaliperError, never a raw exception."""
    _assert_fit_or_caliper_error(
        lambda b: fit_ewma(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


@given(scores=overflow_prone_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_cusum_handles_overflow_prone_scores(scores: list[float]) -> None:
    """CUSUM: overflow-prone baseline → fit or CaliperError, never a raw exception."""
    _assert_fit_or_caliper_error(
        lambda b: fit_cusum(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


@given(scores=overflow_prone_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_shewhart_handles_overflow_prone_scores(scores: list[float]) -> None:
    """Shewhart: overflow-prone baseline -- fit or CaliperError."""
    _assert_fit_or_caliper_error(
        lambda b: fit_shewhart(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


# ---------------------------------------------------------------------------
# Underflow-prone baselines -- all three charts
# ---------------------------------------------------------------------------


@given(scores=underflow_prone_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_ewma_handles_underflow_prone_scores(scores: list[float]) -> None:
    """EWMA: underflow-prone baseline → fit or CaliperError, never a raw exception."""
    _assert_fit_or_caliper_error(
        lambda b: fit_ewma(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


@given(scores=underflow_prone_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_cusum_handles_underflow_prone_scores(scores: list[float]) -> None:
    """CUSUM: underflow-prone baseline → fit or CaliperError, never a raw exception."""
    _assert_fit_or_caliper_error(
        lambda b: fit_cusum(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


@given(scores=underflow_prone_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_shewhart_handles_underflow_prone_scores(scores: list[float]) -> None:
    """Shewhart: underflow-prone baseline -- fit or CaliperError."""
    _assert_fit_or_caliper_error(
        lambda b: fit_shewhart(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


# ---------------------------------------------------------------------------
# Signed-zero baselines -- all three charts
# ---------------------------------------------------------------------------


@given(scores=signed_zero_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_ewma_handles_signed_zero_scores(scores: list[float]) -> None:
    """EWMA: signed-zero baseline → fit or CaliperError, never a raw exception."""
    _assert_fit_or_caliper_error(
        lambda b: fit_ewma(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


@given(scores=signed_zero_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_cusum_handles_signed_zero_scores(scores: list[float]) -> None:
    """CUSUM: signed-zero baseline → fit or CaliperError, never a raw exception."""
    _assert_fit_or_caliper_error(
        lambda b: fit_cusum(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


@given(scores=signed_zero_scores())
@settings(max_examples=50, deadline=None, derandomize=True)
def test_fit_shewhart_handles_signed_zero_scores(scores: list[float]) -> None:
    """Shewhart: signed-zero baseline → fit or CaliperError, never a raw exception."""
    _assert_fit_or_caliper_error(
        lambda b: fit_shewhart(b, target_arl=_SHAPE_TEST_TARGET_ARL), scores
    )


# ---------------------------------------------------------------------------
# Direct edge-case tests -- hand-picked BIN-119 regression inputs
#
# These are the exact inputs from BIN-119 that broke before the fix.
# Written as deterministic unit tests (not Hypothesis) to serve as
# stable regression anchors alongside the property tests above.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chart", "fit_fn"),
    [("ewma", fit_ewma), ("cusum", fit_cusum), ("shewhart", fit_shewhart)],
)
def test_alternating_1e300_fits_with_finite_postconditions(
    chart: str, fit_fn: Callable[..., FittedControlLimits]
) -> None:
    """Alternating ±1e300 fits, and every reported figure stays finite.

    ⚠️ **This exists to stop the overflow property weakening silently**, a
    concern `code-reviewer` raised and the measurement above quantifies:
    only ~2 of 50 overflow-prone draws reach the fit path, so the
    postconditions there ride on a thin margin. A future rejection that
    narrowed the legal space could take that to zero, and
    ``_assert_fit_or_caliper_error`` would then pass on the reject branch
    every time -- still green, no longer checking the artefact.

    **This is the same shape one order of magnitude down.** Alternating
    ±1e308 overflows its moving range and is refused
    (``test_alternating_1e308_raises_caliper_error_not_overflow``, the
    BIN-119 anchor); ±1e300 does not, and must fit cleanly. Together they
    pin **both sides** of that boundary deterministically, so neither can
    drift unobserved.
    """
    baseline = baseline_from_scores([1e300 if i % 2 else -1e300 for i in range(100)])

    artefact = fit_fn(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    assert math.isfinite(artefact.sigma_estimate)
    assert artefact.sigma_estimate > 0
    assert math.isfinite(artefact.baseline_mean)
    assert math.isfinite(artefact.achieved_arl)
    assert artefact.achieved_arl > 0


def test_alternating_1e308_raises_caliper_error_not_overflow() -> None:
    """BIN-119 regression: alternating +/-1e308 overflows the moving-range
    aggregate to inf. Must raise DegenerateBaselineError (a CaliperError),
    not a raw OverflowError or produce an artefact with sigma=inf.
    """
    scores = [1e308, -1e308] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)
    baseline = baseline_from_scores(scores)

    with pytest.raises(CaliperError) as exc_info:
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    assert exc_info.value.category == "degenerate_baseline"
    assert exc_info.value.context["reason"] == "non_finite_sigma_estimate"


def test_one_subnormal_among_zeros_raises_caliper_error_not_zerodiv() -> None:
    """BIN-119 regression: one subnormal (5e-324) among zeros underflows
    the moving-range sigma to 0.0. Must raise DegenerateBaselineError,
    not a raw ZeroDivisionError at CUSUM's standardisation.
    """
    scores = [0.0] * (DEFAULT_SUFFICIENCY_THRESHOLD - 1) + [5e-324]
    baseline = baseline_from_scores(scores)

    with pytest.raises(CaliperError) as exc_info:
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    assert exc_info.value.category == "degenerate_baseline"
    assert exc_info.value.context["reason"] == "sigma_estimate_underflow"


# ---------------------------------------------------------------------------
# Confirmation -- ScoringResult rejects NaN and inf at the boundary
#
# ADR-006: score must be finite. These PASS (the guard is in place).
# Included to confirm the guarantee holds at the value-object level,
# before any fitting code runs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_score",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "inf", "-inf"],
)
def test_scoring_result_rejects_non_finite_score(bad_score: float) -> None:
    """ADR-006 confirmation: ScoringResult's field validator rejects
    NaN and inf. No fitting function needs to guard against them.
    """
    from drift_caliper.measurement import ModelVersion, Provenance, ScoringCriteria

    with pytest.raises(CaliperError) as exc_info:
        ScoringResult(
            score=bad_score,
            reasoning="test",
            provenance=Provenance(
                model_version=ModelVersion(value="v1"),
                scoring_criteria=ScoringCriteria(value="rubric"),
            ),
        )

    assert exc_info.value.category == "invalid_parameter"
