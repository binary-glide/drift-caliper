"""Shared type guards for baseline entry points' caller-supplied parameters (BIN-126).

Six call sites across ``cusum_fitting.py``, ``shewhart_fitting.py`` and
``baseline.py`` validated a wrong-typed argument by letting it reach code
that assumed the right type -- a bare arithmetic comparison, an attribute
access -- and leaked whatever Python (or beartype, on ``fit_ewma``; not
this module's concern, see that module's own docstring) happened to raise:
``AttributeError`` when a caller passed a plain string instead of a
``Baseline``, ``TypeError`` when a numeric-looking parameter arrived as a
string. Neither is a ``CaliperError``, so neither is catchable by category
or ``context`` (ADR-002) -- the same defect class as ``BIN-104``.

**The fix is behavioural, not nominal.** ``fit_cusum``, ``fit_shewhart`` and
``Baseline.check_sufficiency`` all accept ``int``, ``float``, and every
numpy scalar type (``np.float32``, ``np.float64``, ``np.int64``, ...) for
their numeric parameters today, and must keep doing so -- an
``isinstance(x, float)`` guard would silently start rejecting all of them
(see ``tests/unit/test_public_type_guards.py``'s "Numeric acceptance"
section, which pins this as a regression). ``numbers.Real`` is what numpy's
scalar types actually register as (verified directly, not assumed -- numpy
registers its scalar hierarchy with the :mod:`numbers` ABCs), so it is the
duck-typed test used here rather than a fixed tuple of concrete types this
module would have to keep in sync with numpy's own type additions.

**``bool`` is excluded explicitly, and checked before the ``numbers.Real``
test.** ``bool`` subclasses ``int``, so ``isinstance(True, numbers.Real)``
is ``True`` -- a ``numbers.Real`` check alone would silently accept a
boolean anywhere a numeric parameter is expected, which is a real, ratified
defect (not pedantry): ``fit_shewhart(baseline, target_arl=True)`` fits an
ARL0 of 1 -- a chart that alarms on nearly every in-control observation. See
``Projects/caliper/pending-tickets/arl0-of-1-alarms-on-everything.md`` in
the vault.

Deliberately not shared with ``caliper.measurement.domain.judge``'s
``agent_output`` type guard -- ``measurement`` and ``baseline`` are separate
bounded contexts (``CLAUDE.md``'s "Module layout" note), and that guard is a
plain string-type check with no numeric-acceptance question to share a
pattern over.
"""

from __future__ import annotations

import numbers
from typing import TypeVar

from caliper.errors import InvalidParameterError

T = TypeVar("T")


def require_real_number(value: object, *, parameter: str, constraint: str) -> float:
    """Validate that ``value`` is a real number, and narrow it to ``float``.

    Accepts anything that duck-types as a real number -- ``int``, ``float``,
    and every numpy scalar type that registers with :class:`numbers.Real`
    (see module docstring) -- and rejects everything else, ``bool`` included.

    Parameters
    ----------
    value
        The caller-supplied value to validate.
    parameter
        The name of the parameter being validated, for ``context``.
    constraint
        A human-readable description of what a *valid* value must satisfy
        once it is a real number (this function's own constraint is
        "must be a real number, not a bool" -- range/finiteness checks
        beyond that are the caller's responsibility, applied to the
        ``float`` this function returns).

    Returns
    -------
    float
        ``value`` narrowed to a plain ``float``.

    Raises
    ------
    InvalidParameterError
        ``value`` is a ``bool``, or is not a ``numbers.Real``.
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
                f"Pass a real number for {parameter} (an int, a float, or a "
                "numpy numeric scalar) -- not a bool. True/False satisfy "
                "Python's own int-subclassing rule silently, but a boolean "
                "is never a meaningful value here."
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
    return float(value)


def require_type(
    value: T, expected_type: type[T], *, parameter: str, type_name: str
) -> T:
    """Validate that ``value`` is an instance of ``expected_type``.

    Used for parameters whose validity is about *identity* rather than a
    numeric range -- e.g. ``fit_cusum``/``fit_shewhart``'s ``baseline``
    argument, which must be an actual ``Baseline`` rather than anything
    that merely happens to support the attributes those functions go on to
    use.

    Parameters
    ----------
    value
        The caller-supplied value to validate.
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


__all__ = ["require_real_number", "require_type"]
