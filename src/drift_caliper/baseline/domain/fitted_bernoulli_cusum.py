"""``FittedBernoulliCUSUM`` -- the record produced by fitting a Bernoulli CUSUM.

See ``docs/domain-model.md`` (Fitted Artefact Protocol -- Chart-Specific
Artefacts -- FittedBernoulliCUSUM) and
``docs/architecture/adr/014-bernoulli-cusum-api-surface-and-fitted-artefact-shape.md``
Decision 6b for the field table, as amended by Amendment 2 (Decisions 14,
15 and 19) and its corrigendum (C3, C5): the two ``BernoulliArmLattice``
fields are the chart, and the four arm floats are derived from them.

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

from pydantic import ConfigDict, computed_field

from drift_caliper.baseline.domain.audit_summary import CHART_SPECIFIC_HEADING
from drift_caliper.baseline.domain.bernoulli_arm_lattice import BernoulliArmLattice
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
    """The exact in-control ARL of the constructed integer chart (ADR-014
    Decision 13.1), and always ``>= requested_arl``. Its meaning depends on
    which arms are checked: for ``"lower"``, the lower arm's one-sided ARL0 at
    ``p_u``; for ``"upper"``, the upper arm's one-sided ARL0 at ``p_l``; for
    ``"two_sided"``, **B**, the exact expected run length of the coupled
    three-outcome chain -- a guaranteed floor on the joint in-control ARL
    over every true failure rate in ``[p_l, p_u]`` (Decision 19.4)."""

    expected_detection_arl: float
    """ADR-013 section 4's detection disclosure, as amended by ADR-014
    Decision 15: the exact ARL1 of the constructed chart at **the shift the
    checked arm(s) are tuned to detect** -- failure rate
    ``observed_failure_rate * detect_rate_multiple`` for ``"lower"`` (``p_u *
    detect_rate_multiple`` when no failures were observed) and for
    ``"two_sided"`` (the joint chain); ``observed_failure_rate /
    detect_rate_multiple``, the improvement, for ``"upper"``. First-class and
    unconditional (ADR-014 Decision 4)."""

    expected_improvement_detection_arl: float | None = None
    """The two-sided joint chain's exact ARL at failure rate
    ``observed_failure_rate / detect_rate_multiple`` -- the improvement the
    upper arm is tuned to detect (ADR-014 Decision 19.6). Present exactly
    when the chart checks both arms (``direction == "two_sided"``); ``None``
    otherwise, since an upper-only chart already reports its improvement
    figure as ``expected_detection_arl``. A number, not a warning: it can
    exceed ``achieved_arl`` when the baseline has too few failures for an
    improvement to be detectable quickly."""

    calibration_method: str
    """``"gicp_markov_chain"`` for a one-sided fit (exact, at the checked
    arm's own conservative bound); ``"gicp_markov_chain_coupled_bound"`` for
    a two-sided fit, whose ``achieved_arl`` is the coupled floor B under
    calibration D (ADR-014 corrigendum C5). No approximate path exists."""

    advisories: tuple[FittingAdvisory, ...] = ()
    """Non-raising disclosures (ADR-011's vehicle). Two kinds are produced for
    this chart: ``"lower_arm_signals_on_first_failure"`` when the lower arm is
    at its floor -- every single failure signals, so the achieved ARL0 is
    ``1/p_u`` whatever was requested (ADR-014 Decision 12; ``boundary`` is
    that ARL0) -- and ``"upper_arm_not_designable"`` when a two-sided request
    met a zero-failure baseline and only the lower arm could be built
    (Decision 19.2; ``boundary`` is ``1.0``, the smallest failure count at
    which the improvement arm can be designed)."""

    # -- Bernoulli-specific design surface --
    detect_rate_multiple: float
    """*M* -- the shift lever, a multiple of the in-control failure rate
    rather than a sigma multiple (ADR-012 section 1). Moves the lower arm's
    design point up (``M * p_u``) and the upper arm's down (``p_l / M``)."""

    alpha: float
    """GICP's own risk appetite -- ``0.10`` (ADR-013 section 3), the level of
    both confidence bounds. Reported for auditability, not settable (ADR-014
    Decision 5)."""

    p_u: float
    """The one-sided Clopper-Pearson upper confidence bound on the
    baseline's failure rate -- the lower arm's design and calibration rate
    (ADR-013 section 1)."""

    p_l: float
    """The one-sided Clopper-Pearson lower confidence bound on the baseline's
    failure rate -- the upper arm's design and calibration rate (ADR-014
    Decision 19.1). ``0.0`` when no failures were observed."""

    direction: str
    """The chart that actually runs: ``"two_sided"``, ``"lower"`` or
    ``"upper"`` -- same vocabulary as ``FittedCUSUM.direction``. A two-sided
    request against a zero-failure baseline reports ``"lower"``, because only
    that arm could be designed (ADR-014 Decision 19.2)."""

    lattice_lower: BernoulliArmLattice | None
    """The exact integer definition of the degradation-detecting (lower)
    arm -- **the stored, authoritative chart** (ADR-014 Decision 14). Present
    exactly when ``direction`` checks the lower arm (corrigendum C3)."""

    lattice_upper: BernoulliArmLattice | None
    """The same for the improvement-detecting (upper) arm; present exactly
    when ``direction`` checks the upper arm."""

    # Derived, never stored (Decision 14.3): one source of truth, so a float
    # can never disagree with the integers Monitor actually steps.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def reference_value_lower(self) -> float | None:
        """*r* for the lower arm -- ``reference_units / denominator``."""
        lattice = self.lattice_lower
        return None if lattice is None else lattice.reference_value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decision_interval_lower(self) -> float | None:
        """*h* for the lower arm -- ``decision_interval_units / denominator``."""
        lattice = self.lattice_lower
        return None if lattice is None else lattice.decision_interval

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reference_value_upper(self) -> float | None:
        """*r* for the upper arm -- ``reference_units / denominator``."""
        lattice = self.lattice_upper
        return None if lattice is None else lattice.reference_value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decision_interval_upper(self) -> float | None:
        """*h* for the upper arm -- ``decision_interval_units / denominator``."""
        lattice = self.lattice_upper
        return None if lattice is None else lattice.decision_interval

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
            "Expected improvement detection ARL: "
            f"{self.expected_improvement_detection_arl}",
            f"Calibration method: {self.calibration_method}",
            "",
            CHART_SPECIFIC_HEADING,
            f"Detect rate multiple (M): {self.detect_rate_multiple}",
            f"Alpha: {self.alpha}",
            f"Clopper-Pearson upper bound (p_U): {self.p_u}",
            f"Clopper-Pearson lower bound (p_L): {self.p_l}",
            f"Direction: {self.direction}",
            f"Lattice, lower arm: {_describe_lattice(self.lattice_lower)}",
            f"Reference value, lower arm (r): {self.reference_value_lower}",
            f"Decision interval, lower arm (h): {self.decision_interval_lower}",
            f"Lattice, upper arm: {_describe_lattice(self.lattice_upper)}",
            f"Reference value, upper arm (r): {self.reference_value_upper}",
            f"Decision interval, upper arm (h): {self.decision_interval_upper}",
        ]
        return "\n".join(lines)


def _describe_lattice(lattice: BernoulliArmLattice | None) -> str:
    if lattice is None:
        return "not checked"
    return (
        f"N={lattice.denominator}, r_units={lattice.reference_units}, "
        f"h_units={lattice.decision_interval_units}"
    )


__all__ = ["FittedBernoulliCUSUM"]
