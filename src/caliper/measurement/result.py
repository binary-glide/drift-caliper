"""``ScoringResult`` -- the immutable, structured outcome of ``Judge.score()``.

See ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
section 7.
"""

from __future__ import annotations

from dataclasses import dataclass

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

        Not yet implemented -- domain-implementer fills this in per ADR-006
        section 5: raise ``InvalidParameterError`` (``context["parameter"]
        == "score"``, ``context["kind"] == "invalid"``) when ``score`` is
        ``NaN`` or positive/negative infinity. No constraint is placed on
        ``reasoning`` content or on an already-validated ``provenance``.
        """
        raise NotImplementedError
