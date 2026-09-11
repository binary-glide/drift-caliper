"""Statistical Process Control over LLM-as-a-judge agent quality scores.

Caliper treats a judge score stream as a process: fit control limits on a
trusted Phase I baseline, then monitor Phase II observations against them.

``import caliper`` exposes every name an engineer names in their own code --
``Judge``, the value objects it produces, ``JudgeProviderPort`` and the
response type an adapter returns, ``Baseline``, the three ``fit_*`` functions
and the fitted artefact types they return, ``Monitor`` and
``MonitoringResult`` for Phase II recording, and the full ``CaliperError``
taxonomy an engineer catches. Subpackage imports (``caliper.measurement``,
``caliper.baseline``, ``caliper.monitoring``) keep working unconditionally --
this front door only adds a shorter path alongside them, it replaces nothing.

``__all__`` was ``[]`` until BIN-110, and that was a deliberate deferral
rather than an oversight: promoting names one story at a time would have
churned the top-level surface repeatedly, so BIN-57 chose to make the
promotion once, when the walking skeleton's API shape was decided. That
condition is now met -- E1 (scoring) and E2's collection, sufficiency and
fitting stories have all landed -- so the deferral is discharged here, not
overturned.

Names are promoted on one test: does an engineer type it? Validation bounds
(``MIN_*``/``MAX_*``) are not exported anywhere -- they are internal to the
validators that enforce them. ``DEFAULT_*`` constants stay on
``caliper.baseline``, where someone overriding a default reads it first.
"""

from caliper.baseline import (
    Baseline,
    DataQualityConcern,
    FittedControlLimits,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    SufficiencyResult,
    compare_provenance,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.errors import (
    CaliperError,
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidObservationError,
    InvalidParameterError,
    JudgeRefusalError,
    MalformedResponseError,
    MissingPrerequisiteError,
    ProvenanceMismatchError,
    ProviderError,
)
from caliper.measurement import (
    Judge,
    JudgeProviderPort,
    JudgeProviderResponse,
    ModelVersion,
    Provenance,
    ScoringCriteria,
    ScoringResult,
)
from caliper.monitoring import Monitor, MonitoringResult

__all__ = [
    "Baseline",
    "CaliperError",
    "DataQualityConcern",
    "DegenerateBaselineError",
    "FittedCUSUM",
    "FittedControlLimits",
    "FittedEWMA",
    "FittedShewhart",
    "InsufficientBaselineError",
    "InvalidObservationError",
    "InvalidParameterError",
    "Judge",
    "JudgeProviderPort",
    "JudgeProviderResponse",
    "JudgeRefusalError",
    "MalformedResponseError",
    "MissingPrerequisiteError",
    "ModelVersion",
    "Monitor",
    "MonitoringResult",
    "Provenance",
    "ProvenanceMismatchError",
    "ProviderError",
    "ScoringCriteria",
    "ScoringResult",
    "SufficiencyResult",
    "compare_provenance",
    "fit_cusum",
    "fit_ewma",
    "fit_shewhart",
]
