"""Unit tests for ``ScoringResult``'s own construction guards (BIN-104).

Before this file, ``ScoringResult`` was exercised only indirectly: its
finiteness rule via ``tests/support/exception_contract_registry.py``'s
``nan_score``/``infinite_score`` hostile cases, and its happy path via
``tests/unit/measurement/test_judge_scoring.py`` (through ``Judge.score()``).
There was no test constructing ``ScoringResult`` directly to pin its own
validators -- the same gap ``BIN-104``'s "Related" note flagged for
``ModelVersion``, now closed here for its sibling value object.

Error assertions follow ADR-002/ADR-008: type + required ``context`` keys
only, never message text.
"""

from __future__ import annotations

import numpy as np
import pytest

from caliper.errors import InvalidParameterError
from caliper.measurement import ScoringResult
from tests.factories import ProvenanceFactory


def _result(score: object) -> ScoringResult:
    return ScoringResult(
        score=score,  # type: ignore[arg-type]
        reasoning="r",
        provenance=ProvenanceFactory(),
    )


# --- Numeric acceptance is unregressed (int and numpy scalars) -------------


@pytest.mark.parametrize(
    "numeric_value",
    [1, 1.0, np.float32(1.0), np.float64(1.0), np.int64(1)],
    ids=["python_int", "python_float", "np_float32", "np_float64", "np_int64"],
)
def test_accepts_score_across_numeric_types(numeric_value: object) -> None:
    """``int``, ``float``, and every numpy numeric scalar remain accepted.

    The ``mode="before"`` type guard added for BIN-104 must narrow only
    *which types* are rejected, never which of the previously-accepted
    types succeed -- pinned here by direct execution, not assumed.
    """
    # Act
    result = _result(numeric_value)

    # Assert
    assert isinstance(result.score, float)
    assert result.score == pytest.approx(1.0)


# --- Wrong-typed construction (BIN-104) -------------------------------------


@pytest.mark.parametrize(
    "wrong_typed_value", ["not a float", None, ["not", "a", "float"]]
)
def test_raises_invalid_parameter_error_for_wrong_typed_score(
    wrong_typed_value: object,
) -> None:
    """A non-numeric ``score`` is rejected before Pydantic's core coercion runs.

    Before BIN-104, ``ScoringResult(score="not a float")`` was rejected by
    Pydantic's own core coercion instead of Caliper's validation, and
    escaped as a raw ``pydantic_core.ValidationError``.
    """
    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        _result(wrong_typed_value)

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "score"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == wrong_typed_value
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""


# --- Non-finite score is still rejected (ADR-006 section 5, unchanged) -----


@pytest.mark.parametrize(
    "non_finite_value", [float("nan"), float("inf"), float("-inf")]
)
def test_raises_invalid_parameter_error_for_non_finite_score(
    non_finite_value: float,
) -> None:
    """NaN and +/-infinity are rejected by the existing finiteness validator.

    Not a BIN-104 regression target -- this pins that the new ``before``
    type guard runs *in addition to*, not *instead of*, the existing
    ``must_be_finite`` validator.
    """
    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        _result(non_finite_value)

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "score"
    assert error.context["kind"] == "invalid"
