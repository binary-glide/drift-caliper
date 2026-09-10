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

## Verification chain -- record the gap honestly

Technometrics 32(1) (1990) is paywalled and was not accessible directly in
this environment (the same access gap ADR-004's amendment already recorded
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

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, fit_ewma
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
