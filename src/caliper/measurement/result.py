"""``ScoringResult`` -- the immutable, structured outcome of ``Judge.score()``.

See ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
section 7.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from caliper.errors import InvalidParameterError
from caliper.measurement.provenance import Provenance


@dataclass(frozen=True, slots=True)
class ScoringResult:
    """Returned by ``Judge.score()``. Immutable; equality by value.

    Attempting to reassign any field after creation raises Python's
    ``dataclasses.FrozenInstanceError`` -- not a ``CaliperError`` (ADR-002
    section 7; immutability violations are not part of the exception
    taxonomy).
    """

    score: float
    reasoning: str
    provenance: Provenance

    def __post_init__(self) -> None:
        """Reject a non-finite score.

        Raises ``InvalidParameterError`` (``context["parameter"] ==
        "score"``, ``context["kind"] == "invalid"``) when ``score`` is
        ``NaN`` or positive/negative infinity (ADR-006 section 5). No
        constraint is placed on ``reasoning`` content or on an
        already-validated ``provenance``.
        """
        if not math.isfinite(self.score):
            raise InvalidParameterError(
                "score must be a finite number",
                context={
                    "parameter": "score",
                    "constraint": "must be a finite float (not NaN or +/-infinity)",
                    "kind": "invalid",
                    "provided": self.score,
                },
                recovery_hint=(
                    "Ensure the judge provider returns a real, finite "
                    "numeric score. A NaN or infinite value cannot be "
                    "recorded as a measurement."
                ),
            )
