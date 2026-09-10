"""``FittedShewhart`` -- the immutable record from fitting Shewhart control limits.

See ``docs/domain-model.md`` (Fitted Artefact Protocol -- Chart-Specific
Artefacts -- FittedShewhart) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
sections 3 and 6. Satisfies
``caliper.baseline.domain.fitted_control_limits.FittedControlLimits``
structurally: every field below with the same name as a protocol property
*is* that property (Pydantic model fields are attributes, which is all
``@runtime_checkable`` checks for) -- see ``FittedEWMA``/``FittedCUSUM`` for
the identical convention on the sibling chart types.

``caliper.baseline.domain.shewhart_fitting.fit_shewhart`` (BIN-95) is the
only place a real, correctly-calibrated instance should be constructed --
tests obtain a ``FittedShewhart`` by calling it, never by constructing one
directly, mirroring the convention ``FittedEWMA``/``FittedCUSUM`` already
established.

Unlike ``FittedCUSUM``, the Shewhart I-chart's detection boundary *is* an
observation-scale control-limit pair (``ucl``/``lcl``/``cl``) -- the same
shape as ``FittedEWMA``'s. What distinguishes ``FittedShewhart`` from
``FittedEWMA`` is that it has no independent tuning parameter: the sigma
multiplier is entirely derived from the false alarm tolerance (ADR-004
section 5; BIN-95 A3/A5) -- there is no ``smoothing_param``/
``reference_value`` analogue to report alongside it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FittedShewhart(BaseModel):
    """Immutable fitted Shewhart control limits, with baseline stats and provenance.

    Satisfies the ``FittedControlLimits`` protocol structurally -- the first
    eleven fields below are exactly the protocol's property names, in the
    same order as ``docs/domain-model.md``'s shared-core table (identical to
    ``FittedEWMA``/``FittedCUSUM``, including ``sigma_estimate``/
    ``sigma_estimation_method`` -- the moving-range sigma is shared across
    all three chart types, not Shewhart-only, despite an earlier iteration
    of the domain model placing it here exclusively; see
    ``docs/domain-model.md``'s "Dual-Spread Distinction -- All Charts"
    section). The four Shewhart-specific fields follow
    (``docs/domain-model.md``, Chart-Specific Artefacts -- FittedShewhart).
    Immutable after creation (BIN-95 BR-12) via ``ConfigDict(frozen=True)``
    -- attempting to reassign any field raises
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

    # -- Shewhart-specific (docs/domain-model.md, Chart-Specific Artefacts) --
    sigma_multiplier: float
    """*L* -- number of sigma units defining the control limits; derived
    from the false alarm tolerance (ARL0 = 1 / (2 * Phi(-L)) under
    normality), never specified directly by the engineer (A5)."""

    ucl: float
    """Upper control limit = ``baseline_mean + sigma_multiplier * sigma_estimate``."""

    lcl: float
    """Lower control limit = ``baseline_mean - sigma_multiplier * sigma_estimate``."""

    cl: float
    """Centre line (= ``baseline_mean``)."""
