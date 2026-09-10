"""Unit tests for ``Baseline`` (BIN-63).

Pins the ten acceptance scenarios in
``tests/bdd/features/baseline/phase-i-baseline-collection.feature`` at the
unit level, plus a handful of boundary cases the feature file's business
rules require but do not name as separate scenarios (non-sorting of
observations; exact -- not normalised -- criteria comparison, settling the
domain model's OQ-2/OQ-6; a positive same-provenance-accepted partition).
Error assertions follow ADR-002/ADR-008: type + required ``context`` keys
only -- never message text.

``ProvenanceMismatchError.context["dimension"]``/``["expected"]``/
``["received"]`` -- previously asserted as a non-empty, unpinned string
below, because ADR-002 specified the required *key* but never enumerated
its values -- is **superseded** by ``context["mismatches"]`` (ADR-002
Amendment, 2026-09-10, ratified under BIN-68): a
``dict[str, dict[str, str]]`` keyed by dimension name (``"model_version"``,
``"scoring_criteria"``), each holding ``{"expected": ..., "received":
...}``, sugared by a read-only ``.mismatches`` property. Dimension *keys*
are pinned here (``"model_version"``, ``"scoring_criteria"``) because they
are no longer an unpinned token to guess at -- they are the exact key names
the amendment specifies, tracking ``Provenance``'s own field names (see
``docs/domain-model.md`` OQ-11). This is loosening a prior deliberate
under-specification, not weakening an assertion: the ADR-002 amendment is
what makes a precise key pinnable at all.
``test_provenance_mismatch_dimension_distinguishes_model_version_from_criteria``
is rewritten below to what the amendment's own migration note prescribes --
a direct membership test (``"model_version" in error.mismatches`` vs.
``"scoring_criteria" in error.mismatches``) rather than comparing two
unpinned tokens for inequality.

``_reject_if_provenance_differs`` no longer short-circuits on the first
differing dimension (BIN-63's original behaviour) -- it checks **both**
dimensions and raises once, reporting every dimension that differs. This is
a behaviour change, not only a shape change (ADR-002 Amendment, "Migration
cost" item 2), so
``test_raises_provenance_mismatch_error_reporting_both_dimensions_when_both_differ``
below exercises it directly at the Phase I boundary, not only through
BIN-68's Phase II ``compare_provenance()`` path.

``Baseline.record()`` is a scaffold that raises ``NotImplementedError``
(see ``src/caliper/baseline/domain/baseline.py``) -- every test below that
calls it is expected to fail for that reason until ``domain-implementer``
replaces the scaffold. ``uv run pytest`` therefore fails: that is the
correct state for this ticket (TDD red phase).

Uses ``ScoringResultFactory``/``ProvenanceFactory`` (``tests/factories.py``)
for happy-path setup where the specific provenance value does not matter
(SC1, SC2, SC8), and literal, reader-visible ``Provenance``/``ScoringResult``
construction for the provenance-mismatch and boundary cases (SC5, SC6, and
the exact-equality tests), per ``tests/factories.py``'s own module
docstring: boundary-value tests must construct the value under test
directly, not through a factory default.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from caliper.baseline import Baseline
from caliper.errors import (
    CaliperError,
    InvalidObservationError,
    ProvenanceMismatchError,
)
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from tests.factories import ProvenanceFactory, ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."


def _result(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
    score: float = 0.9,
    reasoning: str = "Accurate and concise.",
) -> ScoringResult:
    """Build a ``ScoringResult`` with an explicit, literal provenance.

    Kept separate from ``ScoringResultFactory`` so the provenance-mismatch
    tests (SC5, SC6) can pin the exact model version / criteria strings
    under test at the call site, per ``tests/factories.py``'s own guidance.
    """
    return ScoringResult(
        score=score,
        reasoning=reasoning,
        provenance=Provenance(
            model_version=ModelVersion(value=model_version),
            scoring_criteria=ScoringCriteria(value=criteria),
        ),
    )


def _record_and_capture_error(baseline: Baseline, observation: object) -> CaliperError:
    """Record ``observation`` into ``baseline``, returning the raised error.

    Used only where a test needs the error object itself for comparison
    (SC10) rather than asserting on it inline with ``pytest.raises``.
    """
    try:
        baseline.record(observation)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    except CaliperError as exc:
        return exc
    raise AssertionError("expected baseline.record() to raise a CaliperError")


@dataclass(frozen=True)
class _PartialObservation:
    """Has some of ``ScoringResult``'s fields but not all -- not a ``ScoringResult``.

    Used for SC7: recording something that is not a complete scoring
    result. Missing ``provenance`` entirely, regardless of whether
    ``domain-implementer`` detects missing fields by ``isinstance`` alone
    or by inspecting individual attributes.
    """

    score: float
    reasoning: str


# --- SC1: happy path -- record and inspect -----------------------------------


def test_records_scoring_result_and_reports_total_observation_count() -> None:
    """SC1: a recorded observation is present, and the count reflects it."""
    # Arrange
    baseline = Baseline()
    result = ScoringResultFactory()

    # Act
    baseline.record(result)

    # Assert
    assert result in baseline.observations
    assert baseline.observation_count == 1


# --- SC2: insertion order is preserved ---------------------------------------


def test_preserves_the_order_in_which_observations_were_recorded() -> None:
    """SC2: observations appear in recording order, not sorted or reversed."""
    # Arrange
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    results = [
        ScoringResultFactory(provenance=shared_provenance, score=score)
        for score in (0.9, 0.1, 0.5, 0.3)
    ]

    # Act
    for result in results:
        baseline.record(result)

    # Assert
    assert list(baseline.observations) == results


def test_does_not_sort_observations_by_score() -> None:
    """BR-2: order is arithmetic, not presentational -- no implicit sort."""
    # Arrange
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    descending = [
        ScoringResultFactory(provenance=shared_provenance, score=score)
        for score in (0.9, 0.5, 0.1)
    ]

    # Act
    for result in descending:
        baseline.record(result)

    # Assert -- exact insertion order, not ascending or any other reordering
    assert [obs.score for obs in baseline.observations] == [0.9, 0.5, 0.1]


# --- SC3: full provenance retained -------------------------------------------


def test_observation_retains_provenance_matching_original_result_exactly() -> None:
    """SC3: the recorded observation's provenance matches the original exactly."""
    # Arrange
    baseline = Baseline()
    result = ScoringResultFactory()

    # Act
    baseline.record(result)

    # Assert
    observed = baseline.observations[0]
    assert observed.provenance.model_version == result.provenance.model_version
    assert observed.provenance.scoring_criteria == result.provenance.scoring_criteria
    assert observed.provenance == result.provenance


# --- SC4: score and reasoning retained ---------------------------------------


def test_observation_retains_score_and_reasoning_from_original_result() -> None:
    """SC4: the recorded observation's score and reasoning match the original."""
    # Arrange
    baseline = Baseline()
    result = _result(score=0.73, reasoning="Specific, distinguishable reasoning text.")

    # Act
    baseline.record(result)

    # Assert
    observed = baseline.observations[0]
    assert observed.score == 0.73
    assert observed.reasoning == "Specific, distinguishable reasoning text."


# --- SC5: provenance mismatch -- model version differs -----------------------


def test_raises_provenance_mismatch_error_when_model_version_differs() -> None:
    """SC5: a differing judge model version is rejected; the baseline is unchanged.

    ``context["mismatches"]`` reports exactly one entry, keyed
    ``"model_version"`` (ADR-002 Amendment, 2026-09-10) -- the baseline's
    provenance is the expected value, the rejected observation's is the
    received value.
    """
    # Arrange
    baseline = Baseline()
    baseline.record(_result(model_version="claude-sonnet-a", criteria=_CRITERIA))
    observations_before = baseline.observations

    # Act
    with pytest.raises(ProvenanceMismatchError) as exc_info:
        baseline.record(_result(model_version="claude-sonnet-b", criteria=_CRITERIA))

    # Assert
    error = exc_info.value
    assert error.category == "provenance_mismatch"
    assert set(error.mismatches.keys()) == {"model_version"}
    assert error.mismatches["model_version"] == {
        "expected": "claude-sonnet-a",
        "received": "claude-sonnet-b",
    }
    assert baseline.observation_count == 1
    assert baseline.observations == observations_before


# --- SC6: provenance mismatch -- criteria differs ----------------------------


def test_raises_provenance_mismatch_error_when_criteria_differs() -> None:
    """SC6: differing scoring criteria is rejected; the baseline is unchanged.

    ``context["mismatches"]`` reports exactly one entry, keyed
    ``"scoring_criteria"`` (ADR-002 Amendment, 2026-09-10).
    """
    # Arrange
    baseline = Baseline()
    baseline.record(
        _result(model_version=_MODEL_VERSION, criteria="Evaluate for tone.")
    )
    observations_before = baseline.observations

    # Act
    with pytest.raises(ProvenanceMismatchError) as exc_info:
        baseline.record(
            _result(model_version=_MODEL_VERSION, criteria="Evaluate for accuracy.")
        )

    # Assert
    error = exc_info.value
    assert error.category == "provenance_mismatch"
    assert set(error.mismatches.keys()) == {"scoring_criteria"}
    assert error.mismatches["scoring_criteria"] == {
        "expected": "Evaluate for tone.",
        "received": "Evaluate for accuracy.",
    }
    assert baseline.observation_count == 1
    assert baseline.observations == observations_before


def test_provenance_mismatch_dimension_distinguishes_model_version_from_criteria() -> (
    None
):
    """A model-version mismatch and a criteria mismatch report different

    ``mismatches`` keys -- proving the two failure modes are actually told
    apart. Under the ``mismatches`` shape (ADR-002 Amendment, 2026-09-10)
    this is a direct membership test, not a comparison of two previously
    unpinned tokens for inequality.
    """
    # Arrange
    model_version_mismatch_baseline = Baseline()
    model_version_mismatch_baseline.record(_result(model_version="claude-sonnet-a"))
    criteria_mismatch_baseline = Baseline()
    criteria_mismatch_baseline.record(_result(criteria="Evaluate for tone."))

    # Act
    model_version_error = _record_and_capture_error(
        model_version_mismatch_baseline, _result(model_version="claude-sonnet-b")
    )
    criteria_error = _record_and_capture_error(
        criteria_mismatch_baseline, _result(criteria="Evaluate for accuracy.")
    )

    # Assert
    assert isinstance(model_version_error, ProvenanceMismatchError)
    assert isinstance(criteria_error, ProvenanceMismatchError)
    assert "model_version" in model_version_error.mismatches
    assert "scoring_criteria" not in model_version_error.mismatches
    assert "scoring_criteria" in criteria_error.mismatches
    assert "model_version" not in criteria_error.mismatches


def test_baseline_reports_both_dimensions_when_both_differ() -> None:
    """``_reject_if_provenance_differs`` checks both dimensions before raising

    (ADR-002 Amendment, "Migration cost" item 2) -- a dual mismatch is
    reported in **one** raise covering both dimensions, not the first one
    checked. This is a behaviour change at the Phase I boundary, not only
    at BIN-68's Phase II ``compare_provenance()`` boundary -- see the
    merged BIN-68 scenario "Phase II provenance mismatch is classifiable
    as the same category as a Phase I baseline recording mismatch," which
    requires structural parity between the two boundaries.
    """
    # Arrange
    baseline = Baseline()
    baseline.record(
        _result(model_version="claude-sonnet-a", criteria="Evaluate for tone.")
    )
    observations_before = baseline.observations

    # Act
    with pytest.raises(ProvenanceMismatchError) as exc_info:
        baseline.record(
            _result(model_version="claude-sonnet-b", criteria="Evaluate for accuracy.")
        )

    # Assert
    error = exc_info.value
    assert error.category == "provenance_mismatch"
    assert set(error.mismatches.keys()) == {"model_version", "scoring_criteria"}
    assert error.mismatches["model_version"] == {
        "expected": "claude-sonnet-a",
        "received": "claude-sonnet-b",
    }
    assert error.mismatches["scoring_criteria"] == {
        "expected": "Evaluate for tone.",
        "received": "Evaluate for accuracy.",
    }
    assert error.context["mismatches"] == error.mismatches
    assert baseline.observation_count == 1
    assert baseline.observations == observations_before


# --- Criteria equality is exact (settled OQ-2/OQ-6, 2026-09-10) --------------
#
# No comparison code should exist to test -- Provenance equality is
# Pydantic's field-wise equality over ModelVersion/ScoringCriteria, which is
# exact string comparison. These tests pin the *behaviour* (any difference
# rejected, including whitespace or case alone) so nothing "helpfully"
# reintroduces normalisation later.


def test_raises_mismatch_when_criteria_differs_only_by_whitespace() -> None:
    """Exact equality: surrounding whitespace alone makes criteria differ."""
    # Arrange
    baseline = Baseline()
    baseline.record(_result(model_version=_MODEL_VERSION, criteria="Be helpful."))
    observations_before = baseline.observations

    # Act
    with pytest.raises(ProvenanceMismatchError) as exc_info:
        baseline.record(
            _result(model_version=_MODEL_VERSION, criteria="  Be helpful.  ")
        )

    # Assert
    assert exc_info.value.category == "provenance_mismatch"
    assert baseline.observation_count == 1
    assert baseline.observations == observations_before


def test_raises_mismatch_when_criteria_differs_only_by_case() -> None:
    """Exact equality: case alone makes criteria differ -- no case folding."""
    # Arrange
    baseline = Baseline()
    baseline.record(_result(model_version=_MODEL_VERSION, criteria="Be Helpful."))
    observations_before = baseline.observations

    # Act
    with pytest.raises(ProvenanceMismatchError) as exc_info:
        baseline.record(_result(model_version=_MODEL_VERSION, criteria="be helpful."))

    # Assert
    assert exc_info.value.category == "provenance_mismatch"
    assert baseline.observation_count == 1
    assert baseline.observations == observations_before


def test_accepts_second_observation_with_identical_provenance() -> None:
    """Positive partition: identical provenance (byte-for-byte) is accepted.

    Checks the full observation sequence, not just the count -- a count-only
    assertion would not catch a mutant that accepted the second observation
    but silently dropped or overwrote the first.
    """
    # Arrange
    baseline = Baseline()
    first = _result(model_version=_MODEL_VERSION, criteria=_CRITERIA, score=0.9)
    second = _result(model_version=_MODEL_VERSION, criteria=_CRITERIA, score=0.4)
    baseline.record(first)

    # Act
    baseline.record(second)

    # Assert
    assert baseline.observation_count == 2
    assert list(baseline.observations) == [first, second]


# --- SC7: recording an incomplete scoring result -----------------------------


def test_raises_invalid_observation_error_when_recording_none() -> None:
    """SC7: recording ``None`` fails as an invalid observation; baseline unchanged."""
    # Arrange
    baseline = Baseline()

    # Act
    with pytest.raises(InvalidObservationError) as exc_info:
        baseline.record(None)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_observation"
    assert isinstance(error.context["reason"], str)
    assert error.context["reason"] != ""
    assert set(error.context["missing_fields"]) == {"score", "reasoning", "provenance"}
    assert baseline.observation_count == 0
    assert baseline.observations == ()


def test_raises_invalid_observation_error_when_input_is_missing_provenance() -> None:
    """SC7: an object with only some fields is rejected; baseline unchanged."""
    # Arrange
    baseline = Baseline()
    partial = _PartialObservation(score=0.5, reasoning="looks plausible")

    # Act
    with pytest.raises(InvalidObservationError) as exc_info:
        baseline.record(partial)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_observation"
    assert isinstance(error.context["reason"], str)
    assert error.context["reason"] != ""
    # Exact set, not membership. Membership let two mutants survive: passing
    # `None` into the field check reports every field as missing, and
    # `"provenance" in [...]` still holds. Found by mutmut during BIN-63 review.
    assert set(error.context["missing_fields"]) == {"provenance"}
    assert baseline.observation_count == 0
    assert baseline.observations == ()


# --- SC8: first observation establishes the provenance signature ------------


def test_first_recorded_observation_establishes_provenance_signature() -> None:
    """SC8: an empty baseline's first observation sets its expected provenance."""
    # Arrange
    baseline = Baseline()
    assert baseline.observation_count == 0
    assert baseline.provenance_signature is None
    result = ScoringResultFactory()

    # Act
    baseline.record(result)

    # Assert
    assert baseline.observation_count == 1
    assert baseline.provenance_signature == result.provenance


# --- SC9: observation immutability -------------------------------------------


def test_rejects_attempt_to_modify_score_of_recorded_observation() -> None:
    """SC9: reassigning `score` on a recorded observation is rejected."""
    # Arrange
    baseline = Baseline()
    result = ScoringResultFactory()
    baseline.record(result)
    observed = baseline.observations[0]
    original_score = observed.score

    # Act
    with pytest.raises(ValidationError):
        observed.score = 0.01  # ty: ignore[invalid-assignment]

    # Assert
    assert baseline.observations[0].score == original_score


def test_rejects_attempt_to_modify_reasoning_of_recorded_observation() -> None:
    """SC9: reassigning `reasoning` on a recorded observation is rejected."""
    # Arrange
    baseline = Baseline()
    result = ScoringResultFactory()
    baseline.record(result)
    observed = baseline.observations[0]
    original_reasoning = observed.reasoning

    # Act
    with pytest.raises(ValidationError):
        observed.reasoning = "tampered"  # ty: ignore[invalid-assignment]

    # Assert
    assert baseline.observations[0].reasoning == original_reasoning


def test_rejects_attempt_to_modify_provenance_of_recorded_observation() -> None:
    """SC9: reassigning `provenance` on a recorded observation is rejected."""
    # Arrange
    baseline = Baseline()
    result = ScoringResultFactory()
    baseline.record(result)
    observed = baseline.observations[0]
    original_provenance = observed.provenance

    # Act
    with pytest.raises(ValidationError):
        observed.provenance = None  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

    # Assert
    assert baseline.observations[0].provenance == original_provenance


# --- SC10: error category distinguishability ---------------------------------


def test_recording_errors_are_distinguishable_by_category_with_distinct_guidance() -> (
    None
):
    """SC10: a provenance mismatch and an invalid observation are pairwise distinct."""
    # Arrange
    mismatch_baseline = Baseline()
    mismatch_baseline.record(_result(model_version="claude-sonnet-a"))

    # Act
    provenance_mismatch_error = _record_and_capture_error(
        mismatch_baseline, _result(model_version="claude-sonnet-b")
    )
    invalid_observation_error = _record_and_capture_error(Baseline(), None)
    errors = [provenance_mismatch_error, invalid_observation_error]

    # Assert
    assert len({type(error) for error in errors}) == 2
    assert len({error.category for error in errors}) == 2
    assert len({error.recovery_hint for error in errors}) == 2


# --- Collection protocol (BIN-110 P1) -----------------------------------------
#
# Before BIN-110: ``len(baseline)`` raised ``TypeError``, ``for obs in
# baseline`` raised ``TypeError``, and ``repr(baseline)`` printed
# ``<...Baseline object at 0x...>``. ``.observation_count`` and
# ``.observations`` already worked, but the obvious Python collection forms
# did not -- a collection answering neither ``len()`` nor iteration is not
# holding up its end of Python. ``observation_count`` is KEPT (it reads
# better in ``SufficiencyResult``'s context and in log lines, per the
# ticket) -- ``__len__``/``__iter__``/``__repr__`` are added alongside it,
# not instead of it.


def test_len_returns_the_observation_count() -> None:
    """``len(baseline)`` must agree with ``.observation_count``, not raise."""
    # Arrange
    baseline = Baseline()
    baseline.record(ScoringResultFactory())
    baseline.record(ScoringResultFactory(provenance=baseline.provenance_signature))

    # Act / Assert
    assert len(baseline) == 2
    assert len(baseline) == baseline.observation_count


def test_len_of_empty_baseline_is_zero() -> None:
    """An empty baseline must answer ``len()``, not raise ``TypeError``."""
    assert len(Baseline()) == 0


def test_is_iterable_and_yields_observations_in_recording_order() -> None:
    """``for obs in baseline`` must work and preserve recording order."""
    # Arrange
    baseline = Baseline()
    shared_provenance = ProvenanceFactory()
    results = [
        ScoringResultFactory(provenance=shared_provenance, score=score)
        for score in (0.9, 0.1, 0.5)
    ]
    for result in results:
        baseline.record(result)

    # Act
    iterated = list(baseline)

    # Assert
    assert iterated == results
    assert iterated == list(baseline.observations)


def test_iterating_an_empty_baseline_yields_nothing() -> None:
    """An empty baseline must be iterable, yielding zero observations."""
    assert list(Baseline()) == []


def test_supports_membership_test_via_iteration() -> None:
    """``x in baseline`` -- the natural consequence of being iterable."""
    # Arrange
    baseline = Baseline()
    result = ScoringResultFactory()
    other = ScoringResultFactory(provenance=result.provenance)
    baseline.record(result)

    # Act / Assert
    assert result in baseline
    assert other not in baseline


def test_empty_baseline_is_falsy_as_a_natural_consequence_of_len() -> None:
    """An empty collection is falsy -- the standard Python collection contract.

    This falls out of adding ``__len__`` (Python uses it for ``bool()``
    when ``__bool__`` is absent); no separate ``__bool__`` is needed or
    added. Unlike ``SufficiencyResult``/``ScoringResult``/``Fitted*`` (see
    ``tests/unit/test_truthiness.py``), ``Baseline`` is a genuine mutable
    collection, so "empty is falsy" is the correct, unambiguous meaning --
    not the trap those immutable result types' identity-truthiness was.
    """
    assert not Baseline()


def test_nonempty_baseline_is_truthy() -> None:
    """The positive partition of the same collection contract."""
    baseline = Baseline()
    baseline.record(ScoringResultFactory())

    assert baseline


def test_repr_reports_class_name_and_observation_count() -> None:
    """``repr(baseline)`` must be a useful REPL/log/debugger representation.

    Before BIN-110, ``Baseline`` had no ``__repr__`` and printed as
    ``<caliper.baseline.domain.baseline.Baseline object at 0x...>`` --
    useless in a REPL, a log line, or a debugger (``CLAUDE.md``: "Every
    public type reprs usefully"). This does not pin an exact format string
    (an implementation detail) -- it pins the two facts a useful repr must
    surface.
    """
    # Arrange
    baseline = Baseline()
    baseline.record(ScoringResultFactory())
    baseline.record(ScoringResultFactory(provenance=baseline.provenance_signature))

    # Act
    text = repr(baseline)

    # Assert
    assert "Baseline" in text
    assert "2" in text  # observation_count, somewhere in the repr
    assert "0x" not in text  # not the default object.__repr__ memory address


def test_repr_of_empty_baseline_does_not_use_the_default_object_repr() -> None:
    """The empty case must also get a useful repr, not the default."""
    text = repr(Baseline())

    assert "Baseline" in text
    assert "0x" not in text
    assert "object at" not in text
