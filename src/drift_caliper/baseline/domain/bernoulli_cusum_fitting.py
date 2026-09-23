"""``fit_bernoulli_cusum`` -- fit a Bernoulli CUSUM from a binary pass/fail baseline.

BIN-133.

See ``docs/domain-model.md`` (Library Operations -- Fit Bernoulli CUSUM) and:

- ``docs/architecture/adr/012-bernoulli-chart-design-and-reference-value.md``
  -- the shift lever (``detect_rate_multiple``), the derived reference value,
  the sign convention (higher-is-better), two-sided-by-default, and why the
  lattice quantisation is reported honestly rather than chased.
- ``docs/architecture/adr/013-gicp-supersedes-the-provisional-baseline-floor.md``
  -- Guaranteed In-Control Performance: design at ``p_U`` (the Clopper-Pearson
  upper confidence bound), not the plain point estimate; ``alpha = 0.10``; the
  ``expected_detection_arl`` disclosure; the ``p_hat=0``/``p_hat=1`` handling.
- ``docs/architecture/adr/014-bernoulli-cusum-api-surface-and-fitted-artefact-shape.md``
  -- the concrete Python signature, the validation order, and the exact joint
  two-armed Markov-chain construction (section 6c) this module implements.

## The reference value

For a test of ``H0: p = p0`` against ``H1: p = p1`` (``p1 > p0``), one
Bernoulli observation ``X`` contributes a log-likelihood ratio whose
``X``-coefficient, rescaled, gives a reference value

    r = ln((1 - p0) / (1 - p1)) / ln( p1 * (1 - p0) / (p0 * (1 - p1)) )

with ``p0 < r < p1`` provable for every ``0 < p0 < p1 < 1`` (ADR-012 section
1, corrected/proven in full in ADR-012's 2026-09-17 amendment section 5).
``_bernoulli_reference_value`` below is exactly this formula -- used for
both arms: the lower (degradation-detecting) arm directly, at
``(p0, p1) = (p_u, p_u * detect_rate_multiple)``; the upper
(improvement-detecting) arm on the *success* indicator ``Y = 1 - X``, at
``(q0, q1) = (1 - p_u, 1 - p_u / detect_rate_multiple)`` -- an increase in
success rate, which is the same "detect an increase" shape the formula was
derived for (ADR-012 amendment section 2's symmetric lever, ADR-013 section
6d's ``p_U`` substitution rule applied to both arms).

## GICP -- designing at ``p_U``, not ``p_hat``

ADR-013 replaces the plug-in design's estimated rate ``p_hat = f / m`` with
``p_u`` (``clopper_pearson.clopper_pearson_upper_bound``, ``alpha=0.10``) as
the design's own "in-control rate" everywhere ADR-012's formula references
it. This closes the implementability gap a plug-in design leaves: the
natural adequacy rule is stated in the true, unobservable ``p0``, while
``p_u`` is a function of ``m``/``f`` alone -- the two quantities this
library actually holds at fit time.

## Exact ARL0 -- a finite Markov chain, not an approximation

``_one_sided_bernoulli_arl0`` and ``_joint_two_sided_bernoulli_arl0`` below
solve the CUSUM statistic's exact in-control (or alternative-hypothesis)
expected absorption time via a finite-state Markov chain -- ADR-012 section
4's argument that a two-outcome process gives a finite reachable lattice
applies to the CUSUM (unlike the EWMA, which has no such lattice and is
deferred). ``B_t = max(0, B_(t-1) + X_t - r)``, quantised to a rational
lattice with denominator ``N`` chosen so every reference value/decision
interval this module constructs is exactly representable on it (never an
approximation of the real-valued process -- ADR-012 section 3's "report the
achieved ARL, do not chase the target" already accepts the residual this
quantisation leaves, and reports it honestly via ``achieved_arl`` next to
``requested_arl``).

🚨 **The two-sided combination is deliberately NOT ``cusum_fitting``'s
``_combine_two_sided_arl0`` (Montgomery Eq. 9.7, a harmonic-mean
approximation).** That formula is acceptable for the continuous CUSUM only
because its whole ARL0 computation (Siegmund's diffusion approximation) is
already approximate -- combining two approximations approximately costs
nothing additional in kind. The Bernoulli CUSUM ships *before* the Bernoulli
EWMA specifically because its ARL0 is exact (ADR-012 sections 4-5); reusing
the harmonic shortcut here would silently reintroduce approximation into the
one property that justifies that ordering.
``_joint_two_sided_bernoulli_arl0`` instead builds the state space as the
Cartesian product of both arms' finite lattices, a single shared
Bernoulli(*p*) draw updating both accumulators every step, and solves once
via first-step analysis on the joint absorbing chain -- exactly the
construction ADR-014 section 6c names. See
``tests/unit/baseline/test_bernoulli_cusum_arl_published_values.py`` for the
independent verification (a from-scratch reference solver, a Monte Carlo
cross-check, and a demonstration that the harmonic shortcut diverges from
the exact joint solve by over 10% at a real design point) -- per ADR-013
section 7's verification bar for any number that gates public behaviour.

## Postconditions on every solve (BIN-140's lesson, generalised)

A near-singular linear solve can return a plausible-looking, wrong value
instead of failing (BIN-140; ADR-013 section 7 restates this as a standing
requirement for this whole ADR family). Every ARL this module's Markov-chain
solvers return is checked finite and >= 1.0 (the mathematical floor for any
stopping time's expectation) before being trusted; a solve that fails this
check is replaced with ``_ILL_CONDITIONED_ARL_SENTINEL``, a value far beyond
any legal target -- mirroring ``ewma_numerics._ILL_CONDITIONED_ARL_SENTINEL``
exactly, including why the substitution is sound (the calibration search
below only ever reads the sentinel as "far exceeds the target," and it is
never reported back as an ``achieved_arl``, which is always re-evaluated at
the solved decision interval, inside the trustworthy region).

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

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from drift_caliper.baseline.domain.baseline import Baseline
from drift_caliper.baseline.domain.clopper_pearson import clopper_pearson_upper_bound
from drift_caliper.baseline.domain.cusum_fitting import _validate_direction
from drift_caliper.baseline.domain.ewma_fitting import MAX_MEANINGFUL_ARL
from drift_caliper.baseline.domain.fitted_bernoulli_cusum import FittedBernoulliCUSUM
from drift_caliper.baseline.domain.parameter_guards import (
    require_real_number,
    require_type,
)
from drift_caliper.baseline.domain.spc_numerics import baseline_scores
from drift_caliper.errors import InsufficientBaselineError, InvalidParameterError

_CHART_TYPE = "bernoulli_cusum"
_CALIBRATION_METHOD = "gicp_markov_chain"

# ADR-013 section 3: the largest alpha that clears ADR-005's ratified <=5%
# baseline-adequacy appetite with real headroom (2.57% on its own measured
# upper confidence bound, against 4.97% for the more aggressive but marginal
# 0.125). Fixed, not engineer-facing (ADR-014 Decision 5) -- exposing it
# would let a caller pick a value outside the five-point verified grid with
# no guarantee behind it.
_ALPHA = 0.10

# ADR-012 section 1: 2.0 is the measured, largest-multiple-defined-across-
# the-whole-legal-domain default -- worst-case regret 1.17 for p0 <= 0.20,
# rising to 1.49 across the full legal domain (ADR-013 section 6a), still
# the best available default because 3.0/5.0 are undefined once p0 exceeds
# 1/3 or 1/5 respectively.
DEFAULT_DETECT_RATE_MULTIPLE = 2.0

# ADR-014 amendment Decision 7: per-arm adaptive lattice denominator with
# centring tolerance.  The fixed _LATTICE_DENOMINATOR = 100 violated the
# (p0, p1) interval invariant at low failure rates (p_u < 0.01), where the
# gap p1 - p0 narrowed below one lattice step (1/100).  Replaced by
# _adaptive_lattice_denominator below, which finds the smallest N per arm
# such that round(r * N) / N lies strictly inside (p0, p1) AND within
# epsilon * (p1 - p0) of the unquantised r.
_EPSILON = 0.25

# ADR-014 amendment Decision 10b: joint two-sided state count cap.
# Peak RSS is approximately 950 bytes/state; at 1M states that is ~908 MB,
# safe for a typical CI runner or agent container.  Checked *before* the
# joint solve runs.
_MAX_JOINT_STATES = 1_000_000

# Upper bound on the Fraction reconstruction search a caller-supplied
# (reference_value, decision_interval) pair is matched against in
# `_lattice_denominator` -- large enough to recover `_LATTICE_DENOMINATOR`
# (and any of its divisors) exactly, and large enough for the round, small-
# denominator decimals `test_bernoulli_cusum_arl_published_values.py` calls
# `_one_sided_bernoulli_arl0`/`_joint_two_sided_bernoulli_arl0` with
# directly, without being so large that floating-point noise in an
# arbitrary float gets misread as a huge, spurious denominator.
_DENOMINATOR_RECONSTRUCTION_CAP = 100_000

_MIN_DECISION_INTERVAL_UNITS = 1
_MAX_DECISION_INTERVAL_UNITS = 2_000_000

# ADR-011's MIN_COHERENT_ARL, restated here rather than imported: E[N] >= 1
# for any stopping time N supported on {1, 2, 3, ...} -- a mathematical
# floor about expectation, independent of chart type (ADR-014 Decision 3,
# point 1: "the coherence floor transfers unchanged, no measurement
# needed"). ADR-011's own MIN_TARGET_ARL/VERIFIED_ARL_FLOOR tiers do NOT
# transfer -- see fit_bernoulli_cusum's docstring.
_MIN_COHERENT_ARL = 1.0

# Sentinel for an ill-conditioned Markov-chain solve (BIN-140's lesson) --
# mirrors ewma_numerics._ILL_CONDITIONED_ARL_SENTINEL exactly: a value far
# beyond any legal target_arl, read by the calibration search below as
# "far exceeds the target," never reported as an achieved_arl.
_ILL_CONDITIONED_ARL_SENTINEL = 1e15

# A tiny safety margin keeping a computed design point (p_1 for the lower
# arm) strictly below 1.0 so it round-trips as an accepted input (BIN-122) --
# not a statistical constant, an engineering floor on floating-point
# distinguishability from the boundary itself.
_DESIGN_POINT_SAFETY_MARGIN = 1e-9

_ALL_FAILED_REASON = "all_baseline_judgements_failed"
_SCORE_NOT_BINARY_REASON = "score_not_binary"


# ===========================================================================
# Parameter validation
# ===========================================================================


def _require_bernoulli_target_arl(target_arl: float | None) -> float:
    """Validate ``target_arl`` -- required, finite, and coherent (>= 1.0).

    Unlike ``parameter_guards._require_bernoulli_target_arl``, this does NOT apply
    ADR-011's ``MIN_TARGET_ARL``/``VERIFIED_ARL_FLOOR`` tiers. ADR-014
    Decision 3 is explicit about why: those tiers exist to disclose a gap
    between an *approximation* (Markov-chain EWMA, Siegmund's diffusion
    approximation for CUSUM) and the *published table* that verifies it at
    a handful of points. The Bernoulli CUSUM's ARL0 is exact -- there is no
    approximation-vs-table gap here to gatekeep against, at any
    ``target_arl``. What DOES transfer -- the coherence floor, and a
    *computed* attainability floor (BIN-117's shape, not its number) -- is
    enforced separately once the reference values are known (see
    ``_require_attainable_target_arl`` below), because the attainable floor
    depends on the fitted reference value, not on ``target_arl`` alone.
    """
    if target_arl is None:
        raise InvalidParameterError(
            "target_arl is required to fit a Bernoulli CUSUM chart",
            context={
                "parameter": "target_arl",
                "constraint": "must be a finite float >= 1.0",
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
        target_arl, parameter="target_arl", constraint="must be a finite float >= 1.0"
    )
    if not math.isfinite(numeric) or numeric < _MIN_COHERENT_ARL:
        raise InvalidParameterError(
            "target_arl is below the mathematical floor for any stopping time",
            context={
                "parameter": "target_arl",
                "constraint": "must be a finite float >= 1.0",
                "kind": "invalid",
                "provided": numeric,
                "min_value": _MIN_COHERENT_ARL,
                "min_inclusive": True,
            },
            recovery_hint=(
                "target_arl must be at least 1.0 -- the expectation of any "
                "stopping time supported on {1, 2, 3, ...} is always at "
                "least 1. Choose a target_arl that reflects a genuine "
                "false-alarm tolerance, e.g. 370 or 500."
            ),
        )
    return numeric


def _validate_detect_rate_multiple(value: float | None) -> float:
    """Validate ``detect_rate_multiple`` -- optional, finite, strictly positive."""
    if value is None:
        return DEFAULT_DETECT_RATE_MULTIPLE
    constraint = "must be a finite, strictly positive real number"
    numeric = require_real_number(
        value, parameter="detect_rate_multiple", constraint=constraint
    )
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise InvalidParameterError(
            "detect_rate_multiple must be a finite, strictly positive number",
            context={
                "parameter": "detect_rate_multiple",
                "constraint": constraint,
                "kind": "invalid",
                "provided": numeric,
                "min_value": 0.0,
                "min_inclusive": False,
            },
            recovery_hint=(
                "Pass a finite, strictly positive detect_rate_multiple, or "
                "omit it entirely to use the library default "
                f"({DEFAULT_DETECT_RATE_MULTIPLE})."
            ),
        )
    return numeric


def _require_binary_scores(scores: Sequence[float]) -> None:
    """Reject a baseline containing a score that is not exactly ``0.0``/``1.0``.

    ADR-014 Decision 1's validation order step 2 -- runs before target_arl/
    detect_rate_multiple/direction validation and before sufficiency, so an
    engineer sees this problem first regardless of what else might also be
    wrong with the call (see ``test_checked_before_sufficiency``).

    Raises
    ------
    InvalidParameterError
        Some ``scores[i]`` is neither ``0.0`` nor ``1.0`` -- including a
        legal, finite, in-range continuous score that every other chart
        type would accept without complaint.
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
# The reference value (ADR-012 section 1, amendment section 5)
# ===========================================================================


def _bernoulli_reference_value(p0: float, p1: float) -> float:
    """Derive the CUSUM reference value detecting a rise from ``p0`` to ``p1``.

    ``r = ln((1-p0)/(1-p1)) / ln(p1*(1-p0) / (p0*(1-p1)))`` -- see the
    module docstring's "The reference value" section for the full
    derivation. Requires ``0 < p0 < p1 < 1``; ``p0 < r < p1`` holds
    (ADR-012 amendment section 5's proof).
    """
    numerator = math.log((1.0 - p0) / (1.0 - p1))
    denominator = math.log((p1 * (1.0 - p0)) / (p0 * (1.0 - p1)))
    return numerator / denominator


def _quantise_reference_value(r: float, n: int) -> int:
    """Round ``r`` to the nearest multiple of ``1/n``, clamped strictly inside (0, n).

    Both endpoints are excluded: ``r_units = 0`` would make the CUSUM's
    "down" increment exactly zero (a success would never reduce the
    statistic), and ``r_units = n`` would make its "up" increment exactly
    zero (a failure would never raise it) -- either collapses the chart
    into a degenerate one-directional walk. Clamping to the nearest legal
    unit is a lattice-granularity artefact (ADR-012 section 3 already
    documents that refining the lattice does not monotonically improve
    calibration; this is the same class of residual at the boundary),
    reported honestly via the achieved/requested ARL0 gap, not hidden.
    """
    units = round(r * n)
    return max(1, min(n - 1, units))


def _adaptive_lattice_denominator(r: float, p0: float, p1: float) -> int:
    """Find the smallest ``N >= 2`` satisfying both invariants.

    ADR-014 amendment Decision 7: ``round(r * N) / N`` must lie strictly
    inside ``(p0, p1)`` AND within ``epsilon * (p1 - p0)`` of the
    unquantised ``r``.  The scan starts at ``N = 2`` and is bounded by the
    closed-form ``ceil(1 / (2 * epsilon * gap))`` which guarantees a
    solution exists (since ``|round(r * N) / N - r| <= 1 / (2N)`` and
    ``epsilon * gap < min(r - p0, p1 - r)`` for ``epsilon < 0.5``).
    """
    gap = p1 - p0
    tolerance = _EPSILON * gap
    # Closed-form upper bound on N -- guarantees a solution exists so the
    # scan always terminates (ADR-014 amendment Decision 7).
    max_n = math.ceil(1.0 / (2.0 * _EPSILON * gap)) + 1
    for n in range(2, max_n + 1):
        r_units = _quantise_reference_value(r, n)
        r_q = r_units / n
        if p0 < r_q < p1 and abs(r_q - r) <= tolerance:
            return n
    # Unreachable: the closed-form bound ceil(1/(2*epsilon*gap)) + 1
    # guarantees a solution exists inside the scan range.
    return max_n  # pragma: no cover


# ===========================================================================
# Exact ARL0 via a finite Markov chain (ADR-012 section 4, ADR-014 section 6c)
# ===========================================================================


def _lattice_denominator(*values: float) -> int:
    """Find the smallest integer ``N`` making every value exactly ``k/N``.

    Uses each value's own best rational approximation
    (``fractions.Fraction.limit_denominator``) rather than a single fixed
    denominator, because the two ARL functions below are called two ways:
    internally, with reference values/decision intervals this module itself
    quantised to ``_LATTICE_DENOMINATOR`` (which this recovers exactly, or a
    divisor of it); and directly, in
    ``tests/unit/baseline/test_bernoulli_cusum_arl_published_values.py``,
    with arbitrary round decimals chosen independently of that constant. A
    single fixed ``N`` would force the joint (two-armed) solver's state
    count -- which grows as the PRODUCT of both arms' lattice sizes -- far
    higher than the smallest exact representation needs, which is
    infeasible for realistic decision intervals (see that test file's own
    "N=20, not a finer lattice" note on exactly this trade-off).
    """
    denominators = [
        Fraction(value).limit_denominator(_DENOMINATOR_RECONSTRUCTION_CAP).denominator
        for value in values
    ]
    return math.lcm(*denominators)


def _finite_and_coherent(arl: float) -> float:
    """Apply the BIN-140 postcondition: finite and coherent, or the sentinel."""
    if not math.isfinite(arl) or arl < _MIN_COHERENT_ARL:
        return _ILL_CONDITIONED_ARL_SENTINEL
    return arl


def _solve_absorbing_chain(
    rows: list[int], cols: list[int], data: list[float], n_states: int, start: int
) -> float:
    """Solve ``(I - Q) m = 1`` for the expected steps to absorption from ``start``.

    Shared by both ARL functions below -- the only difference between a
    one-armed and a two-armed (joint) Bernoulli CUSUM chain is how the
    transition entries are built, not how the resulting sparse linear
    system is solved.
    """
    if n_states <= 0:
        return 1.0
    # scipy.sparse/scipy.sparse.linalg have no type stubs mypy can see (the
    # same scipy stub-coverage gap `cusum_fitting.py`'s `brentq` call and
    # this module's own `beta.ppf` call work around) -- each call below
    # is untyped in mypy's view even though it is a real, non-optional
    # runtime call.
    transition = sp.csc_matrix(  # type: ignore[no-untyped-call]
        (data, (rows, cols)), shape=(n_states, n_states)
    )
    identity = sp.identity(n_states, format="csc")  # type: ignore[no-untyped-call]
    ones = np.ones(n_states)
    try:
        steps = spla.spsolve(  # type: ignore[no-untyped-call]
            identity - transition, ones
        )
    except Exception:  # any solver failure is treated as ill-conditioned below
        return _ILL_CONDITIONED_ARL_SENTINEL
    steps_array = np.asarray(steps).reshape(-1)
    if steps_array.shape[0] != n_states:
        return _ILL_CONDITIONED_ARL_SENTINEL
    return _finite_and_coherent(float(steps_array[start]))


def _one_sided_arl0_in_units(up: int, down: int, n_transient: int, p: float) -> float:
    """Exact one-sided ARL0, given already-quantised integer lattice steps.

    ``B_t = max(0, B_(t-1) + X_t - r)``, quantised: a failure (probability
    ``p``) adds ``up`` units, a success (probability ``1-p``) adds ``down``
    units (negative), floored at ``0``. Transient states are
    ``0..n_transient-1``; a transition landing at or beyond
    ``n_transient`` is absorption (Caliper's strict-inequality convention
    -- signal when the statistic strictly exceeds the decision interval).
    """
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for state in range(n_transient):
        failure_state = state + up
        if failure_state < n_transient:
            rows.append(state)
            cols.append(failure_state)
            data.append(p)
        success_state = max(0, state + down)
        if success_state < n_transient:
            rows.append(state)
            cols.append(success_state)
            data.append(1.0 - p)
    return _solve_absorbing_chain(rows, cols, data, n_transient, start=0)


def _one_sided_bernoulli_arl0(
    reference_value: float, decision_interval: float, p: float
) -> float:
    """Exact one-sided in-control (or alternative-hypothesis) Bernoulli CUSUM ARL0.

    Solved via a finite Markov chain over the statistic's reachable lattice
    (ADR-012 section 4) -- see the module docstring's "Exact ARL0" section.
    Caliper's strict-inequality boundary convention throughout: a value
    exactly at the decision interval is in control, not out (matching
    ``Monitor``'s ``S_hi > h`` check for the continuous CUSUM).

    Parameters
    ----------
    reference_value
        The reference value *r*, already derived (and, in production use,
        already lattice-quantised by ``fit_bernoulli_cusum``).
    decision_interval
        The decision interval *h*.
    p
        The Bernoulli parameter to evaluate the chain at -- ``p_u`` for the
        in-control (false-alarm) figure, or an alternative-hypothesis rate
        for a detection-speed figure.

    Returns
    -------
    float
        The exact ARL0, or ``_ILL_CONDITIONED_ARL_SENTINEL`` if the
        underlying linear solve is ill-conditioned (BIN-140's postcondition).
    """
    n = _lattice_denominator(reference_value, decision_interval)
    r_units = round(reference_value * n)
    h_units = round(decision_interval * n)
    up = n - r_units
    down = -r_units
    n_transient = h_units + 1
    return _one_sided_arl0_in_units(up, down, n_transient, p)


def _joint_two_sided_bernoulli_arl0(
    reference_value_lower: float,
    decision_interval_lower: float,
    reference_value_upper: float,
    decision_interval_upper: float,
    p: float,
) -> float:
    """Exact two-sided (joint two-armed) Bernoulli CUSUM ARL0.

    A single shared draw ``X_t ~ Bernoulli(p)`` (the failure indicator)
    updates both arms every step:

        B_lower_t = max(0, B_lower_(t-1) + X_t       - r_lower)   -- degradation
        B_upper_t = max(0, B_upper_(t-1) + (1 - X_t) - r_upper)   -- improvement

    signalling when EITHER arm strictly exceeds its own decision interval.
    State space is the Cartesian product of both arms' finite lattices
    (ADR-014 section 6c) -- deliberately NOT
    ``cusum_fitting._combine_two_sided_arl0``'s harmonic-mean
    approximation, which the module docstring explains would silently
    reintroduce approximation into this chart's one distinguishing property.

    Parameters
    ----------
    reference_value_lower, decision_interval_lower
        *r*, *h* for the degradation-detecting (lower) arm.
    reference_value_upper, decision_interval_upper
        *r*, *h* for the improvement-detecting (upper) arm.
    p
        The shared Bernoulli parameter -- ``p_u`` for the in-control
        (false-alarm) figure, or an alternative-hypothesis rate for a
        detection-speed figure.

    Returns
    -------
    float
        The exact, combined two-sided ARL0, or
        ``_ILL_CONDITIONED_ARL_SENTINEL`` if the underlying linear solve is
        ill-conditioned.
    """
    # ADR-014 amendment Decision 8: per-arm denominators, not a shared LCM.
    # Each arm's CUSUM accumulator lives on its own lattice -- state (i, j)
    # means the lower arm is at i units of 1/n_lo and the upper arm at j
    # units of 1/n_up.  The two arms share a single Bernoulli draw, not a
    # lattice denominator.
    n_lo = _lattice_denominator(reference_value_lower, decision_interval_lower)
    n_up = _lattice_denominator(reference_value_upper, decision_interval_upper)

    r_lo_units = round(reference_value_lower * n_lo)
    h_lo_units = round(decision_interval_lower * n_lo)
    r_up_units = round(reference_value_upper * n_up)
    h_up_units = round(decision_interval_upper * n_up)

    up_lower = n_lo - r_lo_units
    down_lower = -r_lo_units
    up_upper = n_up - r_up_units
    down_upper = -r_up_units

    n_lower = h_lo_units + 1
    n_upper = h_up_units + 1
    n_states = n_lower * n_upper

    def index(i: int, j: int) -> int:
        return i * n_upper + j

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for i in range(n_lower):
        for j in range(n_upper):
            state = index(i, j)
            # X_t = 1 (failure), probability p: lower arm grows, upper arm shrinks.
            next_i = i + up_lower
            next_j = max(0, j + down_upper)
            if next_i < n_lower and next_j < n_upper:
                rows.append(state)
                cols.append(index(next_i, next_j))
                data.append(p)
            # X_t = 0 (success), probability 1-p: lower arm shrinks, upper grows.
            next_i2 = max(0, i + down_lower)
            next_j2 = j + up_upper
            if next_i2 < n_lower and next_j2 < n_upper:
                rows.append(state)
                cols.append(index(next_i2, next_j2))
                data.append(1.0 - p)

    return _solve_absorbing_chain(rows, cols, data, n_states, start=index(0, 0))


# ===========================================================================
# Decision-interval calibration
# ===========================================================================


def _calibrate_one_sided_decision_interval_units(
    r_units: int, n: int, p: float, target: float
) -> int:
    """Find the smallest integer ``h_units`` whose one-sided ARL0 meets ``target``.

    ARL0 is monotonically non-decreasing in the decision interval (a wider
    interval never signals sooner), so this is an ordinary exponential
    search followed by a bisection over integer lattice units -- there is
    no closed form to invert, unlike the continuous CUSUM's Siegmund
    approximation.
    """
    up = n - r_units
    down = -r_units

    def achieved_at(h_units: int) -> float:
        return _one_sided_arl0_in_units(up, down, h_units + 1, p)

    h_units = _MIN_DECISION_INTERVAL_UNITS
    if achieved_at(h_units) >= target:
        return h_units

    # Exponential search for an upper bound on h_units.
    while achieved_at(h_units) < target:
        h_units *= 2
        if h_units > _MAX_DECISION_INTERVAL_UNITS:
            # ADR-014 amendment Decision 10a.  Check whether the cap itself
            # achieves the target -- the exponential search overshoots, so
            # the answer may lie between the last power-of-two and the cap.
            cap_arl = achieved_at(_MAX_DECISION_INTERVAL_UNITS)
            if cap_arl >= target:
                # Bisect between the last safe power-of-two and the cap.
                lo = h_units // 2
                hi = _MAX_DECISION_INTERVAL_UNITS
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if achieved_at(mid) >= target:
                        hi = mid
                    else:
                        lo = mid
                return hi
            # The cap cannot deliver the target -- raise with the largest
            # ARL this arm can achieve, which round-trips (BIN-122).
            raise InvalidParameterError(
                "the one-sided calibration search exceeded its decision "
                "interval cap without reaching the requested ARL0",
                context={
                    "parameter": "target_arl",
                    "kind": "invalid",
                    "max_attainable_arl": float(cap_arl),
                    "constraint": (
                        "the target ARL0 must be achievable within the "
                        "decision interval search range"
                    ),
                },
                recovery_hint=(
                    f"Reduce target_arl to at most {cap_arl}, which is the "
                    "largest ARL0 this arm can deliver at this lattice "
                    "configuration."
                ),
            )

    lo, hi = h_units // 2, h_units
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if achieved_at(mid) >= target:
            hi = mid
        else:
            lo = mid
    return hi


# ===========================================================================
# Joint state count bisection (ADR-014 amendment Decision 10b)
# ===========================================================================


def _joint_state_count_at_target(
    target_arl: float,
    r_lower_units: int,
    n_lower: int,
    p_lower: float,
    r_upper_units: int,
    n_upper: int,
    p_upper: float,
) -> int:
    """Joint state count a two-sided fit at ``target_arl`` would produce.

    Each arm's decision interval is calibrated independently, and the joint
    state count is the product of the two transient-state counts.  Monotone
    in ``target_arl`` for a fixed baseline (verified by ADR-014's
    measurement).
    """
    per_arm_target = target_arl * 2.0
    h_lo = _calibrate_one_sided_decision_interval_units(
        r_lower_units, n_lower, p_lower, per_arm_target
    )
    h_up = _calibrate_one_sided_decision_interval_units(
        r_upper_units, n_upper, p_upper, per_arm_target
    )
    return (h_lo + 1) * (h_up + 1)


def _find_max_two_sided_target_arl(
    r_lower_units: int,
    n_lower: int,
    p_lower: float,
    r_upper_units: int,
    n_upper: int,
    p_upper: float,
) -> float:
    """Bisect for the largest ``target_arl`` within the joint state cap.

    The joint state count is monotonically non-decreasing in ``target_arl``
    (ADR-014 amendment Decision 10b, verified by measurement), so a standard
    bisection over ``[1, MAX_MEANINGFUL_ARL]`` gives the answer.  The
    returned value **round-trips** as an accepted ``target_arl`` (BIN-122's
    rule).
    """
    lo = _MIN_COHERENT_ARL
    hi = MAX_MEANINGFUL_ARL

    # Quick check: if even the ceiling fits, return it.
    try:
        count_at_hi = _joint_state_count_at_target(
            hi, r_lower_units, n_lower, p_lower, r_upper_units, n_upper, p_upper
        )
    except InvalidParameterError:
        count_at_hi = _MAX_JOINT_STATES + 1
    if count_at_hi <= _MAX_JOINT_STATES:
        # Unreachable in practice: if the ceiling fits within the cap, the
        # caller's own target_arl (which is <= the ceiling) also fits, so
        # the raise path that leads here is never taken.
        return hi  # pragma: no cover

    # Bisect to find the boundary.
    for _ in range(100):  # ~50 iterations needed for 1e6 range at 1.0 precision
        if hi - lo < 1.0:
            break
        mid = (lo + hi) / 2.0
        try:
            count = _joint_state_count_at_target(
                mid, r_lower_units, n_lower, p_lower, r_upper_units, n_upper, p_upper
            )
        except InvalidParameterError:
            count = _MAX_JOINT_STATES + 1
        if count <= _MAX_JOINT_STATES:
            lo = mid
        else:
            hi = mid

    # Return the floor to guarantee the round-trip: math.floor ensures the
    # returned value, when re-submitted, produces a state count at most
    # equal to the one at `lo` (which is <= _MAX_JOINT_STATES).
    return math.floor(lo)


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

    Validates, in order (ADR-014 Decision 1): ``baseline``'s type; that
    every recorded score is exactly ``0.0`` or ``1.0``; ``target_arl``/
    ``detect_rate_multiple``/``direction``; ADR-005's unchanged
    100-observation sufficiency floor (ADR-013 section 2); then designs the
    chart at ``p_u`` (Guaranteed In-Control Performance, ADR-013 section 1)
    rather than the plain point estimate, and calibrates both arms via an
    exact Markov-chain solve (ADR-012 section 4, ADR-014 section 6c).

    Parameters
    ----------
    baseline
        The Phase I baseline to fit from -- every recorded
        ``ScoringResult.score`` must be exactly ``0.0`` (fail) or ``1.0``
        (pass); "failure" means ``1 - score`` (ADR-012 amendment section 1's
        sign convention).
    target_arl
        The target in-control ARL0 (false alarm tolerance). Optional in the
        signature, required by validation -- omitting it raises
        ``InvalidParameterError`` with ``context["kind"] == "missing"``.
        Unlike the three continuous charts, ADR-011's ``[100, 370)``
        tiering does not apply here (ADR-014 Decision 3) -- this chart's
        ARL0 is exact, so there is no approximation-vs-published-table gap
        for that tiering to disclose.
    detect_rate_multiple
        The shift lever -- a multiple of the design rate rather than a
        sigma multiple, since a Bernoulli process's variance is determined
        entirely by its rate (ADR-012 section 1). ``None`` uses
        ``DEFAULT_DETECT_RATE_MULTIPLE`` (``2.0``).
    direction
        ``"two_sided"`` (default), ``"lower"``, or ``"upper"`` -- same
        vocabulary as ``fit_cusum``'s ``direction`` (ADR-012 amendment
        section 2). Both arms are always designed and reported regardless
        of ``direction``.

    Returns
    -------
    FittedBernoulliCUSUM
        The fitted artefact. Satisfies ``HasProvenance`` only, not
        ``FittedControlLimits`` (ADR-014 Decision 6a).

    Raises
    ------
    InvalidParameterError
        ``baseline`` is not a ``Baseline``; some recorded score is not
        exactly ``0.0``/``1.0`` (``context["reason"] ==
        "score_not_binary"``); ``target_arl`` is missing or not a finite
        number >= 1.0; ``detect_rate_multiple`` is not a finite, strictly
        positive number; ``direction`` is not one of the three recognised
        values; the implied design point ``p_u * detect_rate_multiple``
        is not a valid probability (``context["max_detect_rate_multiple"]``
        reports the largest value that round-trips as an accepted input,
        computed from ``p_u`` per ADR-013 section 6b); or every baseline
        judgement failed, for which no ``detect_rate_multiple`` exists that
        would fix it (``context["reason"] ==
        "all_baseline_judgements_failed"``, no ``max_detect_rate_multiple``
        key).
    InsufficientBaselineError
        ``baseline`` has fewer than ADR-005's 100-observation floor
        (ADR-013 section 2 -- unchanged for binary charts).

    Notes
    -----
    **Never raises ``DegenerateBaselineError``** -- unlike the three
    continuous charts, GICP's confidence-bound construction means neither
    ``p_hat = 0`` (designed at ``p_u`` instead, ADR-013 section 5) nor
    ``p_hat = 1`` (falls into the ``p_1 >= 1`` ``InvalidParameterError``
    path above) needs the "statistically unusable despite meeting the
    count threshold" diagnosis that category exists for.
    """
    baseline = require_type(
        baseline, Baseline, parameter="baseline", type_name="Baseline"
    )
    scores = baseline_scores(baseline.observations)
    _require_binary_scores(scores)

    validated_target_arl = _require_bernoulli_target_arl(target_arl)
    # Decision 9: ceiling at MAX_MEANINGFUL_ARL (same bound the continuous
    # charts enforce, reused here as a cost bound).
    if validated_target_arl > MAX_MEANINGFUL_ARL:
        raise InvalidParameterError(
            "target_arl exceeds the supported ceiling",
            context={
                "parameter": "target_arl",
                "kind": "invalid",
                "provided": validated_target_arl,
                "max_value": MAX_MEANINGFUL_ARL,
                "max_inclusive": True,
            },
            recovery_hint=(
                f"Choose a target_arl of at most {MAX_MEANINGFUL_ARL}. "
                "This ceiling bounds the cost of the calibration search; "
                "the Bernoulli CUSUM's ARL0 is exact at every value below it."
            ),
        )
    validated_multiple = _validate_detect_rate_multiple(detect_rate_multiple)
    effective_direction = _validate_direction(direction)

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

    if f == m:
        raise InvalidParameterError(
            "no valid detection design exists for a baseline with no "
            "passing judgements",
            context={
                "parameter": "detect_rate_multiple",
                "constraint": ("the implied design point must be a valid probability"),
                "kind": "invalid",
                "reason": _ALL_FAILED_REASON,
                "provided": validated_multiple,
            },
            recovery_hint=(
                "Every judgement in this baseline failed, so there is no "
                "observed passing rate to design a detection sensitivity "
                "against. Collect a baseline with at least one passing "
                "judgement before fitting."
            ),
        )

    p_hat = f / m
    p_u = clopper_pearson_upper_bound(failures=f, observations=m, alpha=_ALPHA)

    p1_lower = p_u * validated_multiple
    if p1_lower >= 1.0:
        max_multiple = (1.0 - _DESIGN_POINT_SAFETY_MARGIN) / p_u
        raise InvalidParameterError(
            "detect_rate_multiple implies a design point that is not a "
            "valid probability",
            context={
                "parameter": "detect_rate_multiple",
                "constraint": (
                    "p_u * detect_rate_multiple must be strictly less than 1.0"
                ),
                "kind": "invalid",
                "provided": validated_multiple,
                "max_detect_rate_multiple": max_multiple,
            },
            recovery_hint=(
                "The requested detect_rate_multiple, applied to this "
                "baseline's conservative failure-rate estimate (p_u), "
                "implies a failure rate of 1.0 or higher -- not a valid "
                "probability. The largest value this baseline supports is "
                f"reported in context['max_detect_rate_multiple'] "
                f"({max_multiple}); pass that value, or a smaller one."
            ),
        )

    r_lower_real = _bernoulli_reference_value(p_u, p1_lower)

    q0_upper = 1.0 - p_u
    q1_upper = 1.0 - p_u / validated_multiple
    r_upper_real = _bernoulli_reference_value(q0_upper, q1_upper)

    # Decision 7: per-arm adaptive lattice denominators with centring
    # tolerance, replacing the fixed _LATTICE_DENOMINATOR = 100.
    n_lower = _adaptive_lattice_denominator(r_lower_real, p_u, p1_lower)
    n_upper = _adaptive_lattice_denominator(r_upper_real, q0_upper, q1_upper)

    r_lower_units = _quantise_reference_value(r_lower_real, n_lower)
    r_upper_units = _quantise_reference_value(r_upper_real, n_upper)
    r_lower = r_lower_units / n_lower
    r_upper = r_upper_units / n_upper

    per_arm_target = (
        validated_target_arl * 2.0
        if effective_direction == "two_sided"
        else validated_target_arl
    )

    h_lower_units = _calibrate_one_sided_decision_interval_units(
        r_lower_units, n_lower, p_u, per_arm_target
    )
    h_upper_units = _calibrate_one_sided_decision_interval_units(
        r_upper_units, n_upper, q0_upper, per_arm_target
    )

    # Decision 10b: joint state count cap -- checked BEFORE building the
    # joint system, so memory is never allocated for an infeasible solve.
    if effective_direction == "two_sided":
        joint_states = (h_lower_units + 1) * (h_upper_units + 1)
        if joint_states > _MAX_JOINT_STATES:
            max_two_sided_target = _find_max_two_sided_target_arl(
                r_lower_units,
                n_lower,
                p_u,
                r_upper_units,
                n_upper,
                q0_upper,
            )
            raise InvalidParameterError(
                "the two-sided fit exceeds the joint state count cap",
                context={
                    "parameter": "target_arl",
                    "kind": "invalid",
                    "provided": validated_target_arl,
                    "reason": "joint_state_count_exceeded",
                    "joint_state_count": joint_states,
                    "max_joint_states": _MAX_JOINT_STATES,
                    "max_two_sided_target_arl": max_two_sided_target,
                },
                recovery_hint=(
                    f"Reduce target_arl to at most "
                    f"{max_two_sided_target} for a two-sided fit at this "
                    f"baseline, increase detect_rate_multiple (which widens "
                    f"the gap and reduces per-arm decision intervals), or "
                    f"use direction='lower' or direction='upper' to avoid "
                    f"the joint solve entirely."
                ),
            )

    h_lower = h_lower_units / n_lower
    h_upper = h_upper_units / n_upper

    p_alt = (p_hat if f > 0 else p_u) * validated_multiple
    p_alt = min(p_alt, 1.0 - _DESIGN_POINT_SAFETY_MARGIN)
    q_alt = max(1.0 - p_alt, _DESIGN_POINT_SAFETY_MARGIN)

    if effective_direction == "two_sided":
        achieved_arl = _joint_two_sided_bernoulli_arl0(
            r_lower, h_lower, r_upper, h_upper, p_u
        )
        expected_detection_arl = _joint_two_sided_bernoulli_arl0(
            r_lower, h_lower, r_upper, h_upper, p_alt
        )
    elif effective_direction == "lower":
        achieved_arl = _one_sided_bernoulli_arl0(r_lower, h_lower, p_u)
        expected_detection_arl = _one_sided_bernoulli_arl0(r_lower, h_lower, p_alt)
    else:  # "upper"
        achieved_arl = _one_sided_bernoulli_arl0(r_upper, h_upper, q0_upper)
        expected_detection_arl = _one_sided_bernoulli_arl0(r_upper, h_upper, q_alt)

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
        achieved_arl=achieved_arl,
        expected_detection_arl=expected_detection_arl,
        calibration_method=_CALIBRATION_METHOD,
        advisories=(),
        detect_rate_multiple=validated_multiple,
        alpha=_ALPHA,
        p_u=p_u,
        direction=effective_direction,
        reference_value_lower=r_lower,
        decision_interval_lower=h_lower,
        reference_value_upper=r_upper,
        decision_interval_upper=h_upper,
    )


__all__ = [
    "DEFAULT_DETECT_RATE_MULTIPLE",
    "fit_bernoulli_cusum",
]
