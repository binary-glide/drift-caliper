"""The two-sided chart's state space and its refusal (ADR-014 Decisions 8, 16 and C11).

Decision 18 items 4, 9 and 24 (item 12's budget, replaced by corrigendum
C11). Governing text: Amendment 1 Decision 8 (independent per-arm lattices;
joint state count ``(h_lo + 1)(h_up + 1)``), Amendment 2 Decision 16 (a
per-arm search-cap hit in two-sided mode is the joint-state refusal F13) and
corrigendum C11 (``max_two_sided_target_arl`` is the equal-split bound
``floor(T_ES)``, with a one-solve guard falling back to the exact D maximum).

**Seam for items 4 and 24.** Production solves ``(I - Q) x = 1`` through
``scipy.sparse.linalg.spsolve``, reached as ``bernoulli_cusum_fitting.spla``.
Item 4 spies on that call's matrix size; item 24's guard test scales the
result of the solves that are ``B`` (Decision 19.4's coupled chain, the only
chain with a transition of probability ``p_U - p_L``). If the implementation
changes solver, move the seam, not the assertions.

**Caps are monkeypatched, never driven for real** where a test is about the
refusal path rather than a published cell (Decision 18 item 12: "Tests must
not drive a zero-drift chain to a real cap: monkeypatch the cap"). When they
are patched, ``_MAX_DECISION_INTERVAL_UNITS`` is kept at
``_MAX_JOINT_STATES - 1``, the relationship Decision 13.3 fixes and Decision
16's proof relies on.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import pytest
import scipy.sparse.linalg
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from drift_caliper.baseline import FittedBernoulliCUSUM, fit_bernoulli_cusum
from drift_caliper.baseline.domain import bernoulli_cusum_fitting as fitting_module
from drift_caliper.errors import InvalidParameterError
from tests.support import bernoulli_reference as ref
from tests.support.bernoulli_surface import triplet
from tests.support.binary_baselines import binary_baseline
from tests.support.isolated_bernoulli_fit import fit_in_child

_JOINT = "joint_state_count_exceeded"
_SMALL_JOINT_CAP = 2_000


def _fit(
    m: int, f: int, target_arl: float, *, multiple: float | None = None
) -> FittedBernoulliCUSUM:
    baseline, _ = binary_baseline(m, f)
    return fit_bernoulli_cusum(
        baseline,
        target_arl=target_arl,
        direction="two_sided",
        detect_rate_multiple=multiple,
    )


def _refusal(
    m: int, f: int, target_arl: float, *, multiple: float | None = None
) -> dict[str, Any]:
    with pytest.raises(InvalidParameterError) as excinfo:
        _fit(m, f, target_arl, multiple=multiple)
    return dict(excinfo.value.context)


def _patch_caps(monkeypatch: pytest.MonkeyPatch, joint_cap: int) -> None:
    monkeypatch.setattr(fitting_module, "_MAX_JOINT_STATES", joint_cap)
    monkeypatch.setattr(fitting_module, "_MAX_DECISION_INTERVAL_UNITS", joint_cap - 1)
    monkeypatch.setattr(ref, "MAX_JOINT_STATES", joint_cap)
    monkeypatch.setattr(ref, "MAX_DECISION_INTERVAL_UNITS", joint_cap - 1)


def _es_design_states(target_arl: float, p_u: float, p_lower: float) -> int | None:
    """The equal-split design's joint state count at ``target_arl`` (C11), or
    ``None`` if an arm cannot reach ``2T`` within the per-arm cap."""
    nl, kl = _lattice(ref.lower_arm_design_pair(p_u, 2.0))
    nu, ku = _lattice(ref.upper_arm_design_pair(p_lower, 2.0))
    h_lo = ref.calibrate(nl, kl, p_u, 2.0 * target_arl)
    h_up = ref.calibrate(nu, ku, 1.0 - p_lower, 2.0 * target_arl)
    if h_lo is None or h_up is None:
        return None
    return (h_lo + 1) * (h_up + 1)


def _lattice(pair: tuple[float, float]) -> tuple[int, int]:
    lattice = ref.exact_lattice(*pair)
    assert lattice is not None
    return lattice


# ===========================================================================
# Decision 8 -- enforced by value, not by a timeout (item 4)
# ===========================================================================


class TestJointStateSpaceIsThePerArmProduct:
    """Decision 18 item 4: at coprime per-arm denominators, the joint solve has
    exactly ``(h_lo + 1)(h_up + 1)`` states. A shared (LCM) lattice -- mutation
    M2 -- would give 75,640 states here instead of 1,078, and is caught by this
    value, not by pytest-timeout.

    Cell: m=100 f=10 T=370 (independent reference: lower ``(4, 1, 13)``, upper
    ``(19, 18, 76)`` under calibration D, ``gcd(4, 19) = 1``; the equal-split
    upper interval is 78, so no solve may exceed ``14 x 79 = 1,106`` states).
    """

    # Budget: reference fit 0.02 s locally; x3 is negligible -- 60 s is a hang
    # guard, and the spy's value assertion fires long before it.
    @pytest.mark.timeout(60)
    def test_every_solve_is_within_the_per_arm_product(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        expected = ref.reference_fit(
            m=100, f=10, target_arl=370.0, direction="two_sided"
        )
        assert expected.lattice_lower is not None
        assert expected.lattice_upper is not None
        (nl, _, hl), (nu, ku, hu) = expected.lattice_lower, expected.lattice_upper
        assert math.gcd(nl, nu) == 1
        h_up_es = ref.calibrate(nu, ku, 1.0 - ref.cp_lower(10, 100), 740.0)
        assert h_up_es is not None
        ceiling = (hl + 1) * (h_up_es + 1)
        sizes: list[int] = []
        real_spsolve = scipy.sparse.linalg.spsolve

        def spsolve(matrix: Any, rhs: Any, *args: Any, **kwargs: Any) -> Any:
            size = int(matrix.shape[0])
            sizes.append(size)
            assert size <= ceiling, f"a {size}-state solve exceeds {ceiling}"
            return real_spsolve(matrix, rhs, *args, **kwargs)  # type: ignore[no-untyped-call]

        monkeypatch.setattr(scipy.sparse.linalg, "spsolve", spsolve)

        chart = _fit(100, 10, 370.0)

        lower, upper = triplet(chart.lattice_lower), triplet(chart.lattice_upper)
        assert lower is not None
        assert upper is not None
        assert math.gcd(lower[0], upper[0]) == 1
        assert (lower[2] + 1) * (upper[2] + 1) == (hl + 1) * (hu + 1)
        assert (lower[2] + 1) * (upper[2] + 1) in sizes


# ===========================================================================
# Decision 16 -- a per-arm cap hit in two-sided mode is F13, not F12 (item 9)
# ===========================================================================


class TestPerArmCapHitInTwoSidedModeIsTheJointRefusal:
    """Decision 16 / Decision 18 item 9, with Decision 13.3's cap relationship.

    Cell: m=1000 f=1, two-sided T=2,000, caps patched to 1,999 units / 2,000
    joint states. The upper arm (``reference_units = N - 1``, so ``h ~ 2T``)
    needs ~4,000 units for its per-arm target and hits the cap. The
    independent reference, under the same caps, refuses and gives
    ``floor(T_ES) = 128``, whose design fits in 354 states.
    """

    # Budget: reference 0.02 s for the refusal and round-trip together; 60 s
    # is a hang guard.
    @pytest.mark.timeout(60)
    def test_refuses_with_f13_and_a_round_tripping_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_caps(monkeypatch, _SMALL_JOINT_CAP)

        context = _refusal(1000, 1, 2_000.0)

        assert context["reason"] == _JOINT
        assert "max_attainable_arl" not in context
        bound = context["max_two_sided_target_arl"]
        chart = _fit(1000, 1, float(bound))
        assert chart.requested_arl == float(bound)
        assert bound == ref.es_bound(
            _lattice(ref.lower_arm_design_pair(chart.p_u, 2.0)),
            _lattice(ref.upper_arm_design_pair(chart.p_l, 2.0)),
            chart.p_u,
            chart.p_l,
        )


# ===========================================================================
# Corrigendum C11 -- max_two_sided_target_arl is floor(T_ES) (item 24)
# ===========================================================================


def _check_c11_cell(
    context: dict[str, Any],
    *,
    m: int,
    f: int,
    multiple: float,
    p_u: float,
    p_lower: float,
    pinned: int,
) -> int:
    assert context["reason"] == _JOINT
    bound = context["max_two_sided_target_arl"]
    assert bound == pinned
    assert bound == ref.es_bound(
        _lattice(ref.lower_arm_design_pair(p_u, multiple)),
        _lattice(ref.upper_arm_design_pair(p_lower, multiple)),
        p_u,
        p_lower,
    )
    es_states = _es_design_states(float(bound), p_u, p_lower)
    assert es_states is not None
    assert es_states <= ref.MAX_JOINT_STATES
    return int(bound)


class TestEqualSplitBound:
    """Corrigendum C11 / Decision 18 item 24.

    For each refusal cell in C11's table: the reported bound equals
    ``floor(T_ES)`` from the independent reference and C11's published value,
    it round-trips under D (production refits there) and under ES (the
    reference's equal-split design at that target fits the joint cap).
    """

    @pytest.mark.parametrize(
        ("m", "f", "pinned"),
        [(300_000, 1, 38_563), (300_000, 30, 3_914)],
        ids=["m300k_f1", "m300k_f30"],
    )
    # Budget: C11's measured end-to-end refusal 2.2 s / 3.3 s
    # (k3_refusal_time.py), plus a round-trip fit and two child start-ups
    # (~4 s): ~7.3 s at worst, x3 = 22 s. 300 s hard stop.
    @pytest.mark.timeout(300)
    def test_fast_refusal_cells(self, m: int, f: int, pinned: int) -> None:
        """Run in a child process: m=300,000 two-sided is the neighbourhood of
        Amendment 2 section 0's defect-2 segfault."""
        (refusal,) = fit_in_child(
            m=m, f=f, direction="two_sided", targets=[1e6], timeout=240.0
        )
        assert not refusal["ok"], refusal
        p_u, p_lower = ref.cp_upper(f, m), ref.cp_lower(f, m)
        bound = _check_c11_cell(
            refusal["context"],
            m=m,
            f=f,
            multiple=2.0,
            p_u=p_u,
            p_lower=p_lower,
            pinned=pinned,
        )

        (accepted,) = fit_in_child(
            m=m, f=f, direction="two_sided", targets=[float(bound)], timeout=240.0
        )
        assert accepted["ok"], accepted
        assert accepted["achieved_arl"] >= bound

    @pytest.mark.slow
    @pytest.mark.parametrize(
        ("m", "f", "multiple", "target", "pinned", "measured_seconds"),
        [
            (1000, 5, 2.0, 1e6, 21_634, 19.9),
            (200, 20, 1.001, 370.0, 249, 16.4),
            (1000, 1, 2.0, 1e6, 1_700, 44.3),
            (1000, 5, 1.01, 1e5, 1_471, 104.2),
        ],
        ids=["m1000_f5", "m200_f20_M1.001", "m1000_f1", "m1000_f5_M1.01"],
    )
    # Budget: C11's measured end-to-end refusal times (k3_refusal_time.py,
    # "total" column) are in ``measured_seconds``; the worst is 104.2 s, and
    # the round-trip fit at the bound is the D feasibility check again
    # (<= 95.5 s). (104.2 + 95.5) x 3 = 599 s.
    @pytest.mark.timeout(900)
    def test_slow_refusal_cells(
        self,
        m: int,
        f: int,
        multiple: float,
        target: float,
        pinned: int,
        measured_seconds: float,
    ) -> None:
        """These four are C11's expensive corners -- the cost is the fit's own
        per-solve cost near the 999,999-unit cap, which C11 leaves to the
        iterative-solver ticket and does not budget."""
        del measured_seconds  # recorded for the budget comment above
        context = _refusal(m, f, target, multiple=multiple)
        p_u, p_lower = ref.cp_upper(f, m), ref.cp_lower(f, m)
        bound = _check_c11_cell(
            context,
            m=m,
            f=f,
            multiple=multiple,
            p_u=p_u,
            p_lower=p_lower,
            pinned=pinned,
        )

        chart = _fit(m, f, float(bound), multiple=multiple)
        assert chart.achieved_arl >= bound

    # Budget: C11 measured 3.3 s end to end for this cell's refusal; the second
    # target repeats it: 6.6 s + ~2 s child start-up, x3 = 26 s. 300 s stop.
    @pytest.mark.timeout(300)
    def test_bound_does_not_depend_on_the_requested_target(self) -> None:
        """``T_ES`` is a property of the baseline, not of the request (C11's
        definition has no ``T`` in it), so two refused targets report one bound."""
        first, second = fit_in_child(
            m=300_000, f=30, direction="two_sided", targets=[1e6, 5e5], timeout=240.0
        )

        assert not first["ok"]
        assert not second["ok"]
        assert (
            first["context"]["max_two_sided_target_arl"]
            == second["context"]["max_two_sided_target_arl"]
        )

    # Budget: C11's measured refusal at this cell is 3.3 s end to end
    # (k3_refusal_time.py). C11's ratified overhead budget is <= 30 s *locally*
    # and is deliberately not enforced at 30 s here; the assertion is the
    # measured total x 4 (13.2 s -> 15 s), leaving CI's ~1.9x headroom.
    @pytest.mark.timeout(120)
    def test_refusal_completes_within_the_measured_budget(self) -> None:
        start = time.monotonic()
        (refusal,) = fit_in_child(
            m=300_000, f=30, direction="two_sided", targets=[1e6], timeout=110.0
        )
        elapsed = time.monotonic() - start

        assert not refusal["ok"]
        assert elapsed <= 15.0, f"the refusal took {elapsed:.1f} s"

    # Budget: patched caps keep every chain under 2,000 states; the reference
    # does the same work in 0.06 s. 120 s is a hang guard for the fallback's
    # exact-D bisection.
    @pytest.mark.timeout(120)
    def test_guard_falls_back_to_the_exact_d_maximum_when_b_misses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C11: "If the guard ever fails, the refusal falls back to the exact D
        maximum ... The report is never an unverified number." Exercised by
        scaling every ``B`` solve by 0.9 (a consistent, deflated ``B`` that the
        fit, the guard and the fallback all see), at m=200 f=20 T=10^5 under
        caps of 1,999 / 2,000. The reference's guard margin there is
        ``B_ES / T = 1.0068``, so after scaling the guard provably fails --
        checked below before production runs, so the test cannot pass without
        reaching the fallback."""
        _patch_caps(monkeypatch, _SMALL_JOINT_CAP)
        m, f, scale = 200, 20, 0.9
        p_u, p_lower = ref.cp_upper(f, m), ref.cp_lower(f, m)
        lower = _lattice(ref.lower_arm_design_pair(p_u, 2.0))
        upper = _lattice(ref.upper_arm_design_pair(p_lower, 2.0))
        es = ref.es_bound(lower, upper, p_u, p_lower)
        h_lo = ref.calibrate(*lower, p_u, 2.0 * es)
        h_up = ref.calibrate(*upper, 1.0 - p_lower, 2.0 * es)
        assert h_lo is not None
        assert h_up is not None
        guard_bound = ref.coupled_arl((*lower, h_lo), (*upper, h_up), p_lower, p_u)
        assert scale * guard_bound < es, "the scaled guard must fail"

        real_spsolve = scipy.sparse.linalg.spsolve
        middle = p_u - p_lower
        deflated: list[int] = []

        def spsolve(matrix: Any, rhs: Any, *args: Any, **kwargs: Any) -> Any:
            result = real_spsolve(matrix, rhs, *args, **kwargs)  # type: ignore[no-untyped-call]
            entries = np.abs(np.asarray(matrix.tocsc().data))
            if np.any(np.isclose(entries, middle, rtol=1e-9, atol=0.0)):
                deflated.append(int(matrix.shape[0]))
                return np.asarray(result) * scale
            return result

        monkeypatch.setattr(scipy.sparse.linalg, "spsolve", spsolve)

        context = _refusal(m, f, 1e5)

        assert context["reason"] == _JOINT
        bound = context["max_two_sided_target_arl"]
        chart = _fit(m, f, float(bound))
        assert chart.achieved_arl >= bound
        # Non-vacuity: the refusal and the refit really solved (and saw the
        # deflated) coupled chain B -- a path with no B cannot exercise a guard.
        assert deflated, "no coupled-bound (B) solve was observed"


class TestEqualSplitStateCountIsMonotone:
    """C11 derivation step 1, checked on the independent reference: the ES state
    count is non-decreasing in ``T`` (Hypothesis). Production's bound rests on
    this; the proof is by coupling, and this is its numerical witness."""

    # Budget: 30 draws x two ES designs at targets <= 1e4, reference <= 0.2 s
    # each locally -- ~12 s; x3 = 36 s.
    @pytest.mark.timeout(120)
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        m=st.integers(min_value=100, max_value=300_000),
        f_fraction=st.floats(min_value=0.0, max_value=0.3),
        low=st.floats(min_value=1.0, max_value=5_000.0),
        gap=st.floats(min_value=0.0, max_value=5_000.0),
    )
    def test_es_state_count_is_non_decreasing_in_target(
        self, m: int, f_fraction: float, low: float, gap: float
    ) -> None:
        f = max(1, int(f_fraction * m))
        p_u, p_lower = ref.cp_upper(f, m), ref.cp_lower(f, m)
        smaller = _es_design_states(low, p_u, p_lower)
        larger = _es_design_states(low + gap, p_u, p_lower)
        assert smaller is not None
        assert larger is not None
        assert smaller <= larger
