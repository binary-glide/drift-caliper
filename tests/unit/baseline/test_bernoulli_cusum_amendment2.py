"""ADR-014 Amendment 2 and its corrigendum: the Bernoulli artefact and its numbers.

TDD red phase for BIN-133's second amendment. The governing text is
ADR-014's "Amendment 2 (2026-09-24)" and "Amendment 2 corrigendum" sections
(on ``arch/BIN-133/adr-014-lattice-amendment``) and ``docs/domain-model.md``'s
``FittedBernoulliCUSUM``/``BernoulliArmLattice`` entries on the same branch.
Where the corrigendum corrects Amendment 2, the corrigendum is followed and
cited (C1-C12).

Decision 18's verification bar, and where each item lives.

Files, abbreviated: [here] this file; [MON]
``tests/unit/monitoring/test_monitor_bernoulli_cusum_differential.py``; [SIM]
``test_bernoulli_cusum_arl_simulated_properties.py``; [REF]
``test_bernoulli_cusum_two_sided_refusal.py``; [DRM]
``test_bernoulli_cusum_detect_rate_multiple.py``; [CON]
``test_bernoulli_cusum_refusal_contract.py``.

- item 1, Monitor against an independent exact stepper: [MON]
- items 2 and 17, simulated ARL0 through Monitor: [SIM]
- item 3, large baselines at C1's cells: [here] ``TestLargeBaselines``
- item 4, Decision 8 enforced by value: [REF]
- item 5, Decision 12's floor and disclosure (C1):
  [here] ``TestLowerArmFloorIsDisclosedNotRefused``
- item 6, the postcondition raises: [here] ``TestReportedArlPostcondition``
- item 7, no float reconstruction: [here] ``TestNoFloatReconstruction``
- item 8, Decision 15 (C1): [here] ``TestDetectionFigureIsAtTheTunedShift``
- items 9, 12 and 24, Decision 16 and C11's bound: [REF]
- items 10, 23 and 27, the registry-driven refusal contract, C6/C10/C12.2:
  [CON] (C5's strings also [here])
- item 11, serialisation round-trip: [here] (artefact) and [MON] (driving)
- item 13, the upper-arm GICP grid: [here] ``TestUpperArmGicpGrid``
- items 14 and 16, ``B`` and calibration D: [here] ``TestTwoSidedCoupledBound``
- item 15, f = 0: [here] ``TestZeroFailureShape``
- item 19, ``expected_improvement_detection_arl``:
  [here] ``TestImprovementDetectionFigure``
- items 20, 25 and 26, ``detect_rate_multiple``, F16 and the finder: [DRM]
- item 21, C7's backstop over ``float | None``: [here] ``TestArtefactShape``
- item 22, C3/C4 lattice presence: [here] and [MON]

**The oracle is independent.** Every expected number is computed at test
time by ``tests.support.bernoulli_reference``, a from-scratch implementation
that imports nothing from ``drift_caliper``, and is also pinned to the figure
the ADR publishes for that cell (to the ADR's printed precision). Where the
reference needs the confidence bounds it is handed the artefact's own
``p_u``/``p_l``: those are verified separately (``test_clopper_pearson.py``
and ``TestArtefactShape.test_p_l_is_the_clopper_pearson_lower_bound``), and
passing them through keeps a last-bit difference in a Beta quantile from
moving a lattice and turning a correct fit into a spurious failure.

**Reading the new fields.** ``lattice_lower``/``lattice_upper``/``p_l``/
``expected_improvement_detection_arl`` and ``BernoulliArmLattice`` do not
exist yet; ``tests.support.bernoulli_surface`` reads them so ``mypy``/``ty``
stay green during the red phase.

**Time budgets** are pytest-timeout hard stops, set from a local measurement
(Apple Silicon; CI measured ~1.9x slower) times at least 3, recorded beside
each. Production is not built yet, so the measurement is of the reference
implementation doing the same work; where production's pre-amendment code
already runs the same cell, its time is recorded too.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pydantic
import pytest
import scipy.sparse.linalg
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from scipy.stats import beta as scipy_beta  # type: ignore[attr-defined]
from scipy.stats import binom  # type: ignore[attr-defined]

import drift_caliper
from drift_caliper.baseline import (
    BernoulliArmLattice,
    FittedBernoulliCUSUM,
    fit_bernoulli_cusum,
)
from drift_caliper.baseline.domain import bernoulli_cusum_fitting as fitting_module
from drift_caliper.errors import DegenerateBaselineError, InvalidParameterError
from tests.support import bernoulli_reference as ref
from tests.support.bernoulli_surface import triplet
from tests.support.binary_baselines import binary_baseline
from tests.support.isolated_bernoulli_fit import fit_in_child

_T = 370.0
_FLOOR_ADVISORY = "lower_arm_signals_on_first_failure"
_NOT_DESIGNABLE_ADVISORY = "upper_arm_not_designable"
# ADR-014 Decision 13.3.
_MAX_DECISION_INTERVAL_UNITS = 999_999
# corrigendum C5.
_ONE_SIDED_METHOD = "gicp_markov_chain"
_TWO_SIDED_METHOD = "gicp_markov_chain_coupled_bound"


def _fit(
    m: int,
    f: int,
    *,
    target_arl: float = _T,
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


def _reference_for(
    chart: FittedBernoulliCUSUM, *, m: int, f: int, direction: str
) -> ref.ReferenceFit:
    return ref.reference_fit(
        m=m,
        f=f,
        target_arl=chart.requested_arl,
        direction=direction,
        multiple=chart.detect_rate_multiple,
        p_u=chart.p_u,
        p_l=chart.p_l,
    )


def _advisory_kinds(chart: FittedBernoulliCUSUM) -> list[str]:
    return [advisory.kind for advisory in chart.advisories]


def _advisory_boundary(chart: FittedBernoulliCUSUM, kind: str) -> float:
    matches = [a.boundary for a in chart.advisories if a.kind == kind]
    assert len(matches) == 1, f"expected exactly one {kind!r}, got {chart.advisories}"
    return matches[0]


# ===========================================================================
# Decision 14 -- BernoulliArmLattice, and the artefact that carries it
# ===========================================================================


class _ExactIntSubclass(int):
    """An ``int`` subclass: Decision 14.1 rejects any integer that is not exact."""


class TestBernoulliArmLatticeValueObject:
    """ADR-014 Decision 14.1; ``docs/domain-model.md`` Value Object Inventory."""

    def test_is_exported_from_baseline_but_not_from_the_top_level(self) -> None:
        assert drift_caliper.baseline.BernoulliArmLattice is BernoulliArmLattice
        assert "BernoulliArmLattice" in drift_caliper.baseline.__all__
        assert "BernoulliArmLattice" not in drift_caliper.__all__

    def test_derived_floats_are_units_over_denominator(self) -> None:
        lattice = BernoulliArmLattice(
            denominator=9, reference_units=8, decision_interval_units=40
        )
        assert lattice.reference_value == 8 / 9
        assert lattice.decision_interval == 40 / 9

    @pytest.mark.parametrize(
        ("denominator", "reference_units", "decision_interval_units"),
        [(2, 1, 1), (9, 8, _MAX_DECISION_INTERVAL_UNITS), (3_364_300, 1, 369)],
        ids=["smallest_legal", "h_at_the_decision_13_3_cap", "no_bound_on_N_C9"],
    )
    def test_accepts_its_bounds(
        self, denominator: int, reference_units: int, decision_interval_units: int
    ) -> None:
        lattice = BernoulliArmLattice(
            denominator=denominator,
            reference_units=reference_units,
            decision_interval_units=decision_interval_units,
        )
        assert triplet(lattice) == (
            denominator,
            reference_units,
            decision_interval_units,
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"denominator": 1, "reference_units": 1},
            {"reference_units": 0},
            {"reference_units": 9},
            {"decision_interval_units": 0},
            {"decision_interval_units": _MAX_DECISION_INTERVAL_UNITS + 1},
            {"denominator": True},
            {"reference_units": True},
            {"decision_interval_units": _ExactIntSubclass(40)},
            {"denominator": 9.0},
            {"reference_units": "8"},
        ],
        ids=[
            "denominator_below_2",
            "reference_units_zero",
            "reference_units_equal_to_denominator",
            "decision_interval_units_zero",
            "decision_interval_units_above_cap",
            "bool_denominator",
            "bool_reference_units",
            "int_subclass_decision_interval_units",
            "float_denominator",
            "str_reference_units",
        ],
    )
    def test_rejects_an_integer_that_is_not_exact_or_is_out_of_bounds(
        self, overrides: dict[str, Any]
    ) -> None:
        arguments: dict[str, Any] = {
            "denominator": 9,
            "reference_units": 8,
            "decision_interval_units": 40,
            **overrides,
        }
        with pytest.raises(InvalidParameterError):
            BernoulliArmLattice(**arguments)

    def test_repr_shows_the_three_integers(self) -> None:
        lattice = BernoulliArmLattice(
            denominator=9, reference_units=8, decision_interval_units=40
        )
        text = repr(lattice)
        assert "9" in text
        assert "8" in text
        assert "40" in text

    def test_bool_raises(self) -> None:
        lattice = BernoulliArmLattice(
            denominator=9, reference_units=8, decision_interval_units=40
        )
        with pytest.raises(TypeError):
            bool(lattice)

    def test_is_immutable(self) -> None:
        lattice = BernoulliArmLattice(
            denominator=9, reference_units=8, decision_interval_units=40
        )
        with pytest.raises(pydantic.ValidationError):
            lattice.denominator = 10  # ty: ignore[invalid-assignment]


class TestArtefactShape:
    """Decision 14.2-14.3 (lattices are the chart; floats are derived), C3, 19.5."""

    @pytest.mark.parametrize(
        ("m", "f", "requested", "reported", "lower_present", "upper_present"),
        [
            (200, 20, "lower", "lower", True, False),
            (200, 20, "upper", "upper", False, True),
            (200, 20, "two_sided", "two_sided", True, True),
            (300, 0, "lower", "lower", True, False),
            (300, 0, "two_sided", "lower", True, False),
        ],
        ids=[
            "lower_f20",
            "upper_f20",
            "two_sided_f20",
            "lower_f0",
            "two_sided_f0_becomes_lower",
        ],
    )
    def test_a_lattice_is_present_exactly_when_its_arm_is_checked(
        self,
        m: int,
        f: int,
        requested: str,
        reported: str,
        lower_present: bool,
        upper_present: bool,
    ) -> None:
        """Corrigendum C3 (ratified C-Q2): ``lattice_X is None`` exactly when
        ``direction`` does not check arm X, for any f -- reversing 6b's "both
        arms always reported"; and Decision 18 item 22."""
        chart = _fit(m, f, direction=requested)

        assert chart.direction == reported
        assert (chart.lattice_lower is not None) is lower_present
        assert (chart.lattice_upper is not None) is upper_present

    @pytest.mark.parametrize("direction", ["lower", "upper", "two_sided"])
    def test_each_float_field_is_its_lattice_units_over_denominator(
        self, direction: str
    ) -> None:
        """Decision 14.3: one source of truth; a float is ``None`` with its lattice."""
        chart = _fit(200, 20, direction=direction)
        pairs = [
            (chart.lattice_lower, "lower"),
            (chart.lattice_upper, "upper"),
        ]

        for lattice, arm in pairs:
            reference_value = getattr(chart, f"reference_value_{arm}")
            decision_interval = getattr(chart, f"decision_interval_{arm}")
            if lattice is None:
                assert reference_value is None
                assert decision_interval is None
            else:
                assert reference_value == lattice.reference_units / lattice.denominator
                assert decision_interval == (
                    lattice.decision_interval_units / lattice.denominator
                )

    def test_float_fields_are_computed_not_stored(self) -> None:
        """Decision 14.3: ``@computed_field`` -- in ``model_dump``, never stored."""
        derived = {
            "reference_value_lower",
            "decision_interval_lower",
            "reference_value_upper",
            "decision_interval_upper",
        }
        chart = _fit(200, 20)

        assert derived.isdisjoint(FittedBernoulliCUSUM.model_fields)
        assert derived <= set(FittedBernoulliCUSUM.model_computed_fields)
        assert {"lattice_lower", "lattice_upper"} <= set(
            FittedBernoulliCUSUM.model_fields
        )
        assert derived <= set(chart.model_dump())

    @pytest.mark.parametrize(
        ("m", "f", "direction"),
        [
            (200, 20, "two_sided"),
            (200, 20, "lower"),
            (200, 20, "upper"),
            (300, 0, "two_sided"),
        ],
    )
    def test_model_dump_round_trip_rebuilds_the_same_chart(
        self, m: int, f: int, direction: str
    ) -> None:
        """Decision 18 item 11 (artefact half; the Monitor half drives the rebuilt
        chart in ``test_monitor_bernoulli_cusum_differential.py``)."""
        chart = _fit(m, f, direction=direction)

        rebuilt = FittedBernoulliCUSUM.model_validate(chart.model_dump())
        from_json = FittedBernoulliCUSUM.model_validate_json(chart.model_dump_json())

        assert rebuilt == chart
        assert from_json == chart
        assert triplet(rebuilt.lattice_lower) == triplet(chart.lattice_lower)
        assert triplet(rebuilt.lattice_upper) == triplet(chart.lattice_upper)

    def test_finite_float_backstop_covers_the_optional_improvement_figure(
        self,
    ) -> None:
        """Corrigendum C7 / Decision 18 item 21: BIN-142's backstop must cover
        ``float | None`` fields, skipping ``None``."""
        well_formed = _fit(200, 20).model_dump()
        for bad in (math.nan, math.inf):
            corrupted = {**well_formed, "expected_improvement_detection_arl": bad}
            with pytest.raises(InvalidParameterError) as excinfo:
                FittedBernoulliCUSUM.model_validate(corrupted)
            assert excinfo.value.context["parameter"] == (
                "expected_improvement_detection_arl"
            )

    @pytest.mark.parametrize(("m", "f"), [(200, 20), (1000, 1), (300, 0)])
    def test_p_l_is_the_clopper_pearson_lower_bound(self, m: int, f: int) -> None:
        """Decision 19.1/19.5: the alpha quantile of Beta(f, m - f + 1), alpha 0.10;
        ``0.0`` at f = 0 (19.2); closed form ``1 - (1 - alpha)^(1/m)`` at f = 1."""
        chart = _fit(m, f, direction="lower")

        if f == 0:
            assert chart.p_l == 0.0
        else:
            expected = float(scipy_beta.ppf(0.10, f, m - f + 1))
            assert chart.p_l == pytest.approx(expected, rel=1e-12)
        if f == 1:
            assert chart.p_l == pytest.approx(1.0 - 0.9 ** (1.0 / m), rel=1e-12)

    def test_audit_summary_reports_each_present_lattice(self) -> None:
        """Decision 14 "Cost": ``audit_summary()`` gains the lattice lines."""
        chart = _fit(200, 20)
        summary = chart.audit_summary()

        for lattice in (chart.lattice_lower, chart.lattice_upper):
            values = triplet(lattice)
            assert values is not None
            for value in values:
                assert str(value) in summary


# ===========================================================================
# Decision 12 -- the lower arm's floor is 1/p_U: fit, report, disclose
# ===========================================================================


class TestLowerArmFloorIsDisclosedNotRefused:
    """Decision 12 and Decision 18 item 5, with corrigendum C1's re-based cells."""

    @pytest.mark.parametrize(
        ("m", "expected"),
        [
            (852, 370.5191),
            (1_000, 434.7947),
            (5_000, 2171.9724),
            (300_000, 130288.8446),
        ],
    )
    def test_floored_lower_arm_reports_one_over_p_u_and_discloses_it(
        self, m: int, expected: float
    ) -> None:
        """C1 item 5: f=0 "lower" T=370 gives ``h_units = 1`` and
        ``achieved_arl = 1/p_U`` = 370.5191, 434.7947, 2171.9724, 130288.8446;
        the advisory is present with ``boundary == achieved_arl``.

        m=300,000 is in-process: its one-sided fit touches no two-sided path and
        the pre-amendment code ran it in 0.12 s without incident (measured)."""
        chart = _fit(m, 0, direction="lower")

        lower = chart.lattice_lower
        assert lower is not None
        assert lower.decision_interval_units == 1
        assert chart.achieved_arl == pytest.approx(1.0 / chart.p_u, rel=1e-9)
        assert chart.achieved_arl == pytest.approx(expected, abs=5e-5)
        assert _advisory_boundary(chart, _FLOOR_ADVISORY) == pytest.approx(
            chart.achieved_arl, rel=1e-12
        )

    def test_floored_case_with_failures(self) -> None:
        """C1 item 5: m=300 f=3 "lower" T=40 is floored, 45.1815, advisory present."""
        chart = _fit(300, 3, target_arl=40.0, direction="lower")

        assert chart.achieved_arl == pytest.approx(1.0 / chart.p_u, rel=1e-9)
        assert chart.achieved_arl == pytest.approx(45.1815, abs=5e-5)
        assert _advisory_boundary(chart, _FLOOR_ADVISORY) == pytest.approx(
            chart.achieved_arl, rel=1e-12
        )

    def test_a_target_in_the_gap_above_the_floor_carries_no_advisory(self) -> None:
        """C1 item 5: the original T=50 cell falls in the *gap* -- h_units=26,
        147.5931, and no advisory. Kept as the gap case (Decision 12 point 3,
        "report, don't chase")."""
        chart = _fit(300, 3, target_arl=50.0, direction="lower")

        assert triplet(chart.lattice_lower) == (27, 1, 26)
        assert chart.achieved_arl == pytest.approx(147.5931, abs=5e-5)
        assert _FLOOR_ADVISORY not in _advisory_kinds(chart)

    def test_an_unfloored_zero_failure_arm_carries_no_advisory(self) -> None:
        """C1 item 5: m=300 f=0 "lower" T=370 -- h_units = 77, 423.8900."""
        chart = _fit(300, 0, direction="lower")

        assert triplet(chart.lattice_lower) == (78, 1, 77)
        assert chart.achieved_arl == pytest.approx(423.8900, abs=5e-5)
        assert _FLOOR_ADVISORY not in _advisory_kinds(chart)

    def test_an_upper_only_chart_never_carries_the_floor_advisory(self) -> None:
        """Decision 12 point 2: the condition requires ``direction`` to check the
        lower arm."""
        chart = _fit(200, 20, target_arl=2.0, direction="upper")

        assert _FLOOR_ADVISORY not in _advisory_kinds(chart)

    def test_zero_failure_two_sided_request_fits_lower_only_with_both_advisories(
        self,
    ) -> None:
        """C1 item 5, replacing "fits at 552.2": m=5000 f=0 "two_sided" T=370 returns
        ``direction = "lower"``, 2171.9724, both advisories, ``lattice_upper is None``
        (Decision 19.2)."""
        chart = _fit(5_000, 0, direction="two_sided")

        assert chart.direction == "lower"
        assert chart.lattice_upper is None
        assert chart.achieved_arl == pytest.approx(2171.9724, abs=5e-5)
        assert _advisory_boundary(chart, _FLOOR_ADVISORY) == pytest.approx(
            chart.achieved_arl, rel=1e-12
        )
        assert _advisory_boundary(chart, _NOT_DESIGNABLE_ADVISORY) == 1.0

    @pytest.mark.slow
    # Budget: 20 draws, each one reference-sized fit of <= 1 s locally at the
    # extremes (reference implementation: m=300,000 f=1 "upper" T=1e6 4.3 s is
    # the single worst one-sided cell measured, C1). 20 x 4.3 s x 3 = 258 s.
    @pytest.mark.timeout(300)
    @settings(
        max_examples=20,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        m=st.integers(min_value=100, max_value=300_000),
        f_fraction=st.floats(min_value=0.0, max_value=1.0),
        log10_target=st.floats(min_value=0.0, max_value=6.0),
        direction=st.sampled_from(["lower", "upper"]),
        multiple_position=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_one_sided_achieved_arl_is_never_below_the_request(
        self,
        m: int,
        f_fraction: float,
        log10_target: float,
        direction: str,
        multiple_position: float,
    ) -> None:
        """Decision 12.1 / Decision 18 item 5's property, over the full legal space
        (Decision 11 item 1's rule: f = 0 at large m included, no "realistic"
        bound on m, f, target or multiple).

        ``f`` spans ``0..m-1``; the multiple spans ``(1.01, 0.99 x F11's
        max_detect_rate_multiple)`` on a log scale, so large multiples are drawn,
        not only M <= 5 (C12.4's blind spot)."""
        f = min(m - 1, int(f_fraction * m))
        assume(not (direction == "upper" and f == 0))  # F15, its own test
        p_u = ref.cp_upper(f, m)
        max_multiple = (1.0 - 1e-9) / p_u
        assume(max_multiple > 1.02)
        multiple = 1.0 + 0.01 * ((0.99 * max_multiple - 1.0) / 0.01) ** (
            multiple_position
        )
        target = 10.0**log10_target

        chart = _fit(m, f, target_arl=target, direction=direction, multiple=multiple)

        assert chart.achieved_arl >= chart.requested_arl


# ===========================================================================
# Decision 13 -- large baselines, integers end to end (item 3)
# ===========================================================================

_LARGE_CELL_TIMEOUT = 120.0  # child process; see each test's budget note


def _only(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(outcomes) == 1
    return outcomes[0]


def _assert_matches_reference(
    outcome: dict[str, Any], *, m: int, f: int, target: float, direction: str
) -> ref.ReferenceFit:
    assert outcome["ok"], f"expected a fit, got {outcome}"
    expected = ref.reference_fit(
        m=m,
        f=f,
        target_arl=target,
        direction=direction,
        p_u=outcome["p_u"],
        p_l=outcome["p_l"],
    )
    assert outcome["direction"] == expected.direction
    assert _as_triplet(outcome["lattice_lower"]) == expected.lattice_lower
    assert _as_triplet(outcome["lattice_upper"]) == expected.lattice_upper
    for figure in (
        "achieved_arl",
        "expected_detection_arl",
        "expected_improvement_detection_arl",
    ):
        reported, reference = outcome[figure], getattr(expected, figure)
        if reference is None:
            assert reported is None, figure
            continue
        assert isinstance(reported, float), f"{figure} is {reported!r}"
        assert math.isfinite(reported)
        assert reported >= 1.0
        assert reported != fitting_module._ILL_CONDITIONED_ARL_SENTINEL
        assert reported == pytest.approx(reference, rel=1e-9), figure
    return expected


def _as_triplet(value: list[int] | None) -> tuple[int, int, int] | None:
    if value is None:
        return None
    n, k, h = value
    return n, k, h


class TestLargeBaselines:
    """Decision 13 and Decision 18 item 3, at corrigendum C1's re-based cells.

    Each fit runs in a child process (``tests.support.isolated_bernoulli_fit``):
    the pre-amendment two-sided solve segfaulted SuperLU at m=200,000 f=0
    (Amendment 2 section 0, defect 2), and a segfault in-process would end the
    whole red run rather than fail one test.
    """

    @pytest.mark.parametrize(
        ("m", "f", "target", "direction", "pinned"),
        [
            # C1 item 3; pre-amendment code: 0.10 s, a different (p_U) design.
            (300_000, 1, _T, "lower", {"achieved_arl": 77126.7422}),
            # Reconstruction regression: N_upper = 3,364,300 > the removed
            # 100,000 reconstruction cap (Decision 13.1, C1). Pre-amendment:
            # 0.10 s, 370.89 at p_U.
            (
                300_000,
                1,
                _T,
                "upper",
                {
                    "achieved_arl": 370.0241,
                    "lattice_upper": (3_364_300, 3_364_299, 369),
                },
            ),
            (
                300_000,
                1,
                _T,
                "two_sided",
                {
                    "achieved_arl": 370.1115,
                    "expected_detection_arl": 370.5428,
                    "expected_improvement_detection_arl": 370.8856,
                    "joint_states": 742,
                },
            ),
            (300_000, 30, _T, "upper", {"achieved_arl": 370.2214}),
            (
                300_000,
                30,
                _T,
                "two_sided",
                {"achieved_arl": 370.9495, "joint_states": 760},
            ),
            # Decision 18 item 3's own f=0 lower cell, unchanged by Decision 19.
            (300_000, 0, 1e6, "lower", {"achieved_arl": 1000020.0999}),
            # The segfault neighbourhood: f=0 two-sided now fits lower-only
            # (Decision 19.2) at 1/p_U = 130288.8446 (C1 item 5).
            (300_000, 0, _T, "two_sided", {"achieved_arl": 130288.8446}),
            (1_000_000, 0, _T, "two_sided", {"achieved_arl": 434294.9819}),
        ],
        ids=[
            "m300k_f1_lower_370",
            "m300k_f1_upper_370_N_3364300",
            "m300k_f1_two_sided_370",
            "m300k_f30_upper_370",
            "m300k_f30_two_sided_370",
            "m300k_f0_lower_1e6",
            "m300k_f0_two_sided_370_becomes_lower",
            "m1M_f0_two_sided_370_becomes_lower",
        ],
    )
    # Budget: reference implementation <= 0.8 s per cell plus ~2 s child start-up
    # and a 1M-observation baseline (0.3 s) -- 3 s x 3 = 9 s; 120 s leaves room
    # for an unvectorised production matrix build.
    @pytest.mark.timeout(240)
    def test_fits_and_matches_the_independent_solver(
        self,
        m: int,
        f: int,
        target: float,
        direction: str,
        pinned: dict[str, Any],
    ) -> None:
        outcome = _only(
            fit_in_child(
                m=m,
                f=f,
                direction=direction,
                targets=[target],
                timeout=_LARGE_CELL_TIMEOUT,
            )
        )

        expected = _assert_matches_reference(
            outcome, m=m, f=f, target=target, direction=direction
        )

        for key, value in pinned.items():
            if key == "joint_states":
                assert expected.lattice_lower is not None
                assert expected.lattice_upper is not None
                assert (expected.lattice_lower[2] + 1) * (
                    expected.lattice_upper[2] + 1
                ) == value
            elif key.startswith("lattice"):
                assert _as_triplet(outcome[key]) == value
            else:
                assert outcome[key] == pytest.approx(value, abs=5e-5)

    @pytest.mark.slow
    @pytest.mark.parametrize(
        ("f", "target", "direction", "pinned_h", "pinned_arl"),
        [
            (1, 1e6, "lower", 101_595, 1000018.2953),
            (1, 1e6, "upper", 857_041, 1000001.1949),
            (30, 1e6, "upper", 81_621, 1000026.7807),
        ],
        ids=["f1_lower_1e6", "f1_upper_1e6", "f30_upper_1e6"],
    )
    # Budget: reference implementation 0.5 s / 4.3 s / 0.5 s locally (C1's own
    # table: the f=1 upper cell's calibration dominates); x3 = 13 s at worst.
    # 600 s allows for an unvectorised production build of ~857k-state chains.
    @pytest.mark.timeout(600)
    def test_large_one_sided_targets_at_m_300000(
        self,
        f: int,
        target: float,
        direction: str,
        pinned_h: int,
        pinned_arl: float,
    ) -> None:
        """C1 item 3: these fit -- **not** F12 (Decision 13.3's cap, C3's proof
        that an f >= 1 upper arm needs ``h <= T - 1``)."""
        outcome = _only(
            fit_in_child(
                m=300_000, f=f, direction=direction, targets=[target], timeout=550.0
            )
        )

        _assert_matches_reference(
            outcome, m=300_000, f=f, target=target, direction=direction
        )
        lattice = outcome[f"lattice_{direction}"]
        assert lattice[2] == pinned_h
        assert outcome["achieved_arl"] == pytest.approx(pinned_arl, abs=5e-5)

    @pytest.mark.slow
    @pytest.mark.parametrize("direction", ["lower", "upper", "two_sided"])
    # Budget: reference implementation < 0.1 s per fit; a 3,000,000-observation
    # baseline builds in ~0.8 s; child start-up ~2 s. 3 s x 3 = 9 s; 180 s for
    # an unbuilt production path.
    @pytest.mark.timeout(240)
    def test_three_million_observations_every_direction(self, direction: str) -> None:
        """Decision 18 item 3: "m=3,000,000 at T=370, all directions, is marked
        ``slow``". f = 1 so that ``"upper"`` is designable (19.2; C1 re-based the
        large cells to f >= 1). N_upper = 33,642,995 here."""
        outcome = _only(
            fit_in_child(
                m=3_000_000, f=1, direction=direction, targets=[_T], timeout=180.0
            )
        )

        _assert_matches_reference(
            outcome, m=3_000_000, f=1, target=_T, direction=direction
        )

    # Budget: C11's measured end-to-end refusal 2.2 s (k3_refusal_time.py) plus
    # the round-trip fit (reference 0.05 s) and two child start-ups (~4 s):
    # 6.3 s x 3 = 19 s; 240 s hard stop for the unbuilt refusal path.
    @pytest.mark.timeout(300)
    def test_two_sided_at_the_ceiling_refuses_with_a_round_tripping_bound(
        self,
    ) -> None:
        """C1 item 3: m=300,000 f=1 "two_sided" T=10^6 refuses with F13 -- the upper
        arm's per-arm target of 2 x 10^6 exceeds the 999,999-unit cap (Decision 16's
        route) -- reporting C11's ``floor(T_ES)`` = 38,563, which round-trips."""
        refusal = _only(
            fit_in_child(
                m=300_000, f=1, direction="two_sided", targets=[1e6], timeout=240.0
            )
        )

        assert not refusal["ok"]
        assert refusal["type"] == "InvalidParameterError"
        context = refusal["context"]
        assert context["reason"] == "joint_state_count_exceeded"
        bound = context["max_two_sided_target_arl"]
        assert bound == 38_563

        accepted = _only(
            fit_in_child(
                m=300_000,
                f=1,
                direction="two_sided",
                targets=[float(bound)],
                timeout=240.0,
            )
        )
        _assert_matches_reference(
            accepted, m=300_000, f=1, target=float(bound), direction="two_sided"
        )


# ===========================================================================
# Decision 13.4 -- the postcondition raises (item 6)
# ===========================================================================

_Poison = Callable[[int], npt.NDArray[np.float64]]

_POISONS: dict[str, _Poison] = {
    "sentinel": lambda n: np.full(n, fitting_module._ILL_CONDITIONED_ARL_SENTINEL),
    "nan": lambda n: np.full(n, math.nan),
    "below_one": lambda n: np.full(n, 0.5),
    "wrong_length": lambda n: np.full(n + 1, 400.0),
}


def _poison_solves_touching(
    monkeypatch: pytest.MonkeyPatch, rate: float, poison: _Poison
) -> None:
    """Make every linear solve whose chain moves with probability ``rate`` bad.

    **Seam:** production solves ``(I - Q) x = 1`` through
    ``scipy.sparse.linalg.spsolve``, reached as ``bernoulli_cusum_fitting.spla``
    (as it does today). A chain is identified by its transition probabilities,
    which appear in ``I - Q`` as off-diagonal ``-p`` (and as a diagonal ``p`` on
    a self-loop). If the implementation changes solver, move this seam -- not
    the assertions.
    """
    real_spsolve = scipy.sparse.linalg.spsolve

    def spsolve(matrix: Any, rhs: Any, *args: Any, **kwargs: Any) -> Any:
        entries = np.abs(np.asarray(matrix.tocsc().data))
        if np.any(np.isclose(entries, rate, rtol=1e-9, atol=0.0)):
            return poison(matrix.shape[0])
        return real_spsolve(matrix, rhs, *args, **kwargs)  # type: ignore[no-untyped-call]

    monkeypatch.setattr(scipy.sparse.linalg, "spsolve", spsolve)


class TestReportedArlPostcondition:
    """Decision 13.4 / Decision 18 item 6 / F14, extended by 19.6 and C10.

    Cell: m=300 f=3 (p_hat = 0.01, p_U ~ 0.0221, p_L ~ 0.00368), M = 2. The rates
    each figure is solved at are all distinct there, so poisoning one figure's
    chain leaves every other solve untouched.
    """

    @pytest.mark.parametrize("poison", list(_POISONS), ids=list(_POISONS))
    @pytest.mark.parametrize(
        ("direction", "figure", "rate"),
        [
            # achieved: the lower arm is solved at p_U (calibration too).
            ("lower", "achieved_arl", ref.cp_upper(3, 300)),
            # achieved for two-sided is B, whose chain moves w.p. p_L.
            ("two_sided", "achieved_arl", ref.cp_lower(3, 300)),
            ("lower", "expected_detection_arl", 0.01 * 2.0),
            ("two_sided", "expected_detection_arl", 0.01 * 2.0),
            ("upper", "expected_detection_arl", 0.01 / 2.0),
            ("two_sided", "expected_improvement_detection_arl", 0.01 / 2.0),
        ],
        ids=[
            "lower_achieved",
            "two_sided_achieved_B",
            "lower_detection",
            "two_sided_detection",
            "upper_detection",
            "two_sided_improvement",
        ],
    )
    # Budget: reference two-sided fit at this cell 0.53 s locally; x3 = 1.6 s.
    @pytest.mark.timeout(60)
    def test_a_bad_solve_raises_arl_not_computable_and_builds_no_artefact(
        self,
        monkeypatch: pytest.MonkeyPatch,
        poison: str,
        direction: str,
        figure: str,
        rate: float,
    ) -> None:
        baseline, _ = binary_baseline(300, 3)
        _poison_solves_touching(monkeypatch, rate, _POISONS[poison])

        with pytest.raises(DegenerateBaselineError) as excinfo:
            fit_bernoulli_cusum(baseline, target_arl=_T, direction=direction)

        context = excinfo.value.context
        assert context["reason"] == "arl_not_computable"
        assert context["chart_type"] == "bernoulli_cusum"
        assert context["figure"] == figure


# ===========================================================================
# Decision 13.1 -- no float reconstruction in production (item 7)
# ===========================================================================


class TestNoFloatReconstruction:
    """Decision 13.1 / Decision 18 item 7: ``limit_denominator``,
    ``_lattice_denominator`` and ``_DENOMINATOR_RECONSTRUCTION_CAP`` are removed
    from production. ``Fraction`` itself is *not* banned: corrigendum C12.4's
    finder uses exact ``Fraction`` arithmetic by design; what is banned is
    rebuilding a lattice from floats."""

    _SRC = Path(drift_caliper.__file__).resolve().parent
    _FORBIDDEN_NAMES = frozenset(
        {"_lattice_denominator", "_DENOMINATOR_RECONSTRUCTION_CAP"}
    )

    def test_no_production_module_reconstructs_a_lattice_from_floats(self) -> None:
        offences: list[str] = []
        for path in sorted(self._SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.Name):
                    name = node.id
                elif isinstance(node, ast.FunctionDef):
                    name = node.name
                if name == "limit_denominator" or name in self._FORBIDDEN_NAMES:
                    offences.append(f"{path.name}:{getattr(node, 'lineno', 0)}: {name}")

        assert offences == []


# ===========================================================================
# Decision 15 -- expected_detection_arl at the tuned shift (item 8)
# ===========================================================================


class TestDetectionFigureIsAtTheTunedShift:
    """Decision 15 / Decision 18 item 8, re-based by corrigendum C1."""

    @pytest.mark.parametrize(
        ("m", "f", "expected"),
        [(150, 40, 72.1128), (200, 20, 157.6429), (1000, 1, 398.1379)],
    )
    def test_upper_only_chart_is_evaluated_at_the_improvement(
        self, m: int, f: int, expected: float
    ) -> None:
        """C1 item 8: at ``p_hat / M`` with the upper arm at ``p_L`` -- 72.1128,
        157.6429, 398.1379. Amendment 2's 32.8/61.3 (upper arm at ``p_U``) and
        the 314.1 f = 0 fallback are withdrawn. The shipped code reports
        357,451.6 at m=150 f=40 (evaluated at a degradation)."""
        chart = _fit(m, f, direction="upper")
        expected_fit = _reference_for(chart, m=m, f=f, direction="upper")

        assert expected_fit.expected_detection_arl is not None
        assert chart.expected_detection_arl == pytest.approx(
            expected_fit.expected_detection_arl, rel=1e-9
        )
        assert chart.expected_detection_arl == pytest.approx(expected, abs=5e-5)

    @pytest.mark.parametrize(
        ("m", "f", "direction"),
        [(200, 20, "lower"), (300, 0, "lower"), (300, 3, "two_sided")],
        ids=["lower_at_p_hat_M", "lower_f0_at_p_u_M", "two_sided_joint_at_p_hat_M"],
    )
    def test_lower_and_two_sided_are_unchanged(
        self, m: int, f: int, direction: str
    ) -> None:
        """Decision 15's table: lower at ``p_hat x M`` (``p_U x M`` at f = 0);
        two-sided via the joint chain at ``p_hat x M`` (C8: its f = 0 row is
        unreachable)."""
        chart = _fit(m, f, direction=direction)
        expected_fit = _reference_for(chart, m=m, f=f, direction=direction)

        assert expected_fit.expected_detection_arl is not None
        assert chart.expected_detection_arl == pytest.approx(
            expected_fit.expected_detection_arl, rel=1e-9
        )


# ===========================================================================
# Decision 19 -- p_L, the coupled bound B, calibration D (items 13-16)
# ===========================================================================

_A10_CELLS = [(300, 3), (200, 20), (100, 10), (1000, 5)]


class TestTwoSidedCoupledBound:
    """Decision 19.4: the two-sided ``achieved_arl`` is ``B`` under calibration D."""

    @pytest.mark.parametrize(("m", "f"), _A10_CELLS)
    def test_design_and_bound_match_the_independent_calibration_d(
        self, m: int, f: int
    ) -> None:
        """Decision 18 item 16, and 19.4's "after, D" column (370.4, 371.1, 373.5,
        370.3). Both lattices and ``B`` equal the reference's calibration D."""
        chart = _fit(m, f)
        expected_fit = _reference_for(chart, m=m, f=f, direction="two_sided")

        assert triplet(chart.lattice_lower) == expected_fit.lattice_lower
        assert triplet(chart.lattice_upper) == expected_fit.lattice_upper
        assert expected_fit.achieved_arl is not None
        assert chart.achieved_arl == pytest.approx(expected_fit.achieved_arl, rel=1e-9)

    @pytest.mark.parametrize(("m", "f"), _A10_CELLS)
    def test_calibration_d_is_minimal(self, m: int, f: int) -> None:
        """Decision 18 item 16: ``B >= T``, and ``B`` at ``h_up - 1`` is ``< T``."""
        chart = _fit(m, f)
        lower, upper = triplet(chart.lattice_lower), triplet(chart.lattice_upper)
        assert lower is not None
        assert upper is not None
        n_up, k_up, h_up = upper

        below = ref.coupled_arl(lower, (n_up, k_up, h_up - 1), chart.p_l, chart.p_u)

        assert chart.achieved_arl >= _T
        assert below < _T

    @pytest.mark.parametrize(("m", "f"), [(300, 3), (200, 20), (1000, 5)])
    def test_bound_is_below_the_joint_arl_at_every_rate_in_the_interval(
        self, m: int, f: int
    ) -> None:
        """Decision 18 item 14: ``B <=`` the exact joint ARL at ``p in {p_L, p_hat,
        p_U}`` and 5 interior points; and ``B`` is non-decreasing in ``h_up``."""
        chart = _fit(m, f)
        lower, upper = triplet(chart.lattice_lower), triplet(chart.lattice_upper)
        assert lower is not None
        assert upper is not None
        low, high = chart.p_l, chart.p_u
        rates = [low, f / m, high, *np.linspace(low, high, 7)[1:-1]]

        for rate in rates:
            joint = ref.coupled_arl(lower, upper, rate, rate)
            assert chart.achieved_arl <= joint * (1.0 + 1e-12), rate

        n_up, k_up, h_up = upper
        bounds = [
            ref.coupled_arl(lower, (n_up, k_up, h), low, high)
            for h in range(max(1, h_up - 3), h_up + 4)
        ]
        assert bounds == sorted(bounds)

    @pytest.mark.parametrize(
        ("direction", "expected"),
        [
            ("lower", _ONE_SIDED_METHOD),
            ("upper", _ONE_SIDED_METHOD),
            ("two_sided", _TWO_SIDED_METHOD),
        ],
    )
    def test_calibration_method_names_the_coupled_bound(
        self, direction: str, expected: str
    ) -> None:
        """Corrigendum C5 / Decision 18 item 23; the harmonic fallback is withdrawn."""
        assert _fit(200, 20, direction=direction).calibration_method == expected

    def test_upper_arm_is_designed_at_p_l(self) -> None:
        """Decision 19.1: ``r`` from ``(1 - p_L, 1 - p_L / M)``, calibrated at
        ``1 - p_L``. Checked on an upper-only fit so no calibration D enters."""
        chart = _fit(200, 20, direction="upper")
        expected_fit = _reference_for(chart, m=200, f=20, direction="upper")

        assert triplet(chart.lattice_upper) == expected_fit.lattice_upper
        assert triplet(chart.lattice_upper) == (17, 16, 52)
        assert expected_fit.achieved_arl is not None
        assert chart.achieved_arl == pytest.approx(expected_fit.achieved_arl, rel=1e-9)


class TestImprovementDetectionFigure:
    """Decision 19.6 / Decision 18 item 19."""

    @pytest.mark.parametrize(
        ("m", "f", "b", "improvement"),
        [
            (100, 1, 370.4, 1416.5),
            (1000, 1, 370.1, 504.7),
            (1000, 5, 370.3, 580.9),
            (300, 3, 370.4, 780.3),
            (200, 20, 371.1, 220.1),
            (100, 10, 373.5, 334.5),
            (150, 40, 382.6, 85.5),
        ],
    )
    # Budget: reference fits 0.02-0.53 s locally (m=100 f=1: 19,182 joint
    # states); x3 = 1.6 s.
    @pytest.mark.timeout(60)
    def test_equals_the_joint_chain_at_p_hat_over_m(
        self, m: int, f: int, b: float, improvement: float
    ) -> None:
        """19.6's measured table (g6_improvement_field.py): equal to an independent
        joint solver at ``p_hat / M`` to rel 1e-9, finite and >= 1."""
        chart = _fit(m, f)
        expected_fit = _reference_for(chart, m=m, f=f, direction="two_sided")
        reported = chart.expected_improvement_detection_arl

        assert reported is not None
        assert expected_fit.expected_improvement_detection_arl is not None
        assert math.isfinite(reported)
        assert reported >= 1.0
        assert reported == pytest.approx(
            expected_fit.expected_improvement_detection_arl, rel=1e-9
        )
        assert reported == pytest.approx(improvement, abs=0.05)
        assert chart.achieved_arl == pytest.approx(b, abs=0.05)

    @pytest.mark.parametrize(
        ("m", "f", "direction"),
        [(200, 20, "lower"), (200, 20, "upper"), (300, 0, "two_sided")],
        ids=["lower", "upper", "two_sided_f0"],
    )
    def test_is_none_unless_both_arms_are_checked(
        self, m: int, f: int, direction: str
    ) -> None:
        """19.6's rule: non-``None`` exactly when the chart checks both arms."""
        assert (
            _fit(m, f, direction=direction).expected_improvement_detection_arl is None
        )


class TestZeroFailureShape:
    """Decision 19.2 / Decision 18 item 15."""

    def test_two_sided_request_becomes_the_one_sided_lower_fit(self) -> None:
        """f = 0: ``direction == "lower"``, the ``upper_arm_not_designable``
        advisory, ``lattice_upper is None``, and ``achieved_arl`` equal to the
        one-sided lower fit at ``T`` (not ``2T``)."""
        requested_two_sided = _fit(300, 0, direction="two_sided")
        lower = _fit(300, 0, direction="lower")

        assert requested_two_sided.direction == "lower"
        assert requested_two_sided.lattice_upper is None
        assert _advisory_boundary(requested_two_sided, _NOT_DESIGNABLE_ADVISORY) == 1.0
        assert requested_two_sided.achieved_arl == lower.achieved_arl
        assert triplet(requested_two_sided.lattice_lower) == triplet(
            lower.lattice_lower
        )
        assert requested_two_sided.calibration_method == _ONE_SIDED_METHOD
        assert requested_two_sided.p_l == 0.0

    def test_a_directly_requested_lower_fit_carries_no_not_designable_advisory(
        self,
    ) -> None:
        """C3: a directly requested ``"lower"`` at f = 0 has the same shape minus
        the ``upper_arm_not_designable`` advisory -- its upper arm is simply not
        checked."""
        assert _NOT_DESIGNABLE_ADVISORY not in _advisory_kinds(
            _fit(300, 0, direction="lower")
        )

    def test_upper_at_zero_failures_is_refused(self) -> None:
        """F15 (Decision 19.5): full key set, and no round-trip key."""
        with pytest.raises(InvalidParameterError) as excinfo:
            _fit(1000, 0, direction="upper")

        context = excinfo.value.context
        assert context["parameter"] == "direction"
        assert context["kind"] == "invalid"
        assert context["provided"] == "upper"
        assert context["reason"] == "no_baseline_failures"
        assert "constraint" in context
        assert not {"min_value", "max_value", "max_detect_rate_multiple"} & set(context)


class TestUpperArmGicpGrid:
    """Decision 19.3 / Decision 18 item 13: the upper arm's appetite by exact
    enumeration over ``f ~ Binomial(m, p0)``, at the worst cell ``(0.075, 100)``
    and the three sub-0.02 rows at ``m = 100``.

    Production designs each baseline (``fit_bernoulli_cusum(direction="upper")``,
    read back through ``lattice_upper``); the true in-control ARL at ``p0`` of
    that exact chart is solved independently. f = 0 has no upper arm (19.2) and
    cannot false-alarm. Pinned values are this reference's exact enumeration,
    equal to 19.3's table at its printed precision (``g1_m100.out``).
    """

    @pytest.mark.slow
    @pytest.mark.parametrize(
        ("p0", "appetite", "below_target"),
        [
            (0.002, 0.0011191032502305227, 0.017391751485409154),
            (0.005, 0.0016732675228853166, 0.08982230899114725),
            (0.01, 0.003432321587640611, 0.07937320225206648),
            (0.075, 0.017273297194371828, 0.07129673967245961),
        ],
    )
    # Budget: <= 40 upper-only fits of m=100, reference ~0.01 s each; x3 < 2 s.
    @pytest.mark.timeout(120)
    def test_appetite_is_within_the_ratified_five_percent(
        self, p0: float, appetite: float, below_target: float
    ) -> None:
        m = 100
        half = full = 0.0
        for f in range(1, m):
            weight = float(binom.pmf(f, m, p0))
            if weight <= 1e-12:
                continue
            upper = triplet(_fit(m, f, direction="upper").lattice_upper)
            assert upper is not None
            n, k, h = upper
            true_arl = ref.one_sided_arl(n, k, h, 1.0 - p0)
            half += weight * (true_arl < _T / 2)
            full += weight * (true_arl < _T)

        assert half <= 0.05
        assert full <= 0.10
        assert half == pytest.approx(appetite, rel=1e-6)
        assert full == pytest.approx(below_target, rel=1e-6)
