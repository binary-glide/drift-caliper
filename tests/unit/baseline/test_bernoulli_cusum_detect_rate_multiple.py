"""``detect_rate_multiple``'s legal range and the lattice finder (ADR-014 C2, C12).

Decision 18 items 20, 25 and 26. Governing text: the Amendment 2 corrigendum
C2 (the legal range, F16, the O(log N) finder), C12.1 (``min_value`` over the
arms the fit designs, as the nearest constructible multiple at or above the
request) and C12.4 (the shipped finder's centring guarantee fails at large
``M`` -- a defect no test reached because every test used ``M <= 5``).

**Reproduced on PR #29** (m=200 f=20 T=370, the coordinator's report, C2):
``M=1.0`` leaks ``ZeroDivisionError``, ``M=0.5`` leaks ``ValueError``,
``M=1.0000001`` hangs in Decision 7's linear scan. Each is pinned below; the
hang is bounded by a pytest-timeout marker so the red run stays finite.

**The ``"no_valid_multiple"`` case (C2, item 20's "measure whether it is
reachable").** Measured for this red phase with the independent reference
(``tests.support.bernoulli_reference``): at ``f = m - 1`` the only way to put
``p_U`` near 1, every lower-arm design on a 400-point grid of ``M`` in
``(1, max_detect_rate_multiple)`` was constructible at m = 300,000 (399/399),
1,000,000 (398/399), 3,000,000 (396/399) and 10,000,000 (356/399). So it is
**not reachable** at any baseline size this library can plausibly hold, and
there is no public-API cell to pin; F16's other two reasons are pinned.

The lattice finder's output is read through the artefact's ``lattice_lower``/
``lattice_upper`` (Decision 14) and checked against the reference's copy of
Decision 7's ratified rule -- not against a private helper, so the test
survives the finder being rewritten (which C2/C12.4 require).
"""

from __future__ import annotations

import math
from functools import cache

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from drift_caliper.baseline import Baseline, FittedBernoulliCUSUM, fit_bernoulli_cusum
from drift_caliper.errors import InvalidParameterError
from tests.support import bernoulli_reference as ref
from tests.support.bernoulli_surface import triplet
from tests.support.binary_baselines import binary_baseline

_NO_SHIFT = "no_shift_to_detect"
_BELOW_RESOLUTION = "shift_below_numerical_resolution"
# corrigendum C12.1 (``k5_monotone.py``): every non-constructible multiple
# measured lies below M - 1 = 5.41e-8.
_NON_CONSTRUCTIBLE_BAND_TOP = 5.41e-8
# corrigendum C2 (``h4_resolution.py``): every baseline measured fails at
# M - 1 = 1e-8 or 1e-9; 1e-10 is safely below every one.
_UNRESOLVABLE_MULTIPLE = 1.0 + 1e-10
# The cheapest legal target: calibration returns h_units = 1 at once
# (ARL(1) >= 1 always), so a test about the *lattice* pays nothing for the
# decision interval.
_CHEAP_TARGET = 1.0


def _fit(
    m: int,
    f: int,
    multiple: float,
    *,
    direction: str = "two_sided",
    target_arl: float = _CHEAP_TARGET,
) -> FittedBernoulliCUSUM:
    baseline, _ = binary_baseline(m, f)
    return fit_bernoulli_cusum(
        baseline,
        target_arl=target_arl,
        detect_rate_multiple=multiple,
        direction=direction,
    )


def _f16(m: int, f: int, multiple: float, direction: str) -> dict[str, object]:
    with pytest.raises(InvalidParameterError) as excinfo:
        _fit(m, f, multiple, direction=direction)
    context = dict(excinfo.value.context)
    assert context["parameter"] == "detect_rate_multiple"
    assert context["kind"] == "invalid"
    assert context["provided"] == multiple
    assert "constraint" in context
    return context


# ===========================================================================
# M <= 1 -- no shift to detect (F16, C2)
# ===========================================================================


class TestNoShiftToDetect:
    """C2: ``M = 1`` detects no shift; ``M < 1`` would mislabel the arms."""

    @pytest.mark.parametrize(
        "multiple",
        [1.0, 0.5, 1.0 - 1e-12, 0.0, -1.0],
        ids=[
            "one_leaked_ZeroDivisionError",
            "half_leaked_ValueError",
            "just_below_one",
            "zero_now_F16_not_F7",
            "negative_now_F16_not_F7",
        ],
    )
    # Budget: a single refusal, no chain solved on the F16 path; the
    # min_value bisection is <= 64 probes of an O(log N) finder at ~0.2 ms
    # each (C2) -- well under 0.1 s. 30 s bounds a hang.
    @pytest.mark.timeout(30)
    def test_refuses_with_a_round_tripping_minimum(self, multiple: float) -> None:
        """F16 with ``reason="no_shift_to_detect"``, ``min_value`` and
        ``min_inclusive=True``. C2: F16 owns every lower bound, so zero and
        negative multiples move here from F7."""
        context = _f16(200, 20, multiple, "two_sided")

        assert context["reason"] == _NO_SHIFT
        assert context["min_inclusive"] is True
        minimum = context["min_value"]
        assert isinstance(minimum, float)
        assert minimum > 1.0

        chart = _fit(200, 20, minimum)
        assert chart.detect_rate_multiple == minimum


class TestNonFiniteMultiple:
    """C2: F7 narrows to a non-finite multiple; its ``min_value=0.0``/
    ``min_inclusive=False`` are withdrawn because F16 owns every lower bound."""

    @pytest.mark.parametrize(
        "multiple", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "-inf"]
    )
    def test_reports_no_lower_bound(self, multiple: float) -> None:
        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(200, 20, multiple)

        context = excinfo.value.context
        assert context["parameter"] == "detect_rate_multiple"
        assert context["kind"] == "invalid"
        assert "constraint" in context
        assert "provided" in context
        assert "min_value" not in context
        assert "min_inclusive" not in context


# ===========================================================================
# Just above 1 -- the design outruns double precision (C2, C12.1)
# ===========================================================================


class TestJustAboveOne:
    """Decision 18 items 20 and 26."""

    @pytest.mark.parametrize(
        ("direction", "expected_lattice"),
        [
            ("lower", (8892, 1181, 54736)),
            ("upper", (14251, 13204, 66483)),
        ],
    )
    # Budget: reference implementation 0.71 s ("lower") / 0.56 s ("upper")
    # locally for the same fit (calibration over chains of up to ~66k states);
    # x3 = 2.1 s; 60 s allows ~25x for an unvectorised matrix build. The shipped
    # linear scan hangs here (C2: ~1.5e8 / ~3.4e8 steps), so this marker is
    # what keeps today's red run finite.
    @pytest.mark.timeout(60)
    def test_multiple_one_plus_1e_minus_7_completes(
        self, direction: str, expected_lattice: tuple[int, int, int]
    ) -> None:
        """C2's table: m=200 f=20 ``M = 1.0000001`` fits, ``"lower"`` at
        ``h = 54,736`` and ``"upper"`` at ``h = 66,483`` -- the O(log N) finder
        instead of the linear scan that hung."""
        chart = _fit(200, 20, 1.0000001, direction=direction, target_arl=370.0)

        lattice = chart.lattice_lower if direction == "lower" else chart.lattice_upper
        assert triplet(lattice) == expected_lattice

    # Budget: reference D feasibility check 1.9 s + C11 bound 0.9 s locally;
    # the round-trip at the reported bound (3) is trivial. x3 = 8.4 s; 90 s
    # for the unbuilt refusal path.
    @pytest.mark.timeout(90)
    def test_two_sided_at_one_plus_1e_minus_7_refuses_within_the_caps(self) -> None:
        """C2's table: two-sided at ``M = 1.0000001`` is F13, not a hang, and its
        bound round-trips (C11: the independent reference gives 3)."""
        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(200, 20, 1.0000001, direction="two_sided", target_arl=370.0)

        context = excinfo.value.context
        assert context["reason"] == "joint_state_count_exceeded"
        bound = context["max_two_sided_target_arl"]
        chart = _fit(200, 20, 1.0000001, direction="two_sided", target_arl=bound)
        assert chart.requested_arl == bound

    @pytest.mark.parametrize("direction", ["lower", "upper", "two_sided"])
    # Budget: the F16 refusal is a bisection of <= 64 finder probes (C2:
    # 0.1-0.2 ms each) and the round-trip fit is at target 1.0 -- both well
    # under 1 s (x3 = 3 s). 20 s bounds a regression to the linear scan.
    @pytest.mark.timeout(20)
    def test_below_resolution_reports_the_nearest_constructible_multiple(
        self, direction: str
    ) -> None:
        """C12.1: F16 fires when the designed arms are not constructible at the
        requested ``M``; ``min_value`` is the nearest constructible multiple at or
        above it, round-trips, and the next float below it is refused (C2 item
        20's "``min_value`` minus one float step raises F16")."""
        context = _f16(200, 20, _UNRESOLVABLE_MULTIPLE, direction)

        assert context["reason"] == _BELOW_RESOLUTION
        assert context["min_inclusive"] is True
        minimum = context["min_value"]
        assert isinstance(minimum, float)
        assert minimum >= _UNRESOLVABLE_MULTIPLE
        assert 1e-10 < minimum - 1.0 <= _NON_CONSTRUCTIBLE_BAND_TOP

        assert _fit(200, 20, minimum, direction=direction).detect_rate_multiple == (
            minimum
        )
        below = math.nextafter(minimum, 0.0)
        if below >= _UNRESOLVABLE_MULTIPLE:
            assert _f16(200, 20, below, direction)["reason"] == _BELOW_RESOLUTION

    # Budget: three F16 refusals, each well under 1 s (see above).
    @pytest.mark.timeout(20)
    def test_min_value_differs_by_direction(self) -> None:
        """C12.1's table: at m=100 f=60, "two_sided" (7.35e-9) is its own
        computation, not the larger of "lower" (3.53e-9) and "upper" (3.54e-9)."""
        minima = {
            direction: _f16(100, 60, _UNRESOLVABLE_MULTIPLE, direction)["min_value"]
            for direction in ("lower", "upper", "two_sided")
        }

        assert len(set(minima.values())) == 3

    # Budget: two F16 refusals, well under 1 s.
    @pytest.mark.timeout(20)
    def test_zero_failure_two_sided_minimum_equals_the_lower_minimum(self) -> None:
        """C12.1: at f = 0 a two-sided request designs the same single arm as
        "lower" (19.2), so its ``min_value`` is identical."""
        two_sided = _f16(1000, 0, _UNRESOLVABLE_MULTIPLE, "two_sided")
        lower = _f16(1000, 0, _UNRESOLVABLE_MULTIPLE, "lower")

        assert two_sided["min_value"] == lower["min_value"]


# ===========================================================================
# C12.4 -- the lattice finder at large M
# ===========================================================================


def _assert_lattice_is_the_ratified_one(
    chart: FittedBernoulliCUSUM, arm: str, multiple: float
) -> None:
    if arm == "lower":
        p0, p1 = ref.lower_arm_design_pair(chart.p_u, multiple)
        lattice = triplet(chart.lattice_lower)
    else:
        p0, p1 = ref.upper_arm_design_pair(chart.p_l, multiple)
        lattice = triplet(chart.lattice_upper)
    assert lattice is not None
    n, k, _ = lattice

    assert ref.lattice_invariants_hold(n, k, p0, p1), (
        f"{arm} arm (N={n}, k={k}) violates Decision 7 at M={multiple}"
    )
    assert (n, k) == ref.exact_lattice(p0, p1)
    if n <= 200_000:
        assert ref.linear_lattice(p0, p1, max_n=n) == (n, k)


class TestLatticeFinderAtLargeMultiples:
    """C12.4 / Decision 18 item 25: the finder returns a lattice satisfying both
    Decision 7 invariants, equal to the ratified linear rule wherever the scan is
    feasible."""

    @pytest.mark.parametrize(
        ("m", "f", "multiple", "expected"),
        [(300_000, 0, 26_556.0, (14, 1)), (300_000, 1, 55.0, (2859, 1))],
        ids=["m300k_f0_M26556", "m300k_f1_M55"],
    )
    def test_pinned_regressions(
        self, m: int, f: int, multiple: float, expected: tuple[int, int]
    ) -> None:
        """C12.4's two cells, lower arm. Measured for this red phase against the
        shipped scan (``feat`` at ``5b7e3a1``): m=300,000 f=0 ``M = 26,556`` gives
        ``(N, k) = (11, 1)``, ``|r_q - r| = 0.0690`` against a tolerance of
        0.0510 (C12.4: "``r_q = 1/11`` against ``r ~ 0.022``"); m=300,000 f=1
        ``M = 55`` gives ``(2858, 1)``, ``|r_q - r| = 1.7515e-4`` against
        1.7504e-4. (The coordinator's brief quotes 0.000183 against 0.000181 for
        the second; the figures above are this session's re-measurement, and
        the violation reproduces either way.) The ratified rule gives (14, 1) and
        (2859, 1)."""
        chart = _fit(m, f, multiple, direction="lower")
        lattice = triplet(chart.lattice_lower)

        assert lattice is not None
        assert lattice[:2] == expected
        _assert_lattice_is_the_ratified_one(chart, "lower", multiple)

    @pytest.mark.slow
    # Budget: 60 draws x (a baseline of up to 300,000 observations, 0.08 s
    # measured, plus a target-1 fit and a bounded linear scan of <= 200,000
    # steps, ~0.3 s measured in the reference) = ~23 s locally; x3 = 70 s.
    @pytest.mark.timeout(300)
    @settings(
        max_examples=60,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    @given(
        m=st.integers(min_value=100, max_value=300_000),
        f_fraction=st.floats(min_value=0.0, max_value=1.0),
        arm=st.sampled_from(["lower", "upper"]),
        position=st.floats(min_value=0.0, max_value=1.0),
    )
    @example(m=300_000, f_fraction=0.0, arm="lower", position=0.9)
    @example(m=10_000, f_fraction=0.0001, arm="lower", position=0.8)
    @example(m=1_000, f_fraction=0.005, arm="upper", position=0.99)
    def test_finder_satisfies_decision_7_over_the_full_multiple_range(
        self, m: int, f_fraction: float, arm: str, position: float
    ) -> None:
        """Hypothesis over the **full** legal ``M`` range, both arms, f = 0 ...
        m - 1, m up to 300,000 -- deliberately not bounded to "realistic" values
        (C12.4: every earlier test used ``M <= 5``, which is how the defect
        survived; Decision 11 item 1's rule).

        ``M - 1`` is drawn log-uniformly from ``1e-6`` (inside the constructible
        region, C2) up to ``0.999 x (max_detect_rate_multiple - 1)`` (F11), so the
        draws reach the ``M ~ 36-26,556`` region where C12.4 measured the
        violations."""
        f = min(m - 1, int(f_fraction * m))
        assume(not (arm == "upper" and f == 0))
        p_u = ref.cp_upper(f, m)
        top = 0.999 * ((1.0 - 1e-9) / p_u - 1.0)
        assume(top > 1e-6)
        multiple = 1.0 + 10.0 ** (-6.0 + position * (math.log10(top) + 6.0))

        chart = _fit(m, f, multiple, direction=arm)

        _assert_lattice_is_the_ratified_one(chart, arm, multiple)


# ===========================================================================
# C14 -- the upper arm can be unconstructible at ordinary multiples
# ===========================================================================

# Found by domain-implementer's search at 3bd013d (test_bernoulli_cusum_
# defensive_paths.py) and confirmed by the independent reference: "upper" at
# m=3,000,000 f=1 is not constructible at this ordinary multiple.
_ORDINARY_UNCONSTRUCTIBLE_MULTIPLE = 4.195702165980544
# C14 item 29's population: baselines whose p_L < 1e-7 (p_L = 3.5e-8, 1.1e-8,
# 5.3e-8 respectively).
_TINY_P_L_BASELINES = ((3_000_000, 1), (10_000_000, 1), (10_000_000, 2))


@cache
def _baseline(m: int, f: int) -> Baseline:
    baseline, _ = binary_baseline(m, f)
    return baseline


@cache
def _refused_multiples_at_or_above_two(m: int, f: int) -> tuple[float, ...]:
    """C14's own sweep, via the independent reference: the multiples >= 2 on a
    3,000-point log grid of ``M - 1`` in ``[1e-6, 1e3]`` at which the upper arm
    is not constructible (m=3,000,000 f=1: 10 of them; m=10,000,000 f=1: 100+;
    f=2: 1)."""
    p_lower = ref.cp_lower(f, m)
    grid = (1.0 + 10.0 ** (-6.0 + 9.0 * i / 2999) for i in range(3000))
    return tuple(
        multiple
        for multiple in grid
        if multiple >= 2.0
        and ref.exact_lattice(*ref.upper_arm_design_pair(p_lower, multiple)) is None
    )


def _upper_f16(m: int, f: int, multiple: float) -> dict[str, object]:
    with pytest.raises(InvalidParameterError) as excinfo:
        fit_bernoulli_cusum(
            _baseline(m, f),
            target_arl=_CHEAP_TARGET,
            direction="upper",
            detect_rate_multiple=multiple,
        )
    return dict(excinfo.value.context)


def _assert_min_value_is_the_nearest_constructible(
    m: int, f: int, requested: float
) -> float:
    context = _upper_f16(m, f, requested)
    assert context["reason"] == _BELOW_RESOLUTION
    minimum = context["min_value"]
    assert isinstance(minimum, float)
    assert minimum >= requested
    chart = fit_bernoulli_cusum(
        _baseline(m, f),
        target_arl=_CHEAP_TARGET,
        direction="upper",
        detect_rate_multiple=minimum,
    )
    assert chart.detect_rate_multiple == minimum
    below = math.nextafter(minimum, 0.0)
    if below >= requested:
        assert _upper_f16(m, f, below)["reason"] == _BELOW_RESOLUTION
    return minimum


class TestUnconstructibleUpperArmAtOrdinaryMultiples:
    """Corrigendum C14 / Decision 18 items 28 and 29. The ``min_value`` search now
    runs upward from the request (C14's specification, replacing C12.1's fixed
    anchor at 2) -- already what 3bd013d does, so these pass today; they pin
    the ratified behaviour."""

    # Budget: a 3,000,000-observation baseline (~0.8 s, measured) and three
    # target-1 fits; ~1.5 s locally, x3 = 4.5 s.
    @pytest.mark.timeout(60)
    def test_pinned_regression_at_m_3_million(self) -> None:
        """Item 28: ``"upper"`` at m=3,000,000 f=1, ``M ~ 4.1957`` raises F16
        (``"shift_below_numerical_resolution"``); ``min_value`` is above the
        request, round-trips, and moves it by less than 1e-6 relative (C14
        measured 6.35e-8 at this baseline)."""
        p_lower = ref.cp_lower(1, 3_000_000)
        assert (
            ref.exact_lattice(
                *ref.upper_arm_design_pair(p_lower, _ORDINARY_UNCONSTRUCTIBLE_MULTIPLE)
            )
            is None
        ), "premise: the independent reference cannot realise it either"

        minimum = _assert_min_value_is_the_nearest_constructible(
            3_000_000, 1, _ORDINARY_UNCONSTRUCTIBLE_MULTIPLE
        )

        assert minimum > _ORDINARY_UNCONSTRUCTIBLE_MULTIPLE
        relative_move = (
            minimum - _ORDINARY_UNCONSTRUCTIBLE_MULTIPLE
        ) / _ORDINARY_UNCONSTRUCTIBLE_MULTIPLE
        assert relative_move < 1e-6

    # Budget: measured 0.6 s per target-1 fit on the 3,000,000-observation
    # baseline (its score scan dominates), three fits per draw: 3 draws ~6 s
    # locally (29.7 s for 5 draws in the full covered run), x3 = 18 s.
    @pytest.mark.timeout(90)
    @settings(
        max_examples=3,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(position=st.floats(min_value=0.0, max_value=1.0, exclude_max=True))
    def test_refused_multiples_above_two_at_m_3_million(self, position: float) -> None:
        """Item 29 on the cheapest qualifying baseline (m=3,000,000 f=1, p_L =
        3.5e-8): for a refused ``M >= 2``, ``min_value >= M``, is constructible,
        and the float below it is not."""
        refused = _refused_multiples_at_or_above_two(3_000_000, 1)
        assert refused
        requested = refused[int(position * len(refused))]

        _assert_min_value_is_the_nearest_constructible(3_000_000, 1, requested)

    @pytest.mark.slow
    # Budget: measured 2.0 s per target-1 fit at m=10,000,000 (0.6 s at
    # 3,000,000) plus ~2.7 s to build each 10M baseline once; 20 draws x 3
    # fits -> ~2 min locally, x3 = 6 min.
    @pytest.mark.timeout(600)
    @settings(
        max_examples=20,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        which=st.sampled_from(_TINY_P_L_BASELINES),
        position=st.floats(min_value=0.0, max_value=1.0, exclude_max=True),
    )
    def test_every_refused_multiple_above_two_gets_the_nearest_constructible_minimum(
        self, which: tuple[int, int], position: float
    ) -> None:
        """Item 29: for any refused ``M >= 2`` on a baseline with ``p_L < 1e-7``,
        ``min_value >= M``, is constructible, and the float below it is not."""
        m, f = which
        refused = _refused_multiples_at_or_above_two(m, f)
        assert refused, f"no refused multiple >= 2 at m={m} f={f}"
        requested = refused[int(position * len(refused))]

        _assert_min_value_is_the_nearest_constructible(m, f, requested)


# ===========================================================================
# C15.2 -- the multiple's ceiling covers the upper arm, and the search ends
# ===========================================================================

# The spacing of doubles just below 1: the upper design point 1 - p_L/M is
# representable strictly below 1 exactly when p_L / M >= 2**-53 (C15.2).
_TWO_TO_THE_53 = 2.0**53


class TestUpperArmCeiling:
    """Corrigendum C15.2 / Decision 18 item 34 at m=200 f=20 (``p_L ~ 0.0735``,
    so ``U = p_L x 2**53 ~ 6.6e14``)."""

    def test_upper_at_the_ceiling_fits(self) -> None:
        """``M = C = U`` is constructible (C15.2 measured it at every baseline).
        Passes today (the upper arm happens to be constructible there)."""
        p_lower = _fit(200, 20, 2.0, direction="upper").p_l
        ceiling = p_lower * _TWO_TO_THE_53

        chart = _fit(200, 20, ceiling, direction="upper")

        assert chart.detect_rate_multiple == ceiling

    @pytest.mark.parametrize("factor", [4.0, 1e3], ids=["4U", "1000U"])
    # Budget: one refusal; today it runs C14's upward search to float overflow
    # (~1,100 doublings, measured well under 1 s). 30 s bounds a hang.
    @pytest.mark.timeout(30)
    def test_above_the_ceiling_is_f11_with_a_round_tripping_maximum(
        self, factor: float
    ) -> None:
        """A request above ``C`` is F11, extended to the upper arm, with
        ``max_detect_rate_multiple = C`` (= ``U`` for ``"upper"``). Today: F16
        ``"no_valid_multiple"`` (the search's ceiling is ``math.inf``)."""
        p_lower = _fit(200, 20, 2.0, direction="upper").p_l
        ceiling = p_lower * _TWO_TO_THE_53

        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(200, 20, ceiling * factor, direction="upper")

        context = excinfo.value.context
        assert context["parameter"] == "detect_rate_multiple"
        assert context["kind"] == "invalid"
        assert context["provided"] == ceiling * factor
        assert "constraint" in context
        assert "reason" not in context
        assert context["max_detect_rate_multiple"] == ceiling
        maximum = context["max_detect_rate_multiple"]
        assert _fit(200, 20, maximum, direction="upper").detect_rate_multiple == (
            maximum
        )

    def test_two_sided_ceiling_is_the_smaller_of_the_two(self) -> None:
        """``C = min(F11's (1 - 1e-9)/p_U, U)``; for two-sided at m=200 f=20 F11's
        bound is the smaller. Passes today."""
        chart = _fit(200, 20, 2.0, direction="two_sided")
        f11 = (1.0 - 1e-9) / chart.p_u
        assert f11 < chart.p_l * _TWO_TO_THE_53

        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(200, 20, f11 * 2.0, direction="two_sided")

        assert excinfo.value.context["max_detect_rate_multiple"] == pytest.approx(
            f11, rel=1e-15
        )


class TestSearchEndsInNoValidMultiple:
    """Corrigendum C15.2 / Decision 18 item 34: driven by a monkeypatched
    always-refusing lattice finder (seam: ``bernoulli_cusum_fitting._arm_lattice``,
    the finder every designed arm goes through), the upward search ends in
    ``reason="no_valid_multiple"`` within a bounded number of probes. C15.2's
    bound: at most ~1,100 doublings and ~1,100 halvings."""

    _PROBE_BOUND = 2_500

    @pytest.mark.parametrize("direction", ["lower", "upper", "two_sided"])
    # Budget: <= 2,500 probes of a patched (constant-time) finder; well under
    # 1 s. 30 s bounds a hang.
    @pytest.mark.timeout(30)
    def test_no_constructible_multiple_is_reported_without_a_minimum(
        self, monkeypatch: pytest.MonkeyPatch, direction: str
    ) -> None:
        """Keys per C15.2: parameter, constraint, kind, provided, reason -- no
        ``min_value`` (mirrors F10). Passes today: the search already terminates
        (for ``"upper"`` only by overflowing to ``inf``, which C15.2 replaces
        with the ceiling ``U``)."""
        import drift_caliper.baseline.domain.bernoulli_cusum_fitting as fitting

        baseline, _ = binary_baseline(200, 20)
        probes: list[float] = []

        def refuse(p0: float, p1: float) -> None:
            probes.append(p1)

        monkeypatch.setattr(fitting, "_arm_lattice", refuse)

        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline,
                target_arl=_CHEAP_TARGET,
                detect_rate_multiple=1.5,
                direction=direction,
            )

        context = excinfo.value.context
        assert context["reason"] == "no_valid_multiple"
        assert context["parameter"] == "detect_rate_multiple"
        assert context["kind"] == "invalid"
        assert context["provided"] == 1.5
        assert "constraint" in context
        assert "min_value" not in context
        assert 0 < len(probes) <= self._PROBE_BOUND
