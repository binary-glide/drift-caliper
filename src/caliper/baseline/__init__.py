"""Baseline bounded context.

Collecting Phase I observations under provenance consistency, from which
control limits will be fitted (BIN-65/94/95, not this story). See
``docs/domain-model.md`` (Bounded Contexts -- Baseline).

Mirrors ``caliper.measurement``'s layout (``domain/`` holding the bounded
context's types, re-exported here so every consumer imports from
``caliper.baseline`` rather than a deep path) -- see ``CLAUDE.md``'s
"Module layout" note.
"""

from caliper.baseline.domain.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline
from caliper.baseline.domain.data_quality_concern import DataQualityConcern
from caliper.baseline.domain.sufficiency_result import SufficiencyResult

__all__ = [
    "DEFAULT_SUFFICIENCY_THRESHOLD",
    "Baseline",
    "DataQualityConcern",
    "SufficiencyResult",
]
