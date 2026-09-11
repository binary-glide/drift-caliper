"""``log_receiver`` -- the built-in receiver that logs a drift signal.

See ``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``
section 6. R1's one built-in ``SignalReceiver`` -- stdlib ``logging`` only
(``structlog`` is an explicit non-goal; see ``CLAUDE.md``, "Stack Members
Not Yet Used"). Gets no special-casing from ``Monitor``: a failure inside
this function is caught by the exact same per-receiver ``try``/``except``
every other receiver goes through, so a logging failure surfaces on
``MonitoringResult.delivery_failures``, never by attempting to log the
failure through the same logging call that just failed.
"""

from __future__ import annotations

import logging

from caliper.monitoring.domain.monitoring_result import MonitoringResult

_LOGGER_NAME = "caliper.monitoring"


def log_receiver(signal: MonitoringResult) -> None:
    """Log ``signal`` as a ``WARNING``-level entry on ``"caliper.monitoring"``.

    ``WARNING`` is required, not stylistic (ADR-010 section 6): Python's
    ``logging.lastResort`` only surfaces ``WARNING`` and above with zero
    configuration anywhere in the logger hierarchy, and this receiver's
    whole point is zero-configuration visibility. The full signal content
    is attached via ``extra=`` so an engineer's own ``Formatter`` or a
    ``structlog`` processor they already run can pick these fields up
    without Caliper requiring either.

    Attach a handler to ``logging.getLogger("caliper.monitoring")`` to
    route these entries to your own destination and format -- Caliper owns
    no destination of its own (BR-1).
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.warning(
        "caliper detected a drift signal: chart_type=%s direction=%s",
        signal.chart_type,
        signal.direction,
        extra={
            "caliper_chart_type": signal.chart_type,
            "caliper_direction": signal.direction,
            "caliper_observation_score": signal.observation.score,
            "caliper_fitted_artefact": signal.fitted_artefact,
        },
    )
