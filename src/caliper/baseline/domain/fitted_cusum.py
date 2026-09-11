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

import math
from typing import NoReturn

from pydantic import BaseModel, ConfigDict, field_validator

from caliper.baseline.domain.audit_summary import render_audit_summary
from caliper.errors import InvalidParameterError


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

    ``bool()`` is forbidden (BIN-110 P0/general ruling): a ``FittedCUSUM``
    that exists already succeeded -- there is no "unfitted" instance to
    distinguish from a fitted one. See ``tests/unit/test_truthiness.py``.
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

    @field_validator("sigma_estimate")
    @classmethod
    def must_be_finite_and_positive(cls, v: float) -> float:
        """Reject a non-finite or non-positive ``sigma_estimate`` (BIN-119).

        Raises ``InvalidParameterError`` (``context["parameter"] ==
        "sigma_estimate"``, ``context["kind"] == "invalid"``) for ``NaN``,
        ``+/-inf``, ``0.0``, or a negative value. Mirrors
        ``ScoringResult.must_be_finite`` and ``FittedEWMA``'s identical
        validator -- an invariant of this type itself, enforced no matter
        how an instance is constructed, not only through ``fit_cusum``.

        Distinct from -- and does not replace -- the
        ``DegenerateBaselineError`` guard
        ``caliper.baseline.domain.spc_numerics._moving_range_sigma``
        already raises before this constructor is ever reached in the
        normal fitting path: that guard diagnoses *the baseline* ("this
        data cannot be fitted"), which is also the guard that stops a
        zero ``sigma_estimate`` from reaching CUSUM's
        ``record()``-time standardisation as a raw
        ``ZeroDivisionError`` (BIN-119). This validator protects *the
        type* ("no ``FittedCUSUM`` may exist with an unusable sigma"),
        which matters even for a value that reaches this constructor by
        some other route than ``fit_cusum`` -- there is no baseline in
        scope here to raise a baseline-shaped error about.
        """
        if not math.isfinite(v) or v <= 0.0:
            raise InvalidParameterError(
                "sigma_estimate must be a finite, strictly positive number",
                context={
                    "parameter": "sigma_estimate",
                    "constraint": "must be a finite float greater than 0.0",
                    "kind": "invalid",
                    "provided": v,
                },
                recovery_hint=(
                    "A FittedCUSUM cannot hold a sigma_estimate that is "
                    "NaN, infinite, zero, or negative -- the standardised "
                    "CUSUM statistic computed from it would be meaningless "
                    "or divide by zero. Construct FittedCUSUM via "
                    "fit_cusum(), which already rejects an unusable "
                    "baseline before reaching this point."
                ),
            )
        return v

    def __bool__(self) -> NoReturn:
        """Forbid truthiness -- see the class docstring's BIN-110 note."""
        raise TypeError(
            "FittedCUSUM has no True/False meaning; check its "
            "`decision_interval` or other fields directly instead of using "
            "it in a boolean context"
        )

    def audit_summary(self) -> str:
        """Give a full, labelled, multi-line record suitable for an audit log (BIN-66).

        Distinct from ``__repr__``/``__str__`` -- see
        ``caliper.baseline.domain.audit_summary``'s module docstring. The
        shared-core section is rendered by ``render_audit_summary``, which
        every concrete ``Fitted*`` type calls identically; only the
        CUSUM-specific lines below are this method's own responsibility.
        """
        return render_audit_summary(
            self,
            [
                f"Reference value (k): {self.reference_value}",
                f"Decision interval (h): {self.decision_interval}",
                f"Target value (mu_0): {self.target_value}",
                f"Direction: {self.direction}",
            ],
        )
