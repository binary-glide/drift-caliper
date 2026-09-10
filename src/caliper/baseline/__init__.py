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
from caliper.baseline.domain.cusum_fitting import (
    DEFAULT_DIRECTION,
    DEFAULT_REFERENCE_VALUE,
    MAX_REFERENCE_VALUE,
    MIN_REFERENCE_VALUE,
    fit_cusum,
)
from caliper.baseline.domain.data_quality_concern import DataQualityConcern
from caliper.baseline.domain.ewma_fitting import (
    DEFAULT_SMOOTHING_PARAM,
    MAX_MEANINGFUL_ARL,
    MAX_SMOOTHING_PARAM,
    MIN_MEANINGFUL_ARL,
    MIN_SMOOTHING_PARAM,
    fit_ewma,
)
from caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from caliper.baseline.domain.fitted_cusum import FittedCUSUM
from caliper.baseline.domain.fitted_ewma import FittedEWMA
from caliper.baseline.domain.fitted_shewhart import FittedShewhart
from caliper.baseline.domain.shewhart_fitting import fit_shewhart
from caliper.baseline.domain.sufficiency_result import SufficiencyResult

__all__ = [
    "DEFAULT_DIRECTION",
    "DEFAULT_REFERENCE_VALUE",
    "DEFAULT_SMOOTHING_PARAM",
    "DEFAULT_SUFFICIENCY_THRESHOLD",
    "MAX_MEANINGFUL_ARL",
    "MAX_REFERENCE_VALUE",
    "MAX_SMOOTHING_PARAM",
    "MIN_MEANINGFUL_ARL",
    "MIN_REFERENCE_VALUE",
    "MIN_SMOOTHING_PARAM",
    "Baseline",
    "DataQualityConcern",
    "FittedCUSUM",
    "FittedControlLimits",
    "FittedEWMA",
    "FittedShewhart",
    "SufficiencyResult",
    "fit_cusum",
    "fit_ewma",
    "fit_shewhart",
]
