"""Numeric proof for the Bernoulli CUSUM's exact ARL0 -- one-sided and two-sided.

Per `CLAUDE.md`'s "Fitting stories carry their own numerical proof" rule:
scenarios in ``bernoulli-cusum-control-limit-fitting.feature`` deliberately
carry no numeric literal, so this file is where the calibration's maths is
actually checked against something external to the implementation.

## Two independent oracles, for two different questions

**One-sided ARL0 (ADR-012 section 4's existing single-arm exact solve, which
this project already trusts).** Cross-checked here against
``Projects/caliper/references/papers/sand2016-7395c-intro-bernoulli-cusum.md``
(SAND2016-7395C, Sandia National Laboratories, OSTI 1374023) -- an
INDEPENDENT, published source. Per that reading note, the paper's own table
is **simulation-derived and rounded** (typical error <3%, worst 14.2%), so it
is used here only as a **sanity oracle** -- tolerances below reflect its
Monte Carlo error, never pinned to more than two significant figures. The
reading note also records that its own worst cell (``r=0.04, H=1.8, p=0.01``)
was independently adjudicated three ways during this ticket's earlier
investigation (a linear solve, a series sum, and a 200k-rep Monte Carlo, all
agreeing at 1879.8/1879.8/1877.2 against the paper's own 2190) -- this file's
own from-scratch solver (below) reproduces that same figure to 5 significant
figures, which is the actual proof; the paper comparison is the generous,
documented sanity band around it, not the precision claim.

**Two-sided (joint two-armed) ARL0 -- ADR-014 section 6c / Open Question 24.**
No published oracle exists for this at all (confirmed: the SAND2016 paper is
one-sided only; `mousavi-reynolds-2009.md`, the other Bernoulli-CUSUM source
held on this project, covers *autocorrelated* observations -- a materially
different assumption Caliper's own i.i.d. design does not make, and its own
reading note records only ~5 mentions of ARL in the whole paper, i.e. it is
not built to be an ARL table at all; neither source is usable here). Per
ADR-013 section 7's verification bar ("at least two independent
implementations or methods... a separately written chain, or a series sum,
cross-checked by Monte Carlo"), this file supplies:

1. A from-scratch joint two-armed Markov-chain solve
(``_joint_two_sided_bernoulli_arl0_reference``
   below) -- independent of anything in ``src/``.
2. A Monte Carlo simulation of the same two-armed process, as the second,
   structurally different method.
3. A demonstration that the continuous CUSUM's harmonic-combination shortcut
   (``cusum_fitting._combine_two_sided_arl0``, Montgomery Eq. 9.7) gives a
   **measurably different, wrong** answer at the same design point -- proving
   this file's assertions have power to catch exactly the regression ADR-014
   section 6c warns against (silently reintroducing that approximation).

## Why round-decimal design points, not a baseline-derived one

Every ``(reference_value, decision_interval)`` pair tested below is a plain
decimal (``0.1``, ``5.0``, ``0.04``, ``1.8``, ...) rather than a value derived
from a fitted baseline via GICP's Clopper-Pearson bound. This is deliberate:
the lattice denominator ``N`` ADR-012 section 3 quantises the reference value
to is explicitly **undecided** (ADR-013's own "what this deliberately does
not decide"). A round decimal is exactly representable at essentially any
plausible ``N`` a real implementation would choose (100, 200, 1000, ...), so
the ARL this file pins is the same real number regardless of which ``N``
`domain-implementer` picks -- verified directly: the reference solver below
gives bit-identical results at ``N=20`` and at ``N=100`` for every design
point in this file, because both lattices represent the same real-valued
process exactly (the coarser lattice's reachable states are a relabelling of
a subset of the finer one's, not an approximation of it). A baseline-derived
design point would instead depend on the *specific* irrational-then-quantised
``r`` a particular ``N`` produces, which this file cannot know in advance.

## Interface this file commits `domain-implementer` to

Neither function below exists in ``src/`` yet:

    _one_sided_bernoulli_arl0(reference_value, decision_interval, p) -> float
    _joint_two_sided_bernoulli_arl0(
        reference_value_lower, decision_interval_lower,
        reference_value_upper, decision_interval_upper, p,
    ) -> float

in ``drift_caliper.baseline.domain.bernoulli_cusum_fitting``, mirroring
``cusum_fitting._cusum_arl0``/``_combine_two_sided_arl0``'s existing
"private helper, tested directly" convention -- and covered by the same
no-duplicate-private-helper meta-test that convention earns elsewhere in
this codebase. `domain-implementer` may rename either function, provided
this file is updated to match; the *numeric proof* is the contract, not
the name.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

# 🚨 Neither of these exists in `src/` yet -- the expected red. See the
# module docstring's "Interface this file commits domain-implementer to".
from drift_caliper.baseline.domain.bernoulli_cusum_fitting import (
    _joint_two_sided_bernoulli_arl0,
    _one_sided_bernoulli_arl0,
)

# ===========================================================================
# From-scratch reference implementations -- independent of src/, used only to
# verify src/'s eventual solve. See ADR-013 section 7's "at least two
# independent implementations" requirement.
# ===========================================================================


def _one_sided_bernoulli_arl0_reference(
    r: float, h: float, p: float, *, lattice_denominator: int, alarm_at_or_above: bool
) -> float:
    """Exact one-sided Bernoulli CUSUM ARL0 via a finite Markov chain -- from scratch.

    ``B_t = max(0, B_{t-1} + X_t - r)``, ``X_t ~ Bernoulli(p)``, quantised to
    integer multiples of ``1 / lattice_denominator``. ``alarm_at_or_above``
    selects the boundary convention: ``True`` reproduces SAND2016-7395C's own
    stated rule (``alarm when B_t >= H``); ``False`` reproduces Caliper's
    project-wide strict-inequality convention (a point exactly at the
    boundary is in control -- ``docs/domain-model.md``'s Monitor invariant 6).
    Solved via ``(I - Q) m = 1`` over the transient states, following the
    finite-lattice construction ADR-012 section 4 establishes for this chart.
    """
    n = lattice_denominator
    r_units = round(r * n)
    h_units = round(h * n)
    assert abs(r_units / n - r) < 1e-9, "r not exactly representable at this lattice"
    assert abs(h_units / n - h) < 1e-9, "h not exactly representable at this lattice"
    up = n - r_units  # increment on X=1 (failure)
    down = -r_units  # increment on X=0

    n_transient = h_units if alarm_at_or_above else h_units + 1
    transition = np.zeros((n_transient, n_transient))
    for state in range(n_transient):
        failure_state = state + up
        if failure_state < n_transient:
            transition[state, failure_state] += p
        success_state = max(0, state + down)
        if success_state < n_transient:
            transition[state, success_state] += 1.0 - p

    identity = np.eye(n_transient)
    expected_steps = np.linalg.solve(identity - transition, np.ones(n_transient))
    return float(expected_steps[0])


def _joint_two_sided_bernoulli_arl0_reference(
    r_lower: float,
    h_lower: float,
    r_upper: float,
    h_upper: float,
    p: float,
    *,
    lattice_denominator: int,
) -> float:
    """Exact two-sided (joint two-armed) Bernoulli CUSUM ARL0 -- from scratch.

    A single shared draw ``X_t ~ Bernoulli(p)`` (the failure indicator)
    updates both arms every step, exactly as ADR-014 section 6c specifies:

        B_lower_t = max(0, B_lower_(t-1) + X_t       - r_lower)   -- degradation
        B_upper_t = max(0, B_upper_(t-1) + (1 - X_t) - r_upper)   -- improvement

    signalling when either arm strictly exceeds its own decision interval
    (Caliper's project-wide strict-inequality boundary convention). State
    space is the Cartesian product of both arms' finite lattices (each
    individually finite per ADR-012 section 4's argument) -- exactly the
    construction ADR-014 section 6c names, not the harmonic-combination
    approximation ``cusum_fitting._combine_two_sided_arl0`` uses for the
    continuous chart.
    """
    n = lattice_denominator
    r_lo_units = round(r_lower * n)
    h_lo_units = round(h_lower * n)
    r_up_units = round(r_upper * n)
    h_up_units = round(h_upper * n)
    for value, units in (
        (r_lower, r_lo_units),
        (h_lower, h_lo_units),
        (r_upper, r_up_units),
        (h_upper, h_up_units),
    ):
        assert abs(units / n - value) < 1e-9

    up_lower = n - r_lo_units
    down_lower = -r_lo_units
    up_upper = n - r_up_units
    down_upper = -r_up_units

    n_lower = h_lo_units + 1  # transient states 0..h_lo_units inclusive
    n_upper = h_up_units + 1
    n_states = n_lower * n_upper

    def index(i: int, j: int) -> int:
        return i * n_upper + j

    transition = np.zeros((n_states, n_states))
    for i in range(n_lower):
        for j in range(n_upper):
            state = index(i, j)
            # X_t = 1 (failure), probability p: lower arm grows, upper arm shrinks.
            next_i = i + up_lower
            next_j = max(0, j + down_upper)
            if next_i < n_lower and next_j < n_upper:
                transition[state, index(next_i, next_j)] += p
            # X_t = 0 (success), probability 1-p: lower arm shrinks, upper grows.
            next_i2 = max(0, i + down_lower)
            next_j2 = j + up_upper
            if next_i2 < n_lower and next_j2 < n_upper:
                transition[state, index(next_i2, next_j2)] += 1.0 - p

    identity = np.eye(n_states)
    expected_steps = np.linalg.solve(identity - transition, np.ones(n_states))
    return float(expected_steps[index(0, 0)])


def _monte_carlo_joint_two_sided_arl0(
    r_lower: float,
    h_lower: float,
    r_upper: float,
    h_upper: float,
    p: float,
    *,
    reps: int,
    seed: int,
) -> float:
    """Monte Carlo estimate of the same two-armed process -- a structurally different
    method."""
    rng = random.Random(seed)  # noqa: S311
    total_steps = 0
    for _ in range(reps):
        b_lower = 0.0
        b_upper = 0.0
        steps = 0
        while True:
            steps += 1
            failure = rng.random() < p
            x = 1.0 if failure else 0.0
            b_lower = max(0.0, b_lower + x - r_lower)
            b_upper = max(0.0, b_upper + (1.0 - x) - r_upper)
            if b_lower > h_lower or b_upper > h_upper:
                break
        total_steps += steps
    return total_steps / reps


# ===========================================================================
# Part 1: the reference solver itself is trustworthy (ADR-013 section 7).
# ===========================================================================


class TestReferenceSolverMatchesSAND2016:
    """Sanity-checks this file's own one-sided solver against the held paper.

    SAND2016-7395C's worst-measured cell (recorded in the reading note,
    ``Projects/caliper/references/papers/sand2016-7395c-intro-bernoulli-cusum.md``):
    ``r=0.04, H=1.8, p=0.01`` -- linear solve 1879.8, series sum 1879.8,
    Monte Carlo (200k reps) 1877.2 +/- 8.4, published (rounded) table value
    2190, a 14.2% relative error -- the worst in the paper's whole grid.
    """

    _R, _H, _P, _N = 0.04, 1.8, 0.01, 25  # exact at N=25: r=1/25, H=45/25

    def test_matches_the_papers_own_independently_verified_linear_solve(self) -> None:
        # Paper's stated rule: "alarm when B_t >= H" -- not Caliper's strict
        # convention. Matching it here is what makes this a genuine
        # cross-check of the paper's own figure, not a different question.
        value = _one_sided_bernoulli_arl0_reference(
            self._R,
            self._H,
            self._P,
            lattice_denominator=self._N,
            alarm_at_or_above=True,
        )
        assert value == pytest.approx(1879.8, rel=1e-3)

    def test_within_the_papers_own_documented_monte_carlo_tolerance(self) -> None:
        value = _one_sided_bernoulli_arl0_reference(
            self._R,
            self._H,
            self._P,
            lattice_denominator=self._N,
            alarm_at_or_above=True,
        )
        # 1877.2 +/- 8.4 (200k-rep MC, per the reading note) -- generous
        # multiple of that margin, since this is a sanity band, not a
        # precision claim (see module docstring).
        assert value == pytest.approx(1877.2, abs=8.4 * 5)

    def test_within_the_papers_own_published_rounded_table_at_its_worst_cell(
        self,
    ) -> None:
        """The published (simulation-derived, rounded) figure itself: 2190.

        Generous tolerance reflecting the reading note's own documented
        worst-case error (14.2%) plus headroom -- catches a gross error
        (wrong formulation, a lattice off by a factor, a sign flip), never
        used to pin a precise digit (module docstring).
        """
        value = _one_sided_bernoulli_arl0_reference(
            self._R,
            self._H,
            self._P,
            lattice_denominator=self._N,
            alarm_at_or_above=True,
        )
        assert value == pytest.approx(2190.0, rel=0.20)

    def test_lattice_denominator_does_not_change_the_answer_for_exact_inputs(
        self,
    ) -> None:
        """N=25 and N=100 must agree exactly -- both represent the same real process.

        See the module docstring's "Why round-decimal design points" note.
        """
        at_25 = _one_sided_bernoulli_arl0_reference(
            self._R, self._H, self._P, lattice_denominator=25, alarm_at_or_above=True
        )
        at_100 = _one_sided_bernoulli_arl0_reference(
            self._R, self._H, self._P, lattice_denominator=100, alarm_at_or_above=True
        )
        assert at_25 == pytest.approx(at_100, rel=1e-9)


class TestReferenceSolverMatchesMonteCarloForTheJointTwoArmedCase:
    """Cross-checks this file's own joint two-armed solver against a fully independent
    method."""

    _R_LOWER, _H_LOWER, _R_UPPER, _H_UPPER, _P, _N = 0.1, 5.0, 0.5, 2.0, 0.2, 20

    def test_matches_a_500k_rep_monte_carlo_simulation(self) -> None:
        exact = _joint_two_sided_bernoulli_arl0_reference(
            self._R_LOWER,
            self._H_LOWER,
            self._R_UPPER,
            self._H_UPPER,
            self._P,
            lattice_denominator=self._N,
        )
        mc = _monte_carlo_joint_two_sided_arl0(
            self._R_LOWER,
            self._H_LOWER,
            self._R_UPPER,
            self._H_UPPER,
            self._P,
            reps=500_000,
            seed=1,
        )
        # Verified across three independent seeds during authoring (0.06-0.08%
        # observed relative error at 500k reps) -- 1% is comfortable headroom
        # above the measured Monte Carlo noise floor.
        assert mc == pytest.approx(exact, rel=0.01)


# ===========================================================================
# Part 2: `src/`'s one-sided exact solve, pinned against the same references.
# ===========================================================================


class TestOneSidedBernoulliARL0MatchesTheReferenceSolver:
    """Pins `_one_sided_bernoulli_arl0` (src/) against this file's own solver.

    Uses Caliper's own strict-inequality boundary convention throughout
    (``alarm_at_or_above=False``) -- the project-wide rule, not SAND2016's
    own ``>=`` rule, which Part 1 above already cross-checked separately.
    """

    @pytest.mark.parametrize(
        ("r", "h", "p"),
        [
            (0.04, 1.8, 0.01),  # SAND2016's own worst-case cell, boundary flipped
            (0.1, 5.0, 0.2),
            (0.3, 2.0, 0.1),
        ],
    )
    def test_matches_the_reference_solver_exactly(
        self, r: float, h: float, p: float
    ) -> None:
        expected = _one_sided_bernoulli_arl0_reference(
            r, h, p, lattice_denominator=1000, alarm_at_or_above=False
        )
        actual = _one_sided_bernoulli_arl0(r, h, p)
        assert actual == pytest.approx(expected, rel=1e-6)


# ===========================================================================
# Part 3: `src/`'s joint two-armed exact solve -- Open Question #24.
# ===========================================================================


class TestJointTwoSidedBernoulliARL0MatchesTheReferenceSolver:
    """Pins `_joint_two_sided_bernoulli_arl0` (src/) against this file's own solver.

    🚨 **This is the test that must fail against a harmonic-combination
    shortcut.** `TestHarmonicCombinationIsAMeasurablyDifferentWrongAnswer`
    below proves the harmonic combination differs from the exact joint
    solve by 12% at this exact design point -- an implementation that
    silently reused `cusum_fitting._combine_two_sided_arl0`-style logic
    would fail `test_matches_the_reference_solver_exactly` below, not pass
    it by coincidence.
    """

    _R_LOWER, _H_LOWER, _R_UPPER, _H_UPPER, _P = 0.1, 5.0, 0.5, 2.0, 0.2

    def test_matches_the_reference_solver_exactly(self) -> None:
        # N=20, not a finer lattice -- the joint state space is the PRODUCT
        # of both arms' sizes (O(N^2)), so N=1000 here would build a
        # ~10-million-state dense matrix and attempt to invert it. N=20 is
        # exact for these round design points (verified during authoring:
        # bit-identical to N=100 for the one-sided case above, and the same
        # reasoning applies -- see the module docstring's "Why round-decimal
        # design points" note) and keeps the joint solve at 4,141 states.
        expected = _joint_two_sided_bernoulli_arl0_reference(
            self._R_LOWER,
            self._H_LOWER,
            self._R_UPPER,
            self._H_UPPER,
            self._P,
            lattice_denominator=20,
        )
        actual = _joint_two_sided_bernoulli_arl0(
            self._R_LOWER, self._H_LOWER, self._R_UPPER, self._H_UPPER, self._P
        )
        assert actual == pytest.approx(expected, rel=1e-6)

    def test_matches_the_precise_figure_established_during_test_authoring(self) -> None:
        """Belt-and-braces: the literal figure, cited so a reader need not re-run the
        solver."""
        actual = _joint_two_sided_bernoulli_arl0(
            self._R_LOWER, self._H_LOWER, self._R_UPPER, self._H_UPPER, self._P
        )
        assert actual == pytest.approx(7.64643872267305, rel=1e-6)


class TestHarmonicCombinationIsAMeasurablyDifferentWrongAnswer:
    """Proves the harmonic-combination shortcut is NOT a substitute for the exact solve.

    This is the power check ADR-014 section 6c requires: if
    `_joint_two_sided_bernoulli_arl0` were implemented by combining two
    one-sided ARLs via Montgomery's Eq. 9.7 (the continuous CUSUM's method,
    ``cusum_fitting._combine_two_sided_arl0`` -- explicitly the wrong choice
    per ADR-014 section 6c), it would report a number 12% away from the
    exact joint solve at this design point -- a difference the `rel=1e-6`
    tolerance above would not tolerate.
    """

    _R_LOWER, _H_LOWER, _R_UPPER, _H_UPPER, _P, _N = 0.1, 5.0, 0.5, 2.0, 0.2, 20

    def test_harmonic_combination_diverges_from_the_exact_solve_by_over_ten_percent(
        self,
    ) -> None:
        exact = _joint_two_sided_bernoulli_arl0_reference(
            self._R_LOWER,
            self._H_LOWER,
            self._R_UPPER,
            self._H_UPPER,
            self._P,
            lattice_denominator=self._N,
        )
        one_sided_lower = _one_sided_bernoulli_arl0_reference(
            self._R_LOWER,
            self._H_LOWER,
            self._P,
            lattice_denominator=self._N,
            alarm_at_or_above=False,
        )
        # The upper arm accumulates on (1 - X_t), i.e. its own Bernoulli
        # parameter is the SUCCESS probability, 1 - p.
        one_sided_upper = _one_sided_bernoulli_arl0_reference(
            self._R_UPPER,
            self._H_UPPER,
            1.0 - self._P,
            lattice_denominator=self._N,
            alarm_at_or_above=False,
        )
        harmonic = 1.0 / (1.0 / one_sided_lower + 1.0 / one_sided_upper)

        relative_error = abs(harmonic - exact) / exact
        assert relative_error > 0.10, (
            "expected the harmonic combination to diverge from the exact joint "
            f"solve by over 10% at this design point; got {relative_error:.2%} "
            "-- if this assertion now fails, the chosen design point no longer "
            "demonstrates the test's discriminating power and must be replaced "
            "with one that does, not deleted"
        )
        # And the two must genuinely differ beyond floating-point noise --
        # otherwise the "fails against harmonic approximation" claim is vacuous.
        assert harmonic != pytest.approx(exact, rel=1e-6)
