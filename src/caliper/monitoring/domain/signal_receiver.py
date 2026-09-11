"""``SignalReceiver`` -- the plain callable shape a receiver satisfies.

See ``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``
section 3. Deliberately a plain ``TypeAlias``, not a ``Protocol`` or base
class -- there is nothing to structurally check (any callable that accepts
a ``MonitoringResult`` and returns ``None`` already satisfies it), and no
formal interface is warranted for R1's single built-in receiver
(``caliper.monitoring.log_receiver``). Offered for engineers' own type
hints only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from caliper.monitoring.domain.monitoring_result import MonitoringResult

SignalReceiver: TypeAlias = Callable[[MonitoringResult], None]
