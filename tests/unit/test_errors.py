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
    assert error_type.category == category


@pytest.mark.parametrize(("error_type", "category"), LIBRARY_CATEGORIES)
def test_every_library_error_is_caught_by_the_base_type(
    error_type: type[CaliperError], category: str
) -> None:
    with pytest.raises(CaliperError) as exc_info:
        raise error_type("boom", context={}, recovery_hint="try something else")

    assert exc_info.value.category == category


def test_category_strings_are_unique_across_the_taxonomy() -> None:
    categories = [category for _, category in LIBRARY_CATEGORIES]

    assert len(set(categories)) == len(categories)


def test_context_and_recovery_hint_are_carried_verbatim() -> None:
    context = {"parameter": "model_version", "kind": "missing"}

    error = InvalidParameterError(
        "boom", context=context, recovery_hint="pin a model version"
    )

    assert error.context == context
    assert error.recovery_hint == "pin a model version"


def test_an_extension_may_add_its_own_category() -> None:
    # ADR-002 section 6: the taxonomy is semi-open. Third-party code extends
    # it by subclassing, and `except CaliperError` still catches the result.
    class JudgeTimeoutError(CaliperError):
        category = "judge_timeout"

    with pytest.raises(CaliperError) as exc_info:
        raise JudgeTimeoutError("boom", context={}, recovery_hint="raise the timeout")

    assert exc_info.value.category == "judge_timeout"


def test_a_subclass_that_omits_its_category_fails_at_definition_time() -> None:
    with pytest.raises(TypeError):

        class UncategorisedError(CaliperError):
            pass
