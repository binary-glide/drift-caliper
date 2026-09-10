"""``FittedEWMA`` -- the immutable record produced by fitting EWMA control limits.

See ``docs/domain-model.md`` (Fitted Artefact Protocol -- Chart-Specific
Artefacts -- FittedEWMA) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``.
Satisfies ``caliper.baseline.domain.fitted_control_limits.FittedControlLimits``
structurally: every field below with the same name as a protocol property
*is* that property (Pydantic model fields are attributes, which is all
``@runtime_checkable`` checks for).

Scaffold only: the fields are exactly what the domain model specifies for
BIN-65, with no validators beyond Pydantic's own type coercion.
``caliper.baseline.domain.ewma_fitting.fit_ewma`` (BIN-65, not yet
implemented) is the only place a real, correctly-calibrated instance should
be constructed -- tests obtain a ``FittedEWMA`` by calling it, never by
constructing one directly, mirroring the convention
``tests/unit/baseline/test_baseline_sufficiency.py`` established for
``SufficiencyResult``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FittedEWMA(BaseModel):
    """Immutable fitted EWMA control limits, with baseline statistics and provenance.

    Satisfies the ``FittedControlLimits`` protocol structurally -- the first
    eleven fields below are exactly the protocol's property names, in the
    same order as ``docs/domain-model.md``'s shared-core table. The four
    EWMA-specific fields follow (``docs/domain-model.md``, Chart-Specific
    Artefacts -- FittedEWMA). Immutable after creation (BIN-65 BR-10) via
    ``ConfigDict(frozen=True)`` -- attempting to reassign any field raises
    ``pydantic_core.ValidationError`` (ADR-002 section 7), not a
    ``CaliperError``.
    """

    model_config = ConfigDict(frozen=True)

    # -- shared core (FittedControlLimits protocol) --
    chart_type: str
    baseline_mean: float
    baseline_spread: float
    sigma_estimate: float
    sigma_estimation_method: str
    observation_count: int
    provenance_model_version: str
    provenance_criteria: str
    requested_arl: float
    achieved_arl: float
    calibration_method: str

    # -- EWMA-specific (docs/domain-model.md, Chart-Specific Artefacts) --
    smoothing_param: float
    ucl: float
    lcl: float
    cl: float
