"""``MonitoringResult`` -- the immutable, per-call outcome of ``Monitor.record()``.

See ``docs/domain-model.md`` (Value Object Inventory -- MonitoringResult) and
``docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md``
section 4 for the full reasoning, including why ``__bool__`` raises despite
this type having an explicit yes/no field (unlike ``ScoringResult``/
``Fitted*``, which have none at all). Extended by
``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``
section 2 with ``direction``, ``fitted_artefact`` and ``delivery_failures``.
"""

from __future__ import annotations

from typing import NoReturn

from pydantic import BaseModel, ConfigDict

from drift_caliper.baseline.domain.fitted_bernoulli_cusum import FittedBernoulliCUSUM
from drift_caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from drift_caliper.measurement import ScoringResult
from drift_caliper.monitoring.domain.delivery_failure import DeliveryFailure


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

    ``arbitrary_types_allowed`` is required because ``fitted_artefact`` is
    typed (in part) as ``FittedControlLimits``, a ``Protocol``, which
    Pydantic cannot build a validation schema for -- the same reason
    ``Judge.provider`` needs it (``src/drift_caliper/measurement/domain/judge.py``).

    ``fitted_artefact``'s type widened to include ``FittedBernoulliCUSUM``
    (BIN-133, ADR-014 section 6a) alongside ``FittedControlLimits`` --
    ``FittedBernoulliCUSUM`` does not satisfy that protocol (it satisfies
    only ``HasProvenance``), and ``Monitor.record()`` builds this type from
    whichever concrete artefact it was constructed with, so the field must
    accept both. Discovered while extending ``Monitor`` for BIN-133: this
    field is typed independently of ``Monitor.__init__``'s own artefact
    parameter and would otherwise reject a ``FittedBernoulliCUSUM`` at
    construction even after the constructor itself accepted one.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    is_in_control: bool
    observation: ScoringResult
    chart_type: str

    # "upper" or "lower" -- None exactly when is_in_control is True. Only
    # two of FittedCUSUM.direction's three configuration values are ever
    # legal here: "two_sided" is never a legal outcome, because a specific
    # departure is always uni-directional (ADR-010 section 2;
    # docs/domain-model.md's explicit warning against a careless
    # direction=artefact.direction pass-through).
    direction: str | None = None

    # The same immutable artefact Monitor was constructed from --
    # referenced, never copied. Present on every result, signal or not.
    fitted_artefact: FittedControlLimits | FittedBernoulliCUSUM

    # One entry per configured receiver that raised during this record()
    # call's delivery step. Empty when every receiver succeeded, none were
    # configured, or no signal occurred to attempt delivery for. Populated
    # by Monitor's own delivery loop, never by the receiver reporting on
    # itself (ADR-010 section 1).
    delivery_failures: tuple[DeliveryFailure, ...] = ()

    def __bool__(self) -> NoReturn:
        """Forbid truthiness -- see the class docstring."""
        raise TypeError(
            "MonitoringResult has no True/False meaning; check `is_in_control` "
            "directly instead of using it in a boolean context"
        )
