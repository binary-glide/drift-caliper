"""Unit tests for Judge creation (BIN-57).

Pins the seven acceptance scenarios in
``tests/bdd/features/measurement/judge-adapter-pinned-model-version.feature``
at the unit level. Error assertions follow ADR-002: type + required
``context`` keys only -- never message text.

Assumption (see the BIN-57 backend-test-writer Session Summary): the
``model_version`` parameter on ``Judge.create`` is optional-in-signature
with required-by-validation semantics (``str | None = None``), following
the same pattern ADR-004 settled for ``target_arl`` on the fitting API.
This is what makes the "model version not provided" scenario reachable as
``InvalidParameterError(kind="missing")`` rather than Python's
``TypeError``.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from caliper.errors import InvalidParameterError
from caliper.measurement import Judge, ModelVersion


def test_creates_judge_and_reports_model_version_when_pinned_version_provided() -> None:
    """SC1: a judge created with a pinned model version reports it back."""
    model_version = "claude-sonnet-4-5-20250929"

    judge = Judge.create(model_version=model_version)

    assert judge.model_version.value == model_version


def test_raises_invalid_parameter_error_when_model_version_not_provided() -> None:
    """SC2: omitting the model version fails as a classifiable invalid parameter."""
    with pytest.raises(InvalidParameterError) as exc_info:
        Judge.create()

    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "model_version"
    assert error.context["kind"] == "missing"
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


def test_raises_invalid_parameter_error_when_model_version_is_empty_string() -> None:
    """SC3: an empty-string model version fails as a classifiable invalid parameter."""
    with pytest.raises(InvalidParameterError) as exc_info:
        Judge.create(model_version="")

    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "model_version"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == ""
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


def test_raises_invalid_parameter_error_when_model_version_is_whitespace_only() -> None:
    """SC4: a whitespace-only model version fails as a classifiable invalid param."""
    whitespace_only = "   \t  "

    with pytest.raises(InvalidParameterError) as exc_info:
        Judge.create(model_version=whitespace_only)

    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "model_version"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == whitespace_only
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


def test_missing_and_invalid_model_version_share_type_but_differ_by_kind() -> None:
    """SC2 vs SC3: distinguishable by ``kind`` without a separate exception type."""
    with pytest.raises(InvalidParameterError) as missing_info:
        Judge.create()
    with pytest.raises(InvalidParameterError) as invalid_info:
        Judge.create(model_version="")

    assert type(missing_info.value) is type(invalid_info.value)
    assert missing_info.value.context["kind"] == "missing"
    assert invalid_info.value.context["kind"] == "invalid"


def test_preserves_model_version_with_mixed_case_and_special_characters() -> None:
    """SC5: the reported version matches the original string exactly."""
    model_version = "Claude-3.5_Sonnet@2025-06-20+beta"

    judge = Judge.create(model_version=model_version)

    assert judge.model_version.value == model_version


def test_rejects_attempt_to_change_model_version_after_creation() -> None:
    """SC6: the model version is immutable; the judge keeps reporting the original."""
    original_version = "claude-sonnet-4-5-20250929"
    judge = Judge.create(model_version=original_version)

    with pytest.raises(ValidationError):
        judge.model_version = ModelVersion(  # ty: ignore[invalid-assignment]
            value="claude-opus-4-20250514"
        )

    assert judge.model_version.value == original_version


def test_accepts_and_preserves_model_version_with_surrounding_whitespace() -> None:
    """SC7: surrounding whitespace is accepted and preserved, not trimmed."""
    padded_version = "  claude-sonnet-4-5-20250929  "

    judge = Judge.create(model_version=padded_version)

    assert judge.model_version.value == padded_version
    assert judge.model_version.value != padded_version.strip()


@given(st.text(min_size=1).filter(lambda s: s.strip() != ""))
def test_preserves_any_non_blank_model_version_character_for_character(
    model_version: str,
) -> None:
    """Property: any string with non-whitespace content round-trips exactly."""
    judge = Judge.create(model_version=model_version)

    assert judge.model_version.value == model_version
