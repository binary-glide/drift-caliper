"""``Provenance`` -- the measurement configuration that produced a score.

See ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
section 7.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from drift_caliper.measurement.domain.criteria import ScoringCriteria
from drift_caliper.measurement.domain.model_version import ModelVersion
from drift_caliper.measurement.domain.type_guards import require_instance


class Provenance(BaseModel):
    """The model version and scoring criteria that produced a score.

    Equality by value (both fields) -- inherited from Pydantic's default
    field-wise ``BaseModel`` equality, since ``ModelVersion`` and
    ``ScoringCriteria`` are themselves value-equal models.

    **No content validator** (ADR-006 section 7): there is nothing left to
    validate about *blank* content here. A ``Provenance`` cannot hold a
    blank or whitespace-only model version or criteria string, because
    ``ModelVersion`` and ``ScoringCriteria`` already cannot -- that
    invariant is structural, not re-checked.

    **That reasoning covers content, not type** (BIN-104, amending ADR-006
    -- see the amendment note at the end of
    ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``).
    ``Provenance(model_version="a string")`` never constructs a
    ``ModelVersion`` at all, so the structural guarantee above never
    engages -- Pydantic's core coercion rejected the wrong-typed value
    first, as a raw ``pydantic_core.ValidationError``. The two
    ``mode="before"`` validators below close that gap: they run ahead of
    Pydantic's core coercion and reject anything that is not already an
    actual ``ModelVersion``/``ScoringCriteria`` instance, raising
    ``InvalidParameterError`` instead.
    """

    model_config = ConfigDict(frozen=True)

    model_version: ModelVersion
    scoring_criteria: ScoringCriteria

    @field_validator("model_version", mode="before")
    @classmethod
    def reject_wrong_type_model_version(cls, v: object) -> object:
        """Reject a wrong-typed ``model_version`` (BIN-104).

        Must already be a ``ModelVersion`` instance.
        """
        return require_instance(
            v, ModelVersion, parameter="model_version", type_name="ModelVersion"
        )

    @field_validator("scoring_criteria", mode="before")
    @classmethod
    def reject_wrong_type_scoring_criteria(cls, v: object) -> object:
        """Reject a wrong-typed ``scoring_criteria`` (BIN-104).

        Must already be a ``ScoringCriteria`` instance.
        """
        return require_instance(
            v,
            ScoringCriteria,
            parameter="scoring_criteria",
            type_name="ScoringCriteria",
        )

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
