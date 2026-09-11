"""Unit tests for ``fit_ewma()`` (BIN-65) -- shape and behaviour, Part 1 of 2.

Pins the nineteen acceptance scenarios in
``tests/bdd/features/baseline/ewma-control-limit-fitting.feature`` at the
unit layer, plus boundary/property cases the feature file's business rules
require but do not name as separate scenarios. Error assertions follow
ADR-002/ADR-008: type + required ``context`` keys only -- never message
text.

**This file asserts shape and behaviour only -- no numeric literal here is a
claim about statistical correctness.** Every concrete ``target_arl`` /
``smoothing_param`` value below is an arbitrary valid input chosen to
exercise a code path, exactly like the feature file's own scenarios (which
name zero numeric literals, deliberately -- see the feature file's header).

**The numerical proof lives in a separate file on purpose**:
``tests/unit/baseline/test_ewma_arl_published_values.py`` verifies specific
(smoothing_param, target_arl) -> achieved_arl triples against Lucas &
Saccucci (1990) Table 3. Keeping the two apart means a reader can tell
instantly, from the file a failure is in, whether a broken test means "the
API contract changed" (this file) or "the calibration is statistically
wrong" (that file) -- see the backend-test-writer brief's explicit
instruction to keep them separate.

``fit_ewma()``, ``FittedEWMA`` and ``FittedControlLimits`` exist only as
scaffolds (``src/caliper/baseline/domain/``): ``fit_ewma()`` always raises
``NotImplementedError``. Every test below that calls it is expected to fail
for that reason until ``domain-implementer`` replaces the scaffold --
``uv run pytest`` therefore fails; that is the correct state for this
ticket (TDD red phase), the same shape as BIN-64's
``Baseline.check_sufficiency()`` scaffold.

**No new factory for ``FittedEWMA``.** Every test obtains its ``FittedEWMA``
by calling ``fit_ewma()`` -- never by constructing one directly -- mirroring
the convention ``tests/unit/baseline/test_baseline_sufficiency.py``
established for ``SufficiencyResult``: a factory would let a test assert
against a value it invented rather than one the fitting operation actually
produced.

**Decisions this file makes, flagged rather than guessed silently:**

1. **``DegenerateBaselineError.context["reason"] == "zero_variance"`` is
   pinned**, not left as "any non-empty string". ``docs/domain-model.md``'s
   Error Contract Reference gives ``"zero_variance"`` as the worked example
   for this exact field, the same precedent BIN-64 used to pin
   ``DataQualityConcern.kind`` -- see that file's module docstring for the
   full reasoning, which applies identically here.
2. **``InvalidParameterError.context["parameter"]`` is pinned to the exact
   Python parameter name** (``"target_arl"``, ``"smoothing_param"``) for
   every invalid/missing-parameter scenario, matching ADR-004 section 5's
   exact fitting signature (``fit_ewma(baseline, *, target_arl=None,
   smoothing_param=None)``) and mirroring how BIN-64 pinned
   ``context["parameter"] == "threshold"``.
3. **OQ-3 (sufficiency check internal or external to fitting) is left
   open, on purpose.** Every insufficient-baseline test asserts only the
   observable failure (``InsufficientBaselineError`` with the right
   ``have``/``need``) -- never that ``check_sufficiency()`` was called.
   Both designs the ADR names satisfy every assertion here.
4. **``InsufficientBaselineError.context["need"]`` is pinned to
   ``DEFAULT_SUFFICIENCY_THRESHOLD``** (imported from
   ``caliper.baseline``, itself ratified by ADR-005 as 100). ``fit_ewma()``
   has no threshold parameter in its signature (ADR-004 section 5), so
   there is no other value it could reasonably use, and OQ-4 (no override
   mechanism) forecloses an alternative. This is a value in the *error's
   contract*, not an assertion about mechanism -- distinguishing it from
   point 3.

Uses ``ScoringResultFactory``/``ProvenanceFactory`` (``tests/factories.py``)
for observations where the specific score does not matter, per that
module's own guidance.
"""

from __future__ import annotations

import itertools
import math
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from caliper.baseline import (
    DEFAULT_SMOOTHING_PARAM,
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedEWMA,
    fit_ewma,
)

# MIN_*/MAX_* validation bounds are internal (BIN-110 P2) -- no longer
# re-exported from caliper.baseline, so tests that need the exact bound
# values import them from the owning submodule directly.
from caliper.baseline.domain.ewma_fitting import (
    MAX_MEANINGFUL_ARL,
    MAX_SMOOTHING_PARAM,
    MIN_MEANINGFUL_ARL,
    MIN_SMOOTHING_PARAM,
)
from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)
from caliper.measurement import Provenance
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary, sufficiently-large target ARL0 and smoothing parameter used
# across the happy-path/shape scenarios below. Their values carry no
# statistical meaning here -- unlike
# tests/unit/baseline/test_ewma_arl_published_values.py, this file asserts
# shape and behaviour only, never a specific achieved-ARL figure, so no
# citation is required for these two constants.
_SHAPE_TEST_TARGET_ARL = 370.0
_SHAPE_TEST_SMOOTHING_PARAM = 0.3

# A custom smoothing parameter distinct from both DEFAULT_SMOOTHING_PARAM
# and _SHAPE_TEST_SMOOTHING_PARAM, for the "engineer overrides the default"
# scenario -- its value likewise carries no statistical meaning.
_CUSTOM_SMOOTHING_PARAM = 0.6

_IDENTICAL_SCORE = 0.62

# The only DegenerateBaselineError.context["reason"] this story introduces
# -- see the module docstring's "decisions" section for why this is pinned.
_ZERO_VARIANCE_REASON = "zero_variance"

# BIN-119: two additional `DegenerateBaselineError.context["reason"]` values,
# for a moving-range aggregate that overflows to +inf or underflows to 0.0 --
# distinct from `_ZERO_VARIANCE_REASON` above, which stays a separate,
# working guard over the *raw scores*. See
# `tests/unit/baseline/test_spc_numerics.py`'s identically-named constants
# and its "Sad path: non-finite or zero moving-range aggregate" section for
# the full reasoning -- this file's values must agree with that file's and
# with `test_cusum_fitting.py`'s/`test_shewhart_fitting.py`'s, since all
# four name the same guard, reused by all three chart types through the one
# shared `spc_numerics` module.
_NON_FINITE_SIGMA_REASON = "non_finite_sigma_estimate"
_SIGMA_UNDERFLOW_REASON = "sigma_estimate_underflow"


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
    """Build a ``Baseline`` recording exactly ``scores``, in the given order.

    Mirrors ``test_shewhart_fitting.py``'s identically-named/-shaped helper
    -- needed here (BIN-119) because the overflow/underflow scenarios
    require an exact, ordered sequence of scores, which
    ``_baseline_with_observations``'s single-repeated-``score`` shape
    cannot express.
    """
    baseline = Baseline()
    for score in scores:
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))
    return baseline


def _sufficient_baseline() -> Baseline:
    """A baseline that passes the sufficiency check and has non-zero variance."""
    return _baseline_with_observations(DEFAULT_SUFFICIENCY_THRESHOLD + 5)


def _capture_fitting_error(
    baseline: Baseline,
    *,
    target_arl: float | None,
    smoothing_param: float | None = None,
) -> CaliperError:
    """Call ``fit_ewma`` expecting it to raise, and return the raised error."""
    try:
        fit_ewma(baseline, target_arl=target_arl, smoothing_param=smoothing_param)
    except CaliperError as exc:
        return exc
    raise AssertionError("expected fit_ewma() to raise for this scenario")


# --- Happy path: core fitting -------------------------------------------------


def test_fits_ewma_control_limits_from_a_sufficient_baseline_with_a_tolerance() -> None:
    """The result contains UCL/LCL/CL and reports smoothing param, tolerance, method."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        smoothing_param=_SHAPE_TEST_SMOOTHING_PARAM,
    )

    # Assert
    assert isinstance(result, FittedEWMA)
    assert isinstance(result, FittedControlLimits)
    assert isinstance(result.ucl, float)
    assert isinstance(result.lcl, float)
    assert isinstance(result.cl, float)
    assert result.ucl > result.lcl  # a well-formed pair of limits
    assert result.smoothing_param == _SHAPE_TEST_SMOOTHING_PARAM
    assert result.requested_arl == _SHAPE_TEST_TARGET_ARL
    assert isinstance(result.achieved_arl, float)
    assert isinstance(result.calibration_method, str)
    assert result.calibration_method != ""


# --- Happy path: auditability --------------------------------------------------


def test_fitted_artefact_reports_baseline_statistics_and_provenance() -> None:
    """The artefact reports baseline mean/variance, count, and provenance."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        smoothing_param=_SHAPE_TEST_SMOOTHING_PARAM,
    )

    # Assert
    assert isinstance(result.baseline_mean, float)
    assert isinstance(result.baseline_spread, float)
    assert result.observation_count == baseline.observation_count
    signature = baseline.provenance_signature
    assert signature is not None
    assert result.provenance_model_version == signature.model_version.value
    assert result.provenance_criteria == signature.scoring_criteria.value


# --- Happy path: custom smoothing parameter ------------------------------------


def test_uses_the_engineers_custom_smoothing_parameter_rather_than_the_default() -> (
    None
):
    """A specified smoothing parameter overrides the library default."""
    # Arrange
    assert _CUSTOM_SMOOTHING_PARAM != DEFAULT_SMOOTHING_PARAM  # precondition
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        smoothing_param=_CUSTOM_SMOOTHING_PARAM,
    )

    # Assert
    assert result.smoothing_param == _CUSTOM_SMOOTHING_PARAM


# --- Happy path: default smoothing parameter ------------------------------------


def test_uses_the_library_default_smoothing_parameter_when_omitted() -> None:
    """Omitting the smoothing parameter uses the library default."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert result.smoothing_param == DEFAULT_SMOOTHING_PARAM


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
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

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
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _ZERO_VARIANCE_REASON


def test_does_not_raise_degenerate_baseline_error_when_exactly_one_score_differs() -> (
    None
):
    """Boundary: a single differing score is enough variance to fit.

    Mutation-testing finding carried from BIN-64 (CLAUDE.md, "carried
    findings"): the zero-variance guard's boundary needs deliberate pinning.
    BIN-64's boundary was about the *observation count* needed for variance
    to be defined (moot here -- fitting requires >= DEFAULT_SUFFICIENCY_
    THRESHOLD observations, far more than the minimum of two). The boundary
    that *is* reachable here is "more than one distinct score" -- this test
    pins it directly: exactly one observation differs from the rest, so
    there are exactly two distinct values, which must NOT be flagged as
    degenerate.
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
    result = fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedEWMA)


# --- Sad path: non-finite or zero moving-range sigma (BIN-119) ------------------
#
# External code review (Codex), 2026-09-11, reproduced against this exact
# function. Every individual score below is finite (`ScoringResult` already
# enforces that), but the *moving-range aggregate* `fit_ewma` derives from
# them via the shared `spc_numerics` estimator still overflows to +inf or
# underflows to 0.0 -- neither is caught by the zero-variance guard above,
# which only asks "are all scores identical?" Verified empirically (not
# assumed) that, unpatched, `fit_ewma` returns a "successfully fitted"
# artefact in both cases: `sigma_estimate=inf`/`ucl=inf`/`lcl=-inf` for the
# overflow case (a chart that can never signal -- the worst failure mode
# this library has), and `sigma_estimate=0.0`/`ucl==lcl==baseline_mean` for
# the underflow case (a chart where almost any future score immediately
# "signals"). See `tests/unit/baseline/test_spc_numerics.py`'s identically
# reasoned section for the full citation of what was verified and why
# `DegenerateBaselineError` is the right type, and for why the two `reason`
# values below must agree exactly across all three chart types' fitting
# test files plus that one.


def test_raises_degenerate_baseline_error_when_moving_range_is_non_finite() -> None:
    """Alternating near-float-max scores overflow the moving-range aggregate to +inf.

    Must be rejected at fit time -- no ``FittedEWMA`` with
    ``sigma_estimate=inf`` may ever be constructed.
    """
    # Arrange -- two distinct values, so the zero-variance guard above does
    # not fire first.
    provenance = ProvenanceFactory()
    scores = [1e308, -1e308] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)
    baseline = _baseline_from_scores(scores, provenance)

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

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
    time regardless -- no ``FittedEWMA`` with ``sigma_estimate=0.0`` (and
    therefore ``ucl == lcl``) may ever be constructed from this.
    """
    # Arrange -- one subnormal among an otherwise-identical baseline.
    provenance = ProvenanceFactory()
    half = DEFAULT_SUFFICIENCY_THRESHOLD // 2
    scores = [0.0] * half + [5e-324] + [0.0] * (half - 1)
    baseline = _baseline_from_scores(scores, provenance)

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _SIGMA_UNDERFLOW_REASON


# --- BIN-123: an intermediate that overflows must not stop a representable ------
# --- baseline from fitting ------------------------------------------------------
#
# Found while briefing the BIN-119 implementation, 2026-09-11, reproduced
# directly against ``fit_ewma``. ``statistics.fmean`` (used for
# ``baseline_mean``, and internally by ``_moving_range_sigma`` for the
# moving-range aggregate) delegates to ``math.fsum`` for its exactly-rounded
# result -- which raises ``OverflowError`` when an *intermediate* (running)
# sum exceeds float64's finite range, even when the true, final mean is
# itself perfectly representable. An alternating ``[1e307, 0.0, 1e307,
# 0.0, ...]`` baseline of 150 scores has a true mean of ``5e306`` and a true
# moving-range sigma of ``~8.86e306`` -- both comfortably representable --
# yet the running sum alone (``~7.5e308``) exceeds float64's ~1.7977e308
# max. Empirically confirmed, unpatched: ``fit_ewma`` raises
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
# ``fit_ewma`` expecting a normal return -- no ``pytest.raises`` -- so a fix
# of that wrong shape fails them directly.
#
# Ground truth is computed with ``fractions.Fraction`` -- exact rational
# arithmetic that cannot itself overflow -- independently of whatever
# summation strategy the fix under test ends up using; this is not a
# reimplementation of ``fit_ewma``'s formula (CLAUDE.md names five prior
# instances of exactly that self-cancelling-helper mistake on this
# project). See ``tests/unit/baseline/test_spc_numerics.py``'s identically
# reasoned section for the same ground-truth helpers, duplicated here per
# this file's own established convention of not importing test helpers
# across sibling fitting test files.

_OVERFLOW_PRONE_BASELINE_SIZE = 150

# 2/sqrt(pi), exact -- same derivation as spc_numerics.py's
# ``_MOVING_RANGE_D2`` and this file's sibling test files.
_D2 = 1.1283791670955126


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
    independent ``Fraction`` oracle, not merely that ``fit_ewma`` returns
    without raising -- a fix that silently returns an inaccurate value
    (e.g. ``inf``, from a careless ``numpy.mean``, verified separately to
    also mishandle this exact input) would pass a "did not raise" check but
    must fail this one. Also asserts the control limits are finite: an
    infinite ``ucl``/``lcl`` is this library's worst failure mode (BIN-119)
    and must not slip back in through this path.
    """
    # Arrange
    provenance = ProvenanceFactory()
    scores = _overflow_prone_but_representable_scores()
    baseline = _baseline_from_scores(scores, provenance)
    moving_ranges = [abs(b - a) for a, b in itertools.pairwise(scores)]
    expected_mean = _exact_mean(scores)
    expected_sigma = _exact_mean(moving_ranges) / _D2

    # Act -- must return normally; no pytest.raises around this call.
    result = fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedEWMA)
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
    result = fit_ewma(representable_baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
    assert isinstance(result, FittedEWMA)
    assert math.isfinite(result.ucl)
    assert math.isfinite(result.lcl)

    # Act / Assert -- non-representable case still raises the typed error
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_ewma(non_representable_baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
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
    result = fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert -- bit-identical, not merely close.
    assert result.baseline_mean == expected_mean


# --- Sad path: invalid smoothing parameter --------------------------------------


@pytest.mark.parametrize(
    "invalid_smoothing_param",
    [0.0, -0.1, MAX_SMOOTHING_PARAM * 2],
    ids=["zero", "negative", "above_upper_bound"],
)
def test_raises_invalid_parameter_error_for_an_invalid_smoothing_parameter(
    invalid_smoothing_param: float,
) -> None:
    """Every invalid smoothing parameter value raises a classifiable error."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    error = _capture_fitting_error(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        smoothing_param=invalid_smoothing_param,
    )

    # Assert
    assert isinstance(error, InvalidParameterError)
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "invalid"
    assert error.context["parameter"] == "smoothing_param"
    assert error.context["provided"] == invalid_smoothing_param
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Sad path: invalid false alarm tolerance --------------------------------------


@pytest.mark.parametrize(
    "invalid_target_arl",
    [0.0, -10.0, MAX_MEANINGFUL_ARL * 2],
    ids=["zero", "negative", "outside_meaningful_range"],
)
def test_raises_invalid_parameter_error_for_an_invalid_false_alarm_tolerance(
    invalid_target_arl: float,
) -> None:
    """Every invalid false alarm tolerance value raises a classifiable error."""
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


# --- Sad path: missing false alarm tolerance --------------------------------------


def test_raises_invalid_parameter_error_when_false_alarm_tolerance_is_omitted() -> None:
    """The false alarm tolerance is required -- omitting it fails loudly (ADR-004)."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    error = _capture_fitting_error(baseline, target_arl=None)

    # Assert -- InvalidParameterError(kind="missing"), never Python's TypeError
    assert isinstance(error, InvalidParameterError)
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "missing"
    assert error.context["parameter"] == "target_arl"
    # ADR-002 requires `constraint` on every invalid_parameter. The sibling
    # invalid-value tests assert it; this branch did not, and renaming the key
    # survived mutation testing as a result.
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


def test_fitted_ewma_artefact_is_immutable_after_creation() -> None:
    """No field of a fitted artefact can be reassigned after construction."""
    # Arrange
    baseline = _sufficient_baseline()
    result = fit_ewma(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        smoothing_param=_SHAPE_TEST_SMOOTHING_PARAM,
    )
    original_ucl = result.ucl
    original_smoothing_param = result.smoothing_param
    original_baseline_mean = result.baseline_mean
    original_provenance_model_version = result.provenance_model_version

    # Act / Assert -- limits, parameters, baseline statistics, provenance
    with pytest.raises(ValidationError):
        result.ucl = original_ucl + 1.0  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.smoothing_param = original_smoothing_param + 0.01  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.baseline_mean = original_baseline_mean + 1.0  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.provenance_model_version = "tampered"  # ty: ignore[invalid-assignment]

    assert result.ucl == original_ucl
    assert result.smoothing_param == original_smoothing_param
    assert result.baseline_mean == original_baseline_mean
    assert result.provenance_model_version == original_provenance_model_version


def test_fitted_ewma_satisfies_the_fitted_control_limits_protocol() -> None:
    """A fitted artefact structurally satisfies the shared protocol (ADR-004 §1)."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        smoothing_param=_SHAPE_TEST_SMOOTHING_PARAM,
    )

    # Assert
    assert isinstance(result, FittedControlLimits)


# --- Boundary: smoothing parameter at valid range limits ----------------------------


@pytest.mark.parametrize(
    "boundary_smoothing_param",
    [MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM],
    ids=["smallest_valid", "largest_valid"],
)
def test_fits_successfully_with_smoothing_parameter_at_the_valid_range_boundary(
    boundary_smoothing_param: float,
) -> None:
    """Boundary value analysis: the edges of the valid range are accepted."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        smoothing_param=boundary_smoothing_param,
    )

    # Assert
    assert isinstance(result, FittedEWMA)
    assert result.smoothing_param == boundary_smoothing_param


# --- Boundary: false alarm tolerance at meaningful range limits ---------------------


@pytest.mark.parametrize(
    "boundary_target_arl",
    [MIN_MEANINGFUL_ARL, MAX_MEANINGFUL_ARL],
    ids=["smallest_meaningful", "largest_meaningful"],
)
def test_fits_successfully_with_false_alarm_tolerance_at_the_meaningful_range_boundary(
    boundary_target_arl: float,
) -> None:
    """Boundary value analysis: the edges of the meaningful range are accepted."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(baseline, target_arl=boundary_target_arl)

    # Assert
    assert isinstance(result, FittedEWMA)
    assert result.requested_arl == boundary_target_arl
    assert isinstance(result.achieved_arl, float)


# --- Property: a fitted artefact's limits are always well-ordered -------------------


@settings(max_examples=20, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_MEANINGFUL_ARL, max_value=MAX_MEANINGFUL_ARL, allow_nan=False
    ),
    smoothing_param=st.floats(
        min_value=MIN_SMOOTHING_PARAM, max_value=MAX_SMOOTHING_PARAM, allow_nan=False
    ),
)
def test_ucl_is_always_above_cl_which_is_always_above_lcl(
    target_arl: float, smoothing_param: float
) -> None:
    """For any valid inputs, the three reported limits are consistently ordered."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_ewma(baseline, target_arl=target_arl, smoothing_param=smoothing_param)

    # Assert
    assert result.ucl > result.cl > result.lcl
