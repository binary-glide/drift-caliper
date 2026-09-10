"""Step definitions for BIN-63: record observations into a Phase I baseline
collection.

Binds to
``tests/bdd/features/baseline/phase-i-baseline-collection.feature`` via
``tests/bdd/test_phase_i_baseline_collection.py``. Error assertions follow
ADR-002/ADR-008: type + required ``context`` keys only -- never message
text. No provider or network is involved -- ``Baseline.record()`` accepts
``ScoringResult`` values directly, so no fake is needed here (unlike
BIN-59's ``FakeJudgeProviderPort``).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from pytest_bdd import given, then, when

from caliper.baseline import Baseline
from caliper.errors import (
    CaliperError,
    InvalidObservationError,
    ProvenanceMismatchError,
)
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."


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


@dataclass
class RecordedObservation:
    """A baseline and the (still-held) result recorded into it."""

    baseline: Baseline
    result: ScoringResult


@dataclass
class RecordedSequence:
    """A baseline and the exact sequence of results recorded into it."""

    baseline: Baseline
    results: list[ScoringResult]


@dataclass
class RecordingAttempt:
    """Outcome of an attempt to record into a baseline that may fail.

    Captures the full observation sequence before the attempt, not just
    the count -- a count-only check would not catch a mutant that left the
    count unchanged while silently swapping or corrupting the existing
    observations.
    """

    baseline: Baseline
    error: CaliperError | None
    observation_count_before: int
    observations_before: tuple[ScoringResult, ...]


@dataclass
class ResultMutationAttempt:
    """Outcome of attempting to reassign every field of a recorded observation."""

    observation: ScoringResult
    errors: list[Exception]


def _attempt_record(baseline: Baseline, observation: object) -> RecordingAttempt:
    """Attempt to record ``observation``, capturing any ``CaliperError``."""
    count_before = baseline.observation_count
    observations_before = tuple(baseline.observations)
    try:
        baseline.record(observation)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    except CaliperError as exc:
        return RecordingAttempt(
            baseline=baseline,
            error=exc,
            observation_count_before=count_before,
            observations_before=observations_before,
        )
    return RecordingAttempt(
        baseline=baseline,
        error=None,
        observation_count_before=count_before,
        observations_before=observations_before,
    )


# --- Scenario: record and inspect (SC1) --------------------------------------


@given("the engineer has a Phase I baseline collection", target_fixture="baseline")
def a_phase_i_baseline_collection() -> Baseline:
    """A fresh, empty baseline, ready to accept observations."""
    return Baseline()


@given(
    "they have a scored agent output with a numeric score, reasoning, and provenance",
    target_fixture="scoring_result",
)
def a_scored_agent_output() -> ScoringResult:
    """A complete scoring result, as BIN-59's Judge.score() would produce."""
    return _result()


@when("they record the scoring result into the baseline")
def record_the_scoring_result(
    baseline: Baseline, scoring_result: ScoringResult
) -> None:
    """Record the scored result into the baseline."""
    baseline.record(scoring_result)


@then("the baseline contains the recorded observation")
def baseline_contains_the_recorded_observation(
    baseline: Baseline, scoring_result: ScoringResult
) -> None:
    """The recorded result is present among the baseline's observations."""
    assert scoring_result in baseline.observations


@then("the engineer can inspect the total number of observations in the baseline")
def engineer_can_inspect_total_observation_count(baseline: Baseline) -> None:
    """The baseline reports how many observations it holds."""
    assert baseline.observation_count == 1


# --- Scenario: insertion order preserved (SC2) -------------------------------


@given(
    "the engineer has a Phase I baseline collection with several recorded observations",
    target_fixture="recorded_sequence",
)
def a_baseline_with_several_recorded_observations() -> RecordedSequence:
    """A baseline with several observations recorded in a specific order."""
    baseline = Baseline()
    results = [_result(score=score) for score in (0.9, 0.2, 0.6, 0.4)]
    for result in results:
        baseline.record(result)
    return RecordedSequence(baseline=baseline, results=results)


@when(
    "they inspect the observations in the baseline",
    target_fixture="observed_sequence",
)
def inspect_the_observations(
    recorded_sequence: RecordedSequence,
) -> list[ScoringResult]:
    """Read back the baseline's observations."""
    return list(recorded_sequence.baseline.observations)


@then("the observations appear in the order they were recorded")
def observations_appear_in_recorded_order(
    observed_sequence: list[ScoringResult], recorded_sequence: RecordedSequence
) -> None:
    """The read-back sequence matches the exact recording order."""
    assert observed_sequence == recorded_sequence.results


# --- Scenario: full provenance retained (SC3) --------------------------------


@given(
    "the engineer has recorded a scoring result into a Phase I baseline",
    target_fixture="recorded_observation",
)
def recorded_a_scoring_result() -> RecordedObservation:
    """A baseline with exactly one recorded observation."""
    baseline = Baseline()
    result = _result()
    baseline.record(result)
    return RecordedObservation(baseline=baseline, result=result)


@when("they inspect the recorded observation", target_fixture="observed")
def inspect_the_recorded_observation(
    recorded_observation: RecordedObservation,
) -> ScoringResult:
    """Read back the single recorded observation."""
    return recorded_observation.baseline.observations[0]


@then("the observation reports the model version that produced the score")
def observation_reports_model_version(
    observed: ScoringResult, recorded_observation: RecordedObservation
) -> None:
    """The observation's provenance carries the original model version."""
    expected = recorded_observation.result.provenance.model_version
    assert observed.provenance.model_version == expected


@then("the observation reports the criteria the score was assessed against")
def observation_reports_criteria(
    observed: ScoringResult, recorded_observation: RecordedObservation
) -> None:
    """The observation's provenance carries the original scoring criteria."""
    expected = recorded_observation.result.provenance.scoring_criteria
    assert observed.provenance.scoring_criteria == expected


@then("the provenance values match the original scoring result exactly")
def provenance_matches_original_result_exactly(
    observed: ScoringResult, recorded_observation: RecordedObservation
) -> None:
    """The observation's whole provenance is value-equal to the original."""
    assert observed.provenance == recorded_observation.result.provenance


# --- Scenario: score and reasoning retained (SC4) ----------------------------


@given(
    "the engineer has recorded a scoring result with a specific numeric "
    "score and specific reasoning into a Phase I baseline",
    target_fixture="recorded_observation",
)
def recorded_a_scoring_result_with_specific_score_and_reasoning() -> (
    RecordedObservation
):
    """A baseline with one observation carrying a specific score/reasoning."""
    baseline = Baseline()
    result = _result(score=0.73, reasoning="Specific, distinguishable reasoning text.")
    baseline.record(result)
    return RecordedObservation(baseline=baseline, result=result)


@then("the observation reports the same numeric score as the original scoring result")
def observation_reports_same_score(
    observed: ScoringResult, recorded_observation: RecordedObservation
) -> None:
    """The observation's score matches the original exactly."""
    assert observed.score == recorded_observation.result.score


@then("the observation reports the same reasoning as the original scoring result")
def observation_reports_same_reasoning(
    observed: ScoringResult, recorded_observation: RecordedObservation
) -> None:
    """The observation's reasoning matches the original exactly."""
    assert observed.reasoning == recorded_observation.result.reasoning


# --- Scenario: provenance mismatch -- model version (SC5) -------------------


@given(
    "the engineer has a Phase I baseline containing observations scored by "
    "a specific judge model version",
    target_fixture="recording_setup",
)
def a_baseline_with_a_specific_model_version() -> Baseline:
    """A baseline with one observation scored by a specific model version."""
    baseline = Baseline()
    baseline.record(_result(model_version="claude-sonnet-a"))
    return baseline


@when(
    "they attempt to record a scoring result produced by a different judge "
    "model version",
    target_fixture="recording_attempt",
)
def attempt_record_with_different_model_version(
    recording_setup: Baseline,
) -> RecordingAttempt:
    """Attempt to record a result scored by a different model version."""
    return _attempt_record(recording_setup, _result(model_version="claude-sonnet-b"))


# --- Scenario: provenance mismatch -- criteria (SC6) -------------------------


@given(
    "the engineer has a Phase I baseline containing observations scored "
    "against specific criteria",
    target_fixture="recording_setup",
)
def a_baseline_with_specific_criteria() -> Baseline:
    """A baseline with one observation scored against specific criteria."""
    baseline = Baseline()
    baseline.record(_result(criteria="Evaluate for tone."))
    return baseline


@when(
    "they attempt to record a scoring result produced against different criteria",
    target_fixture="recording_attempt",
)
def attempt_record_with_different_criteria(
    recording_setup: Baseline,
) -> RecordingAttempt:
    """Attempt to record a result scored against different criteria."""
    return _attempt_record(recording_setup, _result(criteria="Evaluate for accuracy."))


@then(
    "the recording fails with an error that is programmatically "
    "classifiable as a provenance mismatch"
)
def recording_fails_as_provenance_mismatch(recording_attempt: RecordingAttempt) -> None:
    """The attempt captured a ProvenanceMismatchError."""
    assert isinstance(recording_attempt.error, ProvenanceMismatchError)
    assert recording_attempt.error.category == "provenance_mismatch"


@then(
    "the error carries recovery guidance identifying which provenance dimension differs"
)
def error_identifies_differing_dimension(recording_attempt: RecordingAttempt) -> None:
    """The error's context names a non-empty, differing provenance dimension."""
    error = recording_attempt.error
    assert isinstance(error, ProvenanceMismatchError)
    assert isinstance(error.context["dimension"], str)
    assert error.context["dimension"] != ""
    assert error.context["expected"] != error.context["received"]


# --- Scenario: incomplete scoring result (SC7) -------------------------------


@when(
    "they attempt to record something that is not a complete scoring "
    "result with score, reasoning, and provenance",
    target_fixture="recording_attempt",
)
def attempt_record_an_incomplete_observation(baseline: Baseline) -> RecordingAttempt:
    """Attempt to record something that carries no scoring result fields."""
    return _attempt_record(baseline, None)


@then(
    "the recording fails with an error that is programmatically "
    "classifiable as an invalid observation"
)
def recording_fails_as_invalid_observation(recording_attempt: RecordingAttempt) -> None:
    """The attempt captured an InvalidObservationError."""
    assert isinstance(recording_attempt.error, InvalidObservationError)
    assert recording_attempt.error.category == "invalid_observation"


@then("the error carries recovery guidance identifying what the input is missing")
def error_identifies_what_is_missing(recording_attempt: RecordingAttempt) -> None:
    """The error's context names the missing fields."""
    error = recording_attempt.error
    assert isinstance(error, InvalidObservationError)
    assert isinstance(error.context["missing_fields"], list)
    assert len(error.context["missing_fields"]) > 0


@then("the baseline is unchanged")
def the_baseline_is_unchanged(recording_attempt: RecordingAttempt) -> None:
    """The failed attempt changed neither the count nor the observations."""
    assert (
        recording_attempt.baseline.observation_count
        == recording_attempt.observation_count_before
    )
    assert (
        tuple(recording_attempt.baseline.observations)
        == recording_attempt.observations_before
    )


# --- Scenario: first observation establishes provenance signature (SC8) -----


@given(
    "the engineer has a new empty Phase I baseline collection",
    target_fixture="baseline",
)
def a_new_empty_baseline() -> Baseline:
    """A brand-new, empty baseline."""
    return Baseline()


@when("they record their first scoring result", target_fixture="first_result")
def record_the_first_scoring_result(baseline: Baseline) -> ScoringResult:
    """Record a single scoring result into the (still-empty) baseline."""
    result = _result()
    baseline.record(result)
    return result


@then("the baseline reports one observation")
def baseline_reports_one_observation(baseline: Baseline) -> None:
    """The baseline's count reflects exactly one recorded observation."""
    assert baseline.observation_count == 1


@then(
    "the baseline reports the judge model version and scoring criteria "
    "from that observation as its expected provenance"
)
def baseline_reports_expected_provenance(
    baseline: Baseline, first_result: ScoringResult
) -> None:
    """The baseline's provenance signature matches the first observation's."""
    assert baseline.provenance_signature == first_result.provenance


# --- Scenario: observation immutability (SC9) --------------------------------


@when(
    "they attempt to modify the score, reasoning, or provenance of the "
    "recorded observation",
    target_fixture="mutation_attempt",
)
def attempt_to_modify_the_recorded_observation(
    recorded_observation: RecordedObservation,
) -> ResultMutationAttempt:
    """Attempt to reassign every field of the recorded observation."""
    observation = recorded_observation.baseline.observations[0]
    errors: list[Exception] = []
    for attribute, replacement in (
        ("score", 0.1),
        ("reasoning", "tampered"),
        ("provenance", None),
    ):
        try:
            setattr(observation, attribute, replacement)
        except (AttributeError, ValidationError) as exc:
            errors.append(exc)
    return ResultMutationAttempt(observation=observation, errors=errors)


@then("the modification is rejected")
def the_modification_is_rejected(mutation_attempt: ResultMutationAttempt) -> None:
    """Every attempted reassignment raised, and none silently succeeded."""
    assert len(mutation_attempt.errors) == 3
    assert all(
        isinstance(error, (AttributeError, ValidationError))
        for error in mutation_attempt.errors
    )


@then("the observation continues to report its original values")
def the_observation_reports_original_values(
    mutation_attempt: ResultMutationAttempt, recorded_observation: RecordedObservation
) -> None:
    """The observation's fields are unchanged by the rejected mutation attempts."""
    original = recorded_observation.result
    observed = mutation_attempt.observation
    assert observed.score == original.score
    assert observed.reasoning == original.reasoning
    assert observed.provenance == original.provenance


# --- Scenario: error category distinguishability (SC10) ---------------------


@given(
    "a recording attempt has failed with a provenance mismatch",
    target_fixture="provenance_mismatch_error",
)
def a_provenance_mismatch_error() -> CaliperError:
    """Produce a ProvenanceMismatchError from a real recording attempt."""
    baseline = Baseline()
    baseline.record(_result(model_version="claude-sonnet-a"))
    attempt = _attempt_record(baseline, _result(model_version="claude-sonnet-b"))
    assert attempt.error is not None
    return attempt.error


@given(
    "a separate recording attempt has failed with an invalid observation",
    target_fixture="invalid_observation_error",
)
def a_separate_invalid_observation_error() -> CaliperError:
    """Produce an InvalidObservationError from a real recording attempt."""
    attempt = _attempt_record(Baseline(), None)
    assert attempt.error is not None
    return attempt.error


@when("the engineer examines the two errors", target_fixture="two_errors")
def examine_the_two_errors(
    provenance_mismatch_error: CaliperError, invalid_observation_error: CaliperError
) -> list[CaliperError]:
    """Bundle the two independently-produced errors for comparison."""
    return [provenance_mismatch_error, invalid_observation_error]


@then(
    "each is classifiable under a different category without inspecting "
    "the error message text"
)
def each_error_has_a_different_category(two_errors: list[CaliperError]) -> None:
    """The two errors have pairwise-distinct types and category strings."""
    assert len({type(error) for error in two_errors}) == 2
    assert len({error.category for error in two_errors}) == 2


@then("the recovery guidance for each category is distinct from the other")
def recovery_guidance_is_distinct(two_errors: list[CaliperError]) -> None:
    """The two errors' recovery hints are pairwise distinct (content untested)."""
    assert len({error.recovery_hint for error in two_errors}) == 2
