"""ADR-016: the joint two-sided state cap, and calibration D's solve count.

Governing text: ADR-016,
``docs/architecture/adr/016-bernoulli-cusum-joint-chain-solver-cost.md``.

- **Q1 (ruled option (b)).** The joint two-sided state cap falls from
  1,000,000 (ADR-014 Amendment 1 Decision 10b) to **400,000**, the largest cap
  with measured evidence of peaking under ~0.9 GB on every reachable coupled
  chain (Finding 0 on Linux). The one-sided decision-interval cap is
  **decoupled** from it and stays at **999,999** units: Decision 13.3's
  ``_MAX_JOINT_STATES - 1`` tie would otherwise refuse measured one-sided fits
  (ADR-016 cites 742,099 units at m=3,000,000; see the one-sided class).
- **Decision 2.** Calibration D's search for the smallest ``h_up`` with
  ``B >= T`` keeps its answer and needs fewer coupled solves: a proven lower
  bracket ``L - 1`` (``B <= A_up`` pathwise), a safeguarded regula falsi
  (Illinois), and no re-solve of ``B`` for ``achieved_arl``.

Verification items 1-3 and 5 are here; item 4 (no C11 regression) is the
refusal suite, re-based in ``test_bernoulli_cusum_two_sided_refusal.py``.
Decisions 1 and 3 change nothing (``TestTheSolverIsPinned`` already pins the
solver call), and memory is BIN-158's, so neither has a test here.

**Seam.** ``bernoulli_cusum_fitting._coupled_arl_in_units(lower, upper,
fail_both, fail_lower)`` is looked up at call time. ``B`` is the call with
``(fail_both, fail_lower) = (p_l, p_u)``; the two disclosure figures call it
with both rates equal. The oracle for the search is
``bernoulli_reference.calibration_d_searches``, a port of the ADR's own
prototype (``proto_d.py``), which returns both today's bisection and the
Illinois search with their distinct-solve counts.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from drift_caliper.baseline import FittedBernoulliCUSUM, fit_bernoulli_cusum
from drift_caliper.baseline.domain import bernoulli_arm_lattice
from drift_caliper.baseline.domain import bernoulli_cusum_fitting as fitting_module
from drift_caliper.errors import InvalidParameterError
from tests.support import bernoulli_reference as ref
from tests.support.bernoulli_surface import triplet
from tests.support.binary_baselines import binary_baseline
from tests.support.isolated_bernoulli_fit import fit_in_child

_JOINT = "joint_state_count_exceeded"

# ADR-016 Q1 (ruled 2026-09-27).
_JOINT_CAP = 400_000
_ONE_SIDED_CAP = 999_999


def _fit(
    m: int,
    f: int,
    target_arl: float,
    *,
    direction: str = "two_sided",
    multiple: float | None = None,
) -> FittedBernoulliCUSUM:
    baseline, _ = binary_baseline(m, f)
    return fit_bernoulli_cusum(
        baseline,
        target_arl=target_arl,
        direction=direction,
        detect_rate_multiple=multiple,
    )


def _lattice(pair: tuple[float, float]) -> tuple[int, int]:
    lattice = ref.exact_lattice(*pair)
    assert lattice is not None
    return lattice


def _search_inputs(
    m: int, f: int, multiple: float, target: float
) -> tuple[tuple[int, int, int], tuple[int, int], float, float, int]:
    """The reference's calibration-D inputs: ``(lower arm with h_lo, upper
    lattice, p_u, p_l, top)``, exactly as ``reference_fit`` derives them."""
    p_u, p_l = ref.cp_upper(f, m), ref.cp_lower(f, m)
    nl, kl = _lattice(ref.lower_arm_design_pair(p_u, multiple))
    nu, ku = _lattice(ref.upper_arm_design_pair(p_l, multiple))
    h_lo = ref.calibrate(nl, kl, p_u, 2.0 * target)
    assert h_lo is not None
    h_cap = ref.MAX_JOINT_STATES // (h_lo + 1) - 1
    h_up_es = ref.calibrate(nu, ku, 1.0 - p_l, 2.0 * target)
    top = h_cap if h_up_es is None else min(h_up_es, h_cap)
    return (nl, kl, h_lo), (nu, ku), p_u, p_l, top


class _CoupledSolveSpy:
    """Counts ``_coupled_arl_in_units`` calls that are ``B`` (unequal rates)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bound_calls: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        real = fitting_module._coupled_arl_in_units

        def spy(
            lower: tuple[int, int, int],
            upper: tuple[int, int, int],
            fail_both: float,
            fail_lower: float,
        ) -> float:
            if fail_both != fail_lower:
                self.bound_calls.append((tuple(lower), tuple(upper)))
            return real(lower, upper, fail_both, fail_lower)

        monkeypatch.setattr(fitting_module, "_coupled_arl_in_units", spy)


# ===========================================================================
# Q1 -- the joint cap is 400,000
# ===========================================================================


class TestTheJointStateCapIs400000:
    """ADR-016 Q1: refusals report ``max_joint_states = 400,000``, and a design
    between 400,000 and 1,000,000 joint states -- which fitted before -- is now
    refused with a bound that round-trips."""

    # Budget: measured locally only, with production's cap patched to 400,000
    # (``prodcost.py``): refusal 0.7 s + round-trip 0.1 s, plus two child
    # start-ups (~4 s). ~5 s x 1.9 (ADR-015's CI factor) x 3 = 29 s; the child
    # timeouts are sized generously for CI's heterogeneous runners.
    @pytest.mark.timeout(300)
    def test_refusal_reports_the_400000_state_cap(self) -> None:
        (refusal,) = fit_in_child(
            m=300_000, f=30, direction="two_sided", targets=[1e6], timeout=120.0
        )

        assert not refusal["ok"], refusal
        context = refusal["context"]
        assert context["reason"] == _JOINT
        assert context["max_joint_states"] == _JOINT_CAP
        assert context["joint_state_count"] > _JOINT_CAP

    @pytest.mark.slow
    # Budget: measured locally only (``prodcost.py``, cap patched to 400,000):
    # the m=1000 f=5 refusal 5.7 s and the round-trip fit at 4,759 16.5 s
    # under today's bisection, which Decision 2 only shortens: 22.2 s x 1.9 x
    # 3 = 127 s -> 300 s. Today (1M cap) the T=10,000 fit succeeds after
    # ~35 s, so the red run is bounded.
    @pytest.mark.timeout(300)
    def test_a_design_between_400000_and_1000000_states_is_refused(self) -> None:
        """m=1000 f=5 T=10,000: the independent reference fits it at the old cap
        (lattices (64, 1, 296) / (486, 485, 2121), 297 x 2,122 = 630,234
        states) and refuses it at 400,000."""
        m, f, target = 1000, 5, 10_000.0
        expected = ref.reference_fit(m=m, f=f, target_arl=target, direction="two_sided")
        assert expected.refusal == "F13"

        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(m, f, target)

        context = excinfo.value.context
        assert context["reason"] == _JOINT
        assert context["max_joint_states"] == _JOINT_CAP
        assert context["joint_state_count"] > _JOINT_CAP
        bound = context["max_two_sided_target_arl"]
        assert bound == 4_759  # ADR-016 Q1 table, m=1000 f=5 at 400,000
        assert _fit(m, f, float(bound)).achieved_arl >= bound


# ===========================================================================
# Q1 -- the one-sided cap is decoupled and stays at 999,999
# ===========================================================================


class TestTheOneSidedCapIsDecoupledFromTheJointCap:
    """ADR-016 Q1 option (b): "joint cap 400,000, one-sided cap unchanged at
    999,999". A one-sided fit needing more than 400,000 units must still fit.

    These pass today -- today both caps are ~10^6 -- and exist to fail an
    implementation that lowers the joint cap while keeping Decision 13.3's
    ``_MAX_JOINT_STATES - 1`` tie. ``test_bernoulli_cusum_amendment2.py``'s
    m=300,000 f=1 "upper" T=10^6 cell (857,041 units) guards the same thing.

    ADR-016 cites m=3,000,000 at T=10^6 needing 742,099 units. That figure is
    ADR-014 Amendment 2 section 1's f=0 *upper* arm, measured before Decision
    19 made an f=0 upper arm undesignable (F15); today m=3,000,000 f=0 "lower"
    at T=10^6 fits at ``h = 1``. It is not reproducible, so it is not pinned.
    """

    # Budget: reads three module attributes; no solve. 10 s is a hang guard.
    @pytest.mark.timeout(10)
    def test_the_caps_hold_their_ruled_values_independently(self) -> None:
        """ADR-016 Q1 (b): "joint cap 400,000, one-sided cap unchanged at
        999,999". Each cap is pinned to its own ruled value, so an import-time
        re-tie (``_MAX_DECISION_INTERVAL_UNITS = _MAX_JOINT_STATES - 1``) fails
        here on the pull-request gate. The patching test below cannot see such a
        tie -- it patches after import -- and the behavioural 460,645-unit fit
        is ``slow``. The fitting module's search cap must also be the lattice
        value object's own cap, or a fit could calibrate an interval the
        artefact then refuses to hold."""
        assert fitting_module._MAX_JOINT_STATES == _JOINT_CAP
        assert fitting_module._MAX_DECISION_INTERVAL_UNITS == _ONE_SIDED_CAP
        assert bernoulli_arm_lattice.MAX_DECISION_INTERVAL_UNITS == _ONE_SIDED_CAP

    # Budget: patched caps keep every chain under ~4,000 states; well under
    # 1 s locally. 60 s is a hang guard.
    @pytest.mark.timeout(60)
    def test_shrinking_the_joint_cap_does_not_shrink_a_one_sided_fit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the joint cap is patched (to 2,000). An upper fit at m=1000 f=1
        T=4,000 needs more than 2,000 units and still fits, matching the
        reference under the unpatched one-sided cap; a two-sided fit at the
        same baseline is refused against the patched joint cap."""
        monkeypatch.setattr(fitting_module, "_MAX_JOINT_STATES", 2_000)
        monkeypatch.setattr(ref, "MAX_JOINT_STATES", 2_000)
        expected = ref.reference_fit(m=1000, f=1, target_arl=4_000.0, direction="upper")
        assert expected.lattice_upper is not None
        assert expected.lattice_upper[2] > 2_000  # non-vacuity: beyond the joint cap

        chart = _fit(1000, 1, 4_000.0, direction="upper")

        assert triplet(chart.lattice_upper) == expected.lattice_upper
        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(1000, 1, 4_000.0)
        assert excinfo.value.context["reason"] == _JOINT
        assert excinfo.value.context["max_joint_states"] == 2_000

    @pytest.mark.slow
    # Budget: measured locally only -- the reference's own fit is 2.2 s (a
    # 460,645-unit one-sided chain calibrated by bisection); production's is of
    # the same order, plus a 300,000-observation baseline and a child start-up
    # (~3 s): ~5 s x 1.9 x 3 = 29 s. The child gets 240 s, generously.
    @pytest.mark.timeout(300)
    def test_upper_fit_needing_more_than_400000_units_fits(self) -> None:
        """m=300,000 f=1 "upper" T=500,000: the reference calibrates
        ``h = 460,645`` units, above the joint cap and below 999,999."""
        m, f, target = 300_000, 1, 500_000.0
        expected = ref.reference_fit(m=m, f=f, target_arl=target, direction="upper")
        assert expected.lattice_upper is not None
        assert _JOINT_CAP < expected.lattice_upper[2] <= _ONE_SIDED_CAP

        (outcome,) = fit_in_child(
            m=m, f=f, direction="upper", targets=[target], timeout=240.0
        )

        assert outcome["ok"], outcome
        assert tuple(outcome["lattice_upper"]) == expected.lattice_upper


# ===========================================================================
# Q1 / Verification 5 -- max_two_sided_target_arl at the 400,000 cap
# ===========================================================================

# ADR-016 Q1's table, column 400,000 (``capcost.py``), each value reproduced
# by the independent reference's ``es_bound`` under ``MAX_JOINT_STATES =
# 400,000``. Measured locally with production's cap patched to 400,000
# (``prodcost.py``, today's bisection, so an upper bound on Decision 2's
# cost): refusal seconds / round-trip seconds.
_CHANGED_CELLS = [
    pytest.param(1000, 1, 808, 7.0, 23.5, id="m1000_f1"),
    pytest.param(1000, 5, 4_759, 5.7, 16.5, id="m1000_f5"),
    pytest.param(1000, 10, 28_134, 8.3, 40.8, id="m1000_f10"),
    pytest.param(300, 3, 25_526, 12.0, 80.9, id="m300_f3"),
]


class TestMaxTwoSidedTargetArlAtTheJointCap:
    """Verification 5: "pin the new ``max_two_sided_target_arl`` table in the
    tests from the independent reference". Each refused bound equals the ADR's
    figure and the reference's ``floor(T_ES)``, and round-trips.

    The table's unchanged cells: m=300,000 f=1 (38,563) is pinned by
    ``test_bernoulli_cusum_amendment2.py`` and the refusal suite; m=10,000 f=1
    (1,285) and m=200 f=20 (fits at 10^6) are pinned below. They pass today
    because the cap never binds their bound.
    """

    @pytest.mark.slow
    @pytest.mark.parametrize(
        ("m", "f", "pinned", "refusal_seconds", "fit_seconds"), _CHANGED_CELLS
    )
    # Budget: measured locally only (see ``_CHANGED_CELLS``); the worst cell is
    # m=300 f=3 at 12.0 s + 80.9 s. Refusal child: 12.0 x 1.9 x 3 = 68 s ->
    # 180 s. Fit child: 80.9 x 1.9 x 3 = 461 s -> 480 s. Hard stop 720 s.
    # Today the refusal at the 1M cap computes the old bound (m=300 f=3: 931 s
    # measured) -- the refusal child's timeout is what bounds the red run.
    @pytest.mark.timeout(720)
    def test_changed_cells_report_the_adr_bound_and_round_trip(
        self,
        m: int,
        f: int,
        pinned: int,
        refusal_seconds: float,
        fit_seconds: float,
    ) -> None:
        del refusal_seconds, fit_seconds  # recorded for the budget comment
        p_u, p_l = ref.cp_upper(f, m), ref.cp_lower(f, m)
        assert pinned == ref.es_bound(
            _lattice(ref.lower_arm_design_pair(p_u, 2.0)),
            _lattice(ref.upper_arm_design_pair(p_l, 2.0)),
            p_u,
            p_l,
        )

        (refusal,) = fit_in_child(
            m=m, f=f, direction="two_sided", targets=[1e6], timeout=180.0
        )

        assert not refusal["ok"], refusal
        context = refusal["context"]
        assert context["reason"] == _JOINT
        assert context["max_joint_states"] == _JOINT_CAP
        assert context["max_two_sided_target_arl"] == pinned

        (accepted,) = fit_in_child(
            m=m, f=f, direction="two_sided", targets=[float(pinned)], timeout=480.0
        )
        assert accepted["ok"], accepted
        assert accepted["achieved_arl"] >= pinned

    # Budget: measured locally only (cap patched to 400,000): refusal 1.3 s,
    # round-trip < 0.1 s, plus two child start-ups (~4 s): ~5.4 s x 1.9 x 3 =
    # 31 s. Children get 120 s each.
    @pytest.mark.timeout(300)
    def test_m10000_f1_is_unchanged_at_1285(self) -> None:
        p_u, p_l = ref.cp_upper(1, 10_000), ref.cp_lower(1, 10_000)
        assert 1_285 == ref.es_bound(
            _lattice(ref.lower_arm_design_pair(p_u, 2.0)),
            _lattice(ref.upper_arm_design_pair(p_l, 2.0)),
            p_u,
            p_l,
        )

        (refusal,) = fit_in_child(
            m=10_000, f=1, direction="two_sided", targets=[1e6], timeout=120.0
        )
        assert not refusal["ok"], refusal
        assert refusal["context"]["max_two_sided_target_arl"] == 1_285

        (accepted,) = fit_in_child(
            m=10_000, f=1, direction="two_sided", targets=[1_285.0], timeout=120.0
        )
        assert accepted["ok"], accepted
        assert accepted["achieved_arl"] >= 1_285

    @pytest.mark.slow
    # Budget: measured locally only (cap patched to 400,000): the fit at 10^6
    # took 6.5 s; the reference's fit is of the same order. ~13 s x 1.9 x 3 =
    # 74 s -> 240 s.
    @pytest.mark.timeout(240)
    def test_m200_f20_still_fits_at_the_ceiling(self) -> None:
        """ADR-016 Q1's table: m=200 f=20 is "—" (fits at 10^6) at every cap."""
        expected = ref.reference_fit(m=200, f=20, target_arl=1e6, direction="two_sided")
        assert expected.refusal is None

        chart = _fit(200, 20, 1e6)

        assert triplet(chart.lattice_lower) == expected.lattice_lower
        assert triplet(chart.lattice_upper) == expected.lattice_upper


# ===========================================================================
# Decision 2 / Verification 2 -- fewer coupled solves, and no re-solve of B
# ===========================================================================

# Cells from ADR-016 Finding 2's table, with the Illinois search's distinct
# ``B`` solves computed at test time by the reference port.
_SMALL_CELLS = [
    pytest.param(200, 20, 370.0, id="m200_f20_T370"),
    pytest.param(300, 3, 370.0, id="m300_f3_T370"),
    pytest.param(1000, 1, 370.0, id="m1000_f1_T370"),
    pytest.param(1000, 5, 370.0, id="m1000_f5_T370"),
]


class TestCalibrationDSolvesFewerCoupledChains:
    """Verification 2: "A spy on ``_coupled_arl_in_units`` asserts the near-cap
    cell's coupled-solve count is at most the measured figure, and that
    ``_two_sided_design`` performs no coupled solve at ``(h_lo, h_up)`` beyond
    the one the search made."

    The upper bound is the ADR prototype's count (its port,
    ``ref.calibration_d_searches``), which includes ``B(top)`` and its solve
    of ``B(L - 1)``; an implementation that skips the latter (it is known to
    be below ``T``) comes in under it. Today's bisection makes the bisection
    count plus one re-solve at the answer.
    """

    @pytest.mark.parametrize(("m", "f", "target"), _SMALL_CELLS)
    # Budget: every chain here is <= 109,089 states; the reference's two
    # searches together take <= 1.5 s locally and the fit a little less.
    # ~3 s x 1.9 x 3 = 17 s -> 120 s.
    @pytest.mark.timeout(120)
    def test_small_cells_solve_no_more_than_the_illinois_search(
        self, monkeypatch: pytest.MonkeyPatch, m: int, f: int, target: float
    ) -> None:
        lower, upper, p_u, p_l, top = _search_inputs(m, f, 2.0, target)
        (bisect_h, bisect_solves), (illinois_h, illinois_solves) = (
            ref.calibration_d_searches(lower, upper, p_u, p_l, target, top)
        )
        assert bisect_h == illinois_h
        assert illinois_solves < bisect_solves + 1  # non-vacuity: today is above
        spy = _CoupledSolveSpy(monkeypatch)

        chart = _fit(m, f, target)

        assert triplet(chart.lattice_upper) == (*upper, illinois_h)
        assert len(spy.bound_calls) <= illinois_solves, spy.bound_calls
        assert len(set(spy.bound_calls)) == len(spy.bound_calls), (
            "B was solved twice at one design"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize(
        ("m", "f", "target", "h_lo", "h_up", "max_solves"),
        [
            pytest.param(1000, 5, 4_759.0, 250, 1_543, 5, id="m1000_f5_T4759"),
            pytest.param(1000, 1, 808.0, 266, 1_053, 7, id="m1000_f1_T808"),
        ],
    )
    # Budget: measured locally only, cap patched to 400,000 (``prodcost.py``):
    # the round-trip fits took 16.5 s / 23.5 s under today's bisection (12 / 13
    # B solves); Decision 2 needs <= 5 / 7. 23.5 x 1.9 x 3 = 134 s -> 300 s.
    @pytest.mark.timeout(300)
    def test_near_cap_cells_solve_no_more_than_the_measured_count(
        self,
        monkeypatch: pytest.MonkeyPatch,
        m: int,
        f: int,
        target: float,
        h_lo: int,
        h_up: int,
        max_solves: int,
    ) -> None:
        """ADR-016 Finding 2 measured 12 -> 4 and 13 -> 7 at the old cap, on its
        old near-cap targets (21,634 and 1,700). At the 400,000 cap the near-cap
        targets are the new bounds, and the reference port gives: m=1000 f=5
        bisection 11 -> Illinois 5; m=1000 f=1 12 -> 7; both answers identical,
        ``(250, 1543)`` and ``(266, 1053)``, as production (cap patched)
        reproduces. Pinned as literals: recomputing them costs ~35 s here."""
        spy = _CoupledSolveSpy(monkeypatch)

        chart = _fit(m, f, target)

        lower, upper = triplet(chart.lattice_lower), triplet(chart.lattice_upper)
        assert lower is not None
        assert upper is not None
        assert (lower[2], upper[2]) == (h_lo, h_up)
        assert len(spy.bound_calls) <= max_solves, len(spy.bound_calls)
        assert spy.bound_calls.count((lower, upper)) == 1

    # Budget: m=200 f=20 T=370 solves chains of <= 1,380 states; < 0.1 s.
    @pytest.mark.timeout(60)
    def test_achieved_arl_is_the_searchs_own_solve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decision 2 fact 2: "The answer's B is always already computed by the
        search, so ``_two_sided_design``'s re-solve of ``achieved_arl`` is
        redundant". Exactly one ``B`` solve at the final design, and the reported
        ``achieved_arl`` is that solve's value."""
        spy = _CoupledSolveSpy(monkeypatch)

        chart = _fit(200, 20, 370.0)

        lower, upper = triplet(chart.lattice_lower), triplet(chart.lattice_upper)
        assert lower is not None
        assert upper is not None
        assert spy.bound_calls.count((lower, upper)) == 1
        expected = ref.coupled_arl(lower, upper, chart.p_l, chart.p_u)
        assert chart.achieved_arl == pytest.approx(expected, rel=1e-9)


# ===========================================================================
# Decision 2 / Verification 1 -- the design is identical to today's
# ===========================================================================


class TestCalibrationDReturnsTodaysDesign:
    """Verification 1: "the new calibration D returns the same ``(h_lo, h_up)``
    as today's ... Hypothesis over the legal space at small state counts".
    The oracle is ``ref.reference_fit``, whose calibration D is today's
    bisection. These pass today by construction -- production *is* the
    bisection -- and guard the equivalence that makes Decision 2 a pure
    performance change."""

    # Budget: draws are filtered to equal-split designs of <= 20,000 states
    # (a coupled solve of that size is ~10 ms), so each example is a handful
    # of small solves on both sides: < 0.5 s. 40 examples x 0.5 s = 20 s
    # locally; x 1.9 x 3 = 114 s -> 240 s.
    @pytest.mark.timeout(240)
    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    @given(
        m=st.integers(min_value=100, max_value=2_000),
        f_fraction=st.floats(min_value=0.005, max_value=0.3),
        multiple=st.sampled_from([1.1, 1.5, 2.0, 3.0]),
        target=st.floats(min_value=2.0, max_value=2_000.0),
    )
    def test_design_matches_the_bisection_over_the_legal_space(
        self, m: int, f_fraction: float, multiple: float, target: float
    ) -> None:
        f = max(1, int(f_fraction * m))
        p_u, p_l = ref.cp_upper(f, m), ref.cp_lower(f, m)
        lower = ref.exact_lattice(*ref.lower_arm_design_pair(p_u, multiple))
        upper = ref.exact_lattice(*ref.upper_arm_design_pair(p_l, multiple))
        assume(lower is not None and upper is not None)
        assert lower is not None
        assert upper is not None
        h_lo = ref.calibrate(*lower, p_u, 2.0 * target)
        h_up = ref.calibrate(*upper, 1.0 - p_l, 2.0 * target)
        assume(h_lo is not None and h_up is not None)
        assert h_lo is not None
        assert h_up is not None
        assume((h_lo + 1) * (h_up + 1) <= 20_000)

        expected = ref.reference_fit(
            m=m, f=f, target_arl=target, direction="two_sided", multiple=multiple
        )
        assert expected.refusal is None  # the ES design fits, so D does
        chart = _fit(m, f, target, multiple=multiple)

        assert triplet(chart.lattice_lower) == expected.lattice_lower
        assert triplet(chart.lattice_upper) == expected.lattice_upper

    @pytest.mark.slow
    @pytest.mark.parametrize("target", [10.0, 370.0, 1e4], ids=["T10", "T370", "T1e4"])
    @pytest.mark.parametrize("multiple", [1.1, 2.0, 3.0], ids=["M1.1", "M2", "M3"])
    @pytest.mark.parametrize("f_key", ["1", "2", "5", "m/10"])
    @pytest.mark.parametrize("m", [100, 200, 300])
    # Budget: measured locally only -- the slowest cell took 36.7 s end to end
    # (reference + production) under ``-n 4``; the reference alone is <= 16.5 s
    # on every included cell (``sweep.py``). 36.7 x 1.9 x 3 = 209 s -> 300 s.
    @pytest.mark.timeout(300)
    def test_design_matches_the_bisection_across_the_adr_sweep(
        self, m: int, f_key: str, multiple: float, target: float
    ) -> None:
        """Finding 2's sweep: m in {100, 200, 300}, f in {1, 2, 5, m/10}, M in
        {1.1, 2, 3}, T in {10, 370, 10^4}, equal-split design <= 300,000 states
        -- 93 cells, of which the ADR ran 25.

        Three of the 93 are skipped for cost, and the skip says so: M = 1.1,
        T = 10^4, f = m/10 at m = 100, 200, 300. Their coupled chains are the
        stretched shapes of Finding 0; the reference alone took 196 s, 633 s
        and 424 s on them (``sweep.py``), against <= 16.5 s for every other
        cell. The Hypothesis property above covers their region at small
        state counts."""
        f = m // 10 if f_key == "m/10" else int(f_key)
        p_u, p_l = ref.cp_upper(f, m), ref.cp_lower(f, m)
        lower = _lattice(ref.lower_arm_design_pair(p_u, multiple))
        upper = _lattice(ref.upper_arm_design_pair(p_l, multiple))
        h_lo = ref.calibrate(*lower, p_u, 2.0 * target)
        h_up = ref.calibrate(*upper, 1.0 - p_l, 2.0 * target)
        if h_lo is None or h_up is None or (h_lo + 1) * (h_up + 1) > 300_000:
            pytest.skip("outside Finding 2's sweep: ES design > 300,000 states")
        if multiple == 1.1 and target == 1e4 and f_key == "m/10":
            pytest.skip("stretched coupled chain: 196-633 s in the reference alone")

        expected = ref.reference_fit(
            m=m, f=f, target_arl=target, direction="two_sided", multiple=multiple
        )
        chart = _fit(m, f, target, multiple=multiple)

        assert triplet(chart.lattice_lower) == expected.lattice_lower
        assert triplet(chart.lattice_upper) == expected.lattice_upper


# ===========================================================================
# Decision 2 / Verification 3 -- the bracket invariant
# ===========================================================================

_Shape = Callable[[int, int, float], float]


def _flat(h: int, jump: int, target: float) -> float:
    return target / 2.0 if h < jump else 2.0 * target


def _near_miss(h: int, jump: int, target: float) -> float:
    """Just below ``T`` before the jump, exactly ``T`` from it (``>=`` counts)."""
    return math.nextafter(target, 0.0) if h < jump else target


def _misleading_ramp(h: int, jump: int, target: float) -> float:
    """A steep linear ramp that an interpolation extrapolates to the wrong
    place: far below ``T`` until the jump, then enormous."""
    return 1.0 + (target - 2.0) * h / (jump + 1) if h < jump else 1e9 * target


_SHAPES = {"flat": _flat, "near_miss": _near_miss, "misleading_ramp": _misleading_ramp}


class TestCalibrationDBracketInvariant:
    """Verification 3: "Monkeypatch ``B`` to adversarial monotone step functions
    (a jump at ``L``, at ``top``, and one unit above ``L``); the search must
    still return the smallest ``h`` with ``B >= T``."

    ``L`` is the smallest ``h`` whose one-sided upper-arm ARL at ``1 - p_L``
    meets ``T`` -- a proven lower bound, so every jump here is at or above it,
    as a real ``B`` must be. The disclosure figures (equal rates) pass through
    to the real chain. These pass today: bisection keeps the invariant too.

    Cell: m=200 f=20 T=370 (reference: ``L`` well below ``top``, so all three
    jumps are distinct -- asserted).
    """

    @pytest.mark.parametrize("shape", sorted(_SHAPES))
    @pytest.mark.parametrize("where", ["L", "L_plus_1", "top"])
    # Budget: every real solve here is <= 1,380 states; < 0.1 s. 60 s hang guard.
    @pytest.mark.timeout(60)
    def test_search_returns_the_smallest_interval_meeting_the_target(
        self, monkeypatch: pytest.MonkeyPatch, shape: str, where: str
    ) -> None:
        m, f, target = 200, 20, 370.0
        lower, upper, _, p_l, top = _search_inputs(m, f, 2.0, target)
        smallest = ref.calibrate(*upper, 1.0 - p_l, target)
        assert smallest is not None
        assert smallest + 1 < top  # three distinct jumps
        jump = {"L": smallest, "L_plus_1": smallest + 1, "top": top}[where]
        step = _SHAPES[shape]
        real = fitting_module._coupled_arl_in_units
        probed: list[int] = []

        def fake(
            lower_arm: tuple[int, int, int],
            upper_arm: tuple[int, int, int],
            fail_both: float,
            fail_lower: float,
        ) -> float:
            if fail_both == fail_lower:
                return real(lower_arm, upper_arm, fail_both, fail_lower)
            probed.append(upper_arm[2])
            return step(upper_arm[2], jump, target)

        monkeypatch.setattr(fitting_module, "_coupled_arl_in_units", fake)

        chart = _fit(m, f, target)

        lower_triplet, upper_triplet = (
            triplet(chart.lattice_lower),
            triplet(chart.lattice_upper),
        )
        assert lower_triplet == lower
        assert upper_triplet == (*upper, jump)
        assert jump in probed  # the answer was solved, not assumed
        assert chart.achieved_arl == step(jump, jump, target)
