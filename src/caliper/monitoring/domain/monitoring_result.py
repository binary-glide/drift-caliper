"""``MonitoringResult`` -- the immutable, per-call outcome of ``Monitor.record()``.

See ``docs/domain-model.md`` (Value Object Inventory -- MonitoringResult) and
``docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md``
section 4 for the full reasoning, including why ``__bool__`` raises despite
this type having an explicit yes/no field (unlike ``ScoringResult``/
``Fitted*``, which have none at all).
"""

from __future__ import annotations

from typing import NoReturn

from pydantic import BaseModel, ConfigDict

from caliper.measurement import ScoringResult


class MonitoringResult(BaseModel):
    """The outcome of one ``Monitor.record()`` call.

    Built internally by ``Monitor.record()`` only -- no public factory is
    specified (``docs/domain-model.md``). Immutable; equality by value.
    Attempting to reassign any field after creation raises Pydantic's
    ``ValidationError``, not a ``CaliperError`` (ADR-002 section 7).

    ``bool()`` is forbidden even though ``is_in_control`` is an explicit
    yes/no field (domain-modeller's decision, ADR-009 section 4): an
    engineer writing ``if monitor.record(observation):`` could mean either
    "is everything still fine?" (truthy-on-in-control, matching the field)
    or "did something notable just happen?" (truthy-on-signal, the
    opposite) -- unlike ``SufficiencyResult``, nothing disambiguates which
    reading was intended. Returning ``is_in_control`` from ``__bool__``
    risks a silently *inverted* monitoring loop, which is worse than the
    always-``True`` P0 ``SufficiencyResult`` was fixed for, because it does
    not look broken. See ``tests/unit/test_truthiness.py``.
    """

    model_config = ConfigDict(frozen=True)

    is_in_control: bool
    observation: ScoringResult
    chart_type: str

    def __bool__(self) -> NoReturn:
        """Forbid truthiness -- see the class docstring."""
        raise TypeError(
            "MonitoringResult has no True/False meaning; check `is_in_control` "
            "directly instead of using it in a boolean context"
        )
