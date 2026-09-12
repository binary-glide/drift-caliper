"""Unit tests for ``fit_shewhart()`` (BIN-95) -- shape and behaviour, Part 1 of 2.

Pins the acceptance scenarios in
``tests/bdd/features/baseline/shewhart-control-limit-fitting.feature`` at
the unit layer, plus boundary/property cases the feature file's business
rules require but do not name as separate scenarios. Error assertions
follow ADR-002/ADR-008: type + required ``context`` keys only -- never
message text. Mirrors ``tests/unit/baseline/test_ewma_fitting.py`` and
``tests/unit/baseline/test_cusum_fitting.py`` throughout; differences are
called out explicitly rather than silently diverging.

**This file asserts shape and behaviour only -- no numeric literal here is a
claim about statistical correctness.** Every concrete ``target_arl`` value
below is an arbitrary valid input chosen to exercise a code path, exactly
like the feature file's own scenarios (which name zero numeric literals,
deliberately -- see the feature file's header).

**The numerical proof lives in a separate file on purpose**:
``tests/unit/baseline/test_shewhart_arl_published_values.py`` verifies
``fit_shewhart``'s calibration against the closed-form relationship
``ARL0 = 1 / (2 * Phi(-L))`` -- no published table needed, since Shewhart's
calibration is exact math, not an approximation (unlike EWMA/CUSUM). Keeping
the two apart means a reader can tell instantly, from the file a failure is
in, whether a broken test means "the API contract changed" (this file) or
"the calibration is statistically wrong" (that file).

``fit_shewhart()``, ``FittedShewhart`` and ``FittedControlLimits`` exist
only as scaffolds (``src/caliper/baseline/domain/``): ``fit_shewhart()``
always raises ``NotImplementedError``. Every test below that calls it is
expected to fail for that reason until ``domain-implementer`` replaces the
scaffold -- ``uv run pytest`` therefore fails; that is the correct state for
this ticket (TDD red phase).

**No new factory for ``FittedShewhart``.** Every test obtains its
``FittedShewhart`` by calling ``fit_shewhart()`` -- never by constructing
one directly, mirroring the convention the sibling fitting stories
established.

**Decisions this file makes, flagged rather than guessed silently** (mirrors
``test_ewma_fitting.py``'s/``test_cusum_fitting.py``'s own "Decisions this
file makes" sections, not re-argued here where identical):

1. **``DegenerateBaselineError.context["reason"] == "zero_variance"`` is
   pinned**, matching ``docs/domain-model.md``'s Error Contract Reference
   worked example and the identical precedent BIN-64/BIN-65/BIN-94
   established.
2. **``InvalidParameterError.context["parameter"]`` is pinned to
   ``"target_arl"``** -- the *only* engineer-specified parameter
   ``fit_shewhart`` has (ADR-004 section 5: ``fit_shewhart(baseline, *,
   target_arl=None) -> FittedShewhart``). Unlike EWMA/CUSUM there is no
   second tuning parameter to validate.
3. **OQ-3 (sufficiency check internal or external to fitting) is left
   open, on purpose**, identically to BIN-65/BIN-94.
4. **``InsufficientBaselineError.context["need"]`` is pinned to
   ``DEFAULT_SUFFICIENCY_THRESHOLD``**, identically to the siblings.
5. **``sigma_estimation_method`` is pinned to ``"moving_range"``** -- the
   feature file's SC3 asserts this directly ("the fitted artefact reports
   that sigma was estimated using the moving-range method"), and it is the
   same string ``fit_ewma``/``fit_cusum`` already report, per the shared
   ``spc_numerics`` estimator both chart types delegate to.
6. **Observation-order dependency (BR-7) is tested at both layers.** The
   feature file's two order-dependency scenarios are pinned here directly
   against the moving-range definition (computed independently of
   ``fit_shewhart``, mirroring ``test_spc_numerics.py``'s own pattern) and
   again, more thinly, in the BDD steps -- the unit layer is where the
   mutation-resistant assertion belongs; the BDD layer only demonstrates the
   property holds through the public scenario language.

Uses ``ScoringResultFactory``/``ProvenanceFactory`` (``tests/factories.py``)
for observations where the specific score does not matter, per that
module's own guidance.
"""

from __future__ import annotations

import itertools
import math
import statistics
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedShewhart,
    FittingAdvisory,
    fit_shewhart,
)

# MIN_*/MAX_* validation bounds are internal (BIN-110 P2) -- no longer
# re-exported from caliper.baseline, so tests that need the exact bound
# values import them from the owning submodule directly.
#
# MIN_TARGET_ARL (100, ADR-011's hard floor) replaces MIN_MEANINGFUL_ARL as
# the smallest *legal* target_arl -- MIN_COHERENT_ARL (1.0, renamed from
# MIN_MEANINGFUL_ARL) is the older, weaker, purely-arithmetic floor and is
# imported separately below only where a test specifically exercises the
# now-illegal gap between the two (BIN-131).
from caliper.baseline.domain.ewma_fitting import MIN_COHERENT_ARL
from caliper.baseline.domain.parameter_guards import VERIFIED_ARL_FLOOR
from caliper.baseline.domain.shewhart_fitting import (
    MAX_MEANINGFUL_ARL,
    MIN_TARGET_ARL,
)
from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)
from caliper.measurement import Provenance
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary, sufficiently-large target ARL0 used across the happy-path/shape
# scenarios below. Its value carries no statistical meaning here -- unlike
# test_shewhart_arl_published_values.py, this file asserts shape and
# behaviour only, never a specific achieved-ARL or sigma-multiplier figure,
# so no citation is required for this constant.
_SHAPE_TEST_TARGET_ARL = 370.0

_IDENTICAL_SCORE = 0.62
_ZERO_VARIANCE_REASON = "zero_variance"

# BIN-119: two additional `DegenerateBaselineError.context["reason"]` values,
# for a moving-range aggregate that overflows to +inf or underflows to 0.0 --
# distinct from `_ZERO_VARIANCE_REASON` above, which stays a separate,
# working guard over the *raw scores*. See
# `tests/unit/baseline/test_spc_numerics.py`'s identically-named constants
# and its "Sad path: non-finite or zero moving-range aggregate" section for
# the full reasoning -- this file's values must agree with that file's and
# with `test_ewma_fitting.py`'s/`test_cusum_fitting.py`'s, since all four
# name the same guard, reused by all three chart types through the one
# shared `spc_numerics` module.
_NON_FINITE_SIGMA_REASON = "non_finite_sigma_estimate"
_SIGMA_UNDERFLOW_REASON = "sigma_estimate_underflow"

# The unbiasing constant d_2 for a moving-range span of 2. Reproduced here as
# a literal, deliberately independent of
# caliper.baseline.domain.spc_numerics._MOVING_RANGE_D2 -- this file's
# order-dependency assertions are written fresh from the published
# definition, never imported from the module under test (see
# tests/unit/baseline/test_spc_numerics.py, which established this
# convention, and the module docstring's point 6).
_MOVING_RANGE_D2 = 1.1283791670955126  # 2/sqrt(pi), exact


def _baseline_with_observations(count: int, *, score: float | None = None) -> Baseline:
    """Build a ``Baseline`` with ``count`` recorded observations.

    All observations share one ``Provenance`` so recording never raises
    ``ProvenanceMismatchError``. When ``score`` is given, every observation
    carries that exact value (the zero-variance scenarios); otherwise each
    gets an independently varying score from the factory default.
    """
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(count):
        if score is None:
            baseline.record(ScoringResultFactory(provenance=shared_provenance))
        else:
            baseline.record(
                ScoringResultFactory(provenance=shared_provenance, score=score)
            )
    return baseline


def _baseline_from_scores(scores: list[float], provenance: Provenance) -> Baseline:
    """Build a ``Baseline`` recording exactly ``scores``, in the given order."""
    baseline = Baseline()
    for score in scores:
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))
    return baseline


def _sufficient_baseline() -> Baseline:
    """A baseline that passes the sufficiency check and has non-zero variance."""
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)


def _hand_computed_moving_range_sigma(scores: list[float]) -> float:
    """MR-bar / d_2, computed from the definition, independent of the code under test.

    See point 6 in this module's docstring.
    """
    moving_ranges = [abs(b - a) for a, b in itertools.pairwise(scores)]
    return statistics.fmean(moving_ranges) / _MOVING_RANGE_D2


def _capture_fitting_error(
    baseline: Baseline, *, target_arl: float | None
) -> CaliperError:
    """Call ``fit_shewhart`` expecting it to raise, and return the raised error."""
    try:
        fit_shewhart(baseline, target_arl=target_arl)
    except CaliperError as exc:
        return exc
    raise AssertionError("expected fit_shewhart() to raise for this scenario")


# --- Happy path: core fitting -------------------------------------------------


def test_fits_shewhart_control_limits_from_a_sufficient_baseline_with_a_tolerance() -> (
    None
):
    """The result has UCL/LCL/CL and reports sigma estimate/multiplier + tolerance."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedShewhart)
    assert isinstance(result, FittedControlLimits)
    assert isinstance(result.ucl, float)
    assert isinstance(result.lcl, float)
    assert isinstance(result.cl, float)
    assert result.ucl > result.lcl  # a well-formed pair of limits
    assert isinstance(result.sigma_estimate, float)
    assert isinstance(result.sigma_multiplier, float)
    assert result.requested_arl == _SHAPE_TEST_TARGET_ARL
    assert isinstance(result.achieved_arl, float)
    assert isinstance(result.calibration_method, str)
    assert result.calibration_method != ""


# --- Happy path: auditability --------------------------------------------------


def test_fitted_artefact_reports_baseline_mean_sigma_estimate_and_provenance() -> None:
    """The artefact reports baseline mean, sigma estimate, count, and provenance."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result.baseline_mean, float)
    assert isinstance(result.sigma_estimate, float)
    assert result.observation_count == baseline.observation_count
    signature = baseline.provenance_signature
    assert signature is not None
    assert result.provenance_model_version == signature.model_version.value
    assert result.provenance_criteria == signature.scoring_criteria.value


# --- Happy path: dual spread -- both quantities present and distinct -----------


def test_reports_both_baseline_spread_and_sigma_estimate_as_distinct_quantities() -> (
    None
):
    """The shared core's two spread measures are both present, and generally differ.

    ADR-004's "Finding: all artefacts carry two spread measures" is
    explicit that ``baseline_spread`` (total variation, sample std dev) and
    ``sigma_estimate`` (short-term variation, moving-range) are different
    quantities on every artefact -- not just Shewhart's. A test that only
    checks one leaves the conflation this story exists to prevent
    undetected (see this story's brief).
    """
    # Arrange -- a baseline with a slow upward drift superimposed on
    # point-to-point noise, so the sample std dev (which sees the drift)
    # and the moving-range sigma (which does not) are pulled apart, rather
    # than coincidentally close for a stationary baseline.
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    count = DEFAULT_SUFFICIENCY_THRESHOLD + 20
    for i in range(count):
        drift = (i / count) * 0.5
        noise = 0.01 if i % 2 == 0 else -0.01
        baseline.record(
            ScoringResultFactory(provenance=shared_provenance, score=drift + noise)
        )

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert -- both present as floats, and materially different: the
    # drift inflates baseline_spread far beyond the point-to-point
    # sigma_estimate.
    assert isinstance(result.baseline_spread, float)
    assert isinstance(result.sigma_estimate, float)
    assert result.baseline_spread != result.sigma_estimate
    assert result.baseline_spread > result.sigma_estimate


# --- Happy path: sigma estimation method ----------------------------------------


def test_sigma_estimation_method_is_reported_as_moving_range() -> None:
    """SC3: sigma is estimated using the moving-range method, and this is reported."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert result.sigma_estimation_method == "moving_range"


# --- Happy path: no independent tuning parameter (A3/A5) ------------------------


def test_fit_shewhart_accepts_only_baseline_and_target_arl() -> None:
    """The I-chart has no independent tuning parameter (A5) -- unlike EWMA/CUSUM.

    The proof is structural: ``fit_shewhart``'s signature (ADR-004 section
    5) accepts nothing beyond ``baseline`` and ``target_arl``. Passing any
    other keyword is a ``TypeError`` at the call site, not a
    ``CaliperError`` -- this test does not attempt one (asserting on a raw
    ``TypeError`` from an unknown keyword would test Python's own calling
    convention, not Caliper). Instead it asserts the positive claim: fitting
    with only the parameters the signature actually accepts still produces
    a complete, self-consistent artefact.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedShewhart)
    with pytest.raises(TypeError):
        fit_shewhart(
            baseline,
            target_arl=_SHAPE_TEST_TARGET_ARL,
            smoothing_param=0.2,  # type: ignore[call-arg]  # ty: ignore[unknown-argument]
        )


# --- Happy path: observation order dependency (BR-7) -----------------------------


def test_sigma_estimate_reflects_the_consecutive_differences_in_recorded_order() -> (
    None
):
    """Fitted sigma matches a hand computation from the *recorded* order.

    Deliberately non-monotonic, distinct scores so the moving ranges are
    non-trivial and reordering (in the sibling test below) is guaranteed to
    change at least one consecutive difference. Computed independently of
    ``fit_shewhart``, mirroring ``test_spc_numerics.py``'s own pattern --
    per this file's module docstring, point 6.
    """
    # Arrange
    pattern = [0.10, 0.90, 0.30, 0.70, 0.20, 0.80, 0.40, 0.60]
    count = DEFAULT_SUFFICIENCY_THRESHOLD + 4
    scores = [pattern[i % len(pattern)] for i in range(count)]
    baseline = _baseline_from_scores(scores, ProvenanceFactory())

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    expected_sigma = _hand_computed_moving_range_sigma(scores)
    assert result.sigma_estimate == pytest.approx(expected_sigma, rel=1e-9)


def test_reordering_the_baseline_changes_the_fitted_limits() -> None:
    """A reordering that changes the consecutive differences changes the fit.

    BIN-63 BR-2 guarantees insertion order is preserved; this is the first
    story where that guarantee matters for the arithmetic, not just for
    chart sequencing (see the feature file's own header note on this
    scenario pair). Sorting a non-monotonic sequence is guaranteed to
    change at least one consecutive difference -- it is not the identity
    permutation for any non-sorted input, unlike a reversal, which the
    requirements review found to be an unsound counterexample for this
    property (BIN-95 Linear comment `cdeb5b4a`).
    """
    # Arrange -- same set of scores as the test above, deliberately
    # non-sorted in its recorded order.
    pattern = [0.10, 0.90, 0.30, 0.70, 0.20, 0.80, 0.40, 0.60]
    count = DEFAULT_SUFFICIENCY_THRESHOLD + 4
    original_scores = [pattern[i % len(pattern)] for i in range(count)]
    provenance = ProvenanceFactory()
    original_baseline = _baseline_from_scores(original_scores, provenance)
    reordered_baseline = _baseline_from_scores(sorted(original_scores), provenance)

    # Act
    original_result = fit_shewhart(original_baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
    reordered_result = fit_shewhart(
        reordered_baseline, target_arl=_SHAPE_TEST_TARGET_ARL
    )

    # Assert -- same multiset of scores, different consecutive differences,
    # different sigma and different limits.
    assert original_result.sigma_estimate != reordered_result.sigma_estimate
    assert (original_result.ucl, original_result.lcl) != (
        reordered_result.ucl,
        reordered_result.lcl,
    )
    # And the centre line -- the mean -- is order-invariant, which is what
    # makes this a property of the *sigma estimate* specifically, not an
    # artefact of comparing two unrelated fits.
    assert original_result.cl == reordered_result.cl


# --- Sad path: insufficient baseline --------------------------------------------


def test_raises_insufficient_baseline_error_when_below_the_sufficiency_threshold() -> (
    None
):
    """Fitting enforces sufficiency (A1): refuses an insufficient baseline."""
    # Arrange
    shortfall = 10
    baseline = _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - shortfall)

    # Act
    with pytest.raises(InsufficientBaselineError) as exc_info:
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "insufficient_baseline"
    assert error.context["have"] == baseline.observation_count
    assert error.context["need"] == DEFAULT_SUFFICIENCY_THRESHOLD


# --- Sad path: zero-variance baseline --------------------------------------------


def test_raises_degenerate_baseline_error_when_every_score_is_identical() -> None:
    """Fitting refuses a zero-variance baseline (A2): sigma would collapse to zero."""
    # Arrange -- meets the count threshold, but has no variance
    baseline = _baseline_with_observations(
        DEFAULT_SUFFICIENCY_THRESHOLD, score=_IDENTICAL_SCORE
    )

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _ZERO_VARIANCE_REASON


def test_does_not_raise_degenerate_baseline_error_when_exactly_one_score_differs() -> (
    None
):
    """Boundary: a single differing score is enough variance to fit.

    Mirrors the identically-named test in ``test_ewma_fitting.py``/
    ``test_cusum_fitting.py`` -- the same mutation-testing finding carried
    from BIN-64 (CLAUDE.md, "carried findings"): the zero-variance guard's
    boundary needs deliberate pinning.
    """
    # Arrange
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    for _ in range(DEFAULT_SUFFICIENCY_THRESHOLD - 1):
        baseline.record(
            ScoringResultFactory(provenance=shared_provenance, score=_IDENTICAL_SCORE)
        )
    baseline.record(
        ScoringResultFactory(provenance=shared_provenance, score=_IDENTICAL_SCORE + 0.1)
    )

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedShewhart)


# --- Sad path: non-finite or zero moving-range sigma (BIN-119) ------------------
#
# External code review (Codex), 2026-09-11, reproduced against this exact
# function. Every individual score below is finite (`ScoringResult` already
# enforces that), but the *moving-range aggregate* `fit_shewhart` derives
# from them via the shared `spc_numerics` estimator still overflows to +inf
# or underflows to 0.0 -- neither is caught by the zero-variance guard
# above, which only asks "are all scores identical?" Verified empirically
# (not assumed) that, unpatched, `fit_shewhart` returns a "successfully
# fitted" artefact in both cases: `sigma_estimate=inf`/`ucl=inf`/`lcl=-inf`
# for the overflow case (a chart that can never signal -- the worst failure
# mode this library has), and `sigma_estimate=0.0`/`ucl==lcl==baseline_mean`
# for the underflow case (a chart where almost any future score immediately
# "signals"). See `tests/unit/baseline/test_spc_numerics.py`'s identically
# reasoned section for the full citation of what was verified and why
# `DegenerateBaselineError` is the right type, and for why the two `reason`
# values below must agree exactly across all three chart types' fitting
# test files plus that one.


def test_raises_degenerate_baseline_error_when_moving_range_is_non_finite() -> None:
    """Alternating near-float-max scores overflow the moving-range aggregate to +inf.

    Must be rejected at fit time -- no ``FittedShewhart`` with
    ``sigma_estimate=inf`` may ever be constructed.
    """
    # Arrange -- two distinct values, so the zero-variance guard above does
    # not fire first.
    provenance = ProvenanceFactory()
    scores = [1e308, -1e308] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)
    baseline = _baseline_from_scores(scores, provenance)

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _NON_FINITE_SIGMA_REASON


def test_raises_degenerate_baseline_error_when_moving_range_underflows_to_zero() -> (
    None
):
    """A baseline with real variance still underflows the moving-range aggregate to 0.0.

    Two distinct values (0.0 and the smallest positive subnormal float), so
    the zero-variance guard above does not fire. Must be rejected at fit
    time regardless -- no ``FittedShewhart`` with ``sigma_estimate=0.0``
    (and therefore ``ucl == lcl``) may ever be constructed from this.
    """
    # Arrange -- one subnormal among an otherwise-identical baseline.
    provenance = ProvenanceFactory()
    half = DEFAULT_SUFFICIENCY_THRESHOLD // 2
    scores = [0.0] * half + [5e-324] + [0.0] * (half - 1)
    baseline = _baseline_from_scores(scores, provenance)

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _SIGMA_UNDERFLOW_REASON


# --- BIN-123: an intermediate that overflows must not stop a representable ------
# --- baseline from fitting ------------------------------------------------------
#
# Found while briefing the BIN-119 implementation, 2026-09-11, reproduced
# directly against ``fit_shewhart``. ``statistics.fmean`` (used for
# ``baseline_mean``, and internally by ``_moving_range_sigma`` for the
# moving-range aggregate) delegates to ``math.fsum`` for its exactly-rounded
# result -- which raises ``OverflowError`` when an *intermediate* (running)
# sum exceeds float64's finite range, even when the true, final mean is
# itself perfectly representable. An alternating ``[1e307, 0.0, 1e307,
# 0.0, ...]`` baseline of 150 scores has a true mean of ``5e306`` and a true
# moving-range sigma of ``~8.86e306`` -- both comfortably representable --
# yet the running sum alone (``~7.5e308``) exceeds float64's ~1.7977e308
# max. Empirically confirmed, unpatched: ``fit_shewhart`` raises
# ``OverflowError: intermediate overflow in fsum`` on this input, never
# reaching BIN-119's ``math.isfinite`` guard.
#
# 🚨 The obvious "fix" -- catch ``OverflowError`` and raise
# ``DegenerateBaselineError`` -- is wrong, not merely incomplete (BIN-123).
# It would convert a visible leak into a confident, well-typed *rejection of
# data this library should fit perfectly well*, collapsing this case into
# the genuinely non-representable one the two tests directly above already
# cover correctly (alternating ``+/-1e308``, whose true moving range
# (``2e308``) is not representable in float64 at all). The tests below call
# ``fit_shewhart`` expecting a normal return -- no ``pytest.raises`` -- so a
# fix of that wrong shape fails them directly.
#
# Ground truth is computed with ``fractions.Fraction`` -- exact rational
# arithmetic that cannot itself overflow -- independently of whatever
# summation strategy the fix under test ends up using; this is not a
# reimplementation of ``fit_shewhart``'s formula (CLAUDE.md names five
# prior instances of exactly that self-cancelling-helper mistake on this
# project). See ``tests/unit/baseline/test_spc_numerics.py``'s identically
# reasoned section for the same ground-truth helpers, duplicated here per
# this file's own established convention of not importing test helpers
# across sibling fitting test files.

_OVERFLOW_PRONE_BASELINE_SIZE = 150


def _overflow_prone_but_representable_scores() -> list[float]:
    """Alternating 1e307/0.0 -- every score finite, but the naive running sum overflows.

    149 * 1e307 ~= 1.49e309 exceeds float64's max (~1.7977e308) -- the exact
    BIN-123 defect shape. The true mean (5e306) and true moving-range-based
    sigma (~8.86e306) are both nowhere near that boundary.
    """
    return [1e307 if i % 2 == 0 else 0.0 for i in range(_OVERFLOW_PRONE_BASELINE_SIZE)]


def _exact_mean(values: list[float]) -> float:
    """The exact rational mean of ``values``, correctly rounded to the nearest float.

    An oracle independent of whatever summation strategy the code under
    test uses -- ``Fraction`` arithmetic is exact, so it cannot suffer the
    intermediate overflow this ticket is about.
    """
    return float(sum(Fraction(v) for v in values) / len(values))


def _catastrophic_cancellation_scores() -> list[float]:
    """One large positive term, many unit terms, one large negative term.

    ``1e16`` exceeds float64's exact-integer boundary (2**53 ~= 9.007e15),
    so a naive left-to-right accumulation absorbs (loses) unit-sized
    additions made against it -- the classic example motivating
    ``math.fsum``'s existence. Ordinary and finite -- nowhere near overflow.
    """
    return [1e16, *([1.0] * (_OVERFLOW_PRONE_BASELINE_SIZE - 2)), -1e16]


def test_fits_when_running_sum_overflows_but_result_is_representable() -> None:
    """A representable baseline must fit -- not raise -- on an overflowing intermediate.

    Asserts the reported ``baseline_mean``/``sigma_estimate`` against an
    independent ``Fraction`` oracle, not merely that ``fit_shewhart``
    returns without raising -- a fix that silently returns an inaccurate
    value (e.g. ``inf``, from a careless ``numpy.mean``, verified
    separately to also mishandle this exact input) would pass a "did not
    raise" check but must fail this one. Also asserts the control limits
    are finite: an infinite ``ucl``/``lcl`` is this library's worst failure
    mode (BIN-119) and must not slip back in through this path.
    """
    # Arrange
    provenance = ProvenanceFactory()
    scores = _overflow_prone_but_representable_scores()
    baseline = _baseline_from_scores(scores, provenance)
    moving_ranges = [abs(b - a) for a, b in itertools.pairwise(scores)]
    expected_mean = _exact_mean(scores)
    expected_sigma = _exact_mean(moving_ranges) / _MOVING_RANGE_D2

    # Act -- must return normally; no pytest.raises around this call.
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedShewhart)
    assert result.baseline_mean == pytest.approx(expected_mean, rel=1e-9)
    assert result.sigma_estimate == pytest.approx(expected_sigma, rel=1e-9)
    assert math.isfinite(result.ucl)
    assert math.isfinite(result.lcl)


def test_representable_and_non_representable_overflow_cases_are_distinguished() -> None:
    """Two superficially similar overflow-prone inputs must behave oppositely.

    Direct enforcement of BIN-123's central point: alternating ``1e307/0.0``
    (representable mean and sigma; the running sum alone overflows) must
    fit, while alternating ``+/-1e308`` (a genuinely non-representable
    moving range; BIN-119's existing, unduplicated guard) must still raise.
    A fix that merges the two -- e.g. by catching every ``OverflowError``
    and raising ``DegenerateBaselineError`` regardless of representability
    -- fails this test, even if each half passed in isolation elsewhere.
    """
    # Arrange
    provenance = ProvenanceFactory()
    representable_baseline = _baseline_from_scores(
        _overflow_prone_but_representable_scores(), provenance
    )
    non_representable_baseline = _baseline_from_scores(
        [1e308, -1e308] * (_OVERFLOW_PRONE_BASELINE_SIZE // 2), provenance
    )

    # Act / Assert -- representable case fits
    result = fit_shewhart(representable_baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
    assert isinstance(result, FittedShewhart)
    assert math.isfinite(result.ucl)
    assert math.isfinite(result.lcl)

    # Act / Assert -- non-representable case still raises the typed error
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_shewhart(non_representable_baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
    assert exc_info.value.category == "degenerate_baseline"


def test_baseline_mean_precision_is_unchanged_on_an_ordinary_baseline() -> None:
    """The overflow fix must not cost precision on data that never overflows.

    Catastrophic-cancellation data is deliberately chosen: a hand-written
    accumulation loop over these exact scores was verified separately to
    return ``0.0`` for the mean -- entirely losing all 148 of the small
    terms -- against a true value of ``~0.9867``, which is exactly the kind
    of "cheaper but imprecise" regression ADR-001 ("statistical correctness
    is the product") and this ticket both rule out. Every value here is
    ordinary and finite; nothing is anywhere near float64's range limit, so
    this is squarely the "must not regress" case, not a second instance of
    the overflow case above. Verified empirically that
    ``statistics.fmean`` -- today's, pre-fix, implementation -- already
    agrees with this ``Fraction``-computed value to the bit for this exact
    dataset, so asserting equality against the independent oracle *is*
    asserting bit-identity with today's output.
    """
    # Arrange
    provenance = ProvenanceFactory()
    scores = _catastrophic_cancellation_scores()
    baseline = _baseline_from_scores(scores, provenance)
    expected_mean = _exact_mean(scores)

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert -- bit-identical, not merely close.
    assert result.baseline_mean == expected_mean


# --- Sad path: invalid false alarm tolerance --------------------------------------


@pytest.mark.parametrize(
    "invalid_target_arl",
    [0.0, -10.0, MAX_MEANINGFUL_ARL * 2, MIN_COHERENT_ARL],
    ids=[
        "zero",
        "negative",
        "outside_meaningful_range",
        "coherent_but_below_policy_floor",
    ],
)
def test_raises_invalid_parameter_error_for_an_invalid_false_alarm_tolerance(
    invalid_target_arl: float,
) -> None:
    """Every invalid false alarm tolerance value raises a classifiable error.

    ``MIN_COHERENT_ARL`` (1.0, ADR-011's worked example) used to fit
    "successfully" here -- the exact degenerate point where
    ``sigma_multiplier == 0.0`` and the chart alarms on nearly every
    in-control observation. It must now be refused.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    error = _capture_fitting_error(baseline, target_arl=invalid_target_arl)

    # Assert
    assert isinstance(error, InvalidParameterError)
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "invalid"
    assert error.context["parameter"] == "target_arl"
    assert error.context["provided"] == invalid_target_arl
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- ADR-011: three-tier target_arl policy ------------------------------------
#
# refused (< MIN_TARGET_ARL) is covered by the invalid-parameter test above.
# These cover the two tiers that both fit: flagged ([MIN_TARGET_ARL,
# VERIFIED_ARL_FLOOR)) attaches a FittingAdvisory; clean (>= VERIFIED_ARL_FLOOR)
# does not.


@pytest.mark.parametrize(
    "flagged_target_arl",
    [MIN_TARGET_ARL, VERIFIED_ARL_FLOOR - 1e-6],
    ids=["at_policy_floor", "just_below_verified_floor"],
)
def test_fits_with_a_non_raising_advisory_when_target_arl_is_in_the_flagged_tier(
    flagged_target_arl: float,
) -> None:
    """``target_arl`` inside ``[MIN_TARGET_ARL, VERIFIED_ARL_FLOOR)`` fits, flagged."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=flagged_target_arl)

    # Assert
    assert isinstance(result, FittedShewhart)
    assert result.requested_arl == flagged_target_arl
    assert len(result.advisories) == 1
    advisory = result.advisories[0]
    assert isinstance(advisory, FittingAdvisory)
    assert advisory.kind == "target_arl_below_verified_range"
    assert advisory.description != ""


@pytest.mark.parametrize(
    "clean_target_arl",
    [VERIFIED_ARL_FLOOR, MAX_MEANINGFUL_ARL],
    ids=["at_verified_floor", "largest_meaningful"],
)
def test_fits_with_no_advisory_when_target_arl_is_in_the_clean_tier(
    clean_target_arl: float,
) -> None:
    """``target_arl`` at or above ``VERIFIED_ARL_FLOOR`` fits silently.

    No advisory.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=clean_target_arl)

    # Assert
    assert isinstance(result, FittedShewhart)
    assert result.advisories == ()


# --- Sad path: missing false alarm tolerance --------------------------------------


def test_raises_invalid_parameter_error_when_false_alarm_tolerance_is_omitted() -> None:
    """The false alarm tolerance is required -- omitting it fails loudly (ADR-004).

    For the I-chart this is the *only* engineer-specified parameter (A3):
    there is nothing else to configure, so a silently-defaulted tolerance
    would make the entire auditable commitment on the engineer's behalf.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    error = _capture_fitting_error(baseline, target_arl=None)

    # Assert -- InvalidParameterError(kind="missing"), never Python's TypeError
    assert isinstance(error, InvalidParameterError)
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "missing"
    assert error.context["parameter"] == "target_arl"
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Edge: error distinguishability -----------------------------------------------


def test_fitting_errors_are_distinguishable_with_distinct_recovery_guidance() -> None:
    """Three different failure modes classify under three different categories."""
    # Arrange / Act
    insufficient = _capture_fitting_error(
        _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD - 1),
        target_arl=_SHAPE_TEST_TARGET_ARL,
    )
    degenerate = _capture_fitting_error(
        _baseline_with_observations(
            DEFAULT_SUFFICIENCY_THRESHOLD, score=_IDENTICAL_SCORE
        ),
        target_arl=_SHAPE_TEST_TARGET_ARL,
    )
    invalid_parameter = _capture_fitting_error(_sufficient_baseline(), target_arl=0.0)

    # Assert -- exact set, not membership (CLAUDE.md carried finding: `in`
    # checks on a collection have been caught missing bogus extra members
    # four times on this project already).
    categories = {
        insufficient.category,
        degenerate.category,
        invalid_parameter.category,
    }
    assert categories == {
        "insufficient_baseline",
        "degenerate_baseline",
        "invalid_parameter",
    }

    # Recovery guidance distinct per category, not asserted on content
    # (ADR-002/ADR-008: recovery_hint is human-facing and untested for
    # *content* -- but CLAUDE.md's "programmatic error classifiability"
    # pattern requires distinctness, which is a structural property, not a
    # content assertion).
    hints = {
        insufficient.recovery_hint,
        degenerate.recovery_hint,
        invalid_parameter.recovery_hint,
    }
    assert len(hints) == 3


# --- Edge: immutability -------------------------------------------------------------


def test_fitted_shewhart_artefact_is_immutable_after_creation() -> None:
    """No field of a fitted artefact can be reassigned after construction."""
    # Arrange
    baseline = _sufficient_baseline()
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
    original_ucl = result.ucl
    original_sigma_multiplier = result.sigma_multiplier
    original_baseline_mean = result.baseline_mean
    original_provenance_model_version = result.provenance_model_version

    # Act / Assert -- limits, parameters, baseline statistics, provenance
    with pytest.raises(ValidationError):
        result.ucl = original_ucl + 1.0  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.sigma_multiplier = original_sigma_multiplier + 0.01  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.baseline_mean = original_baseline_mean + 1.0  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.provenance_model_version = "tampered"  # ty: ignore[invalid-assignment]

    assert result.ucl == original_ucl
    assert result.sigma_multiplier == original_sigma_multiplier
    assert result.baseline_mean == original_baseline_mean
    assert result.provenance_model_version == original_provenance_model_version


def test_fitted_shewhart_satisfies_the_fitted_control_limits_protocol() -> None:
    """A fitted artefact structurally satisfies the shared protocol (ADR-004 §1)."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedControlLimits)


# --- Boundary: false alarm tolerance at meaningful range limits ---------------------


@pytest.mark.parametrize(
    "boundary_target_arl",
    [MIN_TARGET_ARL, MAX_MEANINGFUL_ARL],
    ids=["smallest_legal", "largest_meaningful"],
)
def test_fits_successfully_with_false_alarm_tolerance_at_the_meaningful_range_boundary(
    boundary_target_arl: float,
) -> None:
    """Boundary value analysis: the edges of the legal range are accepted (ADR-011)."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=boundary_target_arl)

    # Assert
    assert isinstance(result, FittedShewhart)
    assert result.requested_arl == boundary_target_arl
    assert isinstance(result.achieved_arl, float)


# --- Property: a fitted artefact's limits are always well-ordered -------------------


#
# Rebounded under ADR-011/BIN-131 (was ``[MIN_MEANINGFUL_ARL,
# MAX_MEANINGFUL_ARL]`` -- MIN_MEANINGFUL_ARL is now MIN_COHERENT_ARL, 1.0,
# no longer a legal target_arl at all). ``exclude_min=True`` is no longer
# needed: the old exclusion existed because Shewhart's closed-form
# calibration genuinely produces ``sigma_multiplier == 0.0`` exactly at
# ``target_arl == MIN_COHERENT_ARL`` (1.0) -- a mathematically correct,
# degenerate design point where the limits collapse onto the centre line.
# ``MIN_TARGET_ARL`` (100) is far from that degeneracy
# (``sigma_multiplier(100) ~= 2.576``), so the strategy's new floor no
# longer needs to dodge it; the degenerate point itself is still real
# mathematics (``_shewhart_sigma_multiplier(1.0) == 0.0``), it is simply no
# longer reachable through the public ``target_arl`` parameter at all (see
# ``test_raises_invalid_parameter_error_for_a_now_illegal_coherent_arl``
# below, which pins that ADR-011 worked example directly).
@settings(max_examples=20, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_TARGET_ARL,
        max_value=MAX_MEANINGFUL_ARL,
        allow_nan=False,
    ),
)
def test_ucl_is_always_above_cl_which_is_always_above_lcl(target_arl: float) -> None:
    """Across the entire legal range, all three limits are strictly ordered."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=target_arl)

    # Assert
    assert result.ucl > result.cl > result.lcl


# --- Property: the sigma multiplier is strictly positive across the legal range -----


@settings(max_examples=20, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_TARGET_ARL,
        max_value=MAX_MEANINGFUL_ARL,
        allow_nan=False,
    ),
)
def test_sigma_multiplier_is_positive_across_the_legal_range(
    target_arl: float,
) -> None:
    """A negative (or zero) sigma multiplier would invert (or collapse) the limits.

    Unlike before ADR-011, the legal range no longer approaches the
    ``target_arl == MIN_COHERENT_ARL`` (1.0) degenerate point where
    ``sigma_multiplier == 0.0`` is the mathematically correct answer -- see
    the note above ``test_ucl_is_always_above_cl_which_is_always_above_lcl``.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=target_arl)

    # Assert
    assert result.sigma_multiplier > 0.0


# --- Sanity: the hand-computed helper this file relies on is itself correct --------


def test_hand_computed_moving_range_sigma_helper_matches_a_known_value() -> None:
    """Guards the guard: the independent helper this file uses must itself be right.

    Mirrors ``test_spc_numerics.py``'s own self-check -- every consecutive
    pair differs by exactly 0.10 here, so the mean moving range is 0.10 and
    sigma is 0.10 / d2, computable by inspection without running the
    helper.
    """
    scores = [0.50, 0.60] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)

    result = _hand_computed_moving_range_sigma(scores)

    assert result == pytest.approx(0.10 / 1.1283791670955126, rel=1e-9)
