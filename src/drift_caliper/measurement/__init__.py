"""Measurement bounded context.

Creating judges with pinned model versions, defining scoring criteria, and
scoring agent outputs to produce structured results with provenance. See
``docs/domain-model.md`` (Bounded Contexts -- Measurement).
"""

from drift_caliper.measurement.domain.criteria import ScoringCriteria
from drift_caliper.measurement.domain.judge import Judge
from drift_caliper.measurement.domain.model_version import ModelVersion
from drift_caliper.measurement.domain.provenance import Provenance
from drift_caliper.measurement.domain.result import ScoringResult
from drift_caliper.measurement.ports.judge_provider import (
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
