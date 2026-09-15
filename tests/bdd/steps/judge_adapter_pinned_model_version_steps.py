"""Step definitions for BIN-57: judge adapter with required pinned model version.

Binds to
``tests/bdd/features/measurement/judge-adapter-pinned-model-version.feature``
via ``tests/bdd/test_judge_adapter_pinned_model_version.py``. Error
assertions follow ADR-002: type + required ``context`` keys only -- never
message text.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from pytest_bdd import given, then, when

from drift_caliper.errors import CaliperError, InvalidParameterError
from drift_caliper.measurement import Judge, ModelVersion


@dataclass
class CreationAttempt:
    """Outcome of an attempted judge creation."""

    judge: Judge | None
    error: CaliperError | None


@dataclass
class MutationAttempt:
    """Outcome of an attempted post-creation model version change."""

    judge: Judge
    error: Exception | None


# --- Scenario: happy path --------------------------------------------------


@given(
    "the engineer has identified a model version string for their chosen provider",
    target_fixture="model_version_input",
)
def identified_model_version() -> str:
    """A realistic, valid model version string."""
    return "claude-sonnet-4-5-20250929"


@when(
    "they create a judge specifying that model version",
    target_fixture="created_judge",
)
def create_judge_with_version(model_version_input: str) -> Judge:
    """Create a judge with the identified model version."""
    return Judge.create(model_version=model_version_input)


@then("the judge should be created successfully")
def judge_created_successfully(created_judge: Judge) -> None:
    """The creation call returned a Judge instance."""
    assert isinstance(created_judge, Judge)


@then("the judge should report the specified model version when inspected")
def judge_reports_specified_model_version(
    created_judge: Judge, model_version_input: str
) -> None:
    """The judge's model version matches what was specified."""
    assert created_judge.model_version.value == model_version_input


# --- Scenarios: missing / empty / whitespace-only model version -----------


@given(
    "the engineer has not provided a model version",
    target_fixture="model_version_input",
)
def missing_model_version() -> None:
    """Sentinel: no model version is supplied at all."""
    return None


@given(
    "the engineer provides an empty string where a model version is expected",
    target_fixture="model_version_input",
)
def empty_string_model_version() -> str:
    """An empty string, which carries no pinning guarantee."""
    return ""


@given(
    "the engineer provides a string containing only whitespace as the model version",
    target_fixture="model_version_input",
)
def whitespace_only_model_version() -> str:
    """A whitespace-only string, which carries no pinning guarantee."""
    return "   \t  "


@when("they attempt to create a judge", target_fixture="creation_attempt")
def attempt_create_judge(model_version_input: str | None) -> CreationAttempt:
    """Attempt judge creation, capturing success or a Caliper error."""
    try:
        judge = (
            Judge.create()
            if model_version_input is None
            else Judge.create(model_version=model_version_input)
        )
    except CaliperError as exc:
        return CreationAttempt(judge=None, error=exc)
    return CreationAttempt(judge=judge, error=None)


@then("the creation fails with an error classifiable as an invalid parameter")
def creation_fails_as_invalid_parameter(creation_attempt: CreationAttempt) -> None:
    """No judge was created; the error is classifiable as invalid_parameter."""
    assert creation_attempt.judge is None
    assert isinstance(creation_attempt.error, InvalidParameterError)
    assert creation_attempt.error.category == "invalid_parameter"


@then("the error identifies that the model version parameter is required")
def error_identifies_model_version_required(
    creation_attempt: CreationAttempt,
) -> None:
    """The error's context names the missing model_version parameter."""
    error = creation_attempt.error
    assert isinstance(error, InvalidParameterError)
    assert error.context["parameter"] == "model_version"
    assert error.context["kind"] == "missing"


@then("the error identifies which parameter is invalid and what is required")
def error_identifies_which_parameter_is_invalid(
    creation_attempt: CreationAttempt,
) -> None:
    """The error's context names the invalid model_version parameter."""
    error = creation_attempt.error
    assert isinstance(error, InvalidParameterError)
    assert error.context["parameter"] == "model_version"
    assert error.context["kind"] == "invalid"
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Scenarios: preservation ------------------------------------------------


@given(
    "the engineer creates a judge with a model version containing mixed "
    "case and special characters",
    target_fixture="judge_and_original_version",
)
def create_judge_with_mixed_case_version() -> tuple[Judge, str]:
    """Create a judge with a mixed-case, special-character model version."""
    raw_version = "Claude-3.5_Sonnet@2025-06-20+beta"
    return Judge.create(model_version=raw_version), raw_version


@given(
    "the engineer creates a judge with a model version that has leading "
    "and trailing spaces",
    target_fixture="judge_and_original_version",
)
def create_judge_with_padded_version() -> tuple[Judge, str]:
    """Create a judge with a model version padded by whitespace."""
    raw_version = "  claude-sonnet-4-5-20250929  "
    return Judge.create(model_version=raw_version), raw_version


@when(
    "they inspect the judge's model version",
    target_fixture="inspected_model_version",
)
def inspect_model_version(judge_and_original_version: tuple[Judge, str]) -> str:
    """Read back the judge's model version."""
    judge, _ = judge_and_original_version
    return judge.model_version.value


@then("the reported version should match the original string character for character")
def reported_version_matches_original(
    inspected_model_version: str,
    judge_and_original_version: tuple[Judge, str],
) -> None:
    """The reported version is byte-for-byte identical to the original."""
    _, raw_version = judge_and_original_version
    assert inspected_model_version == raw_version


@then("the reported version should include the surrounding spaces exactly as provided")
def reported_version_includes_surrounding_spaces(
    inspected_model_version: str,
    judge_and_original_version: tuple[Judge, str],
) -> None:
    """Surrounding whitespace is preserved, not trimmed."""
    _, raw_version = judge_and_original_version
    assert inspected_model_version == raw_version
    assert inspected_model_version != raw_version.strip()


# --- Scenario: immutability --------------------------------------------------


@given(
    "the engineer has created a judge with a pinned model version",
    target_fixture="judge_before_mutation_attempt",
)
def create_judge_for_mutation_attempt() -> tuple[Judge, str]:
    """Create a judge whose model version will be mutated in the When step."""
    raw_version = "claude-sonnet-4-5-20250929"
    return Judge.create(model_version=raw_version), raw_version


@when(
    "they attempt to change the judge's model version",
    target_fixture="mutation_attempt",
)
def attempt_to_change_model_version(
    judge_before_mutation_attempt: tuple[Judge, str],
) -> MutationAttempt:
    """Attempt to reassign the judge's model version after creation."""
    judge, _ = judge_before_mutation_attempt
    try:
        judge.model_version = ModelVersion(  # ty: ignore[invalid-assignment]
            value="claude-opus-4-20250514"
        )
    except (AttributeError, ValidationError) as exc:
        return MutationAttempt(judge=judge, error=exc)
    return MutationAttempt(judge=judge, error=None)


@then("the change should be rejected")
def change_should_be_rejected(mutation_attempt: MutationAttempt) -> None:
    """The mutation attempt raised, and did not silently succeed."""
    assert mutation_attempt.error is not None
    assert isinstance(mutation_attempt.error, (AttributeError, ValidationError))


@then("the judge should continue to report its original model version")
def judge_reports_original_version(
    mutation_attempt: MutationAttempt,
    judge_before_mutation_attempt: tuple[Judge, str],
) -> None:
    """The judge's model version is unchanged after the rejected mutation."""
    _, raw_version = judge_before_mutation_attempt
    assert mutation_attempt.judge.model_version.value == raw_version
