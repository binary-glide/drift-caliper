"""Shared ``mode="before"`` type guards for the measurement value objects (BIN-104).

Pydantic's core type coercion runs *before* a ``@field_validator`` declared
with the default ``mode="after"``, so a wrong-*typed* constructor argument
(``ModelVersion(value=123)``, ``ScoringResult(score="not a float")``,
``Provenance(model_version="not a ModelVersion")``) never reached any of
this codebase's own validation -- it was rejected by Pydantic's core schema
first, and escaped as a raw ``pydantic_core.ValidationError`` rather than a
classifiable ``CaliperError``. A ``mode="before"`` validator runs ahead of
that core coercion, so the raw input can be inspected while it is still
whatever the caller actually passed.

**This only works because ``CaliperError`` does not subclass ``ValueError``**
(verified against pydantic 2.13.5, and pinned by a dedicated ``BIN-121``
test -- see ``tests/unit/test_errors.py``). Pydantic re-wraps ``ValueError``/
``AssertionError`` raised inside any field validator into its own
``ValidationError``; every other exception type propagates unwrapped. Raise
``InvalidParameterError`` directly here, never ``ValueError``, or this
module silently stops working.

**Why these three helpers live here, in ``measurement/domain/``, rather than
being imported from ``caliper.baseline.domain.parameter_guards``** (which
already has near-identical ``require_real_number``/``require_type``
functions for the same defect class in a different bounded context):
``measurement`` and ``baseline`` are separate bounded contexts (see
``CLAUDE.md``'s "Module layout" note, and ``judge.py``'s own docstring
making the identical call for ``agent_output``'s type guard). A shared
helper *within* one bounded context's four value objects
(``ModelVersion``, ``ScoringCriteria``, ``ScoringResult``, ``Provenance``)
is the DRY case this module exists to serve; a cross-context import
between ``measurement`` and ``baseline`` would be coupling two contexts
that otherwise have no dependency on each other.
``code-reviewer`` reached the same conclusion for ``Judge.score``'s
``agent_output`` guard on ``BIN-126`` -- this module applies that ruling
consistently rather than revisiting it per-ticket.

⚠️ **That justification is not equally strong for all three helpers, and
saying so is better than letting a blanket claim cover a weak case**
(raised by ``code-reviewer`` on ``BIN-104``, which diffed them):

- ``require_real_number`` **genuinely differs** from ``parameter_guards``'
  version. This one *accepts* ``bool`` and returns the value unchanged;
  that one *rejects* ``bool`` and narrows to ``float``, because a boolean
  ``target_arl`` silently means an ARL0 of 1 (``BIN-131``). Two contexts,
  two real rules -- duplication is correct here, not incidental.
- ``require_str`` has no counterpart at all.
- ``require_instance`` **is byte-identical** to ``parameter_guards.require_type``
  apart from its name and one annotation (``object`` vs a ``TypeVar``).
  Nothing about the bounded-context boundary makes it *different*; it is
  duplicated because sharing it would mean importing across contexts for
  three lines. That is a deliberate trade, not a principled distinction,
  and it is the one to revisit first if a third context ever needs it.
"""

from __future__ import annotations

import numbers
from typing import TypeVar

from caliper.errors import InvalidParameterError

T = TypeVar("T")


def require_str(value: object, *, parameter: str, constraint: str) -> str:
    """Reject a non-``str`` value before Pydantic's core coercion runs.

    Parameters
    ----------
    value
        The raw, caller-supplied value -- not yet coerced by Pydantic.
    parameter
        The name of the parameter being validated, for ``context``.
    constraint
        A human-readable description of what a valid value must satisfy
        (the same constraint string the field's own blank-check validator
        already reports, so both failure modes of the same parameter agree
        on what "valid" means).

    Returns
    -------
    str
        ``value``, unchanged, narrowed to ``str``.

    Raises
    ------
    InvalidParameterError
        ``value`` is not a ``str``.
    """
    if not isinstance(value, str):
        raise InvalidParameterError(
            f"{parameter} must be a string",
            context={
                "parameter": parameter,
                "constraint": constraint,
                "kind": "invalid",
                "provided": value,
            },
            recovery_hint=(
                f"Pass a string for {parameter}, not a {type(value).__name__}."
            ),
        )
    return value


def require_real_number(value: object, *, parameter: str, constraint: str) -> object:
    """Reject a value that is not a real number before Pydantic's core coercion runs.

    Accepts anything that duck-types as a real number -- ``int``, ``float``,
    ``bool`` (an ``int`` subclass; not excluded here, unlike
    ``caliper.baseline.domain.parameter_guards.require_real_number`` -- no
    scenario or business rule in this bounded context treats a boolean
    score as a distinct hazard the way an ARL0 target does), and every
    numpy scalar type that registers with :class:`numbers.Real`. Returned
    unchanged rather than narrowed to ``float`` -- Pydantic's own core
    coercion (which already accepts every one of these types, verified by
    direct execution) still runs afterwards and performs that narrowing.

    Parameters
    ----------
    value
        The raw, caller-supplied value.
    parameter
        The name of the parameter being validated, for ``context``.
    constraint
        A human-readable description of what a valid value must satisfy.

    Returns
    -------
    object
        ``value``, unchanged.

    Raises
    ------
    InvalidParameterError
        ``value`` is not a :class:`numbers.Real`.
    """
    if not isinstance(value, numbers.Real):
        raise InvalidParameterError(
            f"{parameter} must be a real number",
            context={
                "parameter": parameter,
                "constraint": constraint,
                "kind": "invalid",
                "provided": value,
            },
            recovery_hint=(
                f"Pass a real number for {parameter} -- an int, a float, or "
                "a numpy numeric scalar."
            ),
        )
    return value


def require_instance(
    value: object, expected_type: type[T], *, parameter: str, type_name: str
) -> T:
    """Reject a value that is not an instance of ``expected_type``.

    Used for :class:`~caliper.measurement.domain.provenance.Provenance`'s
    two fields, whose validity is about *identity* (an actual
    ``ModelVersion``/``ScoringCriteria`` instance) rather than a string or
    numeric constraint.

    Parameters
    ----------
    value
        The raw, caller-supplied value.
    expected_type
        The type ``value`` must be an instance of.
    parameter
        The name of the parameter being validated, for ``context``.
    type_name
        A human-readable name for ``expected_type``, for ``context`` and
        the recovery hint.

    Returns
    -------
    T
        ``value``, unchanged, narrowed to ``expected_type``.

    Raises
    ------
    InvalidParameterError
        ``value`` is not an instance of ``expected_type``.
    """
    if not isinstance(value, expected_type):
        raise InvalidParameterError(
            f"{parameter} must be a {type_name}",
            context={
                "parameter": parameter,
                "constraint": f"must be an instance of {type_name}",
                "kind": "invalid",
                "provided": value,
            },
            recovery_hint=f"Pass a {type_name} for {parameter}.",
        )
    return value


__all__ = ["require_instance", "require_real_number", "require_str"]
