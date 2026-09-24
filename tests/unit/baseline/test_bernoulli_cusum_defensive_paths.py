"""Reachable edge paths in ``fit_bernoulli_cusum`` that the Decision 18 cells miss.

Each test drives one branch of the ADR-014 Amendment 2 implementation that is
reachable through the public API but that none of the verification-bar cells
happens to reach. They exist so that no reachable line is left to a
``# pragma: no cover`` (and so Codecov's patch check sees them), and each
asserts the ratified behaviour on that path, not merely that it runs.

- **The lattice finder at the edge of double precision** (corrigendum C12.4).
  At m=3,000,000 f=1 the upper arm's ``1 - p_l`` sits within ~4e-8 of 1, so
  Decision 7's floating-point test can disagree with exact arithmetic by a
  rounding. Found while implementing, by a 60,000-draw search over the legal
  space with the production finder: the finder's forward walk from ``N_any``
  was needed 7 times, all at m=3,000,000 ``"upper"``, and the walk exhausted
  (no ``N`` up to ``N_sym`` passes in floating point) 7 times, at ordinary
  multiples such as M ~ 4.1957 -- **outside** corrigendum C12.1's measured
  band (``M - 1 < 5.41e-8``), whose sweep stopped at m=300,000. The
  independent reference (``tests.support.bernoulli_reference.exact_lattice``)
  agrees on every one of these cells.
- **The two-sided refusal's cap branches** (Decision 16, row F13): a lower arm
  that needs more than the per-arm cap, and one whose interval alone leaves no
  room under the joint cap for any upper interval. Caps are patched, never
  driven for real (Decision 18 item 12).
- **A solver that raises** is ill-conditioned, and must surface as row F14,
  never as the solver's own exception.
- **``audit_summary()`` of a one-sided chart** names the unchecked arm.
"""

from __future__ import annotations

from typing import Any

import pytest
import scipy.sparse.linalg

from drift_caliper.baseline import FittedBernoulliCUSUM, fit_bernoulli_cusum
from drift_caliper.baseline.domain import bernoulli_cusum_fitting as fitting_module
from drift_caliper.errors import DegenerateBaselineError, InvalidParameterError
from tests.support import bernoulli_reference as ref
from tests.support.bernoulli_surface import triplet
from tests.support.binary_baselines import binary_baseline

_SMALL_JOINT_CAP = 2_000
# Found by the search described in the module docstring (m=3,000,000 f=1,
# "upper"): the finder must walk one step past N_any.
_WALKING_MULTIPLE = 837.624532957969
# Same search: no N up to N_sym passes Decision 7 in floating point.
_UNREALISABLE_MULTIPLE = 4.195702165980544


def _patch_caps(monkeypatch: pytest.MonkeyPatch, joint_cap: int) -> None:
    monkeypatch.setattr(fitting_module, "_MAX_JOINT_STATES", joint_cap)
    monkeypatch.setattr(fitting_module, "_MAX_DECISION_INTERVAL_UNITS", joint_cap - 1)


def _fit(
    m: int,
    f: int,
    *,
    target_arl: float,
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


class TestLatticeFinderAtTheEdgeOfDoublePrecision:
    """Corrigendum C12.4's finder, on cells where floating point bites."""

    # Budget: a 3,000,000-observation baseline builds in ~0.8 s and the fit is
    # at target 1.0 (h_units = 1); ~1 s locally, x3 = 3 s.
    @pytest.mark.timeout(60)
    def test_the_forward_walk_finds_the_ratified_lattice(self) -> None:
        chart = _fit(
            3_000_000,
            1,
            target_arl=1.0,
            direction="upper",
            multiple=_WALKING_MULTIPLE,
        )
        p0, p1 = ref.upper_arm_design_pair(chart.p_l, _WALKING_MULTIPLE)
        lattice = triplet(chart.lattice_upper)

        assert lattice is not None
        assert lattice[:2] == ref.exact_lattice(p0, p1)
        assert ref.lattice_invariants_hold(lattice[0], lattice[1], p0, p1)

    # Budget: the refusal's search is ~60 probes of the O(log N) finder, and
    # the round-trip fit is at target 1.0 -- ~1.5 s locally with the baseline.
    @pytest.mark.timeout(60)
    def test_an_unrealisable_design_at_an_ordinary_multiple_is_f16_with_a_minimum(
        self,
    ) -> None:
        """F16 fires when the designed arm is not constructible at the multiple
        passed (C12.1), and ``min_value`` is the nearest constructible multiple
        at or above it -- here *above* 2, where C12.1's fixed anchor could not
        have bracketed it."""
        baseline, _ = binary_baseline(3_000_000, 1)
        p_l = fit_bernoulli_cusum(baseline, target_arl=1.0, direction="upper").p_l
        assert (
            ref.exact_lattice(*ref.upper_arm_design_pair(p_l, _UNREALISABLE_MULTIPLE))
            is None
        ), "premise: the independent finder cannot realise this design either"

        with pytest.raises(InvalidParameterError) as excinfo:
            fit_bernoulli_cusum(
                baseline,
                target_arl=1.0,
                direction="upper",
                detect_rate_multiple=_UNREALISABLE_MULTIPLE,
            )

        context = excinfo.value.context
        assert context["reason"] == "shift_below_numerical_resolution"
        assert context["min_inclusive"] is True
        minimum = context["min_value"]
        assert minimum > _UNREALISABLE_MULTIPLE
        chart = fit_bernoulli_cusum(
            baseline, target_arl=1.0, direction="upper", detect_rate_multiple=minimum
        )
        assert chart.detect_rate_multiple == minimum


class TestTwoSidedCapBranches:
    """Decision 16 / row F13, with Decision 13.3's cap relationship patched small."""

    # Budget: every chain is under 2,000 states; ~0.3 s locally.
    @pytest.mark.timeout(60)
    def test_a_lower_arm_past_its_own_cap_is_the_joint_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """m=300,000 f=1: the lower arm is floored at 1/p_U ~ 77,127, so a
        per-arm target of 2 x 10^5 needs h_units >= N - r_units = 45,564, far
        past a 1,999-unit cap. That is over the joint cap whatever the upper arm
        is (Decision 16's proof), so it is F13, not F12, and its reported
        ``joint_state_count`` is a lower bound still over the cap."""
        _patch_caps(monkeypatch, _SMALL_JOINT_CAP)

        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(300_000, 1, target_arl=1e5)

        context = excinfo.value.context
        assert context["reason"] == "joint_state_count_exceeded"
        assert "max_attainable_arl" not in context
        assert context["joint_state_count"] > context["max_joint_states"]
        bound = context["max_two_sided_target_arl"]
        assert _fit(300_000, 1, target_arl=float(bound)).requested_arl == bound

    @pytest.mark.timeout(60)
    def test_a_lower_arm_leaving_no_room_for_an_upper_interval_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """m=10,000 f=1: a per-arm target of 4,000 is above the lower arm's
        floor (1/p_U ~ 2,571), so it needs h_units = N - r_units = 1,518 (N =
        1,519). Then (h_lo + 1) x 2 > 2,000: no upper interval of even one unit
        fits the joint cap."""
        _patch_caps(monkeypatch, _SMALL_JOINT_CAP)

        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(10_000, 1, target_arl=2_000.0)

        context = excinfo.value.context
        assert context["reason"] == "joint_state_count_exceeded"
        assert context["joint_state_count"] > context["max_joint_states"]
        bound = context["max_two_sided_target_arl"]
        assert _fit(10_000, 1, target_arl=float(bound)).requested_arl == bound


class TestASolverThatRaisesIsIllConditioned:
    def test_surfaces_as_arl_not_computable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decision 13.4 / row F14: whatever the solver raises, the fit raises
        ``DegenerateBaselineError``, never the solver's own exception."""

        def spsolve(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("the factorisation broke down")

        monkeypatch.setattr(scipy.sparse.linalg, "spsolve", spsolve)

        with pytest.raises(DegenerateBaselineError) as excinfo:
            _fit(200, 20, target_arl=370.0, direction="lower")

        assert excinfo.value.context["reason"] == "arl_not_computable"
        assert excinfo.value.context["figure"] == "achieved_arl"


class TestAuditSummaryOfAOneSidedChart:
    @pytest.mark.parametrize(
        ("direction", "unchecked"), [("lower", "upper"), ("upper", "lower")]
    )
    def test_names_the_unchecked_arm(self, direction: str, unchecked: str) -> None:
        """Corrigendum C3: a one-sided chart carries only its checked arm, and
        the audit record says so rather than printing a bare ``None``."""
        chart = _fit(200, 20, target_arl=370.0, direction=direction)

        assert f"Lattice, {unchecked} arm: not checked" in chart.audit_summary()
