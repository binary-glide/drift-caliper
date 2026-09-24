"""``fit_bernoulli_cusum`` -- fit a Bernoulli CUSUM from a binary pass/fail baseline.

BIN-133.

See ``docs/domain-model.md`` (Library Operations -- Fit Bernoulli CUSUM) and:

- ``docs/architecture/adr/012-bernoulli-chart-design-and-reference-value.md``
  -- the shift lever (``detect_rate_multiple``), the derived reference value,
  the sign convention (higher-is-better), two-sided-by-default, and why the
  lattice quantisation is reported honestly rather than chased.
- ``docs/architecture/adr/013-gicp-supersedes-the-provisional-baseline-floor.md``
  -- Guaranteed In-Control Performance: design at a confidence bound, not the
  plain point estimate; ``alpha = 0.10``; the ``expected_detection_arl``
  disclosure.
- ``docs/architecture/adr/014-bernoulli-cusum-api-surface-and-fitted-artefact-shape.md``
  -- the signature and validation order, and its two amendments: Amendment 1
  (Decisions 7-11: per-arm adaptive lattices, the independent-lattice joint
  chain, the caps) and Amendment 2 with its corrigendum (Decisions 12-19,
  C1-C12), which this module implements.

## Each arm is designed on its conservative side (Decision 19.1)

The lower (degradation-detecting) arm accumulates failures and is designed and
calibrated at ``p_u``, the Clopper-Pearson **upper** bound (ADR-013). The upper
(improvement-detecting) arm accumulates successes, so its in-control ARL
*falls* as the true failure rate falls; it is designed and calibrated at
``p_l``, the Clopper-Pearson **lower** bound. By the coupling argument in
Decision 19.1, each arm's in-control ARL at the true rate is then at least its
reported figure with probability at least ``1 - alpha``.

Both arms use ADR-012's reference value, on their own indicator:

    r = ln((1 - p0) / (1 - p1)) / ln( p1 (1 - p0) / (p0 (1 - p1)) )

the lower arm at ``(p0, p1) = (p_u, M p_u)`` on the failure indicator, the
upper arm at ``(1 - p_l, 1 - p_l / M)`` on the success indicator. ``p0 < r <
p1`` holds for every ``0 < p0 < p1 < 1`` (ADR-012's 2026-09-17 amendment
section 5).

## The integers are the chart (Decisions 7, 13 and 14)

Each arm lives on its own lattice ``1/N``, where ``N`` is the smallest
denominator placing ``round(r N) / N`` strictly inside ``(p0, p1)`` and within
``epsilon (p1 - p0)`` of ``r`` (Decision 7). :func:`_arm_lattice` finds it in
O(log N) by continued fractions, then walks forward applying Decision 7's test
exactly (corrigendum C12.4) -- the linear scan it replaces hung as
``detect_rate_multiple`` approached 1 and returned unchecked lattices at large
multiples. Every solver takes the resulting ``(N, r_units, h_units)`` integers
directly: nothing is ever rebuilt from a float (Decision 13.1), which is what
let a 1,474-state chain be handed to SuperLU as a 16.5-million-state one and
segfault (Amendment 2 section 0, defect 2).

## Exact ARLs from finite absorbing chains

An arm's statistic ``S = max(0, S + X - r)``, in integer units, moves up by
``N - r_units`` or down by ``r_units`` (floored at 0) and signals when it
**strictly** exceeds ``h_units`` (ADR-009 section 5 / BIN-112). Its ARL is the
expected absorption time of that finite chain, solved exactly from ``(I - Q) m
= 1``. The two-sided chart runs both arms off one draw per step, on the
Cartesian product of their lattices (Decision 8) -- never the continuous
chart's harmonic-combination approximation, which would reintroduce
approximation into the one property that justifies shipping this chart first
(ADR-012 sections 4-5; corrigendum C5 withdraws the fallback).

The two-sided ``achieved_arl`` is **B**, the exact run length of the *coupled*
chain driven by one uniform ``U`` per step: a failure for both arms when ``U <
p_l``, a failure for the lower arm and a success for the upper when ``p_l <= U
< p_u``, and a success for both otherwise (Decision 19.4). By coupling, ``B``
is at most the joint in-control ARL at every true rate in ``[p_l, p_u]`` -- a
guaranteed floor, not a plug-in estimate. **Calibration D** keeps the lower
arm at its equal-split design (per-arm target ``2T``) and gives the upper arm
the smallest interval with ``B >= T``.

## Postconditions on every reported number (BIN-140; Decision 13.4)

A near-singular solve can return a plausible, wrong value instead of failing.
Every solve here is checked -- finite, at least 1.0, and a solution vector of
exactly the chain's state count -- and a failed check yields
``_ILL_CONDITIONED_ARL_SENTINEL``. The sentinel may steer a calibration search
(it reads as "far above any target"), but it is **never** copied onto an
artefact: :func:`_reported_arl` raises ``DegenerateBaselineError(reason=
"arl_not_computable")`` instead (row F14), so a public entry point never
reports a number no solve produced.

References
----------
.. [1] Heidema, ... (2026). "The Poisson CUSUM Chart for Monitoring Small
       Counts: Addressing the Estimation Uncertainty." Biometrical Journal,
       open access, PMC13051258.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from drift_caliper.baseline.domain.baseline import Baseline
from drift_caliper.baseline.domain.bernoulli_arm_lattice import (
    MAX_DECISION_INTERVAL_UNITS,
    BernoulliArmLattice,
)
from drift_caliper.baseline.domain.clopper_pearson import (
    clopper_pearson_lower_bound,
    clopper_pearson_upper_bound,
)
from drift_caliper.baseline.domain.cusum_fitting import _validate_direction
from drift_caliper.baseline.domain.ewma_fitting import MAX_MEANINGFUL_ARL
from drift_caliper.baseline.domain.fitted_bernoulli_cusum import FittedBernoulliCUSUM
from drift_caliper.baseline.domain.fitting_advisory import FittingAdvisory
from drift_caliper.baseline.domain.parameter_guards import (
    _target_arl_constraint,
    require_real_number,
    require_target_arl_in_range,
    require_type,
)
from drift_caliper.baseline.domain.spc_numerics import baseline_scores
from drift_caliper.errors import (
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)

_CHART_TYPE = "bernoulli_cusum"
# Corrigendum C5: the two-sided string differs so an auditor can tell the
# coupled floor B apart from a pre-Amendment-2 two-sided figure.
_ONE_SIDED_CALIBRATION_METHOD = "gicp_markov_chain"
_TWO_SIDED_CALIBRATION_METHOD = "gicp_markov_chain_coupled_bound"

# ADR-013 section 3: the largest alpha that clears ADR-005's ratified <=5%
# baseline-adequacy appetite with real headroom. Fixed, not engineer-facing
# (ADR-014 Decision 5), and shared by both confidence bounds (Decision 19.1).
_ALPHA = 0.10

# ADR-012 section 1: 2.0 is the measured, largest-multiple-defined-across-
# the-whole-legal-domain default.
DEFAULT_DETECT_RATE_MULTIPLE = 2.0

# ADR-014 Amendment 1 Decision 7: the centring tolerance, measured (not
# picked) as the largest epsilon below the detection-penalty jump at 0.30.
_EPSILON = 0.25

# ADR-014 Amendment 1 Decision 10b: the joint two-sided state count cap,
# ~950 bytes per state of peak RSS. Read at call time, so tests can shrink it.
_MAX_JOINT_STATES = 1_000_000

# ADR-014 Amendment 2 Decision 13.3: `_MAX_JOINT_STATES - 1`, so no single
# solve, one-sided or joint, exceeds the joint budget. A module attribute read
# at call time (tests shrink it together with `_MAX_JOINT_STATES`); the
# lattice value object enforces the ratified value itself.
_MAX_DECISION_INTERVAL_UNITS = MAX_DECISION_INTERVAL_UNITS

_MIN_DECISION_INTERVAL_UNITS = 1

# E[N] >= 1 for any stopping time N on {1, 2, 3, ...}: the only lower bound
# on target_arl that transfers to an exact chart (ADR-014 Decision 3).
_MIN_COHERENT_ARL = 1.0

# BIN-140's sentinel, mirroring ewma_numerics._ILL_CONDITIONED_ARL_SENTINEL:
# far beyond any legal target, so a search reads it as "exceeds the target".
_ILL_CONDITIONED_ARL_SENTINEL = 1e15

# Keeps the reported `max_detect_rate_multiple` strictly below the point
# where `p_u * M` reaches 1.0, so it round-trips (BIN-122) -- an engineering
# floor on floating-point distinguishability, not a statistical constant.
_DESIGN_POINT_SAFETY_MARGIN = 1e-9

# Corrigendum C15.2: 2**53 = 1 / (the spacing of doubles just below 1), so
# the upper arm's design point 1 - p_l / M stays below 1 exactly when M <=
# p_l * 2**53.
_UPPER_ARM_CEILING_FACTOR = 2.0**53

# The exceptions that mean "this linear system has no usable solution in
# double precision" -- the ill-conditioning the sentinel stands for, and
# nothing else:
# - np.linalg.LinAlgError: numpy/scipy's own singular-matrix signal.
# - spla.MatrixRankWarning: what spsolve emits for an exactly singular matrix,
#   raised as an exception when a caller promotes warnings to errors.
# - ArithmeticError: FloatingPointError under a caller's np.errstate(all=
#   "raise"), plus ZeroDivisionError/OverflowError from the same arithmetic.
# SuperLU's exact-singularity RuntimeError is matched by message below,
# because RuntimeError itself is far broader than numerics.
_NUMERICAL_SOLVE_FAILURES = (
    np.linalg.LinAlgError,
    spla.MatrixRankWarning,
    ArithmeticError,
)
_SUPERLU_SINGULAR = "singular"

_ALL_FAILED_REASON = "all_baseline_judgements_failed"
_SCORE_NOT_BINARY_REASON = "score_not_binary"
_NO_BASELINE_FAILURES_REASON = "no_baseline_failures"
_JOINT_STATE_COUNT_EXCEEDED_REASON = "joint_state_count_exceeded"
_NO_SHIFT_REASON = "no_shift_to_detect"
_BELOW_RESOLUTION_REASON = "shift_below_numerical_resolution"
_NO_VALID_MULTIPLE_REASON = "no_valid_multiple"
_ARL_NOT_COMPUTABLE_REASON = "arl_not_computable"

_FLOORED_LOWER_ARM_ADVISORY = "lower_arm_signals_on_first_failure"
_DEGRADATION_WITHIN_DESIGN_RATE_ADVISORY = "detection_shift_within_design_rate"
_IMPROVEMENT_WITHIN_DESIGN_RATE_ADVISORY = "improvement_shift_within_design_rate"
_UPPER_ARM_NOT_DESIGNABLE_ADVISORY = "upper_arm_not_designable"

_LOWER = "lower"
_UPPER = "upper"
_TWO_SIDED = "two_sided"
_ARMS_CHECKED = {_LOWER: (_LOWER,), _UPPER: (_UPPER,), _TWO_SIDED: (_LOWER, _UPPER)}

_TARGET_ARL_CONSTRAINT = _target_arl_constraint(MAX_MEANINGFUL_ARL, _MIN_COHERENT_ARL)
_MULTIPLE_CONSTRAINT = (
    "must be a finite real number greater than 1 at which every arm the fit "
    "designs is constructible"
)

# (denominator, reference_units) -- an arm's lattice before calibration.
_ArmLattice = tuple[int, int]
# (denominator, reference_units, decision_interval_units) -- a calibrated arm.
_Arm = tuple[int, int, int]


# ===========================================================================
# Parameter validation
# ===========================================================================


def _require_bernoulli_target_arl(target_arl: float | None) -> float:
    """Validate ``target_arl``: required, a real number, finite, in ``[1, 10^6]``.

    Rows F3, F4 and F5. ADR-011's ``MIN_TARGET_ARL``/``VERIFIED_ARL_FLOOR``
    tiers do not apply (ADR-014 Decision 3): they disclose a gap between an
    approximation and the published table verifying it, and this chart's
    ARL0 is exact. What transfers is the coherence floor, 1.0. The ceiling is
    ``MAX_MEANINGFUL_ARL``, reused as a cost bound (Amendment 1 Decision 9).
    A target below what the chart can attain is *not* refused: the chart is
    fitted and disclosed instead (Decision 12).
    """
    if target_arl is None:
        raise InvalidParameterError(
            "target_arl is required to fit a Bernoulli CUSUM chart",
            context={
                "parameter": "target_arl",
                "constraint": _TARGET_ARL_CONSTRAINT,
                "kind": "missing",
            },
            recovery_hint=(
                "Specify target_arl explicitly -- the in-control ARL0 "
                "(false alarm tolerance) you want the fitted chart to "
                "achieve, e.g. 370 or 500. Caliper will not choose this on "
                "your behalf: it is a statistical commitment the engineer "
                "must own."
            ),
        )
    numeric = require_real_number(
        target_arl, parameter="target_arl", constraint=_TARGET_ARL_CONSTRAINT
    )
    require_target_arl_in_range(
        numeric,
        min_target_arl=_MIN_COHERENT_ARL,
        max_target_arl=MAX_MEANINGFUL_ARL,
        recovery_hint=(
            f"Choose a target_arl within [{_MIN_COHERENT_ARL}, "
            f"{MAX_MEANINGFUL_ARL}]. 1.0 is the floor for the expectation of "
            "any stopping time; the ceiling bounds the calibration's cost. "
            "The Bernoulli CUSUM's ARL0 is exact everywhere in between."
        ),
    )
    return numeric


def _require_finite_multiple(value: float | None) -> float:
    """Validate ``detect_rate_multiple``'s type and finiteness (rows F6, F7).

    Its lower bound depends on the baseline, so it is checked once the
    design rates are known (row F16, :func:`_require_constructible_multiple`).
    """
    if value is None:
        return DEFAULT_DETECT_RATE_MULTIPLE
    numeric = require_real_number(
        value, parameter="detect_rate_multiple", constraint=_MULTIPLE_CONSTRAINT
    )
    if not math.isfinite(numeric):
        raise InvalidParameterError(
            "detect_rate_multiple must be finite",
            context={
                "parameter": "detect_rate_multiple",
                "constraint": _MULTIPLE_CONSTRAINT,
                "kind": "invalid",
                "provided": numeric,
            },
            recovery_hint=(
                "Pass a finite detect_rate_multiple greater than 1, or omit "
                "it to use the library default "
                f"({DEFAULT_DETECT_RATE_MULTIPLE})."
            ),
        )
    return numeric


def _require_binary_scores(scores: Sequence[float], baseline: Baseline) -> None:
    """Reject a baseline containing a score that is not exactly ``0.0``/``1.0``.

    Row F2. Runs before every other value check (ADR-014 Decision 1), so an
    engineer sees this problem first whatever else is wrong with the call.
    ``provided`` is the ``Baseline`` passed -- the meaning ``require_type``
    gives this parameter in row F1.
    """
    for position, score in enumerate(scores):
        if score != 0.0 and score != 1.0:
            raise InvalidParameterError(
                "baseline contains a score that is not exactly 0.0 or 1.0",
                context={
                    "parameter": "baseline",
                    "constraint": (
                        "every observation's score must be exactly 0.0 or 1.0"
                    ),
                    "kind": "invalid",
                    "provided": baseline,
                    "reason": _SCORE_NOT_BINARY_REASON,
                    "invalid_score": score,
                    "position": position,
                },
                recovery_hint=(
                    "fit_bernoulli_cusum() is for a binary pass/fail rubric "
                    "-- every recorded score must be exactly 0.0 (fail) or "
                    "1.0 (pass). A baseline containing a continuous score "
                    "(even a legal one for every other chart type) cannot "
                    "be interpreted this way. Use fit_ewma()/fit_cusum()/"
                    "fit_shewhart() for a continuous-valued rubric instead."
                ),
            )


# ===========================================================================
# The reference value and the lattice (ADR-012 section 1; Decision 7; C12.4)
# ===========================================================================


def _bernoulli_reference_value(p0: float, p1: float) -> float:
    """ADR-012's reference value for detecting a rise from ``p0`` to ``p1``.

    ``r = ln((1-p0)/(1-p1)) / ln(p1 (1-p0) / (p0 (1-p1)))``, written with
    ``log1p`` so the ``1 - p`` terms keep their precision when ``p`` is tiny
    (a clean baseline's ``p_u``, or ``p_l``). Requires ``0 < p0 < p1 < 1``.

    ``nan`` when ``p0`` and ``p1`` are adjacent floats whose logarithms round
    to the same value: the design is then beyond double precision, and the
    ``nan`` fails every comparison the lattice finder makes.
    """
    u = math.log1p(-p0) - math.log1p(-p1)
    denominator = math.log(p1) - math.log(p0) + u
    return u / denominator if denominator > 0.0 else math.nan


def _simplest_rational(
    lo: Fraction, hi: Fraction | None, lo_open: bool, hi_open: bool
) -> Fraction:
    """Find the rational with the smallest denominator between ``lo`` and ``hi``.

    The classic continued-fraction (Stern-Brocot) construction, in exact
    arithmetic. ``hi`` of ``None`` means unbounded above; ``lo >= 0``, and
    ``lo < hi``. Each flag says whether that end is excluded.
    """
    floor_lo = math.floor(lo)
    candidate = floor_lo if (lo == floor_lo and not lo_open) else floor_lo + 1
    if hi is None or candidate < hi or (candidate == hi and not hi_open):
        return Fraction(candidate)
    new_lo = 1 / (hi - floor_lo)
    new_hi = None if lo == floor_lo else 1 / (lo - floor_lo)
    return floor_lo + 1 / _simplest_rational(new_lo, new_hi, hi_open, lo_open)


def _passes_decision_7(
    n: int, r: float, p0: float, p1: float, tolerance: float
) -> tuple[bool, int]:
    """Decision 7's ratified test at denominator ``n``, in double precision.

    ``k = round(r n)``, clamped to ``[1, n - 1]`` (``k = 0`` or ``k = n``
    would stop one direction of the statistic moving at all); it passes when
    ``k/n`` lies strictly inside ``(p0, p1)`` and within ``tolerance`` of
    ``r``.
    """
    k = min(n - 1, max(1, round(r * n)))
    return p0 < k / n < p1 and abs(k / n - r) <= tolerance, k


def _arm_lattice(p0: float, p1: float) -> _ArmLattice | None:
    """Decision 7's lattice for the arm designed on ``(p0, p1)``, or ``None``.

    Corrigendum C12.4's exact finder. Let ``J = [r - tol, r + tol]``
    intersected with ``(p0, p1)``. ``N_any``, the denominator of the simplest
    rational in ``J``, is the smallest ``N`` with *any* ``k/N`` in ``J``, so
    Decision 7's answer is at least ``N_any``; walk forward from it applying
    Decision 7's test. The walk is bounded by ``N_sym``, the simplest
    denominator in the symmetric interval of radius ``min(tol, r - p0, p1 -
    r)``, where the nearest numerator passes in exact arithmetic -- so it
    always terminates, and measured at most one step over 10,846 designs.

    Returns ``None`` when double precision cannot realise the design: ``r``
    does not land strictly inside ``(p0, p1)`` in floating point, or no ``N``
    up to ``N_sym`` passes the floating-point test. That is row F16's
    condition, never an exception. Corrigendum C12.1 measured it only just
    above ``detect_rate_multiple = 1``; it also occurs, rarely, at ordinary
    multiples on an upper arm whose ``1 - p_l`` sits within ~1e-8 of 1 (m =
    3,000,000, f = 1), where a design passing Decision 7 in exact arithmetic
    by a margin of 3e-9 of the tolerance fails it by a rounding.
    """
    r = _bernoulli_reference_value(p0, p1)
    if not p0 < r < p1:
        return None
    # With r strictly inside (p0, p1) and the tolerance positive, J is a
    # non-empty interval and the symmetric radius is positive.
    exact_r, exact_p0, exact_p1 = Fraction(r), Fraction(p0), Fraction(p1)
    tolerance = _EPSILON * (p1 - p0)
    exact_tolerance = Fraction(tolerance)
    lo, lo_open = (
        (exact_r - exact_tolerance, False)
        if exact_r - exact_tolerance > exact_p0
        else (exact_p0, True)
    )
    hi, hi_open = (
        (exact_r + exact_tolerance, False)
        if exact_r + exact_tolerance < exact_p1
        else (exact_p1, True)
    )
    radius = min(exact_tolerance, exact_r - exact_p0, exact_p1 - exact_r)
    n = max(2, _simplest_rational(lo, hi, lo_open, hi_open).denominator)
    n_sym = max(
        2,
        _simplest_rational(exact_r - radius, exact_r + radius, True, True).denominator,
    )
    while n <= n_sym:
        passes, k = _passes_decision_7(n, r, p0, p1, tolerance)
        if passes:
            return n, k
        n += 1
    return None


def _lower_arm_pair(p_u: float, multiple: float) -> tuple[float, float]:
    """Give the lower arm's ``(p0, p1)``, on the failure indicator (Decision 19.1)."""
    return p_u, p_u * multiple


def _upper_arm_pair(p_l: float, multiple: float) -> tuple[float, float]:
    """Give the upper arm's ``(q0, q1)``, on the success indicator (Decision 19.1)."""
    return 1.0 - p_l, 1.0 - p_l / multiple


def _designed_lattices(
    arms: Sequence[str], p_u: float, p_l: float, multiple: float
) -> dict[str, _ArmLattice] | None:
    """Find each designed arm's lattice at ``multiple``.

    ``None`` if any is not constructible in double precision (corrigendum
    C12.1: "every arm the fit designs").
    """
    lattices: dict[str, _ArmLattice] = {}
    for arm in arms:
        p0, p1 = (
            _lower_arm_pair(p_u, multiple)
            if arm == _LOWER
            else _upper_arm_pair(p_l, multiple)
        )
        lattice = _arm_lattice(p0, p1) if 0.0 < p0 < p1 < 1.0 else None
        if lattice is None:
            return None
        lattices[arm] = lattice
    return lattices


# ===========================================================================
# Exact ARLs on the integer lattices (ADR-012 section 4; Decisions 8, 19.4)
# ===========================================================================


def _solve_absorbing_chain(
    n_states: int,
    transitions: Sequence[tuple[float, npt.NDArray[np.int64]]],
) -> float:
    """Solve for the expected steps to absorption from state 0, with a postcondition.

    ``transitions`` pairs each outcome's probability with every state's
    destination under it, ``-1`` meaning absorbed. Solves ``(I - Q) m = 1``
    through ``scipy.sparse.linalg.spsolve``. Returns the sentinel when the
    solve fails *numerically*, returns something other than one value per
    state, or returns a value that is not finite or is below 1.0.

    Only numerical failures become the sentinel -- and so, if reported, row
    F14's "these legal inputs give a number double precision cannot
    represent". A ``MemoryError``, a ``KeyboardInterrupt``, a caller's
    timeout, or any other non-numerical exception says nothing about the
    chain and propagates as itself (ADR-002: Caliper does not relabel a
    failure it does not own).
    """
    sources = np.arange(n_states)
    rows: list[npt.NDArray[np.int64]] = []
    cols: list[npt.NDArray[np.int64]] = []
    data: list[npt.NDArray[np.float64]] = []
    for probability, destination in transitions:
        keep = destination >= 0
        rows.append(sources[keep])
        cols.append(destination[keep])
        data.append(np.full(int(np.count_nonzero(keep)), probability))
    # scipy.sparse/scipy.sparse.linalg have no type stubs mypy can see (the
    # same stub-coverage gap this module's `beta.ppf` callers work around).
    transient = sp.coo_matrix(  # type: ignore[no-untyped-call]
        (np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n_states, n_states),
    ).tocsc()
    system = (
        sp.identity(n_states, format="csc")  # type: ignore[no-untyped-call]
        - transient
    ).tocsc()
    try:
        steps = spla.spsolve(system, np.ones(n_states))  # type: ignore[no-untyped-call]
    except _NUMERICAL_SOLVE_FAILURES:
        return _ILL_CONDITIONED_ARL_SENTINEL
    except RuntimeError as error:
        # SuperLU reports an exactly singular factor as a bare RuntimeError
        # ("Factor is exactly singular"); every other RuntimeError is not a
        # statement about this chain and propagates as itself.
        if _SUPERLU_SINGULAR not in str(error):
            raise
        return _ILL_CONDITIONED_ARL_SENTINEL
    steps_array = np.asarray(steps).reshape(-1)
    if steps_array.shape[0] != n_states:
        return _ILL_CONDITIONED_ARL_SENTINEL
    value = float(steps_array[0])
    if not math.isfinite(value) or value < _MIN_COHERENT_ARL:
        return _ILL_CONDITIONED_ARL_SENTINEL
    return value


def _one_sided_arl0_in_units(up: int, down: int, n_transient: int, p: float) -> float:
    """Exact one-sided ARL on an integer lattice, from a statistic of 0.

    With probability ``p`` the statistic moves up ``up`` units, otherwise by
    ``down`` units (``down <= 0``), floored at 0. States ``0 .. n_transient -
    1`` are in control; reaching ``n_transient`` or beyond -- strictly
    exceeding ``h_units = n_transient - 1`` -- signals.
    """
    states = np.arange(n_transient)
    after_up = states + up
    after_up[after_up >= n_transient] = -1
    after_down = np.maximum(0, states + down)
    return _solve_absorbing_chain(n_transient, [(p, after_up), (1.0 - p, after_down)])


def _arm_arl(lattice: _ArmLattice, h_units: int, p_up: float) -> float:
    """One arm's exact ARL at interval ``h_units``, stepping up with ``p_up``.

    ``p_up`` is the failure rate for the lower arm and the success rate for
    the upper arm: each arm's statistic rises on the outcome it counts.
    """
    n, k = lattice
    return _one_sided_arl0_in_units(n - k, -k, h_units + 1, p_up)


def _coupled_arl_in_units(
    lower: _Arm, upper: _Arm, fail_both: float, fail_lower: float
) -> float:
    """Exact run length of both arms driven by one uniform ``U`` per step.

    ``U < fail_both`` is a failure for both arms; ``fail_both <= U <
    fail_lower`` a failure for the lower arm and a success for the upper;
    otherwise a success for both. State ``(i, j)`` holds each arm's integer
    statistic on its own lattice (Decision 8), ``(h_lo + 1)(h_up + 1)``
    states; either arm strictly exceeding its interval signals. With
    ``(fail_both, fail_lower) = (p_l, p_u)`` this is the coupled floor B
    (Decision 19.4); with both equal to one rate it is the ordinary joint
    chain at that rate.
    """
    (n_lo, k_lo, h_lo), (n_up, k_up, h_up) = lower, upper
    width = h_up + 1
    n_states = (h_lo + 1) * width
    i, j = np.divmod(np.arange(n_states), width)
    i_fail, i_success = i + (n_lo - k_lo), np.maximum(0, i - k_lo)
    j_fail, j_success = np.maximum(0, j - k_up), j + (n_up - k_up)

    def destination(
        i_next: npt.NDArray[np.int64], j_next: npt.NDArray[np.int64]
    ) -> npt.NDArray[np.int64]:
        state = i_next * width + j_next
        state[(i_next > h_lo) | (j_next > h_up)] = -1
        return state

    transitions = [(fail_both, destination(i_fail, j_fail))]
    if fail_lower > fail_both:
        transitions.append((fail_lower - fail_both, destination(i_fail, j_success)))
    transitions.append((1.0 - fail_lower, destination(i_success, j_success)))
    return _solve_absorbing_chain(n_states, transitions)


def _joint_two_sided_arl0_in_units(lower: _Arm, upper: _Arm, p: float) -> float:
    """Exact two-sided ARL of the joint chain at the single failure rate ``p``."""
    return _coupled_arl_in_units(lower, upper, p, p)


# ===========================================================================
# Calibration
# ===========================================================================


def _smallest_decision_interval_units(
    lattice: _ArmLattice, p_up: float, target: float, limit: int
) -> int | None:
    """Find the smallest ``h`` in ``[1, limit]`` whose ARL meets ``target``.

    ``limit >= 1``; ``None`` when even ``limit`` falls short. An arm's ARL
    is non-decreasing in ``h`` (a wider interval delays the stopping time on
    every path), so an exponential search then a bisection finds it. A sentinel from an
    ill-conditioned solve reads as "meets the target", steering the search
    without ever being reported.
    """
    lo, hi = 0, _MIN_DECISION_INTERVAL_UNITS
    while _arm_arl(lattice, hi, p_up) < target:
        if hi >= limit:
            return None
        lo, hi = hi, min(2 * hi, limit)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _arm_arl(lattice, mid, p_up) >= target:
            hi = mid
        else:
            lo = mid
    return hi


def _calibrate_one_sided_decision_interval_units(
    r_units: int, n: int, p: float, target: float, *, direction: str | None = None
) -> int:
    """Find the smallest ``h_units`` whose one-sided ARL meets ``target``, or raise F12.

    Searches up to ``_MAX_DECISION_INTERVAL_UNITS`` (Decision 13.3). Past it,
    raises with ``max_attainable_arl``, the arm's ARL at the cap: ARL is
    non-decreasing in ``h``, so that is the largest this arm can deliver, and
    it round-trips as a target (BIN-122). ``direction`` names the arm for
    the refusal's ``context`` (Decision 17, F12).
    """
    cap = _MAX_DECISION_INTERVAL_UNITS
    h_units = _smallest_decision_interval_units((n, r_units), p, target, cap)
    if h_units is not None:
        return h_units
    max_attainable = _arm_arl((n, r_units), cap, p)
    context: dict[str, object] = {
        "parameter": "target_arl",
        "constraint": (
            "the target ARL0 must be achievable within the decision interval "
            "search range"
        ),
        "kind": "invalid",
        "provided": target,
        "max_attainable_arl": max_attainable,
    }
    if direction is not None:
        context["direction"] = direction
    raise InvalidParameterError(
        "the one-sided calibration search exceeded its decision interval cap "
        "without reaching the requested ARL0",
        context=context,
        recovery_hint=(
            f"Reduce target_arl to at most {max_attainable}, the largest ARL0 "
            "this arm can deliver within the decision interval cap."
        ),
    )


class _TwoSidedCalibration(NamedTuple):
    """Calibration D's outcome: the intervals, or the state count refused."""

    intervals: tuple[int, int] | None
    joint_state_count: int


def _calibrate_two_sided(
    lower: _ArmLattice,
    upper: _ArmLattice,
    p_u: float,
    p_l: float,
    target: float,
) -> _TwoSidedCalibration:
    """Calibration D (Decision 19.4) within the joint cap (Decisions 10b, 16).

    The lower arm keeps its equal-split design, the smallest ``h_lo`` meeting
    ``2T`` at ``p_u``. The upper arm takes the smallest ``h_up`` with ``B >=
    T``: ``B`` is non-decreasing in ``h_up`` (coupling), and the equal-split
    ``h_up`` for ``2T`` is an upper bound on it, as is the largest ``h_up``
    the joint cap allows. A lower arm past its own search cap is over the
    joint cap whatever the upper arm is (Decision 16's proof), so it is the
    joint refusal, not F12.

    ``joint_state_count`` is the chart's state count when it fits, and a
    lower bound on the count D would need -- still over the cap -- when it
    does not (row F13).
    """
    joint_cap, arm_cap = _MAX_JOINT_STATES, _MAX_DECISION_INTERVAL_UNITS
    h_lo = _smallest_decision_interval_units(lower, p_u, 2.0 * target, arm_cap)
    if h_lo is None:
        return _TwoSidedCalibration(None, (arm_cap + 2) * 2)
    h_up_cap = joint_cap // (h_lo + 1) - 1
    refused = _TwoSidedCalibration(None, (h_lo + 1) * (h_up_cap + 2))
    if h_up_cap < _MIN_DECISION_INTERVAL_UNITS:
        return refused
    top = _smallest_decision_interval_units(
        upper, 1.0 - p_l, 2.0 * target, min(h_up_cap, arm_cap)
    )
    top = h_up_cap if top is None else top

    def bound_at(h_up: int) -> float:
        return _coupled_arl_in_units((*lower, h_lo), (*upper, h_up), p_l, p_u)

    if bound_at(top) < target:
        return refused
    lo, hi = 0, top
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if bound_at(mid) >= target:
            hi = mid
        else:
            lo = mid
    return _TwoSidedCalibration((h_lo, hi), (h_lo + 1) * (hi + 1))


# ===========================================================================
# max_two_sided_target_arl (corrigendum C11)
# ===========================================================================


def _equal_split_bound(
    lower: _ArmLattice, upper: _ArmLattice, p_u: float, p_l: float
) -> float:
    """``floor(T_ES)``, capped at ``MAX_MEANINGFUL_ARL`` -- corrigendum C11.

    ``T_ES = max over a >= 1 of min(A_lo(a), A_up(H(a))) / 2``, with ``H(a)
    = floor(cap / (a + 1)) - 1``: the largest two-sided target whose
    equal-split design fits the joint cap. ``A_lo`` is non-decreasing in
    ``a`` and ``A_up(H(a))`` non-increasing, so the maximum of their minimum
    sits at the crossing, found by bisection -- two one-sided solves per
    probe, no joint solve. A solve beyond double resolution reads as
    ``+inf`` (BIN-140's rule): it steers the search and is never reported.
    """
    joint_cap = _MAX_JOINT_STATES

    def finite_or_inf(value: float) -> float:
        return math.inf if value == _ILL_CONDITIONED_ARL_SENTINEL else value

    def lower_arl(a: int) -> float:
        return finite_or_inf(_arm_arl(lower, a, p_u))

    def upper_arl(a: int) -> float:
        return finite_or_inf(_arm_arl(upper, joint_cap // (a + 1) - 1, 1.0 - p_l))

    # Bisect for the crossing, keeping `lower_arl(lo) <= upper_arl(lo)` where
    # it holds. If it fails even at a = 1, every probe moves `hi` down and the
    # search ends at (1, 2), where the better of the two is a = 1 -- the
    # maximum, because the minimum is then `upper_arl`, non-increasing in a.
    lo, hi = 1, joint_cap // 2 - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if lower_arl(mid) <= upper_arl(mid):
            lo = mid
        else:
            hi = mid
    best = max(min(lower_arl(lo), upper_arl(lo)), min(lower_arl(hi), upper_arl(hi)))
    # `min` first, so two sides beyond double resolution report the ceiling.
    return float(math.floor(min(best / 2.0, MAX_MEANINGFUL_ARL)))


def _max_two_sided_target_arl(
    lower: _ArmLattice,
    upper: _ArmLattice,
    p_u: float,
    p_l: float,
    requested: float,
) -> float:
    """Report the largest two-sided ``target_arl`` this baseline fits (C11), verified.

    The equal-split bound is reported when **one** guard check confirms it:
    at that target the equal-split design fits the joint cap and its coupled
    floor ``B_ES`` meets the target. Calibration D then provably fits there
    too -- it keeps the equal-split lower arm and needs an upper interval no
    wider than the equal-split one -- so the value round-trips by
    construction. C11's premise that this always holds is measured, not
    proven, so if the guard ever fails the report falls back to the exact
    calibration-D maximum, found by bisection. The report is never an
    unverified number.
    """
    bound = _equal_split_bound(lower, upper, p_u, p_l)
    arm_cap = _MAX_DECISION_INTERVAL_UNITS
    h_lo = _smallest_decision_interval_units(lower, p_u, 2.0 * bound, arm_cap)
    h_up = _smallest_decision_interval_units(upper, 1.0 - p_l, 2.0 * bound, arm_cap)
    if (
        bound >= _MIN_COHERENT_ARL
        and h_lo is not None
        and h_up is not None
        and (h_lo + 1) * (h_up + 1) <= _MAX_JOINT_STATES
        and _coupled_arl_in_units((*lower, h_lo), (*upper, h_up), p_l, p_u) >= bound
    ):
        return bound

    def fits(target: float) -> bool:
        return (
            _calibrate_two_sided(lower, upper, p_u, p_l, target).intervals is not None
        )

    # Target 1.0 always fits: B >= 1 for any chain, and a per-arm target of 2
    # needs only a handful of units on the lower arm.
    lo, hi = 1, math.floor(requested) + 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if fits(float(mid)):
            lo = mid
        else:
            hi = mid
    return float(lo)


# ===========================================================================
# detect_rate_multiple's lower bound (corrigendum C2, C12.1; row F16)
# ===========================================================================


def _max_multiple(arms: Sequence[str], p_u: float, p_l: float) -> float:
    """Give ``C``, the largest ``detect_rate_multiple`` every designed arm can take.

    Corrigendum C15.2: the smaller of F11's ``(1 - 1e-9) / p_u`` when the
    lower arm is designed (its design point ``p_u * M`` must stay below 1) and
    ``U = p_l * 2**53`` when the upper arm is designed. ``2**-53`` is the
    spacing of doubles just below 1, so the upper design point ``1 - p_l /
    M`` is representable strictly below 1 exactly when ``M <= U``. Every
    fit designs at least one arm, so ``C`` is always finite.
    """
    ceilings = []
    if _LOWER in arms:
        ceilings.append((1.0 - _DESIGN_POINT_SAFETY_MARGIN) / p_u)
    if _UPPER in arms:
        ceilings.append(p_l * _UPPER_ARM_CEILING_FACTOR)
    return min(ceilings)


def _nearest_constructible_multiple(
    arms: Sequence[str], p_u: float, p_l: float, requested: float
) -> float | None:
    """Find the nearest constructible multiple at or above ``requested``.

    Corrigendum C12.1. Starting from the refused request (or 1, when the
    request is at most 1), step upward by one float spacing, doubling the
    step until a multiple is constructible; then bisect between that
    multiple and the last refused one until the two are adjacent floats. The
    result is constructible and the float just below it is not, so it
    round-trips and moves the engineer's request by the least the arithmetic
    allows.

    Not C12.1's fixed anchor at 2 (corrigendum C14): a bracket ``[request,
    2]`` cannot hold a request at or above 2, and non-constructible multiples
    do occur there -- at m = 3,000,000 f = 1, ``"upper"`` is refused at M ~
    4.1957. The search is capped at the ceiling ``C`` (C15.2), so it always
    terminates: the step at least doubles each time, reaching ``C`` within
    about 1,100 doublings, and the bisection halves a bracket of doubles.
    ``None`` when nothing in ``(requested, C]`` is constructible
    (``"no_valid_multiple"``; measured unreachable, C15.2).
    """
    refused = max(requested, 1.0)
    ceiling = _max_multiple(arms, p_u, p_l)
    step = math.ulp(refused)
    while True:
        candidate = min(refused + step, ceiling)
        if _designed_lattices(arms, p_u, p_l, candidate) is not None:
            break
        if candidate >= ceiling:
            return None
        refused = candidate
        step *= 2.0
    while True:
        mid = refused + (candidate - refused) / 2.0
        if mid <= refused or mid >= candidate:
            return candidate
        if _designed_lattices(arms, p_u, p_l, mid) is None:
            refused = mid
        else:
            candidate = mid


def _require_constructible_multiple(
    multiple: float, arms: Sequence[str], p_u: float, p_l: float
) -> dict[str, _ArmLattice]:
    """Rows F11 and F16: ``multiple`` must give every designed arm a lattice.

    F16 fires when ``multiple <= 1`` (no shift to detect: ``p1 = p0``, and
    below 1 the arms would be mislabelled) or when some designed arm is not
    constructible at the multiple the caller passed (corrigendum C12.1).
    F11 fires when a designed arm has no representable design point: the
    lower arm's ``p_u * multiple`` is not below 1, or (C15.2) the upper arm's
    ``1 - p_l / multiple`` rounds to 1, i.e. ``multiple`` exceeds ``U = p_l *
    2**53``. Its ``max_detect_rate_multiple`` is the ceiling ``C`` over the
    designed arms, which round-trips. Returns the designed arms' lattices.
    """
    if multiple <= 1.0:
        raise _multiple_refusal(multiple, _NO_SHIFT_REASON, arms, p_u, p_l)
    lower_unrepresentable = _LOWER in arms and p_u * multiple >= 1.0
    upper_unrepresentable = (
        _UPPER in arms and multiple > p_l * _UPPER_ARM_CEILING_FACTOR
    )
    if lower_unrepresentable or upper_unrepresentable:
        max_multiple = _max_multiple(arms, p_u, p_l)
        raise InvalidParameterError(
            "detect_rate_multiple implies a design point that is not a "
            "valid probability",
            context={
                "parameter": "detect_rate_multiple",
                "constraint": (
                    "p_u * detect_rate_multiple must be strictly less than 1.0, "
                    "and 1 - p_l / detect_rate_multiple strictly less than 1.0 "
                    "in double precision"
                ),
                "kind": "invalid",
                "provided": multiple,
                "max_detect_rate_multiple": max_multiple,
            },
            recovery_hint=(
                "The requested detect_rate_multiple is too large for this "
                "baseline: applied to p_u it implies a failure rate of 1.0 or "
                "higher, or applied to p_l it implies an improved failure "
                "rate too small to represent. The largest value this "
                "baseline supports is "
                f"reported in context['max_detect_rate_multiple'] "
                f"({max_multiple}); pass that value, or a smaller one."
            ),
        )
    lattices = _designed_lattices(arms, p_u, p_l, multiple)
    if lattices is None:
        raise _multiple_refusal(multiple, _BELOW_RESOLUTION_REASON, arms, p_u, p_l)
    return lattices


def _multiple_refusal(
    multiple: float, reason: str, arms: Sequence[str], p_u: float, p_l: float
) -> InvalidParameterError:
    """Row F16, with ``min_value`` -- or ``"no_valid_multiple"`` without one."""
    minimum = _nearest_constructible_multiple(arms, p_u, p_l, multiple)
    context: dict[str, object] = {
        "parameter": "detect_rate_multiple",
        "constraint": _MULTIPLE_CONSTRAINT,
        "kind": "invalid",
        "provided": multiple,
    }
    if minimum is None:
        context["reason"] = _NO_VALID_MULTIPLE_REASON
        hint = (
            "No detect_rate_multiple at or above the one requested gives this "
            "baseline a constructible design. Pass a smaller "
            "detect_rate_multiple."
        )
    else:
        context.update(reason=reason, min_value=minimum, min_inclusive=True)
        hint = (
            "Pass a detect_rate_multiple of at least "
            f"context['min_value'] ({minimum}). A multiple of 1 detects no "
            "shift, and one just above 1 describes a shift too small to "
            "represent in double precision."
        )
    return InvalidParameterError(
        "detect_rate_multiple does not describe a detectable, constructible shift",
        context=context,
        recovery_hint=hint,
    )


# ===========================================================================
# Reporting
# ===========================================================================


def _reported_arl(value: float, figure: str) -> float:
    """Decision 13.4's raising postcondition on a number copied to the artefact.

    The solver's own check has already replaced a non-finite, sub-1.0 or
    wrongly-sized solution with the sentinel, so the sentinel is the one
    value to refuse here -- but every condition is restated, so this guard
    does not depend on how the solver signals trouble. Row F14.
    """
    if (
        math.isfinite(value)
        and value >= _MIN_COHERENT_ARL
        and value != _ILL_CONDITIONED_ARL_SENTINEL
    ):
        return value
    raise DegenerateBaselineError(
        f"the Bernoulli CUSUM's {figure} could not be computed to double precision",
        context={
            "reason": _ARL_NOT_COMPUTABLE_REASON,
            "chart_type": _CHART_TYPE,
            "figure": figure,
        },
        recovery_hint=(
            "The inputs are legal, but the exact Markov-chain solve for this "
            "figure did not produce a representable run length. Try a "
            "smaller target_arl or a larger detect_rate_multiple, which "
            "shrink the chain."
        ),
    )


def _floor_advisory(p_u: float) -> FittingAdvisory:
    """Decision 12's disclosure: every single failure signals.

    The boundary is the lower arm's exact ARL0 at ``h_units = 1``, which is
    ``1/p_u`` exactly: while ``h < N - r_units`` one failure lifts the
    statistic past ``h`` from anywhere and a success returns it to 0, so the
    run length is geometric with mean ``1/p``, on any lattice. No lower-arm
    Bernoulli CUSUM on this baseline has a smaller in-control ARL.
    """
    boundary = 1.0 / p_u
    return FittingAdvisory(
        kind=_FLOORED_LOWER_ARM_ADVISORY,
        description=(
            "The lower arm signals on the first failure it sees: its decision "
            "interval is below one failure's step, so its in-control ARL0 is "
            f"{boundary}, the mean wait for one failure at this baseline's "
            "conservative failure rate p_u. No detect_rate_multiple, "
            "direction or lattice can lower it; achieved_arl is reported "
            "exactly beside requested_arl."
        ),
        boundary=boundary,
    )


def _not_designable_advisory() -> FittingAdvisory:
    """Decision 19.2's disclosure: a two-sided request met zero failures."""
    return FittingAdvisory(
        kind=_UPPER_ARM_NOT_DESIGNABLE_ADVISORY,
        description=(
            "The baseline has no failed judgements, so there is no failure "
            "rate to detect an improvement from: only the lower "
            "(degradation) arm was built, and direction is reported as "
            "'lower'. The improvement arm can be designed once the baseline "
            "has at least one failure."
        ),
        boundary=1.0,
    )


class _ShiftsWithinDesignRate(NamedTuple):
    """Corrigendum C13's disclosures: which figures describe no shift.

    Each is the advisory to attach -- and the signal to report the figure as
    ``None`` without solving it -- or ``None`` when the figure is reported.
    """

    degradation: FittingAdvisory | None
    improvement: FittingAdvisory | None

    @classmethod
    def of(
        cls,
        arms: Sequence[str],
        f: int,
        p_hat: float,
        multiple: float,
        p_u: float,
        p_l: float,
    ) -> _ShiftsWithinDesignRate:
        """Decide both conditions from the inputs alone, before any solve.

        The lower arm's run length can only fall as the failure rate rises,
        and the upper arm's only as it falls (Decision 19.1's coupling), so a
        shifted rate at or inside the arm's design rate gives a run length
        no shorter than the chart's own false-alarm figure: it describes no
        detection, and can be beyond double resolution. The degradation
        condition is ``p_hat * M <= p_u`` with ``f >= 1`` (at f = 0 the
        figure is taken at ``p_u * M``, always outside); the improvement
        condition is ``p_hat / M >= p_l``. Each is tested as ``M <=
        boundary``, against the very ``boundary`` the advisory reports, so
        the advisory's promise -- any strictly larger multiple reports the
        figure -- holds exactly, with no rounding between the two.
        """
        degradation = improvement = None
        if f >= 1 and _LOWER in arms:
            boundary = p_u / p_hat
            if multiple <= boundary:
                degradation = _no_shift_advisory(
                    _DEGRADATION_WITHIN_DESIGN_RATE_ADVISORY, boundary
                )
        if f >= 1 and _UPPER in arms:
            boundary = p_hat / p_l
            if multiple <= boundary:
                improvement = _no_shift_advisory(
                    _IMPROVEMENT_WITHIN_DESIGN_RATE_ADVISORY, boundary
                )
        return cls(degradation, improvement)


def _no_shift_advisory(kind: str, boundary: float) -> FittingAdvisory:
    """Corrigendum C13's disclosure for a figure reported as ``None``."""
    shift, design_bound = (
        ("a degradation of", "p_u")
        if kind == _DEGRADATION_WITHIN_DESIGN_RATE_ADVISORY
        else ("an improvement of", "p_l")
    )
    return FittingAdvisory(
        kind=kind,
        description=(
            f"The detection figure for {shift} detect_rate_multiple from the "
            f"observed failure rate is not reported: that shifted rate lies at "
            f"or inside the rate this arm is designed to tolerate ({design_bound}), "
            "so the chart would take at least as long to signal it as to raise "
            "a false alarm. The chart itself is valid. The figure appears once "
            "the baseline contains more failures -- the gap between the "
            "observed rate and its confidence bound depends on the failure "
            "count, not the baseline's size -- or with a detect_rate_multiple "
            f"strictly above {boundary} (this advisory's boundary)."
        ),
        boundary=boundary,
    )


class _Design(NamedTuple):
    """Every number a fit derives from the baseline before building the artefact."""

    direction: str
    lattice_lower: BernoulliArmLattice | None
    lattice_upper: BernoulliArmLattice | None
    achieved_arl: float
    expected_detection_arl: float | None
    expected_improvement_detection_arl: float | None


def _to_lattice(arm: _ArmLattice, h_units: int) -> BernoulliArmLattice:
    n, k = arm
    return BernoulliArmLattice(
        denominator=n, reference_units=k, decision_interval_units=h_units
    )


def _one_sided_design(
    direction: str,
    arm: _ArmLattice,
    in_control_up: float,
    detection_up: float,
    target: float,
    *,
    detection_within_design_rate: bool,
) -> _Design:
    """Calibrate the one checked arm and report its figures (C3, C13).

    The detection figure is not solved at all when its shifted rate lies
    within the design rate (corrigendum C13).
    """
    n, k = arm
    h = _calibrate_one_sided_decision_interval_units(
        k, n, in_control_up, target, direction=direction
    )
    achieved = _reported_arl(_arm_arl(arm, h, in_control_up), "achieved_arl")
    detection = (
        None
        if detection_within_design_rate
        else _reported_arl(_arm_arl(arm, h, detection_up), "expected_detection_arl")
    )
    lattice = _to_lattice(arm, h)
    return _Design(
        direction=direction,
        lattice_lower=lattice if direction == _LOWER else None,
        lattice_upper=lattice if direction == _UPPER else None,
        achieved_arl=achieved,
        expected_detection_arl=detection,
        expected_improvement_detection_arl=None,
    )


def _two_sided_design(
    lower: _ArmLattice,
    upper: _ArmLattice,
    p_u: float,
    p_l: float,
    p_hat: float,
    multiple: float,
    target: float,
    *,
    within_design_rate: tuple[bool, bool],
) -> _Design:
    """Calibration D, or row F13 with C11's round-tripping bound.

    ``within_design_rate`` is C13's ``(degradation, improvement)`` pair: a
    figure whose shifted rate lies within the design rate is not solved.
    """
    degradation_within, improvement_within = within_design_rate
    calibration = _calibrate_two_sided(lower, upper, p_u, p_l, target)
    if calibration.intervals is None:
        maximum = _max_two_sided_target_arl(lower, upper, p_u, p_l, target)
        raise InvalidParameterError(
            "the two-sided fit exceeds the joint state count cap",
            context={
                "parameter": "target_arl",
                "constraint": (
                    "the two-sided joint state count must not exceed max_joint_states"
                ),
                "kind": "invalid",
                "provided": target,
                "reason": _JOINT_STATE_COUNT_EXCEEDED_REASON,
                "joint_state_count": calibration.joint_state_count,
                "max_joint_states": _MAX_JOINT_STATES,
                "max_two_sided_target_arl": maximum,
            },
            recovery_hint=(
                f"Reduce target_arl to at most {maximum} for a two-sided fit "
                "at this baseline, increase detect_rate_multiple (which "
                "shortens both arms' decision intervals), or use "
                "direction='lower' or direction='upper' to avoid the joint "
                "chain entirely."
            ),
        )
    h_lo, h_up = calibration.intervals
    lower_arm, upper_arm = (*lower, h_lo), (*upper, h_up)
    achieved = _reported_arl(
        _coupled_arl_in_units(lower_arm, upper_arm, p_l, p_u), "achieved_arl"
    )
    detection = (
        None
        if degradation_within
        else _reported_arl(
            _joint_two_sided_arl0_in_units(lower_arm, upper_arm, p_hat * multiple),
            "expected_detection_arl",
        )
    )
    improvement = (
        None
        if improvement_within
        else _reported_arl(
            _joint_two_sided_arl0_in_units(lower_arm, upper_arm, p_hat / multiple),
            "expected_improvement_detection_arl",
        )
    )
    return _Design(
        direction=_TWO_SIDED,
        lattice_lower=_to_lattice(lower, h_lo),
        lattice_upper=_to_lattice(upper, h_up),
        achieved_arl=achieved,
        expected_detection_arl=detection,
        expected_improvement_detection_arl=improvement,
    )


def _is_floored(lattice: BernoulliArmLattice | None) -> bool:
    """Decision 12's integer test: one failure's step already exceeds ``h``."""
    return lattice is not None and (
        lattice.decision_interval_units < lattice.denominator - lattice.reference_units
    )


# ===========================================================================
# Public API
# ===========================================================================


def fit_bernoulli_cusum(
    baseline: Baseline,
    *,
    target_arl: float | None = None,
    detect_rate_multiple: float | None = None,
    direction: str | None = None,
) -> FittedBernoulliCUSUM:
    """Fit a Bernoulli CUSUM from ``baseline``, a binary pass/fail rubric (BIN-133).

    Validates ``baseline``'s type and that every recorded score is exactly
    ``0.0`` or ``1.0``; then ``target_arl``, ``detect_rate_multiple``'s type
    and ``direction``; then ADR-005's 100-observation floor. It designs each
    checked arm at its conservative confidence bound -- the lower arm at
    ``p_u``, the upper at ``p_l`` -- on an exact integer lattice, and
    calibrates it by an exact Markov-chain solve (see the module docstring).

    Parameters
    ----------
    baseline
        The Phase I baseline -- every recorded ``ScoringResult.score`` must be
        exactly ``0.0`` (fail) or ``1.0`` (pass).
    target_arl
        The target in-control ARL0 (false alarm tolerance), in ``[1.0,
        1,000,000]``. Optional in the signature, required by validation.
        Unlike the continuous charts, ADR-011's ``[100, 370)`` tiering does
        not apply: this chart's ARL0 is exact. A target below what the chart
        can attain is fitted, not refused -- ``achieved_arl`` is reported
        beside it, and a floored lower arm carries a
        ``"lower_arm_signals_on_first_failure"`` advisory (ADR-014 Decision
        12).
    detect_rate_multiple
        The shift lever *M*: the lower arm detects a failure rate of ``M *
        p_u``, the upper arm one of ``p_l / M``. Must be finite and greater
        than 1. ``None`` uses ``DEFAULT_DETECT_RATE_MULTIPLE`` (``2.0``).
    direction
        ``"two_sided"`` (default), ``"lower"`` or ``"upper"``. Only the arms
        ``direction`` checks are designed and carried. On a baseline with no
        failures a two-sided request builds the lower arm alone, reports
        ``direction == "lower"`` and carries an ``"upper_arm_not_designable"``
        advisory; ``"upper"`` is refused there.

    Returns
    -------
    FittedBernoulliCUSUM
        The fitted artefact. Satisfies ``HasProvenance`` only, not
        ``FittedControlLimits`` (ADR-014 Decision 6a). ``achieved_arl >=
        requested_arl`` always.

    Raises
    ------
    InvalidParameterError
        ``baseline`` is not a ``Baseline``, or holds a score that is not
        exactly ``0.0``/``1.0`` (``reason == "score_not_binary"``);
        ``target_arl`` is missing, not a number, or outside ``[1.0,
        1,000,000]``; ``detect_rate_multiple`` is not a finite number, is at
        most 1 (``reason == "no_shift_to_detect"``), or is too close to 1 for
        double precision to build the design (``reason ==
        "shift_below_numerical_resolution"``) -- both with a round-tripping
        ``min_value``; ``p_u * detect_rate_multiple >= 1``
        (``max_detect_rate_multiple``); ``direction`` is not recognised, or is
        ``"upper"`` on a baseline with no failures (``reason ==
        "no_baseline_failures"``); every judgement failed (``reason ==
        "all_baseline_judgements_failed"``); a one-sided target is beyond the
        decision interval cap (``max_attainable_arl``); or a two-sided target
        exceeds the joint state count cap (``reason ==
        "joint_state_count_exceeded"``, ``max_two_sided_target_arl``). Every
        reported bound round-trips as an accepted input.
    InsufficientBaselineError
        ``baseline`` has fewer than ADR-005's 100 observations.
    DegenerateBaselineError
        A reported ARL could not be computed to double precision (``reason
        == "arl_not_computable"``, with ``figure``). A guard: no measured
        input reaches it (ADR-014 Decision 13.4).
    """
    baseline = require_type(
        baseline, Baseline, parameter="baseline", type_name="Baseline"
    )
    scores = baseline_scores(baseline.observations)
    _require_binary_scores(scores, baseline)
    validated_target_arl = _require_bernoulli_target_arl(target_arl)
    multiple = _require_finite_multiple(detect_rate_multiple)
    requested_direction = _validate_direction(direction)

    sufficiency = baseline.check_sufficiency()
    if not sufficiency.is_sufficient:
        raise InsufficientBaselineError(
            "baseline does not have enough observations to fit a Bernoulli "
            "CUSUM chart reliably",
            context={
                "have": sufficiency.observation_count,
                "need": sufficiency.threshold,
            },
            recovery_hint=(
                "Collect more observations before fitting -- record at "
                f"least {sufficiency.gap} more scoring results with "
                "Baseline.record() to reach the sufficiency threshold."
            ),
        )

    m = len(scores)
    f = scores.count(0.0)
    _require_designable_baseline(m, f, multiple, requested_direction)

    not_designable = requested_direction == _TWO_SIDED and f == 0
    effective_direction = _LOWER if not_designable else requested_direction

    p_hat = f / m
    p_u = clopper_pearson_upper_bound(failures=f, observations=m, alpha=_ALPHA)
    p_l = clopper_pearson_lower_bound(failures=f, observations=m, alpha=_ALPHA)
    arms = _ARMS_CHECKED[effective_direction]
    lattices = _require_constructible_multiple(multiple, arms, p_u, p_l)
    shifts = _ShiftsWithinDesignRate.of(arms, f, p_hat, multiple, p_u, p_l)

    if effective_direction == _LOWER:
        design = _one_sided_design(
            _LOWER,
            lattices[_LOWER],
            p_u,
            (p_hat if f > 0 else p_u) * multiple,
            validated_target_arl,
            detection_within_design_rate=shifts.degradation is not None,
        )
    elif effective_direction == _UPPER:
        design = _one_sided_design(
            _UPPER,
            lattices[_UPPER],
            1.0 - p_l,
            1.0 - p_hat / multiple,
            validated_target_arl,
            detection_within_design_rate=shifts.improvement is not None,
        )
    else:
        design = _two_sided_design(
            lattices[_LOWER],
            lattices[_UPPER],
            p_u,
            p_l,
            p_hat,
            multiple,
            validated_target_arl,
            within_design_rate=(
                shifts.degradation is not None,
                shifts.improvement is not None,
            ),
        )
    # C13 point 3's order: the floor, the no-shift disclosures, then
    # upper_arm_not_designable.
    advisories = [
        advisory
        for advisory in (
            _floor_advisory(p_u) if _is_floored(design.lattice_lower) else None,
            shifts.degradation,
            shifts.improvement,
            _not_designable_advisory() if not_designable else None,
        )
        if advisory is not None
    ]

    provenance = baseline.provenance_signature
    if provenance is None:  # pragma: no cover
        # Unreachable: sufficiency requires observation_count >= threshold
        # > 0, and Baseline sets provenance_signature on its first recorded
        # observation -- an internal invariant, not a CaliperError path.
        raise RuntimeError(
            "fit_bernoulli_cusum invariant violation: a sufficient baseline "
            "has no provenance signature"
        )

    return FittedBernoulliCUSUM(
        chart_type=_CHART_TYPE,
        observed_failure_rate=p_hat,
        observation_count=m,
        provenance_model_version=provenance.model_version.value,
        provenance_criteria=provenance.scoring_criteria.value,
        requested_arl=validated_target_arl,
        achieved_arl=design.achieved_arl,
        expected_detection_arl=design.expected_detection_arl,
        expected_improvement_detection_arl=design.expected_improvement_detection_arl,
        calibration_method=(
            _TWO_SIDED_CALIBRATION_METHOD
            if design.direction == _TWO_SIDED
            else _ONE_SIDED_CALIBRATION_METHOD
        ),
        advisories=tuple(advisories),
        detect_rate_multiple=multiple,
        alpha=_ALPHA,
        p_u=p_u,
        p_l=p_l,
        direction=design.direction,
        lattice_lower=design.lattice_lower,
        lattice_upper=design.lattice_upper,
    )


def _require_designable_baseline(
    m: int, f: int, multiple: float, direction: str
) -> None:
    """Rows F10 and F15: the baseline has the outcome each checked arm needs."""
    if f == m:
        raise InvalidParameterError(
            "no valid detection design exists for a baseline with no "
            "passing judgements",
            context={
                "parameter": "detect_rate_multiple",
                "constraint": "the implied design point must be a valid probability",
                "kind": "invalid",
                "reason": _ALL_FAILED_REASON,
                "provided": multiple,
            },
            recovery_hint=(
                "Every judgement in this baseline failed, so there is no "
                "observed passing rate to design a detection sensitivity "
                "against. Collect a baseline with at least one passing "
                "judgement before fitting."
            ),
        )
    if f == 0 and direction == _UPPER:
        raise InvalidParameterError(
            "an improvement-only chart needs at least one failed judgement",
            context={
                "parameter": "direction",
                "constraint": (
                    "'upper' requires at least one failed judgement in the baseline"
                ),
                "kind": "invalid",
                "provided": direction,
                "reason": _NO_BASELINE_FAILURES_REASON,
            },
            recovery_hint=(
                "This baseline has no failures, so there is no failure rate "
                "for an improvement to fall from. Use direction='lower' or "
                "'two_sided' (which builds the lower arm alone here), or "
                "collect a baseline with at least one failure."
            ),
        )


__all__ = [
    "DEFAULT_DETECT_RATE_MULTIPLE",
    "fit_bernoulli_cusum",
]
