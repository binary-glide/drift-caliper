"""Typed read access to ``FittedBernoulliCUSUM``'s ADR-014 Amendment 2 fields.

ADR-014 Amendment 2 adds ``lattice_lower``/``lattice_upper``
(``BernoulliArmLattice | None``, Decision 14 and corrigendum C3), ``p_l``
(Decision 19.1/19.5) and ``expected_improvement_detection_arl`` (Decision
19.6) to the artefact, and exports ``BernoulliArmLattice`` from
``drift_caliper.baseline`` (Decision 14). None of them exists yet -- these
tests are the red phase -- so reading them directly would fail ``mypy
--strict``/``ty`` on every access, not only at run time.

Every read goes through one of the functions below instead, so the type
checkers stay green and a missing field still fails the *test* at run time
with an ``AttributeError`` naming it.

TODO (domain-implementer): once the fields exist, these accessors can be
inlined as plain attribute reads; the protocol below states the shape the
tests rely on.
"""

from __future__ import annotations

from typing import Any, Protocol

import drift_caliper.baseline as baseline_package


class ArmLattice(Protocol):
    """The shape of ``BernoulliArmLattice`` (ADR-014 Decision 14.1)."""

    @property
    def denominator(self) -> int:
        """``N``: the lattice step is ``1/N``."""
        ...

    @property
    def reference_units(self) -> int:
        """``r_units``: the reference value is ``r_units / N``."""
        ...

    @property
    def decision_interval_units(self) -> int:
        """``h_units``: the decision interval is ``h_units / N``."""
        ...

    @property
    def reference_value(self) -> float:
        """Derived: ``reference_units / denominator``."""
        ...

    @property
    def decision_interval(self) -> float:
        """Derived: ``decision_interval_units / denominator``."""
        ...


def _read(obj: object, name: str) -> Any:
    return getattr(obj, name)


def lattice_lower(chart: object) -> ArmLattice | None:
    """``chart.lattice_lower`` (Decision 14.2, corrigendum C3)."""
    value: ArmLattice | None = _read(chart, "lattice_lower")
    return value


def lattice_upper(chart: object) -> ArmLattice | None:
    """``chart.lattice_upper`` (Decision 14.2, corrigendum C3)."""
    value: ArmLattice | None = _read(chart, "lattice_upper")
    return value


def triplet(lattice: ArmLattice | None) -> tuple[int, int, int] | None:
    """``(denominator, reference_units, decision_interval_units)``, or ``None``."""
    if lattice is None:
        return None
    return (
        lattice.denominator,
        lattice.reference_units,
        lattice.decision_interval_units,
    )


def p_l(chart: object) -> float:
    """``chart.p_l``, the Clopper-Pearson lower bound (Decision 19.1/19.5)."""
    value: float = _read(chart, "p_l")
    return value


def expected_improvement_detection_arl(chart: object) -> float | None:
    """``chart.expected_improvement_detection_arl`` (Decision 19.6)."""
    value: float | None = _read(chart, "expected_improvement_detection_arl")
    return value


def bernoulli_arm_lattice_type() -> type[Any]:
    """``drift_caliper.baseline.BernoulliArmLattice`` (Decision 14)."""
    value: type[Any] = _read(baseline_package, "BernoulliArmLattice")
    return value


def optional_arm_float(chart: object, name: str) -> float | None:
    """One of the four derived arm floats, typed as corrigendum C3 makes them.

    ``reference_value_lower``/``decision_interval_lower``/
    ``reference_value_upper``/``decision_interval_upper`` become
    ``float | None`` (``None`` exactly when that arm is not checked). Until
    the artefact's annotations say so, reading them directly types as
    ``float`` and a ``None`` check is flagged unreachable.
    """
    value: float | None = _read(chart, name)
    return value
