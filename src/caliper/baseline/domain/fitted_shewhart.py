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

import math
from typing import NoReturn

from pydantic import BaseModel, ConfigDict, field_validator

from caliper.baseline.domain.audit_summary import render_audit_summary
from caliper.baseline.domain.fitting_advisory import FittingAdvisory
from caliper.errors import InvalidParameterError


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

    ``bool()`` is forbidden (BIN-110 P0/general ruling): a ``FittedShewhart``
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

    # -- ADR-011: non-raising disclosures, e.g. target_arl inside the
    # flagged tier ([100, 370)) -- empty when there is nothing to disclose.
    # Defaults to `()` so every existing direct-construction call site keeps
    # working unchanged; `fit_shewhart` always passes it explicitly.
    advisories: tuple[FittingAdvisory, ...] = ()

    @field_validator("sigma_estimate")
    @classmethod
    def must_be_finite_and_positive(cls, v: float) -> float:
        """Reject a non-finite or non-positive ``sigma_estimate`` (BIN-119).

        Raises ``InvalidParameterError`` (``context["parameter"] ==
        "sigma_estimate"``, ``context["kind"] == "invalid"``) for ``NaN``,
        ``+/-inf``, ``0.0``, or a negative value. Mirrors
        ``ScoringResult.must_be_finite`` and ``FittedEWMA``/``FittedCUSUM``'s
        identical validator -- an invariant of this type itself, enforced
        no matter how an instance is constructed, not only through
        ``fit_shewhart``.

        Distinct from -- and does not replace -- the
        ``DegenerateBaselineError`` guard
        ``caliper.baseline.domain.spc_numerics._moving_range_sigma``
        already raises before this constructor is ever reached in the
        normal fitting path: that guard diagnoses *the baseline* ("this
        data cannot be fitted"). This validator protects *the type*
        ("no ``FittedShewhart`` may exist with an unusable sigma"), which
        matters even for a value that reaches this constructor by some
        other route than ``fit_shewhart`` -- there is no baseline in
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
                    "A FittedShewhart cannot hold a sigma_estimate that is "
                    "NaN, infinite, zero, or negative -- control limits "
                    "computed from it would be meaningless. Construct "
                    "FittedShewhart via fit_shewhart(), which already "
                    "rejects an unusable baseline before reaching this "
                    "point."
                ),
            )
        return v

    def __bool__(self) -> NoReturn:
        """Forbid truthiness -- see the class docstring's BIN-110 note."""
        raise TypeError(
            "FittedShewhart has no True/False meaning; check its "
            "`ucl`/`lcl`/`cl` or other fields directly instead of using it "
            "in a boolean context"
        )

    def audit_summary(self) -> str:
        """Give a full, labelled, multi-line record suitable for an audit log (BIN-66).

        Distinct from ``__repr__``/``__str__`` -- see
        ``caliper.baseline.domain.audit_summary``'s module docstring. The
        shared-core section is rendered by ``render_audit_summary``, which
        every concrete ``Fitted*`` type calls identically; only the
        Shewhart-specific lines below are this method's own responsibility.
        """
        return render_audit_summary(
            self,
            [
                f"Sigma multiplier (L): {self.sigma_multiplier}",
                f"Upper control limit (UCL): {self.ucl}",
                f"Lower control limit (LCL): {self.lcl}",
                f"Centre line (CL): {self.cl}",
            ],
        )
