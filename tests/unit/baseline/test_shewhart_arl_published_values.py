"""Numerical proof: ``fit_shewhart()`` matches its own closed-form calibration.

**Ratified 2026-09-10 (CLAUDE.md, "Fitting stories carry their own numerical
proof").** ``tests/unit/baseline/test_shewhart_fitting.py`` (Part 1) asserts
shape and behaviour only, with no numeric literal claiming statistical
correctness -- the feature file itself names no numbers, deliberately. This
file is the per-chart floor beneath BIN-84's broader property-based
strategy: it verifies the fitted output against ground truth, so Shewhart is
never shipped statistically unverified. Kept in a separate module,
deliberately, mirroring
``tests/unit/baseline/test_ewma_arl_published_values.py`` and
``tests/unit/baseline/test_cusum_arl_published_values.py``'s own discipline
throughout.

## Why this file needs no published table, unlike its siblings

EWMA's in-control ARL0 needs a Markov-chain approximation (Lucas & Saccucci
1990) and CUSUM's needs Siegmund's (1985) corrected diffusion approximation
-- both are *approximations* to a quantity with no simpler closed form, so
both stories' numerical proofs anchor against externally published or
independently computed values, with a documented (paywalled) citation gap.

**The Shewhart I-chart has no such gap, because its calibration has an
exact closed form.** For a two-sided chart with fixed limits at
``+/- L`` sigma under the normality assumption (BIN-95 A4), the in-control
ARL0 is:

    ARL0(L) = 1 / alpha = 1 / (2 * (1 - Phi(L))) = 1 / (2 * Phi(-L))

where ``alpha = 2 * (1 - Phi(L))`` is the two-sided false alarm probability
per observation (one tail beyond ``+L`` sigma, one beyond ``-L`` sigma) and
``Phi`` is the standard normal CDF. This is not an approximation needing
external verification against a table -- it *is* the definition of a
two-sided Type I error rate under normality, and it is directly invertible:

    L(ARL0) = Phi^-1(1 - 1 / (2 * ARL0))

Both directions are computed below using ``statistics.NormalDist`` (Python's
standard-library implementation of the normal distribution, not something
this project needs to independently verify -- it is stdlib, not a
project-specific approximation), reproduced fresh in this file and never
imported from ``drift_caliper.baseline.domain.shewhart_fitting`` -- see "Helpers
whose effect cancels out" below for why that independence matters even
though the relationship is exact.

## The classical 3-sigma result, as a sanity anchor

The specific pairing ``L = 3.0 -> ARL0 ~= 370.4`` is one of the most widely
cited facts in statistical process control (NIST/SEMATECH's *Engineering
Statistics Handbook*, S6.2.1; Montgomery's *Introduction to Statistical
Quality Control*) -- ubiquitous enough that it needs no paywalled primary
source to corroborate; it is exactly what the closed form above computes at
``L = 3.0``, so this file treats it as a sanity check on the closed-form
helper, not the helper's justification. The helper's justification is the
definition of a normal tail probability, verifiable from ``statistics``
directly.

## d_2 is derived, not cited

``drift_caliper.baseline.domain.spc_numerics``'s ``_MOVING_RANGE_D2`` was
cross-verified only against three secondary sources on BIN-65 -- never derived.
It turns out to need no source at all. For a moving
range of span 2, ``d_2`` is the expected value of ``|X1 - X2|`` for
``X1, X2`` iid standard normal. Since ``X1 - X2 ~ N(0, 2)``, and
``E[|Z|] = sigma * sqrt(2 / pi)`` for ``Z ~ N(0, sigma^2)`` (the standard
half-normal mean identity), substituting ``sigma = sqrt(2)``:

    d_2 = sqrt(2) * sqrt(2 / pi) = 2 / sqrt(pi)

Derived and checked below. The constant is now stored **as that expression**
(``2.0 / math.sqrt(math.pi)``), not as the rounded ``1.128`` tables print;
the citation chain BIN-65 built is gone, because a derivation supersedes it.

Worth carrying forward: some "published constants" are measurements and some
are arithmetic. Only the first kind needs a source, and it is worth asking
which before going hunting -- per this story's instruction to derive or corroborate
``d_2`` rather than inherit its prior verification.

## Helpers whose effect cancels out -- checked even though the relationship is exact

`code-reviewer` found on BIN-65 and BIN-94 that a helper used both to
calibrate a parameter and to report the achieved value back divides itself
out of any assertion made only on public output. Shewhart's calibration is
an exact bijection rather than an approximation with a free internal
parameter, which makes this trap structurally less likely here -- but "less
likely" is not "impossible": if ``fit_shewhart`` computed ``sigma_multiplier``
and ``achieved_arl`` through a *shared* internal helper with, say, a
forgotten factor of two on the false alarm probability, the round trip
would still self-consistently report ``achieved_arl == requested_arl``,
because both directions would be wrong by the same mistake. The fix is the
same one BIN-65/BIN-94 used: check the *chart-specific* reported field
(``sigma_multiplier``) against a value computed independently of the
implementation, not only that ``achieved_arl`` echoes ``requested_arl``.
``test_fit_shewhart_recovers_sigma_multiplier_for_several_target_arl_values``
below does exactly that.

## Tolerance

Because this calibration is exact math rather than a numerical
approximation, the tolerances below are far tighter than the 2% relative
tolerance EWMA/CUSUM's numerical proofs use. If ``domain-implementer``'s
calibration cannot land within these tolerances, that is a signal the
calibration is wrong (e.g. an off-by-a-factor-of-two in the tail
probability, or root-finding used where direct inversion was available),
not that the tolerance is too tight.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pytest

from drift_caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, fit_shewhart
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Relative tolerance for round trips through fit_shewhart's actual
# calibration (may use a numerical inverse-CDF routine rather than a
# symbolic closed form, so a small floating-point gap is expected -- but
# nothing like the 2% EWMA/CUSUM's approximations require).
_RELATIVE_TOLERANCE = 1e-6

_MOVING_RANGE_D2 = 1.128


def _sufficient_baseline() -> Baseline:
    """A baseline large enough to fit from, with ordinary (non-zero) variance.

    The specific sample variance is irrelevant to this file's assertions --
    identically to the EWMA/CUSUM numerical-proof files' own baseline
    helper: the closed form calibrates in sigma-standardised units, so the
    in-control ARL0 does not depend on the baseline's actual sample
    variance.
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(DEFAULT_SUFFICIENCY_THRESHOLD + 20):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))
    return baseline


def _shewhart_arl0(sigma_multiplier: float) -> float:
    """The exact in-control ARL0 at ``sigma_multiplier`` sigma, for a two-sided chart.

    ``ARL0(L) = 1 / (2 * (1 - Phi(L)))``. Written fresh from the
    definition, using the standard library's normal distribution --
    deliberately not imported from
    ``drift_caliper.baseline.domain.shewhart_fitting``, so a bug shared between
    this file and the implementation cannot cancel out of the comparison.
    """
    return 1.0 / (2.0 * (1.0 - NormalDist().cdf(sigma_multiplier)))


def _shewhart_sigma_multiplier(target_arl: float) -> float:
    """The sigma multiplier achieving ``target_arl`` -- inverts ``_shewhart_arl0``.

    ``L(ARL0) = Phi^-1(1 - 1 / (2 * ARL0))``. Independent of
    ``_shewhart_arl0`` above only in the sense that it is the analytic
    inverse, not a numerical root-find on it -- both are written directly
    from the closed form, not derived from one another computationally.
    """
    return NormalDist().inv_cdf(1.0 - 1.0 / (2.0 * target_arl))


def _assert_close(actual: float, expected: float) -> None:
    tolerance = abs(expected) * _RELATIVE_TOLERANCE
    assert abs(actual - expected) <= tolerance, (
        f"{actual!r} is not within {tolerance!r} of the closed-form value {expected!r}"
    )


# --- The closed form itself, self-consistent by construction -----------------------
#
# Not a claim about fit_shewhart -- a sanity check that this file's own two
# helper functions are genuinely inverses of one another, before either is
# trusted against the implementation below.


@pytest.mark.parametrize(
    "sigma_multiplier",
    [0.5, 1.0, 2.0, 3.0, 4.0],
    ids=lambda multiplier: f"L={multiplier}",
)
def test_shewhart_arl0_and_sigma_multiplier_are_genuine_inverses(
    sigma_multiplier: float,
) -> None:
    """Round-tripping L through ARL0 and back recovers L, up to float precision."""
    # Act
    arl0 = _shewhart_arl0(sigma_multiplier)
    recovered = _shewhart_sigma_multiplier(arl0)

    # Assert
    assert recovered == pytest.approx(sigma_multiplier, rel=1e-9)


def test_shewhart_arl0_matches_the_classical_three_sigma_result() -> None:
    """L=3.0 gives the widely-cited ARL0 ~= 370.4 (NIST/SEMATECH; Montgomery).

    See module docstring: this pairing is ubiquitous in the SPC literature,
    but the assertion's real weight is that it falls directly out of the
    standard normal tail probability at 3 sigma, computed here from
    ``statistics.NormalDist`` rather than quoted from any table.
    """
    # Act
    arl0_at_three_sigma = _shewhart_arl0(3.0)

    # Assert -- generous absolute tolerance around the commonly-cited
    # rounded figure; the tight, load-bearing check is the parametrized
    # inverse test above and the fit_shewhart tests below.
    assert arl0_at_three_sigma == pytest.approx(370.4, abs=0.5)


# --- d_2, corroborated by closed-form derivation, not just secondary sources -------


def test_moving_range_d2_matches_the_expected_range_of_two_standard_normals() -> None:
    """d_2 for span 2 is E[|X1 - X2|] for X1, X2 ~ iid N(0, 1).

    See module docstring's "d_2, corroborated by closed-form derivation"
    section for the full derivation:
    ``d_2 = sqrt(2) * sqrt(2 / pi) = 2 / sqrt(pi)``. A derivation, not a
    citation -- and since ``spc_numerics.py`` now stores exactly this
    expression, the value it pins is the one the library uses rather than a
    rounded approximation of it.
    """
    # Act
    closed_form_d2 = 2.0 / math.sqrt(math.pi)

    # Assert -- the closed form, rounded to three decimal places, is
    # exactly the published constant.
    assert round(closed_form_d2, 3) == _MOVING_RANGE_D2
    assert closed_form_d2 == pytest.approx(_MOVING_RANGE_D2, abs=5e-4)


# --- The fitting pipeline, checked against the closed form --------------------------


def test_fit_shewhart_recovers_the_classical_three_sigma_multiplier() -> None:
    """Fitting for the closed-form ARL0 at L=3.0 recovers a sigma multiplier of ~3.0.

    Unlike an assertion that only checks ``achieved_arl ~= requested_arl``
    (which a shared, self-cancelling internal helper could satisfy
    regardless of correctness -- see module docstring's "Helpers whose
    effect cancels out"), this checks the chart-specific
    ``sigma_multiplier`` field against a value computed independently of
    the implementation.
    """
    # Arrange
    baseline = _sufficient_baseline()
    target_arl = _shewhart_arl0(3.0)

    # Act
    result = fit_shewhart(baseline, target_arl=target_arl)

    # Assert
    _assert_close(result.sigma_multiplier, 3.0)


@pytest.mark.parametrize(
    "target_arl", [200.0, 370.0, 500.0, 1000.0], ids=lambda arl: f"target_arl={arl}"
)
def test_fit_shewhart_recovers_sigma_multiplier_for_several_target_arl_values(
    target_arl: float,
) -> None:
    """The fitted sigma multiplier matches the closed-form inverse at several ARL0s.

    A single design point (the test above) could coincidentally pass a
    shared, wrong helper; several independent ARL0 values sharing no
    internal state make a systematic scaling error visible.
    """
    # Arrange
    baseline = _sufficient_baseline()
    expected_sigma_multiplier = _shewhart_sigma_multiplier(target_arl)

    # Act
    result = fit_shewhart(baseline, target_arl=target_arl)

    # Assert
    _assert_close(result.sigma_multiplier, expected_sigma_multiplier)


def test_fit_shewhart_achieved_arl_matches_requested_arl_almost_exactly() -> None:
    """Unlike EWMA/CUSUM, achieved and requested ARL0 coincide near-exactly.

    A2% gap (the sibling stories' tolerance) would be a red flag here, not
    an acceptable approximation error -- Shewhart's calibration under
    normality has no discretisation and no diffusion approximation (A4).
    """
    # Arrange
    baseline = _sufficient_baseline()
    requested = 500.0

    # Act
    result = fit_shewhart(baseline, target_arl=requested)

    # Assert
    _assert_close(result.achieved_arl, requested)


def test_control_limits_are_consistent_with_the_reported_sigma_multiplier() -> None:
    """``ucl``/``lcl`` equal ``baseline_mean +/- sigma_multiplier * sigma_estimate``.

    Per ``docs/domain-model.md``'s FittedShewhart field table. Written
    fresh from the artefact's own reported fields (not a second citation),
    so a wiring bug between the calibrated multiplier and the reported
    limits -- distinct from a wrong multiplier itself, which the tests
    above already cover -- fails here.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=370.0)

    # Assert
    multiplier, sigma, mean = (
        result.sigma_multiplier,
        result.sigma_estimate,
        result.baseline_mean,
    )
    assert result.ucl == pytest.approx(mean + multiplier * sigma, rel=1e-12)
    assert result.lcl == pytest.approx(mean - multiplier * sigma, rel=1e-12)
    assert result.cl == pytest.approx(mean, rel=1e-12)
