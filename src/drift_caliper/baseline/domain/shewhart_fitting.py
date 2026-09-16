"""``fit_shewhart`` -- fit Shewhart I-chart control limits from a Phase I baseline.

See ``docs/domain-model.md`` (Library Operations -- Fit Shewhart) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
sections 4-6 for the fitting signature shape and parameter semantics, and
ADR-001 for the calibration method.

## Calibration method

Unlike EWMA (Brook & Evans 1972 Markov-chain approximation) and CUSUM
(Siegmund's 1985 corrected diffusion approximation), the Shewhart I-chart's
in-control ARL0 has a **closed form under normality, with no free
calibration parameter of its own**:

    ARL0(L) = 1 / (2 * (1 - Phi(L))) = 1 / (2 * Phi(-L))

where ``L`` is the sigma multiplier (``FittedShewhart.sigma_multiplier``)
and ``Phi`` is the standard normal CDF. This is the two-sided false alarm
probability per observation (``alpha = 2 * Phi(-L)``, one tail on each
side) inverted into an expected run length. ``fit_shewhart`` inverts this
relationship **directly** (``L = Phi^-1(1 - 1 / (2 * target_arl))``) rather
than root-finding, since the closed form is already invertible in closed
form -- unlike EWMA/CUSUM, there is no discretisation, no approximation
error, and no free tuning parameter for the engineer to specify (ADR-004
section 5, BIN-95 A3/A5: the I-chart has no analogue to EWMA's
``smoothing_param`` or CUSUM's ``reference_value``).

Control limits are then ``baseline_mean +/- L * sigma_estimate``, where
``sigma_estimate`` is the shared moving-range estimator
(``drift_caliper.baseline.domain.spc_numerics._moving_range_sigma`` -- the same
estimator EWMA and CUSUM both delegate to; see that module's docstring for
the ``d_2`` closed form ``2/sqrt(pi)``, which needs no citation -- see
``spc_numerics``).

``achieved_arl`` is computed by a genuine forward evaluation of the ARL0
formula at the solved ``L`` (``_shewhart_arl0``), not by echoing
``requested_arl`` back. The two values coincide to float precision because
the inversion is an exact bijection, not because one is *defined* in terms
of the other -- but note that, for exactly this reason, a mutant that
replaced the forward evaluation with a bare echo would not be caught by any
test here (see this story's completion report for the honest accounting of
that gap; unlike EWMA/CUSUM, whose approximation error makes forward and
echo genuinely distinguishable, Shewhart's exact bijection makes them
numerically identical, so ``sigma_multiplier`` -- not ``achieved_arl`` -- is
the field that actually constrains the calibration; see the tests that
check it independently of ``achieved_arl``).

See ``tests/unit/baseline/test_shewhart_arl_published_values.py`` for the
closed-form numerical proof: unlike its Markov-chain/Siegmund-approximation
siblings, Shewhart's calibration needs no published table at all -- the
1/(2*Phi(-L)) relationship is exact mathematics, not an approximation, and
is verified there directly against the standard normal CDF rather than any
external citation.
"""

from __future__ import annotations

import statistics
from statistics import NormalDist

from drift_caliper.baseline.domain.baseline import Baseline
from drift_caliper.baseline.domain.ewma_fitting import MAX_MEANINGFUL_ARL
from drift_caliper.baseline.domain.fitted_shewhart import FittedShewhart
from drift_caliper.baseline.domain.parameter_guards import (
    MIN_TARGET_ARL,
    _require_target_arl,
    require_type,
)
from drift_caliper.baseline.domain.spc_numerics import (
    _has_zero_variance,
    _moving_range_sigma,
    _overflow_safe_mean,
    baseline_scores,
    require_representable_limits,
)
from drift_caliper.errors import (
    DegenerateBaselineError,
    InsufficientBaselineError,
)

# --- Moving-range sigma estimation -------------------------------------------
#
# Shared with EWMA and CUSUM via ``drift_caliper.baseline.domain.spc_numerics`` --
# see that module's docstring for the full citation chain. No independent
# copy here.
_MOVING_RANGE_METHOD = "moving_range"

_CHART_TYPE = "shewhart"
_CALIBRATION_METHOD = "tail_probability"
_ZERO_VARIANCE_REASON = "zero_variance"


# --- Parameter validation ----------------------------------------------------


# --- Baseline statistics ------------------------------------------------------


# --- Closed-form tail-probability calibration ---------------------------------


def _shewhart_arl0(sigma_multiplier: float) -> float:
    """Compute the exact in-control ARL0 at ``sigma_multiplier`` sigma, two-sided.

    ``ARL0(L) = 1 / (2 * (1 - Phi(L)))`` -- the definition of a two-sided
    normal tail probability inverted into an expected run length. A genuine
    forward evaluation, used to compute ``achieved_arl`` from the solved
    ``L`` rather than echoing ``requested_arl`` back (see module docstring).
    """
    return 1.0 / (2.0 * (1.0 - NormalDist().cdf(sigma_multiplier)))


def _shewhart_sigma_multiplier(target_arl: float) -> float:
    """Compute the sigma multiplier ``L`` achieving ``target_arl`` -- direct inversion.

    ``L(ARL0) = Phi^-1(1 - 1 / (2 * ARL0))``. No root-find: the relationship
    is already invertible in closed form (module docstring).
    """
    return NormalDist().inv_cdf(1.0 - 1.0 / (2.0 * target_arl))


# --- Public API ----------------------------------------------------------------


def fit_shewhart(
    baseline: Baseline, *, target_arl: float | None = None
) -> FittedShewhart:
    """Fit Shewhart I-chart control limits from ``baseline`` (BIN-95).

    Validates ``target_arl`` first (fail fast), then enforces baseline
    sufficiency by calling ``baseline.check_sufficiency()`` internally
    (OQ-3, resolved the same way ``fit_ewma``/``fit_cusum`` resolved it:
    fitting owns enforcement rather than duplicating BIN-64's threshold
    logic in a second guard), then refuses a zero-variance baseline, then
    derives the sigma multiplier directly from ``target_arl`` via the
    closed-form relationship described in the module docstring -- no
    root-finding, no discretisation, no independent tuning parameter.

    Parameters
    ----------
    baseline
        The Phase I baseline to fit from.
    target_arl
        The target in-control ARL0 (false alarm tolerance). Optional in
        the signature, required by validation -- omitting it raises
        ``InvalidParameterError`` with ``context["kind"] == "missing"``.
        Unlike EWMA/CUSUM, there is no second, independently-specifiable
        tuning parameter (ADR-004 section 5, BIN-95 A3/A5).

    Returns
    -------
    FittedShewhart
        The fitted artefact. Carries a non-empty ``advisories`` when
        ``target_arl`` is inside ADR-011's flagged tier (``[100, 370)``).

    Raises
    ------
    InvalidParameterError
        ``target_arl`` is missing or outside ``[MIN_TARGET_ARL,
        MAX_MEANINGFUL_ARL]`` (ADR-011).
    InsufficientBaselineError
        ``baseline`` does not meet the sufficiency threshold (BIN-95
        A1/BR-1).
    DegenerateBaselineError
        Every observation in ``baseline`` has an identical score (BIN-95
        A2/BR-2).
    """
    # BIN-126: reject a wrong-typed baseline before any attribute on it is
    # accessed -- previously left to leak AttributeError the moment
    # `baseline.check_sufficiency()` below was reached.
    baseline = require_type(
        baseline, Baseline, parameter="baseline", type_name="Baseline"
    )
    validated_target_arl, target_arl_advisory = _require_target_arl(
        target_arl, chart_name="Shewhart I-chart", max_target_arl=MAX_MEANINGFUL_ARL
    )

    sufficiency = baseline.check_sufficiency()
    if not sufficiency.is_sufficient:
        raise InsufficientBaselineError(
            "baseline does not have enough observations to fit Shewhart "
            "I-chart control limits reliably",
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

    scores = baseline_scores(baseline.observations)
    if _has_zero_variance(scores):
        raise DegenerateBaselineError(
            "baseline has zero score variance -- Shewhart I-chart control "
            "limits cannot be fitted from it",
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

    sigma_multiplier = _shewhart_sigma_multiplier(validated_target_arl)
    achieved_arl = _shewhart_arl0(sigma_multiplier)
    half_width = sigma_multiplier * sigma_estimate

    require_representable_limits(
        baseline_mean=baseline_mean, half_width=half_width, chart_type=_CHART_TYPE
    )

    provenance = baseline.provenance_signature
    if provenance is None:  # pragma: no cover
        # Unreachable: sufficiency requires observation_count >= threshold
        # > 0, and Baseline sets provenance_signature on its first recorded
        # observation -- an internal invariant, not a CaliperError path.
        raise RuntimeError(
            "fit_shewhart invariant violation: a sufficient baseline has no "
            "provenance signature"
        )

    return FittedShewhart(
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
        sigma_multiplier=sigma_multiplier,
        advisories=(target_arl_advisory,) if target_arl_advisory is not None else (),
        ucl=baseline_mean + half_width,
        lcl=baseline_mean - half_width,
        cl=baseline_mean,
    )


__all__ = ["MAX_MEANINGFUL_ARL", "MIN_TARGET_ARL", "fit_shewhart"]
