"""Unit test for the shared moving-range sigma estimator, hoisted for BIN-94.

``caliper.baseline.domain.spc_numerics._moving_range_sigma`` is the same
estimator ``tests/unit/baseline/test_ewma_arl_published_values.py``'s
``test_moving_range_sigma_matches_a_hand_computed_value`` already pins,
reached there indirectly through ``fit_ewma``'s public ``sigma_estimate``
field. This file pins the **hoisted, shared** copy directly, per the BIN-94
scope addition:

    "`_moving_range_sigma` is shared, and its untestedness will propagate
    unless hoisted to a common module with its own dedicated test before
    CUSUM/Shewhart need it -- otherwise there will be three independently-
    untested copies of the same gap." (`code-reviewer` on BIN-65)

Testing the module-private function directly -- rather than only through a
public caller's output -- is deliberate, not an oversight: a helper reused
by more than one chart's calibration *and* reporting path is exactly the
shape that let BIN-65 ship two tautological checks (CLAUDE.md, "the trap
that caught BIN-65 twice"). Once ``fit_ewma`` and ``fit_cusum`` both delegate
to this one estimator, only a test that calls it directly -- independent of
either fitting function's own round-trip -- can catch a bug in it.

**Scaffold state (BIN-94 TDD red phase):**
``caliper.baseline.domain.spc_numerics._moving_range_sigma`` always raises
``NotImplementedError`` until ``domain-implementer`` completes the hoist
from ``ewma_fitting.py`` (see that scaffold's module docstring). This test
is expected to fail with that error, not to pass, until then.
"""

from __future__ import annotations

import math

import pytest

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD
from caliper.baseline.domain.spc_numerics import _moving_range_sigma
from caliper.errors import DegenerateBaselineError

# The unbiasing constant d_2 for a moving-range span of 2. Same citation
# chain as ewma_fitting.py's _MOVING_RANGE_D2 (Montgomery Appendix VI,
# cross-verified against three independent secondary sources reproducing
# the standard control-chart-constants table for n=2) -- reproduced here as
# a literal, exactly as test_ewma_arl_published_values.py does, so this
# file's expected value is computed from the published constant rather than
# imported from the module under test.
_MOVING_RANGE_D2 = 1.1283791670955126  # 2/sqrt(pi), exact


def test_moving_range_sigma_matches_a_hand_computed_value() -> None:
    """MR-bar / d2 on a sequence whose moving ranges are known by inspection.

    Identical arrangement to
    ``test_ewma_arl_published_values.test_moving_range_sigma_matches_a_hand_computed_value``:
    every consecutive pair differs by exactly 0.10, so the mean moving range
    is 0.10 and sigma is 0.10 / d2 -- computed here from the definition,
    never read back off any fitted artefact.
    """
    # Arrange -- alternating scores, so |consecutive difference| is 0.10
    # throughout and the mean moving range needs no arithmetic to predict.
    scores = [0.50, 0.60] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)

    # Act
    sigma = _moving_range_sigma(scores)

    # Assert
    expected_sigma = 0.10 / _MOVING_RANGE_D2
    assert sigma == pytest.approx(expected_sigma, rel=1e-9)


def test_moving_range_sigma_matches_a_hand_computed_value_for_irregular_diffs() -> None:
    """A second, independent hand-computed case with non-uniform differences.

    Guards against a formula that happens to be right only when every
    consecutive difference is identical (the first test's shape) -- e.g. a
    bug that used the range of the whole sequence rather than the mean of
    the consecutive absolute differences would coincidentally pass the
    uniform-difference case above but not this one.

    Sequence: 0.10, 0.40, 0.30, 0.70. Consecutive absolute differences:
    |0.40-0.10|=0.30, |0.30-0.40|=0.10, |0.70-0.30|=0.40. Mean moving range
    = (0.30 + 0.10 + 0.40) / 3 = 0.80 / 3.
    """
    # Arrange
    scores = [0.10, 0.40, 0.30, 0.70]

    # Act
    sigma = _moving_range_sigma(scores)

    # Assert
    expected_mean_moving_range = (0.30 + 0.10 + 0.40) / 3
    expected_sigma = expected_mean_moving_range / _MOVING_RANGE_D2
    assert sigma == pytest.approx(expected_sigma, rel=1e-9)


# --- Sad path: non-finite or zero moving-range aggregate (BIN-119) --------------
#
# External code review (Codex), 2026-09-11, reproduced. Both cases below were
# verified directly against this function, with real float64 arithmetic, before
# writing these tests -- no hand-computed expected value is asserted, because
# the point of both tests is that the *aggregate itself* is unusable (+inf or
# exactly 0.0), not a specific numeric outcome:
#
#   Half 1 -- alternating +/-1e308 (each individual value finite; `ScoringResult`
#   already enforces that -- but each consecutive difference is ~2e308, which
#   overflows float64's finite range): `_moving_range_sigma` currently returns
#   `float("inf")`, silently. Left unchecked, this lets `fit_ewma`/`fit_cusum`/
#   `fit_shewhart` all construct a "successfully fitted" artefact whose control
#   limits are +/-inf -- a chart that can never signal. That is this library's
#   worst possible failure mode: not a wrong answer, a confident, permanent
#   silence.
#
#   Half 2 -- one minimum positive subnormal (5e-324) among otherwise-identical
#   values (two distinct values, so the zero-variance guard in every fit_*()
#   function does not fire): every consecutive difference is so small that the
#   *mean* moving range underflows to exactly 0.0 in float64 arithmetic.
#   `_moving_range_sigma` currently returns `0.0`, silently. Left unchecked,
#   `Monitor.record()` against a CUSUM artefact fitted from this divides by
#   `sigma_estimate` and raises a raw `ZeroDivisionError` -- not a
#   `CaliperError` (ADR-002/ADR-008): no `category`, no `context` to branch
#   on. See `tests/unit/monitoring/test_monitor.py` for the direct
#   `Monitor.record()` reproduction, and `tests/unit/baseline/
#   test_ewma_fitting.py`/`test_cusum_fitting.py`/`test_shewhart_fitting.py`
#   for the same two cases exercised through each chart's public `fit_*()`
#   entry point -- confirmed empirically (not assumed) that all three charts
#   currently construct a bad artefact from both cases, not just CUSUM.
#
# This file's own docstring already frames `_moving_range_sigma` as
# deliberately having "no public entry point" -- its only callers are the
# three `fit_*()` functions, never an engineer directly -- so a
# `DegenerateBaselineError` raised here is not a foreign exception type
# escaping a public boundary; it propagates unchanged through whichever
# `fit_*()` called this function, exactly like the existing zero-variance
# guard those functions already apply to the raw scores before ever reaching
# this estimator.
#
# `reason` is descriptive, not a closed discriminator (CLAUDE.md: do not
# conflate it with `kind`) -- the two values below are this test file's own
# proposed contract, distinct from the existing `"zero_variance"` reason
# (which stays a separate, working guard -- see the existing test above:
# these are two *additional* guards, catching a different thing each,
# not a replacement for it). `domain-implementer` should confirm these two
# exact strings against `docs/domain-model.md`'s Error Contract Reference
# (neither is named there yet) or choose different ones and update this
# file plus every sibling fitting test file that also asserts on them,
# identically -- all four files must agree, since they all name the same
# guard, reused by all three chart types through this one shared module.
_NON_FINITE_SIGMA_REASON = "non_finite_sigma_estimate"
_SIGMA_UNDERFLOW_REASON = "sigma_estimate_underflow"


def test_raises_degenerate_baseline_error_when_aggregate_overflows_to_infinity() -> (
    None
):
    """Alternating near-float-max scores overflow the moving-range aggregate to +inf.

    Reproduces BIN-119 Half 1 directly against the shared estimator, not
    only through a fitting function's round-trip -- the same reasoning
    ``test_moving_range_sigma_matches_a_hand_computed_value`` above already
    gives for testing this function directly (a helper shared by three
    callers divides itself out of any assertion made only against one
    caller's public output).
    """
    # Arrange -- every individual value is finite; every consecutive
    # difference overflows float64's finite range.
    scores = [1e308, -1e308] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        _moving_range_sigma(scores)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _NON_FINITE_SIGMA_REASON


def test_raises_degenerate_baseline_error_when_aggregate_underflows_to_zero() -> None:
    """A real-but-tiny amount of variance underflows the moving-range aggregate to 0.0.

    Reproduces BIN-119 Half 2 directly against the shared estimator. Two
    distinct values are present (0.0 and the smallest positive subnormal
    float) -- this is not the zero-variance case
    (``test_moving_range_sigma_matches_a_hand_computed_value``'s siblings
    in the fitting test files cover that separately); the aggregate is
    unusable despite genuine variance existing in principle.
    """
    # Arrange -- one subnormal among otherwise-identical values.
    half = DEFAULT_SUFFICIENCY_THRESHOLD // 2
    scores = [0.0] * half + [5e-324] + [0.0] * (half - 1)
    assert len(set(scores)) == 2  # precondition: not the zero-variance case

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        _moving_range_sigma(scores)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _SIGMA_UNDERFLOW_REASON


def test_does_not_raise_for_an_ordinary_finite_positive_aggregate() -> None:
    """Guard: the new checks must not false-positive on an ordinary baseline.

    Regression check that the non-finite/underflow guards above are
    additional conditions, not a tightening of what counts as valid --
    this file's own existing hand-computed-value tests already prove this
    implicitly, but this test pins it as an explicit, named assertion of
    the negative case.
    """
    # Arrange
    scores = [0.50, 0.60] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)

    # Act
    sigma = _moving_range_sigma(scores)

    # Assert
    assert math.isfinite(sigma)
    assert sigma > 0.0
