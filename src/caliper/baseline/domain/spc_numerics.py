"""Shared numerical primitives used by more than one chart-fitting module.

Hoisted out of ``caliper.baseline.domain.ewma_fitting`` during BIN-94, per the
scope addition recorded on that ticket:

    "`_moving_range_sigma` is shared, and its untestedness will propagate
    unless hoisted to a common module with its own dedicated test before
    CUSUM/Shewhart need it -- otherwise there will be three independently-
    untested copies of the same gap." (`code-reviewer` on BIN-65)

``sigma_estimate`` -- the moving-range-based estimator this module owns -- is
the shared-core quantity **all three chart types** (EWMA, CUSUM, Shewhart I-
chart) use for control-limit computation on individual observations
(``docs/domain-model.md``, "The Dual-Spread Distinction -- All Charts"). It is
NOT the same quantity as ``baseline_spread`` (the plain sample standard
deviation) -- see that section for the full distinction.

**Deliberately has no public entry point.** This is what lets `beartype`'s
dev-only runtime hook (BIN-109) cover this module without the carve-out
``caliper.baseline.domain.ewma_fitting`` currently needs: a module whose only
callers are other domain modules, never an engineer, can be hooked without
risking ``BeartypeCallHintParamViolation`` displacing a typed ``CaliperError``
at a public boundary (see ``tests/conftest.py``'s beartype section for the
full reasoning). Whether to actually add the hook here is
``domain-implementer``/`BIN-109`-adjacent scope -- this module only makes it a
*clean target* by staying entry-point-free.

**Scaffold only (BIN-94 TDD red phase).** ``_moving_range_sigma`` below always
raises ``NotImplementedError`` -- the real extraction (moving the working
implementation out of ``ewma_fitting.py`` and pointing both ``fit_ewma`` and
``fit_cusum`` at this module) is ``domain-implementer`` work, deliberately
left undone here so the already-green EWMA suite is not touched by a test-
writing pass. See ``tests/unit/baseline/test_spc_numerics.py``, which pins the
direct, hand-computed behaviour this function must reproduce once hoisted --
the same assertion ``tests/unit/baseline/test_ewma_arl_published_values.py``
already makes against ``fit_ewma``'s public ``sigma_estimate`` output, per
that file's carried finding: a helper reused for both calibration and
reporting divides itself out of any assertion made only on public output, so
it must also be tested directly.
"""

from __future__ import annotations

from collections.abc import Sequence

# The unbiasing constant d_2 for a moving-range span of 2 (consecutive
# individual observations). See
# ``caliper.baseline.domain.ewma_fitting``'s ``_MOVING_RANGE_D2`` for the full
# citation chain (Montgomery Appendix VI, cross-verified against three
# independent secondary sources) -- reproduced verbatim here rather than
# imported, so this module has no dependency on ``ewma_fitting`` in either
# direction once the hoist is complete.
_MOVING_RANGE_D2 = 1.128
_MOVING_RANGE_METHOD = "moving_range"


def _moving_range_sigma(scores: Sequence[float]) -> float:
    """Estimate short-term sigma from the mean moving range (span 2).

    ``scores`` must have at least one pair of unequal consecutive-difference
    contributions -- guaranteed by the time a caller reaches this, because
    the fitting operation calling it has already rejected an all-identical
    baseline (a baseline containing any two distinct values has at least one
    non-zero consecutive difference, so the mean moving range is strictly
    positive).

    Raises:
        NotImplementedError: always, in this scaffold. See module docstring.
    """
    raise NotImplementedError(
        "_moving_range_sigma is a BIN-94 scaffold -- domain-implementer "
        "completes the hoist from caliper.baseline.domain.ewma_fitting"
    )
