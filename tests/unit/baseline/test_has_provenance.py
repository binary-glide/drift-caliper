"""Unit tests for ``HasProvenance`` (BIN-135, ADR-004 amendment 2026-09-12).

Pins the three items in the amendment's scope:

1. ``HasProvenance`` is a ``@runtime_checkable`` ``Protocol`` with exactly
   two string-typed property declarations (``provenance_model_version``,
   ``provenance_criteria``), exported from ``caliper`` and
   ``caliper.baseline``.
2. ``compare_provenance`` accepts any ``HasProvenance``-satisfying object --
   in particular, one that satisfies *only* ``HasProvenance`` and **not**
   ``FittedControlLimits``. This is a *widening* in principle, identical in
   practice, since the two provenance attributes are a subset of
   ``FittedControlLimits``.
3. ``Monitor`` **rejects** that same object -- the accept/reject asymmetry
   is the whole point of the split.

Additionally pins:

4. ``FittedControlLimits`` docstring contains the required disclaimer that
   it is not a plug-in interface for third-party charts.
5. Every existing ``FittedControlLimits`` conformer (``FittedEWMA``,
   ``FittedCUSUM``, ``FittedShewhart``) also satisfies ``HasProvenance`` --
   the subset relationship is structural, not just documented.

**Error assertions follow ADR-002/ADR-008:** type + ``context`` keys, never
message text. ``recovery_hint`` is human-facing and deliberately untested.

``HasProvenance`` does not exist yet anywhere in ``src/`` as of this ticket.
``uv run pytest`` is expected to fail at collection with ``ImportError``
until ``domain-implementer`` adds it -- that import failure is the correct
red state (TDD red phase).

``BIN-139`` proved that ``@runtime_checkable`` verifies attribute **names**
only, never types, never semantics. No test here implies ``isinstance(x,
HasProvenance)`` guarantees the attributes are ``str`` -- that guarantee
lives in ``compare_provenance``'s own validation (``BIN-127``/``BIN-139``),
not in the protocol check.
"""

from __future__ import annotations

import pytest

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    HasProvenance,
    compare_provenance,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.errors import InvalidParameterError, ProvenanceMismatchError
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from caliper.monitoring import Monitor
from tests.factories import ScoringResultFactory

# --- Constants ---------------------------------------------------------------

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."
_DIFFERENT_MODEL_VERSION = "claude-opus-4-5-20260101"
_SHAPE_TEST_TARGET_ARL = 370.0


# --- Helpers -----------------------------------------------------------------


class _HasProvenanceOnly:
    """Satisfies ``HasProvenance`` but NOT ``FittedControlLimits``.

    The minimal viable object -- two readable string attributes, nothing
    more. This is the *narrowest* conformer, and the one the ticket's
    accept/reject asymmetry test depends on: ``compare_provenance`` must
    accept it; ``Monitor`` must reject it.

    Not a ``@dataclass`` or Pydantic model, deliberately -- those would
    add structure beyond what the protocol requires. A plain class with
    two plain attributes is the least constrained way to satisfy a
    two-attribute protocol, proving that the protocol check really is
    sufficient for ``compare_provenance`` and really is insufficient for
    ``Monitor``.
    """

    def __init__(
        self, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
    ) -> None:
        self.provenance_model_version = model_version
        self.provenance_criteria = criteria


def _result(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
    score: float = 0.9,
    reasoning: str = "Accurate and concise.",
) -> ScoringResult:
    """Build a ``ScoringResult`` with an explicit, literal provenance."""
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


# === 1. Protocol existence and shape =========================================


def test_has_provenance_is_runtime_checkable() -> None:
    """``HasProvenance`` is ``@runtime_checkable`` so ``isinstance`` works.

    Without ``@runtime_checkable``, ``isinstance(obj, HasProvenance)`` at
    runtime raises ``TypeError`` -- the protocol would be usable only for
    static type checking. The amendment requires runtime checking because
    ``compare_provenance`` must accept any conformer, which means
    testing structural conformance at the call boundary.
    """
    # Arrange
    obj = _HasProvenanceOnly()

    # Act / Assert
    assert isinstance(obj, HasProvenance)


def test_has_provenance_requires_both_attributes() -> None:
    """The protocol specifies exactly two attributes, nothing more.

    An object lacking either does not satisfy it. An object with both
    does, regardless of whatever else it carries.
    """

    class _MissingModelVersion:
        provenance_criteria = _CRITERIA

    class _MissingCriteria:
        provenance_model_version = _MODEL_VERSION

    class _HasBoth:
        provenance_model_version = _MODEL_VERSION
        provenance_criteria = _CRITERIA

    # Assert: objects missing one attribute fail the isinstance check
    assert not isinstance(_MissingModelVersion(), HasProvenance)
    assert not isinstance(_MissingCriteria(), HasProvenance)

    # Assert: an object with both attributes passes
    assert isinstance(_HasBoth(), HasProvenance)


def test_has_provenance_is_a_typing_protocol() -> None:
    """``HasProvenance`` is a ``typing.Protocol``, not a concrete class.

    This pins the implementation mechanism the amendment requires --
    structural subtyping, not inheritance.
    """
    from typing import Protocol

    assert issubclass(HasProvenance, Protocol)  # type: ignore[arg-type]


# === 2. Subset relationship with FittedControlLimits =========================


def test_every_fitted_control_limits_conformer_also_satisfies_has_provenance() -> None:
    """``HasProvenance``'s attributes are a strict subset of ``FittedControlLimits``.

    Every existing concrete artefact (``FittedEWMA``, ``FittedCUSUM``,
    ``FittedShewhart``) must satisfy both protocols. This is the
    amendment's "identical in practice" claim: narrowing
    ``compare_provenance`` to ``HasProvenance`` changes no existing call
    site's behaviour.
    """
    # Arrange
    ewma = _fitted_ewma()
    cusum = _fitted_cusum()
    shewhart = _fitted_shewhart()

    # Assert: all three satisfy FittedControlLimits (precondition)
    assert isinstance(ewma, FittedControlLimits)
    assert isinstance(cusum, FittedControlLimits)
    assert isinstance(shewhart, FittedControlLimits)

    # Assert: all three also satisfy HasProvenance (the subset claim)
    assert isinstance(ewma, HasProvenance)
    assert isinstance(cusum, HasProvenance)
    assert isinstance(shewhart, HasProvenance)


def test_has_provenance_only_object_does_not_satisfy_fitted_control_limits() -> None:
    """A two-attribute object is NOT a ``FittedControlLimits``.

    This precondition test validates that ``_HasProvenanceOnly`` is the
    correct fixture for the asymmetry test -- if it accidentally satisfied
    ``FittedControlLimits`` too, the asymmetry would not be exercisable.
    """
    # Arrange
    obj = _HasProvenanceOnly()

    # Act / Assert
    assert isinstance(obj, HasProvenance)
    assert not isinstance(obj, FittedControlLimits)


# === 3. compare_provenance accepts HasProvenance ==============================


def test_compare_provenance_accepts_has_provenance_only_object() -> None:
    """A ``HasProvenance``-only object with matching provenance passes.

    This is the first half of the ticket's central asymmetry test.
    ``compare_provenance`` must accept this object -- it has readable
    provenance attributes and they match the scoring result's provenance.
    """
    # Arrange
    obj = _HasProvenanceOnly(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(model_version=_MODEL_VERSION, criteria=_CRITERIA)

    # Act
    outcome = compare_provenance(result, obj)  # type: ignore[func-returns-value]

    # Assert
    assert outcome is None


def test_compare_provenance_detects_mismatch_on_has_provenance_only_object() -> None:
    """A ``HasProvenance``-only object with differing provenance raises the same error.

    The error shape (``ProvenanceMismatchError`` with ``context["mismatches"]``)
    must be identical to what ``compare_provenance`` produces for a real
    fitted artefact -- the mismatch detection logic reads only the two
    ``HasProvenance`` attributes, so the result is indistinguishable.
    """
    # Arrange
    obj = _HasProvenanceOnly(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)

    # Act
    with pytest.raises(ProvenanceMismatchError) as exc_info:
        compare_provenance(result, obj)

    # Assert
    error = exc_info.value
    assert error.category == "provenance_mismatch"
    assert set(error.mismatches.keys()) == {"model_version"}
    assert error.mismatches["model_version"]["expected"] == _MODEL_VERSION
    assert error.mismatches["model_version"]["received"] == _DIFFERENT_MODEL_VERSION


# === 4. Monitor rejects HasProvenance-only objects ============================


def test_monitor_rejects_has_provenance_only_object() -> None:
    """A ``HasProvenance``-only object is rejected by ``Monitor.__init__``.

    This is the second half of the ticket's central asymmetry test.
    ``Monitor`` needs chart-specific detection logic that a two-attribute
    provenance object cannot supply. The rejection must be
    ``InvalidParameterError`` with the same shape ``BIN-120``'s concrete-
    type check already produces.
    """
    # Arrange
    obj = _HasProvenanceOnly()
    assert isinstance(obj, HasProvenance)
    assert not isinstance(obj, FittedControlLimits)

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        Monitor(obj)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "artefact"
    assert error.context["kind"] == "invalid"


# === 5. The asymmetry is genuinely two-way ====================================


def test_accept_reject_asymmetry_is_two_way() -> None:
    """One object: accepted by ``compare_provenance``, rejected by ``Monitor``.

    This single test pins the ticket's core claim end to end. Without it,
    the two halves above could pass with two *different* objects, and the
    split would be two names for one thing. Everything else is plumbing;
    this is the ticket.
    """
    # Arrange -- one object, used at both boundaries
    obj = _HasProvenanceOnly(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    result = _result(model_version=_MODEL_VERSION, criteria=_CRITERIA)

    # Preconditions: obj satisfies HasProvenance, not FittedControlLimits
    assert isinstance(obj, HasProvenance)
    assert not isinstance(obj, FittedControlLimits)

    # Act 1: compare_provenance ACCEPTS it
    outcome = compare_provenance(result, obj)  # type: ignore[func-returns-value]
    assert outcome is None

    # Act 2: Monitor REJECTS it
    with pytest.raises(InvalidParameterError) as exc_info:
        Monitor(obj)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "artefact"
    assert error.context["kind"] == "invalid"


# === 6. Existing compare_provenance behaviour unchanged =======================


def test_compare_provenance_still_accepts_fitted_ewma() -> None:
    """Narrowing the annotation to ``HasProvenance`` does not reject ``FittedEWMA``."""
    artefact = _fitted_ewma()
    result = _result()

    outcome = compare_provenance(result, artefact)  # type: ignore[func-returns-value]
    assert outcome is None


def test_compare_provenance_still_accepts_fitted_cusum() -> None:
    """Narrowing the annotation to ``HasProvenance`` does not reject ``FittedCUSUM``."""
    artefact = _fitted_cusum()
    result = _result()

    outcome = compare_provenance(result, artefact)  # type: ignore[func-returns-value]
    assert outcome is None


def test_compare_provenance_still_accepts_fitted_shewhart() -> None:
    """Narrowing to ``HasProvenance`` does not reject ``FittedShewhart``."""
    artefact = _fitted_shewhart()
    result = _result()

    outcome = compare_provenance(result, artefact)  # type: ignore[func-returns-value]
    assert outcome is None


# === 7. FittedControlLimits docstring disclaimer ==============================


def test_fitted_control_limits_docstring_disclaims_plug_in_interface() -> None:
    """``FittedControlLimits``' docstring must state it is **not** a plug-in interface.

    ADR-004's amendment requires this in as many words -- *"Its docstring
    must say so"* -- because the false half of
    ``isinstance(x, FittedControlLimits)`` (that it implies "can be
    monitored") is what produced BIN-120, and a reader reaches the
    docstring before they reach the ADR.

    ⚠️ **This asserts on prose, and the first draft was near-tautological.**
    It checked ``"not" in docstring`` *and* ``"plug-in" in docstring`` --
    but ``"not"`` appears in almost any prose, so in practice it only
    required the topic to be *mentioned*. **A docstring claiming this IS a
    plug-in interface would have passed it**, which inverts the very
    requirement.

    The contiguous phrase is checked instead. ⚠️ **That is deliberately
    brittle to rewording**, and the trade is accepted: a reword breaks the
    test loudly and someone reinstates the claim, whereas a check that
    cannot tell "is" from "is not" fails silently and forever. ADR-008
    forbids this shape for *error messages* precisely because wording
    drifts; here the wording **is** the deliverable, so pinning it is the
    point rather than a workaround.
    """
    docstring = FittedControlLimits.__doc__
    assert docstring is not None, "FittedControlLimits must have a docstring"

    normalised = " ".join(docstring.lower().split())
    assert (
        "not a plug-in interface" in normalised
        or "not a plugin interface" in normalised
    ), (
        "FittedControlLimits' docstring must state, as a contiguous claim, "
        "that it is NOT a plug-in interface for third-party charts "
        "(ADR-004 amendment 2026-09-12). Mentioning the topic is not "
        "enough -- the negation is the whole requirement."
    )
