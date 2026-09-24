"""``BernoulliArmLattice`` -- the exact integer definition of one Bernoulli CUSUM arm.

See ``docs/domain-model.md`` (Value Object Inventory -- ``BernoulliArmLattice``)
and ADR-014 Amendment 2, Decision 14.

**The integers are the chart.** A Bernoulli CUSUM arm on the lattice ``1/N``
is fully described by three integers: the denominator ``N``, the reference
value in units (``r_units``, so ``r = r_units / N``) and the decision
interval in units (``h_units``, so ``h = h_units / N``). The ARLs a fit
reports are solved on exactly this chain, and ``Monitor`` steps exactly this
chain, so the reported numbers and the running chart cannot drift apart --
which is what happened while the artefact stored floats and ``Monitor``
accumulated them in binary floating point (Amendment 2 section 0, defect 3).
The floats an engineer reads are *derived* from these integers, never stored
beside them: two stored copies of one number is this project's recurring
failure.

**Why the bounds are what they are.**

- ``denominator >= 2`` -- the smallest lattice with a numerator strictly
  inside ``(0, N)``.
- ``0 < reference_units < denominator`` -- ``r_units = 0`` would make a
  success never lower the lower arm, and ``r_units = N`` would make a failure
  never raise it; either collapses the arm into a one-directional walk.
- ``1 <= decision_interval_units <= MAX_DECISION_INTERVAL_UNITS`` -- the
  calibration search starts at one unit, and Decision 13.3 caps every arm at
  999,999 units so no single solve exceeds the ratified 1,000,000-state
  memory budget (Decision 10b).
- **No upper bound on ``denominator``** (Decision 13.2; corrigendum C9):
  state counts depend on ``h_units``, not on ``N``, and ``N`` legitimately
  reaches 3,364,300 at m=300,000 f=1.

Every integer must be an **exact** ``int``: a ``bool`` is an ``int`` to
Python but not a lattice size, and an ``int`` subclass can override the
arithmetic ``Monitor`` performs on it.
"""

from __future__ import annotations

from typing import NoReturn

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from drift_caliper.errors import InvalidParameterError

# ADR-014 Decision 13.3: one below the joint-state cap (Decision 10b), so a
# one-sided chain (h_units + 1 states) never exceeds 1,000,000 states either.
MAX_DECISION_INTERVAL_UNITS = 999_999

MIN_DENOMINATOR = 2
MIN_DECISION_INTERVAL_UNITS = 1

_FIELD_ORDER = ("denominator", "reference_units", "decision_interval_units")


def lattice_integer_violation(
    attribute: str, value: object, *, denominator: int
) -> tuple[str, dict[str, object]] | None:
    """Check one lattice integer without trusting how its lattice was built.

    Shared by this type's validators and by ``Monitor``'s re-validation at
    use (Decision 14.5, row M2): ``model_copy(update=...)`` and
    ``model_construct()`` skip validation, so a caller-supplied artefact can
    carry integers this type would have refused.

    Parameters
    ----------
    attribute
        One of ``"denominator"``, ``"reference_units"``,
        ``"decision_interval_units"``.
    value
        The value found under that name.
    denominator
        The lattice's already-checked denominator, which bounds
        ``reference_units``; ignored for the other two.

    Returns
    -------
    tuple[str, dict[str, object]] | None
        ``None`` when the integer is legal. Otherwise ``(constraint,
        detail)``, where ``detail`` is ``{"provided_type": ...}`` for a value
        that is not an exact ``int`` -- its type name only, never the value,
        because a hostile object's ``repr`` can raise inside the error path
        (corrigendum C6/C12.2) -- or ``{"provided": value}`` for an exact
        ``int`` out of bounds.
    """
    if type(value) is not int:
        return (
            f"{attribute} must be an exact int, not a bool or int subclass",
            {"provided_type": type(value).__name__},
        )
    if attribute == "denominator":
        constraint = f"denominator must be at least {MIN_DENOMINATOR}"
        legal = value >= MIN_DENOMINATOR
    elif attribute == "reference_units":
        constraint = "reference_units must satisfy 0 < reference_units < denominator"
        legal = 0 < value < denominator
    else:
        constraint = (
            "decision_interval_units must satisfy "
            f"{MIN_DECISION_INTERVAL_UNITS} <= decision_interval_units "
            f"<= {MAX_DECISION_INTERVAL_UNITS}"
        )
        legal = MIN_DECISION_INTERVAL_UNITS <= value <= MAX_DECISION_INTERVAL_UNITS
    return None if legal else (constraint, {"provided": value})


def _lattice_error(
    attribute: str, constraint: str, detail: dict[str, object]
) -> InvalidParameterError:
    return InvalidParameterError(
        f"{attribute} is not a legal lattice integer",
        context={
            "parameter": attribute,
            "constraint": constraint,
            "kind": "invalid",
            **detail,
        },
        recovery_hint=(
            "BernoulliArmLattice is constructed by fit_bernoulli_cusum(); read "
            "it from a fitted artefact rather than building one."
        ),
    )


class BernoulliArmLattice(BaseModel):
    """One arm of a Bernoulli CUSUM, as the three exact integers that define it.

    Engineers read it from ``FittedBernoulliCUSUM.lattice_lower``/
    ``lattice_upper``; only ``fit_bernoulli_cusum`` constructs one in the
    normal path. Immutable, equal by value, and with no truth value
    (BIN-110): every lattice that exists is a valid chart, so there is no
    "false" one to distinguish.

    Attributes
    ----------
    denominator
        ``N`` -- the lattice step is ``1/N``. At least 2, with no upper bound.
    reference_units
        ``r_units`` -- the reference value is ``r_units / N``, strictly
        inside ``(0, 1)``.
    decision_interval_units
        ``h_units`` -- the decision interval is ``h_units / N``. The arm
        signals when its integer statistic strictly exceeds this (ADR-009
        section 5 / BIN-112).
    """

    model_config = ConfigDict(frozen=True)

    denominator: int
    reference_units: int
    decision_interval_units: int

    @field_validator(*_FIELD_ORDER, mode="before")
    @classmethod
    def must_be_a_legal_lattice_integer(
        cls, value: object, info: ValidationInfo
    ) -> object:
        """Reject a non-exact ``int`` or an out-of-bounds one (module docstring).

        ``mode="before"`` so Pydantic's own coercion (``9.0`` -> ``9``,
        ``"8"`` -> ``8``) never gets the chance to make a wrong type look
        right. Fields validate in declaration order, so ``denominator`` is
        already in ``info.data`` when ``reference_units`` is checked.
        """
        attribute = info.field_name or ""
        denominator = info.data.get("denominator", MIN_DENOMINATOR)
        violation = lattice_integer_violation(attribute, value, denominator=denominator)
        if violation is not None:
            raise _lattice_error(attribute, *violation)
        return value

    @property
    def reference_value(self) -> float:
        """``r = reference_units / denominator``."""
        return self.reference_units / self.denominator

    @property
    def decision_interval(self) -> float:
        """``h = decision_interval_units / denominator``."""
        return self.decision_interval_units / self.denominator

    def __bool__(self) -> NoReturn:
        """Forbid truthiness -- see the class docstring's BIN-110 note."""
        raise TypeError(
            "BernoulliArmLattice has no True/False meaning; read its integer "
            "fields directly instead of using it in a boolean context"
        )


__all__ = ["MAX_DECISION_INTERVAL_UNITS", "BernoulliArmLattice"]
