"""Measurement bounded context.

Creating judges with pinned model versions, defining scoring criteria, and
scoring agent outputs to produce structured results with provenance. See
``docs/domain-model.md`` (Bounded Contexts -- Measurement).
"""

from caliper.measurement.criteria import ScoringCriteria
from caliper.measurement.judge import Judge
from caliper.measurement.model_version import ModelVersion
from caliper.measurement.provenance import Provenance
from caliper.measurement.provider import JudgeProviderPort, JudgeProviderResponse
from caliper.measurement.result import ScoringResult

__all__ = [
    "Judge",
    "JudgeProviderPort",
    "JudgeProviderResponse",
    "ModelVersion",
    "Provenance",
    "ScoringCriteria",
    "ScoringResult",
]
