"""Read a ``BernoulliArmLattice`` as the plain triplet the Bernoulli tests compare.

ADR-014 Amendment 2 (Decision 14) makes each arm's integer lattice the
artefact's authoritative chart. The tests compare lattices against the
independent reference (``tests.support.bernoulli_reference``), which speaks
in ``(denominator, reference_units, decision_interval_units)`` tuples; this
is the one conversion between the two.
"""

from __future__ import annotations

from drift_caliper.baseline import BernoulliArmLattice


def triplet(lattice: BernoulliArmLattice | None) -> tuple[int, int, int] | None:
    """``(denominator, reference_units, decision_interval_units)``, or ``None``."""
    if lattice is None:
        return None
    return (
        lattice.denominator,
        lattice.reference_units,
        lattice.decision_interval_units,
    )


def expected_detection_arl(chart: object) -> float | None:
    """``chart.expected_detection_arl``, typed as corrigendum C13 makes it.

    C13 turns the field into ``float | None`` (``None`` when the shifted rate
    lies at or inside the design rate). Until the artefact's annotation says
    so, reading it directly types as ``float`` and a ``None`` check is flagged
    unreachable by mypy.

    TODO (domain-implementer): inline as ``chart.expected_detection_arl`` once
    the annotation is ``float | None``.
    """
    value: float | None = getattr(chart, _EXPECTED_DETECTION_ARL)
    return value


_EXPECTED_DETECTION_ARL = "expected_detection_arl"
