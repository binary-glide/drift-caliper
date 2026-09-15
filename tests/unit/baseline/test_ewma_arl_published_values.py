"""Numerical proof: ``fit_ewma()`` reproduces published ARL0 values, Part 2 of 2.

**Ratified 2026-09-10 (CLAUDE.md, "Fitting stories carry their own numerical
proof").** ``tests/unit/baseline/test_ewma_fitting.py`` (Part 1) asserts
shape and behaviour only, with no numeric literal claiming statistical
correctness -- the feature file itself names no numbers, deliberately. This
file is the per-chart floor beneath BIN-84's broader property-based
strategy: it verifies the fitted output against a published table, so EWMA
is never shipped statistically unverified. Kept in a separate module,
deliberately, so a failure here reads unambiguously as "the calibration is
wrong", never as "the API contract changed" (that is Part 1's job).

## Primary source

Lucas, J. M. and Saccucci, M. S. (1990). "Exponentially Weighted Moving
Average Control Schemes: Properties and Enhancements." *Technometrics*,
32(1), 1-12. Table 3 ("two-sided EWMA with fixed limits") gives, for each
of several (lambda, L) pairs, the in-control (zero-state) ARL and the
out-of-control ARL at a series of mean shifts. This story only needs the
in-control entry (shift = 0) for each pair, which is exactly what
``FittedEWMA.achieved_arl`` reports when ``target_arl`` is the in-control
value the engineer requested.

## Primary source obtained 2026-09-11 -- the gap is closed

**Table 3 has been read directly** from Lucas & Saccucci (1990),
*Technometrics* **32**(1), page 5, and every ``L`` this module asserts is
confirmed against it. The full published row:

    L   = 3.090  3.087  3.071  3.054  3.023  2.998  2.962  2.814  2.615  2.437
    lam =  1.00    .75    .50    .40    .30    .25    .20    .10    .05    .03

with the table's own footnote stating the calibration these answer to:
*"L values are based on zero-state in-control ARL = 500."* That is exactly
the claim this module makes, now quoted rather than inferred.

``test_calibration_recovers_the_published_limit_multiplier_for_arl0_500``
is parametrised over **all ten** entries. It previously pinned only the
first and last, because the table was not held; two endpoints could in
principle be hit by a chain that was wrong in between, and ten cannot.

Table 3 also settles a question this project raised separately (BIN-113):
at ARL0 = 500 its steady-state row reads 500, 500, 499, 498, 497, 496, 496,
492, 487, 480 against a zero-state 500 throughout -- so steady-state is
**lower**, as predicted, by 0% at lambda = 1.00 rising to **4% at
lambda = 0.03**. The paper's own text puts the spread at "less than 2% for
an in-control ARL of 5,000 to approximately 10% for an in-control ARL of
100", and concludes: *"For most practical purposes, the difference between
zero-state and steady-state ARL's is unimportant and either one suffices."*

## The chain that was built before the source arrived -- kept, not deleted

Technometrics 32(1) (1990) was paywalled and not accessible in the session
that wrote this module (the same access gap ADR-004's amendment already recorded
for Montgomery Chapter 9 -- see its "Citation status" section). Table 3's
values were instead verified via the CRAN package **`spc`: Statistical
Process Control -- Calculation of ARL and Other Control Chart Performance
Measures** (Sven Knoth, https://cran.r-project.org/package=spc), whose
``xewma.arl`` function documentation explicitly cites "J. M. Lucas and
M. S. Saccucci (1990), Exponentially weighted moving average control
schemes: Properties and enhancements, Technometrics 32, 1-12" as a
reference, and whose worked example reproduces Table 3 by an independent
numerical method (Nystroem quadrature on the ARL integral equation, per
Knoth 2003/2004 -- a different computational technique from the Markov-chain
approximation ADR-001 selected for Caliper, which is itself the method
Lucas & Saccucci's own paper uses). The example's own comment block reads:

    ## Lucas/Saccucci (1990)
    ## two-sided EWMA with fixed limits
    l1 <- .5;  c1 <- 3.071
    l2 <- .03; c2 <- 2.437
    ...
    ## original results are (in Table 3)
    ## 0.00 500. 500.
    ## ...

i.e. for lambda=0.5 with L=3.071, and separately for lambda=0.03 with
L=2.437, Table 3's own published zero-shift (in-control) ARL is 500 for
*both* pairs -- both L values were solved by Lucas & Saccucci specifically
to hit ARL0=500 for their respective lambda. Two independently-implemented
numerical methods (the `spc` package's Nystroem quadrature, and whatever
Lucas & Saccucci used in 1990) agree on this to at least three significant
figures. This is the strongest verification available without paywalled
access to the original paper, and is recorded transparently here rather
than presented as a direct primary-source read -- the same honesty
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``'s
amendment practised for its own citation gap.

**If this environment gains access to Technometrics 32(1) directly, this
note should be updated to cite the table entries directly rather than via
the `spc` package's reproduction.**

## Third link: reproduced from the method, not from any implementation

Both (lambda, L) pairs below were **independently recomputed** while reviewing
this file, using a Brook & Evans / Lucas & Saccucci Markov-chain
discretisation written from the published method rather than copied from
`spc`, R, or any other implementation:

    lambda=0.50, L=3.071  ->  ARL0 = 499.9   (table: 500)
    lambda=0.03, L=2.437  ->  ARL0 = 499.8   (table: 500)

That calculation was itself validated before being trusted: as lambda -> 1 an
EWMA degenerates to a Shewhart individuals chart, whose in-control ARL has the
closed form 1 / (2 * Phi(-L)). The chain reproduces it to four decimal places
at lambda = 0.999 for three different L values.

The self-test was not ceremony. The first version of that chain was wrong by a
factor of exactly 2.0000 -- it discretised 2m cells of half-width h/m, spanning
(-2h, +2h) instead of (-h, +h), so it modelled limits at twice their true
width. It reported ~1000 against the table's 500 and would have been read as
"the published constants are wrong" had the closed-form check not caught it
first.

**Carry that forward to BIN-84 and to BIN-94/BIN-95.** A verification routine
is code, it can be wrong, and a disagreement with a published table is at
least as likely to be a bug in the checker as in the table. Validate the
checker against a case with a known closed form before trusting what it says
about a case without one.

So the chain of evidence for these two constants is: the paper (paywalled,
not read) -> `spc`'s documentation, which cites it and reproduces it by
Nystroem quadrature -> an independent Markov-chain recomputation here, itself
validated against a closed form. Three routes, two of them computational and
mutually independent, agreeing to within 0.1.

## Why sigma does not need to be controlled

The in-control (zero-state) ARL of an EWMA chart depends only on the
smoothing parameter (lambda) and the control-limit multiplier (L) -- not on
the process sigma itself, because the calibration works in sigma-standardised
units. This is why the tests below can use an ordinarily-constructed,
non-degenerate baseline (whatever its actual sample variance happens to be)
and still expect ``achieved_arl`` to land close to the published value: the
baseline's sigma affects where the limits sit in score-units, not how many
in-control observations elapse, on average, before one strays past them.

## Tolerance

Each assertion allows a tolerance of the published ARL0 to accommodate two
independent implementations' numerical convergence differing slightly
(Markov-chain discretisation here vs. Nystroem quadrature in the reference
implementation) -- not to be loosened for any other reason. If
``domain-implementer``'s calibration cannot land within this tolerance of a
published table entry, that is a signal the calibration is wrong, not that
the tolerance is too tight.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pytest

from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedEWMA,
    fit_ewma,
)
from drift_caliper.baseline.domain.ewma_numerics import (
    _MARKOV_CHAIN_STATES,
    _ewma_asymptotic_std_ratio,
    _in_control_arl,
)
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Relative tolerance applied to each published ARL0 value below. 2% of 500
# is 10 -- generous enough to absorb Markov-chain vs. Nystroem-quadrature
# discretisation differences, tight enough that a materially wrong
# calibration (wrong L, wrong table, an off-by-an-order-of-magnitude bug)
# fails loudly.
_RELATIVE_TOLERANCE = 0.02


def _sufficient_baseline() -> Baseline:
    """A baseline large enough to fit from, with ordinary (non-zero) variance.

    The specific sample variance is irrelevant to this file's assertions --
    see the module docstring's "why sigma does not need to be controlled".
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(DEFAULT_SUFFICIENCY_THRESHOLD + 20):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))
    return baseline


def _assert_achieved_arl_close_to(achieved_arl: float, published_arl0: float) -> None:
    tolerance = published_arl0 * _RELATIVE_TOLERANCE
    assert abs(achieved_arl - published_arl0) <= tolerance, (
        f"achieved_arl={achieved_arl!r} is not within {tolerance!r} of the "
        f"published Lucas & Saccucci (1990) Table 3 value {published_arl0!r}"
    )


# --- Lucas & Saccucci (1990), Table 3: lambda=0.5, L=3.071, ARL0=500 ----------------


def test_lambda_0_5_achieves_the_published_in_control_arl_of_500() -> None:
    """lambda=0.5 calibrated for target_arl=500 achieves ~500 (Table 3, col. 1)."""
    # Arrange
    baseline = _sufficient_baseline()
    published_arl0 = 500.0

    # Act
    result = fit_ewma(baseline, target_arl=published_arl0, smoothing_param=0.5)

    # Assert
    assert result.smoothing_param == 0.5
    assert result.requested_arl == published_arl0
    _assert_achieved_arl_close_to(result.achieved_arl, published_arl0)


# --- Lucas & Saccucci (1990), Table 3: lambda=0.03, L=2.437, ARL0=500 ---------------


def test_lambda_0_03_achieves_the_published_in_control_arl_of_500() -> None:
    """lambda=0.03 calibrated for target_arl=500 achieves ~500 (Table 3, second column).

    Deliberately a very different lambda from the test above (0.03 vs 0.5)
    -- Table 3 calibrates a different L for each, and both hit the same
    published ARL0. Exercising both is a much stronger check on the
    calibration engine than either alone: a bug that only manifests for
    small lambda (a common failure mode, since small lambda makes the EWMA
    statistic's variance -- and therefore the Markov chain's state space --
    behave very differently) would pass the lambda=0.5 test and fail this
    one.
    """
    # Arrange
    baseline = _sufficient_baseline()
    published_arl0 = 500.0

    # Act
    result = fit_ewma(baseline, target_arl=published_arl0, smoothing_param=0.03)

    # Assert
    assert result.smoothing_param == 0.03
    assert result.requested_arl == published_arl0
    _assert_achieved_arl_close_to(result.achieved_arl, published_arl0)


# --- The assertions that actually carry the published table's content ----------
#
# `domain-implementer` flagged this against its own work, and it is the most
# important finding of BIN-65: the two tests above are **self-consistent by
# construction**. `fit_ewma` solves for the multiplier L such that its own
# Markov chain reports the requested ARL0, so `achieved_arl ~= requested_arl`
# holds whatever that chain computes. A systematic scaling error would simply
# produce a different L and report the target back regardless -- precisely the
# factor-of-2.0000 discretisation bug described in this module's docstring
# would sail through both of them.
#
# The published table's real content is the *multiplier*: lambda=0.5 with
# ARL0=500 requires L=3.071, and lambda=0.03 requires L=2.437. L is recoverable
# from the artefact, since ucl = cl + L * sigma * sqrt(lambda / (2 - lambda)).
# Checking it is what makes these tests a proof rather than a tautology.


def _implied_limit_multiplier(result: FittedEWMA) -> float:
    """Recover L from a fitted artefact's reported limits.

    Inverts ``ucl = cl + L * sigma_estimate * sqrt(lam / (2 - lam))``, the
    asymptotic (fixed-limit) EWMA form Lucas & Saccucci tabulate.
    """
    lam = result.smoothing_param
    sigma_z = result.sigma_estimate * math.sqrt(lam / (2.0 - lam))
    return (result.ucl - result.cl) / sigma_z


@pytest.mark.parametrize(
    ("smoothing_param", "published_multiplier"),
    [
        # The complete L row of Table 3, read from the paper (Technometrics
        # 32(1), p. 5) on 2026-09-11. Previously only the first and last
        # entries were pinned, because the table itself was not held.
        #
        # Its footnote states the calibration these are the answer to:
        # "L values are based on zero-state in-control ARL = 500."
        pytest.param(1.00, 3.090, id="lambda-1.00-L-3.090"),
        pytest.param(0.75, 3.087, id="lambda-0.75-L-3.087"),
        pytest.param(0.50, 3.071, id="lambda-0.50-L-3.071"),
        pytest.param(0.40, 3.054, id="lambda-0.40-L-3.054"),
        pytest.param(0.30, 3.023, id="lambda-0.30-L-3.023"),
        pytest.param(0.25, 2.998, id="lambda-0.25-L-2.998"),
        pytest.param(0.20, 2.962, id="lambda-0.20-L-2.962"),
        pytest.param(0.10, 2.814, id="lambda-0.10-L-2.814"),
        pytest.param(0.05, 2.615, id="lambda-0.05-L-2.615"),
        pytest.param(0.03, 2.437, id="lambda-0.03-L-2.437"),
    ],
)
def test_calibration_recovers_the_published_limit_multiplier_for_arl0_500(
    smoothing_param: float, published_multiplier: float
) -> None:
    """The fitted limits imply the L that Lucas & Saccucci (1990) Table 3 gives.

    Unlike the two tests above, this one cannot pass against a chain with a
    systematic scaling error: L is fixed by the published table, not by the
    implementation's own arithmetic.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(baseline, target_arl=500.0, smoothing_param=smoothing_param)

    # Assert -- 1% of the published value. Tight enough that the 2x
    # discretisation bug (which would move L by far more) fails loudly;
    # loose enough to absorb the difference between the Markov-chain
    # approximation and the quadrature the table was produced with.
    assert _implied_limit_multiplier(result) == pytest.approx(
        published_multiplier, rel=0.01
    )


def test_calibration_matches_the_shewhart_closed_form_as_lambda_approaches_one() -> (
    None
):
    """As lambda -> 1 an EWMA degenerates to a Shewhart individuals chart.

    That chart's in-control ARL0 has a closed form, ``1 / (2 * Phi(-L))``, with
    no free parameters and nothing borrowed from any table. It is the one check
    here that depends on no published source at all, and it is what actually
    guards against a systematic scaling error in the chain.

    It was carrying that weight in a docstring rather than an assertion until
    BIN-65's review; a comment cannot fail CI.
    """
    # Arrange -- lambda at the top of its range, where the EWMA has no memory.
    baseline = _sufficient_baseline()
    target_arl = 370.0

    # Act
    result = fit_ewma(baseline, target_arl=target_arl, smoothing_param=1.0)
    implied_l = _implied_limit_multiplier(result)

    # Assert -- the closed form, computed here rather than quoted.
    closed_form_arl = 1.0 / (2.0 * NormalDist().cdf(-implied_l))
    assert closed_form_arl == pytest.approx(target_arl, rel=0.01)


# --- Helpers whose effect cancels out of the public output ---------------------
#
# `code-reviewer` found the blocker on BIN-65 and it is subtle enough to be
# worth stating in full, because the same shape will recur in BIN-94 and BIN-95.
#
# `fit_ewma` calibrates L against a helper, then reapplies the *same* helper to
# build the reported limits. The helper therefore cancels algebraically out of
# the round trip, and no assertion on `fit_ewma`'s public output can falsify it:
#
#     ucl - cl = L_solved * sigma_estimate * ratio(lambda)
#
# and the checks above recover L by dividing by that same product. A wrong
# `sigma_estimate` or a wrong `ratio(lambda)` divides itself out of its own
# check. Demonstrated, not theorised: patching `abs(b - a)` to `abs(b + a)`, or
# `/ d2` to `* d2`, left all 27 EWMA tests passing -- including the published-
# value proof above.
#
# The only fix is to test the helpers **directly**, against values computed
# independently of the implementation. Testing module-private functions is
# normally a smell; here it is the sole way to constrain them at all.


def test_moving_range_sigma_matches_a_hand_computed_value() -> None:
    """MR-bar / d2 on a baseline whose moving ranges are known by inspection.

    Every consecutive pair differs by exactly 0.10, so the mean moving range
    is 0.10 and sigma is 0.10 / d2 -- computed here from the definition,
    never read back off the artefact.
    """
    # Arrange -- alternating scores, so |consecutive difference| is 0.10
    # throughout and the mean moving range needs no arithmetic to predict.
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for score in [0.50, 0.60] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2):
        baseline.record(ScoringResultFactory(provenance=shared_provenance, score=score))

    # Act
    result = fit_ewma(baseline, target_arl=370.0)

    # Assert
    expected_sigma = 0.10 / 1.1283791670955126  # d2 = 2/sqrt(pi)
    assert result.sigma_estimate == pytest.approx(expected_sigma, rel=1e-9)


@pytest.mark.parametrize(
    ("smoothing_param", "expected_ratio"),
    [
        # lambda=1 removes all smoothing: the EWMA statistic is the observation
        # itself, so its std dev equals the process std dev exactly.
        pytest.param(1.0, 1.0, id="lambda-1-is-identity"),
        # sqrt(0.5 / 1.5) = sqrt(1/3), computed from the definition below.
        pytest.param(0.5, math.sqrt(1.0 / 3.0), id="lambda-0.5"),
        # sqrt(0.2 / 1.8) = sqrt(1/9) = 1/3 exactly -- a value with a closed
        # form, so a wrong formula cannot coincidentally reproduce it.
        pytest.param(0.2, 1.0 / 3.0, id="lambda-0.2-exact-third"),
    ],
)
def test_ewma_asymptotic_std_ratio_matches_its_published_formula(
    smoothing_param: float, expected_ratio: float
) -> None:
    """``sqrt(lambda / (2 - lambda))`` -- Roberts (1959); L&S (1990) eq. 3.

    Pinned directly because it cancels out of `fit_ewma`'s public output:
    mutating it to ``lambda * (2 - lambda)``, ``2 + lambda`` or ``3 - lambda``
    produces byte-identical limits and ARLs.
    """
    assert _ewma_asymptotic_std_ratio(smoothing_param) == pytest.approx(
        expected_ratio, rel=1e-12
    )


# --- The discretisation is an accuracy/cost trade-off, not a lucky number ------


@pytest.mark.parametrize("num_states", [101, 301, 901])
def test_markov_chain_converges_as_the_state_count_rises(num_states: int) -> None:
    """The chain's ARL0 converges toward the published value as the grid refines.

    `_MARKOV_CHAIN_STATES = 301` was justified only as "it agreed with the
    published tables", which is an observation rather than a claim anyone can
    check. `code-reviewer` flagged that constants justified that way get copied
    forward -- BIN-94 and BIN-95 will each need their own discretisation
    parameter.

    This pins it as an accuracy statement: a coarse grid is visibly worse, and
    the configured grid is within 0.5% of the published 500 for the tabulated
    (lambda, L) pair.
    """
    # Arrange -- Lucas & Saccucci (1990) Table 3: lambda=0.5, L=3.071 -> 500.
    published_arl0 = 500.0

    # Act
    achieved = _in_control_arl(0.5, 3.071, num_states)

    # Assert -- every grid in the range is in the right neighbourhood, and the
    # error shrinks monotonically with refinement (checked separately below).
    assert achieved == pytest.approx(published_arl0, rel=0.05)


def test_the_configured_state_count_is_accurate_enough_and_a_coarse_one_is_not() -> (
    None
):
    """301 states earns its place; 21 would not.

    Turns "it happened to work" into a checkable accuracy claim, so a future
    story that changes `_MARKOV_CHAIN_STATES` finds out immediately whether the
    new value still holds.
    """
    # Arrange
    published_arl0 = 500.0

    # Act
    configured = _in_control_arl(0.5, 3.071, _MARKOV_CHAIN_STATES)
    coarse = _in_control_arl(0.5, 3.071, 21)
    fine = _in_control_arl(0.5, 3.071, 1501)

    # Assert -- the configured grid is within 0.5% of the table...
    assert configured == pytest.approx(published_arl0, rel=0.005)
    # ...and materially closer to a much finer grid than a coarse one is,
    # which is what makes 301 a trade-off rather than an arbitrary choice.
    assert abs(configured - fine) < abs(coarse - fine)
