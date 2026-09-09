"""``ScoringResult`` -- the immutable, structured outcome of ``Judge.score()``.

See ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
section 7.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, field_validator

from caliper.errors import InvalidParameterError
from caliper.measurement.provenance import Provenance


class ScoringResult(BaseModel):
    """Returned by ``Judge.score()``. Immutable; equality by value.

    Attempting to reassign any field after creation raises Pydantic's
    ``ValidationError`` -- not a ``CaliperError`` (ADR-002 section 7;
    immutability violations are not part of the exception taxonomy).
    """

    model_config = ConfigDict(frozen=True)

    score: float
    reasoning: str
    provenance: Provenance

    @field_validator("score")
    @classmethod
    def must_be_finite(cls, v: float) -> float:
        """Reject a non-finite score.

        Raises ``InvalidParameterError`` (``context["parameter"] ==
        "score"``, ``context["kind"] == "invalid"``) when ``score`` is
        ``NaN`` or positive/negative infinity (ADR-006 section 5). No
        constraint is placed on ``reasoning`` content or on an
        already-validated ``provenance``.
        """
        if not math.isfinite(v):
            raise InvalidParameterError(
                "score must be a finite number",
                context={
                    "parameter": "score",
                    "constraint": "must be a finite float (not NaN or +/-infinity)",
                    "kind": "invalid",
                    "provided": v,
                },
                recovery_hint=(
                    "Ensure the judge provider returns a real, finite "
                    "numeric score. A NaN or infinite value cannot be "
                    "recorded as a measurement."
                ),
            )
        return v
