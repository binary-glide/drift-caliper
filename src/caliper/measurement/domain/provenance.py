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
