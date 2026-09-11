"""``DeliveryFailure`` -- the record of one ``SignalReceiver`` raising.

See ``docs/domain-model.md`` (Value Object Inventory -- ``DeliveryFailure``)
and ``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``
section 1 for the full reasoning, including why this holds
``error_type``/``error_message`` strings rather than the live exception
object.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DeliveryFailure(BaseModel):
    """One ``SignalReceiver`` raising during ``Monitor.record()``'s delivery step.

    Carried by ``MonitoringResult.delivery_failures`` -- never constructed
    or held anywhere else. Built entirely from ``Monitor``'s own
    ``try``/``except`` around the receiver call (``Monitor._deliver``,
    ADR-010 section 4 step 3); never by asking the receiver to report on
    itself (ADR-010 section 1).

    Immutable; equality by value. ``error_type``/``error_message`` are
    plain strings, not the live exception object -- a receiver's exception
    can reference tracebacks, frames, and arbitrarily large closures, which
    would compound ``Monitor.history``'s already-accepted unbounded-growth
    risk (ADR-009 section 7) for no scenario-required benefit.
    """

    model_config = ConfigDict(frozen=True)

    receiver: str
    """Identifies which receiver failed (its ``repr``/``__qualname__``)."""

    error_type: str
    """``type(exc).__name__`` -- the machine-branchable "why"."""

    error_message: str
    """``str(exc)`` -- the human-readable "why"."""
