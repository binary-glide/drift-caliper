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
import statistics

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedShewhart,
    fit_shewhart,
)

# MIN_*/MAX_* validation bounds are internal (BIN-110 P2) -- no longer
# re-exported from caliper.baseline, so tests that need the exact bound
# values import them from the owning submodule directly.
from caliper.baseline.domain.shewhart_fitting import (
    MAX_MEANINGFUL_ARL,
    MIN_MEANINGFUL_ARL,
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
    result = fit_shewhart(baseline, target_arl=boundary_target_arl)

    # Assert
    assert isinstance(result, FittedShewhart)
    assert result.requested_arl == boundary_target_arl
    assert isinstance(result.achieved_arl, float)


# --- Property: a fitted artefact's limits are always well-ordered -------------------


#
# ``exclude_min=True`` deliberately excludes ``MIN_MEANINGFUL_ARL`` (1.0)
# itself: unlike EWMA/CUSUM's numerical root-finders (which never reach
# their own floor exactly, by construction), Shewhart's closed-form
# calibration genuinely produces ``sigma_multiplier == 0.0`` at
# ``target_arl == 1.0`` (solving ``1 = 1 / (2 * Phi(-L))`` gives ``L = 0``
# exactly) -- a mathematically correct, degenerate design point where the
# limits collapse onto the centre line, not a bug. The feature file's own
# boundary scenario covers that exact point with a weaker, shape-only
# assertion (see the boundary test above and the BDD steps); this property
# test asserts strict ordering over the meaningful *interior* of the range.
@settings(max_examples=20, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_MEANINGFUL_ARL,
        max_value=MAX_MEANINGFUL_ARL,
        exclude_min=True,
        allow_nan=False,
    ),
)
def test_ucl_is_always_above_cl_which_is_always_above_lcl(target_arl: float) -> None:
    """Above the ARL0=1 degenerate point, all three limits are strictly ordered."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_shewhart(baseline, target_arl=target_arl)

    # Assert
    assert result.ucl > result.cl > result.lcl


# --- Property: the sigma multiplier is strictly positive above the ARL0=1 point -----


@settings(max_examples=20, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_MEANINGFUL_ARL,
        max_value=MAX_MEANINGFUL_ARL,
        exclude_min=True,
        allow_nan=False,
    ),
)
def test_sigma_multiplier_is_positive_above_the_arl0_equals_one_degenerate_point(
    target_arl: float,
) -> None:
    """A negative sigma multiplier would invert the limits.

    See the note above ``test_ucl_is_always_above_cl_which_is_always_above_lcl``
    for why ``target_arl == MIN_MEANINGFUL_ARL`` (exactly 1.0) is excluded:
    it is the one point where ``sigma_multiplier == 0.0`` is the
    mathematically correct answer, not a defect.
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
