"""``fit_ewma`` -- fit EWMA control limits from a Phase I baseline (BIN-65).

See ``docs/domain-model.md`` (Library Operations -- Fit EWMA) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
section 5 for the fitting signature shape and parameter semantics, and
ADR-001/ADR-003 for the calibration method (Markov-chain approximation,
Lucas & Saccucci 1990).

``fit_ewma`` is this module's only public entry point. The Markov-chain
calibration machinery it calls -- ``_calibrate_limit_multiplier``,
``_in_control_arl``, ``_ewma_asymptotic_std_ratio``, and the method's full
derivation and verification -- live in ``caliper.baseline.domain.ewma_numerics``
(split out under BIN-130, mirroring the ``spc_numerics``/BIN-94 hoist), so
that the dev-only beartype import hook (BIN-109, ``tests/conftest.py``) can
guard the numerics without ever guarding this public boundary. See that
module's docstring for the calibration method and its verification against
Lucas & Saccucci (1990) Table 3.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from caliper.baseline.domain.baseline import Baseline
from caliper.baseline.domain.ewma_numerics import (
    _calibrate_limit_multiplier,
    _ewma_asymptotic_std_ratio,
)
from caliper.baseline.domain.fitted_ewma import FittedEWMA
from caliper.baseline.domain.fitting_advisory import FittingAdvisory
from caliper.baseline.domain.parameter_guards import (
    MIN_TARGET_ARL,
    classify_target_arl,
    require_real_number,
    require_type,
)
from caliper.baseline.domain.spc_numerics import (
    _moving_range_sigma,
    _overflow_safe_mean,
)
from caliper.errors import (
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)

# --- Smoothing parameter (lambda) valid range -------------------------------
#
# The EWMA statistic itself is defined for 0 < lambda <= 1 (Roberts 1959;
# Hunter 1986; Lucas & Saccucci 1990 sec. 2) -- lambda=1 degenerates to a
# Shewhart individuals chart (only the most recent observation matters),
# lambda=0 is undefined (no weight ever falls on a new observation).
# Confirmed against the NIST/SEMATECH e-Handbook of Statistical Methods,
# section 6.3.2.4 ("EWMA Control Charts"): "the valid range for lambda is
# 0 < lambda <= 1". MAX_SMOOTHING_PARAM = 1.0 follows directly from that
# closed upper bound.
MAX_SMOOTHING_PARAM = 1.0

# MIN_SMOOTHING_PARAM has no smallest element to inherit from the chart's own
# mathematical definition -- (0, 1] is open at zero -- so a library
# implementation must choose a concrete floor. This is an engineering
# default, not a published constant, chosen for two reasons:
#
# 1. It must not exclude lambda=0.03, the smaller of the two (lambda, L)
#    pairs this story's own numerical proof verifies against Lucas &
#    Saccucci (1990) Table 3 (see test_ewma_arl_published_values.py) --
#    Table 3 itself tabulates lambda values at least that small, so 0.03 is
#    inside the range the primary source treats as meaningful.
# 2. An EWMA's weight on an observation k steps in the past decays as
#    (1 - lambda)^k, so its half-life is ln(2) / -ln(1 - lambda)
#    observations -- a direct algebraic consequence of the recursion, not a
#    citation-requiring constant. At lambda = 0.01 that half-life is
#    approximately 69 observations, already comparable to
#    DEFAULT_SUFFICIENCY_THRESHOLD (100, ADR-005) -- the library's own floor
#    for a usable Phase I baseline. A smaller lambda would need a baseline
#    larger than the library's own recommended minimum just for the chart's
#    memory to be shorter than the data it was calibrated from, which is not
#    a useful default to allow silently.
MIN_SMOOTHING_PARAM = 0.01

# --- Library default smoothing parameter ------------------------------------
#
# ADR-004 section 5: "smoothing_param (EWMA) ... Optional. None uses library
# default" -- deliberately left unpinned by the ADR (ADR-001's "no numerical
# constants" discipline). The NIST/SEMATECH e-Handbook of Statistical
# Methods, section 6.3.2.4, states: "The value of lambda is usually set
# between 0.2 and 0.3 (Hunter, 1986) although this choice is somewhat
# arbitrary." 0.2 is the low end of that commonly-cited range -- consistent
# with Lucas & Saccucci's (1990) own discussion that small lambda affords
# better sensitivity to small, sustained shifts (the failure mode Caliper
# exists to catch: gradual agent quality drift, not a single anomalous
# response), at some cost to large-shift responsiveness.
DEFAULT_SMOOTHING_PARAM = 0.2

# --- False alarm tolerance (target ARL0) meaningful range -------------------
#
# MIN_COHERENT_ARL = 1.0 is not an engineering choice -- it is a
# mathematical floor. ARL0 is defined as the expectation of a stopping time
# (the count of in-control observations until the first false alarm), and
# that count is a positive integer -- it is always at least 1, because the
# very first observation is itself a trial that can trigger an alarm.
# E[N] >= 1 for any N supported on {1, 2, 3, ...} follows directly from the
# definition of expectation; no value below 1 is a coherent ARL0 to request.
#
# Renamed from MIN_MEANINGFUL_ARL under ADR-011 (2026-09-12): this constant
# was correctly derived but wrongly named -- it names the smallest
# *arithmetically coherent* ARL0, not the smallest *useful* one, and the gap
# between those two claims is exactly what let target_arl=1.0 fit
# "successfully" while alarming on nearly every in-control observation
# (BIN-131). It is no longer the enforced lower bound on target_arl -- that
# is now caliper.baseline.domain.parameter_guards.MIN_TARGET_ARL (100.0),
# ADR-011's hard floor, a much stronger claim ("the field tabulates nothing
# smaller") than this one ("the arithmetic is still coherent"). This
# constant is kept, unused in the validation path below, purely for its
# derivation -- ADR-011 requires keeping the comment verbatim.
#
# Internal-only: absent from both caliper.__all__ and
# caliper.baseline.__all__, and not reachable via hasattr on either package
# (test_baseline_package_exports.py pins this) -- so renaming it carries no
# deprecation burden.
MIN_COHERENT_ARL = 1.0

# MAX_MEANINGFUL_ARL has no comparable mathematical ceiling -- ARL0 grows
# without bound as L -> infinity. 1,000,000 is an engineering default, not a
# published constant: at any realistic scoring cadence this already
# represents a false alarm tolerance of years to millennia (e.g. roughly
# 2,700 years of daily scoring), well past the point where a larger number
# is practically distinguishable, and it keeps the calibration's root-finder
# search bracket (see _calibrate_limit_multiplier) bounded rather than
# needing to expand indefinitely.
MAX_MEANINGFUL_ARL = 1_000_000.0

# --- Moving-range sigma estimation -------------------------------------------
#
# Hoisted to ``caliper.baseline.domain.spc_numerics`` during BIN-94 -- see
# that module's docstring for the full citation chain (Montgomery Appendix
# VI, d_2 = 1.128 for a moving-range span of 2 -- superseded on BIN-95 by the
# exact closed form 2/sqrt(pi); see spc_numerics) and
# ``tests/unit/baseline/test_spc_numerics.py`` for its direct test. Both
# ``fit_ewma`` and ``fit_cusum`` delegate to the one shared estimator now,
# rather than each carrying an independently-untested copy.
_MOVING_RANGE_METHOD = "moving_range"

_CHART_TYPE = "ewma"
_CALIBRATION_METHOD = "markov_chain"

_ZERO_VARIANCE_REASON = "zero_variance"


# --- Parameter validation ----------------------------------------------------


def _require_target_arl(
    target_arl: float | None,
) -> tuple[float, FittingAdvisory | None]:
    """Validate ``target_arl``, returning it narrowed to ``float`` plus any advisory.

    ``target_arl`` is optional in the Python signature but required by
    Caliper's validation (ADR-004 section 5, closing ADR-002's open
    dependency): omitting it is a classifiable ``CaliperError``, never
    Python's ``TypeError``. Returning the validated value (rather than
    ``None``) lets callers avoid a redundant ``is None`` narrowing check
    after this function has already ruled that case out.

    The range check itself, and the ADR-011 flagged-tier disclosure, are
    delegated to ``parameter_guards.classify_target_arl`` -- shared verbatim
    with ``cusum_fitting``/``shewhart_fitting`` rather than tripled, per the
    BIN-124 lesson about identical validation logic drifting out of sync
    across the three fitting modules.
    """
    constraint = f"must be a finite float in [{MIN_TARGET_ARL}, {MAX_MEANINGFUL_ARL}]"
    if target_arl is None:
        raise InvalidParameterError(
            "target_arl is required to fit EWMA control limits",
            context={
                "parameter": "target_arl",
                "constraint": constraint,
                "kind": "missing",
            },
            recovery_hint=(
                "Specify target_arl explicitly -- the in-control ARL0 (false "
                "alarm tolerance) you want the fitted chart to achieve, e.g. "
                "370 or 500. Caliper will not choose this on your behalf: it "
                "is a statistical commitment the engineer must own."
            ),
        )
    # BIN-126: reject a bool or a non-numeric value (e.g. a string) before
    # any arithmetic comparison is attempted against it -- see
    # parameter_guards.require_real_number's docstring for why this is a
    # behavioural, not nominal, check. Mirrors
    # cusum_fitting._require_target_arl/shewhart_fitting._require_target_arl.
    numeric_target_arl = require_real_number(
        target_arl, parameter="target_arl", constraint=constraint
    )
    # ADR-011: refuses below MIN_TARGET_ARL (100) or above MAX_MEANINGFUL_ARL;
    # returns a FittingAdvisory when inside [MIN_TARGET_ARL, VERIFIED_ARL_FLOOR).
    advisory = classify_target_arl(
        numeric_target_arl, max_target_arl=MAX_MEANINGFUL_ARL
    )
    return numeric_target_arl, advisory


def _validate_smoothing_param(smoothing_param: float | None) -> float | None:
    """Validate a supplied ``smoothing_param``, narrowed to ``float`` if given.

    ``smoothing_param`` is genuinely optional -- ``None`` is not validated
    here at all; ``fit_ewma`` substitutes ``DEFAULT_SMOOTHING_PARAM``.
    Mirrors ``cusum_fitting._validate_reference_value`` -- the other
    optional, single-tuning-parameter chart.
    """
    if smoothing_param is None:
        return None
    constraint = (
        f"must be a finite float in [{MIN_SMOOTHING_PARAM}, {MAX_SMOOTHING_PARAM}]"
    )
    # BIN-126: reject a bool or a non-numeric value before any arithmetic
    # comparison is attempted against it.
    numeric_smoothing_param = require_real_number(
        smoothing_param, parameter="smoothing_param", constraint=constraint
    )
    if not math.isfinite(numeric_smoothing_param) or not (
        MIN_SMOOTHING_PARAM <= numeric_smoothing_param <= MAX_SMOOTHING_PARAM
    ):
        raise InvalidParameterError(
            "smoothing_param is outside the valid range",
            context={
                "parameter": "smoothing_param",
                "constraint": constraint,
                "kind": "invalid",
                "provided": smoothing_param,
            },
            recovery_hint=(
                "Choose a smoothing_param within "
                f"[{MIN_SMOOTHING_PARAM}, {MAX_SMOOTHING_PARAM}], or omit it "
                f"entirely to use the library default ({DEFAULT_SMOOTHING_PARAM})."
            ),
        )
    return numeric_smoothing_param


# --- Baseline statistics ------------------------------------------------------


def _has_zero_variance(scores: Sequence[float]) -> bool:
    """Report whether every score in ``scores`` is identical."""
    return len(set(scores)) <= 1


# --- Public API ----------------------------------------------------------------


def fit_ewma(
    baseline: Baseline,
    *,
    target_arl: float | None = None,
    smoothing_param: float | None = None,
) -> FittedEWMA:
    """Fit EWMA control limits from ``baseline`` (BIN-65).

    Validates parameters first (fail fast), then enforces baseline
    sufficiency by calling ``baseline.check_sufficiency()`` internally
    (OQ-3: this fitting operation owns enforcement rather than duplicating
    BIN-64's threshold logic in a second guard -- both designs the feature
    file names are consistent with its scenarios, since none of them assert
    on the mechanism), then refuses a zero-variance baseline, then
    calibrates the control-limit multiplier via a Brook & Evans (1972)
    Markov-chain approximation (see module docstring) and reports both the
    requested and achieved false alarm tolerance on the returned artefact.

    Parameters
    ----------
    baseline
        The Phase I baseline to fit from.
    target_arl
        The target in-control ARL0 (false alarm tolerance). Optional in
        the signature, required by validation -- omitting it raises
        ``InvalidParameterError`` with ``context["kind"] == "missing"``.
    smoothing_param
        The EWMA smoothing parameter (lambda). ``None`` uses
        ``DEFAULT_SMOOTHING_PARAM``.

    Returns
    -------
    FittedEWMA
        The fitted artefact. Carries a non-empty ``advisories`` when
        ``target_arl`` is inside ADR-011's flagged tier (``[100, 370)``) --
        see that ADR for why this fits rather than refuses.

    Raises
    ------
    InvalidParameterError
        ``baseline`` is not a ``Baseline``; ``target_arl`` is missing,
        not a real number (``bool`` included), or outside
        ``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]`` (ADR-011); or
        ``smoothing_param`` is supplied but not a real number (``bool``
        included) or outside ``[MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM]``
        (BIN-126).
    InsufficientBaselineError
        ``baseline`` does not meet the sufficiency threshold (BIN-65
        A1/BR-1).
    DegenerateBaselineError
        Every observation in ``baseline`` has an identical score (BIN-65
        A2/BR-2).

    References
    ----------
    .. [1] Lucas, J. M. and Saccucci, M. S. (1990). "Exponentially Weighted
           Moving Average Control Schemes: Properties and Enhancements."
           Technometrics, 32(1), 1-12.
    """
    # BIN-126: reject a wrong-typed baseline before any attribute on it is
    # accessed -- previously left to leak AttributeError the moment
    # `baseline.check_sufficiency()` below was reached. Mirrors
    # cusum_fitting.fit_cusum/shewhart_fitting.fit_shewhart.
    baseline = require_type(
        baseline, Baseline, parameter="baseline", type_name="Baseline"
    )
    validated_target_arl, target_arl_advisory = _require_target_arl(target_arl)
    validated_smoothing_param = _validate_smoothing_param(smoothing_param)
    effective_smoothing_param = (
        validated_smoothing_param
        if validated_smoothing_param is not None
        else DEFAULT_SMOOTHING_PARAM
    )

    sufficiency = baseline.check_sufficiency()
    if not sufficiency.is_sufficient:
        raise InsufficientBaselineError(
            "baseline does not have enough observations to fit EWMA control "
            "limits reliably",
            context={
                "have": sufficiency.observation_count,
                "need": sufficiency.threshold,
            },
            recovery_hint=(
                "Collect more observations before fitting -- record "
                f"at least {sufficiency.gap} more scoring results with "
                "Baseline.record() to reach the sufficiency threshold."
            ),
        )

    scores = [observation.score for observation in baseline.observations]
    if _has_zero_variance(scores):
        raise DegenerateBaselineError(
            "baseline has zero score variance -- EWMA control limits cannot "
            "be fitted from it",
            context={"reason": _ZERO_VARIANCE_REASON},
            recovery_hint=(
                "Every recorded observation has an identical score, so "
                "fitted control limits would collapse to the centre line "
                "and be unable to detect any deviation. Collect "
                "observations that reflect the agent's genuine output "
                "variation before fitting."
            ),
        )

    # statistics.fmean(scores) would raise OverflowError here on a baseline
    # whose running sum overflows float64 even though the mean itself is
    # representable (BIN-123) -- see _overflow_safe_mean's docstring.
    baseline_mean = _overflow_safe_mean(scores)
    baseline_spread = statistics.stdev(scores)
    sigma_estimate = _moving_range_sigma(scores)

    # `float(...)` here is a boundary normalisation, not a validation step:
    # `effective_smoothing_param`/`validated_target_arl` may be a plain `int`
    # or a numpy scalar (`np.float32`, `np.int64`, ...) that this function
    # has always accepted -- only `ewma_numerics`'s own functions are
    # beartype-hooked (BIN-130), and their `float` annotations reject
    # anything that is not literally a `float` instance under beartype's
    # default `is_pep484_tower=False`. Without this cast, a plain
    # `target_arl=370` would raise `BeartypeCallHintParamViolation` inside
    # this dev-only-hooked test suite while working fine in the shipped
    # wheel (which never imports beartype) -- exactly the load-order
    # instability BIN-130 exists to close, just one call frame deeper than
    # `fit_ewma`'s own signature. A pure module move alone did not close
    # it; this cast is what does.
    #
    # This also makes `fit_ewma` consistent with `fit_cusum`/`fit_shewhart`,
    # which normalise their own numeric parameters to `float` at their
    # boundary via `caliper.baseline.domain.parameter_guards.require_real_number`
    # (BIN-126). `fit_ewma` now carries the identical guard --
    # `_require_target_arl`/`_validate_smoothing_param` both call
    # `require_real_number`, so `validated_target_arl`/
    # `effective_smoothing_param` already arrive here narrowed to a plain
    # `float` (never a bool, never a bare numpy scalar) before this line
    # ever runs. That makes the `float(...)` cast below redundant for the
    # gap it was originally added to close, but it is left in place rather
    # than removed: it costs nothing applied to an already-`float` value,
    # it keeps this call site correct independently of
    # `_require_target_arl`'s own implementation, and the *widening*
    # behaviour -- np.float32 promoted to float64 crossing this boundary --
    # is the same shape all three charts share via the NEP 50 reasoning
    # below. `float()` never rejects anything `fit_ewma` itself accepts and
    # is exact for every numeric type already in the acceptance matrix (int,
    # np.float64, np.float32 promotion, np.int64) -- verified directly
    # against `test_ewma_arl_published_values.py`, not assumed: identical
    # `achieved_arl` before and after for every input already exercised as
    # a plain Python `float`, since `float(x) is x`-equivalent (bit-exact)
    # whenever `x` already is one.
    #
    # 🔍 The stronger reason, found by code-reviewer on BIN-130 and worth
    # recording because it is not obvious: numpy's NEP 50 weak promotion
    # keeps `1.0 - np.float32(x)` in **float32**. Without this cast a single
    # float32 smoothing parameter would silently demote the whole
    # Markov-chain calibration to single precision -- measured at 2.69e-12
    # relative drift in `achieved_arl`. So the cast is a precision
    # *safeguard*, not merely a convention match: it stops one narrow input
    # type from changing the width of every subsequent operation. Do not
    # remove it on the grounds that `float()` "does nothing" for a float.
    limit_multiplier, achieved_arl = _calibrate_limit_multiplier(
        float(effective_smoothing_param), float(validated_target_arl)
    )
    half_width = (
        limit_multiplier
        * sigma_estimate
        * _ewma_asymptotic_std_ratio(float(effective_smoothing_param))
    )

    provenance = baseline.provenance_signature
    if provenance is None:  # pragma: no cover
        # Unreachable: sufficiency requires observation_count >= threshold
        # > 0, and Baseline sets provenance_signature on its first recorded
        # observation -- an internal invariant, not a CaliperError path.
        raise RuntimeError(
            "fit_ewma invariant violation: a sufficient baseline has no "
            "provenance signature"
        )

    return FittedEWMA(
        chart_type=_CHART_TYPE,
        baseline_mean=baseline_mean,
        baseline_spread=baseline_spread,
        sigma_estimate=sigma_estimate,
        sigma_estimation_method=_MOVING_RANGE_METHOD,
        observation_count=len(scores),
        provenance_model_version=provenance.model_version.value,
        provenance_criteria=provenance.scoring_criteria.value,
        requested_arl=validated_target_arl,
        achieved_arl=achieved_arl,
        calibration_method=_CALIBRATION_METHOD,
        smoothing_param=effective_smoothing_param,
        ucl=baseline_mean + half_width,
        lcl=baseline_mean - half_width,
        cl=baseline_mean,
        advisories=(target_arl_advisory,) if target_arl_advisory is not None else (),
    )
