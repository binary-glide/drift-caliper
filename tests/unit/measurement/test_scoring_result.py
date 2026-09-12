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


# --- bool score is rejected (BIN-132) ---------------------------------------
#
# ``ScoringResult(score=True)`` used to silently succeed with `score == 1.0`
# -- `bool` subclasses `int`, so `isinstance(True, numbers.Real)` is `True`,
# and the BIN-104 type guard's `numbers.Real` check alone accepted it. A
# pass/fail judge's output then enters a baseline as ones and zeros and gets
# fitted with normal-theory control limits, which do not hold for Bernoulli
# data. The declaration is rejected, not any particular value: a genuinely
# continuous process can legitimately produce 0.0 and 1.0 (see the test
# below), so this must reject `bool` specifically, never a heuristic over
# the values a baseline happens to contain.


@pytest.mark.parametrize("bool_value", [True, False])
def test_raises_invalid_parameter_error_for_bool_score(bool_value: bool) -> None:
    """A ``bool`` score is rejected outright -- it is a caller's declaration
    of intent (pass/fail), not a continuous measurement, regardless of
    which of the two bool values was passed.
    """
    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        _result(bool_value)

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "score"
    assert error.context["kind"] == "invalid"
    assert error.context["provided"] == bool_value
    assert isinstance(error.context["constraint"], str)
    assert error.context["constraint"] != ""
    # The recovery_hint is the whole point (BIN-132): it must redirect to a
    # legitimate alternative, not just refuse. Not asserted on content
    # (ADR-002/ADR-008 -- recovery_hint is human-facing and untested for
    # content), only that one exists.
    assert error.recovery_hint != ""


def test_float_zero_and_one_are_not_rejected_as_if_they_were_bool() -> None:
    """A continuous process legitimately producing exactly 0.0 or 1.0 must
    not be caught by the bool exclusion -- the declaration (``bool``) is
    rejected, not the values (BIN-132: no heuristic inspects a baseline for
    "looks binary").
    """
    # Act
    zero = _result(0.0)
    one = _result(1.0)

    # Assert
    assert zero.score == 0.0
    assert isinstance(zero.score, float)
    assert one.score == 1.0
    assert isinstance(one.score, float)
