"""Shared rendering for ``Fitted*.audit_summary()`` (BIN-66).

See ``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
and ``tests/bdd/steps/review_fitted_control_limits_steps.py``'s module
docstring for the design decision this module implements: ``audit_summary()``
is a dedicated method on each concrete ``Fitted*`` type -- not ``__repr__``
or ``__str__`` (BIN-110 already owns the compact debugger/log-line case) --
and is deliberately not added to the ``FittedControlLimits`` protocol, since
no scenario calls it without already knowing which concrete artefact was
fitted.

SC5 requires the shared audit fields to appear "in the same position and
with the same labelling in all three summaries." That is a structural
guarantee, not something to get right independently three times -- so
``render_audit_summary`` is the single place the shared-core label text and
order are written down. Every concrete ``Fitted*.audit_summary()`` calls
this same function with only its own chart-specific lines; there is no
per-chart-type copy of the shared section that could drift out of sync.

Label order matches ``FittedControlLimits``'s own property order
(``docs/domain-model.md`` section 2 / ADR-004 section 2).
"""

from __future__ import annotations

from collections.abc import Sequence

from drift_caliper.baseline.domain.fitted_control_limits import FittedControlLimits

CHART_SPECIFIC_HEADING = "Chart-specific parameters:"


def _shared_audit_lines(artefact: FittedControlLimits) -> list[str]:
    """Render the shared-core fields as labelled lines, in a fixed order.

    Takes a ``FittedControlLimits``, not a concrete chart type -- this
    function contains no branch keyed on which chart was fitted, which is
    what makes the ordering and labelling identical across all three
    concrete types by construction.
    """
    return [
        f"Chart type: {artefact.chart_type}",
        f"Baseline mean: {artefact.baseline_mean}",
        f"Baseline spread: {artefact.baseline_spread}",
        f"Sigma estimate: {artefact.sigma_estimate}",
        f"Sigma estimation method: {artefact.sigma_estimation_method}",
        f"Observation count: {artefact.observation_count}",
        f"Provenance model version: {artefact.provenance_model_version}",
        f"Provenance criteria: {artefact.provenance_criteria}",
        f"Requested ARL: {artefact.requested_arl}",
        f"Achieved ARL: {artefact.achieved_arl}",
        f"Calibration method: {artefact.calibration_method}",
    ]


def render_audit_summary(
    artefact: FittedControlLimits, chart_specific_lines: Sequence[str]
) -> str:
    """Compose a complete audit summary: shared core, then a chart-specific section.

    ``chart_specific_lines`` are already-labelled strings supplied by the
    concrete ``Fitted*`` type -- this function does not know what a
    smoothing parameter or a decision interval is, only that they belong
    after the ``CHART_SPECIFIC_HEADING`` marker (SC5: "a clearly identified
    section").
    """
    lines = [
        *_shared_audit_lines(artefact),
        "",
        CHART_SPECIFIC_HEADING,
        *chart_specific_lines,
    ]
    return "\n".join(lines)
