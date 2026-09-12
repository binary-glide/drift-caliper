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

import math
import numbers
from typing import TypeVar

from caliper.baseline.domain.fitting_advisory import FittingAdvisory
from caliper.errors import InvalidParameterError

T = TypeVar("T")

# --- ADR-011: minimum meaningful target_arl -----------------------------------
#
# Three tiers, shared by all three fit_* functions -- ADR-011 is explicit
# that this is one policy applied uniformly across charts, not a per-chart
# choice, so the tiering itself lives here rather than being re-derived
# three times (the BIN-124 lesson: identical logic triplicated across
# ewma_fitting.py/cusum_fitting.py/shewhart_fitting.py drifts silently the
# next time either threshold needs to change).
#
#   target_arl < MIN_TARGET_ARL          -> InvalidParameterError (refused)
#   MIN_TARGET_ARL <= target_arl < VERIFIED_ARL_FLOOR -> fits, FittingAdvisory attached
#   target_arl >= VERIFIED_ARL_FLOOR     -> fits, no advisory
#
# Distinct from ewma_fitting.MIN_COHERENT_ARL (1.0) -- that is the smallest
# *arithmetically meaningful* ARL0 (E[N] >= 1, a mathematical fact about any
# stopping time). MIN_TARGET_ARL is the smallest ARL0 the field's own
# literature *tabulates at all*, a different and much stronger claim. See
# ADR-011's "Four candidate floors, and what each actually claims" table --
# conflating the two was the exact defect ADR-011 exists to fix (a
# mathematically coherent but practically meaningless target_arl=1.0 fit
# "successfully" and alarmed on nearly every observation).
MIN_TARGET_ARL = 100.0
"""ADR-011 hard floor, refused below. Lucas & Saccucci (1990), Technometrics
32(1):1-12, section "Tables": "Lucas and Saccucci (1987) also provided
tables for in-control ARL's of 100, 300, 1,000, 2,000, and 5,000." 100 is
the lowest in-control ARL0 the canonical EWMA reference tabulates at all --
below it, the field has nothing to calibrate against, so Caliper has no
basis to claim the number it would report."""

VERIFIED_ARL_FLOOR = 370.0
"""ADR-011 advisory line. Every published-table oracle this repository
verifies a fitted chart against (Lucas & Saccucci 1990 Table 3 for EWMA;
Montgomery's (2013) worked Siegmund-approximation example for CUSUM) sits
at ARL0 = 370-500. Below 370 Caliper has never checked its own calibration
against a published value -- the maths is identical, only the verification
coverage differs, which is why this is a disclosure, not a refusal."""

_TARGET_ARL_BELOW_VERIFIED_RANGE_KIND = "target_arl_below_verified_range"


def classify_target_arl(
    numeric_target_arl: float,
    *,
    max_target_arl: float,
    parameter: str = "target_arl",
) -> FittingAdvisory | None:
    """Enforce ADR-011's hard floor/ceiling; return the flagged-tier advisory, if any.

    ``numeric_target_arl`` must already be validated as a non-``bool``,
    real number (via :func:`require_real_number`) -- this function applies
    only the ADR-011 range policy on top of that, so it is shared verbatim
    by ``fit_ewma``/``fit_cusum``/``fit_shewhart``'s ``_require_target_arl``.

    Parameters
    ----------
    numeric_target_arl
        The caller's ``target_arl``, already narrowed to ``float``.
    max_target_arl
        The chart's own ceiling (``MAX_MEANINGFUL_ARL`` today, unchanged by
        ADR-011 -- only the lower bound moved).
    parameter
        The parameter name, for ``context`` -- always ``"target_arl"``
        today, but not hard-coded, since every caller already has that
        string available and passing it keeps this function's contract
        general rather than baking in one call site's spelling.

    Returns
    -------
    FittingAdvisory | None
        A disclosure when ``MIN_TARGET_ARL <= numeric_target_arl <
        VERIFIED_ARL_FLOOR``; ``None`` at or above ``VERIFIED_ARL_FLOOR``.

    Raises
    ------
    InvalidParameterError
        ``numeric_target_arl`` is not finite, is below ``MIN_TARGET_ARL``,
        or is above ``max_target_arl``.
    """
    constraint = f"must be a finite float in [{MIN_TARGET_ARL}, {max_target_arl}]"
    if not math.isfinite(numeric_target_arl) or not (
        MIN_TARGET_ARL <= numeric_target_arl <= max_target_arl
    ):
        raise InvalidParameterError(
            f"{parameter} is outside the supported range",
            context={
                "parameter": parameter,
                "constraint": constraint,
                "kind": "invalid",
                "provided": numeric_target_arl,
            },
            recovery_hint=(
                f"Choose a {parameter} within [{MIN_TARGET_ARL}, "
                f"{max_target_arl}]. Caliper does not fit below "
                f"{MIN_TARGET_ARL} -- Lucas & Saccucci (1987) tabulate no "
                "lower in-control ARL0, so there is no published basis to "
                "calibrate or verify against. Common choices are 370 or 500."
            ),
        )
    if numeric_target_arl < VERIFIED_ARL_FLOOR:
        return FittingAdvisory(
            kind=_TARGET_ARL_BELOW_VERIFIED_RANGE_KIND,
            description=(
                f"{parameter}={numeric_target_arl} is below "
                f"{VERIFIED_ARL_FLOOR}, the smallest in-control ARL0 any "
                "published table in Caliper's own test suite verifies a "
                "fitted chart against (Lucas & Saccucci 1990 for EWMA; "
                "Montgomery 2013's worked Siegmund-approximation example "
                "for CUSUM). The fitted limits are computed by the exact "
                "same calibration method as any other target -- only the "
                "verification coverage is thinner here."
            ),
        )
    return None


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


__all__ = [
    "MIN_TARGET_ARL",
    "VERIFIED_ARL_FLOOR",
    "classify_target_arl",
    "require_real_number",
    "require_type",
]
