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
being imported from ``drift_caliper.baseline.domain.parameter_guards``** (which
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

- ``require_real_number`` **used to genuinely differ** from
  ``parameter_guards``' version -- this one *accepted* ``bool``, that one
  *rejected* it. **BIN-132 closed that gap**: a boolean ``score`` silently
  became ``1.0``/``0.0`` and entered a baseline as Bernoulli data, which is
  fitted with normal-theory limits that do not hold for it -- the same
  class of defect ``BIN-131`` found on the fitting side for a boolean
  ``target_arl``. Both helpers now reject ``bool`` before the
  ``numbers.Real`` check (checked first deliberately: ``bool`` subclasses
  ``int``, so ``isinstance(True, numbers.Real)`` is ``True`` and a
  ``numbers.Real``-only check would silently accept it). What still
  differs is shape, not the bool rule: this one returns the value
  *unchanged* (Pydantic's own core coercion still narrows it afterwards);
  ``parameter_guards.require_real_number`` narrows to ``float`` itself,
  because nothing downstream of a fitting parameter performs that
  coercion. That shape difference, plus the bounded-context boundary
  argument above, is why this remains its own function rather than an
  import.
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

from drift_caliper.errors import InvalidParameterError

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
    and every numpy scalar type that registers with :class:`numbers.Real` --
    and rejects everything else, ``bool`` included (BIN-132). Returned
    unchanged rather than narrowed to ``float`` -- Pydantic's own core
    coercion (which already accepts every one of these types, verified by
    direct execution) still runs afterwards and performs that narrowing.

    **``bool`` is excluded explicitly, and checked before the
    ``numbers.Real`` test** -- mirrors
    ``drift_caliper.baseline.domain.parameter_guards.require_real_number`` (see
    that function's docstring for why the check order matters: ``bool``
    subclasses ``int``, so ``isinstance(True, numbers.Real)`` is ``True``,
    and a ``numbers.Real``-only check would silently accept it). Before
    BIN-132 this function deliberately accepted ``bool`` -- see the module
    docstring's "That justification is not equally strong" section for why
    that was reversed: ``ScoringResult(score=True)`` silently became
    ``1.0``, and a pass/fail judge's output entering a baseline as ones and
    zeros gets fitted with normal-theory control limits that do not hold
    for Bernoulli data.

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
        ``value`` is a ``bool``, or is not a :class:`numbers.Real`.
    """
    if isinstance(value, bool):
        raise InvalidParameterError(
            f"{parameter} must be a real number, not a bool",
            context={
                "parameter": parameter,
                "constraint": constraint,
                "kind": "invalid",
                "provided": value,
            },
            recovery_hint=(
                "A bool score silently becomes 1.0/0.0 and, once enough of "
                "them accumulate in a baseline, gets fitted with "
                "normal-theory control limits that do not hold for "
                "Bernoulli data -- Caliper will not do that silently. "
                "Aggregate before scoring instead: score each "
                "NON-OVERLAPPING batch of judgements with that batch's pass "
                "rate (e.g. one score per 20 judged outputs). Use "
                "non-overlapping batches, not a rolling window -- "
                "consecutive rolling values share almost all their "
                "observations, and the moving-range sigma Caliper fits from "
                "assumes consecutive observations are independent, so a "
                "rolling pass-rate reintroduces a variant of the problem "
                "this rejection exists to prevent. Check the normal "
                "approximation holds for YOUR pass rate: it needs both "
                "n*p > 5 and n*(1-p) > 5, so a batch of 20 is only adequate "
                "for pass rates roughly between 0.25 and 0.75 -- a "
                "well-behaved agent passing 90% of the time needs a batch "
                "of about 50, not 20. Cost, honestly: ADR-005's "
                "100-observation Phase I minimum then means batch_size * "
                "100 underlying judgements before a baseline exists (2,000 "
                "at batch 20; 5,000 at batch 50), not 100. If you need "
                "proper Bernoulli/p-chart support instead of this "
                "workaround, track BIN-133."
            ),
        )
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

    Used for :class:`~drift_caliper.measurement.domain.provenance.Provenance`'s
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
