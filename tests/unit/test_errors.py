"""Tests for the exception taxonomy itself (ADR-002).

The nine leaf types are exercised story by story as each category becomes
reachable. What is pinned here is the taxonomy's own contract: the category
strings are stable identifiers consumers may branch on, the base type
catches everything, and a subclass cannot silently omit its category.
"""

from __future__ import annotations

import pytest

from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidObservationError,
    InvalidParameterError,
    JudgeRefusalError,
    MalformedResponseError,
    MissingPrerequisiteError,
    ProvenanceMismatchError,
    ProviderError,
)

# ADR-002's nine categories. Removing an entry is a breaking change for
# consumers branching on `category`; adding one is a minor-version change.
LIBRARY_CATEGORIES: list[tuple[type[CaliperError], str]] = [
    (InvalidParameterError, "invalid_parameter"),
    (MissingPrerequisiteError, "missing_prerequisite"),
    (ProviderError, "provider_failure"),
    (MalformedResponseError, "malformed_response"),
    (JudgeRefusalError, "judge_refusal"),
    (ProvenanceMismatchError, "provenance_mismatch"),
    (InvalidObservationError, "invalid_observation"),
    (InsufficientBaselineError, "insufficient_baseline"),
    (DegenerateBaselineError, "degenerate_baseline"),
]


@pytest.mark.parametrize(("error_type", "category"), LIBRARY_CATEGORIES)
def test_each_library_error_declares_its_stable_category(
    error_type: type[CaliperError], category: str
) -> None:
    # Arrange: error_type and category come from the parametrize table above.
    # Act
    declared_category = error_type.category

    # Assert
    assert declared_category == category


@pytest.mark.parametrize(("error_type", "category"), LIBRARY_CATEGORIES)
def test_every_library_error_is_caught_by_the_base_type(
    error_type: type[CaliperError], category: str
) -> None:
    # Act
    with pytest.raises(CaliperError) as exc_info:
        raise error_type("boom", context={}, recovery_hint="try something else")

    # Assert
    assert exc_info.value.category == category


def test_category_strings_are_unique_across_the_taxonomy() -> None:
    # Arrange
    categories = [category for _, category in LIBRARY_CATEGORIES]

    # Assert
    assert len(set(categories)) == len(categories)


def test_context_and_recovery_hint_are_carried_verbatim() -> None:
    # Arrange
    context = {"parameter": "model_version", "kind": "missing"}

    # Act
    error = InvalidParameterError(
        "boom", context=context, recovery_hint="pin a model version"
    )

    # Assert
    assert error.context == context
    assert error.recovery_hint == "pin a model version"


def test_an_extension_may_add_its_own_category() -> None:
    # Arrange: ADR-002 section 6 -- the taxonomy is semi-open. Third-party
    # code extends it by subclassing, and `except CaliperError` still
    # catches the result.
    class JudgeTimeoutError(CaliperError):
        category = "judge_timeout"

    # Act
    with pytest.raises(CaliperError) as exc_info:
        raise JudgeTimeoutError("boom", context={}, recovery_hint="raise the timeout")

    # Assert
    assert exc_info.value.category == "judge_timeout"


def test_a_subclass_that_omits_its_category_fails_at_definition_time() -> None:
    # Act/Assert: the class *definition* below is the action under test --
    # `__init_subclass__` must raise before the class body finishes, so
    # there is no separate instance to act on afterwards.
    with pytest.raises(TypeError):

        class UncategorisedError(CaliperError):
            pass


# --- The Pydantic interaction that five field validators depend on ---------
#
# Pydantic v2 converts a `ValueError` or `AssertionError` raised inside a
# `@field_validator` into a `ValidationError`. Any other exception type
# propagates to the caller unchanged.
#
# Five validators rely on that second branch to satisfy ADR-002 --
# `ScoringResult.must_be_finite`, `ModelVersion`'s and `ScoringCriteria`'s
# blank-text checks, and the `sigma_estimate` invariant on all three
# `Fitted*` types (BIN-119). Each raises a `CaliperError`, and each reaches
# the caller as that type *only because* `CaliperError` does not inherit
# from `ValueError`.
#
# Nothing pinned that until now. Rebasing `CaliperError` onto `ValueError`
# is a plausible-looking tidy-up -- it reads as "these are value errors,
# after all" -- and it would silently turn every one of those validators
# into a `ValidationError` leak from the public API. That is BIN-104
# exactly, reintroduced by a change no reviewer would flag as risky.
# Raised by code-reviewer on BIN-119, 2026-09-11.


@pytest.mark.parametrize(("error_type", "category"), LIBRARY_CATEGORIES)
def test_library_errors_are_not_value_errors(
    error_type: type[CaliperError], category: str
) -> None:
    """No library error inherits from a type Pydantic re-wraps."""
    assert not issubclass(error_type, ValueError)
    assert not issubclass(error_type, AssertionError)


def test_a_caliper_error_raised_inside_a_field_validator_is_not_rewrapped() -> None:
    """A validator's `CaliperError` reaches the caller as itself.

    The end-to-end form of the rule above, asserted against Pydantic itself
    rather than against our reading of its documentation -- so the test
    fails if Pydantic's wrapping behaviour ever changes, not only if
    `CaliperError`'s bases do.
    """
    from pydantic import BaseModel, field_validator
    from pydantic import ValidationError as PydanticValidationError

    class Guarded(BaseModel):
        value: float

        @field_validator("value")
        @classmethod
        def must_be_positive(cls, v: float) -> float:
            if v <= 0:
                raise InvalidParameterError(
                    "value must be positive",
                    context={"parameter": "value", "kind": "invalid", "provided": v},
                    recovery_hint="Pass a positive value.",
                )
            return v

    with pytest.raises(InvalidParameterError) as exc_info:
        Guarded(value=-1.0)
    assert exc_info.value.category == "invalid_parameter"
    assert not isinstance(exc_info.value, PydanticValidationError)
