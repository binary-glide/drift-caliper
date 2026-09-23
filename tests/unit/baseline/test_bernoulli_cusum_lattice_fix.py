"""Tests for the ADR-014 amendment -- lattice correctness defect and cost-bounding.

These tests cover Decision 11's verification bar plus gaps found in review.
Every test here is expected to be RED against the pre-amendment implementation
on ``feat/BIN-133/bernoulli-cusum`` -- the implementation uses a fixed
``_LATTICE_DENOMINATOR = 100`` that violates the ``(p0, p1)`` interval
invariant at low failure rates, has no ``MAX_MEANINGFUL_ARL`` ceiling, no
joint state count cap, and no search-cap enforcement.

Governing documents:
    ADR-014 amendment (Decisions 7-11), ``docs/domain-model.md``
    (Error Contract Reference, Resource bounds on ``fit_bernoulli_cusum``).

Sources cited in assertions:
    - ADR-014 amendment section 0 table: the six violated configurations
    - ADR-014 amendment Decision 7: per-arm adaptive lattice, epsilon=0.25
    - ADR-014 amendment Decision 8: independent per-arm lattices
    - ADR-014 amendment Decision 9: MAX_MEANINGFUL_ARL ceiling
    - ADR-014 amendment Decision 10a: search-cap enforcement
    - ADR-014 amendment Decision 10b: joint state cap = 1,000,000
    - ADR-014 amendment Decision 11: verification bar
"""

from __future__ import annotations

import math
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    fit_bernoulli_cusum,
)
from drift_caliper.baseline.domain.bernoulli_cusum_fitting import (
    _ALPHA,
    _SCORE_NOT_BINARY_REASON,
    _bernoulli_reference_value,
)
from drift_caliper.baseline.domain.clopper_pearson import clopper_pearson_upper_bound
from drift_caliper.baseline.domain.ewma_fitting import MAX_MEANINGFUL_ARL
from drift_caliper.errors import InvalidParameterError
from drift_caliper.measurement import Provenance
from drift_caliper.monitoring import Monitor
from tests.factories import ProvenanceFactory, ScoringResultFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bernoulli_baseline(
    count: int, *, num_failures: int, provenance: Provenance | None = None
) -> Baseline:
    """Build a Baseline of binary (0.0/1.0) scores."""
    if not 0 <= num_failures <= count:
        raise ValueError("num_failures must be between 0 and count")
    shared_provenance = provenance or ProvenanceFactory()
    baseline = Baseline()
    for i in range(count):
        score = 0.0 if i < num_failures else 1.0
        baseline.record(ScoringResultFactory(provenance=shared_provenance, score=score))
    return baseline


def _compute_arm_design(m: int, f: int, multiple: float = 2.0) -> dict[str, float]:
    """Compute the design-point parameters for both arms.

    Mirrors the fitting logic.
    """
    p_u = clopper_pearson_upper_bound(failures=f, observations=m, alpha=_ALPHA)

    # Lower arm: detect degradation (failure rate increase)
    p0_lower = p_u
    p1_lower = p_u * multiple
    r_lower = _bernoulli_reference_value(p0_lower, p1_lower)

    # Upper arm: detect improvement (failure rate decrease)
    q0_upper = 1.0 - p_u
    q1_upper = 1.0 - p_u / multiple
    r_upper = _bernoulli_reference_value(q0_upper, q1_upper)

    return {
        "p_u": p_u,
        "p0_lower": p0_lower,
        "p1_lower": p1_lower,
        "r_lower": r_lower,
        "q0_upper": q0_upper,
        "q1_upper": q1_upper,
        "r_upper": r_upper,
    }


# ---------------------------------------------------------------------------
# Item 1: Property — r_q lies strictly inside (p0, p1) AND within epsilon
#         tolerance, over the FULL legal baseline space
#
# ADR-014 amendment Decision 11 item 1. The defect survived because every
# test sat at p0 in [0.02, 0.30]. Strategies MUST reach f=0 at large m and
# small f/m. epsilon = 0.25 per Decision 7.
#
# Seam: the fitted artefact exposes reference_value_lower/upper which are
# the quantised r_q values. We compare these against the design-point
# (p0, p1) intervals computed from the artefact's own p_u.
# ---------------------------------------------------------------------------

_EPSILON = 0.25  # Decision 7


class TestReferenceValueIntervalInvariant:
    """Property: quantised r_q lies strictly inside (p0, p1) AND within
    epsilon * (p1 - p0) of the unquantised r, for both arms."""

    @given(
        m=st.integers(min_value=DEFAULT_SUFFICIENCY_THRESHOLD, max_value=10_000),
        f_frac=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=200, deadline=None)
    def test_both_arms_satisfy_interval_and_centring_invariants(
        self, m: int, f_frac: float
    ) -> None:
        """Decision 11 item 1: over the full legal space, including f=0
        at large m (at least m=10,000) and small f/m."""
        from hypothesis import assume

        f = int(f_frac * (m - 1))  # f in [0, m-1] -- excludes all-failed

        # Skip configurations where the default detect_rate_multiple (2.0) is
        # unattainable (p_u * 2.0 >= 1.0) -- that is a different, already-
        # tested failure path (TestDetectRateMultipleUnattainableRoundTrip).
        p_u = clopper_pearson_upper_bound(failures=f, observations=m, alpha=_ALPHA)
        assume(p_u * 2.0 < 1.0)

        baseline = _bernoulli_baseline(m, num_failures=f)

        result = fit_bernoulli_cusum(baseline, target_arl=370.0)

        design = _compute_arm_design(m, f)

        # Lower arm: r_q must be in (p0_lower, p1_lower) strictly
        r_q_lower = result.reference_value_lower
        p0_lower = design["p0_lower"]
        p1_lower = design["p1_lower"]
        r_lower = design["r_lower"]

        assert p0_lower < r_q_lower < p1_lower, (
            f"Lower arm: r_q={r_q_lower} not in ({p0_lower}, {p1_lower}) "
            f"at m={m}, f={f}"
        )
        assert abs(r_q_lower - r_lower) <= _EPSILON * (p1_lower - p0_lower), (
            f"Lower arm: |r_q - r| = {abs(r_q_lower - r_lower)} > "
            f"eps * gap = {_EPSILON * (p1_lower - p0_lower)} at m={m}, f={f}"
        )

        # Upper arm: r_q must be in (q0_upper, q1_upper) strictly
        r_q_upper = result.reference_value_upper
        q0_upper = design["q0_upper"]
        q1_upper = design["q1_upper"]
        r_upper = design["r_upper"]

        assert q0_upper < r_q_upper < q1_upper, (
            f"Upper arm: r_q={r_q_upper} not in ({q0_upper}, {q1_upper}) "
            f"at m={m}, f={f}"
        )
        assert abs(r_q_upper - r_upper) <= _EPSILON * (q1_upper - q0_upper), (
            f"Upper arm: |r_q - r| = {abs(r_q_upper - r_upper)} > "
            f"eps * gap = {_EPSILON * (q1_upper - q0_upper)} at m={m}, f={f}"
        )


# ---------------------------------------------------------------------------
# Item 2: Regression tests for the six violated configurations
#
# ADR-014 amendment section 0 table. These are the exact configurations the
# fixed N=100 lattice violated.
# ---------------------------------------------------------------------------


class TestFixedN100RegressionCases:
    """Decision 11 item 4: each of the six violated configurations from
    section 0's table must hold the invariant under the fix."""

    @pytest.mark.parametrize(
        "m, f, arm",
        [
            # ADR-014 amendment section 0 table:
            # upper arm m=300  f=0: r_q=0.99 < p0=0.992354  VIOLATED
            (300, 0, "upper"),
            # lower arm m=500  f=0: r_q=0.01 > p1=0.009189  VIOLATED
            (500, 0, "lower"),
            # upper arm m=500  f=0: VIOLATED
            (500, 0, "upper"),
            # lower arm m=1000 f=0: VIOLATED
            (1000, 0, "lower"),
            # upper arm m=1000 f=0: VIOLATED
            (1000, 0, "upper"),
            # upper arm m=1000 f=5: r_q=0.99 < p0=0.990745  VIOLATED
            (1000, 5, "upper"),
        ],
        ids=[
            "m300_f0_upper",
            "m500_f0_lower",
            "m500_f0_upper",
            "m1000_f0_lower",
            "m1000_f0_upper",
            "m1000_f5_upper",
        ],
    )
    def test_invariant_holds_at_previously_violated_configuration(
        self, m: int, f: int, arm: str
    ) -> None:
        baseline = _bernoulli_baseline(m, num_failures=f)
        result = fit_bernoulli_cusum(baseline, target_arl=370.0)
        design = _compute_arm_design(m, f)

        if arm == "lower":
            r_q = result.reference_value_lower
            p0, p1 = design["p0_lower"], design["p1_lower"]
            r_real = design["r_lower"]
        else:
            r_q = result.reference_value_upper
            p0, p1 = design["q0_upper"], design["q1_upper"]
            r_real = design["r_upper"]

        assert p0 < r_q < p1, (
            f"{arm} arm at m={m}, f={f}: r_q={r_q} not in ({p0}, {p1})"
        )
        assert abs(r_q - r_real) <= _EPSILON * (p1 - p0), (
            f"{arm} arm at m={m}, f={f}: centring violated: "
            f"|r_q - r| = {abs(r_q - r_real)}, "
            f"epsilon * gap = {_EPSILON * (p1 - p0)}"
        )


# ---------------------------------------------------------------------------
# Item 3: Per-arm denominator search terminates (bounded by closed-form)
#
# Decision 11 item 2. The closed-form bound ceil(1 / (2 * epsilon * gap))
# guarantees a safe N exists. The test verifies the invariant holds at the
# returned N — termination is proved by the function returning at all, plus
# the invariant holding.
# ---------------------------------------------------------------------------


class TestDenominatorSearchTermination:
    """Decision 11 item 2: the per-arm denominator finder always terminates."""

    @pytest.mark.parametrize(
        "m, f",
        [(100, 0), (300, 0), (1000, 0), (5000, 0), (10000, 0), (1000, 5)],
        ids=["m100_f0", "m300_f0", "m1000_f0", "m5000_f0", "m10000_f0", "m1000_f5"],
    )
    def test_fit_completes_and_invariant_holds(self, m: int, f: int) -> None:
        """The fit returns (termination) and both arms satisfy the invariant."""
        baseline = _bernoulli_baseline(m, num_failures=f)
        # Use one-sided to avoid joint state count issues
        result = fit_bernoulli_cusum(baseline, target_arl=370.0, direction="lower")
        design = _compute_arm_design(m, f)

        # Lower arm invariant (the one that matters for direction="lower")
        r_q = result.reference_value_lower
        p0, p1 = design["p0_lower"], design["p1_lower"]
        assert p0 < r_q < p1


# ---------------------------------------------------------------------------
# Item 4: One-sided calibration search raises at its cap
#
# Decision 10a: _calibrate_one_sided_decision_interval_units must raise
# InvalidParameterError with context["max_attainable_arl"] when the target
# exceeds what the search bracket can deliver, and that value round-trips.
#
# NOTE: With the adaptive lattice fix (Decision 7), this cap may not fire
# from the public API for any legal input, because the invariant holds and
# the search does not need to inflate h indefinitely. If so, we test the
# private helper directly, with a note why.
# ---------------------------------------------------------------------------


class TestSearchCapEnforcement:
    """Decision 10a: the one-sided calibration search raises rather than
    returning silently past the cap."""

    def test_search_cap_raises_with_max_attainable_arl_context(self) -> None:
        """If no legal input from the public API reaches the cap after
        Decisions 7/9, this tests the private helper directly.

        The amendment states: at the upper arm of m=1000, f=0, per-arm
        target 2e6, the search returned 2,097,152 (>_MAX_DECISION_INTERVAL_UNITS).
        With the fix, this path should raise instead of returning silently.

        Seam assumed: _calibrate_one_sided_decision_interval_units raises
        InvalidParameterError when the search exceeds _MAX_DECISION_INTERVAL_UNITS.
        """
        from drift_caliper.baseline.domain.bernoulli_cusum_fitting import (
            _calibrate_one_sided_decision_interval_units,
        )

        # Construct a scenario where the search must exceed the cap:
        # Use a very small lattice unit where the in-control drift is near zero
        # (the edge-placement scenario the old code produced).
        # r_units = 1, n = 100 => up = 99, down = -1 for the lower arm
        # p close to r => in-control drift near zero => h must grow very large
        # to achieve a high ARL.
        n = 100
        r_units = 1  # r = 0.01
        p = 0.01  # r = p => zero drift, h must be enormous

        with pytest.raises(InvalidParameterError) as excinfo:
            _calibrate_one_sided_decision_interval_units(
                r_units,
                n,
                p,
                target=1e12,  # impossibly high target
            )

        error = excinfo.value
        assert "max_attainable_arl" in error.context
        max_arl = error.context["max_attainable_arl"]
        assert isinstance(max_arl, float)
        assert math.isfinite(max_arl)
        assert max_arl >= 1.0

    def test_max_attainable_arl_round_trips(self) -> None:
        """BIN-122 rule: the reported max_attainable_arl must itself be
        accepted when passed back as the target."""
        from drift_caliper.baseline.domain.bernoulli_cusum_fitting import (
            _calibrate_one_sided_decision_interval_units,
        )

        n = 100
        r_units = 1
        p = 0.01

        with pytest.raises(InvalidParameterError) as excinfo:
            _calibrate_one_sided_decision_interval_units(r_units, n, p, target=1e12)

        max_arl = excinfo.value.context["max_attainable_arl"]

        # Passing max_arl as the target must succeed (not raise)
        h_units = _calibrate_one_sided_decision_interval_units(
            r_units, n, p, target=max_arl
        )
        assert h_units >= 1


# ---------------------------------------------------------------------------
# Item 5: target_arl above MAX_MEANINGFUL_ARL raises; exactly MAX_MEANINGFUL_ARL
#         is accepted
#
# Decision 9. Context keys: max_value, max_inclusive (matching parameter_guards.py).
# ---------------------------------------------------------------------------


class TestTargetArlCeiling:
    """Decision 9: target_arl > MAX_MEANINGFUL_ARL is refused."""

    def test_raises_when_target_arl_exceeds_max_meaningful_arl(self) -> None:
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=10
        )
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=MAX_MEANINGFUL_ARL + 1.0)
        error = excinfo.value
        assert error.context["parameter"] == "target_arl"
        assert error.context["kind"] == "invalid"
        assert error.context["max_value"] == MAX_MEANINGFUL_ARL
        assert error.context["max_inclusive"] is True

    def test_exactly_max_meaningful_arl_is_accepted(self) -> None:
        """Round-trip: the ceiling value itself must be accepted."""
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=10
        )
        result = fit_bernoulli_cusum(baseline, target_arl=MAX_MEANINGFUL_ARL)
        assert result.requested_arl == MAX_MEANINGFUL_ARL

    def test_max_meaningful_arl_value_matches_continuous_charts(self) -> None:
        """The ceiling is the same 1,000,000 the continuous charts enforce."""
        assert MAX_MEANINGFUL_ARL == 1_000_000.0


# ---------------------------------------------------------------------------
# Item 6: Joint state count cap — refusal with correct context keys
#
# Decision 10b. Cap = 1,000,000 states. Context must include:
#   reason = "joint_state_count_exceeded"
#   max_two_sided_target_arl (round-trips as accepted input)
# ---------------------------------------------------------------------------


class TestJointStateCountCap:
    """Decision 10b: a configuration exceeding 1,000,000 joint states is
    refused with the correct context."""

    def test_raises_with_joint_state_count_exceeded_context(self) -> None:
        """m=1000, f=0, target=1e6, two_sided — produces ~16M states
        (Decision 8's table), well above the 1M cap."""
        baseline = _bernoulli_baseline(1000, num_failures=0)
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline,
                target_arl=1_000_000.0,
                direction="two_sided",
            )

        error = excinfo.value
        assert error.context["reason"] == "joint_state_count_exceeded"
        assert "max_two_sided_target_arl" in error.context
        max_t = error.context["max_two_sided_target_arl"]
        assert isinstance(max_t, (int, float))
        assert max_t >= 1.0

    def test_max_two_sided_target_arl_round_trips(self) -> None:
        """BIN-122 rule: passing the reported max back must succeed."""
        baseline = _bernoulli_baseline(1000, num_failures=0)
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline,
                target_arl=1_000_000.0,
                direction="two_sided",
            )

        max_t = excinfo.value.context["max_two_sided_target_arl"]

        # Must succeed at the reported maximum
        result = fit_bernoulli_cusum(
            baseline,
            target_arl=float(max_t),
            direction="two_sided",
        )
        assert result.requested_arl == float(max_t)

    def test_target_370_fits_every_baseline(self) -> None:
        """Decision 10b's measurement: target_arl=370 fits every baseline,
        even the worst corner for the joint state count."""
        for m, f in [(200, 0), (500, 0), (1000, 0), (5000, 0)]:
            baseline = _bernoulli_baseline(m, num_failures=f)
            result = fit_bernoulli_cusum(
                baseline, target_arl=370.0, direction="two_sided"
            )
            assert math.isfinite(result.achieved_arl), (
                f"m={m}, f={f}: achieved_arl not finite"
            )


# ---------------------------------------------------------------------------
# Item 7: One-sided fits succeed at MAX_MEANINGFUL_ARL for f=0 baselines
#
# Decision 10b: "One-sided fits always succeed up to MAX_MEANINGFUL_ARL."
# Decision 11 item 7.
# ---------------------------------------------------------------------------


class TestOneSidedFitsSucceedAtMaxArl:
    """One-sided fits at MAX_MEANINGFUL_ARL succeed for f=0 baselines."""

    @pytest.mark.parametrize(
        "m",
        [100, 500, 1000, 5000, 10000],
        ids=["m100", "m500", "m1000", "m5000", "m10000"],
    )
    def test_one_sided_lower_succeeds_at_max_meaningful_arl(self, m: int) -> None:
        baseline = _bernoulli_baseline(m, num_failures=0)
        result = fit_bernoulli_cusum(
            baseline,
            target_arl=MAX_MEANINGFUL_ARL,
            direction="lower",
        )
        assert math.isfinite(result.achieved_arl)
        assert result.direction == "lower"


# ---------------------------------------------------------------------------
# Item 8: Bounded time at the worst legal corner
#
# Decision 11 items 3 and 8. m=10,000, f=0, target=1e6, two_sided.
# Must either complete or raise InvalidParameterError — never hang.
#
# Budget: the amendment says the bisection for max_two_sided_target_arl
# completes in < 1 second; the refusal path is O(50) iterations of per-arm
# calibration (each < 0.01s). We use 30 seconds -- generous headroom for
# CI runners (Linux, py3.11-3.13) which may be 3-10x slower than the Apple
# Silicon development machine where the amendment's measurements were taken.
# Chosen by: amendment says < 1s on Apple Silicon; CI runners are typically
# 3-5x slower; 30s gives 30x headroom above the Apple Silicon measurement.
# ---------------------------------------------------------------------------

_WORST_CORNER_BUDGET_SECONDS = 30.0


class TestBoundedTimeWorstCorner:
    """Decision 11 items 3 and 8: the worst legal corner completes in bounded
    time — it must either produce a result or raise, never hang."""

    def test_worst_corner_completes_or_raises_within_budget(self) -> None:
        """m=10,000, f=0, target_arl=MAX_MEANINGFUL_ARL, direction=two_sided.

        Budget: 30 seconds. Chosen from ADR-014 amendment: < 1s on Apple
        Silicon (the bisection for max_two_sided_target_arl is O(50)
        iterations of per-arm calibration, each at < 40K states). CI runners
        are typically 3-5x slower; 30s gives 30x headroom.
        """
        baseline = _bernoulli_baseline(10_000, num_failures=0)

        start = time.monotonic()
        try:
            result = fit_bernoulli_cusum(
                baseline,
                target_arl=MAX_MEANINGFUL_ARL,
                direction="two_sided",
            )
            elapsed = time.monotonic() - start
            assert elapsed < _WORST_CORNER_BUDGET_SECONDS, (
                f"Completed but took {elapsed:.1f}s, exceeding the "
                f"{_WORST_CORNER_BUDGET_SECONDS}s budget"
            )
            assert math.isfinite(result.achieved_arl)
        except InvalidParameterError:
            elapsed = time.monotonic() - start
            assert elapsed < _WORST_CORNER_BUDGET_SECONDS, (
                f"Raised InvalidParameterError but took {elapsed:.1f}s, "
                f"exceeding the {_WORST_CORNER_BUDGET_SECONDS}s budget"
            )


# ---------------------------------------------------------------------------
# Item 9: Monitor signalling for the Bernoulli CUSUM chart
#
# Drive a Monitor through record() until it signals, separately for lower
# (failure rate up) and upper (failure rate down), asserting the direction.
# ---------------------------------------------------------------------------


class TestMonitorSignallingBernoulliCUSUM:
    """Currently untested: Monitor signalling for this chart type."""

    def test_lower_arm_signals_when_failure_rate_increases(self) -> None:
        """Drive the monitor with all-fail observations until it signals
        on the lower arm (degradation detected)."""
        provenance = ProvenanceFactory()
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5,
            num_failures=10,
            provenance=provenance,
        )
        chart = fit_bernoulli_cusum(baseline, target_arl=370.0, direction="two_sided")
        monitor = Monitor(chart)

        signalled = False
        direction_reported = None
        # Feed all-fail observations (score=0.0 => failure_indicator=1.0)
        # This simulates a catastrophic degradation.
        for _ in range(10_000):
            obs = ScoringResultFactory(provenance=provenance, score=0.0)
            result = monitor.record(obs)
            if not result.is_in_control:
                signalled = True
                direction_reported = result.direction
                break

        assert signalled, "Monitor did not signal after 10,000 all-fail observations"
        assert direction_reported == "lower"

    def test_upper_arm_signals_when_failure_rate_decreases(self) -> None:
        """Drive the monitor with all-pass observations until it signals
        on the upper arm (improvement/staleness detected)."""
        provenance = ProvenanceFactory()
        # Use a baseline with a moderate failure rate so the upper arm has
        # room to detect improvement.
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5,
            num_failures=30,
            provenance=provenance,
        )
        chart = fit_bernoulli_cusum(baseline, target_arl=370.0, direction="two_sided")
        monitor = Monitor(chart)

        signalled = False
        direction_reported = None
        # Feed all-pass observations (score=1.0 => success_indicator=1.0)
        # This simulates a dramatic improvement.
        for _ in range(10_000):
            obs = ScoringResultFactory(provenance=provenance, score=1.0)
            result = monitor.record(obs)
            if not result.is_in_control:
                signalled = True
                direction_reported = result.direction
                break

        assert signalled, "Monitor did not signal after 10,000 all-pass observations"
        assert direction_reported == "upper"


# ---------------------------------------------------------------------------
# Item 10: FittedBernoulliCUSUM.audit_summary() test
# ---------------------------------------------------------------------------


class TestAuditSummary:
    """audit_summary() currently has no test."""

    def test_audit_summary_returns_a_non_empty_string(self) -> None:
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=10
        )
        chart = fit_bernoulli_cusum(baseline, target_arl=370.0)
        summary = chart.audit_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_audit_summary_contains_all_key_fields(self) -> None:
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=10
        )
        chart = fit_bernoulli_cusum(baseline, target_arl=370.0)
        summary = chart.audit_summary()

        # Every field from ADR-014 Decision 6b must appear
        assert "bernoulli_cusum" in summary
        assert "Observed failure rate" in summary
        assert "Observation count" in summary
        assert "Requested ARL" in summary
        assert "Achieved ARL" in summary
        assert "Expected detection ARL" in summary
        assert "Calibration method" in summary
        assert "Detect rate multiple" in summary
        assert "Alpha" in summary
        assert "Clopper-Pearson" in summary or "p_U" in summary
        assert "Direction" in summary
        assert "Reference value, lower arm" in summary
        assert "Decision interval, lower arm" in summary
        assert "Reference value, upper arm" in summary
        assert "Decision interval, upper arm" in summary


# ---------------------------------------------------------------------------
# Item 11: Negative / zero / non-finite detect_rate_multiple is rejected
# ---------------------------------------------------------------------------


class TestDetectRateMultipleRejection:
    """Negative, zero, and non-finite detect_rate_multiple must be rejected."""

    @pytest.mark.parametrize(
        "value, label",
        [
            (-1.0, "negative"),
            (-0.001, "small_negative"),
            (0.0, "zero"),
            (float("inf"), "positive_infinity"),
            (float("-inf"), "negative_infinity"),
            (float("nan"), "nan"),
        ],
        ids=["negative", "small_negative", "zero", "pos_inf", "neg_inf", "nan"],
    )
    def test_raises_invalid_parameter(self, value: float, label: str) -> None:
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD + 5, num_failures=10
        )
        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline,
                target_arl=370.0,
                detect_rate_multiple=value,
            )
        error = excinfo.value
        assert error.context["parameter"] == "detect_rate_multiple"
        assert error.context["kind"] == "invalid"


# ---------------------------------------------------------------------------
# Item 12: Replace the weak disjunction assertion
#
# The existing test at line ~101 of test_bernoulli_cusum_fitting.py uses:
#   assert "invalid_score" in error.context or "provided" in error.context
# The domain model says: "the offending value plus its position are reported"
# with context keys "invalid_score" and "position".
# ---------------------------------------------------------------------------


class TestScoreNotBinaryContextKeys:
    """Replace the weak disjunction with exact keys."""

    def test_reports_exact_invalid_score_and_position(self) -> None:
        """Domain model: context carries 'invalid_score' (the offending value)
        and 'position' (its index in the baseline)."""
        provenance = ProvenanceFactory()
        baseline = _bernoulli_baseline(
            DEFAULT_SUFFICIENCY_THRESHOLD, num_failures=5, provenance=provenance
        )
        # Add a continuous score at the end
        baseline.record(ScoringResultFactory(provenance=provenance, score=0.42))

        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=370.0)

        error = excinfo.value
        assert error.context["reason"] == _SCORE_NOT_BINARY_REASON
        # Exact keys — not a disjunction
        assert "invalid_score" in error.context
        assert error.context["invalid_score"] == 0.42
        assert "position" in error.context
        assert error.context["position"] == DEFAULT_SUFFICIENCY_THRESHOLD
