"""``FittedCUSUM`` -- the immutable record produced by fitting CUSUM control limits.

See ``docs/domain-model.md`` (Fitted Artefact Protocol -- Chart-Specific
Artefacts -- FittedCUSUM) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
sections 3 and 6. Satisfies
``caliper.baseline.domain.fitted_control_limits.FittedControlLimits``
structurally: every field below with the same name as a protocol property
*is* that property (Pydantic model fields are attributes, which is all
``@runtime_checkable`` checks for) -- see ``FittedEWMA`` for the identical
convention on the sibling chart type.

``caliper.baseline.domain.cusum_fitting.fit_cusum`` (BIN-94) is the only
place a real, correctly-calibrated instance should be constructed -- tests
obtain a ``FittedCUSUM`` by calling it, never by constructing one directly,
mirroring the convention ``tests/unit/baseline/test_ewma_fitting.py``
established for ``FittedEWMA``.

CUSUM's detection boundary (the decision interval ``h``, compared against
the accumulating CUSUM statistic) is deliberately **not** an
observation-scale control-limit pair -- ADR-004 section 3 rejected a
collapsed common representation specifically because it would misrepresent
this. Do not read ``decision_interval`` as a UCL/LCL analogue.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FittedCUSUM(BaseModel):
    """Immutable fitted CUSUM control limits, with baseline statistics and provenance.

    Satisfies the ``FittedControlLimits`` protocol structurally -- the first
    eleven fields below are exactly the protocol's property names, in the
    same order as ``docs/domain-model.md``'s shared-core table (identical to
    ``FittedEWMA``, including ``sigma_estimate``/``sigma_estimation_method``
    -- the moving-range sigma is shared across all three chart types, not
    Shewhart-only; see ``docs/domain-model.md``'s "Dual-Spread Distinction"
    amendment). The four CUSUM-specific fields follow (``docs/domain-model.md``,
    Chart-Specific Artefacts -- FittedCUSUM). Immutable after creation
    (BIN-94 BR-11) via ``ConfigDict(frozen=True)`` -- attempting to reassign
    any field raises ``pydantic_core.ValidationError`` (ADR-002 section 7),
    not a ``CaliperError``.
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

    # -- CUSUM-specific (docs/domain-model.md, Chart-Specific Artefacts) --
    reference_value: float
    """*k* -- shift size to detect, in sigma units of the shared ``sigma_estimate``."""

    decision_interval: float
    """*h* -- derived from ``reference_value`` and ``requested_arl`` via
    Siegmund's (1985) approximation. NOT an observation-scale limit -- see
    module docstring."""

    target_value: float
    """mu_0 -- the CUSUM's target value, typically the baseline mean."""

    direction: str
    """``"two_sided"`` (default), ``"lower"`` (degradation only), or
    ``"upper"`` (improvement only, i.e. baseline staleness)."""
