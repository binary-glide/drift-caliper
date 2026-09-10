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

Uses ``ScoringResultFactory``/``ProvenanceFactory`` (``tests/factories.py``)
for observations where the specific score does not matter, per that
module's own guidance.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from caliper.baseline import (
    DEFAULT_REFERENCE_VALUE,
    DEFAULT_SUFFICIENCY_THRESHOLD,
    MAX_MEANINGFUL_ARL,
    MAX_REFERENCE_VALUE,
    MIN_MEANINGFUL_ARL,
    MIN_REFERENCE_VALUE,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    fit_cusum,
)
from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)
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
    """Boundary value analysis: the edges of the valid range are accepted."""
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(
        baseline,
        target_arl=_SHAPE_TEST_TARGET_ARL,
        reference_value=boundary_reference_value,
    )

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert result.reference_value == boundary_reference_value


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
    result = fit_cusum(baseline, target_arl=boundary_target_arl)

    # Assert
    assert isinstance(result, FittedCUSUM)
    assert result.requested_arl == boundary_target_arl
    assert isinstance(result.achieved_arl, float)


# --- Property: a fitted artefact's decision interval is always positive -------------


@settings(max_examples=20, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_MEANINGFUL_ARL, max_value=MAX_MEANINGFUL_ARL, allow_nan=False
    ),
    reference_value=st.floats(
        min_value=MIN_REFERENCE_VALUE, max_value=MAX_REFERENCE_VALUE, allow_nan=False
    ),
)
def test_decision_interval_is_always_positive(
    target_arl: float, reference_value: float
) -> None:
    """For any valid inputs, the derived decision interval is a positive quantity.

    A negative or zero decision interval would be a chart that signals
    immediately or never meaningfully accumulates -- not a coherent CUSUM
    design for any positive target ARL0.
    """
    # Arrange
    baseline = _sufficient_baseline()

    # Act
    result = fit_cusum(baseline, target_arl=target_arl, reference_value=reference_value)

    # Assert
    assert result.decision_interval > 0.0
