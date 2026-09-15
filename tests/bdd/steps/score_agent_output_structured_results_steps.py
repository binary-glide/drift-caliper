"""Step definitions for BIN-59: score a single agent output and receive
structured results.

Binds to
``tests/bdd/features/measurement/score-agent-output-structured-results.feature``
via
``tests/bdd/test_score_agent_output_structured_results.py``. Error
assertions follow ADR-002: type + required ``context`` keys only -- never
message text. Uses ``FakeJudgeProviderPort`` (``tests/support/fakes.py``)
throughout -- no network call, per ADR-006's note for backend-test-writer.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from pytest_bdd import given, then, when

from drift_caliper.errors import (
    CaliperError,
    MalformedResponseError,
    MissingPrerequisiteError,
    ProviderError,
)
from drift_caliper.measurement import Judge, JudgeProviderResponse, ScoringResult
from tests.support.fakes import FakeJudgeProviderPort

_AGENT_OUTPUT = "The capital of France is Paris."


@dataclass
class ScoringSetup:
    """A judge, its fake provider, and the raw configuration values used."""

    judge: Judge
    provider: FakeJudgeProviderPort
    model_version: str
    criteria: str


@dataclass
class ScoringAttempt:
    """Outcome of an attempted scoring call."""

    result: ScoringResult | None
    error: CaliperError | None


@dataclass
class ResultMutationAttempt:
    """Outcome of attempting to reassign every field of a ScoringResult."""

    result: ScoringResult
    errors: list[Exception]


def _attempt_score(
    judge: Judge, *, agent_output: str = _AGENT_OUTPUT
) -> ScoringAttempt:
    """Call ``judge.score()``, capturing success or a Caliper error."""
    try:
        result = judge.score(agent_output)
    except CaliperError as exc:
        return ScoringAttempt(result=None, error=exc)
    return ScoringAttempt(result=result, error=None)


# --- Scenario: happy path ---------------------------------------------------


@given(
    "the engineer has a judge configured with a pinned model version and "
    "scoring criteria",
    target_fixture="scoring_setup",
)
def judge_configured_with_version_and_criteria() -> ScoringSetup:
    """A judge with a valid provider, model version and criteria."""
    model_version = "claude-sonnet-4-5-20250929"
    criteria = "Evaluate the response for factual accuracy and helpfulness."
    provider = FakeJudgeProviderPort(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )
    judge = Judge.create(
        model_version=model_version, provider=provider, criteria=criteria
    )
    return ScoringSetup(
        judge=judge, provider=provider, model_version=model_version, criteria=criteria
    )


@when("they score an agent output", target_fixture="scoring_result")
def score_an_agent_output(scoring_setup: ScoringSetup) -> ScoringResult:
    """Score the fixed agent output through the configured judge."""
    return scoring_setup.judge.score(_AGENT_OUTPUT)


@then("they receive a result containing a numeric score")
def result_contains_numeric_score(scoring_result: ScoringResult) -> None:
    """The result's score is a numeric (float) value."""
    assert isinstance(scoring_result.score, float)


@then("the result contains the judge's textual reasoning for the score")
def result_contains_textual_reasoning(scoring_result: ScoringResult) -> None:
    """The result's reasoning is non-empty text."""
    assert isinstance(scoring_result.reasoning, str)
    assert scoring_result.reasoning != ""


# --- Scenario: provenance ---------------------------------------------------


@given(
    "the engineer has a judge with a specific pinned model version and "
    "specific scoring criteria",
    target_fixture="scoring_setup",
)
def judge_with_specific_version_and_criteria() -> ScoringSetup:
    """A judge configured with specific, trackable model version and criteria."""
    model_version = "claude-opus-4-20250514"
    criteria = "Evaluate the response for tone and correctness."
    provider = FakeJudgeProviderPort(
        response=JudgeProviderResponse(score=0.75, reasoning="Correct, neutral tone.")
    )
    judge = Judge.create(
        model_version=model_version, provider=provider, criteria=criteria
    )
    return ScoringSetup(
        judge=judge, provider=provider, model_version=model_version, criteria=criteria
    )


@when(
    "they score an agent output and inspect the result",
    target_fixture="scoring_result",
)
def score_and_inspect_result(scoring_setup: ScoringSetup) -> ScoringResult:
    """Score the fixed agent output and keep the result for inspection."""
    return scoring_setup.judge.score(_AGENT_OUTPUT)


@then("the result reports the model version that produced the score")
def result_reports_model_version(
    scoring_result: ScoringResult, scoring_setup: ScoringSetup
) -> None:
    """The result's provenance carries the judge's model version."""
    assert scoring_result.provenance.model_version.value == scoring_setup.model_version


@then("the result reports the criteria the score was assessed against")
def result_reports_criteria(
    scoring_result: ScoringResult, scoring_setup: ScoringSetup
) -> None:
    """The result's provenance carries the judge's criteria."""
    assert scoring_result.provenance.scoring_criteria.value == scoring_setup.criteria


@then("the provenance values match the judge's configuration exactly")
def provenance_matches_judge_configuration(
    scoring_result: ScoringResult, scoring_setup: ScoringSetup
) -> None:
    """Provenance's value objects are value-equal to the judge's own fields."""
    assert scoring_result.provenance.model_version == scoring_setup.judge.model_version
    assert scoring_result.provenance.scoring_criteria == scoring_setup.judge.criteria


# --- Scenarios: provider error / malformed response -------------------------


@given(
    "the engineer has a judge configured with criteria",
    target_fixture="scoring_setup",
)
def judge_configured_with_criteria() -> ScoringSetup:
    """A judge with criteria and an as-yet-unconfigured fake provider."""
    model_version = "claude-sonnet-4-5-20250929"
    criteria = "Evaluate the response for factual accuracy and helpfulness."
    provider = FakeJudgeProviderPort()
    judge = Judge.create(
        model_version=model_version, provider=provider, criteria=criteria
    )
    return ScoringSetup(
        judge=judge, provider=provider, model_version=model_version, criteria=criteria
    )


@when(
    "they attempt to score an agent output and the judge's provider returns an error",
    target_fixture="scoring_attempt",
)
def attempt_score_with_provider_error(scoring_setup: ScoringSetup) -> ScoringAttempt:
    """Configure the fake to fail as a provider error, then attempt to score."""
    scoring_setup.provider.error_to_raise = ProviderError(
        "the provider returned an error",
        context={"provider": "test-provider", "operation": "score"},
        recovery_hint="Check the provider's status and retry.",
    )
    return _attempt_score(scoring_setup.judge)


@then(
    "the scoring call fails with an error that is programmatically "
    "classifiable as a provider failure"
)
def scoring_fails_as_provider_failure(scoring_attempt: ScoringAttempt) -> None:
    """The attempt captured a ProviderError, not a result."""
    assert isinstance(scoring_attempt.error, ProviderError)
    assert scoring_attempt.error.category == "provider_failure"


@then(
    "the error carries recovery guidance identifying the provider and the "
    "failed operation"
)
def error_identifies_provider_and_operation(scoring_attempt: ScoringAttempt) -> None:
    """The error's context names the failed provider and operation."""
    error = scoring_attempt.error
    assert isinstance(error, ProviderError)
    assert isinstance(error.context["provider"], str)
    assert error.context["provider"] != ""
    assert error.context["operation"] == "score"


@when(
    "they attempt to score an agent output and the judge produces a "
    "response that cannot be interpreted as a structured result",
    target_fixture="scoring_attempt",
)
def attempt_score_with_malformed_response(
    scoring_setup: ScoringSetup,
) -> ScoringAttempt:
    """Configure the fake to fail as a malformed response, then attempt to score."""
    scoring_setup.provider.error_to_raise = MalformedResponseError(
        "the provider's response could not be interpreted",
        context={"operation": "score", "expected_shape": "(score, reasoning)"},
        recovery_hint="Inspect the judge's raw response and its parser.",
    )
    return _attempt_score(scoring_setup.judge)


@then(
    "the scoring call fails with an error that is programmatically "
    "classifiable as a malformed response"
)
def scoring_fails_as_malformed_response(scoring_attempt: ScoringAttempt) -> None:
    """The attempt captured a MalformedResponseError, not a result."""
    assert isinstance(scoring_attempt.error, MalformedResponseError)
    assert scoring_attempt.error.category == "malformed_response"


@then("the error carries recovery guidance identifying the expected response shape")
def error_identifies_expected_response_shape(scoring_attempt: ScoringAttempt) -> None:
    """The error's context names the expected response shape."""
    error = scoring_attempt.error
    assert isinstance(error, MalformedResponseError)
    assert isinstance(error.context["expected_shape"], str)
    assert error.context["expected_shape"] != ""


@then("no result is returned")
def no_result_is_returned(scoring_attempt: ScoringAttempt) -> None:
    """The scoring attempt produced no result at all."""
    assert scoring_attempt.result is None


@then("no partial or default result is returned")
def no_partial_or_default_result_is_returned(scoring_attempt: ScoringAttempt) -> None:
    """The scoring attempt produced no result -- not even a partial one."""
    assert scoring_attempt.result is None


# --- Scenario: missing criteria ---------------------------------------------


@given(
    "the engineer has a judge but no scoring criteria are available",
    target_fixture="scoring_setup",
)
def judge_with_no_criteria() -> ScoringSetup:
    """A judge with a provider but no criteria configured anywhere."""
    model_version = "claude-sonnet-4-5-20250929"
    provider = FakeJudgeProviderPort(
        response=JudgeProviderResponse(score=0.9, reasoning="should never be reached")
    )
    judge = Judge.create(model_version=model_version, provider=provider)
    return ScoringSetup(
        judge=judge, provider=provider, model_version=model_version, criteria=""
    )


@when("they attempt to score an agent output", target_fixture="scoring_attempt")
def attempt_score_an_agent_output(scoring_setup: ScoringSetup) -> ScoringAttempt:
    """Attempt to score without configuring any failure.

    The missing criteria is itself the prerequisite under test here.
    """
    return _attempt_score(scoring_setup.judge)


@then(
    "the scoring call fails immediately with an error that is "
    "programmatically classifiable as a missing prerequisite"
)
def scoring_fails_immediately_as_missing_prerequisite(
    scoring_attempt: ScoringAttempt, scoring_setup: ScoringSetup
) -> None:
    """The attempt captured a MissingPrerequisiteError before reaching the provider."""
    assert isinstance(scoring_attempt.error, MissingPrerequisiteError)
    assert scoring_attempt.error.category == "missing_prerequisite"
    assert scoring_setup.provider.calls == []


@then("the error identifies that scoring criteria are required")
def error_identifies_scoring_criteria_required(
    scoring_attempt: ScoringAttempt,
) -> None:
    """The error's context names the missing scoring_criteria prerequisite."""
    error = scoring_attempt.error
    assert isinstance(error, MissingPrerequisiteError)
    assert error.context["prerequisite"] == "scoring_criteria"


# --- Scenario: immutability --------------------------------------------------


@given(
    "the engineer has scored an agent output and received a result",
    target_fixture="scored_result",
)
def scored_an_agent_output() -> ScoringResult:
    """Score an agent output through a happy-path judge and keep the result."""
    provider = FakeJudgeProviderPort(
        response=JudgeProviderResponse(score=0.9, reasoning="Accurate and concise.")
    )
    judge = Judge.create(
        model_version="claude-sonnet-4-5-20250929",
        provider=provider,
        criteria="Evaluate the response for factual accuracy and helpfulness.",
    )
    return judge.score(_AGENT_OUTPUT)


@when(
    "they attempt to modify the score, reasoning, or provenance of that result",
    target_fixture="result_mutation_attempt",
)
def attempt_to_modify_result(scored_result: ScoringResult) -> ResultMutationAttempt:
    """Attempt to reassign every field of the result, capturing each rejection."""
    errors: list[Exception] = []
    for attribute, replacement in (
        ("score", 0.1),
        ("reasoning", "tampered"),
        ("provenance", None),
    ):
        try:
            setattr(scored_result, attribute, replacement)
        except (AttributeError, ValidationError) as exc:
            errors.append(exc)
    return ResultMutationAttempt(result=scored_result, errors=errors)


@then("the modification is rejected")
def modification_is_rejected(result_mutation_attempt: ResultMutationAttempt) -> None:
    """Every attempted reassignment raised, and none silently succeeded."""
    assert len(result_mutation_attempt.errors) == 3
    assert all(
        isinstance(error, (AttributeError, ValidationError))
        for error in result_mutation_attempt.errors
    )


@then("the result continues to report its original values")
def result_reports_original_values(
    result_mutation_attempt: ResultMutationAttempt, scored_result: ScoringResult
) -> None:
    """The result's fields are unchanged by the rejected mutation attempts."""
    assert result_mutation_attempt.result.score == scored_result.score
    assert result_mutation_attempt.result.reasoning == scored_result.reasoning
    assert result_mutation_attempt.result.provenance == scored_result.provenance


# --- Scenario: error category distinguishability ---------------------------


@given(
    "a scoring call has failed with a provider error", target_fixture="provider_error"
)
def a_provider_error() -> CaliperError:
    """Produce a ProviderError from a real scoring attempt."""
    provider = FakeJudgeProviderPort(
        error_to_raise=ProviderError(
            "provider failed",
            context={"provider": "test-provider", "operation": "score"},
            recovery_hint="Check the provider's status and retry.",
        )
    )
    judge = Judge.create(
        model_version="claude-sonnet-4-5-20250929", provider=provider, criteria="x"
    )
    attempt = _attempt_score(judge)
    assert attempt.error is not None
    return attempt.error


@given(
    "a separate scoring call has failed with a malformed judge response",
    target_fixture="malformed_response_error",
)
def a_malformed_response_error() -> CaliperError:
    """Produce a MalformedResponseError from a real scoring attempt."""
    provider = FakeJudgeProviderPort(
        error_to_raise=MalformedResponseError(
            "response could not be interpreted",
            context={"operation": "score", "expected_shape": "(score, reasoning)"},
            recovery_hint="Inspect the judge's raw response and its parser.",
        )
    )
    judge = Judge.create(
        model_version="claude-sonnet-4-5-20250929", provider=provider, criteria="x"
    )
    attempt = _attempt_score(judge)
    assert attempt.error is not None
    return attempt.error


@given(
    "a third scoring call has failed with a missing prerequisite",
    target_fixture="missing_prerequisite_error",
)
def a_missing_prerequisite_error() -> CaliperError:
    """Produce a MissingPrerequisiteError from a real scoring attempt."""
    provider = FakeJudgeProviderPort(
        response=JudgeProviderResponse(score=0.9, reasoning="unreachable")
    )
    judge = Judge.create(model_version="claude-sonnet-4-5-20250929", provider=provider)
    attempt = _attempt_score(judge)
    assert attempt.error is not None
    return attempt.error


@when("the engineer examines the three errors", target_fixture="three_errors")
def examine_the_three_errors(
    provider_error: CaliperError,
    malformed_response_error: CaliperError,
    missing_prerequisite_error: CaliperError,
) -> list[CaliperError]:
    """Bundle the three independently-produced errors for comparison."""
    return [provider_error, malformed_response_error, missing_prerequisite_error]


@then(
    "each is classifiable under a different category without inspecting "
    "the error message text"
)
def each_error_has_a_different_category(three_errors: list[CaliperError]) -> None:
    """The three errors have pairwise-distinct types and category strings."""
    assert len({type(error) for error in three_errors}) == 3
    assert len({error.category for error in three_errors}) == 3


@then("the recovery guidance for each category is distinct from the others")
def recovery_guidance_is_distinct(three_errors: list[CaliperError]) -> None:
    """The three errors' recovery hints are pairwise distinct (content untested)."""
    assert len({error.recovery_hint for error in three_errors}) == 3
