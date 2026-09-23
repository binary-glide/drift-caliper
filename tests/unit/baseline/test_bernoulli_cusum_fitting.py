"""Unit tests for `fit_bernoulli_cusum` -- business rules the feature file leaves out.

Covers what
``tests/bdd/features/baseline/bernoulli-cusum-control-limit-fitting.feature``
deliberately does not assert (no numeric literals, per that file's own header
comments) and what its scenarios cannot reach at all (the Phase II binary-score
contract, ADR-014 Decision 2 -- see that file's own "Decision made while
writing these scenarios" note). The numeric ARL proof itself lives in
``test_bernoulli_cusum_arl_published_values.py``; the Clopper-Pearson proof in
``test_clopper_pearson.py``. This file is everything else ADR-012/013/014
settle that a BDD scenario cannot express without leaking mechanism.

Governing documents: ADR-012 (design rule), ADR-013 (GICP, alpha=0.10),
ADR-014 (API surface, artefact shape), ``docs/domain-model.md`` (Object Map --
FittedBernoulliCUSUM, Monitor invariant 9, Error Contract Reference, Open
Questions #23/#24).
"""

from __future__ import annotations

import inspect
import math

import pytest
from scipy.stats import beta as scipy_beta  # type: ignore[attr-defined]

# 🚨 Neither of these exists in `drift_caliper.baseline` yet -- the expected red.
from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    fit_bernoulli_cusum,
)
from drift_caliper.baseline.domain.has_provenance import HasProvenance
from drift_caliper.errors import (
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)
from drift_caliper.measurement import Provenance
from tests.factories import ProvenanceFactory, ScoringResultFactory

_VALID_TARGET_ARL = 370.0


def _bernoulli_baseline(
    count: int, *, num_failures: int, provenance: Provenance | None = None
) -> Baseline:
    if not 0 <= num_failures <= count:
        raise ValueError("num_failures must be between 0 and count")
    shared_provenance = provenance or ProvenanceFactory()
    baseline = Baseline()
    for i in range(count):
        score = 0.0 if i < num_failures else 1.0
        baseline.record(ScoringResultFactory(provenance=shared_provenance, score=score))
    return baseline


def _mixed_baseline(*, extra: int = 5, failure_rate: float = 0.1) -> Baseline:
    count = DEFAULT_SUFFICIENCY_THRESHOLD + extra
    return _bernoulli_baseline(count, num_failures=max(1, round(count * failure_rate)))


# ===========================================================================
# Baseline type / score-not-binary validation (ADR-014 Decision 1)
# ===========================================================================


class TestBaselineTypeValidation:
    def test_raises_invalid_parameter_for_a_non_baseline_argument(self) -> None:
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                "not a baseline",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                target_arl=_VALID_TARGET_ARL,
            )
        assert excinfo.value.context["parameter"] == "baseline"


class TestScoreNotBinaryRejection:
    """ADR-014 Decision 1's validation order step 2: every score must be exactly
    0.0/1.0."""

    def test_raises_when_a_baseline_score_is_a_legal_continuous_value(self) -> None:
        provenance = ProvenanceFactory()
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD, num_failures=5, provenance=provenance
        )
        # Overwrite one observation's score with a legal, finite, in-range
        # continuous value -- exactly the case ADR-014 Decision 1 targets:
        # "a baseline containing any other value (including a legal, finite,
        # in-range continuous score)".
        baseline.record(ScoringResultFactory(provenance=provenance, score=0.42))

        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)

        error = excinfo.value
        assert error.context["parameter"] == "baseline"
        assert error.context["kind"] == "invalid"
        assert error.context["reason"] == "score_not_binary"
        # "the offending value plus its position are reported" (domain-model.md).
        # Exact keys -- not a disjunction (ADR-014 amendment fix).
        assert "invalid_score" in error.context
        assert error.context["invalid_score"] == 0.42
        assert "position" in error.context
        assert isinstance(error.context["position"], int)

    def test_checked_before_sufficiency(self) -> None:
        """Validation order step 2 (score check) precedes step 4 (sufficiency, BIN-64).

        A too-small baseline that ALSO contains a non-binary score must
        raise for the score, not for insufficiency -- otherwise an engineer
        fixing the reported problem first (adding more observations) would
        still be surprised by a second, undisclosed problem.
        """
        provenance = ProvenanceFactory()
        baseline = _bernoulli_baseline(10, num_failures=2, provenance=provenance)
        baseline.record(ScoringResultFactory(provenance=provenance, score=0.5))

        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert excinfo.value.context["reason"] == "score_not_binary"


# ===========================================================================
# target_arl -- optional-with-required-semantics (ADR-004 section 5)
# ===========================================================================


class TestTargetArlRequired:
    def test_raises_missing_when_target_arl_is_omitted(self) -> None:
        baseline = _mixed_baseline()
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=None)
        assert excinfo.value.context["kind"] == "missing"
        assert excinfo.value.context["parameter"] == "target_arl"


# ===========================================================================
# ADR-005's unchanged 100-observation floor (ADR-013 section 2)
# ===========================================================================


class TestSufficiencyFloorUnchanged:
    def test_raises_insufficient_baseline_below_100_observations(self) -> None:
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD - 1, num_failures=1
        )
        with pytest.raises(InsufficientBaselineError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert excinfo.value.context["have"] == DEFAULT_SUFFICIENCY_THRESHOLD - 1
        assert excinfo.value.context["need"] == DEFAULT_SUFFICIENCY_THRESHOLD

    def test_fits_successfully_at_exactly_100_observations(self) -> None:
        baseline = _bernoulli_baseline(DEFAULT_SUFFICIENCY_THRESHOLD, num_failures=10)
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.observation_count == DEFAULT_SUFFICIENCY_THRESHOLD

    def test_no_new_higher_binary_specific_floor_ships(self) -> None:
        """ADR-013 section 2 supersedes the provisional 1,500-observation floor.

        100 observations must be sufficient on its own -- no silent second
        threshold.
        """
        baseline = _bernoulli_baseline(150, num_failures=15)
        # Must not raise InsufficientBaselineError at 150 -- would indicate a
        # reintroduced provisional floor.
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.observation_count == 150


# ===========================================================================
# Never raises DegenerateBaselineError (ADR-013 section 5 / domain-model.md)
# ===========================================================================


class TestNeverRaisesDegenerateBaseline:
    """GICP folds both former degenerate cases into other, more specific paths."""

    def test_zero_failure_baseline_does_not_raise_degenerate_baseline_error(
        self,
    ) -> None:
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=0
        )
        try:
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        except DegenerateBaselineError:
            pytest.fail(
                "fit_bernoulli_cusum must never raise DegenerateBaselineError "
                "(ADR-013 section 5) -- p_hat=0 is designed at p_U instead"
            )

    def test_all_failed_baseline_raises_invalid_parameter_not_degenerate_baseline(
        self,
    ) -> None:
        count = DEFAULT_SUFFICIENCY_THRESHOLD + 5
        baseline = _bernoulli_baseline(count, num_failures=count)
        with pytest.raises(InvalidParameterError):
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        # Confirm it is specifically NOT the old degenerate-baseline category.
        try:
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        except DegenerateBaselineError:
            pytest.fail("all-failed baseline must not raise DegenerateBaselineError")
        except InvalidParameterError:
            pass


class TestZeroFailureBaselineDisclosesDetectionWeakness:
    """BR-7: the zero-failure relief and the detection disclosure ship together,
    or neither does.

    🚨 Non-vacuous by construction: both the successful fit AND the
    disclosure are asserted in the SAME test, so a lift of the refusal
    without the disclosure (ADR-013 section 5's named failure mode) fails
    this test even though `fit_bernoulli_cusum` itself returns successfully.
    """

    def test_fits_successfully_and_reports_expected_detection_arl(self) -> None:
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=0
        )
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)

        # Half 1: the fit succeeded (reaching here at all is part of the proof).
        assert result.observed_failure_rate == 0.0

        # Half 2: the detection-performance disclosure is present and is a
        # real, finite number -- not merely a default/placeholder.
        assert isinstance(result.expected_detection_arl, float)
        assert math.isfinite(result.expected_detection_arl)
        assert result.expected_detection_arl > 0.0


class TestAllFailedBaselineErrorShape:
    def test_reason_is_all_baseline_judgements_failed(self) -> None:
        count = DEFAULT_SUFFICIENCY_THRESHOLD + 5
        baseline = _bernoulli_baseline(count, num_failures=count)
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert excinfo.value.context["reason"] == "all_baseline_judgements_failed"

    def test_carries_no_max_detect_rate_multiple_key(self) -> None:
        """ADR-013 section 5: no multiple would fix an all-failed baseline."""
        count = DEFAULT_SUFFICIENCY_THRESHOLD + 5
        baseline = _bernoulli_baseline(count, num_failures=count)
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert "max_detect_rate_multiple" not in excinfo.value.context


# ===========================================================================
# detect_rate_multiple -- default, custom, unattainable, round-trip
# ===========================================================================


class TestDetectRateMultipleDefault:
    def test_defaults_to_2_0(self) -> None:
        """ADR-012 section 1: 2.0 is the measured, largest-defined-everywhere value."""
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.detect_rate_multiple == 2.0


class TestDetectRateMultipleUnattainableRoundTrip:
    """BIN-122's contract: the reported maximum must itself be accepted (ADR-013 section
    6b)."""

    def test_raises_invalid_parameter_when_design_point_exceeds_one(self) -> None:
        baseline = _mixed_baseline()
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline, target_arl=_VALID_TARGET_ARL, detect_rate_multiple=1e6
            )
        assert excinfo.value.context["parameter"] == "detect_rate_multiple"
        assert excinfo.value.context["kind"] == "invalid"
        assert "max_detect_rate_multiple" in excinfo.value.context

    def test_reported_maximum_is_computed_from_p_u_not_p_hat(self) -> None:
        """ADR-013 section 6b: the bound must be computed from p_U, what GICP actually
        uses.

        A bound computed from p_hat would name a multiple GICP then
        refuses on resupply, breaking the round-trip guarantee at exactly
        the boundary that matters.
        """
        baseline = _mixed_baseline()
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline, target_arl=_VALID_TARGET_ARL, detect_rate_multiple=1e6
            )
        max_multiple = excinfo.value.context["max_detect_rate_multiple"]

        # Refit at exactly the reported maximum: must succeed (the actual
        # round-trip assertion -- proves the bound is computed against
        # whatever rate the design step actually uses, p_U).
        result = fit_bernoulli_cusum(
            baseline, target_arl=_VALID_TARGET_ARL, detect_rate_multiple=max_multiple
        )
        assert result.detect_rate_multiple == max_multiple

    def test_reported_maximum_matches_1_over_p_u_within_the_design_margin(self) -> None:
        """The bound must be derived from `1 / p_U`, not `1 / p_hat` -- checked
        directly.

        `p_U >= p_hat` always (Clopper-Pearson), so `1/p_U <= 1/p_hat`: a
        p_hat-derived bound would be strictly LARGER than the true (p_U-
        derived) ceiling and would therefore itself be refused on
        resupply -- exactly the round-trip failure ADR-013 section 6b warns
        against. This test pins the direction, not only the round-trip
        outcome.
        """
        baseline = _mixed_baseline()
        fitted = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        p_u = fitted.p_u
        p_hat = fitted.observed_failure_rate

        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline, target_arl=_VALID_TARGET_ARL, detect_rate_multiple=1e6
            )
        max_multiple = excinfo.value.context["max_detect_rate_multiple"]

        # The p_U-derived ceiling must be strictly below the p_hat-derived
        # one whenever p_U > p_hat (the ordinary case for a mixed baseline).
        assert max_multiple < (1.0 / p_hat)
        assert max_multiple == pytest.approx(1.0 / p_u, rel=1e-3)


# ===========================================================================
# direction -- two-sided default, restrictable (ADR-012 amendment)
# ===========================================================================


class TestDirection:
    def test_defaults_to_two_sided(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.direction == "two_sided"

    @pytest.mark.parametrize("direction", ["lower", "upper", "two_sided"])
    def test_accepts_every_valid_direction(self, direction: str) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(
            baseline, target_arl=_VALID_TARGET_ARL, direction=direction
        )
        assert result.direction == direction

    def test_rejects_an_unrecognised_direction(self) -> None:
        baseline = _mixed_baseline()
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline, target_arl=_VALID_TARGET_ARL, direction="sideways"
            )
        assert excinfo.value.context["parameter"] == "direction"

    def test_both_arms_always_reported_regardless_of_direction(self) -> None:
        """ADR-014 section 6b: both arms' fields present regardless of `direction`.

        Mirrors `Monitor._check_cusum`'s "both sums always updated
        regardless of direction" convention.
        """
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(
            baseline, target_arl=_VALID_TARGET_ARL, direction="lower"
        )
        assert isinstance(result.reference_value_upper, float)
        assert isinstance(result.decision_interval_upper, float)


# ===========================================================================
# alpha -- fixed at 0.10, not engineer-facing (ADR-014 Decision 5)
# ===========================================================================


class TestAlphaIsFixedAndReportedNotSettable:
    def test_reports_the_ratified_default(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.alpha == 0.10

    def test_fit_bernoulli_cusum_takes_no_alpha_parameter(self) -> None:
        """Pins ADR-014 Decision 5 so it cannot be quietly reopened.

        Mirrors `compare_provenance`'s existing
        `test_takes_no_acknowledge_or_force_override_parameter` pattern.
        """
        signature = inspect.signature(fit_bernoulli_cusum)
        assert "alpha" not in signature.parameters


# ===========================================================================
# GICP -- p_U substitutes for p_hat in the design (ADR-013 section 1)
# ===========================================================================


class TestGICPDesignUsesConfidenceBoundNotPointEstimate:
    def test_p_u_is_at_least_the_point_estimate(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.p_u >= result.observed_failure_rate

    def test_p_u_matches_the_clopper_pearson_formula_directly(self) -> None:
        """Independent check: recomputes p_U via `scipy.stats.beta` directly, not via
        `clopper_pearson_upper_bound` (already covered by `test_clopper_pearson.py`) --
        this test is about `fit_bernoulli_cusum` actually USING it, not about the
        formula's own correctness."""
        count = DEFAULT_SUFFICIENCY_THRESHOLD + 5
        num_failures = 10
        baseline = _bernoulli_baseline(count, num_failures=num_failures)
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        expected_p_u = scipy_beta.ppf(1 - 0.10, num_failures + 1, count - num_failures)
        assert result.p_u == pytest.approx(expected_p_u, rel=1e-9)


# ===========================================================================
# expected_detection_arl -- ADR-013 section 4's definition
# ===========================================================================


class TestExpectedDetectionArl:
    def test_present_and_finite_on_the_ordinary_happy_path(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert math.isfinite(result.expected_detection_arl)
        assert result.expected_detection_arl > 0.0

    def test_differs_from_achieved_arl(self) -> None:
        """Two distinct questions, ADR-013 section 4: false-alarm safety vs. detection
        speed."""
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.expected_detection_arl != result.achieved_arl


# ===========================================================================
# calibration_method -- honest naming (ADR-014 section 6c)
# ===========================================================================


class TestCalibrationMethodNaming:
    def test_two_sided_reports_a_named_calibration_method(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(
            baseline, target_arl=_VALID_TARGET_ARL, direction="two_sided"
        )
        assert result.calibration_method in (
            "gicp_markov_chain",
            "gicp_markov_chain_harmonic_combination",
        )

    def test_one_sided_reports_the_exact_method(self) -> None:
        """ADR-012 section 4/5: one-sided configurations are unaffected by Open Question
        #24."""
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(
            baseline, target_arl=_VALID_TARGET_ARL, direction="lower"
        )
        assert result.calibration_method == "gicp_markov_chain"


# ===========================================================================
# Auditability, immutability, protocol conformance
# ===========================================================================


class TestAuditability:
    def test_reports_observed_failure_rate_and_observation_count(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert result.observation_count == baseline.observation_count
        assert 0.0 <= result.observed_failure_rate <= 1.0

    def test_reports_provenance(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        signature = baseline.provenance_signature
        assert signature is not None
        assert result.provenance_model_version == signature.model_version.value
        assert result.provenance_criteria == signature.scoring_criteria.value


class TestImmutability:
    def test_reassigning_a_field_raises_pydantic_validation_error(self) -> None:
        """ADR-002 section 7: immutability violations are NOT part of the CaliperError
        taxonomy."""
        import pydantic

        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        with pytest.raises(pydantic.ValidationError):
            result.observed_failure_rate = 0.99  # ty: ignore[invalid-assignment]


class TestFittedBernoulliCUSUMProtocolConformance:
    """ADR-014 Decision 6a: satisfies `HasProvenance` only, not
    `FittedControlLimits`."""

    def test_satisfies_has_provenance(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert isinstance(result, HasProvenance)

    def test_does_not_satisfy_fitted_control_limits(self) -> None:
        """It has no `sigma_estimate`/`baseline_mean`/`baseline_spread` --
        deliberately."""
        from drift_caliper.baseline.domain.fitted_control_limits import (
            FittedControlLimits,
        )

        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert not isinstance(result, FittedControlLimits)

    def test_carries_no_sigma_based_fields(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert not hasattr(result, "sigma_estimate")
        assert not hasattr(result, "baseline_mean")
        assert not hasattr(result, "baseline_spread")
        assert not hasattr(result, "target_value")


class TestTruthinessForbidden:
    """BIN-110: no `Fitted*` type has a "failed" instance, so bool() must raise, not
    default True."""

    def test_bool_raises_type_error(self) -> None:
        baseline = _mixed_baseline()
        result = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        with pytest.raises(TypeError):
            bool(result)


# ===========================================================================
# Determinism (BR-6 -- no chart Caliper ships consults an RNG)
# ===========================================================================


class TestDeterminism:
    def test_fitting_the_same_baseline_twice_produces_identical_figures(self) -> None:
        baseline = _mixed_baseline()
        first = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        second = fit_bernoulli_cusum(baseline, target_arl=_VALID_TARGET_ARL)
        assert first.achieved_arl == second.achieved_arl
        assert first.expected_detection_arl == second.expected_detection_arl
        assert first.p_u == second.p_u
        assert first.reference_value_lower == second.reference_value_lower
        assert first.decision_interval_lower == second.decision_interval_lower


# ===========================================================================
# Open Question #23 -- upper-arm coverage is UNVERIFIED, not asserted either way
# ===========================================================================


@pytest.mark.skip(
    reason=(
        "Open Question #23 (docs/domain-model.md; ADR-014 section 6d): whether "
        "p_U preserves the 1-alpha false-alarm coverage guarantee for the "
        "UPPER (improvement-detecting) arm is unverified -- Heidema et al.'s "
        "GICP proof covers detecting a parameter INCREASE, the direction an "
        "upper confidence bound is conservative for; the upper arm here "
        "detects a DECREASE, a related but distinct question nobody has "
        "measured or derived on this ticket. Asserting the guarantee holds "
        "would go green while claiming something unproven -- the exact "
        "vacuity shape this project has repeatedly caught (CLAUDE.md's "
        "'Vacuity is this project's blind spot' note). This test is a "
        "deliberate placeholder recording the gap, not a probe for it: "
        "closing it requires a mirrored study of ADR-013 section 3's 40-cell "
        "grid at the upper arm's own design point, which is out of scope for "
        "this ticket and explicitly deferred to a future amendment."
    )
)
def test_upper_arm_false_alarm_coverage_is_unverified_open_question_23() -> None:
    raise NotImplementedError(
        "intentionally not implemented -- see the skip reason above; do not "
        "fill this in with an assertion that the guarantee holds or does not "
        "hold without first performing the measurement ADR-013 section 7 "
        "requires"
    )
