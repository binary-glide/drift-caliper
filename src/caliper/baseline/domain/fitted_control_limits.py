"""``FittedControlLimits`` -- the shared protocol every fitted artefact satisfies.

See ``docs/domain-model.md`` (Fitted Artefact Protocol) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
sections 1-2 for the mechanism (``typing.Protocol``, ``@runtime_checkable``)
and the shared field surface. Concrete artefacts -- ``FittedEWMA`` today,
``FittedCUSUM``/``FittedShewhart`` in BIN-94/BIN-95 -- satisfy this protocol
structurally. No inheritance is required: a frozen Pydantic ``BaseModel``
that exposes every property below (as a field, since Pydantic fields are
also attributes) satisfies it.

Detection boundaries (control limits for EWMA/Shewhart, the decision
interval for CUSUM) are deliberately **not** part of this protocol -- see
ADR-004 section 3. They differ in shape between chart types (a limit pair
vs. a decision interval compared against an accumulating statistic), so a
shared accessor would misrepresent one or the other. Consumers that need
detection boundaries narrow to the concrete chart type.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FittedControlLimits(Protocol):
    """Consumer contract for any fitted artefact, regardless of chart type."""

    @property
    def chart_type(self) -> str:
        """Which chart type this artefact represents (e.g. ``"ewma"``)."""
        ...

    @property
    def baseline_mean(self) -> float:
        """Mean of the Phase I baseline scores."""
        ...

    @property
    def baseline_spread(self) -> float:
        """Sample standard deviation of Phase I scores.

        A descriptive statistic capturing TOTAL variation in the baseline,
        including any slow drift. Useful for characterising the data, but
        NOT the sigma used for control limit computation -- see
        ``sigma_estimate`` below and the dual-spread note in
        ``docs/domain-model.md``.
        """
        ...

    @property
    def sigma_estimate(self) -> float:
        """Moving-range-based sigma estimate (MR-bar / d_2).

        The OPERATIONAL sigma used by ALL chart types for control limit
        computation on individual observations. Captures SHORT-TERM
        variation only, robust to slow drift within the baseline. A
        DIFFERENT quantity from ``baseline_spread`` -- see the dual-spread
        note in ``docs/domain-model.md``.
        """
        ...

    @property
    def sigma_estimation_method(self) -> str:
        """Identifies how ``sigma_estimate`` was computed (e.g. ``"moving_range"``)."""
        ...

    @property
    def observation_count(self) -> int:
        """Number of baseline observations the limits were fitted from."""
        ...

    @property
    def provenance_model_version(self) -> str:
        """The judge model version from the baseline's provenance."""
        ...

    @property
    def provenance_criteria(self) -> str:
        """The scoring criteria from the baseline's provenance."""
        ...

    @property
    def requested_arl(self) -> float:
        """The target in-control ARL_0 the engineer specified."""
        ...

    @property
    def achieved_arl(self) -> float:
        """The in-control ARL_0 actually produced by the calibration.

        May differ from ``requested_arl`` due to numerical approximation.
        """
        ...

    @property
    def calibration_method(self) -> str:
        """Identifier for the method that produced the limits.

        E.g. ``"markov_chain"``.
        """
        ...
