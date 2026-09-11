"""Monitoring bounded context.

Recording Phase II observations against a fitted control-limit artefact,
checking each one for an out-of-control signal, and making a session's
recording history reviewable in-memory. See ``docs/domain-model.md``
(Bounded Contexts -- Monitoring) and
``docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md``.

Mirrors ``caliper.measurement``/``caliper.baseline``'s layout (``domain/``
holding the bounded context's types, re-exported here so every consumer
imports from ``caliper.monitoring`` rather than a deep path) -- see
``CLAUDE.md``'s "Module layout" note.
"""

from caliper.monitoring.domain.monitor import Monitor
from caliper.monitoring.domain.monitoring_result import MonitoringResult

__all__ = [
    "Monitor",
    "MonitoringResult",
]
