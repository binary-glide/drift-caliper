"""Invariants shared by every ``Fitted*`` artefact (BIN-142).

Two invariants live here rather than in each concrete type:

**Every float field must be finite.** BIN-142 found ``fit_ewma`` and
``fit_shewhart`` returning ``ucl=inf``/``lcl=-inf`` from a *finite* sigma --
an artefact reporting it delivered the requested ARL0 while being incapable of
signalling, because nothing exceeds infinity.

**``sigma_estimate`` must also be strictly positive** (BIN-119). This check
previously existed three times, identically, one copy per concrete type. It is
now written once.

⚠️ **Why a base class when ADR-004 chose a structural ``Protocol``.** These are
different mechanisms answering different questions. ``FittedControlLimits``
describes what a *consumer* may rely on, and stays structural -- inheriting
from this base is not how a type satisfies it, and a third-party artefact that
never imports this module still conforms. This base shares *implementation*
between the three concrete types Caliper ships. Nothing about the protocol
changes.

🚨 **Why the check is here and not in each ``fit_*``.** BIN-140 added a
postcondition to ``achieved_arl`` and stated the lesson as *"any number a
numerical routine hands to a caller needs a postcondition"* -- then BIN-142
appeared the next day, because the postcondition guarded one field and the
overflow happened in a different one. **A postcondition on one field is not a
postcondition on the artefact.** A per-field or per-call-site fix is also how
``_has_zero_variance`` ended up triplicated (BIN-125). Enforcing it over
*every* float field of *every* artefact is the only version of this guard that
cannot be incompletely applied.
"""

from __future__ import annotations

import math
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from drift_caliper.errors import InvalidParameterError


class FittedArtefactBase(BaseModel):
    """Base carrying the numeric invariants every fitted artefact shares.

    Declares no fields: the concrete types own their own shapes, and this
    base owns only the rules that apply to all of them.
    """

    model_config = ConfigDict(frozen=True)

    @field_validator("sigma_estimate", check_fields=False)
    @classmethod
    def must_be_finite_and_positive(cls, v: float) -> float:
        """Reject a non-finite or non-positive ``sigma_estimate`` (BIN-119).

        Raises ``InvalidParameterError`` (``context["parameter"] ==
        "sigma_estimate"``, ``context["kind"] == "invalid"``) for ``NaN``,
        ``+/-inf``, ``0.0``, or a negative value. Mirrors
        ``ScoringResult.must_be_finite`` -- an invariant of the type itself,
        enforced no matter how an instance is constructed, not only through
        ``fit_ewma``/``fit_cusum``/``fit_shewhart``.

        Distinct from -- and does not replace -- the
        ``DegenerateBaselineError`` guard
        ``drift_caliper.baseline.domain.spc_numerics._moving_range_sigma``
        raises before this constructor is reached in the normal fitting
        path: that guard diagnoses *the baseline* ("this data cannot be
        fitted"), and for CUSUM it is also what stops a zero
        ``sigma_estimate`` reaching ``record()``-time standardisation as a
        raw ``ZeroDivisionError``. This validator protects *the type* ("no
        fitted artefact may exist with an unusable sigma"), which matters
        for a value reaching the constructor by some route other than a
        ``fit_*`` call -- there is no baseline in scope here to raise a
        baseline-shaped error about.

        ``check_fields=False`` because this base declares no fields; each
        concrete type declares ``sigma_estimate`` itself.
        """
        if not math.isfinite(v) or v <= 0.0:
            raise InvalidParameterError(
                "sigma_estimate must be a finite, strictly positive number",
                context={
                    "parameter": "sigma_estimate",
                    "constraint": "must be a finite float greater than 0.0",
                    "kind": "invalid",
                    "provided": v,
                    "min_value": 0.0,
                    "min_inclusive": False,
                },
                recovery_hint=(
                    "A fitted artefact cannot hold a sigma_estimate that is "
                    "NaN, infinite, zero, or negative -- control limits "
                    "computed from it would be meaningless. Construct the "
                    "artefact via fit_ewma(), fit_cusum() or fit_shewhart(), "
                    "which reject an unusable baseline before reaching this "
                    "point."
                ),
            )
        return v

    @model_validator(mode="after")
    def every_float_field_must_be_finite(self) -> Self:
        """Reject an artefact carrying ``NaN`` or an infinite float (BIN-142).

        Runs over every field annotated ``float`` on the concrete type, so a
        chart-specific boundary -- ``ucl``, ``lcl``, ``decision_interval`` --
        is covered by the same rule as the shared core, without any type
        having to remember to opt in.

        🚨 **An infinite control limit is worse than a wrong one.** A chart
        with ``ucl=inf`` never signals, while its ``achieved_arl`` reports the
        false alarm rate it was asked for. That is confident silence: the
        failure mode this library exists to prevent, produced by the library
        itself.

        Raises ``InvalidParameterError`` naming the offending field. In the
        normal fitting path the caller sees ``DegenerateBaselineError`` from
        ``spc_numerics.require_representable_limits`` first, which diagnoses
        *the baseline* rather than a field they never passed; this is the
        type-level backstop for every other construction route.
        """
        for name, field in type(self).model_fields.items():
            if field.annotation is not float:
                continue
            value = getattr(self, name)
            if not math.isfinite(value):
                raise InvalidParameterError(
                    f"{name} must be a finite number",
                    context={
                        "parameter": name,
                        "constraint": "must be a finite float",
                        "kind": "invalid",
                        "provided": value,
                        "chart_type": getattr(self, "chart_type", None),
                    },
                    recovery_hint=(
                        f"A fitted artefact cannot hold a non-finite {name}. "
                        "A control limit of infinity can never be exceeded, "
                        "so the chart would report that it delivers the "
                        "requested false alarm rate while being unable to "
                        "signal at all. Construct the artefact via fit_ewma(), "
                        "fit_cusum() or fit_shewhart(), which reject a "
                        "baseline whose control limits are not representable "
                        "before reaching this point."
                    ),
                )
        return self
