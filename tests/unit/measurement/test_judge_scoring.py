"""Unit tests for Judge.score() (BIN-59).

Pins the seven acceptance scenarios in
``tests/bdd/features/measurement/score-agent-output-structured-results.feature``
at the unit level, plus a handful of ADR-006-settled behaviours the feature
file's open questions resolve but do not name as separate scenarios (empty
agent output, per-call criteria override, missing-provider). Error
assertions follow ADR-002: type + required ``context`` keys only -- never
message text. Recovery guidance *distinctness* (not content) is asserted
where the feature file requires it.

Uses ``FakeJudgeProviderPort`` (``tests/support/fakes.py``) throughout --
no network call, per ADR-006's note for backend-test-writer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from drift_caliper.errors import (
    InvalidParameterError,
    JudgeRefusalError,
    MalformedResponseError,
    MissingPrerequisiteError,
    ProviderError,
)
from drift_caliper.measurement import Judge, JudgeProviderResponse, Provenance
from tests.support.fakes import FakeJudgeProviderPort

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."
_AGENT_OUTPUT = "The capital of France is Paris."


def _configured_judge(
    *, response: JudgeProviderResponse | None = None
) -> tuple[Judge, FakeJudgeProviderPort]:
    """Build a Judge with a pinned model version, criteria, and a fake provider."""
    provider = FakeJudgeProviderPort(response=response)
    judge = Judge.create(
        model_version=_MODEL_VERSION, provider=provider, criteria=_CRITERIA
    )
    return judge, provider


# --- Scenario: happy path ---------------------------------------------------


def test_returns_result_with_numeric_score_and_reasoning_when_scoring_succeeds() -> (
    None
):
    """SC1: a successful scoring call returns a numeric score and reasoning."""
    # Arrange
    judge, _ = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )

    # Act
    result = judge.score(_AGENT_OUTPUT)

    # Assert
    assert isinstance(result.score, float)
    assert isinstance(result.reasoning, str)
    assert result.reasoning != ""


def test_calls_provider_with_the_judges_model_version_and_the_given_agent_output() -> (
    None
):
    """The provider is called with the judge's own model version and the

    exact agent output passed to score() -- not some other value. Mutation
    testing (BIN-103) found `self.provider.score(...)` could pass ``None``
    for either argument with no test noticing; the provenance-only checks
    below assert on `self.model_version` directly, which is independent of
    what was actually handed to the provider.
    """
    # Arrange
    judge, provider = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )

    # Act
    judge.score(_AGENT_OUTPUT)

    # Assert
    assert provider.calls[-1]["model_version"] == _MODEL_VERSION
    assert provider.calls[-1]["agent_output"] == _AGENT_OUTPUT


# --- Scenario: provenance ---------------------------------------------------


def test_result_provenance_reports_judges_model_version_and_criteria_exactly() -> None:
    """SC2: provenance reports the model version and criteria, matching the judge."""
    # Arrange
    judge, _ = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )

    # Act
    result = judge.score(_AGENT_OUTPUT)

    # Assert
    assert isinstance(result.provenance, Provenance)
    assert result.provenance.model_version.value == _MODEL_VERSION
    assert result.provenance.scoring_criteria.value == _CRITERIA
    assert result.provenance.model_version == judge.model_version
    assert result.provenance.scoring_criteria == judge.criteria


# --- Scenario: provider error -----------------------------------------------


def test_raises_provider_error_when_providers_call_fails() -> None:
    """SC3: a provider failure is classifiable as a provider failure; no result."""
    # Arrange
    provider = FakeJudgeProviderPort(
        error_to_raise=ProviderError(
            "the provider returned an error",
            context={"provider": "test-provider", "operation": "score"},
            recovery_hint="Check the provider's status and retry.",
        )
    )
    judge = Judge.create(
        model_version=_MODEL_VERSION, provider=provider, criteria=_CRITERIA
    )

    # Act
    with pytest.raises(ProviderError) as exc_info:
        judge.score(_AGENT_OUTPUT)

    # Assert
    error = exc_info.value
    assert error.category == "provider_failure"
    assert error.context["provider"] == "test-provider"
    assert error.context["operation"] == "score"


# --- Scenario: malformed response -------------------------------------------


def test_raises_malformed_response_error_when_response_is_uninterpretable() -> None:
    """SC4: an uninterpretable response is classifiable as malformed; no result."""
    # Arrange
    provider = FakeJudgeProviderPort(
        error_to_raise=MalformedResponseError(
            "the provider's response could not be interpreted",
            context={"operation": "score", "expected_shape": "(score, reasoning)"},
            recovery_hint="Inspect the judge's raw response and its parser.",
        )
    )
    judge = Judge.create(
        model_version=_MODEL_VERSION, provider=provider, criteria=_CRITERIA
    )

    # Act
    with pytest.raises(MalformedResponseError) as exc_info:
        judge.score(_AGENT_OUTPUT)

    # Assert
    error = exc_info.value
    assert error.category == "malformed_response"
    assert error.context["operation"] == "score"
    assert isinstance(error.context["expected_shape"], str)
    assert error.context["expected_shape"] != ""


def test_raises_judge_refusal_error_when_provider_declines_to_score() -> None:
    """The port's third named exception also propagates through score() unchanged."""
    # Arrange
    provider = FakeJudgeProviderPort(
        error_to_raise=JudgeRefusalError(
            "the provider declined to score this output",
            context={"provider": "test-provider", "operation": "score"},
            recovery_hint="Review the provider's content policy.",
        )
    )
    judge = Judge.create(
        model_version=_MODEL_VERSION, provider=provider, criteria=_CRITERIA
    )

    # Act
    with pytest.raises(JudgeRefusalError) as exc_info:
        judge.score(_AGENT_OUTPUT)

    # Assert
    error = exc_info.value
    assert error.category == "judge_refusal"
    assert error.context["provider"] == "test-provider"
    assert error.context["operation"] == "score"


# --- Scenario: missing prerequisites ----------------------------------------


def test_raises_missing_prerequisite_error_when_no_provider_configured() -> None:
    """No provider at all fails as a missing prerequisite, before anything else."""
    # Arrange
    judge = Judge.create(model_version=_MODEL_VERSION, criteria=_CRITERIA)

    # Act
    with pytest.raises(MissingPrerequisiteError) as exc_info:
        judge.score(_AGENT_OUTPUT)

    # Assert
    error = exc_info.value
    assert error.category == "missing_prerequisite"
    assert error.context["prerequisite"] == "judge_provider"
    assert error.context["operation"] == "score"


def test_raises_missing_prerequisite_error_when_no_criteria_available() -> None:
    """SC6: no criteria anywhere fails immediately as a missing prerequisite."""
    # Arrange
    provider = FakeJudgeProviderPort(
        response=JudgeProviderResponse(score=0.9, reasoning="should never be reached")
    )
    judge = Judge.create(model_version=_MODEL_VERSION, provider=provider)

    # Act
    with pytest.raises(MissingPrerequisiteError) as exc_info:
        judge.score(_AGENT_OUTPUT)

    # Assert
    error = exc_info.value
    assert error.category == "missing_prerequisite"
    assert error.context["prerequisite"] == "scoring_criteria"
    assert error.context["operation"] == "score"


def test_provider_is_never_called_when_criteria_is_missing() -> None:
    """SC6: the failure happens before reaching the judge's provider."""
    # Arrange
    provider = FakeJudgeProviderPort(
        response=JudgeProviderResponse(score=0.9, reasoning="should never be reached")
    )
    judge = Judge.create(model_version=_MODEL_VERSION, provider=provider)

    # Act
    with pytest.raises(MissingPrerequisiteError):
        judge.score(_AGENT_OUTPUT)

    # Assert
    assert provider.calls == []


# --- Scenario: immutability -------------------------------------------------


def test_rejects_attempt_to_modify_score_after_creation() -> None:
    """SC5: reassigning `score` is rejected; the original value is retained."""
    # Arrange
    judge, _ = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )
    result = judge.score(_AGENT_OUTPUT)
    original_score = result.score

    # Act
    with pytest.raises(ValidationError):
        result.score = 0.1  # ty: ignore[invalid-assignment]

    # Assert
    assert result.score == original_score


def test_rejects_attempt_to_modify_reasoning_after_creation() -> None:
    """SC5: reassigning `reasoning` is rejected; the original value is retained."""
    # Arrange
    judge, _ = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )
    result = judge.score(_AGENT_OUTPUT)
    original_reasoning = result.reasoning

    # Act
    with pytest.raises(ValidationError):
        result.reasoning = "tampered"  # ty: ignore[invalid-assignment]

    # Assert
    assert result.reasoning == original_reasoning


def test_rejects_attempt_to_modify_provenance_after_creation() -> None:
    """SC5: reassigning `provenance` is rejected; the original value is retained."""
    # Arrange
    judge, _ = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )
    result = judge.score(_AGENT_OUTPUT)
    original_provenance = result.provenance

    # Act
    with pytest.raises(ValidationError):
        result.provenance = None  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

    # Assert
    assert result.provenance == original_provenance


# --- Scenario: error category distinguishability ---------------------------


def test_failure_categories_are_distinguishable_with_distinct_recovery_hints() -> None:
    """SC7: the three failure categories are pairwise distinct in type, category

    and recovery guidance -- classifiable without inspecting message text.
    """
    # Arrange
    provider_error_judge = Judge.create(
        model_version=_MODEL_VERSION,
        provider=FakeJudgeProviderPort(
            error_to_raise=ProviderError(
                "provider failed",
                context={"provider": "test-provider", "operation": "score"},
                recovery_hint="Check the provider's status and retry.",
            )
        ),
        criteria=_CRITERIA,
    )
    malformed_response_judge = Judge.create(
        model_version=_MODEL_VERSION,
        provider=FakeJudgeProviderPort(
            error_to_raise=MalformedResponseError(
                "response could not be interpreted",
                context={"operation": "score", "expected_shape": "(score, reasoning)"},
                recovery_hint="Inspect the judge's raw response and its parser.",
            )
        ),
        criteria=_CRITERIA,
    )
    missing_prerequisite_judge = Judge.create(
        model_version=_MODEL_VERSION,
        provider=FakeJudgeProviderPort(
            response=JudgeProviderResponse(score=0.9, reasoning="unreachable")
        ),
        # no criteria configured anywhere
    )

    # Act
    with pytest.raises(ProviderError) as provider_info:
        provider_error_judge.score(_AGENT_OUTPUT)
    with pytest.raises(MalformedResponseError) as malformed_info:
        malformed_response_judge.score(_AGENT_OUTPUT)
    with pytest.raises(MissingPrerequisiteError) as missing_info:
        missing_prerequisite_judge.score(_AGENT_OUTPUT)

    # Assert
    errors = [provider_info.value, malformed_info.value, missing_info.value]

    assert len({type(error) for error in errors}) == 3
    assert len({error.category for error in errors}) == 3
    assert len({error.recovery_hint for error in errors}) == 3


# --- ADR-006 section 6: empty agent output ----------------------------------


def test_raises_invalid_parameter_error_when_agent_output_is_empty_string() -> None:
    """An empty agent output is rejected before any provider call."""
    # Arrange
    judge, provider = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="should never be reached")
    )

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        judge.score("")

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "agent_output"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == ""
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""
    assert provider.calls == []


def test_raises_invalid_parameter_error_when_agent_output_is_whitespace_only() -> None:
    """A whitespace-only agent output is rejected before any provider call."""
    # Arrange
    judge, provider = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="should never be reached")
    )
    whitespace_only = "   \t  "

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        judge.score(whitespace_only)

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "agent_output"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == whitespace_only
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""
    assert provider.calls == []


# --- ADR-006 section 3: agent_input is forwarded to the provider -----------


def test_forwards_agent_input_to_the_provider_when_supplied() -> None:
    """``agent_input`` reaches the provider call, even though it is never

    carried onto ``Provenance`` or ``ScoringResult`` (ADR-006 section 3).
    Mutation testing (BIN-103) found `self.provider.score(...)` could drop
    ``agent_input`` entirely with no test noticing -- this closes that gap.
    """
    # Arrange
    judge, provider = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )
    agent_input = "What is the capital of France?"

    # Act
    judge.score(_AGENT_OUTPUT, agent_input=agent_input)

    # Assert
    assert provider.calls[-1]["agent_input"] == agent_input


# --- ADR-006 section 2: per-call criteria overrides judge-level criteria ----


def test_per_call_criteria_overrides_judge_level_criteria_for_that_call() -> None:
    """Per-call criteria wins for that call, without mutating the judge."""
    # Arrange
    override_criteria = "Evaluate the response for tone only."
    judge, provider = _configured_judge(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )

    # Act
    result = judge.score(_AGENT_OUTPUT, criteria=override_criteria)

    # Assert
    assert result.provenance.scoring_criteria.value == override_criteria
    assert provider.calls[-1]["criteria"] == override_criteria
    assert judge.criteria is not None
    assert judge.criteria.value == _CRITERIA
