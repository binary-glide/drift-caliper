"""Numerical proof: ``fit_cusum()`` reproduces a published CUSUM ARL0 design point.

**Ratified 2026-09-10 (CLAUDE.md, "Fitting stories carry their own numerical
proof").** ``tests/unit/baseline/test_cusum_fitting.py`` (Part 1) asserts
shape and behaviour only, with no numeric literal claiming statistical
correctness -- the feature file itself names no numbers, deliberately. This
file is the per-chart floor beneath BIN-84's broader property-based
strategy: it verifies the fitted output against a published/independently-
computed design point, so CUSUM is never shipped statistically unverified.
Kept in a separate module, deliberately, so a failure here reads
unambiguously as "the calibration is wrong", never as "the API contract
changed" (that is Part 1's job) -- see
``tests/unit/baseline/test_ewma_arl_published_values.py``'s module docstring
for the same discipline on the sibling EWMA story, which this file mirrors
throughout.

## Primary source

D. Siegmund (1985), *Sequential Analysis: Tests and Confidence Intervals*,
Springer-Verlag -- the closed-form corrected-diffusion approximation ADR-001
names for CUSUM's in-control ARL0.

## Verification chain -- record the gap honestly

Siegmund (1985) is a book, not a paper, and was not accessible directly in
this environment. Nor was D. C. Montgomery's *Introduction to Statistical
Quality Control* (7th ed., 2013) -- the same paywall gap ADR-004's amendment
already recorded for Montgomery Chapter 9 (the dual-spread finding). Two
independent routes were used instead, both fetched and read directly during
BIN-94's research (not taken from training-data recall, per CLAUDE.md's
"never from recall" rule):

**Route 1 -- the formula itself.** S. Maghsoodloo's Auburn University INSY
7330 course notes
(``https://www.eng.auburn.edu/~maghssa/INSY7330/Cusum-Control-Charts-M2013-Maghsoodloo.pdf``,
fetched in full) quote Montgomery's equation 9.6 (p. 423) verbatim, with an
explicit citation: "D. C. Montgomery also provides Siegmund's approximation
(1985), in his formula (9.6) on page 423 of his 7th edition, for the ARL
after a shift has occurred":

    ARL(Delta) = [exp(-2*Delta*b) - 1 + 2*Delta*b] / (2*Delta^2)

where ``b = A + 1.166``, ``A = h / sigma_xbar`` (the decision interval,
standardised -- ``A = h`` directly in Caliper's own sigma-standardised
units, since ``sigma_xbar = 1`` there), and ``Delta = (mu - mu0)/sigma_xbar -
k`` for a chart detecting an increase. The same document also quotes
Montgomery's equation 9.7 (p. 423) for combining two one-sided arms into a
two-sided ARL0: ``1/ARL(2) = 1/ARL- + 1/ARL+``. A second, independent web
search (not this document) returned the identical ``b = h + 1.166``
relation, corroborating the constant from a second route.

At the in-control point (``shift = 0``, so ``Delta = -k``), the general
formula above simplifies algebraically (substituting ``Delta = -k``) to:

    ARL0(k, h) = [exp(2*k*b) - 1 - 2*k*b] / (2*k^2)

This is ``_cusum_arl0`` in ``caliper.baseline.domain.cusum_fitting``, tested
directly below.

**Route 2 -- an independent numeric anchor.** The SAS/STAT QC procedure
documentation's worked CUSUM chart example
(``https://www.sfu.ca/sasdoc/sashtml/qc/chap12/sect6.htm``, fetched in full)
reports, for a one-sided CUSUM with reference value *k* = 0.5 and decision
interval *h* = 3 ("Figure 12.6. Summary Table"):

    Average Run Length (0) = 117.595692

This is SAS's own computed figure (its QC procedure uses an exact/numeric
ARL routine, not Siegmund's approximation, so this is a genuinely
independent check, not a restatement of the same method). Applying the
formula above to the identical design point (``k=0.5, h=3``, computed fresh
in this file, not imported from ``cusum_fitting.py``) gives ``ARL0 ~=
118.58`` -- a relative difference of about 0.84% from SAS's figure. That
gap is consistent with Siegmund's approximation's well-documented small
systematic bias relative to an exact computation, and is far too small to
be explained by a gross implementation bug (e.g. the factor-of-2
discretisation bug ``test_ewma_arl_published_values.py`` records catching
on BIN-65 review, which would produce a difference of 100%, not 1%).

Inverting the direction of this check -- solving for the *h* that makes
Siegmund's approximation hit SAS's exact ARL0 of 117.595692 at k=0.5 --
gives ``h ~= 2.992``, within 0.3% of SAS's own ``h=3``. This is the
strongest available anchor without paywalled access to Siegmund (1985) or
Montgomery directly, and is recorded transparently here rather than
presented as a direct primary-source read -- the same honesty
``test_ewma_arl_published_values.py`` practised for its own Technometrics
access gap.

**If this environment gains access to Siegmund (1985) or Montgomery (2013)
7th ed. directly, this note should be updated to cite the primary source
rather than via the Auburn reproduction and the SAS documentation.**

## Third link: validate the checker before trusting it (BIN-65's carried finding)

BIN-65's review found that a first Markov-chain implementation was wrong by
exactly a factor of 2 and would have been blamed on the published table had
a closed-form self-check not caught it first. CUSUM's analogue: as the
reference value *k* approaches 0, the in-control ARL0 formula's limit has a
closed form derivable directly from the formula's own Taylor expansion --
substitute ``exp(2*k*b) ~= 1 + 2*k*b + (2*k*b)^2/2`` for small ``k`` and the
``(2*k*b)^2/2 / (2*k^2)`` term is exactly ``b^2``, with the linear terms
cancelling. So ``ARL0(k, h) -> b^2`` as ``k -> 0``. This was verified
numerically (not just algebraically) before being trusted: computing the
formula in isolation at ``k`` in ``{1e-2, 1e-3, 1e-4, 1e-6}`` for a fixed
``h`` showed the gap from ``b^2`` shrinking roughly quadratically with
``k`` (0.49, 0.048, 0.0048, 0.00009 respectively, for h=3 where b^2 ~=
17.356) -- convergence behaviour consistent with a correct Taylor
expansion, not a coincidence.
``test_cusum_arl0_matches_its_closed_form_limit_as_reference_value_approaches_zero``
below pins this directly against the actual ``_cusum_arl0`` implementation,
not a hand re-derivation, so a wrong constant in the exponent or a sign
error in the ``-1-2kb`` term (which would NOT cancel correctly in this
limit) fails this test even though it might still coincidentally pass the
SAS-anchored check above for a different (k, h) pair.

## Primary source obtained 2026-09-11 -- the citation chain is now closed

**The `b = h + 1.166` relation and the two-sided combination rule are now
verified directly against Montgomery (2013), *Introduction to Statistical
Quality Control*, 7th ed., Wiley, page 423**, which states Siegmund's
approximation in full:

    "For a one-sided CUSUM (that is, C+_i or C-_i) with parameters h and k,
     Siegmund's approximation is (9.6) [...] where Delta = d* - k for the
     upper one-sided CUSUM C+_i, Delta = -d* - k for the lower one-sided
     CUSUM C-_i, **b = h + 1.166**, and d* = (mu_1 - mu_0)/sigma. If
     Delta = 0, one can use ARL = b^2."

Equation 9.7 gives the two-sided combination as ``1/ARL = 1/ARL+ + 1/ARL-``.

Montgomery's own worked example on the same page --  k = 1/2, h = 5, giving
b = 6.166, a one-sided ARL0 of 938.2 and a two-sided ARL0 of 469.1 against a
true value of 465 from his Table 9.3 -- is asserted by
``test_reproduces_montgomery_worked_example`` below. **That is a published
numerical result this implementation had never been checked against**, and it
is a stronger oracle than anything that preceded it here, because the values
were computed by someone else from an independently stated formula.

The verification chain that follows was built *before* the primary source was
available. It is kept in full rather than deleted: each link is still a real
check, they caught real errors, and an implementation agreeing with four
mutually independent methods is better evidenced than one agreeing with a
single quotation.

## Fourth link: Monte Carlo, which shares no assumptions with the closed form

Before the primary source was obtained, Siegmund's approximation reached this
file through two hops of secondary sources. A citation chain is thin evidence
for the numbers a control chart is built on, so both the formula **and** the
two-sided combination rule were checked against a direct simulation of the
CUSUM recursion -- no shared algebra, just counting steps to the first boundary
crossing with x ~ N(0, 1):

    k     h     Siegmund two-sided   Monte Carlo (200k runs)   ratio
    0.5   3.0              59.29                     58.76     0.991
    0.5   4.0             169.05                    167.29     0.990
    0.25  5.0              70.96                     70.73     0.997
    1.0   3.0            1036.35                    984.39     0.950

Within 1% for small k, widening to 5% at k = 1.0. That is the **known**
behaviour of Siegmund's approximation rather than a defect -- it is derived
from a Brownian-motion limit and is most accurate for small reference values,
which is also the regime CUSUM is chosen for. Worth knowing before anyone
reads a 5% gap at large k as a bug.

This also independently confirms the two-arm combination, `1/ARL_two =
2/ARL_one`, which no published table in the chain states directly.

## `target_arl` means the COMBINED two-sided ARL0

`backend-test-writer` flagged this as unpinned by ADR-004 and took the
combined reading. The Monte Carlo above settles it, and the reasoning is worth
stating so it is not re-opened:

**For a two-sided chart the combined ARL0 is the only quantity an engineer
observes.** A per-arm reading would mean someone requesting ARL0 = 500 sees a
false alarm roughly every 250 observations -- the chart signalling at twice the
rate they asked for. The per-arm figure is an internal step, not something
anyone experiences.

So `fit_cusum(target_arl=500, direction="two_sided")` calibrates `h` such that
the **chart as a whole** signals once per 500 in-control observations.

## Fifth link: the fitted chart itself, simulated end to end

The checks above verify the *formula*. This one verifies the *library*: take
the decision interval `fit_cusum` actually derived, simulate a CUSUM using it,
and count how often it signals in control. No shared algebra with Siegmund at
all.

    k      target   h fitted   simulated ARL0   ratio
    0.25      200     6.8489            199.6   0.998
    0.25      500     8.5825            499.8   1.000
    0.5       200     4.1635            199.0   0.995
    0.5       500     5.0630            494.1   0.988
    0.75      200     2.9173            196.0   0.980
    0.75      500     3.5224            488.9   0.978

A chart fitted by this library signals at the rate the engineer asked for.

⚠️ **Note the direction of the residual bias, and do not treat it as noise.**
At k = 0.75 a request for ARL0 = 500 yields roughly 489 -- about 2% *more*
false alarms than asked for, not fewer. That is the direction that costs a
user trust rather than the direction that hides drift, so it is the honest one
to name. It is inherent to Siegmund's Brownian-motion approximation, which is
most accurate for small reference values, and it is why CUSUM's defaults sit
in the small-k regime.

**For BIN-84:** this is the shape a property-based test should take for all
three charts -- fit, simulate, compare -- rather than only checking published
tables. It catches wiring errors a table lookup cannot, because it exercises
the calibration end to end rather than the formula in isolation.

## Tolerance

The published-value assertions below use a 2% relative tolerance --
identical to ``test_ewma_arl_published_values.py``'s own tolerance and
justified the same way: generous enough to absorb the genuine ~0.84%
approximation-vs-exact gap measured above, tight enough that a materially
wrong calibration (wrong sign, wrong constant, an order-of-magnitude bug)
fails loudly. If ``domain-implementer``'s calibration cannot land within
this tolerance, that is a signal the calibration is wrong, not that the
tolerance is too tight.
"""

from __future__ import annotations

import math

import pytest

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, fit_cusum
from caliper.baseline.domain.cusum_fitting import (
    _combine_two_sided_arl0,
    _cusum_arl0,
)
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Relative tolerance applied to each published/independently-anchored value
# below. See the module docstring's "Tolerance" section.
_RELATIVE_TOLERANCE = 0.02

# SAS/STAT QC documentation's exact (non-approximation) computed in-control
# ARL0 for a one-sided CUSUM with k=0.5, h=3 -- see module docstring Route 2.
_SAS_REFERENCE_VALUE = 0.5
_SAS_DECISION_INTERVAL = 3.0
_SAS_ARL0 = 117.595692

# Siegmund's (1985) correction constant, per the citation chain in the
# module docstring. Reproduced here as a literal, deliberately independent
# of caliper.baseline.domain.cusum_fitting._SIEGMUND_CORRECTION -- this
# file's formula is written fresh from the published definition, never
# imported from the implementation under test (see "Helpers whose effect
# cancels out" section below).
_SIEGMUND_CORRECTION = 1.166


def _sufficient_baseline() -> Baseline:
    """A baseline large enough to fit from, with ordinary (non-zero) variance.

    The specific sample variance is irrelevant to this file's assertions --
    identically to test_ewma_arl_published_values.py's own baseline helper:
    Siegmund's approximation, like the EWMA Markov-chain method, calibrates
    in sigma-standardised units, so the in-control ARL0 does not depend on
    the baseline's actual sample variance.
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(DEFAULT_SUFFICIENCY_THRESHOLD + 20):
        baseline.record(ScoringResultFactory(provenance=shared_provenance))
    return baseline


def _published_cusum_arl0(reference_value: float, decision_interval: float) -> float:
    """Siegmund's (1985) one-sided in-control ARL0, computed fresh from the definition.

    Deliberately NOT calling ``caliper.baseline.domain.cusum_fitting._cusum_arl0``
    -- this is an independent re-derivation used only to check the fitted
    artefact's *public* output (``reference_value``, ``decision_interval``)
    in the two-sided test below, so that a bug shared between this file and
    the implementation could not cancel out of the comparison. See the
    module docstring's "Third link" section and the BIN-94 brief's warning
    about helpers that divide themselves out of a round-trip check.
    """
    b = decision_interval + _SIEGMUND_CORRECTION
    exponent = 2.0 * reference_value * b
    return (math.exp(exponent) - 1.0 - exponent) / (2.0 * reference_value**2)


def _assert_close_to_published(actual: float, published: float) -> None:
    tolerance = published * _RELATIVE_TOLERANCE
    assert abs(actual - published) <= tolerance, (
        f"{actual!r} is not within {tolerance!r} of the published/"
        f"independently-anchored value {published!r}"
    )


# --- The helper that carries the citation's content, tested directly ---------------
#
# Per the BIN-94 brief: "test internal helpers directly, against a value
# computed from their published definition rather than read back off the
# artefact." `_cusum_arl0` is calibrated against by `fit_cusum` (root-finding
# on it) and then reapplied to compute `achieved_arl` -- the exact shape that
# let a wrong helper cancel out of BIN-65's public-output-only assertions,
# twice. Testing it directly, against SAS's independently-computed figure
# rather than any value this implementation itself produced, is what makes
# this a proof rather than a tautology.


def test_cusum_arl0_matches_the_sas_computed_value_for_a_known_design_point() -> None:
    """``_cusum_arl0(0.5, 3.0)`` lands within 2% of SAS's exact ARL0 of 117.6.

    See module docstring Route 2. This is the single strongest assertion in
    this file: SAS's figure was computed by a different method entirely
    (not Siegmund's approximation), so agreement here is not circular.
    """
    # Act
    achieved = _cusum_arl0(_SAS_REFERENCE_VALUE, _SAS_DECISION_INTERVAL)

    # Assert
    _assert_close_to_published(achieved, _SAS_ARL0)


def test_cusum_arl0_matches_its_closed_form_limit_as_k_approaches_zero() -> None:
    """As k -> 0, ``_cusum_arl0`` approaches ``(h + 1.166) ** 2`` (see "Third link").

    Validates the checker itself before it is trusted against the SAS
    anchor above -- BIN-65's carried finding: a first Markov-chain checker
    written for that story was wrong by exactly a factor of 2 and would
    have been blamed on the published table had a closed-form self-check
    not caught it first.
    """
    # Arrange -- k small enough that the Taylor-expansion argument in the
    # module docstring applies tightly (verified numerically during
    # research: the gap from the closed form shrinks roughly quadratically
    # with k, so 1e-4 is already within a tight tolerance of the limit).
    small_reference_value = 1e-4
    decision_interval = 3.0
    closed_form_limit = (decision_interval + _SIEGMUND_CORRECTION) ** 2

    # Act
    achieved = _cusum_arl0(small_reference_value, decision_interval)

    # Assert -- loose relative tolerance because this is a limit, not an
    # exact identity at any finite k; tight enough that a wrong exponent or
    # a sign error in the "-1-2kb" term (which would not cancel correctly
    # in this limit) fails loudly.
    assert achieved == pytest.approx(closed_form_limit, rel=0.01)


# --- The fitting pipeline, checked against the same design point -------------------


def test_calibration_recovers_the_sas_decision_interval_for_a_known_design_point() -> (
    None
):
    """Fitting for SAS's exact ARL0=117.6 at k=0.5 recovers h close to SAS's h=3.

    Unlike an assertion that only checks ``achieved_arl ~= requested_arl``
    (which ``fit_cusum`` can satisfy by construction regardless of whether
    its internal calibration is correct -- the exact tautology the BIN-94
    brief warns about), this checks the *decision interval* CUSUM actually
    reports against a value anchored to SAS's independently-computed figure,
    not to anything this implementation produced.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(
        baseline,
        target_arl=_SAS_ARL0,
        reference_value=_SAS_REFERENCE_VALUE,
        direction="lower",
    )

    # Assert -- 1% tolerance: tight enough that a materially wrong
    # calibration (the wrong root, a missing correction term) fails loudly;
    # loose enough to absorb Siegmund's approximation's own small bias
    # relative to SAS's exact figure (measured at ~0.84% for this exact
    # design point -- see module docstring Route 2).
    assert result.reference_value == _SAS_REFERENCE_VALUE
    assert result.decision_interval == pytest.approx(_SAS_DECISION_INTERVAL, rel=0.01)


def test_two_sided_calibration_matches_the_one_sided_design_at_half_target() -> None:
    """A two-sided fit at half SAS's ARL0 reproduces SAS's one-sided decision interval.

    Per Montgomery's Eq. 9.7 (module docstring, Route 1): for a symmetric
    two-sided CUSUM, ``ARL0_two_sided = ARL0_one_sided_arm / 2``. Fitting
    with ``direction="two_sided"`` and ``target_arl = SAS_ARL0 / 2`` should
    therefore produce the *same* decision interval as the pure one-sided fit
    above, at the *same* reference value -- because each arm individually
    must still achieve the one-sided ARL0 of 117.6 for the combined,
    two-sided figure to be 58.8.

    Checked against ``_published_cusum_arl0`` -- this file's own,
    independently-written re-derivation of Siegmund's formula, never the
    implementation's ``_cusum_arl0`` -- so a bug shared between the
    two-sided combination logic and the one-sided calibration could not
    cancel out of this comparison. See the BIN-94 brief's flagged reading
    of what ``target_arl`` means under ``direction="two_sided"``
    (``cusum_fitting.py``'s module docstring) -- if that reading is wrong,
    this specific test is the one to revisit; the one-sided tests above are
    unaffected either way.
    """
    # Arrange
    baseline = _sufficient_baseline()
    two_sided_target_arl = _SAS_ARL0 / 2.0

    # Act
    result = fit_cusum(
        baseline,
        target_arl=two_sided_target_arl,
        reference_value=_SAS_REFERENCE_VALUE,
        direction="two_sided",
    )
    implied_one_sided_arl0 = _published_cusum_arl0(
        result.reference_value, result.decision_interval
    )

    # Assert
    assert result.decision_interval == pytest.approx(_SAS_DECISION_INTERVAL, rel=0.01)
    _assert_close_to_published(implied_one_sided_arl0, _SAS_ARL0)


# --- The two-sided combination rule, tested directly --------------------------------


@pytest.mark.parametrize(
    ("lower_arm_arl0", "upper_arm_arl0", "expected_combined"),
    [
        # Symmetric arms: 1/(1/x + 1/x) = x/2 exactly.
        pytest.param(100.0, 100.0, 50.0, id="symmetric-100"),
        pytest.param(500.0, 500.0, 250.0, id="symmetric-500"),
        # Asymmetric arms: 1/(1/100 + 1/300) = 75.0 exactly -- a case a
        # simple "divide by 2" mutant (correct only for the symmetric case)
        # would fail.
        pytest.param(100.0, 300.0, 75.0, id="asymmetric-100-300"),
    ],
)
def test_combine_two_sided_arl0_matches_montgomery_eq_9_7(
    lower_arm_arl0: float, upper_arm_arl0: float, expected_combined: float
) -> None:
    """``1/ARL0_two_sided = 1/ARL0_lower + 1/ARL0_upper`` (Montgomery Eq. 9.7).

    Pinned directly with exact expected values (not approximations) because
    the relationship is exact arithmetic, not a statistical approximation --
    unlike ``_cusum_arl0`` itself, there is no tolerance to justify here.
    """
    # Act
    combined = _combine_two_sided_arl0(lower_arm_arl0, upper_arm_arl0)

    # Assert
    assert combined == pytest.approx(expected_combined, rel=1e-9)


# --- The calibration's central promise, and the direction that shapes it -------
#
# `code-reviewer` found that flipping `if direction == "two_sided":` inside
# `_calibrate_decision_interval` left all 255 tests passing. That single line
# decides whether `achieved_arl` reports the combined two-sided figure or the
# raw per-arm one -- so nothing was asserting the calibration's central
# promise: that a chart fitted for a requested ARL0 actually reports achieving
# it.
#
# The third instance on this project of a helper whose effect cancels out of
# everything observable. See this module's docstring and BIN-65's.


@pytest.mark.parametrize("direction", ["two_sided", "upper", "lower"])
def test_achieved_arl_matches_the_requested_arl_in_either_direction(
    direction: str,
) -> None:
    """The calibration reports achieving what it was asked for.

    Pins both arms of the flipped branch: under the mutation, a two-sided fit
    reports twice the requested ARL0 and a one-sided fit reports half of it.
    """
    # Arrange
    baseline = _sufficient_baseline()
    requested = 500.0

    # Act
    result = fit_cusum(
        baseline, target_arl=requested, reference_value=0.5, direction=direction
    )

    # Assert -- Siegmund is an approximation, but the root-find targets the
    # requested value directly, so agreement here is tight.
    assert result.achieved_arl == pytest.approx(requested, rel=0.01)


def test_two_sided_needs_a_wider_decision_interval_than_one_sided() -> None:
    """A structural relationship no round trip can cancel.

    Two arms each signal independently, so for the *same* combined false alarm
    rate each arm must be less sensitive than a lone arm would be -- which
    means a larger decision interval. (``"upper"`` is one such lone arm;
    ``_VALID_DIRECTIONS`` names the arm rather than saying "one-sided".)
    Asserting the inequality rather than either value pins the direction
    semantics without depending on the calibration's own arithmetic to
    interpret them.
    """
    # Arrange
    baseline = _sufficient_baseline()
    requested = 500.0

    # Act
    two_sided = fit_cusum(
        baseline, target_arl=requested, reference_value=0.5, direction="two_sided"
    )
    one_sided = fit_cusum(
        baseline, target_arl=requested, reference_value=0.5, direction="upper"
    )

    # Assert
    assert two_sided.decision_interval > one_sided.decision_interval


# --- Primary source: Montgomery (2013) 7th ed., p. 423 ------------------------

# Montgomery's own worked example, read from the page rather than recalled:
# k = 1/2 and h = 5 give b = h + 1.166 = 6.166, a one-sided ARL0 of 938.2, and
# a two-sided ARL0 of 469.1 -- which he notes is "very close to the true ARL0
# value of 465 shown in Table 9.3".
#
# Deliberately hand-typed rather than imported from `cusum_fitting`: these are
# an external claim about what the published approximation yields, and a test
# that sourced them from the implementation would pass for any value. Same
# reasoning as the audit-summary labels in BIN-66.
_MONTGOMERY_K = 0.5
_MONTGOMERY_H = 5.0
_MONTGOMERY_ONE_SIDED_ARL0 = 938.2
_MONTGOMERY_TWO_SIDED_ARL0 = 469.1
_MONTGOMERY_TABLE_9_3_EXACT = 465.0


def test_reproduces_montgomery_worked_example() -> None:
    """`_cusum_arl0` reproduces Montgomery (2013) 7th ed. p. 423 exactly.

    The strongest oracle in this module: a published numerical result,
    computed by someone else from an independently stated formula, for a
    design point this implementation was never tuned against.

    Agreement to four significant figures means `_SIEGMUND_CORRECTION`, the
    exponent, the `-1` term and the two-sided reciprocal-sum rule are each
    right -- a sign error or a wrong constant in any of them moves this
    number visibly.
    """
    # Act
    one_sided = _cusum_arl0(_MONTGOMERY_K, _MONTGOMERY_H)
    two_sided = _combine_two_sided_arl0(one_sided, one_sided)

    # Assert
    assert one_sided == pytest.approx(_MONTGOMERY_ONE_SIDED_ARL0, rel=1e-4)
    assert two_sided == pytest.approx(_MONTGOMERY_TWO_SIDED_ARL0, rel=1e-4)


def test_siegmund_approximation_sits_close_to_montgomery_table_9_3() -> None:
    """The approximation lands near the exact ARL0, and slightly above it.

    Montgomery reports 469.1 from the approximation against 465 exact. Pinning
    the *direction* and rough size of that gap guards the approximation's known
    behaviour: it is derived from a Brownian-motion limit and mildly
    overestimates ARL0 here. A change that made it match 465 exactly would mean
    the implementation had stopped being Siegmund's approximation.
    """
    # Act
    two_sided = _combine_two_sided_arl0(
        _cusum_arl0(_MONTGOMERY_K, _MONTGOMERY_H),
        _cusum_arl0(_MONTGOMERY_K, _MONTGOMERY_H),
    )

    # Assert
    assert two_sided > _MONTGOMERY_TABLE_9_3_EXACT
    assert two_sided == pytest.approx(_MONTGOMERY_TABLE_9_3_EXACT, rel=0.02)
