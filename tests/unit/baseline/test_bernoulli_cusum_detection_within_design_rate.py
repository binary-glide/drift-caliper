"""A disclosure figure describing no shift is ``None``, with an advisory (C13).

Decision 18 items 30-32 (corrigendum C13, ratified 2026-09-24).

**What was found.** Hypothesis (``test_one_sided_achieved_arl_is_never_below_
the_request``) drew m=100, f=25, ``"lower"``, T=10^5, M=1.01. Production at
``3bd013d`` raises F14 (``figure="expected_detection_arl"``) and refuses a
chart that is itself valid. The detection rate ``p_hat x M`` sits at or inside
the lower arm's design rate ``p_U``, so the lower arm's run length there is at
least ``achieved_arl``: the figure describes no detection, and at M=1.01 it is
beyond double resolution.

**The rule** (C13's table; boundaries included, because at equality the figure
equals the in-control run length):

- ``expected_detection_arl`` for ``"lower"``/``"two_sided"`` is ``None``
  exactly when f >= 1 and ``p_hat x M <= p_U``, with
  ``FittingAdvisory(kind="detection_shift_within_design_rate",
  boundary=p_U / p_hat)``;
- ``expected_detection_arl`` for ``"upper"`` and
  ``expected_improvement_detection_arl`` for ``"two_sided"`` are ``None``
  exactly when ``p_hat / M >= p_L``, with
  ``FittingAdvisory(kind="improvement_shift_within_design_rate",
  boundary=p_hat / p_L)``;
- decided from ``(p_hat, M, p_U, p_L)`` before any solve -- ``None`` even when
  the solve would succeed (M=1.2 on the same baseline reports 2,843,692
  today);
- the advisory boundaries are **exclusive**: at ``M = boundary`` the figure is
  ``None``; a strictly larger multiple reports it;
- ``achieved_arl`` never takes this path, and F14 remains only for
  ``achieved_arl`` in normal operation (C13 point 5/6).

**Reading the figure.** ``expected_detection_arl`` is annotated ``float | None``
(C13), so it is read directly.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
import scipy.sparse.linalg
from hypothesis import HealthCheck, Phase, assume, given, reject, settings
from hypothesis import strategies as st

from drift_caliper.baseline import FittedBernoulliCUSUM, fit_bernoulli_cusum
from drift_caliper.errors import DegenerateBaselineError, InvalidParameterError
from tests.support import bernoulli_reference as ref
from tests.support.binary_baselines import binary_baseline

_DEGRADATION = "detection_shift_within_design_rate"
_IMPROVEMENT = "improvement_shift_within_design_rate"


def _fit(
    m: int, f: int, direction: str, multiple: float, target_arl: float = 370.0
) -> FittedBernoulliCUSUM:
    baseline, _ = binary_baseline(m, f)
    return fit_bernoulli_cusum(
        baseline,
        target_arl=target_arl,
        direction=direction,
        detect_rate_multiple=multiple,
    )


def _advisories(chart: FittedBernoulliCUSUM) -> dict[str, float]:
    return {advisory.kind: advisory.boundary for advisory in chart.advisories}


# ===========================================================================
# Item 30 -- the Hypothesis counterexample, and the boundary either side
# ===========================================================================


class TestDegradationFigureInsideTheDesignRate:
    """C13 item 30, at m=100 f=25 (``p_hat = 0.25``, ``p_U/p_hat ~ 1.2561``)."""

    def test_the_pinned_counterexample_fits_with_no_figure(self) -> None:
        """The regression: m=100 f=25 "lower" T=10^5 M=1.01 fits, the figure is
        ``None``, and the degradation advisory carries ``boundary = p_U/p_hat``.
        Today: ``DegenerateBaselineError`` (F14 on ``expected_detection_arl``)."""
        chart = _fit(100, 25, "lower", 1.01, target_arl=1e5)

        assert chart.expected_detection_arl is None
        assert chart.achieved_arl >= 1e5
        assert _advisories(chart)[_DEGRADATION] == pytest.approx(
            chart.p_u / 0.25, rel=1e-12
        )
        assert _advisories(chart)[_DEGRADATION] == pytest.approx(1.2561, abs=5e-5)

    def test_inside_the_boundary_the_figure_is_none_even_though_it_solves(
        self,
    ) -> None:
        """C13 point 2: M=1.2 is inside (``1.2 x 0.25 <= p_U``). The solve succeeds
        (today it reports 2,843,691.65; the independent reference agrees it is
        finite) and the figure is still ``None``. Today: a float is reported."""
        chart = _fit(100, 25, "lower", 1.2, target_arl=1e5)
        lattice = chart.lattice_lower
        assert lattice is not None
        solvable = ref.one_sided_arl(
            lattice.denominator,
            lattice.reference_units,
            lattice.decision_interval_units,
            0.25 * 1.2,
        )
        assert math.isfinite(solvable)

        assert chart.expected_detection_arl is None
        assert _DEGRADATION in _advisories(chart)

    def test_just_outside_the_boundary_the_figure_is_reported(self) -> None:
        """C13 item 30: at M=1.3 the figure is a float (34,959.25) and the
        advisory is absent. Passes today (already reported)."""
        chart = _fit(100, 25, "lower", 1.3, target_arl=1e5)

        assert chart.expected_detection_arl == pytest.approx(34959.25, abs=5e-3)
        assert _DEGRADATION not in _advisories(chart)

    @pytest.mark.parametrize("direction", ["lower", "two_sided"])
    def test_the_advisory_boundary_is_exact_and_exclusive(self, direction: str) -> None:
        """C13 point 3: at ``M = boundary`` the figure is ``None`` (boundary
        included in the condition); the next float above reports it. Today: no
        advisory exists, so the first read fails."""
        inside = _fit(100, 25, direction, 1.1)
        boundary = _advisories(inside)[_DEGRADATION]

        at = _fit(100, 25, direction, boundary)
        above = _fit(100, 25, direction, math.nextafter(boundary, math.inf))

        assert at.expected_detection_arl is None
        assert _advisories(at)[_DEGRADATION] == boundary
        assert above.expected_detection_arl is not None
        assert _DEGRADATION not in _advisories(above)

    def test_zero_failures_always_reports_the_degradation_figure(self) -> None:
        """C13: at f = 0 the figure is evaluated at ``p_U x M > p_U``, so it is
        always reported -- even at M=1.01. Passes today."""
        chart = _fit(300, 0, "lower", 1.01)

        figure = chart.expected_detection_arl
        assert figure is not None
        assert math.isfinite(figure)
        assert _DEGRADATION not in _advisories(chart)


class TestImprovementFigureInsideTheDesignRate:
    """C13 item 32, the mirror: ``p_hat / M >= p_L`` (m=100 f=25:
    ``p_hat/p_L ~ 1.2901``)."""

    def test_upper_only_detection_figure_is_none_inside(self) -> None:
        """Today: 1,311.47 is reported at M=1.1."""
        chart = _fit(100, 25, "upper", 1.1)

        assert chart.expected_detection_arl is None
        assert _advisories(chart)[_IMPROVEMENT] == pytest.approx(
            0.25 / chart.p_l, rel=1e-12
        )

    def test_upper_boundary_is_exact_and_exclusive(self) -> None:
        inside = _fit(100, 25, "upper", 1.1)
        boundary = _advisories(inside)[_IMPROVEMENT]

        at = _fit(100, 25, "upper", boundary)
        above = _fit(100, 25, "upper", math.nextafter(boundary, math.inf))

        assert at.expected_detection_arl is None
        assert above.expected_detection_arl is not None
        assert _IMPROVEMENT not in _advisories(above)

    def test_upper_only_detection_figure_is_reported_outside(self) -> None:
        """Passes today (M=2: ``0.125 < p_L``)."""
        chart = _fit(100, 25, "upper", 2.0)

        assert chart.expected_detection_arl is not None
        assert _IMPROVEMENT not in _advisories(chart)

    @pytest.mark.parametrize(
        ("multiple", "degradation_none", "improvement_none"),
        [(1.1, True, True), (1.27, False, True), (1.35, False, False)],
        ids=["both_inside", "only_improvement_inside", "both_outside"],
    )
    def test_two_sided_reports_each_figure_by_its_own_condition(
        self, multiple: float, degradation_none: bool, improvement_none: bool
    ) -> None:
        """C13 item 32: two-sided with either condition, and both at once (two
        advisories, degradation first -- C13 point 3's ordering). Today both
        figures are always floats and no advisory exists."""
        chart = _fit(100, 25, "two_sided", multiple)

        assert (chart.expected_detection_arl is None) is degradation_none
        assert (chart.expected_improvement_detection_arl is None) is improvement_none
        kinds = [a.kind for a in chart.advisories]
        expected_kinds = [
            kind
            for kind, present in (
                (_DEGRADATION, degradation_none),
                (_IMPROVEMENT, improvement_none),
            )
            if present
        ]
        assert kinds == expected_kinds


# ===========================================================================
# C13 point 5 -- F14 stays for achieved_arl only
# ===========================================================================


def _poison(monkeypatch: pytest.MonkeyPatch, rate: float) -> list[int]:
    """Return NaN from every solve of a chain moving w.p. ``rate``; record them."""
    real = scipy.sparse.linalg.spsolve
    touched: list[int] = []

    def spsolve(matrix: Any, rhs: Any, *args: Any, **kwargs: Any) -> Any:
        entries = np.abs(np.asarray(matrix.tocsc().data))
        if np.any(np.isclose(entries, rate, rtol=1e-9, atol=0.0)):
            touched.append(int(matrix.shape[0]))
            return np.full(matrix.shape[0], math.nan)
        return real(matrix, rhs, *args, **kwargs)  # type: ignore[no-untyped-call]

    monkeypatch.setattr(scipy.sparse.linalg, "spsolve", spsolve)
    return touched


class TestNoRefusalForAFigureInsideTheDesignRate:
    def test_an_unsolvable_chain_inside_the_condition_is_never_consulted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C13 point 2: ``None`` is decided before any solve, so even a solve that
        would fail at the detection rate cannot raise F14. m=100 f=25 "lower"
        M=1.2 (inside). Today: the poisoned solve raises F14."""
        touched = _poison(monkeypatch, 0.25 * 1.2)

        chart = _fit(100, 25, "lower", 1.2)

        assert chart.expected_detection_arl is None
        assert touched == []

    def test_outside_the_condition_a_bad_solve_is_still_f14(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C13 point 5: outside the condition the figure is bounded by quantities
        already computed, so an uncomputable figure is a solver defect and keeps
        F14 with its ``figure``. Passes today."""
        _poison(monkeypatch, 0.25 * 1.3)

        with pytest.raises(DegenerateBaselineError) as excinfo:
            _fit(100, 25, "lower", 1.3)

        assert excinfo.value.context["figure"] == "expected_detection_arl"


# ===========================================================================
# Item 31 -- the property
# ===========================================================================


class TestDisclosureFigureProperty:
    # Budget: 40 draws, each one fit at target <= 10^3 on m <= 3,000 with
    # M >= 1.05 (<= 0.1 s measured, two-sided); ~4 s locally, x3 = 12 s. A first
    # draft reaching M = 1.001 and T = 10^4 took 1,072 s in the red run: near
    # M = 1 the chains grow without bound, and neither boundary (1.2-9.5 here)
    # needs them. Shrinking is off so a red run reports without re-running
    # hundreds of expensive fits.
    @pytest.mark.timeout(120)
    @settings(
        max_examples=40,
        deadline=None,
        phases=[Phase.explicit, Phase.reuse, Phase.generate],
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    @given(
        m=st.integers(min_value=100, max_value=3_000),
        f_fraction=st.floats(min_value=0.0, max_value=0.45),
        direction=st.sampled_from(["lower", "upper", "two_sided"]),
        position=st.floats(min_value=0.0, max_value=1.0),
        log10_target=st.floats(min_value=0.0, max_value=3.0),
    )
    def test_figure_is_none_exactly_when_its_condition_holds(
        self,
        m: int,
        f_fraction: float,
        direction: str,
        position: float,
        log10_target: float,
    ) -> None:
        """C13 item 31: over legal inputs, each disclosure figure is ``None`` iff
        its condition holds; ``achieved_arl`` is never ``None``; F14 is never
        raised for a disclosure figure. Multiples span ``(1.001, 0.99 x F11's
        maximum)`` on a log scale -- here from 1.05 -- so both sides of both
        boundaries are drawn."""
        f = int(f_fraction * m)
        assume(not (direction == "upper" and f == 0))
        p_u = ref.cp_upper(f, m)
        top = 0.99 * (1.0 - 1e-9) / p_u
        assume(top > 1.06)
        multiple = 1.05 * (top / 1.05) ** position
        try:
            chart = _fit(m, f, direction, multiple, target_arl=10.0**log10_target)
        except DegenerateBaselineError as error:
            assert error.context["figure"] == "achieved_arl", error.context
            return
        except InvalidParameterError:
            reject()  # F12/F13/F16: other rows, covered elsewhere

        p_hat = f / m
        effective = chart.direction
        degradation_inside = ref.degradation_within_design_rate(
            f, p_hat, multiple, chart.p_u
        )
        improvement_inside = f > 0 and ref.improvement_within_design_rate(
            p_hat, multiple, chart.p_l
        )
        assert math.isfinite(chart.achieved_arl)  # never None (C13 point 4)
        detection = chart.expected_detection_arl
        if effective == "upper":
            assert (detection is None) is improvement_inside
        else:
            assert (detection is None) is degradation_inside
        if effective == "two_sided":
            assert (
                chart.expected_improvement_detection_arl is None
            ) is improvement_inside


# ===========================================================================
# Item 35 -- C15.3's table as a property
# ===========================================================================


class TestDefaultMultipleBlanksLowFailureFigures:
    """Corrigendum C15.3 / Decision 18 item 35: the ratios ``p_U/p_hat`` and
    ``p_hat/p_L`` depend almost only on ``f``. At the default M = 2 both figures
    are ``None`` for f = 1 (ratios 3.83-3.89 and 9.49-9.50 at every m measured)
    and both are floats for f = 10 (1.50-1.54 and 1.59-1.61)."""

    # Budget: 10 draws x two two-sided fits at T=370 (m <= 300,000: a 0.08 s
    # baseline build and a <= 0.1 s fit, measured) -- ~3 s locally, x3 = 9 s.
    # Shrinking is off: in the red run it re-ran the fits 164 s.
    @pytest.mark.timeout(120)
    @settings(
        max_examples=10,
        deadline=None,
        phases=[Phase.explicit, Phase.reuse, Phase.generate],
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(m=st.integers(min_value=100, max_value=300_000))
    def test_f1_blanks_both_and_f10_reports_both(self, m: int) -> None:
        few = _fit(m, 1, "two_sided", 2.0)
        many = _fit(m, 10, "two_sided", 2.0)

        assert few.expected_detection_arl is None
        assert few.expected_improvement_detection_arl is None
        assert set(_advisories(few)) >= {_DEGRADATION, _IMPROVEMENT}
        assert many.expected_detection_arl is not None
        assert many.expected_improvement_detection_arl is not None
        assert not set(_advisories(many)) & {_DEGRADATION, _IMPROVEMENT}
