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

import pytest

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD
from caliper.baseline.domain.spc_numerics import _moving_range_sigma

# The unbiasing constant d_2 for a moving-range span of 2. Same citation
# chain as ewma_fitting.py's _MOVING_RANGE_D2 (Montgomery Appendix VI,
# cross-verified against three independent secondary sources reproducing
# the standard control-chart-constants table for n=2) -- reproduced here as
# a literal, exactly as test_ewma_arl_published_values.py does, so this
# file's expected value is computed from the published constant rather than
# imported from the module under test.
_MOVING_RANGE_D2 = 1.128


def test_moving_range_sigma_matches_a_hand_computed_value() -> None:
    """MR-bar / d2 on a sequence whose moving ranges are known by inspection.

    Identical arrangement to
    ``test_ewma_arl_published_values.test_moving_range_sigma_matches_a_hand_computed_value``:
    every consecutive pair differs by exactly 0.10, so the mean moving range
    is 0.10 and sigma is 0.10 / 1.128 -- computed here from the definition,
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
