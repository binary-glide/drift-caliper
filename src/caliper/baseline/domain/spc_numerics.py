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
``caliper.baseline.domain.ewma_fitting`` needs: a module whose only callers
are other domain modules, never an engineer, can be hooked without risking
``BeartypeCallHintParamViolation`` displacing a typed ``CaliperError`` at a
public boundary (see ``tests/conftest.py``'s beartype section for the full
reasoning). ``tests/conftest.py`` hooks this module for exactly that reason
-- neither ``ewma_fitting.fit_ewma`` nor ``cusum_fitting.fit_cusum`` is
hooked, since both are public entry points.

``_moving_range_sigma`` below is the working implementation, extracted
verbatim from ``ewma_fitting.py`` during BIN-94; ``fit_ewma`` and
``fit_cusum`` both delegate to it now, rather than each carrying an
independently-untested copy. See
``tests/unit/baseline/test_spc_numerics.py``, which pins its direct,
hand-computed behaviour -- the same assertion
``tests/unit/baseline/test_ewma_arl_published_values.py`` makes against
``fit_ewma``'s public ``sigma_estimate`` output, per that file's carried
finding: a helper reused for both calibration and reporting divides itself
out of any assertion made only on public output, so it must also be tested
directly.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Sequence

# The unbiasing constant d_2 for a moving-range span of 2 (consecutive
# individual observations).
#
# ⚠️ Left as the rounded published figure for now. It has an EXACT closed form
# and does not need a citation at all -- see BIN-95, where this was derived
# from first principles rather than inherited:
#
#     d2(n=2) = E[|X1 - X2|] for iid X1, X2 ~ N(0, 1)
#             = E|N(0, 2)|  =  sqrt(2) * sqrt(2/pi)  =  2 / sqrt(pi)
#             = 1.128379167...
#
# Verified against 20 million simulated pairs (agreeing to 0.03%, sampling
# error). Tables publish 1.128 because they are printed to four figures, not
# because the quantity is empirical.
#
# Using the rounded value over-estimates sigma by ~336 ppm, so every control
# limit derived from it is that fraction too wide. Negligible in practice and
# harmless in direction (slightly fewer false alarms, not more), but it is a
# free accuracy gain and it removes this project's dependency on a paywalled
# source. **BIN-95 should replace this with `2.0 / math.sqrt(math.pi)`** and
# drop the citation chain, since a derivation beats a citation.
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
    """
    moving_ranges = [abs(b - a) for a, b in itertools.pairwise(scores)]
    mean_moving_range = statistics.fmean(moving_ranges)
    return mean_moving_range / _MOVING_RANGE_D2
