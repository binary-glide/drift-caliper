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
(``caliper.baseline.domain.spc_numerics._moving_range_sigma`` -- the same
estimator EWMA and CUSUM both delegate to; see that module's docstring for
the ``d_2`` closed form ``2/sqrt(pi)``, which needs no citation -- see
``spc_numerics``).

See ``tests/unit/baseline/test_shewhart_arl_published_values.py`` for the
closed-form numerical proof: unlike its Markov-chain/Siegmund-approximation
siblings, Shewhart's calibration needs no published table at all -- the
1/(2*Phi(-L)) relationship is exact mathematics, not an approximation, and
is verified there directly against the standard normal CDF rather than any
external citation.

## Scaffold state (BIN-95 TDD red phase)

``fit_shewhart`` always raises ``NotImplementedError`` until
``domain-implementer`` replaces this scaffold with the closed-form
calibration described above. Every test that calls it is expected to fail
for that reason until then -- the same shape ``fit_ewma``/``fit_cusum``
carried during their own red phases (BIN-65/BIN-94).
"""

from __future__ import annotations

from caliper.baseline.domain.baseline import Baseline
from caliper.baseline.domain.ewma_fitting import MAX_MEANINGFUL_ARL, MIN_MEANINGFUL_ARL
from caliper.baseline.domain.fitted_shewhart import FittedShewhart

# --- Moving-range sigma estimation -------------------------------------------
#
# Shared with EWMA and CUSUM via ``caliper.baseline.domain.spc_numerics`` --
# see that module's docstring for the full citation chain. No independent
# copy here.
_MOVING_RANGE_METHOD = "moving_range"

_CHART_TYPE = "shewhart"
_CALIBRATION_METHOD = "tail_probability"
_ZERO_VARIANCE_REASON = "zero_variance"


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

    Args:
        baseline: The Phase I baseline to fit from.
        target_arl: The target in-control ARL0 (false alarm tolerance).
            Optional in the signature, required by validation -- omitting
            it raises ``InvalidParameterError`` with
            ``context["kind"] == "missing"``. Unlike EWMA/CUSUM, there is
            no second, independently-specifiable tuning parameter (ADR-004
            section 5, BIN-95 A3/A5).

    Returns:
        A ``FittedShewhart`` artefact.

    Raises:
        InvalidParameterError: ``target_arl`` is missing or outside
            ``[MIN_MEANINGFUL_ARL, MAX_MEANINGFUL_ARL]``.
        InsufficientBaselineError: ``baseline`` does not meet the
            sufficiency threshold (BIN-95 A1/BR-1).
        DegenerateBaselineError: every observation in ``baseline`` has an
            identical score (BIN-95 A2/BR-2).
    """
    raise NotImplementedError(
        "fit_shewhart is a TDD red-phase scaffold (BIN-95) -- "
        "domain-implementer replaces this with the closed-form "
        "tail-probability calibration described in this module's "
        "docstring."
    )


__all__ = ["MAX_MEANINGFUL_ARL", "MIN_MEANINGFUL_ARL", "fit_shewhart"]
