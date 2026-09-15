"""``DataQualityConcern`` -- a data-quality issue found during a sufficiency check.

See ``docs/domain-model.md`` (Value Object Inventory -- DataQualityConcern).

Produced by ``Baseline.check_sufficiency()`` and carried on
``SufficiencyResult.data_quality_concerns``. Both fields are frozen; the
domain model specifies no validators beyond field presence.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DataQualityConcern(BaseModel):
    """A single data-quality issue found alongside a sufficiency check.

    E.g. a baseline whose observations all carry an identical score --
    ``kind == "zero_variance"`` (BIN-64 SC7/SC12). Immutable; equality by
    value.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    description: str
