"""Unit tests for ``fit_cusum()`` (BIN-94) -- shape and behaviour, Part 1 of 2.

Pins the fifteen acceptance scenarios (21 executable with outline expansion)
in ``tests/bdd/features/baseline/cusum-control-limit-fitting.feature`` at the
unit layer, plus boundary/property cases the feature file's business rules
require but do not name as separate scenarios. Error assertions follow
ADR-002/ADR-008: type + required ``context`` keys only -- never message
text.

**This file asserts shape and behaviour only -- no numeric literal here is a
claim about statistical correctness.** Every concrete ``target_arl`` /
``reference_value`` value below is an arbitrary valid input chosen to
exercise a code path, exactly like the feature file's own scenarios (which
name zero numeric literals, deliberately -- see the feature file's header)
and exactly the discipline ``tests/unit/baseline/test_ewma_fitting.py``
already established for the sibling EWMA story.

**The numerical proof lives in a separate file on purpose**:
``tests/unit/baseline/test_cusum_arl_published_values.py`` verifies specific
(reference_value, target_arl) -> (decision_interval, achieved_arl) results
against a published/independently-computed CUSUM design point, per
Siegmund's (1985) approximation. Keeping the two apart means a reader can
tell instantly, from the file a failure is in, whether a broken test means
"the API contract changed" (this file) or "the calibration is statistically
wrong" (that file) -- the same split the BIN-94 brief explicitly instructs,
mirroring BIN-65.

``fit_cusum()``, ``FittedCUSUM`` and ``FittedControlLimits`` exist only as
scaffolds (``src/caliper/baseline/domain/``): ``fit_cusum()`` always raises
``NotImplementedError``. Every test below that calls it is expected to fail
for that reason until ``domain-implementer`` replaces the scaffold --
``uv run pytest`` therefore fails; that is the correct state for this
ticket (TDD red phase).

**No new factory for ``FittedCUSUM``.** Every test obtains its
``FittedCUSUM`` by calling ``fit_cusum()`` -- never by constructing one
directly, mirroring the convention ``test_ewma_fitting.py`` established for
``FittedEWMA``.

**Decisions this file makes, flagged rather than guessed silently** (mirrors
``test_ewma_fitting.py``'s own "Decisions this file makes" section, which
this list does not re-argue where it applies identically):

1. **``DegenerateBaselineError.context["reason"] == "zero_variance"`` is
   pinned**, matching ``docs/domain-model.md``'s Error Contract Reference
   worked example and the identical precedent BIN-64/BIN-65 established.
2. **``InvalidParameterError.context["parameter"]`` is pinned to the exact
   Python parameter name** (``"target_arl"``, ``"reference_value"``,
   ``"direction"``), matching ADR-004 section 5's exact fitting signature
   (``fit_cusum(baseline, *, target_arl=None, reference_value=None,
   direction=None)``).
3. **OQ-3 (sufficiency check internal or external to fitting) is left
   open, on purpose**, identically to BIN-65.
4. **``InsufficientBaselineError.context["need"]`` is pinned to
   ``DEFAULT_SUFFICIENCY_THRESHOLD``**, identically to BIN-65 -- ``fit_cusum``
   has no threshold parameter (ADR-004 section 5) and OQ-4 forecloses an
   override mechanism.
5. **The direction parameter's valid set is treated as a closed, three-member
   set** (``"two_sided"``, ``"lower"``, ``"upper"``) per ADR-004 section 6 --
   any other string, including plausible near-misses, is invalid. This file
   uses one arbitrary invalid string (never a value from the valid set) for
   the invalid-direction scenario; the exact valid set itself is pinned once,
   in ``test_fitting_accepts_every_member_of_the_documented_direction_set``,
   rather than repeated as a magic literal across every direction-happy-path
   test.
6. **BIN-117 (external code review, 2026-09-11): an unattainable
   ``(reference_value, direction, target_arl)`` combination raises
   ``InvalidParameterError``, category ``invalid_parameter``, rather than
   ``fit_cusum`` silently returning ``_MIN_DECISION_INTERVAL`` with an
   ``achieved_arl`` far above what was requested.** The minimum ARL0
   actually attainable for a given ``(reference_value, direction)`` is
   computed by production's own ``_min_attainable_arl0`` -- imported
   directly here, not reimplemented, per ``memory/vector-search.md``'s
   "pattern found -- use it" and to remove the drift risk a second, private
   copy of this same formula turned out to create (see the "Second-pass
   correction" note below). ``_min_attainable_arl0`` evaluates
   ``_cusum_arl0(reference_value, h)`` at ``h = _MIN_DECISION_INTERVAL`` --
   the smallest decision interval ``_calibrate_decision_interval`` will
   ever return, not the mathematical (open, unattained) limit at ``h = 0``
   -- one-sided, halved via ``_combine_two_sided_arl0`` for
   ``"two_sided"``. This file's tests are about the *unattainability
   contract* (does ``fit_cusum`` correctly detect and reject this, and is
   what it reports genuinely usable?), not Siegmund's formula's own
   correctness, which ``test_cusum_arl_published_values.py`` already
   verifies independently against Montgomery's (2013) worked example and
   SAS's independently-computed figure (see that file's module docstring).
   The new error's ``context`` reuses the existing ``invalid_parameter``
   required keys (``parameter="target_arl"``, ``kind="invalid"``,
   ``provided``, ``constraint``) plus additional fields the ticket
   specifically asks for so the engineer can see what to change:
   ``reference_value``, ``direction``, ``min_attainable_arl``. No new
   category is introduced (ADR-002 section 2 already covers "a supplied
   value violates a constraint" -- this is exactly that, the constraint
   just depends on two other parameters instead of one).

   ⚠️ **Residual tension flagged by ``backend-test-writer``, resolved by
   ``domain-implementer``.** The unattainable-ARL0 zone is not unique to the
   external review's extreme ``reference_value=5.0`` example -- it exists
   at *every* reference value, including the library default
   (``DEFAULT_REFERENCE_VALUE=0.5``, two-sided infimum ~1.043), whenever
   ``target_arl`` sits below that chart's own infimum. This file's
   pre-existing
   ``test_fits_successfully_with_false_alarm_tolerance_at_the_meaningful_range_boundary``
   (``smallest_meaningful`` case) originally fixed ``target_arl`` at
   ``MIN_MEANINGFUL_ARL=1.0`` at the default reference value, which sits
   **inside** that zone by a small margin (~4.3%) -- a genuinely
   unattainable combination BIN-117's fix now (correctly) rejects.
   ``MIN_MEANINGFUL_ARL`` is a library-wide mathematical floor (``E[N] >=
   1`` for any stopping time), not a per-chart-parameter guarantee that
   every meaningful ARL0 is attainable at every reference value, so this
   was a boundary the test was conflating, not a case the fix should carve
   an exception for. Resolved by deriving the ``smallest_meaningful`` case
   from the actual per-``k`` infimum
   (``_SMALLEST_MEANINGFUL_TARGET_ARL_AT_DEFAULT_REFERENCE_VALUE``) instead
   of the library-wide floor -- a strategy/boundary correction, not a
   weakened assertion: the test still asserts the identical success
   properties it always did, just against an input that is actually
   attainable at this reference value.

   ⚠️ **Second-pass correction, found in review of the first fix.**
   ``_min_attainable_arl0`` originally evaluated at the mathematical limit
   ``h = 0`` -- an *open* bound, approached but never itself attained by
   ``_calibrate_decision_interval``, whose search bracket floors at
   ``_MIN_DECISION_INTERVAL`` (1e-6), not 0. That left a narrow band of
   genuinely-unattainable ``target_arl`` values just above the ``h=0``
   figure but below the true floor able to pass the pre-check and still
   silently bottom out during calibration -- the identical defect class
   BIN-117 exists to close, one level down. Fixed by evaluating
   ``_min_attainable_arl0`` at ``h = _MIN_DECISION_INTERVAL`` instead (see
   that function's docstring in ``cusum_fitting.py``), which makes it
   genuinely attainable -- proven directly by
   ``test_fits_successfully_when_target_arl_equals_the_minimum_attainable_exactly``
   below, and by this file no longer keeping its own duplicate copy of the
   helper (imported from production instead, removing the drift risk that
   let the two versions disagree in the first place).

Uses ``ScoringResultFactory``/``ProvenanceFactory`` (``tests/factories.py``)
for observations where the specific score does not matter, per that
module's own guidance.
"""

from __future__ import annotations

import itertools
import math
from fractions import Fraction

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from caliper.baseline import (
    DEFAULT_REFERENCE_VALUE,
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    FittingAdvisory,
    fit_cusum,
)

# MIN_*/MAX_* validation bounds are internal (BIN-110 P2) -- no longer
# re-exported from caliper.baseline, so tests that need the exact bound
# values import them from the owning submodule directly.
#
# BIN-117: `_min_attainable_arl0` is imported directly too -- see the module
# docstring's "Decisions this file makes" point 6. This file previously
# duplicated its own copy of this helper (computing the *open* h=0 bound),
# which review found let a narrow band of genuinely-unattainable
# `target_arl` values slip past `fit_cusum`'s pre-check -- the same defect
# class, one level removed. Importing the production function directly
# (now fixed to evaluate at `h = _MIN_DECISION_INTERVAL`, the true
# attainable floor) instead of re-deriving it here removes that drift risk
# entirely: this file and `fit_cusum` now cannot disagree about what "the
# minimum attainable ARL0" means, because they call the same function.
from caliper.baseline.domain.cusum_fitting import (
    MAX_MEANINGFUL_ARL,
    MAX_REFERENCE_VALUE,
    MIN_REFERENCE_VALUE,
    MIN_TARGET_ARL,
    _min_attainable_arl0,
)
from caliper.baseline.domain.ewma_fitting import MIN_COHERENT_ARL
from caliper.baseline.domain.parameter_guards import VERIFIED_ARL_FLOOR
from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)
from caliper.measurement import Provenance
from tests.factories import ProvenanceFactory, ScoringResultFactory

# Arbitrary, sufficiently-large target ARL0 and reference value used across
# the happy-path/shape scenarios below. Their values carry no statistical
# meaning here -- unlike test_cusum_arl_published_values.py, this file
# asserts shape and behaviour only, never a specific achieved-ARL or
# decision-interval figure, so no citation is required for these two
# constants.
_SHAPE_TEST_TARGET_ARL = 370.0
_SHAPE_TEST_REFERENCE_VALUE = 0.4

# A custom reference value distinct from both DEFAULT_REFERENCE_VALUE and
# _SHAPE_TEST_REFERENCE_VALUE, for the "engineer overrides the default"
# scenario -- its value likewise carries no statistical meaning.
_CUSTOM_REFERENCE_VALUE = 0.8

_IDENTICAL_SCORE = 0.62
_ZERO_VARIANCE_REASON = "zero_variance"

# BIN-119: two additional `DegenerateBaselineError.context["reason"]` values,
# for a moving-range aggregate that overflows to +inf or underflows to 0.0 --
# distinct from `_ZERO_VARIANCE_REASON` above, which stays a separate,
# working guard over the *raw scores*. See
# `tests/unit/baseline/test_spc_numerics.py`'s identically-named constants
# and its "Sad path: non-finite or zero moving-range aggregate" section for
# the full reasoning -- this file's values must agree with that file's and
# with `test_ewma_fitting.py`'s/`test_shewhart_fitting.py`'s, since all four
# name the same guard, reused by all three chart types through the one
# shared `spc_numerics` module.
_NON_FINITE_SIGMA_REASON = "non_finite_sigma_estimate"
_SIGMA_UNDERFLOW_REASON = "sigma_estimate_underflow"

# The three-member closed direction set ADR-004 section 6 specifies. Pinned
# once, here, rather than repeated as a magic literal across every test that
# needs "a valid direction" or "the full valid set".
_VALID_DIRECTIONS = ("two_sided", "lower", "upper")

# An arbitrary string outside _VALID_DIRECTIONS, for the invalid-direction
# scenario. Not a value anyone would plausibly mistake for a near-miss of a
# valid member (unlike, say, "twosided" or "both").
_INVALID_DIRECTION = "sideways"


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
    reference_value: float | None = None,
    direction: str | None = None,
) -> CaliperError:
    """Call ``fit_cusum`` expecting it to raise, and return the raised error."""
    try:
        fit_cusum(
            baseline,
            target_arl=target_arl,
            reference_value=reference_value,
            direction=direction,
        )
    except CaliperError as exc:
        return exc
    raise AssertionError("expected fit_cusum() to raise for this scenario")


# BIN-117: at the library default reference value, MIN_COHERENT_ARL (1.0,
# formerly MIN_MEANINGFUL_ARL) itself sits inside the unattainable zone --
# the two-sided minimum attainable ARL0 at DEFAULT_REFERENCE_VALUE (0.5) is
# ~1.0431, not 1.0. This is the residual tension this file's own module
# docstring ("Decisions this file makes" point 6) flagged rather than
# resolved: MIN_COHERENT_ARL is a library-wide mathematical floor (E[N] >=
# 1 for any stopping time), not a per-reference-value guarantee that every
# coherent ARL0 is attainable. `fit_cusum` now (correctly) rejects
# target_arl=MIN_COHERENT_ARL at the default reference value, so the
# "smallest meaningful" boundary this file exercises must be redefined as
# the actual per-k minimum attainable value, not the library-wide floor --
# otherwise this test would assert success for an input BIN-117's own fix
# now (correctly) rejects.
#
# No margin above the minimum: `_min_attainable_arl0` now reports a
# genuinely-attainable value (evaluated at h=_MIN_DECISION_INTERVAL, not
# the unattained h=0 limit -- see that function's docstring), so sitting
# exactly on it is itself a stronger boundary test than a value some
# distance away, and is the same value
# `test_fits_successfully_when_target_arl_equals_the_minimum_attainable_exactly`
# proves succeeds for MAX_REFERENCE_VALUE. The complementary "some margin
# above the boundary" case is already covered separately by
# `test_fits_successfully_when_target_arl_is_just_above_the_minimum_attainable`.
#
# ADR-011/BIN-131: a second, independent floor now applies -- MIN_TARGET_ARL
# (100). At DEFAULT_REFERENCE_VALUE=0.5 the attainability floor (~1.0431)
# sits far below MIN_TARGET_ARL, so MIN_TARGET_ARL is the one that actually
# binds; `max()` keeps this correct regardless of which floor binds at a
# given reference_value (see test_cusum_arl_simulated_properties.py's
# identical `max()` fix for the same reasoning).
_SMALLEST_MEANINGFUL_TARGET_ARL_AT_DEFAULT_REFERENCE_VALUE = max(
    _min_attainable_arl0(DEFAULT_REFERENCE_VALUE, "two_sided"), MIN_TARGET_ARL
)


# --- Happy path: core fitting -------------------------------------------------


def test_fits_cusum_control_limits_from_a_sufficient_baseline_with_a_tolerance() -> (
    None
):
    """The result contains the decision interval/target value and reports metadata."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=_SHAPE_TEST_REFERENCE_VALUE,
    )

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert isinstance(result, FittedControlLimits)
    assert isinstance(result.decision_interval, float)
    assert isinstance(result.target_value, float)
    assert result.reference_value == _SHAPE_TEST_REFERENCE_VALUE
    assert isinstance(result.direction, str)
    assert result.direction != ""
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
    result = fit_cusum(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=_SHAPE_TEST_REFERENCE_VALUE,
    )

    # Assert
    assert isinstance(result.baseline_mean, float)
    assert isinstance(result.baseline_spread, float)
    assert result.observation_count == baseline.observation_count
    signature = baseline.provenance_signature
    assert signature is not None
    assert result.provenance_model_version == signature.model_version.value
    assert result.provenance_criteria == signature.scoring_criteria.value


# --- Happy path: custom reference value ------------------------------------


def test_uses_the_engineers_custom_reference_value_rather_than_the_default() -> None:
    """A specified reference value overrides the library default."""
    # Arrange
    assert _CUSTOM_REFERENCE_VALUE != DEFAULT_REFERENCE_VALUE  # precondition
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=_CUSTOM_REFERENCE_VALUE,
    )

    # Assert
    assert result.reference_value == _CUSTOM_REFERENCE_VALUE


# --- Happy path: default reference value ------------------------------------


def test_uses_the_library_default_reference_value_when_omitted() -> None:
    """Omitting the reference value uses the library default."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert result.reference_value == DEFAULT_REFERENCE_VALUE


# --- Happy path: decision interval is derived, not specified ------------------


def test_decision_interval_is_reported_without_being_an_input_parameter() -> None:
    """The engineer cannot specify the decision interval directly (A5).

    ``fit_cusum``'s signature (ADR-004 section 5) has no ``decision_interval``
    parameter -- passing one is a ``TypeError`` at the call site, not a
    ``CaliperError``, and this test does not attempt it (asserting on a raw
    ``TypeError`` from an unknown keyword would test Python's own calling
    convention, not Caliper). Instead this test asserts the positive claim:
    fitting with only the parameters the signature actually accepts still
    produces a reported decision interval.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=_SHAPE_TEST_REFERENCE_VALUE,
    )

    # Assert
    assert isinstance(result.decision_interval, float)
    with pytest.raises(TypeError):
        fit_cusum(
            baseline,
            target_arl=_SHAPE_TEST_TARGET_ARL,
            decision_interval=4.0,  # type: ignore[call-arg]  # ty: ignore[unknown-argument]
        )


# --- Happy path: direction reporting -------------------------------------------


@pytest.mark.parametrize("direction", _VALID_DIRECTIONS)
def test_fitting_accepts_every_member_of_the_documented_direction_set(
    direction: str,
) -> None:
    """Every direction ADR-004 section 6 documents is accepted and reported back."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL, direction=direction)

    # Assert
    assert result.direction == direction


def test_uses_the_library_default_direction_when_omitted() -> None:
    """Omitting direction defaults to two-sided (ADR-004 section 6)."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert result.direction == "two_sided"


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
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

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
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _ZERO_VARIANCE_REASON


def test_does_not_raise_degenerate_baseline_error_when_exactly_one_score_differs() -> (
    None
):
    """Boundary: a single differing score is enough variance to fit.

    Mirrors ``test_ewma_fitting.py``'s identically-named test -- the same
    mutation-testing finding carried from BIN-64 (CLAUDE.md, "carried
    findings"): the zero-variance guard's boundary needs deliberate pinning.
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
    result = fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedCUSUM)


# --- Sad path: non-finite or zero moving-range sigma (BIN-119) ------------------
#
# External code review (Codex), 2026-09-11, reproduced against this exact
# function -- and this is the chart where the review's Half 2 crash was
# actually observed: `Monitor.record()` against a `FittedCUSUM` fitted from
# a zero-underflowed baseline divides by `sigma_estimate` and raises a raw
# `ZeroDivisionError`, not a `CaliperError`. See
# `tests/unit/baseline/test_spc_numerics.py`'s identically reasoned section
# for the full citation of what was verified (including that EWMA and
# Shewhart also construct a bad artefact from both cases, even though only
# CUSUM crashes downstream at `record()`) and why `DegenerateBaselineError`
# is the right type; and `tests/unit/monitoring/test_monitor.py` for the
# direct `Monitor.record()` reproduction of the `ZeroDivisionError` this fix
# must prevent from ever being reachable, by rejecting at fit time instead.


def test_raises_degenerate_baseline_error_when_moving_range_is_non_finite() -> None:
    """Alternating near-float-max scores overflow the moving-range aggregate to +inf.

    Must be rejected at fit time -- no ``FittedCUSUM`` with
    ``sigma_estimate=inf`` may ever be constructed.
    """
    # Arrange -- two distinct values, so the zero-variance guard above does
    # not fire first.
    provenance = ProvenanceFactory()
    scores = [1e308, -1e308] * (DEFAULT_SUFFICIENCY_THRESHOLD // 2)
    baseline = _baseline_from_scores(scores, provenance)

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

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
    time -- this is the exact baseline shape that, unpatched, lets
    ``Monitor.record()`` raise a raw ``ZeroDivisionError`` later (see the
    section docstring above); rejecting here at fit time means no
    ``FittedCUSUM`` with ``sigma_estimate=0.0`` can ever reach a ``Monitor``
    in the first place.
    """
    # Arrange -- one subnormal among an otherwise-identical baseline.
    provenance = ProvenanceFactory()
    half = DEFAULT_SUFFICIENCY_THRESHOLD // 2
    scores = [0.0] * half + [5e-324] + [0.0] * (half - 1)
    baseline = _baseline_from_scores(scores, provenance)

    # Act
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    error = exc_info.value
    assert error.category == "degenerate_baseline"
    assert error.context["reason"] == _SIGMA_UNDERFLOW_REASON


# --- BIN-123: an intermediate that overflows must not stop a representable ------
# --- baseline from fitting ------------------------------------------------------
#
# Found while briefing the BIN-119 implementation, 2026-09-11, reproduced
# directly against ``fit_cusum``. ``statistics.fmean`` (used for
# ``baseline_mean``/``target_value``, and internally by
# ``_moving_range_sigma`` for the moving-range aggregate) delegates to
# ``math.fsum`` for its exactly-rounded result -- which raises
# ``OverflowError`` when an *intermediate* (running) sum exceeds float64's
# finite range, even when the true, final mean is itself perfectly
# representable. An alternating ``[1e307, 0.0, 1e307, 0.0, ...]`` baseline
# of 150 scores has a true mean of ``5e306`` and a true moving-range sigma
# of ``~8.86e306`` -- both comfortably representable -- yet the running sum
# alone (``~7.5e308``) exceeds float64's ~1.7977e308 max. Empirically
# confirmed, unpatched: ``fit_cusum`` raises ``OverflowError: intermediate
# overflow in fsum`` on this input, never reaching BIN-119's
# ``math.isfinite`` guard.
#
# 🚨 The obvious "fix" -- catch ``OverflowError`` and raise
# ``DegenerateBaselineError`` -- is wrong, not merely incomplete (BIN-123).
# It would convert a visible leak into a confident, well-typed *rejection of
# data this library should fit perfectly well*, collapsing this case into
# the genuinely non-representable one the two tests directly above already
# cover correctly (alternating ``+/-1e308``, whose true moving range
# (``2e308``) is not representable in float64 at all). The tests below call
# ``fit_cusum`` expecting a normal return -- no ``pytest.raises`` -- so a
# fix of that wrong shape fails them directly.
#
# Ground truth is computed with ``fractions.Fraction`` -- exact rational
# arithmetic that cannot itself overflow -- independently of whatever
# summation strategy the fix under test ends up using; this is not a
# reimplementation of ``fit_cusum``'s formula (CLAUDE.md names five prior
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

    Asserts the reported ``baseline_mean``/``sigma_estimate``/
    ``target_value`` against an independent ``Fraction`` oracle, not merely
    that ``fit_cusum`` returns without raising -- a fix that silently
    returns an inaccurate value (e.g. ``inf``, from a careless
    ``numpy.mean``, verified separately to also mishandle this exact input)
    would pass a "did not raise" check but must fail this one. Also asserts
    ``decision_interval`` is finite and positive: this is the exact
    baseline shape that, unpatched, lets ``Monitor.record()`` raise a raw
    ``ZeroDivisionError`` for the *sibling* underflow case (BIN-119) --
    confirming the overflow case does not construct an equally unusable
    artefact by a different route.
    """
    # Arrange
    provenance = ProvenanceFactory()
    scores = _overflow_prone_but_representable_scores()
    baseline = _baseline_from_scores(scores, provenance)
    moving_ranges = [abs(b - a) for a, b in itertools.pairwise(scores)]
    expected_mean = _exact_mean(scores)
    expected_sigma = _exact_mean(moving_ranges) / _D2

    # Act -- must return normally; no pytest.raises around this call.
    result = fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert result.baseline_mean == pytest.approx(expected_mean, rel=1e-9)
    assert result.sigma_estimate == pytest.approx(expected_sigma, rel=1e-9)
    assert result.target_value == pytest.approx(expected_mean, rel=1e-9)
    assert math.isfinite(result.decision_interval)
    assert result.decision_interval > 0.0


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
    result = fit_cusum(representable_baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
    assert isinstance(result, FittedCUSUM)
    assert math.isfinite(result.decision_interval)

    # Act / Assert -- non-representable case still raises the typed error
    with pytest.raises(DegenerateBaselineError) as exc_info:
        fit_cusum(non_representable_baseline, target_arl=_SHAPE_TEST_TARGET_ARL)
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
    result = fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)

    # Assert -- bit-identical, not merely close.
    assert result.baseline_mean == expected_mean
    assert result.target_value == expected_mean


# --- Sad path: invalid reference value --------------------------------------


@pytest.mark.parametrize(
    "invalid_reference_value",
    [0.0, -0.1, MAX_REFERENCE_VALUE * 2],
    ids=["zero", "negative", "above_upper_bound"],
)
def test_raises_invalid_parameter_error_for_an_invalid_reference_value(
    invalid_reference_value: float,
) -> None:
    """Every invalid reference value raises a classifiable error."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    error = _capture_fitting_error(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=invalid_reference_value,
    )

    # Assert
    assert isinstance(error, InvalidParameterError)
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "invalid"
    assert error.context["parameter"] == "reference_value"
    assert error.context["provided"] == invalid_reference_value
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


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

    ``MIN_COHERENT_ARL`` (1.0) is rejected by ADR-011's policy floor
    (``MIN_TARGET_ARL``, 100) before ``fit_cusum`` ever reaches the
    per-``k`` attainability check (BIN-117) -- the two are independent
    bounds and this is the one that binds first at the library default
    ``reference_value``.
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
# does not. Fixed at the library default reference_value, where MIN_TARGET_ARL
# (not the per-k attainability floor, ~1.0431) is the one that binds.


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
    result = fit_cusum(baseline, target_arl=flagged_target_arl)

    # Assert
    assert isinstance(result, FittedCUSUM)
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
    result = fit_cusum(baseline, target_arl=clean_target_arl)

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert result.advisories == ()


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
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Sad path: invalid direction -------------------------------------------------


def test_raises_invalid_parameter_error_for_an_unrecognised_direction() -> None:
    """An unrecognised direction raises a classifiable error (ADR-004 section 6)."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    error = _capture_fitting_error(
        baseline, target_arl=_SHAPE_TEST_TARGET_ARL, direction=_INVALID_DIRECTION
    )

    # Assert
    assert isinstance(error, InvalidParameterError)
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "invalid"
    assert error.context["parameter"] == "direction"
    assert error.context["provided"] == _INVALID_DIRECTION
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Sad path: unattainable false alarm tolerance (BIN-117) -----------------
#
# When target_arl sits below the minimum ARL0 actually attainable for the
# given (reference_value, direction) -- computed by `_min_attainable_arl0`
# (imported from production) at h=_MIN_DECISION_INTERVAL, the smallest
# decision interval `_calibrate_decision_interval` will ever return -- no
# non-negative decision interval can reach it. Before the BIN-117 fix,
# `_calibrate_decision_interval` silently returned `_MIN_DECISION_INTERVAL`
# and reported the (far higher) achieved figure as `achieved_arl` -- a
# silent 3.1x/6.3x miscalibration reproduced by external code review,
# 2026-09-11 (Linear BIN-117):
#
#   k=5.0 two_sided   requested=370   achieved=1158.3   h=0.000001
#   k=5.0 upper       requested=370   achieved=2316.7   h=0.000001
#
# `fit_cusum` must instead raise `InvalidParameterError` before ever
# treating that bound-hit as a usable result.
#
# ⚠️ A second review pass found the first fix's own pre-check compared
# against the wrong quantity -- the *open* h=0 limit, not the *attainable*
# h=_MIN_DECISION_INTERVAL floor -- which let a narrow band of genuinely
# unattainable target_arl values slip through and still bottom out during
# calibration, and made the error's own `min_attainable_arl` a value the
# library would not actually accept back. `test_raises_invalid_parameter_`
# `error_when_target_arl_is_below_the_minimum_attainable` below did not
# catch this because it only ever probed comfortably below the (wrong)
# reported floor, never in the gap between the two -- exactly why the
# round-trip test after it exists now.


@pytest.mark.parametrize("direction", _VALID_DIRECTIONS)
def test_raises_invalid_parameter_error_when_target_arl_is_below_the_minimum_attainable(
    direction: str,
) -> None:
    """A target_arl below the (reference_value, direction) infimum is rejected.

    Reproduces the external review's exact finding: reference_value=5.0
    (MAX_REFERENCE_VALUE) with target_arl=370 is unattainable in every
    direction -- the true minimum attainable ARL0 at k=5.0 is far higher
    (~2316.6 one-sided / ~1158.3 two-sided), so no non-negative decision
    interval can reach 370.
    """
    # Arrange
    baseline = _sufficient_baseline()
    min_attainable = _min_attainable_arl0(MAX_REFERENCE_VALUE, direction)
    assert (
        _SHAPE_TEST_TARGET_ARL < min_attainable
    )  # precondition: genuinely unattainable

    # Act
    error = _capture_fitting_error(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=MAX_REFERENCE_VALUE,
        direction=direction,
    )

    # Assert -- reuses the existing invalid_parameter required keys
    assert isinstance(error, InvalidParameterError)
    assert error.category == "invalid_parameter"
    assert error.context["kind"] == "invalid"
    assert error.context["parameter"] == "target_arl"
    assert error.context["provided"] == _SHAPE_TEST_TARGET_ARL
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""

    # Assert -- additional context the ticket specifically asks for, so the
    # engineer can see what to change without re-deriving the infimum
    # themselves.
    assert error.context["reference_value"] == MAX_REFERENCE_VALUE
    assert error.context["direction"] == direction
    assert isinstance(error.context["min_attainable_arl"], float)
    assert error.context["min_attainable_arl"] == pytest.approx(
        min_attainable, rel=1e-6
    )
    # The reported minimum must itself be a coherent ARL0 -- and, since the
    # whole point is that it exceeds what was requested, strictly greater
    # than the (rejected) provided value.
    assert error.context["min_attainable_arl"] > _SHAPE_TEST_TARGET_ARL


def test_unattainable_arl_error_distinct_recovery_hint_from_out_of_range() -> None:
    """The unattainable-combination error is still classifiable the same way
    as an ordinary out-of-range target_arl (same category, same required
    keys) -- ADR-002 does not need a new category for this -- but its
    recovery guidance differs, since the fix is "pick a reachable target",
    not "pick a value inside the legal range" (the target here IS inside
    [MIN_TARGET_ARL, MAX_MEANINGFUL_ARL])."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    unattainable = _capture_fitting_error(
        baseline, target_arl=_SHAPE_TEST_TARGET_ARL, reference_value=MAX_REFERENCE_VALUE
    )
    out_of_range = _capture_fitting_error(baseline, target_arl=0.0)

    # Assert -- both classifiable identically...
    assert unattainable.category == out_of_range.category == "invalid_parameter"
    # ...but distinct, non-empty recovery guidance.
    assert unattainable.recovery_hint != out_of_range.recovery_hint
    assert unattainable.recovery_hint != ""


# --- Boundary: the reported minimum is itself genuinely attainable (BIN-117) --
#
# The test review that found the first fix's pre-check compared against the
# wrong (open, h=0) bound asked for exactly this: the value the error
# reports in `context["min_attainable_arl"]` must itself succeed when
# passed straight back as `target_arl` -- "errors are UX" means a caller
# who does exactly what the error tells them must not get the same error
# again. This is the assertion that would have caught the second-pass
# defect; its prior absence is why 526 green tests did not.


@pytest.mark.parametrize("direction", _VALID_DIRECTIONS)
def test_fits_successfully_when_target_arl_equals_the_minimum_attainable_exactly(
    direction: str,
) -> None:
    """The exact ``min_attainable_arl`` an unattainable-target error reports
    is itself a value ``fit_cusum`` accepts -- round-tripping the error's
    own ``context`` back in as input must succeed, not raise again.
    """
    # Arrange -- first, trigger the error and capture the value it reports,
    # exactly as an engineer following its recovery_hint would.
    baseline = _sufficient_baseline()
    unattainable_error = _capture_fitting_error(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=MAX_REFERENCE_VALUE,
        direction=direction,
    )
    reported_minimum = unattainable_error.context["min_attainable_arl"]

    # Act -- pass that exact value straight back in.
    result = fit_cusum(
        baseline,
        target_arl=reported_minimum,
        reference_value=MAX_REFERENCE_VALUE,
        direction=direction,
    )

    # Assert -- succeeds, and reports back the value asked for.
    assert isinstance(result, FittedCUSUM)
    assert result.decision_interval > 0.0
    assert result.requested_arl == reported_minimum


# --- Boundary: a target just above the minimum still succeeds (BIN-117) -----


@pytest.mark.parametrize("direction", _VALID_DIRECTIONS)
def test_fits_successfully_when_target_arl_is_just_above_the_minimum_attainable(
    direction: str,
) -> None:
    """The boundary must not over-reject: a reachable target just above the
    infimum still fits, and achieved_arl lands close to what was requested
    -- BIN-117 explicitly warns the fix must not turn into a broader
    rejection of realistic, attainable targets.
    """
    # Arrange
    baseline = _sufficient_baseline()
    min_attainable = _min_attainable_arl0(MAX_REFERENCE_VALUE, direction)
    reachable_target = min_attainable * 1.05  # comfortably attainable

    # Act
    result = fit_cusum(
        baseline,
        target_arl=reachable_target,
        reference_value=MAX_REFERENCE_VALUE,
        direction=direction,
    )

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert result.decision_interval > 0.0
    relative_gap = abs(result.achieved_arl - reachable_target) / reachable_target
    assert relative_gap < 0.05


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


def test_fitted_cusum_artefact_is_immutable_after_creation() -> None:
    """No field of a fitted artefact can be reassigned after construction."""
    # Arrange
    baseline = _sufficient_baseline()
    result = fit_cusum(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=_SHAPE_TEST_REFERENCE_VALUE,
    )
    original_decision_interval = result.decision_interval
    original_reference_value = result.reference_value
    original_baseline_mean = result.baseline_mean
    original_provenance_model_version = result.provenance_model_version
    original_direction = result.direction

    # Act / Assert -- limits, parameters, baseline statistics, provenance
    with pytest.raises(ValidationError):
        result.decision_interval = original_decision_interval + 1.0  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.reference_value = original_reference_value + 0.01  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.baseline_mean = original_baseline_mean + 1.0  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.provenance_model_version = "tampered"  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError):
        result.direction = "lower"  # ty: ignore[invalid-assignment]

    assert result.decision_interval == original_decision_interval
    assert result.reference_value == original_reference_value
    assert result.baseline_mean == original_baseline_mean
    assert result.provenance_model_version == original_provenance_model_version
    assert result.direction == original_direction


def test_fitted_cusum_satisfies_the_fitted_control_limits_protocol() -> None:
    """A fitted artefact structurally satisfies the shared protocol (ADR-004 §1)."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=_SHAPE_TEST_REFERENCE_VALUE,
    )

    # Assert
    assert isinstance(result, FittedControlLimits)


# --- Boundary: reference value at valid range limits ----------------------------


@pytest.mark.parametrize(
    "boundary_reference_value",
    [MIN_REFERENCE_VALUE, MAX_REFERENCE_VALUE],
    ids=["smallest_valid", "largest_valid"],
)
def test_fits_successfully_with_reference_value_at_the_valid_range_boundary(
    boundary_reference_value: float,
) -> None:
    """Boundary value analysis: the edges of the valid range are accepted.

    **Updated for BIN-117.** This test previously fixed ``target_arl`` at
    ``_SHAPE_TEST_TARGET_ARL`` (370) for both boundary reference values.
    At ``MAX_REFERENCE_VALUE`` (5.0) that combination is exactly the
    external review's reproduced defect -- the minimum attainable
    two-sided ARL0 at k=5.0 is ~1158.3, so 370 is genuinely unattainable
    and (correctly, post-fix) raises rather than fitting. Asserting success
    with that literal here would directly contradict this file's own
    unattainable-target tests below, for the identical inputs. Deriving
    the target from the reference value under test keeps this a pure
    boundary-value-of-``reference_value`` test, decoupled from
    ``target_arl`` attainability -- exactly what BIN-117 revealed this
    test was silently conflating before the fix. The smallest-valid case
    is unaffected: 370 remains comfortably attainable at
    ``MIN_REFERENCE_VALUE`` (0.01), so ``max()`` below leaves it unchanged.
    """
    # Arrange
    baseline = _sufficient_baseline()
    target_arl = max(
        _SHAPE_TEST_TARGET_ARL,
        _min_attainable_arl0(boundary_reference_value, "two_sided") * 1.5,
    )

    # Act
    result = fit_cusum(
        baseline,
        target_arl=target_arl,
        reference_value=boundary_reference_value,
    )

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert result.reference_value == boundary_reference_value


# --- Boundary: false alarm tolerance at meaningful range limits ---------------------


@pytest.mark.parametrize(
    "boundary_target_arl",
    [_SMALLEST_MEANINGFUL_TARGET_ARL_AT_DEFAULT_REFERENCE_VALUE, MAX_MEANINGFUL_ARL],
    ids=["smallest_meaningful", "largest_meaningful"],
)
def test_fits_successfully_with_false_alarm_tolerance_at_the_meaningful_range_boundary(
    boundary_target_arl: float,
) -> None:
    """Boundary value analysis: the edges of the meaningful range are accepted.

    **Updated for BIN-117.** ``smallest_meaningful`` previously used
    ``MIN_MEANINGFUL_ARL`` (1.0) directly, fixed at the library default
    reference value. That combination is genuinely unattainable -- the
    two-sided minimum attainable ARL0 at ``DEFAULT_REFERENCE_VALUE`` is
    ~1.0431, so 1.0 sits inside the zone BIN-117's fix now (correctly)
    rejects. Using the actual per-``k`` minimum attainable value, with no
    margin, keeps this a pure boundary-value test of the *meaningful
    range*, decoupled from an attainability failure at this particular
    reference value -- exactly the same correction
    ``test_fits_successfully_with_reference_value_at_the_valid_range_boundary``
    already applies for the reference-value axis. No margin is needed
    here (unlike an earlier draft of this fix): ``_min_attainable_arl0``
    now reports a genuinely-attainable value, so sitting exactly on it is
    itself the boundary test, and a stronger one than a value some
    distance away. ``largest_meaningful`` is unaffected:
    ``MAX_MEANINGFUL_ARL`` remains comfortably attainable at the default
    reference value.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(baseline, target_arl=boundary_target_arl)

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert result.requested_arl == boundary_target_arl
    assert isinstance(result.achieved_arl, float)


# --- Property: a fitted artefact's decision interval is always positive -------------


@settings(max_examples=20, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_TARGET_ARL, max_value=MAX_MEANINGFUL_ARL, allow_nan=False
    ),
    reference_value=st.floats(
        min_value=MIN_REFERENCE_VALUE, max_value=MAX_REFERENCE_VALUE, allow_nan=False
    ),
)
def test_decision_interval_is_always_positive(
    target_arl: float, reference_value: float
) -> None:
    """For any valid, attainable inputs, the decision interval is positive.

    A negative or zero decision interval would be a chart that signals
    immediately or never meaningfully accumulates -- not a coherent CUSUM
    design for any positive target ARL0.

    **Updated for BIN-117.** An unattainable ``(reference_value,
    target_arl)`` combination (two-sided default direction) is BIN-117's
    own dedicated failure mode -- see the unattainable-target tests below
    -- not a case this property should generate at all. ``assume()`` skips
    (never fails) any Hypothesis-drawn pair the fix now correctly rejects,
    so this property is only ever evaluated against combinations
    ``fit_cusum`` is actually expected to succeed on.

    **Rebounded for ADR-011/BIN-131.** ``target_arl`` now draws from
    ``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]`` rather than
    ``[MIN_MEANINGFUL_ARL, MAX_MEANINGFUL_ARL]`` -- the old floor
    (``MIN_MEANINGFUL_ARL``, now ``MIN_COHERENT_ARL``, 1.0) is no longer a
    legal ``target_arl`` at all, independent of attainability.
    """
    # Arrange
    assume(target_arl > _min_attainable_arl0(reference_value, "two_sided"))
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(baseline, target_arl=target_arl, reference_value=reference_value)

    # Assert
    assert result.decision_interval > 0.0
