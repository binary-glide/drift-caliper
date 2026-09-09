"""Measurement bounded context.

Creating judges with pinned model versions, defining scoring criteria, and
scoring agent outputs to produce structured results with provenance. See
``docs/domain-model.md`` (Bounded Contexts -- Measurement).
"""

from caliper.measurement.domain.criteria import ScoringCriteria
from caliper.measurement.domain.judge import Judge
from caliper.measurement.domain.model_version import ModelVersion
from caliper.measurement.domain.provenance import Provenance
from caliper.measurement.domain.result import ScoringResult
from caliper.measurement.ports.judge_provider import (
    JudgeProviderPort,
    JudgeProviderResponse,
)

__all__ = [
    "Judge",
    "JudgeProviderPort",
    "JudgeProviderResponse",
    "ModelVersion",
    "Provenance",
    "ScoringCriteria",
    "ScoringResult",
]
