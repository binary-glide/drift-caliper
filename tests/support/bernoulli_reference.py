"""An independent, from-scratch reference implementation of the Bernoulli CUSUM design.

**It imports nothing from ``drift_caliper``.** Every function here re-derives
what ADR-014 (Amendment 1 Decisions 7-10, Amendment 2 Decisions 12-19 and the
corrigendum C1-C12) ratifies, using only ``numpy``/``scipy`` primitives. It is
the oracle behind ``test_bernoulli_cusum_amendment2.py`` and its siblings, so
the checks there compare production against a second implementation rather
than against itself -- this project's recurring defect is a helper that both
calibrates a value and checks it, so the error divides out (``CLAUDE.md``,
BIN-84).

Provenance: condensed from the measurement scripts the ADR's figures come
from (``scratchpad/amend2/g5_twosided_independent.py`` -- from-scratch
Clopper-Pearson bounds, reference value, lattice rule, one-sided and coupled
solvers, calibration D; ``fast_finder3.py`` -- corrigendum C12.4's exact
lattice finder; ``h1_d18_cells.py`` -- the caps; ``k2_es_bound.py`` --
corrigendum C11's equal-split bound). Every expected number the tests pin was
re-measured through this module and matches the ADR's published figure (see
each test's citation).

What each piece implements:

- :func:`cp_upper`/:func:`cp_lower` -- one-sided Clopper-Pearson bounds at
  alpha = 0.10 (ADR-013 section 3; Decision 19.1 for the lower bound).
- :func:`reference_value` -- ADR-012 section 1's log-likelihood-ratio
  reference value, ``p0 < r < p1``.
- :func:`linear_lattice` -- Decision 7's ratified rule, literally: the
  smallest ``N >= 2`` with ``k = round(r N)`` (clamped to ``[1, N-1]``)
  strictly inside ``(p0, p1)`` and within ``eps * (p1 - p0)`` of ``r``.
- :func:`exact_lattice` -- corrigendum C12.4's O(log N) finder, identical to
  the linear rule by construction (it starts at the smallest denominator that
  has *any* rational in the tolerance window and walks forward applying the
  ratified test).
- :func:`one_sided_arl`/:func:`coupled_arl` -- exact absorbing-chain solves on
  the integer lattice (ADR-012 section 4; Decision 8's state space; Decision
  19.4's three-outcome coupled chain for ``B``). Strict inequality at the
  boundary (ADR-009 section 5 / BIN-112): a statistic *equal* to ``h`` is in
  control.
- :func:`calibrate` -- the smallest ``h`` whose ARL meets a target, capped at
  Decision 13.3's 999,999 units.
- :func:`reference_fit` -- a complete reference ``fit_bernoulli_cusum`` for
  the ratified behaviour: per-direction arms (C3), f = 0 rules (Decision
  19.2), calibration D (Decision 19.4), the caps (Decisions 10b, 13.3, 16).
- :func:`es_bound` -- C11's ``floor(T_ES)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp
from scipy.sparse.linalg import splu
from scipy.stats import beta  # type: ignore[attr-defined]

# ADR-013 section 3 (lower arm) and ADR-014 Decision 19.1 (upper arm): both
# one-sided bounds at the same ratified alpha.
ALPHA = 0.10
# ADR-014 Amendment 1 Decision 7: the centring tolerance.
EPSILON = 0.25
# ADR-014 Amendment 2 Decision 13.3: one-sided search cap, 999,999 units.
MAX_DECISION_INTERVAL_UNITS = 999_999
# ADR-014 Amendment 1 Decision 10b: the joint two-sided state cap.
MAX_JOINT_STATES = 1_000_000
# ADR-014 Amendment 1 Decision 9 (the continuous charts' MAX_MEANINGFUL_ARL).
MAX_TARGET_ARL = 1_000_000.0


class NotComputableError(ArithmeticError):
    """A reference solve returned something that is not a valid ARL."""


# ---------------------------------------------------------------------------
# Confidence bounds and the reference value
# ---------------------------------------------------------------------------


def cp_upper(failures: int, observations: int) -> float:
    """One-sided Clopper-Pearson upper bound: the 1-alpha quantile of Beta(f+1, m-f)."""
    if failures == 0:
        return float(1.0 - ALPHA ** (1.0 / observations))
    return float(beta.ppf(1.0 - ALPHA, failures + 1, observations - failures))


def cp_lower(failures: int, observations: int) -> float:
    """One-sided Clopper-Pearson lower bound: the alpha quantile of Beta(f, m-f+1).

    ``0.0`` at f = 0 (Decision 19.2: "``p_L = 0``").
    """
    if failures == 0:
        return 0.0
    return float(beta.ppf(ALPHA, failures, observations - failures + 1))


def reference_value(p0: float, p1: float) -> float:
    """ADR-012 section 1: ``r = ln((1-p0)/(1-p1)) / ln(p1 (1-p0) / (p0 (1-p1)))``."""
    u = math.log1p(-p0) - math.log1p(-p1)
    return u / (math.log(p1) - math.log(p0) + u)


def lower_arm_design_pair(p_u: float, multiple: float) -> tuple[float, float]:
    """Decision 19.1: the lower arm's ``(p0, p1)`` on the failure indicator."""
    return p_u, p_u * multiple


def upper_arm_design_pair(p_l: float, multiple: float) -> tuple[float, float]:
    """Decision 19.1: the upper arm's ``(q0, q1)`` on the success indicator."""
    return 1.0 - p_l, 1.0 - p_l / multiple


# ---------------------------------------------------------------------------
# Decision 7's lattice rule
# ---------------------------------------------------------------------------


def _accepts(n: int, r: float, p0: float, p1: float) -> tuple[bool, int]:
    tolerance = EPSILON * (p1 - p0)
    k = min(n - 1, max(1, round(r * n)))
    return (p0 < k / n < p1 and abs(k / n - r) <= tolerance), k


def lattice_invariants_hold(n: int, k: int, p0: float, p1: float) -> bool:
    """Decision 7's two invariants, checked at a given ``(N, k)``."""
    r = reference_value(p0, p1)
    return p0 < k / n < p1 and abs(k / n - r) <= EPSILON * (p1 - p0)


def linear_lattice(p0: float, p1: float, *, max_n: int) -> tuple[int, int] | None:
    """Decision 7's rule, applied literally by a scan from ``N = 2``.

    Returns ``None`` if no ``N <= max_n`` is accepted -- the scan is only
    *feasible* below some size, which is corrigendum C2's point.
    """
    r = reference_value(p0, p1)
    for n in range(2, max_n + 1):
        ok, k = _accepts(n, r, p0, p1)
        if ok:
            return n, k
    return None


def _simplest(
    lo: Fraction, hi: Fraction | None, lo_open: bool, hi_open: bool
) -> Fraction:
    """The simplest rational in the interval between ``lo`` and ``hi`` (Stern-Brocot).

    ``hi`` of ``None`` means unbounded above. ``0 <= lo``.
    """
    floor_lo = math.floor(lo)
    candidate = floor_lo if (lo == floor_lo and not lo_open) else floor_lo + 1
    if hi is None or candidate < hi or (candidate == hi and not hi_open):
        return Fraction(candidate)
    new_lo = 1 / (hi - floor_lo)
    new_hi = None if lo == floor_lo else 1 / (lo - floor_lo)
    return floor_lo + 1 / _simplest(new_lo, new_hi, hi_open, lo_open)


def exact_lattice(p0: float, p1: float) -> tuple[int, int] | None:
    """Corrigendum C12.4's exact finder -- the linear rule, in O(log N) to start.

    ``N_any`` is the denominator of the simplest rational in
    ``J = [r - tol, r + tol] intersect (p0, p1)``; no smaller ``N`` has any
    ``k/N`` in ``J``, so the linear rule's answer is ``>= N_any``. Walk
    forward from there applying the ratified test, bounded by ``N_sym``.
    Returns ``None`` when floating point cannot realise a design (C12.1's band
    just above ``M = 1``).
    """
    r = reference_value(p0, p1)
    big_r, big_a, big_b = Fraction(r), Fraction(p0), Fraction(p1)
    tol = Fraction(EPSILON * (p1 - p0))
    lo, lo_open = (big_r - tol, False) if big_r - tol > big_a else (big_a, True)
    hi, hi_open = (big_r + tol, False) if big_r + tol < big_b else (big_b, True)
    if not lo < hi:
        return None
    n = max(2, _simplest(lo, hi, lo_open, hi_open).denominator)
    radius = min(tol, big_r - big_a, big_b - big_r)
    if radius <= 0:
        return None
    n_sym = max(2, _simplest(big_r - radius, big_r + radius, True, True).denominator)
    while n <= n_sym:
        ok, k = _accepts(n, r, p0, p1)
        if ok:
            return n, k
        n += 1
    return None


# ---------------------------------------------------------------------------
# Exact solves on the integer lattice
# ---------------------------------------------------------------------------


def _solve_from_origin(
    n_states: int, transitions: list[tuple[float, npt.NDArray[np.int64]]]
) -> float:
    sources, destinations, weights = [], [], []
    index = np.arange(n_states)
    for probability, destination in transitions:
        keep = destination >= 0
        sources.append(index[keep])
        destinations.append(destination[keep])
        weights.append(np.full(int(keep.sum()), probability))
    q = sp.coo_matrix(  # type: ignore[no-untyped-call]
        (
            np.concatenate(weights),
            (np.concatenate(sources), np.concatenate(destinations)),
        ),
        shape=(n_states, n_states),
    ).tocsc()
    system = (sp.eye(n_states, format="csc") - q).tocsc()  # type: ignore[no-untyped-call]
    solution = splu(system).solve(np.ones(n_states))  # type: ignore[no-untyped-call]
    value = float(solution[0])
    if not (math.isfinite(value) and value >= 1.0):
        raise NotComputableError(value)
    return value


def one_sided_arl(n: int, k: int, h: int, p_step_up: float) -> float:
    """Exact one-arm run length from 0: ``+(N - k)`` w.p. ``p_step_up``, else down.

    The "down" step is ``max(0, s - k)``.

    For the lower arm the "up" event is a failure (``p_step_up`` = failure
    rate); for the upper arm it is a success (``p_step_up`` = 1 - failure
    rate). Absorbs when the statistic strictly exceeds ``h``.
    """
    states = np.arange(h + 1)
    up = states + (n - k)
    up[up > h] = -1
    down = np.maximum(0, states - k)
    return _solve_from_origin(h + 1, [(p_step_up, up), (1.0 - p_step_up, down)])


def coupled_arl(
    lower: tuple[int, int, int],
    upper: tuple[int, int, int],
    fail_both: float,
    fail_lower: float,
) -> float:
    """Decision 19.4's coupled chain on Decision 8's joint state space.

    One uniform ``U`` per step: ``U < fail_both`` is a failure for both arms;
    ``fail_both <= U < fail_lower`` is a failure for the lower arm and a
    success for the upper; ``U >= fail_lower`` is a success for both. With
    ``(fail_both, fail_lower) = (p_L, p_U)`` this is ``B``; with both equal to
    one rate ``p`` it is the ordinary joint chain at ``p``.
    """
    (nl, kl, hl), (nu, ku, hu) = lower, upper
    width = hu + 1
    i, j = np.divmod(np.arange((hl + 1) * width), width)
    i_fail, i_succ = i + (nl - kl), np.maximum(0, i - kl)
    j_fail, j_succ = np.maximum(0, j - ku), j + (nu - ku)

    def destination(
        i2: npt.NDArray[np.int64], j2: npt.NDArray[np.int64]
    ) -> npt.NDArray[np.int64]:
        d = i2 * width + j2
        d[(i2 > hl) | (j2 > hu)] = -1
        return d

    transitions = [(fail_both, destination(i_fail, j_fail))]
    if fail_lower - fail_both > 0:
        transitions.append((fail_lower - fail_both, destination(i_fail, j_succ)))
    transitions.append((1.0 - fail_lower, destination(i_succ, j_succ)))
    return _solve_from_origin((hl + 1) * width, transitions)


def calibrate(n: int, k: int, p_step_up: float, target: float) -> int | None:
    """Smallest ``h`` in ``[1, 999,999]`` with ARL ``>= target``; ``None`` if capped."""
    lo, hi = 0, 1
    while one_sided_arl(n, k, hi, p_step_up) < target:
        if hi == MAX_DECISION_INTERVAL_UNITS:
            return None
        lo, hi = hi, min(2 * hi, MAX_DECISION_INTERVAL_UNITS)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if one_sided_arl(n, k, mid, p_step_up) >= target:
            hi = mid
        else:
            lo = mid
    return hi


# ---------------------------------------------------------------------------
# A complete reference fit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceFit:
    """What the ratified ``fit_bernoulli_cusum`` must produce, or which refusal."""

    direction: str | None = None
    lattice_lower: tuple[int, int, int] | None = None
    lattice_upper: tuple[int, int, int] | None = None
    achieved_arl: float | None = None
    expected_detection_arl: float | None = None
    expected_improvement_detection_arl: float | None = None
    refusal: str | None = None


def reference_fit(
    *,
    m: int,
    f: int,
    target_arl: float,
    direction: str,
    multiple: float = 2.0,
    p_u: float | None = None,
    p_l: float | None = None,
) -> ReferenceFit:
    """The ratified fit (ADR-014 Amendment 2 + corrigendum), from first principles.

    ``p_u``/``p_l`` default to this module's own Clopper-Pearson bounds; a
    test may pass the artefact's reported values instead, so a last-bit
    difference in a confidence-bound evaluation cannot move a lattice.
    Returns a :class:`ReferenceFit` whose ``refusal`` is ``"F12"``,
    ``"F13"`` or ``"F15"`` when the fit must refuse.

    Corrigendum C13: a disclosure figure whose shifted rate lies at or inside
    the arm's design rate describes no shift and is ``None``, decided before
    any solve (:func:`degradation_within_design_rate`,
    :func:`improvement_within_design_rate`).
    """
    p_u = cp_upper(f, m) if p_u is None else p_u
    p_l = cp_lower(f, m) if p_l is None else p_l
    p_hat = f / m
    if direction == "upper" and f == 0:
        return ReferenceFit(refusal="F15")
    if direction == "two_sided" and f == 0:
        direction = "lower"  # Decision 19.2
    if direction == "lower":
        lattice = exact_lattice(*lower_arm_design_pair(p_u, multiple))
        assert lattice is not None
        nl, kl = lattice
        h = calibrate(nl, kl, p_u, target_arl)
        if h is None:
            return ReferenceFit(refusal="F12")
        detection_rate = (p_hat if f else p_u) * multiple
        return ReferenceFit(
            direction="lower",
            lattice_lower=(nl, kl, h),
            achieved_arl=one_sided_arl(nl, kl, h, p_u),
            expected_detection_arl=None
            if degradation_within_design_rate(f, p_hat, multiple, p_u)
            else one_sided_arl(nl, kl, h, detection_rate),
        )
    upper = exact_lattice(*upper_arm_design_pair(p_l, multiple))
    assert upper is not None
    nu, ku = upper
    if direction == "upper":
        h = calibrate(nu, ku, 1.0 - p_l, target_arl)
        if h is None:
            return ReferenceFit(refusal="F12")
        return ReferenceFit(
            direction="upper",
            lattice_upper=(nu, ku, h),
            achieved_arl=one_sided_arl(nu, ku, h, 1.0 - p_l),
            expected_detection_arl=None
            if improvement_within_design_rate(p_hat, multiple, p_l)
            else one_sided_arl(nu, ku, h, 1.0 - p_hat / multiple),
        )
    lower = exact_lattice(*lower_arm_design_pair(p_u, multiple))
    assert lower is not None
    nl, kl = lower
    h_lo = calibrate(nl, kl, p_u, 2.0 * target_arl)
    h_up_es = calibrate(nu, ku, 1.0 - p_l, 2.0 * target_arl)
    if h_lo is None:
        return ReferenceFit(refusal="F13")
    h_cap = MAX_JOINT_STATES // (h_lo + 1) - 1
    top = h_cap if h_up_es is None else min(h_up_es, h_cap)

    def bound(h_up: int) -> float:
        return coupled_arl((nl, kl, h_lo), (nu, ku, h_up), p_l, p_u)

    if top < 1 or bound(top) < target_arl:
        return ReferenceFit(refusal="F13")
    lo, hi = 0, top
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if bound(mid) >= target_arl:
            hi = mid
        else:
            lo = mid
    lower_lattice, upper_lattice = (nl, kl, h_lo), (nu, ku, hi)
    return ReferenceFit(
        direction="two_sided",
        lattice_lower=lower_lattice,
        lattice_upper=upper_lattice,
        achieved_arl=bound(hi),
        expected_detection_arl=None
        if degradation_within_design_rate(f, p_hat, multiple, p_u)
        else coupled_arl(
            lower_lattice, upper_lattice, p_hat * multiple, p_hat * multiple
        ),
        expected_improvement_detection_arl=None
        if improvement_within_design_rate(p_hat, multiple, p_l)
        else coupled_arl(
            lower_lattice, upper_lattice, p_hat / multiple, p_hat / multiple
        ),
    )


def degradation_within_design_rate(
    f: int, p_hat: float, multiple: float, p_u: float
) -> bool:
    """Corrigendum C13: f >= 1 and ``p_hat * M <= p_U`` (boundary included)."""
    return f >= 1 and p_hat * multiple <= p_u


def improvement_within_design_rate(p_hat: float, multiple: float, p_l: float) -> bool:
    """Corrigendum C13: ``p_hat / M >= p_L`` (boundary included)."""
    return p_hat / multiple >= p_l


def es_bound(
    lower: tuple[int, int],
    upper: tuple[int, int],
    p_u: float,
    p_l: float,
) -> float:
    """Corrigendum C11: ``floor(T_ES)``, capped at ``MAX_TARGET_ARL``.

    ``T_ES = max over a >= 1 of min(A_lo(a), A_up(H(a))) / 2`` with
    ``H(a) = floor(1e6 / (a + 1)) - 1``. A solve beyond double resolution is
    read as ``+inf`` (BIN-140's rule), never reported.
    """
    (nl, kl), (nu, ku) = lower, upper

    def safe(n: int, k: int, h: int, p: float) -> float:
        try:
            return one_sided_arl(n, k, h, p)
        except NotComputableError:
            return math.inf

    def a_lo(a: int) -> float:
        return safe(nl, kl, a, p_u)

    def a_up(a: int) -> float:
        return safe(nu, ku, MAX_JOINT_STATES // (a + 1) - 1, 1.0 - p_l)

    lo, hi = 1, MAX_JOINT_STATES // 2 - 1
    if a_lo(lo) > a_up(lo):
        best = min(a_lo(lo), a_up(lo))
    else:
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if a_lo(mid) <= a_up(mid):
                lo = mid
            else:
                hi = mid
        best = max(min(a_lo(lo), a_up(lo)), min(a_lo(hi), a_up(hi)))
    return float(min(math.floor(best / 2.0), MAX_TARGET_ARL))
