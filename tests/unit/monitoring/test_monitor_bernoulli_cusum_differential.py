"""``Monitor`` runs exactly the integer chain its artefact reports (ADR-014 D14).

Decision 18 item 1 (🚨 the differential test), the Monitor half of item 11
(a serialised-and-rebuilt artefact drives ``Monitor`` identically), and item
22's Monitor rows (Decision 14.5 / M2 and corrigendum C4).

**Why this exists (Amendment 2 section 0, defect 3).** ``Monitor`` accumulated
``max(0, S + x - r)`` in binary floating point from the derived float fields,
so it did not run the integer chain whose ARL0 was calibrated. On the
reviewer's sequence at m=105 f=10 it signalled "upper" at observation 139
with ``S = 4.444444444444446`` while the exact statistic was 40 units = h,
which is in control under strict ``>`` (ADR-009 section 5 / BIN-112). Over
4,000 paired runs at m=300 f=3 the float path signalled at or before the
exact chain every time. The earlier Monitor check -- "some signal arrives
within 10,000 identical observations" -- was vacuous: any chart accumulating
in the right direction passes it.

**The stepper** (``_exact_step``) is written here, is under 20 lines, imports
nothing from ``monitor.py`` or ``bernoulli_cusum_fitting.py``, reads only the
artefact's ``lattice_lower``/``lattice_upper`` and applies Decision 14.4's
integer transitions:

- failure: ``s_lo += N_lo - r_lo``; ``s_up = max(0, s_up - r_up)``
- success: ``s_lo = max(0, s_lo - r_lo)``; ``s_up += N_up - r_up``
- signal on ``s_lo > h_lo`` or ``s_up > h_up``, strictly; only checked arms
  accumulate (C3).

Each comparison runs from a fresh ``Monitor`` up to and including the first
signal: what a chart does *after* signalling is not specified by Decision 14,
so this file does not encode it. When both arms exceed on the same step
(possible only after a long excursion), either direction is accepted -- the
ADR does not order them.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from functools import cache
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from drift_caliper.baseline import FittedBernoulliCUSUM, fit_bernoulli_cusum
from drift_caliper.errors import InvalidParameterError
from drift_caliper.measurement import Provenance, ScoringResult
from drift_caliper.monitoring import Monitor
from tests.support.bernoulli_surface import triplet
from tests.support.binary_baselines import binary_baseline

_T = 370.0

Lattice = tuple[int, int, int] | None
State = tuple[int, int]


def _exact_step(
    state: State, failed: bool, lower: Lattice, upper: Lattice
) -> tuple[State, frozenset[str]]:
    s_lo, s_up = state
    if lower is not None:
        n, r, _ = lower
        s_lo = s_lo + (n - r) if failed else max(0, s_lo - r)
    if upper is not None:
        n, r, _ = upper
        s_up = max(0, s_up - r) if failed else s_up + (n - r)
    exceeded = set()
    if lower is not None and s_lo > lower[2]:
        exceeded.add("lower")
    if upper is not None and s_up > upper[2]:
        exceeded.add("upper")
    return (s_lo, s_up), frozenset(exceeded)


@cache
def _chart(m: int, f: int, direction: str) -> tuple[FittedBernoulliCUSUM, Provenance]:
    baseline, provenance = binary_baseline(m, f)
    return (
        fit_bernoulli_cusum(baseline, target_arl=_T, direction=direction),
        provenance,
    )


def _lattices(chart: FittedBernoulliCUSUM) -> tuple[Lattice, Lattice]:
    return triplet(chart.lattice_lower), triplet(chart.lattice_upper)


def _observation(provenance: Provenance, failed: bool) -> ScoringResult:
    return ScoringResult(
        score=0.0 if failed else 1.0, reasoning="", provenance=provenance
    )


def _assert_monitor_matches_stepper(
    chart: FittedBernoulliCUSUM, provenance: Provenance, sequence: Sequence[bool]
) -> int | None:
    """Drive a fresh Monitor and the stepper side by side; return the 1-indexed
    step of the first signal, or ``None`` if the sequence stayed in control."""
    lower, upper = _lattices(chart)
    monitor = Monitor(chart, retain_history=False)
    state: State = (0, 0)
    for step, failed in enumerate(sequence, start=1):
        result = monitor.record(_observation(provenance, failed))
        state, exceeded = _exact_step(state, failed, lower, upper)
        assert result.is_in_control is (not exceeded), (
            f"step {step}: Monitor in_control={result.is_in_control}, exact "
            f"statistic {state} against lower={lower} upper={upper}"
        )
        if exceeded:
            assert result.direction in exceeded, (step, result.direction, exceeded)
            return step
        assert result.direction is None
    return None


def _decode(tokens: str) -> list[bool]:
    """``"P15 F1 ..."`` -> 15 passes, 1 failure, ... (``True`` = failure)."""
    sequence: list[bool] = []
    for token in tokens.split():
        sequence += [token[0] == "F"] * int(token[1:])
    return sequence


# The reviewer's sequence (PR #29 re-review; Amendment 2 section 0, defect 3).
_REVIEWER_SEQUENCE = _decode(
    "P15 F1 P7 F1 P21 F1 P4 F1 P8 F1 P2 F1 P1 F1 P9 F1 P23 F1 P9 F1 P5 F1 P24"
)

# Decision 18 item 1's required configurations: m=105 f=10 and m=300 f=3
# (where float drift was measured), one f=0 baseline with m >= 1,000, one
# baseline with p_hat >= 0.25.
_CONFIGURATIONS = [
    (105, 10, "two_sided"),
    (105, 10, "lower"),
    (105, 10, "upper"),
    (300, 3, "two_sided"),
    (300, 3, "lower"),
    (300, 3, "upper"),
    (1000, 0, "two_sided"),
    (1000, 0, "lower"),
    (120, 30, "two_sided"),
    (120, 30, "lower"),
    (120, 30, "upper"),
]
_IDS = [f"m{m}_f{f}_{d}" for m, f, d in _CONFIGURATIONS]


class TestMonitorAgainstAnIndependentExactStepper:
    """Decision 18 item 1."""

    @pytest.mark.parametrize(("m", "f", "direction"), _CONFIGURATIONS, ids=_IDS)
    # Budget: 40 draws x <= 400 observations x ~25 us per Monitor.record
    # (measured) = 0.4 s, plus one fit per configuration (reference <= 0.53 s
    # at m=300 f=3 two-sided); x3 = 3 s. 120 s hard stop.
    @pytest.mark.timeout(120)
    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(
        failure_rate=st.one_of(
            st.sampled_from([0.0, 0.01, 0.05, 0.2, 0.5, 0.9, 1.0]),
            st.floats(min_value=0.0, max_value=1.0),
        ),
        uniforms=st.lists(
            st.floats(min_value=0.0, max_value=1.0, exclude_max=True),
            min_size=1,
            max_size=400,
        ),
    )
    def test_every_step_matches(
        self,
        m: int,
        f: int,
        direction: str,
        failure_rate: float,
        uniforms: list[float],
    ) -> None:
        chart, provenance = _chart(m, f, direction)
        sequence = [u < failure_rate for u in uniforms]

        _assert_monitor_matches_stepper(chart, provenance, sequence)

    @pytest.mark.parametrize(("m", "f", "direction"), _CONFIGURATIONS, ids=_IDS)
    @pytest.mark.parametrize("arm", ["lower", "upper"])
    def test_landing_exactly_on_h_is_in_control_and_the_next_step_signals(
        self, m: int, f: int, direction: str, arm: str
    ) -> None:
        """Decision 18 item 1: constructed sequences land each checked arm's
        statistic exactly on ``h_units`` (in control, strict ``>``), then take
        the one step that exceeds it (a failure for the lower arm, a success for
        the upper), which signals that arm.

        A floored lower arm (Decision 12: ``h_units < N - r_units``) has no
        in-control state at ``h`` -- its first failure jumps past it -- and that
        structural fact is asserted instead."""
        chart, provenance = _chart(m, f, direction)
        lower, upper = _lattices(chart)
        lattice = lower if arm == "lower" else upper
        if lattice is None:
            pytest.skip(f"direction {chart.direction!r} does not check the {arm} arm")
        n, r, h = lattice
        if arm == "lower" and h < n - r:
            assert _path_to_exactly_h(lower, upper, arm) is None
            return

        path = _path_to_exactly_h(lower, upper, arm)
        assert path is not None, f"no in-control path lands the {arm} arm on h={h}"
        overshoot = arm == "lower"  # a failure lifts the lower arm past h

        signal_step = _assert_monitor_matches_stepper(
            chart, provenance, [*path, overshoot]
        )

        assert signal_step == len(path) + 1

    def test_reviewers_sequence_stays_in_control_through_observation_139(
        self,
    ) -> None:
        """The pinned regression (Decision 18 item 1): today Monitor signals
        "upper" at observation 139. Under the ratified design (upper arm at
        ``p_L``, calibration D) the sequence never reaches ``h`` -- the
        independent reference gives lattices ``(5, 1, 21)``/``(20, 19, 78)`` and
        a final exact statistic of ``(0, 24)`` -- so it must stay in control
        throughout, step for step with the stepper."""
        chart, provenance = _chart(105, 10, "two_sided")
        assert len(_REVIEWER_SEQUENCE) == 139
        # First on Monitor alone, so the named defect (a float "upper" signal at
        # observation 139) is what fails, before any lattice is read.
        monitor = Monitor(chart, retain_history=False)
        for step, failed in enumerate(_REVIEWER_SEQUENCE, start=1):
            result = monitor.record(_observation(provenance, failed))
            assert result.is_in_control, (step, result.direction)

        assert (
            _assert_monitor_matches_stepper(chart, provenance, _REVIEWER_SEQUENCE)
            is None
        )


def _path_to_exactly_h(lower: Lattice, upper: Lattice, arm: str) -> list[bool] | None:
    """Breadth-first search over in-control states for the shortest sequence
    whose last step leaves ``arm``'s statistic exactly at its ``h_units``."""
    start: State = (0, 0)
    parents: dict[State, tuple[State, bool] | None] = {start: None}
    queue: deque[State] = deque([start])
    target_index = 0 if arm == "lower" else 1
    target = lower if arm == "lower" else upper
    assert target is not None
    while queue:
        state = queue.popleft()
        for failed in (True, False):
            nxt, exceeded = _exact_step(state, failed, lower, upper)
            if exceeded or nxt in parents:
                continue
            parents[nxt] = (state, failed)
            if nxt[target_index] == target[2]:
                path: list[bool] = []
                node: State = nxt
                while (link := parents[node]) is not None:
                    node, step_failed = link
                    path.append(step_failed)
                return path[::-1]
            queue.append(nxt)
    return None


# ===========================================================================
# Decision 18 item 11 -- the rebuilt artefact drives Monitor identically
# ===========================================================================


class TestSerialisedArtefactDrivesMonitorIdentically:
    @pytest.mark.parametrize("direction", ["two_sided", "lower", "upper"])
    def test_rebuilt_chart_matches_the_original_and_the_stepper(
        self, direction: str
    ) -> None:
        """Decision 14's reason for public integer fields: fit in one process,
        monitor in another, and lose nothing."""
        chart, provenance = _chart(300, 3, direction)
        rebuilt = FittedBernoulliCUSUM.model_validate_json(chart.model_dump_json())
        sequence = [index % 7 == 0 or index % 11 == 0 for index in range(1, 500)]

        original_signal = _assert_monitor_matches_stepper(chart, provenance, sequence)
        rebuilt_signal = _assert_monitor_matches_stepper(rebuilt, provenance, sequence)

        assert original_signal == rebuilt_signal


# ===========================================================================
# Decision 14.5 / M2 and corrigendum C4 -- lattices re-validated at use
# ===========================================================================


def _assert_statistics_untouched(monitor: Monitor) -> None:
    """Review 3, S3: "before any state changes" (Decision 14.5, C4) means the
    integer statistics too, not only the history. Both start at 0; a
    refusal that stepped first would have moved one of them."""
    assert monitor._bernoulli_s_lower == 0
    assert monitor._bernoulli_s_upper == 0


class _IntSubclass(int):
    """Not an exact ``int`` (Decision 14.1)."""


def _corrupted(
    chart: FittedBernoulliCUSUM, field: str, attribute: str, value: object
) -> FittedBernoulliCUSUM:
    lattice = chart.lattice_lower if field == "lattice_lower" else chart.lattice_upper
    assert lattice is not None
    bad_lattice: Any = lattice
    return chart.model_copy(
        update={field: bad_lattice.model_copy(update={attribute: value})}
    )


class TestMonitorRefusesAnUnknownDirection:
    """Review 3, R4: ``model_copy(update={"direction": "sideways"})`` passes
    ``require_exact_str`` (it is an exact ``str``), and ``Monitor`` then selects
    neither arm and reports in control forever -- a drift signal nobody
    receives, the failure this library exists to prevent. The ADR's M-rows do
    not name an unknown *value*; this follows M3's ``require_exact_str`` family
    and F8's unknown-string path: ``parameter="direction"``, ``kind="invalid"``,
    ``provided`` carrying the value (not ``provided_type``). Refusal may come at
    construction or at the first ``record()``; either satisfies the test. (The
    continuous CUSUM has the same defect; it is a separate ticket and is
    deliberately not tested here.)"""

    @pytest.mark.parametrize("direction", ["sideways", "", "Two_Sided"])
    def test_an_unrecognised_direction_is_refused(self, direction: str) -> None:
        """Today: accepted, and every observation reports in control."""
        chart, provenance = _chart(300, 3, "two_sided")
        corrupted = chart.model_copy(update={"direction": direction})

        with pytest.raises(InvalidParameterError) as excinfo:
            Monitor(corrupted).record(_observation(provenance, failed=True))

        context = excinfo.value.context
        assert context["parameter"] == "direction"
        assert context["kind"] == "invalid"
        assert context["provided"] == direction
        assert "constraint" in context
        assert "provided_type" not in context


class TestMonitorRevalidatesTheLattices:
    """Decision 14.5 (row M2) and C4, with C6/C12.2's ``provided``/
    ``provided_type`` split. ``model_copy(update=...)`` skips validation, which
    is exactly the route a caller-supplied artefact can take."""

    @pytest.mark.parametrize(
        ("field", "attribute", "value", "type_failure"),
        [
            ("lattice_upper", "reference_units", True, True),
            ("lattice_lower", "decision_interval_units", _IntSubclass(5), True),
            ("lattice_upper", "denominator", 17.0, True),
            ("lattice_lower", "reference_units", 0, False),
            ("lattice_upper", "decision_interval_units", 1_000_000, False),
            ("lattice_lower", "denominator", 1, False),
        ],
        ids=[
            "bool",
            "int_subclass",
            "float",
            "reference_units_zero",
            "h_above_cap",
            "denominator_below_2",
        ],
    )
    def test_a_bad_lattice_integer_raises_before_any_state_changes(
        self, field: str, attribute: str, value: object, type_failure: bool
    ) -> None:
        chart, provenance = _chart(300, 3, "two_sided")
        monitor = Monitor(_corrupted(chart, field, attribute, value))

        with pytest.raises(InvalidParameterError) as excinfo:
            monitor.record(_observation(provenance, failed=False))

        context = excinfo.value.context
        assert context["parameter"] == "artefact"
        assert context["kind"] == "invalid"
        assert context["field"] == f"{field}.{attribute}"
        assert "constraint" in context
        if type_failure:
            assert context["provided_type"] == type(value).__name__
            assert "provided" not in context
        else:
            assert context["provided"] == value
            assert "provided_type" not in context
        assert monitor.history == ()
        _assert_statistics_untouched(monitor)

    @pytest.mark.parametrize(
        ("direction", "missing"),
        [("two_sided", "lattice_upper"), ("two_sided", "lattice_lower")],
    )
    def test_a_checked_arm_without_a_lattice_raises(
        self, direction: str, missing: str
    ) -> None:
        """C4: never ``AttributeError``/``TypeError`` (BIN-121)."""
        chart, provenance = _chart(300, 3, direction)
        monitor = Monitor(chart.model_copy(update={missing: None}))
        # Record the observation that would move the arm that is still
        # present: a failure moves only the lower statistic and a success only
        # the upper one. Otherwise the "statistics untouched" check below could
        # not tell a refusal-before-stepping from a refusal-after-stepping.
        moves_the_present_arm = missing == "lattice_upper"

        with pytest.raises(InvalidParameterError) as excinfo:
            monitor.record(_observation(provenance, failed=moves_the_present_arm))

        context = excinfo.value.context
        assert context["parameter"] == "artefact"
        assert context["kind"] == "invalid"
        assert context["field"] == missing
        assert context["provided_type"] == "NoneType"
        assert "constraint" in context
        assert "provided" not in context
        assert monitor.history == ()
        _assert_statistics_untouched(monitor)
