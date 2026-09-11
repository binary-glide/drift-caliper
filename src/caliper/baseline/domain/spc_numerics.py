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
import math
from collections.abc import Sequence

from caliper.errors import DegenerateBaselineError

# The unbiasing constant d_2 for a moving-range span of 2 (consecutive
# individual observations).
#
# **Derived, not cited.** d2 for a moving-range span of 2 has an exact closed
# form, so this project needs no source for it:
#
#     d2(n=2) = E[|X1 - X2|]  for iid X1, X2 ~ N(0, 1)
#             = E|N(0, 2)|  =  sqrt(2) * sqrt(2/pi)  =  2 / sqrt(pi)
#             = 1.128379167...
#
# Published tables give 1.128 because they are printed to four significant
# figures, not because the quantity was ever measured. BIN-65 originally
# reached it through a paywalled Montgomery lookup cross-verified against three
# secondary sources -- a citation chain guarding plain arithmetic. Derived from
# first principles on BIN-95 and checked against 20 million simulated pairs
# (agreeing to 0.03%, sampling error).
#
# Worth asking of any constant this project treats as published: some are
# measurements, some are arithmetic. Only the first kind needs a source.
#
# The rounded literal over-estimated sigma by ~336 ppm, making every derived
# control limit that fraction too wide -- negligible, and harmless in direction
# (slightly fewer false alarms rather than more), but there is no reason to
# carry it.
_MOVING_RANGE_D2 = 2.0 / math.sqrt(math.pi)
_MOVING_RANGE_METHOD = "moving_range"

# BIN-119: two additional degenerate-baseline conditions this estimator must
# reject, beyond the all-identical-scores case each fit_*() caller already
# rules out before ever reaching this function. Both are float64 arithmetic
# artefacts of the moving-range aggregate, not properties either caller's
# own zero-variance guard can see:
#
#   non-finite -- consecutive score differences overflow float64's finite
#   range (e.g. alternating +/-1e308), so the mean moving range -- and
#   therefore sigma -- comes back +inf. A chart calibrated from an infinite
#   sigma has control limits at +/-inf and can never signal: confident,
#   permanent silence, this library's worst failure mode.
#
#   underflow -- consecutive score differences are so small that their mean
#   underflows to exactly 0.0 despite genuine, non-zero variance existing in
#   principle (e.g. one subnormal float among otherwise-identical scores).
#   A chart calibrated from a zero sigma has ucl == lcl == baseline_mean --
#   collapsed control limits that turn the chart into a false-positive
#   machine for EWMA/Shewhart, and a raw ZeroDivisionError at CUSUM's
#   record()-time standardisation. A zero-width interval is never a
#   plausible value for a real quality characteristic's spread.
#
# `reason` is descriptive, not a closed discriminator -- see
# InvalidParameterError.kind's docstring for why the two keys are
# deliberately not unified. Distinct from the existing "zero_variance"
# reason each fit_*() function's own guard raises directly (unaffected --
# this module never sees an all-identical baseline, since that guard runs
# first): these are two *additional* guards, not a replacement.
_NON_FINITE_SIGMA_REASON = "non_finite_sigma_estimate"
_SIGMA_UNDERFLOW_REASON = "sigma_estimate_underflow"


def _overflow_safe_mean(values: Sequence[float]) -> float:
    """Exactly-rounded mean, tolerating a running sum that overflows float64.

    ``statistics.fmean`` delegates to ``math.fsum`` for its exactly-rounded
    result. ``fsum`` raises ``OverflowError`` when its *intermediate*
    (running) sum exceeds float64's finite range -- even when the true,
    final mean is itself perfectly representable (BIN-123). An alternating
    ``[1e307, 0.0, ...]`` sequence is the canonical example: the true sum
    (~7.5e308 for 150 such values) is not representable, but dividing by
    150 first would give ~5e306, comfortably representable.

    The ordinary path -- ``math.fsum(values) / len(values)`` -- is tried
    first and returned unchanged whenever it succeeds, so this function is
    bit-identical to ``statistics.fmean`` on every input that does not hit
    the overflow edge case. Precision cannot regress *by construction* for
    the common case; it is not merely expected to measure the same.

    On overflow, every value is scaled down by the same power of two before
    summing, and the sum is scaled back up by the same factor afterwards
    (after dividing by ``len(values)``, not before -- the *sum* is exactly
    what does not fit; the *mean* is what does). Multiplying by a power of
    two only shifts a float's exponent; the mantissa -- and therefore
    ``fsum``'s exact rounding -- is untouched, so this fallback is exact in
    a way that scaling by an arbitrary factor (``len(values)``, say) would
    not be: dividing each term by ``n`` first would round every term
    individually and give up ``fsum``'s exactness before it ever ran.

    The scale is the *smallest* power of two (found by trying successively
    larger shifts) that keeps the scaled sum finite. The smallest sufficient
    shift minimises how far every value is pushed towards zero -- an
    unnecessarily large one risks pushing a value that was normal before
    scaling into the subnormal range, and losing part or all of its
    contribution to the sum. A baseline whose dynamic range is wide enough
    that even the smallest sufficient shift still loses a value this way is
    not something this function can repair: at that point the input is at
    the edge of what float64 can represent at all, and the caller's own
    finite/positive check on the *result* (BIN-119) is the backstop for
    that, not this function.
    """
    try:
        return math.fsum(values) / len(values)
    except OverflowError:
        pass

    shift = 0
    while True:
        shift += 1
        scale = math.ldexp(1.0, -shift)
        scaled = [value * scale for value in values]
        try:
            scaled_sum = math.fsum(scaled)
        except OverflowError:
            continue
        return math.ldexp(scaled_sum / len(values), shift)


def _moving_range_sigma(scores: Sequence[float]) -> float:
    """Estimate short-term sigma from the mean moving range (span 2).

    ``scores`` must have at least one pair of unequal consecutive-difference
    contributions -- guaranteed by the time a caller reaches this, because
    the fitting operation calling it has already rejected an all-identical
    baseline (a baseline containing any two distinct values has at least one
    non-zero consecutive difference, so the mean moving range is strictly
    positive in exact arithmetic).

    That last clause is the reason this function validates its own result
    rather than trusting the caller's zero-variance guard to be sufficient:
    "strictly positive in exact arithmetic" does not imply "finite and
    strictly positive in float64 arithmetic" -- the aggregate can still
    overflow to ``inf`` or underflow to exactly ``0.0`` (BIN-119).

    Raises
    ------
    DegenerateBaselineError
        The moving-range aggregate is not finite
        (``context["reason"] == "non_finite_sigma_estimate"``), or it
        underflowed to exactly zero despite genuine variance in ``scores``
        (``context["reason"] == "sigma_estimate_underflow"``).
    """
    moving_ranges = [abs(b - a) for a, b in itertools.pairwise(scores)]
    mean_moving_range = _overflow_safe_mean(moving_ranges)
    sigma = mean_moving_range / _MOVING_RANGE_D2

    if not math.isfinite(sigma):
        raise DegenerateBaselineError(
            "the moving-range sigma estimate is not finite -- control "
            "limits calibrated from it would never signal",
            context={"reason": _NON_FINITE_SIGMA_REASON},
            recovery_hint=(
                "One or more consecutive scores in the baseline differ by "
                "an amount that overflows float64's finite range, so the "
                "moving-range sigma estimate came back infinite. Control "
                "limits built from an infinite sigma can never detect a "
                "deviation. Review the judge's score scale -- this usually "
                "means implausibly large-magnitude scores reached the "
                "baseline -- before fitting again."
            ),
        )
    if sigma <= 0.0:
        raise DegenerateBaselineError(
            "the moving-range sigma estimate underflowed to zero despite "
            "genuine variance in the baseline",
            context={"reason": _SIGMA_UNDERFLOW_REASON},
            recovery_hint=(
                "The baseline's consecutive score differences are so small "
                "that their mean underflowed to exactly 0.0 in float64 "
                "arithmetic, which would collapse the control limits onto "
                "the centre line and turn the chart into a false-positive "
                "machine. Collect observations with more meaningful score "
                "variation before fitting."
            ),
        )
    return sigma
