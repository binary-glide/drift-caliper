"""Monitoring bounded context.

Recording Phase II observations against a fitted control-limit artefact,
checking each one for an out-of-control signal, making a session's
recording history reviewable in-memory, and delivering a signal's full
content to zero or more engineer-supplied receivers. See
``docs/domain-model.md`` (Bounded Contexts -- Monitoring),
``docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md``,
and ``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``.

Mirrors ``drift_caliper.measurement``/``drift_caliper.baseline``'s layout (``domain/``
holding the bounded context's types, re-exported here so every consumer
imports from ``drift_caliper.monitoring`` rather than a deep path) -- see
``CLAUDE.md``'s "Module layout" note.
"""

from drift_caliper.monitoring.domain.delivery_failure import DeliveryFailure
from drift_caliper.monitoring.domain.log_receiver import log_receiver
from drift_caliper.monitoring.domain.monitor import Monitor
from drift_caliper.monitoring.domain.monitoring_result import MonitoringResult
from drift_caliper.monitoring.domain.signal_receiver import SignalReceiver

__all__ = [
    "DeliveryFailure",
    "Monitor",
    "MonitoringResult",
    "SignalReceiver",
    "log_receiver",
]
