"""Baseline bounded context.

Collecting Phase I observations under provenance consistency, from which
control limits will be fitted (BIN-65/94/95, not this story). See
``docs/domain-model.md`` (Bounded Contexts -- Baseline).

Mirrors ``drift_caliper.measurement``'s layout (``domain/`` holding the bounded
context's types, re-exported here so every consumer imports from
``drift_caliper.baseline`` rather than a deep path) -- see ``CLAUDE.md``'s
"Module layout" note.

``MIN_*``/``MAX_*`` validation bounds (``cusum_fitting``'s
``MIN_REFERENCE_VALUE``/``MAX_REFERENCE_VALUE``, ``ewma_fitting``'s
``MIN_SMOOTHING_PARAM``/``MAX_SMOOTHING_PARAM``/``MIN_COHERENT_ARL``/
``MAX_MEANINGFUL_ARL``, ``parameter_guards``'s ``MIN_TARGET_ARL``/
``VERIFIED_ARL_FLOOR``) are deliberately NOT re-exported here (BIN-110 P2).
They are internal validation floors and ceilings an engineer supplies a
value *within*, never a value they assign -- noise on autocomplete that an
``InvalidParameterError``'s ``constraint`` message already communicates at
the moment it is actually needed. They still exist on their owning
submodules; only the re-export into this package's namespace is removed,
since ``__all__`` alone governs ``from drift_caliper.baseline import *`` and not
``hasattr``/tab-completion, which was the actual complaint. ``DEFAULT_*``
constants stay -- an engineer overriding e.g. ``smoothing_param`` benefits
from seeing the un-overridden default first, the same reasoning ADR-005
already established for ``DEFAULT_SUFFICIENCY_THRESHOLD``. See
``tests/unit/baseline/test_baseline_package_exports.py``.
"""

from drift_caliper.baseline.domain.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
)
from drift_caliper.baseline.domain.compare_provenance import compare_provenance
from drift_caliper.baseline.domain.cusum_fitting import (
    DEFAULT_DIRECTION,
    DEFAULT_REFERENCE_VALUE,
    fit_cusum,
)
from drift_caliper.baseline.domain.data_quality_concern import DataQualityConcern
from drift_caliper.baseline.domain.ewma_fitting import DEFAULT_SMOOTHING_PARAM, fit_ewma
from drift_caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from drift_caliper.baseline.domain.fitted_cusum import FittedCUSUM
from drift_caliper.baseline.domain.fitted_ewma import FittedEWMA
from drift_caliper.baseline.domain.fitted_shewhart import FittedShewhart
from drift_caliper.baseline.domain.fitting_advisory import FittingAdvisory
from drift_caliper.baseline.domain.has_provenance import HasProvenance
from drift_caliper.baseline.domain.shewhart_fitting import fit_shewhart
from drift_caliper.baseline.domain.sufficiency_result import SufficiencyResult

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
    "FittingAdvisory",
    "HasProvenance",
    "SufficiencyResult",
    "compare_provenance",
    "fit_cusum",
    "fit_ewma",
    "fit_shewhart",
]
