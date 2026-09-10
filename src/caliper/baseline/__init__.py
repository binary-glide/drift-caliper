"""Baseline bounded context.

Collecting Phase I observations under provenance consistency, from which
control limits will be fitted (BIN-65/94/95, not this story). See
``docs/domain-model.md`` (Bounded Contexts -- Baseline).

Mirrors ``caliper.measurement``'s layout (``domain/`` holding the bounded
context's types, re-exported here so every consumer imports from
``caliper.baseline`` rather than a deep path) -- see ``CLAUDE.md``'s
"Module layout" note.

``MIN_*``/``MAX_*`` validation bounds (``cusum_fitting``'s
``MIN_REFERENCE_VALUE``/``MAX_REFERENCE_VALUE``, ``ewma_fitting``'s
``MIN_SMOOTHING_PARAM``/``MAX_SMOOTHING_PARAM``/``MIN_MEANINGFUL_ARL``/
``MAX_MEANINGFUL_ARL``) are deliberately NOT re-exported here (BIN-110 P2).
They are internal validation floors and ceilings an engineer supplies a
value *within*, never a value they assign -- noise on autocomplete that an
``InvalidParameterError``'s ``constraint`` message already communicates at
the moment it is actually needed. They still exist on their owning
submodules; only the re-export into this package's namespace is removed,
since ``__all__`` alone governs ``from caliper.baseline import *`` and not
``hasattr``/tab-completion, which was the actual complaint. ``DEFAULT_*``
constants stay -- an engineer overriding e.g. ``smoothing_param`` benefits
from seeing the un-overridden default first, the same reasoning ADR-005
already established for ``DEFAULT_SUFFICIENCY_THRESHOLD``. See
``tests/unit/baseline/test_baseline_package_exports.py``.
"""

from caliper.baseline.domain.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline
from caliper.baseline.domain.cusum_fitting import (
    DEFAULT_DIRECTION,
    DEFAULT_REFERENCE_VALUE,
    fit_cusum,
)
from caliper.baseline.domain.data_quality_concern import DataQualityConcern
from caliper.baseline.domain.ewma_fitting import DEFAULT_SMOOTHING_PARAM, fit_ewma
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
