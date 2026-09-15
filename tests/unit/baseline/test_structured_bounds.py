"""BIN-134: every reported boundary is a structured numeric field, not prose.

**The property.** Any boundary Caliper *reports* must equal the boundary it
*enforces*. BIN-117 proved the class is real: ``InvalidParameterError``
reported ``min_attainable_arl``, its ``recovery_hint`` said "choose a
target_arl at or above that value", and passing that value back raised the
same error again.

``min_attainable_arl`` is already a structured numeric field on ``context``,
so a test can feed it straight back -- that is the worked pattern this file
generalises. ADR-011's boundaries and ``FittingAdvisory.boundary`` are
currently prose-only; this file asserts the structured fields that
``domain-implementer`` must add.

**Design decision encoded here: ``min_inclusive``/``max_inclusive`` booleans.**
Every caller-facing range today is inclusive, so the flags could look
redundant. But the ``sigma_estimate > 0.0`` validators on the three
``Fitted*`` types have an *exclusive* lower bound: ``min_value=0.0`` would
be a value the library refuses. Omitting the flags for those sites would
silently reintroduce BIN-117's trap in structured form. The flags make the
round-trip property precisely testable:

- **inclusive** bound -> feeding it back is **accepted**
- **exclusive** bound -> feeding it back is **rejected**,
  and ``math.nextafter(bound, interior)`` is **accepted**

**Surfaces covered (complete survey -- 30 constraint emission sites, of
which 10 emit range bounds needing structured fields):**

1.  ``parameter_guards.classify_target_arl`` -- ``[MIN_TARGET_ARL,
    max_target_arl]`` inclusive, shared by all three ``fit_*`` functions
2.  ``ewma_fitting._validate_smoothing_param`` -- ``[MIN_SMOOTHING_PARAM,
    MAX_SMOOTHING_PARAM]`` inclusive
3.  ``cusum_fitting._validate_reference_value`` -- ``[MIN_REFERENCE_VALUE,
    MAX_REFERENCE_VALUE]`` inclusive
4.  ``fitted_ewma`` sigma_estimate validator -- ``> 0.0`` exclusive lower
5.  ``fitted_cusum`` sigma_estimate validator -- ``> 0.0`` exclusive lower
6.  ``fitted_shewhart`` sigma_estimate validator -- ``> 0.0`` exclusive lower
7.  ``baseline.check_sufficiency`` threshold -- ``>= 1`` (positive integer)
8.  ``FittingAdvisory.boundary`` -- the numeric value the advisory is *about*

**Out of scope (enumeration, not range):** ``cusum_fitting._validate_direction``
(``must be one of {...}``), ``monitor``'s artefact-type checks. Enumerations
do not have numeric bounds to round-trip.

**Out of scope (already structured):** ``cusum_fitting._require_attainable_target_arl``
-- already emits ``min_attainable_arl`` as a structured float on ``context``.
That is the worked pattern; it needs no change.

**Out of scope (type guard, not range):** ``parameter_guards.require_real_number``,
``parameter_guards.require_type``. No numeric bounds to report.

**Three sites emit ``kind: "missing"`` with a ``constraint`` string.**
These do NOT need structured bounds -- a missing parameter has no value to
round-trip. Covered only to confirm they do not gain ``min_value``/``max_value``
(the fields are meaningless when no value was provided).
"""

from __future__ import annotations

import math

import pytest

from drift_caliper.baseline import (
    Baseline,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    FittingAdvisory,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from drift_caliper.baseline.domain.cusum_fitting import (
    MAX_REFERENCE_VALUE,
    MIN_REFERENCE_VALUE,
)
from drift_caliper.baseline.domain.ewma_fitting import (
    MAX_MEANINGFUL_ARL,
    MAX_SMOOTHING_PARAM,
    MIN_SMOOTHING_PARAM,
)
from drift_caliper.baseline.domain.parameter_guards import (
    MIN_TARGET_ARL,
    VERIFIED_ARL_FLOOR,
)
from drift_caliper.errors import InvalidParameterError
from tests.support.baseline_strategies import probe_baseline

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_PROBE_BASELINE = probe_baseline()


# ---------------------------------------------------------------------------
# Section 1: classify_target_arl -- [MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]
#
# Both bounds are inclusive. The structured fields must appear on every
# InvalidParameterError emitted by classify_target_arl (which is called by
# all three fit_* functions). The min_value/max_value must exactly equal
# the constants the library enforces, and the inclusivity flags must be
# True for both.
# ---------------------------------------------------------------------------


class TestTargetArlStructuredBounds:
    """Structured bound fields on ``target_arl`` range rejections."""

    def test_below_min_reports_min_value_and_max_value(self) -> None:
        """An out-of-range target_arl error carries structured bounds."""
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)
        ctx = exc_info.value.context
        assert ctx["min_value"] == MIN_TARGET_ARL
        assert ctx["max_value"] == MAX_MEANINGFUL_ARL

    def test_below_min_reports_inclusive_flags(self) -> None:
        """Both bounds are inclusive for ``target_arl``."""
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)
        ctx = exc_info.value.context
        assert ctx["min_inclusive"] is True
        assert ctx["max_inclusive"] is True

    def test_above_max_reports_min_value_and_max_value(self) -> None:
        """Above-ceiling rejection also carries structured bounds."""
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MAX_MEANINGFUL_ARL + 1.0)
        ctx = exc_info.value.context
        assert ctx["min_value"] == MIN_TARGET_ARL
        assert ctx["max_value"] == MAX_MEANINGFUL_ARL

    def test_reported_min_value_round_trips_as_accepted(self) -> None:
        """The ``min_value`` the error reports is itself accepted when fed back.

        This is the generalised BIN-117 property: the reported bound must
        equal the enforced bound. For an inclusive lower bound, feeding
        the exact value back must succeed -- not raise.
        """
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)
        reported_min = exc_info.value.context["min_value"]
        # Feed the reported value straight back -- must succeed.
        result = fit_shewhart(_PROBE_BASELINE, target_arl=reported_min)
        assert result.requested_arl == reported_min

    def test_reported_max_value_round_trips_as_accepted(self) -> None:
        """The ``max_value`` the error reports is itself accepted when fed back."""
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MAX_MEANINGFUL_ARL + 1.0)
        reported_max = exc_info.value.context["max_value"]
        result = fit_shewhart(_PROBE_BASELINE, target_arl=reported_max)
        assert result.requested_arl == reported_max

    def test_reported_min_equals_enforced_constant(self) -> None:
        """The structured ``min_value`` equals the constant the library enforces.

        This is stronger than the existing weakened test in
        ``test_reported_bound_round_trips.py``, which only proved the
        *imported constant* is accepted. This proves the *reported value*
        IS the constant -- catching a future drift between what is
        reported and what is enforced.
        """
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)
        assert exc_info.value.context["min_value"] == MIN_TARGET_ARL

    def test_reported_max_equals_enforced_constant(self) -> None:
        """The structured ``max_value`` equals the constant the library enforces."""
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MAX_MEANINGFUL_ARL + 1.0)
        assert exc_info.value.context["max_value"] == MAX_MEANINGFUL_ARL

    def test_all_three_charts_emit_same_structured_bounds(self) -> None:
        """EWMA, CUSUM and Shewhart share one policy (parameter_guards), so
        all three must report the same structured min_value/max_value."""
        errors: list[InvalidParameterError] = []
        for fit_fn in (fit_ewma, fit_cusum, fit_shewhart):
            with pytest.raises(InvalidParameterError) as exc_info:
                fit_fn(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)
            errors.append(exc_info.value)

        min_values = [e.context["min_value"] for e in errors]
        max_values = [e.context["max_value"] for e in errors]
        assert len(set(min_values)) == 1, f"min_value disagrees: {min_values}"
        assert len(set(max_values)) == 1, f"max_value disagrees: {max_values}"

    def test_prose_constraint_still_present(self) -> None:
        """The human-readable ``constraint`` string is preserved alongside the
        structured fields -- additive, not a replacement."""
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)
        ctx = exc_info.value.context
        assert "constraint" in ctx
        assert isinstance(ctx["constraint"], str)
        assert ctx["constraint"] != ""

    def test_missing_target_arl_has_no_structured_bounds(self) -> None:
        """``kind: "missing"`` errors have no value to round-trip, so
        ``min_value``/``max_value`` must not be present."""
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=None)
        ctx = exc_info.value.context
        assert ctx["kind"] == "missing"
        assert "min_value" not in ctx
        assert "max_value" not in ctx


# ---------------------------------------------------------------------------
# Section 2: smoothing_param -- [MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM]
# ---------------------------------------------------------------------------


class TestSmoothingParamStructuredBounds:
    """Structured bound fields on ``smoothing_param`` range rejections."""

    def test_below_min_reports_structured_bounds(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_ewma(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                smoothing_param=MIN_SMOOTHING_PARAM - 0.001,
            )
        ctx = exc_info.value.context
        assert ctx["min_value"] == MIN_SMOOTHING_PARAM
        assert ctx["max_value"] == MAX_SMOOTHING_PARAM
        assert ctx["min_inclusive"] is True
        assert ctx["max_inclusive"] is True

    def test_above_max_reports_structured_bounds(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_ewma(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                smoothing_param=MAX_SMOOTHING_PARAM + 0.1,
            )
        ctx = exc_info.value.context
        assert ctx["min_value"] == MIN_SMOOTHING_PARAM
        assert ctx["max_value"] == MAX_SMOOTHING_PARAM

    def test_reported_min_round_trips_as_accepted(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_ewma(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                smoothing_param=MIN_SMOOTHING_PARAM - 0.001,
            )
        reported_min = exc_info.value.context["min_value"]
        result = fit_ewma(
            _PROBE_BASELINE,
            target_arl=VERIFIED_ARL_FLOOR,
            smoothing_param=reported_min,
        )
        assert isinstance(result, FittedEWMA)

    def test_reported_max_round_trips_as_accepted(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_ewma(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                smoothing_param=MAX_SMOOTHING_PARAM + 0.1,
            )
        reported_max = exc_info.value.context["max_value"]
        result = fit_ewma(
            _PROBE_BASELINE,
            target_arl=VERIFIED_ARL_FLOOR,
            smoothing_param=reported_max,
        )
        assert isinstance(result, FittedEWMA)


# ---------------------------------------------------------------------------
# Section 3: reference_value -- [MIN_REFERENCE_VALUE, MAX_REFERENCE_VALUE]
# ---------------------------------------------------------------------------


# Above the minimum attainable ARL0 at k = MAX_REFERENCE_VALUE (5.0), which
# is 1158.33 two-sided -- computed by the library itself and reported as
# `min_attainable_arl` (BIN-117), not a figure typed in here. Used so the
# reference_value round-trip below is not confounded by an unrelated
# joint-parameter constraint.
_ARL_ABOVE_MAX_K_ATTAINABLE_FLOOR = 2000.0


class TestReferenceValueStructuredBounds:
    """Structured bound fields on ``reference_value`` range rejections."""

    def test_below_min_reports_structured_bounds(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_cusum(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                reference_value=MIN_REFERENCE_VALUE - 0.001,
            )
        ctx = exc_info.value.context
        assert ctx["min_value"] == MIN_REFERENCE_VALUE
        assert ctx["max_value"] == MAX_REFERENCE_VALUE
        assert ctx["min_inclusive"] is True
        assert ctx["max_inclusive"] is True

    def test_above_max_reports_structured_bounds(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_cusum(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                reference_value=MAX_REFERENCE_VALUE + 0.1,
            )
        ctx = exc_info.value.context
        assert ctx["min_value"] == MIN_REFERENCE_VALUE
        assert ctx["max_value"] == MAX_REFERENCE_VALUE

    def test_reported_min_round_trips_as_accepted(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_cusum(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                reference_value=MIN_REFERENCE_VALUE - 0.001,
            )
        reported_min = exc_info.value.context["min_value"]
        result = fit_cusum(
            _PROBE_BASELINE,
            target_arl=VERIFIED_ARL_FLOOR,
            reference_value=reported_min,
        )
        assert isinstance(result, FittedCUSUM)

    def test_reported_max_round_trips_as_accepted(self) -> None:
        """The reported ``max_value`` is accepted **as a reference_value**.

        ⚠️ **The round-trip property is per-parameter, not joint, and this
        test had to be corrected to say so.** As first written it fed the
        reported ``max_value`` (5.0) back alongside
        ``target_arl=VERIFIED_ARL_FLOOR`` (370.0) and expected a fit. That
        pair is refused -- not because the reported bound is wrong, but
        because ``k=5.0`` has a minimum attainable ARL0 of 1158.33
        (two-sided), which BIN-117 established and already reports as a
        structured ``min_attainable_arl``.

        So ``target_arl`` here is chosen **above** that floor, isolating
        the property actually under test: a bound Caliper reports for a
        parameter is a legal value *of that parameter*.
        """
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_cusum(
                _PROBE_BASELINE,
                target_arl=_ARL_ABOVE_MAX_K_ATTAINABLE_FLOOR,
                reference_value=MAX_REFERENCE_VALUE + 0.1,
            )
        reported_max = exc_info.value.context["max_value"]

        result = fit_cusum(
            _PROBE_BASELINE,
            target_arl=_ARL_ABOVE_MAX_K_ATTAINABLE_FLOOR,
            reference_value=reported_max,
        )
        assert isinstance(result, FittedCUSUM)

    def test_joint_refusal_after_round_trip_is_itself_structured(self) -> None:
        """Feeding the bound back into an incompatible pair still guides the caller.

        🚨 **This is the case that makes the per-parameter scoping
        acceptable rather than a hole.** An engineer who is told
        ``max_value=5.0`` and passes it back with their existing
        ``target_arl=370`` **is refused again** -- superficially the
        BIN-117 experience, where following the advice looped forever.

        The difference, and the reason this is sound: the second refusal
        is a *different* error about a *different* parameter, and it is
        **itself structured** -- it names ``target_arl`` as the parameter
        at fault, carries the offending ``reference_value``, and reports
        ``min_attainable_arl`` as a float the caller can act on. Every
        step of the two-step path tells the engineer exactly what to do
        next, which is precisely what BIN-117 did not.

        ⚠️ If this ever starts raising something unstructured, the
        per-parameter scoping above stops being defensible and the
        round-trip property needs to become joint.
        """
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_cusum(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                reference_value=MAX_REFERENCE_VALUE,
            )

        context = exc_info.value.context
        assert context["parameter"] == "target_arl"
        assert isinstance(context["min_attainable_arl"], float)
        assert context["reference_value"] == MAX_REFERENCE_VALUE

        # The path out is real: the value it reports is itself acceptable.
        recovered = fit_cusum(
            _PROBE_BASELINE,
            target_arl=context["min_attainable_arl"],
            reference_value=MAX_REFERENCE_VALUE,
        )
        assert isinstance(recovered, FittedCUSUM)


# ---------------------------------------------------------------------------
# Section 4: sigma_estimate on Fitted* types -- exclusive lower bound > 0.0
#
# The three Fitted* types all validate sigma_estimate > 0.0 (exclusive).
# min_value=0.0 is a value the library refuses. The inclusive flag
# distinguishes this from the inclusive bounds above.
# ---------------------------------------------------------------------------


class TestSigmaEstimateStructuredBounds:
    """Structured bound fields on ``sigma_estimate`` validation (exclusive lower)."""

    @pytest.mark.parametrize(
        "fitted_type",
        [FittedEWMA, FittedCUSUM, FittedShewhart],
        ids=["ewma", "cusum", "shewhart"],
    )
    def test_reports_exclusive_lower_bound(
        self, fitted_type: type[FittedEWMA] | type[FittedCUSUM] | type[FittedShewhart]
    ) -> None:
        """sigma_estimate=0.0 is rejected with min_value=0.0 and min_inclusive=False."""
        # Construct with sigma_estimate=0.0, which all three reject.
        # Use a dict of valid fields, adjusted per type, to build an
        # invalid instance that triggers the validator.
        with pytest.raises(InvalidParameterError) as exc_info:
            _construct_fitted_with_sigma(fitted_type, sigma_estimate=0.0)
        ctx = exc_info.value.context
        assert ctx["min_value"] == 0.0
        assert ctx["min_inclusive"] is False

    @pytest.mark.parametrize(
        "fitted_type",
        [FittedEWMA, FittedCUSUM, FittedShewhart],
        ids=["ewma", "cusum", "shewhart"],
    )
    def test_has_no_max_value(
        self, fitted_type: type[FittedEWMA] | type[FittedCUSUM] | type[FittedShewhart]
    ) -> None:
        """sigma_estimate has no upper bound -- ``max_value`` must not appear."""
        with pytest.raises(InvalidParameterError) as exc_info:
            _construct_fitted_with_sigma(fitted_type, sigma_estimate=0.0)
        ctx = exc_info.value.context
        assert "max_value" not in ctx

    @pytest.mark.parametrize(
        "fitted_type",
        [FittedEWMA, FittedCUSUM, FittedShewhart],
        ids=["ewma", "cusum", "shewhart"],
    )
    def test_exclusive_bound_is_rejected_and_nextafter_is_accepted(
        self, fitted_type: type[FittedEWMA] | type[FittedCUSUM] | type[FittedShewhart]
    ) -> None:
        """Feeding the exclusive bound back is rejected; the smallest value
        strictly above it is accepted. This is the stronger test that would
        have caught BIN-117 in exclusive-bound form."""
        # The exclusive bound (0.0) must be rejected.
        with pytest.raises(InvalidParameterError) as exc_info:
            _construct_fitted_with_sigma(fitted_type, sigma_estimate=0.0)
        reported_min = exc_info.value.context["min_value"]
        reported_inclusive = exc_info.value.context["min_inclusive"]

        assert reported_inclusive is False
        assert reported_min == 0.0

        # The smallest representable float above the exclusive bound must
        # be accepted.
        smallest_above = math.nextafter(reported_min, math.inf)
        result = _construct_fitted_with_sigma(
            fitted_type, sigma_estimate=smallest_above
        )
        assert result is not None  # construction succeeded


# Helper to construct a Fitted* type with a given sigma_estimate, using
# otherwise-valid field values. Each type has different required fields.


def _construct_fitted_with_sigma(
    fitted_type: type[FittedEWMA] | type[FittedCUSUM] | type[FittedShewhart],
    *,
    sigma_estimate: float,
) -> FittedEWMA | FittedCUSUM | FittedShewhart:
    """Construct a ``Fitted*`` type with the given ``sigma_estimate``."""
    if fitted_type is FittedEWMA:
        return FittedEWMA(
            chart_type="ewma",
            baseline_mean=0.5,
            baseline_spread=1.0,
            sigma_estimate=sigma_estimate,
            sigma_estimation_method="moving_range",
            observation_count=100,
            provenance_model_version="test-model",
            provenance_criteria="test criteria",
            requested_arl=370.0,
            achieved_arl=370.0,
            calibration_method="test",
            advisories=(),
            smoothing_param=0.2,
            ucl=1.5,
            lcl=-0.5,
            cl=0.5,
        )
    elif fitted_type is FittedCUSUM:
        return FittedCUSUM(
            chart_type="cusum",
            baseline_mean=0.5,
            baseline_spread=1.0,
            sigma_estimate=sigma_estimate,
            sigma_estimation_method="moving_range",
            observation_count=100,
            provenance_model_version="test-model",
            provenance_criteria="test criteria",
            requested_arl=370.0,
            achieved_arl=370.0,
            calibration_method="test",
            advisories=(),
            reference_value=0.5,
            decision_interval=4.0,
            direction="two_sided",
            target_value=0.5,
        )
    else:
        return FittedShewhart(
            chart_type="shewhart",
            baseline_mean=0.5,
            baseline_spread=1.0,
            sigma_estimate=sigma_estimate,
            sigma_estimation_method="moving_range",
            observation_count=100,
            provenance_model_version="test-model",
            provenance_criteria="test criteria",
            requested_arl=370.0,
            achieved_arl=370.0,
            calibration_method="test",
            advisories=(),
            ucl=1.5,
            lcl=-0.5,
            cl=0.5,
            sigma_multiplier=3.0,
        )


# ---------------------------------------------------------------------------
# Section 5: check_sufficiency threshold -- positive integer (>= 1)
# ---------------------------------------------------------------------------


class TestSufficiencyThresholdStructuredBounds:
    """Structured bound fields on ``check_sufficiency(threshold=...)``."""

    def test_non_integral_threshold_reports_structured_bounds(self) -> None:
        """threshold=50.7 is rejected, and reports the same structured bound.

        ⚠️ **`check_sufficiency` has two adjacent raise sites** -- one for a
        non-whole number, one for a non-positive one -- and they emit
        identical structured fields. `code-reviewer` noticed only the
        non-positive path was exercised.

        🚨 **Worth covering rather than waving through, because this exact
        path has form.** `check_sufficiency(threshold=50.7)` once
        *silently truncated* to 50, flipping sufficiency at `len == 50`;
        the rejection exists because of that regression. A path added to
        stop silent truncation is the last one to leave unpinned.
        """
        baseline = Baseline()

        with pytest.raises(InvalidParameterError) as exc_info:
            baseline.check_sufficiency(threshold=50.7)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

        context = exc_info.value.context
        assert context["min_value"] == 1
        assert context["min_inclusive"] is True
        assert "max_value" not in context, (
            "threshold has no upper bound -- absent, not None"
        )

    def test_zero_threshold_reports_structured_bounds(self) -> None:
        """threshold=0 is rejected with min_value=1 and min_inclusive=True."""
        baseline = Baseline()
        with pytest.raises(InvalidParameterError) as exc_info:
            baseline.check_sufficiency(threshold=0)
        ctx = exc_info.value.context
        assert ctx["min_value"] == 1
        assert ctx["min_inclusive"] is True

    def test_negative_threshold_reports_structured_bounds(self) -> None:
        """threshold=-5 is rejected with the same structured bounds."""
        baseline = Baseline()
        with pytest.raises(InvalidParameterError) as exc_info:
            baseline.check_sufficiency(threshold=-5)
        ctx = exc_info.value.context
        assert ctx["min_value"] == 1
        assert ctx["min_inclusive"] is True

    def test_reported_min_round_trips_as_accepted(self) -> None:
        """The reported min_value (1) is itself accepted when fed back."""
        baseline = Baseline()
        with pytest.raises(InvalidParameterError) as exc_info:
            baseline.check_sufficiency(threshold=0)
        reported_min = exc_info.value.context["min_value"]
        # Feed the reported min back -- must succeed (not raise).
        result = baseline.check_sufficiency(threshold=reported_min)
        assert result is not None

    def test_has_no_max_value(self) -> None:
        """threshold has no upper bound -- max_value must not appear."""
        baseline = Baseline()
        with pytest.raises(InvalidParameterError) as exc_info:
            baseline.check_sufficiency(threshold=0)
        assert "max_value" not in exc_info.value.context


# ---------------------------------------------------------------------------
# Section 6: FittingAdvisory.boundary -- the numeric value the advisory
# is *about*
#
# ADR-011's flagged-tier advisory currently embeds the VERIFIED_ARL_FLOOR
# value (370.0) in a sentence and nowhere else. A structured
# ``boundary: float`` field makes it testable without parsing prose.
# ---------------------------------------------------------------------------


class TestFittingAdvisoryBoundaryField:
    """``FittingAdvisory`` carries a structured ``boundary`` field."""

    def test_flagged_tier_advisory_has_boundary_field(self) -> None:
        """An advisory in the flagged tier carries ``boundary`` as a float."""
        result = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
        assert len(result.advisories) == 1
        advisory = result.advisories[0]
        assert isinstance(advisory, FittingAdvisory)
        assert hasattr(advisory, "boundary")
        assert isinstance(advisory.boundary, float)

    def test_boundary_equals_verified_arl_floor(self) -> None:
        """The boundary the advisory reports is the VERIFIED_ARL_FLOOR --
        the exact constant the library uses to decide the tier."""
        result = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
        advisory = result.advisories[0]
        assert advisory.boundary == VERIFIED_ARL_FLOOR

    def test_boundary_round_trips_clean(self) -> None:
        """Fitting at exactly the reported boundary produces no advisory --
        the engineer can rely on the value to escape the flagged tier."""
        result = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
        advisory = result.advisories[0]
        clean_result = fit_shewhart(_PROBE_BASELINE, target_arl=advisory.boundary)
        assert clean_result.advisories == ()

    def test_all_three_charts_report_same_boundary(self) -> None:
        """The boundary is chart-independent (one ADR-011 policy)."""
        boundaries = []
        for fit_fn in (fit_ewma, fit_cusum, fit_shewhart):
            result = fit_fn(_PROBE_BASELINE, target_arl=200.0)
            assert len(result.advisories) == 1
            boundaries.append(result.advisories[0].boundary)
        assert len(set(boundaries)) == 1

    def test_boundary_serves_adr005_middle_tier(self) -> None:
        """``FittingAdvisory`` still works for ADR-005's second caller.

        ADR-005's middle tier needs ``observation_count``, ``target_arl``
        and the ``adequate()`` figure. ``boundary: float`` is the shape
        for the ``adequate()`` figure. The ``kind`` discriminator tells a
        caller which advisory they have, so the same type serves both
        callers. This test verifies the ``kind`` field still works as a
        discriminator.
        """
        result = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
        advisory = result.advisories[0]
        # The kind is a discriminator -- callers branch on it.
        assert advisory.kind == "target_arl_below_verified_range"
        # boundary is a float, not a tuple or dict -- it serves exactly
        # one numeric boundary per advisory, which is what both callers
        # need (VERIFIED_ARL_FLOOR for ADR-011, adequate() for ADR-005).
        assert isinstance(advisory.boundary, float)

    def test_prose_description_still_present(self) -> None:
        """The human-readable ``description`` is preserved alongside ``boundary``."""
        result = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
        advisory = result.advisories[0]
        assert isinstance(advisory.description, str)
        assert advisory.description != ""


# ---------------------------------------------------------------------------
# Section 7: Cross-cutting -- the reported == enforced property
#
# The tests above prove the *reported* value round-trips. These tests
# strengthen the claim: the reported value is not merely accepted, it IS
# the enforced constant. A future drift (the enforced constant changes but
# the reported value does not, or vice versa) fails here.
# ---------------------------------------------------------------------------


class TestReportedEqualsEnforced:
    """The reported structured bound IS the enforced constant, not merely an
    accepted value. This is strictly stronger than round-tripping."""

    def test_target_arl_min_value_is_min_target_arl(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)
        assert exc_info.value.context["min_value"] is not None
        assert exc_info.value.context["min_value"] == MIN_TARGET_ARL

    def test_target_arl_max_value_is_max_meaningful_arl(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_shewhart(_PROBE_BASELINE, target_arl=MAX_MEANINGFUL_ARL + 1.0)
        assert exc_info.value.context["max_value"] == MAX_MEANINGFUL_ARL

    def test_smoothing_param_min_value_is_min_smoothing_param(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_ewma(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                smoothing_param=MIN_SMOOTHING_PARAM - 0.001,
            )
        assert exc_info.value.context["min_value"] == MIN_SMOOTHING_PARAM

    def test_smoothing_param_max_value_is_max_smoothing_param(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_ewma(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                smoothing_param=MAX_SMOOTHING_PARAM + 0.1,
            )
        assert exc_info.value.context["max_value"] == MAX_SMOOTHING_PARAM

    def test_reference_value_min_is_min_reference_value(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_cusum(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                reference_value=MIN_REFERENCE_VALUE - 0.001,
            )
        assert exc_info.value.context["min_value"] == MIN_REFERENCE_VALUE

    def test_reference_value_max_is_max_reference_value(self) -> None:
        with pytest.raises(InvalidParameterError) as exc_info:
            fit_cusum(
                _PROBE_BASELINE,
                target_arl=VERIFIED_ARL_FLOOR,
                reference_value=MAX_REFERENCE_VALUE + 0.1,
            )
        assert exc_info.value.context["max_value"] == MAX_REFERENCE_VALUE

    def test_advisory_boundary_is_verified_arl_floor(self) -> None:
        result = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
        assert result.advisories[0].boundary == VERIFIED_ARL_FLOOR


__all__: list[str] = []
