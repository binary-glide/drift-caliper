"""``Provenance`` -- the measurement configuration that produced a score.

See ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
section 7.
"""

from __future__ import annotations

from dataclasses import dataclass

from caliper.measurement.criteria import ScoringCriteria
from caliper.measurement.judge import ModelVersion


@dataclass(frozen=True, slots=True)
class Provenance:
    """The model version and scoring criteria that produced a score.

    Equality by value (both fields) -- inherited from the dataclass default,
    since ``ModelVersion`` and ``ScoringCriteria`` are themselves value-equal
    dataclasses.

    No ``__post_init__``: there is nothing left to validate here. A
    ``Provenance`` cannot hold a blank or whitespace-only model version or
    criteria string, because ``ModelVersion`` and ``ScoringCriteria``
    already cannot -- the invariant is structural, not re-checked.
    """

    model_version: ModelVersion
    scoring_criteria: ScoringCriteria
