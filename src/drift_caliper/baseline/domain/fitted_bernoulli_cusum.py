"""``FittedBernoulliCUSUM`` -- the record produced by fitting a Bernoulli CUSUM.

See ``docs/domain-model.md`` (Fitted Artefact Protocol -- Chart-Specific
Artefacts -- FittedBernoulliCUSUM) and
``docs/architecture/adr/014-bernoulli-cusum-api-surface-and-fitted-artefact-shape.md``
Decision 6b for the field table this type implements verbatim.

🚨 **Does not satisfy ``FittedControlLimits``** -- the first fitted artefact
type that does not (ADR-014 Decision 6a). Its statistic accumulates the raw
pass/fail value directly against a probability-space reference value derived
from a log-likelihood ratio over ``(p_U, p_1)``; nowhere does a sigma
estimate enter its calibration, so ``sigma_estimate``/``baseline_mean``/
``baseline_spread``/``target_value`` have no referent for this chart and are
deliberately absent. It satisfies
``drift_caliper.baseline.domain.has_provenance.HasProvenance`` (the two-attribute
``provenance_model_version``/``provenance_criteria`` protocol) and is
otherwise its own type, reporting its own, honestly-scoped field set.

``drift_caliper.baseline.domain.bernoulli_cusum_fitting.fit_bernoulli_cusum``
(BIN-133) is the only place a real, correctly-calibrated instance should be
constructed -- tests obtain a ``FittedBernoulliCUSUM`` by calling it, never
by constructing one directly, mirroring the convention every other
``Fitted*`` type establishes.
"""

from __future__ import annotations

from typing import NoReturn

from pydantic import ConfigDict

from drift_caliper.baseline.domain.audit_summary import CHART_SPECIFIC_HEADING
from drift_caliper.baseline.domain.fitted_artefact_base import FittedArtefactBase
from drift_caliper.baseline.domain.fitting_advisory import FittingAdvisory


class FittedBernoulliCUSUM(FittedArtefactBase):
    """Immutable fitted Bernoulli CUSUM control limits, with provenance.

    Satisfies ``HasProvenance`` only -- see the module docstring. Immutable
    after creation via ``ConfigDict(frozen=True)`` -- attempting to reassign
    any field raises ``pydantic_core.ValidationError`` (ADR-002 section 7),
    not a ``CaliperError``.

    ``bool()`` is forbidden (BIN-110 P0/general ruling, applied uniformly to
    every ``Fitted*`` type): a ``FittedBernoulliCUSUM`` that exists already
    succeeded -- there is no "unfitted" instance to distinguish from a
    fitted one.
    """

    model_config = ConfigDict(frozen=True)

    # -- reporting core (HasProvenance + Bernoulli-specific) --
    chart_type: str
    observed_failure_rate: float
    """p-hat = f / m. The one summary statistic ADR-012/013's own vocabulary
    uses throughout -- no separate ``baseline_mean``; reporting the
    complement too would be redundant."""

    observation_count: int
    provenance_model_version: str
    provenance_criteria: str
    requested_arl: float
    achieved_arl: float
    """Exact, via the joint two-armed Markov-chain solve for a two-sided fit,
    or the single-arm exact solve for a one-sided fit (ADR-014 section 6c)."""

    expected_detection_arl: float
    """ADR-013 section 4's detection-performance disclosure -- the exact
    ARL1 of the constructed chart, evaluated at ``observed_failure_rate *
    detect_rate_multiple`` (or ``p_u * detect_rate_multiple`` when no
    failures were observed, since "a rise from zero" is otherwise undefined
    as a target rate). A first-class, unconditional field, not routed
    through ``FittingAdvisory`` (ADR-014 Decision 4) -- every fit reports it
    on the main happy path."""

    calibration_method: str
    """``"gicp_markov_chain"`` -- the exact joint (two-sided) or single-arm
    (one-sided) Markov-chain solve, never the continuous chart's
    harmonic-combination approximation (ADR-014 section 6c)."""

    # ADR-011's non-raising disclosure vehicle -- carried for forward
    # compatibility with ADR-005's still-unbuilt middle-tier baseline-
    # adequacy advisory (ADR-013 section 2 confirms it does apply to binary
    # baselines unchanged); empty today, since no producer for this chart
    # exists yet.
    advisories: tuple[FittingAdvisory, ...] = ()

    # -- Bernoulli-specific design surface --
    detect_rate_multiple: float
    """*M* -- the shift lever, a multiple of the in-control failure rate
    rather than a sigma multiple (ADR-012 section 1)."""

    alpha: float
    """GICP's own risk appetite -- ``0.10`` (ADR-013 section 3), fixed.
    Reported for auditability, not settable (ADR-014 Decision 5)."""

    p_u: float
    """The one-sided Clopper-Pearson upper confidence bound on the
    baseline's observed failure rate -- the conservative rate the design
    actually uses in place of ``observed_failure_rate`` (ADR-013 section 1)."""

    direction: str
    """``"two_sided"`` (default), ``"lower"``, or ``"upper"`` -- same
    vocabulary as ``FittedCUSUM.direction``."""

    reference_value_lower: float
    """*r* for the degradation-detecting (lower) arm -- design point
    ``p_1 = detect_rate_multiple * p_u``."""

    decision_interval_lower: float
    """*h* for the degradation-detecting (lower) arm."""

    reference_value_upper: float
    """*r* for the improvement-detecting (upper) arm -- design point
    ``p_u / detect_rate_multiple`` (ADR-012 amendment section 2)."""

    decision_interval_upper: float
    """*h* for the improvement-detecting (upper) arm."""

    def __bool__(self) -> NoReturn:
        """Forbid truthiness -- see the class docstring's BIN-110 note."""
        raise TypeError(
            "FittedBernoulliCUSUM has no True/False meaning; check its "
            "`achieved_arl` or other fields directly instead of using it in "
            "a boolean context"
        )

    def audit_summary(self) -> str:
        """Give a full, labelled, multi-line record suitable for an audit log.

        Unlike the three continuous ``Fitted*`` types, this does not reuse
        ``render_audit_summary`` -- that helper is written against the
        ``FittedControlLimits`` shared core (``baseline_mean``,
        ``sigma_estimate``, ...), which this type deliberately does not
        have (ADR-014 Decision 6a). Every field below is this type's own.
        """
        lines = [
            f"Chart type: {self.chart_type}",
            f"Observed failure rate: {self.observed_failure_rate}",
            f"Observation count: {self.observation_count}",
            f"Provenance model version: {self.provenance_model_version}",
            f"Provenance criteria: {self.provenance_criteria}",
            f"Requested ARL: {self.requested_arl}",
            f"Achieved ARL: {self.achieved_arl}",
            f"Expected detection ARL: {self.expected_detection_arl}",
            f"Calibration method: {self.calibration_method}",
            "",
            CHART_SPECIFIC_HEADING,
            f"Detect rate multiple (M): {self.detect_rate_multiple}",
            f"Alpha: {self.alpha}",
            f"Clopper-Pearson upper bound (p_U): {self.p_u}",
            f"Direction: {self.direction}",
            f"Reference value, lower arm (r): {self.reference_value_lower}",
            f"Decision interval, lower arm (h): {self.decision_interval_lower}",
            f"Reference value, upper arm (r): {self.reference_value_upper}",
            f"Decision interval, upper arm (h): {self.decision_interval_upper}",
        ]
        return "\n".join(lines)


__all__ = ["FittedBernoulliCUSUM"]
