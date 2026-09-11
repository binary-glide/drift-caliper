"""``Provenance`` -- the measurement configuration that produced a score.

See ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
section 7.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from caliper.measurement.domain.criteria import ScoringCriteria
from caliper.measurement.domain.model_version import ModelVersion


class Provenance(BaseModel):
    """The model version and scoring criteria that produced a score.

    Equality by value (both fields) -- inherited from Pydantic's default
    field-wise ``BaseModel`` equality, since ``ModelVersion`` and
    ``ScoringCriteria`` are themselves value-equal models.

    No validator: there is nothing left to validate here. A
    ``Provenance`` cannot hold a blank or whitespace-only model version or
    criteria string, because ``ModelVersion`` and ``ScoringCriteria``
    already cannot -- the invariant is structural, not re-checked.
    """

    model_config = ConfigDict(frozen=True)

    model_version: ModelVersion
    scoring_criteria: ScoringCriteria

    def __str__(self) -> str:
        """Report the wrapped values directly, not nested wrapper reprs.

        Before this (BIN-110 P3), the default Pydantic repr nested
        ``ModelVersion``'s and ``ScoringCriteria``'s own reprs three levels
        deep to read two strings. ``.model_version``/``.scoring_criteria``
        still return the real value objects, unchanged (ADR-006 section 7)
        -- only this readout changes.
        """
        return (
            f"model_version={self.model_version}, "
            f"scoring_criteria={self.scoring_criteria}"
        )

    def __repr__(self) -> str:
        """Produce a reconstructible-looking repr without nesting wrapper reprs.

        See ``__str__`` above for the rationale -- this is the same fix
        applied to ``repr()``, since an f-string/log line and a REPL echo
        both hit this, and both suffered the same three-level nesting.
        """
        return (
            f"Provenance(model_version={str(self.model_version)!r}, "
            f"scoring_criteria={str(self.scoring_criteria)!r})"
        )
