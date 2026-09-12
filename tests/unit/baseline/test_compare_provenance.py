"""Unit tests for ``compare_provenance()`` (BIN-68).

Pins the six acceptance scenarios in
``tests/bdd/features/baseline/provenance-mismatch-between-phases.feature``
at the unit level. Error assertions follow ADR-002/ADR-008, as amended
2026-09-10: type + the required ``context["mismatches"]`` key only -- never
message text. ``mismatches`` is a ``dict[str, dict[str, str]]`` keyed by
provenance dimension name, each holding ``{"expected": ..., "received": ...}``
-- see the ADR-002 amendment ("provenance_mismatch context becomes a
mismatches mapping") and ``docs/domain-model.md`` OQ-11.

``compare_provenance()`` does not exist yet anywhere in ``src/`` as of this
ticket -- per the ADR-002 amendment's migration note 5 ("BIN-68 itself
needs no migration ... it is written directly against mismatches"), this
file is written directly against the new shape with nothing to migrate
from. ``uv run pytest`` is expected to fail at collection with
``ImportError`` until ``domain-implementer`` adds
``src/caliper/baseline/domain/compare_provenance.py`` and exports it from
``caliper.baseline`` -- that import failure is the correct red state for
this ticket (TDD red phase), not a mistake to fix here.

**API shape this file commits to, flagged because no ADR settles it.**
ADR-002's amendment settles the error *shape* (``mismatches``); nothing
settles ``compare_provenance()``'s own signature, return value, or module
location -- no architecture pass has run for BIN-68 beyond that amendment.
Four choices below are this file's own, made to keep the ADR-002 amendment
testable, not decisions any ADR dictates:

1. **Location and name**: ``compare_provenance(result, artefact)``,
   importable from ``caliper.baseline`` -- the same package
   ``Baseline``/``fit_ewma``/``fit_cusum``/``fit_shewhart`` are promoted
   to, since this is baseline-context machinery (Phase I baseline vs. a
   Phase II observation) in exactly the same sense. Not promoted to the
   ``caliper`` top-level package here -- that promotion (BIN-110's DX
   pass) is a separate, deliberate decision this ticket does not make on
   its behalf.
2. **Parameters**: ``result: ScoringResult`` (the Phase II observation,
   BIN-59) first, ``artefact: FittedControlLimits`` (any chart type's
   fitted artefact, BIN-65/94/95 -- the shared protocol, not a concrete
   class, per BR-6 "without chart-type-specific branching") second --
   matching the Gherkin's own subject/referent order ("compare the
   scoring result's provenance against the fitted artefact's").
3. **Return value on success: ``None``.** Mirrors ``Baseline.record()``'s
   precedent exactly: a validation-gate operation that raises on failure
   and returns nothing meaningful on success. The one place this file
   invents a detail with no textual precedent in an ADR -- flagged because
   it is genuinely a guess, though a low-risk, non-breaking one (a caller
   that ignores ``None`` is unaffected if a richer return type is added
   later).
4. **No ``acknowledge=``/``force=`` parameter**
   (``docs/domain-model.md`` OQ-9, ratified 2026-09-10 -- "no override.
   The engineer refits."; CLAUDE.md "Provenance mismatch raises" ->
   "No acknowledgement path"). Pinned by
   ``test_takes_no_acknowledge_or_force_override_parameter`` below so a
   future addition fails a test rather than silently reopening a settled
   product decision.

Uses ``ScoringResultFactory`` (``tests/factories.py``) for baseline filler
observations where the specific score does not matter, and literal
``ScoringResult``/``Provenance`` construction for the provenance-mismatch
cases under test, per that module's own guidance (boundary-value tests
construct the value under test directly). Fitted artefacts are obtained by
calling ``fit_ewma``/``fit_cusum``/``fit_shewhart`` -- never constructed
directly -- mirroring the convention ``FittedEWMA``'s own docstring
establishes and ``test_ewma_fitting.py`` follows.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    compare_provenance,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.errors import CaliperError, InvalidParameterError, ProvenanceMismatchError
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from tests.factories import ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."
_DIFFERENT_MODEL_VERSION = "claude-opus-4-5-20260101"
_DIFFERENT_CRITERIA = "Evaluate the response for tone and empathy."

# Arbitrary, sufficiently-large target ARL0 shared across every fitted
# artefact built below -- its value carries no statistical meaning here,
# matching test_ewma_fitting.py / test_cusum_fitting.py /
# test_shewhart_fitting.py's own `_SHAPE_TEST_TARGET_ARL`.
_SHAPE_TEST_TARGET_ARL = 370.0


def _result(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
    score: float = 0.9,
    reasoning: str = "Accurate and concise.",
) -> ScoringResult:
    """Build a ``ScoringResult`` with an explicit, literal provenance.

    Kept separate from ``ScoringResultFactory`` so the provenance-mismatch
    tests can pin the exact model version / criteria strings under test at
    the call site, per ``tests/factories.py``'s own guidance -- mirrors
    ``test_baseline.py``'s ``_result()`` helper exactly.
    """
    return ScoringResult(
        score=score,
        reasoning=reasoning,
        provenance=Provenance(
            model_version=ModelVersion(value=model_version),
            scoring_criteria=ScoringCriteria(value=criteria),
        ),
    )


def _baseline_with_provenance(
    *, model_version: str, criteria: str, count: int
) -> Baseline:
    """Build a ``Baseline`` of ``count`` observations sharing one literal provenance."""
    baseline = Baseline()
    provenance = Provenance(
        model_version=ModelVersion(value=model_version),
        scoring_criteria=ScoringCriteria(value=criteria),
    )
    for _ in range(count):
        baseline.record(ScoringResultFactory(provenance=provenance))
    return baseline


def _fitted_ewma(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedEWMA:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _fitted_cusum(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedCUSUM:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _fitted_shewhart(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedShewhart:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _capture_comparison_error(
    result: ScoringResult, artefact: FittedControlLimits
) -> CaliperError:
    """Call ``compare_provenance()`` expecting it to raise, and return the

    raised error.
    """
    try:
        compare_provenance(result, artefact)
    except CaliperError as exc:
        return exc
    raise AssertionError("expected compare_provenance() to raise a CaliperError")


# --- SC1: happy path -- provenance matches ------------------------------------


def test_confirms_compatible_when_provenance_matches_the_fitted_artefact() -> None:
    """SC1: identical provenance on both sides -- no exception; returns ``None``."""
    # Arrange
    artefact = _fitted_ewma()
    result = _result()

    # Act
    outcome = compare_provenance(result, artefact)  # type: ignore[func-returns-value]

    # Assert
    assert outcome is None


# --- SC2: provenance mismatch -- model version differs ------------------------


def test_raises_provenance_mismatch_error_when_model_version_differs() -> None:
    """SC2: a differing judge model version is reported as an expected/received pair."""
    # Arrange
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)

    # Act
    error = _capture_comparison_error(result, artefact)

    # Assert
    assert isinstance(error, ProvenanceMismatchError)
    assert error.category == "provenance_mismatch"
    assert set(error.mismatches.keys()) == {"model_version"}
    assert error.mismatches["model_version"] == {
        "expected": _MODEL_VERSION,
        "received": _DIFFERENT_MODEL_VERSION,
    }


# --- SC3: provenance mismatch -- criteria differs ------------------------------


def test_raises_provenance_mismatch_error_when_criteria_differs() -> None:
    """SC3: differing scoring criteria is reported as an expected/received pair."""
    # Arrange
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(model_version=_MODEL_VERSION, criteria=_DIFFERENT_CRITERIA)

    # Act
    error = _capture_comparison_error(result, artefact)

    # Assert
    assert isinstance(error, ProvenanceMismatchError)
    assert error.category == "provenance_mismatch"
    assert set(error.mismatches.keys()) == {"scoring_criteria"}
    assert error.mismatches["scoring_criteria"] == {
        "expected": _CRITERIA,
        "received": _DIFFERENT_CRITERIA,
    }


def test_raises_mismatch_when_criteria_differs_only_by_whitespace() -> None:
    """Exact equality, inherited from BIN-63 OQ-2/OQ-6 (ratified 2026-09-10):

    surrounding whitespace alone makes criteria differ -- no normalisation
    on either side of the Phase I/II boundary.
    """
    # Arrange
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria="Be helpful.")
    result = _result(model_version=_MODEL_VERSION, criteria="  Be helpful.  ")

    # Act
    error = _capture_comparison_error(result, artefact)

    # Assert
    assert isinstance(error, ProvenanceMismatchError)
    assert set(error.mismatches.keys()) == {"scoring_criteria"}


# --- SC4: dual mismatch --------------------------------------------------------


def test_reports_both_dimensions_when_both_differ() -> None:
    """SC4/BR-4: a dual mismatch reports both dimensions in one raise.

    Not just the first one checked -- see the ADR-002 amendment's "no
    first-checked-wins short-circuit".
    """
    # Arrange
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(
        model_version=_DIFFERENT_MODEL_VERSION, criteria=_DIFFERENT_CRITERIA
    )

    # Act
    error = _capture_comparison_error(result, artefact)

    # Assert
    assert isinstance(error, ProvenanceMismatchError)
    assert set(error.mismatches.keys()) == {"model_version", "scoring_criteria"}
    assert error.mismatches["model_version"] == {
        "expected": _MODEL_VERSION,
        "received": _DIFFERENT_MODEL_VERSION,
    }
    assert error.mismatches["scoring_criteria"] == {
        "expected": _CRITERIA,
        "received": _DIFFERENT_CRITERIA,
    }
    # `mismatches` is sugar over `context["mismatches"]`, not a second
    # source of truth (ADR-002 amendment).
    assert error.context["mismatches"] == error.mismatches


# --- SC5: chart-type independence ----------------------------------------------

_FITTED_ARTEFACT_BUILDERS: list[Callable[..., FittedControlLimits]] = [
    _fitted_ewma,
    _fitted_cusum,
    _fitted_shewhart,
]


@pytest.mark.parametrize(
    "build_artefact",
    _FITTED_ARTEFACT_BUILDERS,
    ids=["ewma", "cusum", "shewhart"],
)
def test_produces_the_same_error_shape_regardless_of_chart_type(
    build_artefact: Callable[..., FittedControlLimits],
) -> None:
    """SC5/BR-6: comparison works uniformly against any fitted artefact type.

    Every chart type's fitted artefact carries baseline provenance in the
    same two flat fields (``FittedControlLimits.provenance_model_version``/
    ``provenance_criteria``), so the same assertion body -- applied
    identically to all three chart types via parametrize -- is itself the
    "same shape" proof: no chart-type-specific branching is exercised.
    """
    # Arrange
    artefact = build_artefact(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)

    # Act
    error = _capture_comparison_error(result, artefact)

    # Assert
    assert isinstance(error, ProvenanceMismatchError)
    assert error.category == "provenance_mismatch"
    assert set(error.context.keys()) == {"mismatches"}
    assert set(error.mismatches.keys()) == {"model_version"}
    assert error.mismatches["model_version"] == {
        "expected": _MODEL_VERSION,
        "received": _DIFFERENT_MODEL_VERSION,
    }


# --- SC6: category consistency with a Phase I intra-baseline mismatch ---------


def test_phase_ii_mismatch_shares_category_with_phase_i_mismatch() -> None:
    """SC6: the same violation, same category, same required context fields,

    at both the Phase I intra-baseline boundary (BIN-63) and the Phase
    I/II boundary (BIN-68) -- this is the ratified decision the scenario
    exists to pin, not a coincidental similarity.
    """
    # Arrange / Act -- Phase I: intra-baseline mismatch via Baseline.record()
    phase_i_baseline = Baseline()
    phase_i_baseline.record(_result(model_version=_MODEL_VERSION, criteria=_CRITERIA))
    try:
        phase_i_baseline.record(
            _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)
        )
    except ProvenanceMismatchError as exc:
        phase_i_error: ProvenanceMismatchError = exc
    else:
        raise AssertionError(
            "expected Baseline.record() to raise a ProvenanceMismatchError"
        )

    # Arrange / Act -- Phase II: cross-boundary mismatch via compare_provenance()
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    phase_ii_error = _capture_comparison_error(
        _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA), artefact
    )

    # Assert
    assert phase_i_error.category == phase_ii_error.category == "provenance_mismatch"
    assert (
        set(phase_i_error.context.keys())
        == set(phase_ii_error.context.keys())
        == {"mismatches"}
    )


# --- No override path (domain-model.md OQ-9, ratified 2026-09-10) -------------


def test_takes_no_acknowledge_or_force_override_parameter() -> None:
    """There is no escape hatch: ``compare_provenance()`` accepts no

    ``acknowledge=``/``force=`` (or equivalent) parameter. An engineer who
    knowingly changed the judge must refit -- see
    ``docs/domain-model.md`` "Provenance change requires a refit" and
    CLAUDE.md "No acknowledgement path -- the engineer refits". Pinned here
    so a future addition of such a parameter fails this test rather than
    silently reopening a settled product decision.
    """
    # Arrange
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)

    # Act / Assert
    with pytest.raises(TypeError):
        compare_provenance(  # type: ignore[call-arg]
            result,
            artefact,
            acknowledge=True,  # ty: ignore[unknown-argument]
        )

    with pytest.raises(TypeError):
        compare_provenance(  # type: ignore[call-arg]
            result,
            artefact,
            force=True,  # ty: ignore[unknown-argument]
        )


# --- BIN-127: artefact provenance attribute raises on access -----------------


class _RaisingModelVersionArtefact:
    """A ``FittedControlLimits``-shaped object whose model-version property raises.

    ``provenance_criteria`` is genuinely present; only
    ``provenance_model_version`` misbehaves on access -- so the raised/absent
    distinction in ``context`` can be pinned precisely.
    """

    provenance_criteria = _CRITERIA

    @property
    def provenance_model_version(self) -> str:
        raise RuntimeError("boom-on-provenance-access")


class _AbsentCriteriaArtefact:
    """A ``FittedControlLimits``-shaped object entirely lacking ``provenance_criteria``.

    ``provenance_model_version`` is genuinely present -- only
    ``provenance_criteria`` is absent, the ``hasattr``-safe case, so this
    is distinguishable from ``_RaisingModelVersionArtefact`` above.
    """

    provenance_model_version = _MODEL_VERSION


class _MixedProvenanceArtefact:
    """``provenance_model_version`` raises; ``provenance_criteria`` is absent.

    Both failure modes on the same object, so a single raise must report
    both distinctly rather than only the first one probed -- mirrors the
    mixed fixtures ``test_baseline.py``/``test_monitor.py`` use for the
    other two BIN-127 entry points.
    """

    @property
    def provenance_model_version(self) -> str:
        raise RuntimeError("boom-on-provenance-access")


def test_raises_invalid_parameter_error_when_artefact_provenance_raises() -> None:
    """BIN-127: an artefact whose provenance attribute raises is rejected as an

    invalid parameter, not treated as a provenance mismatch -- there is no
    actual "received" value to report when the read itself failed. The raw
    ``RuntimeError`` must never escape.
    """
    # Arrange
    result = _result()
    artefact = _RaisingModelVersionArtefact()

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        compare_provenance(result, artefact)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "artefact"
    assert error.context["kind"] == "invalid"
    # Raised, not merely absent -- and reported as such, distinctly.
    assert error.context["unreadable_fields"] == {
        "provenance_model_version": "RuntimeError"
    }
    assert error.context["missing_fields"] == []


def test_raises_invalid_parameter_error_when_artefact_provenance_absent() -> None:
    """BIN-127: an artefact genuinely lacking a required provenance attribute

    is rejected the same way, but reported as absent rather than raised --
    the two are not flattened into one undifferentiated failure.
    """
    # Arrange
    result = _result()
    artefact = _AbsentCriteriaArtefact()

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        compare_provenance(result, artefact)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["missing_fields"] == ["provenance_criteria"]
    assert error.context["unreadable_fields"] == {}


def test_raises_invalid_parameter_error_for_mixed_absent_and_raised() -> None:
    """BIN-127: one attribute raises, the other is absent, on the same artefact.

    Each probe is classified independently, so a mixed failure reports
    both distinctly in the same raise rather than only the first one
    checked.
    """
    # Arrange
    result = _result()
    artefact = _MixedProvenanceArtefact()

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        compare_provenance(result, artefact)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["missing_fields"] == ["provenance_criteria"]
    assert error.context["unreadable_fields"] == {
        "provenance_model_version": "RuntimeError"
    }
