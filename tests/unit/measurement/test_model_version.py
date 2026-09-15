"""Unit tests for ``ModelVersion``'s readback ergonomics (BIN-110 P3).

Before BIN-110, ``str(judge.model_version)`` (and f-string interpolation,
which uses the same protocol) produced Pydantic's default
``"ModelVersion(value='claude-sonnet-4-5')"`` -- a plain ``str`` went in at
``Judge.create(model_version=...)``, and reading it back needed ``.value``.
Per ``CLAUDE.md`` ("What goes in should come out"), ``__str__`` returns the
wrapped value directly.

``ModelVersion`` itself is NOT removed or restructured -- ADR-006 section 7
is load-bearing for provenance comparison (see
``tests/unit/measurement/test_provenance.py``). ``judge.model_version``
still *is* a ``ModelVersion``; only its ``str()``/log-line readout changes.

Creation and blank-content validation are already covered by
``tests/unit/measurement/test_judge.py`` (via ``Judge.create``) and this
type's own field validator -- the readback tests below are BIN-110's.

**Wrong-typed construction (BIN-104)** is pinned directly here, below the
readback tests -- previously this value object had no direct unit test
file at all (flagged as a gap by ``BIN-104``'s own "Related" note), so
``ModelVersion(value=123)`` was exercised only indirectly through
``tests/support/exception_contract_registry.py``'s hostile-case audit.
"""

from __future__ import annotations

import pytest

from drift_caliper.errors import InvalidParameterError
from drift_caliper.measurement import ModelVersion


def test_str_returns_the_wrapped_value_directly() -> None:
    """``str(ModelVersion(...))`` must return the raw string, not a wrapper repr."""
    # Arrange
    model_version = ModelVersion(value="claude-sonnet-4-5-20250929")

    # Act / Assert
    assert str(model_version) == "claude-sonnet-4-5-20250929"


def test_f_string_interpolation_uses_the_wrapped_value() -> None:
    """The common log-line case: an engineer interpolates the value directly."""
    # Arrange
    model_version = ModelVersion(value="claude-sonnet-4-5-20250929")

    # Act
    line = f"model={model_version}"

    # Assert
    assert line == "model=claude-sonnet-4-5-20250929"
    assert "ModelVersion(" not in line


def test_repr_still_identifies_the_wrapper_type() -> None:
    """``repr()`` stays a reconstructible, typed representation -- unlike ``str()``.

    BIN-110's readback complaint is about ``str()``/log-line readout, not
    ``repr()`` -- a REPL echo of a value object usefully shows its type
    (``CLAUDE.md``: "Every public type reprs usefully"). The nested-repr
    complaint (``Provenance`` showing ``ModelVersion(value=...)`` three
    levels deep) is ``Provenance``'s repr problem to fix, not
    ``ModelVersion``'s -- see ``tests/unit/measurement/test_provenance.py``.
    """
    model_version = ModelVersion(value="claude-sonnet-4-5-20250929")

    assert repr(model_version) == "ModelVersion(value='claude-sonnet-4-5-20250929')"


# --- Wrong-typed construction (BIN-104) -------------------------------------


@pytest.mark.parametrize("wrong_typed_value", [123, None, ["not", "a", "string"]])
def test_raises_invalid_parameter_error_for_wrong_typed_value(
    wrong_typed_value: object,
) -> None:
    """A wrong-typed ``value`` is rejected before Pydantic's core coercion runs.

    Before BIN-104, ``ModelVersion(value=123)`` was rejected by Pydantic's
    own core type coercion instead of Caliper's validation, and escaped as
    a raw ``pydantic_core.ValidationError`` -- no ``category``, no
    ``context`` to branch on (ADR-002). The ``mode="before"``
    ``reject_wrong_type`` validator closes that gap.
    """
    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        ModelVersion(value=wrong_typed_value)  # type: ignore[arg-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "model_version"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == wrong_typed_value
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""
