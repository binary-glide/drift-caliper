"""Control limits must be finite, or the fit must refuse (BIN-142).

`fit_ewma` and `fit_shewhart` returned ``ucl=inf`` / ``lcl=-inf`` from a
*finite* sigma. The artefact reported ``achieved_arl == 370.0`` -- exactly what
was requested -- while being incapable of signalling, because nothing exceeds
infinity. A ``Monitor`` built on it reported ``is_in_control`` for a score of
``1e308``.

🚨 **Confident silence is the failure this library exists to prevent**, and
here the library produced it.

Deterministic, not property-based. ``.hypothesis/examples`` is gitignored, so a
property-only guard passes CI while the defect is live -- which is how BIN-119
shipped (BIN-124).

⚠️ **Two distinct defects were behind one symptom**, and the tests below pin
them separately because the fixes are different:

**1. An avoidable intermediate overflow (EWMA only).** ``L * sigma * ratio``
associates left-to-right, computing ``L * sigma`` first. That intermediate
overflows for a large sigma even when the final product is representable:
at ``sigma = 7.09e307``, ``L * sigma`` is ``inf`` while ``(L * ratio) * sigma``
is ``6.998e307``. **The right answer existed and the arithmetic threw it away.**
Fixed by grouping, not by refusing.

**2. A genuinely unrepresentable limit (both charts).** Shewhart's half-width
is ``3 * sigma`` with no sub-1 factor to fold in, so at the same sigma the true
value really does exceed float64. Refusing is correct there.

⚠️ **The ticket assumed every case in this region should be refused.** Treating
(1) as a refusal would have been over-rejection -- the BIN-123 class -- turning
a fixable arithmetic bug into a permanent capability gap.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedEWMA,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from drift_caliper.errors import DegenerateBaselineError, InvalidParameterError
from drift_caliper.monitoring import Monitor
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.baseline_strategies import baseline_from_scores

_TARGET_ARL = 370.0

_NON_FINITE_LIMITS_REASON = "non_representable_control_limits"

# The magnitude from BIN-142's report. Consecutive differences are 8e307,
# under float64's 1.797e308 ceiling, so sigma estimation succeeds and returns
# a finite 7.09e307 -- this is deliberately *past* BIN-119's guard.
_BIN_142_MAGNITUDE = 4e307

# A baseline whose centre and half-width are each representable but whose sum
# is not: alternating values near the top of float64, so `baseline_mean` is
# ~1.66e308 and `baseline_mean + half_width` overflows.
_HIGH = 1.7e308
_LOW = 1.7e308 - 8e307


def _alternating(magnitude: float) -> list[float]:
    """A baseline alternating +/-``magnitude``, at the sufficiency threshold."""
    return [
        magnitude if index % 2 else -magnitude
        for index in range(DEFAULT_SUFFICIENCY_THRESHOLD)
    ]


def _near_ceiling() -> list[float]:
    """A baseline whose mean is finite but ``mean + half_width`` is not."""
    return [
        _HIGH if index % 2 else _LOW for index in range(DEFAULT_SUFFICIENCY_THRESHOLD)
    ]


# ---------------------------------------------------------------------------
# Defect 1 -- the answer existed, and the arithmetic threw it away
# ---------------------------------------------------------------------------


def test_ewma_fits_a_baseline_whose_limits_are_representable() -> None:
    """EWMA at sigma ~7.09e307 fits, because ``(L * ratio) * sigma`` is finite.

    Before BIN-142 this returned ``ucl=inf``. ⚠️ It must not now *refuse*
    instead: the limits are representable and refusing would be
    over-rejection, trading one wrong answer for another.
    """
    fitted = fit_ewma(
        baseline_from_scores(_alternating(_BIN_142_MAGNITUDE)), target_arl=_TARGET_ARL
    )

    assert math.isfinite(fitted.ucl)
    assert math.isfinite(fitted.lcl)
    assert fitted.ucl > fitted.lcl
    assert math.isfinite(fitted.sigma_estimate)


def test_ewma_limits_survive_the_largest_sigma_that_can_be_estimated() -> None:
    """The grouping fix holds at the top of the representable sigma range.

    Pins the property rather than one magnitude: if the multiplication is ever
    reassociated back to ``L * sigma * ratio``, this fails alongside the test
    above.
    """
    # 8.9e307 is the largest magnitude whose consecutive difference (1.78e308)
    # still fits in float64, so sigma estimation succeeds.
    fitted = fit_ewma(
        baseline_from_scores(_alternating(8.9e307)), target_arl=_TARGET_ARL
    )

    assert math.isfinite(fitted.ucl)
    assert math.isfinite(fitted.lcl)


# ---------------------------------------------------------------------------
# Defect 2 -- genuinely unrepresentable, so refusing is the right answer
# ---------------------------------------------------------------------------


def test_shewhart_refuses_when_the_half_width_cannot_be_represented() -> None:
    """Shewhart's ``3 * sigma`` has no sub-1 factor to fold in.

    At sigma ~7.09e307 the true half-width is ~2.1e308, past float64's
    ceiling. There is no grouping that rescues it, so the fit must refuse
    rather than return ``inf``.
    """
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_shewhart(
            baseline_from_scores(_alternating(_BIN_142_MAGNITUDE)),
            target_arl=_TARGET_ARL,
        )

    assert exc_info.value.context["reason"] == _NON_FINITE_LIMITS_REASON
    assert exc_info.value.context["chart_type"] == "shewhart"


@pytest.mark.parametrize("fit_fn", [fit_ewma, fit_shewhart], ids=["ewma", "shewhart"])
def test_refuses_when_centre_plus_half_width_overflows(
    fit_fn: Callable[..., FittedControlLimits],
) -> None:
    """Both charts refuse when the limits overflow even though each part fits.

    `baseline_mean` is finite (~1.66e308) and `half_width` is finite, but
    their sum is not. ⚠️ This is BIN-122's shape: every component individually
    valid, the combination unusable -- which no single-field check can catch.
    """
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_fn(baseline_from_scores(_near_ceiling()), target_arl=_TARGET_ARL)

    context = exc_info.value.context
    assert context["reason"] == _NON_FINITE_LIMITS_REASON
    assert math.isfinite(context["baseline_mean"])


# ---------------------------------------------------------------------------
# The symptom that made this urgent
# ---------------------------------------------------------------------------


def test_no_fit_can_produce_a_monitor_that_never_signals() -> None:
    """The end-to-end property, stated as the user experiences it.

    🚨 Before the fix, `ucl` was `inf` and **no sequence of observations could
    ever signal.** Now the limits are finite, so a sustained shift reaches
    them.

    ⚠️ **Sustained, not single.** A first draft of this test recorded one
    score of 1e308 and asserted it must be out of control. That is wrong about
    EWMA and the test correctly failed: the statistic is
    `z = 0.2 * x + 0.8 * z_prev`, so one observation moves `z` to 2e307 --
    inside a `ucl` of 6.76e307. **Refusing to signal on a single point is the
    smoothing working**, which is the whole reason EWMA detects gradual drift.
    Asserting otherwise would have encoded a Shewhart expectation into an EWMA
    test.
    """
    provenance = ProvenanceFactory()
    baseline = Baseline()
    for score in _alternating(_BIN_142_MAGNITUDE):
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))

    try:
        fitted = fit_ewma(baseline, target_arl=_TARGET_ARL)
    except DegenerateBaselineError:
        return  # Refusing is a valid outcome; an inert chart is not.

    monitor = Monitor(fitted)
    signalled = False
    for _ in range(50):
        result = monitor.record(
            ScoringResultFactory(provenance=provenance, score=1e308)
        )
        if not result.is_in_control:
            signalled = True
            break

    assert signalled, (
        f"50 consecutive observations of 1e308 never signalled against "
        f"ucl={fitted.ucl}, lcl={fitted.lcl} -- the chart cannot signal"
    )


# ---------------------------------------------------------------------------
# CUSUM is unaffected -- recorded, not assumed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scores",
    [_alternating(_BIN_142_MAGNITUDE), _near_ceiling()],
    ids=["bin_142_magnitude", "near_ceiling"],
)
def test_cusum_is_structurally_immune(scores: list[float]) -> None:
    """CUSUM computes no observation-scale limit, so it has nothing to overflow.

    Its ``decision_interval`` is in sigma units (h is around 4.77 at the
    default reference value) and its ``target_value`` is the baseline mean.
    Neither scales with sigma, so the overflow that defeats EWMA and Shewhart
    cannot arise.

    ⚠️ Asserted rather than argued: BIN-142 required CUSUM's immunity to be
    "confirmed, with the reason recorded rather than assumed", and an argument
    about why a bug cannot happen is exactly the kind of claim that rots.
    """
    fitted = fit_cusum(baseline_from_scores(scores), target_arl=_TARGET_ARL)

    assert math.isfinite(fitted.decision_interval)
    assert math.isfinite(fitted.target_value)
    assert math.isfinite(fitted.reference_value)


# ---------------------------------------------------------------------------
# The type-level backstop -- for construction routes that bypass fit_*
# ---------------------------------------------------------------------------


def _well_formed_ewma() -> FittedEWMA:
    """A valid ``FittedEWMA``, constructed directly rather than via ``fit_ewma``.

    Direct construction is the point: this section tests the *type's* invariant,
    which must hold for any construction route, not only the fitting one.
    """
    return FittedEWMA(
        chart_type="ewma",
        baseline_mean=8.0,
        baseline_spread=0.5,
        sigma_estimate=0.5,
        sigma_estimation_method="moving_range",
        observation_count=DEFAULT_SUFFICIENCY_THRESHOLD,
        provenance_model_version="m-1",
        provenance_criteria="rubric",
        requested_arl=_TARGET_ARL,
        achieved_arl=_TARGET_ARL,
        calibration_method="markov_chain",
        smoothing_param=0.2,
        ucl=9.0,
        lcl=7.0,
        cl=8.0,
    )


@pytest.mark.parametrize(
    "field",
    ["ucl", "lcl", "cl", "baseline_mean", "achieved_arl", "smoothing_param"],
)
@pytest.mark.parametrize(
    "value", [math.inf, -math.inf, math.nan], ids=["inf", "-inf", "nan"]
)
def test_no_fitted_artefact_may_hold_a_non_finite_float(
    field: str, value: float
) -> None:
    """Every float field is guarded, not only the ones ``fit_*`` computes.

    🚨 **This is the half of the fix that cannot be incompletely applied.**
    BIN-140 added a postcondition to ``achieved_arl`` and stated the lesson as
    "any number a numerical routine hands to a caller needs a postcondition" --
    and BIN-142 appeared the next day in ``ucl``, a field that postcondition
    never looked at.

    ⚠️ The fields are parametrised rather than asserted in a loop so a failure
    names the field, and ``baseline_mean``/``achieved_arl`` are included
    deliberately: they were *already* reachable and are covered here for the
    same reason the new ones are, rather than trusted to a different test.
    """
    corrupted = {**_well_formed_ewma().model_dump(), field: value}

    with pytest.raises(InvalidParameterError) as exc_info:
        FittedEWMA.model_validate(corrupted)

    context = exc_info.value.context
    assert context["parameter"] == field
    assert context["kind"] == "invalid"


def test_a_well_formed_artefact_still_constructs() -> None:
    """The guard rejects non-finite values and nothing else.

    ⚠️ Without this, every assertion above would still pass if the validator
    rejected *everything* -- the over-rejection failure mode (BIN-123), which
    a test suite full of `pytest.raises` cannot see.
    """
    fitted = _well_formed_ewma()

    assert fitted.ucl == 9.0
    assert fitted.lcl == 7.0

    # And the same values survive the round trip the corruption tests use, so
    # a failure above is the injected value and never the mechanism.
    assert FittedEWMA.model_validate(fitted.model_dump()) == fitted
