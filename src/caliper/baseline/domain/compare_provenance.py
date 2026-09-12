"""``compare_provenance()`` -- Phase I/II provenance boundary check.

Compares a Phase II ``ScoringResult``'s measurement provenance against a
fitted artefact's Phase I baseline provenance, raising
``ProvenanceMismatchError`` if they differ on either dimension. The same
violation, same category, same required ``context`` shape as
``Baseline.record()``'s intra-baseline check (ADR-002 "Category
consistency with Phase I" / ``docs/domain-model.md`` OQ-11) -- see
``caliper.baseline.domain.provenance_comparison`` for the shared
mismatch-accumulation logic both boundaries use, so they cannot drift
apart.

See ``docs/domain-model.md`` "Provenance change requires a refit" and
CLAUDE.md "Provenance mismatch raises -- Phase I and Phase II alike".
Deliberately takes no ``acknowledge=``/``force=`` parameter of any kind --
an acknowledged mismatch is still a mismatch, and every downstream ARL_0
claim would be computed against a baseline that no longer describes the
process. The engineer refits (ratified 2026-09-10, ``docs/domain-model.md``
OQ-9).

**BIN-127: reading ``artefact``'s provenance is guarded.** Unlike
``Monitor`` (narrowed at construction to the three concrete ``Fitted*``
types), this function accepts anything satisfying ``FittedControlLimits``
structurally, and reads ``artefact.provenance_model_version``/
``provenance_criteria`` directly. An object that duck-types past that
protocol but raises when one of those two attributes is actually read --
or genuinely lacks one -- used to leak that raw exception unchanged. Both
outcomes are now caught by ``caliper.baseline.domain.attribute_probe`` and
turned into ``InvalidParameterError`` instead. **Not ``ProvenanceMismatchError``**
-- see ``_reject_if_artefact_provenance_unreadable``'s docstring for why.
"""

from __future__ import annotations

from caliper.baseline.domain.attribute_probe import AttributeProbe, probe_attribute
from caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from caliper.baseline.domain.provenance_comparison import build_mismatches
from caliper.errors import InvalidParameterError, ProvenanceMismatchError
from caliper.measurement import ScoringResult

_ARTEFACT_PROVENANCE_CONSTRAINT = (
    "must expose readable provenance_model_version and provenance_criteria "
    "string attributes (a FittedControlLimits-conforming object -- the "
    "return value of fit_ewma(), fit_cusum(), or fit_shewhart())"
)


def _reject_if_artefact_provenance_unreadable(
    artefact: object,
    model_version_probe: AttributeProbe,
    criteria_probe: AttributeProbe,
) -> None:
    """Raise ``InvalidParameterError`` if either provenance attribute is unreadable.

    **Why ``InvalidParameterError``, not ``ProvenanceMismatchError``, and not
    a guess.** ``ProvenanceMismatchError`` means "two established
    provenances were compared and differ" -- it requires an actual
    ``received`` value on the artefact side to report, per its
    ``context["mismatches"]`` shape (ADR-002). There is no such value here:
    the artefact's own provenance could not be read at all, so there is
    nothing to compare, only a malformed ``artefact`` parameter to reject.
    Forcing this into ``ProvenanceMismatchError`` would mean fabricating a
    ``"received"`` string for a value that was never actually obtained --
    a fabrication, not a report. ``InvalidParameterError`` with
    ``kind="invalid"`` on the ``artefact`` parameter is the same category
    ``Monitor.__init__`` already uses to reject a structurally-conforming
    but unusable artefact (BIN-120), which this is a further instance of:
    the object does not actually behave as a ``FittedControlLimits``, it
    only looks like one until read.
    """
    probes = {
        "provenance_model_version": model_version_probe,
        "provenance_criteria": criteria_probe,
    }
    absent = tuple(name for name, probe in probes.items() if probe.is_absent)
    unreadable = {
        name: probe.raised_type
        for name, probe in probes.items()
        if probe.raised_type is not None
    }
    if not absent and not unreadable:
        return

    raise InvalidParameterError(
        "artefact does not expose a readable provenance signature",
        context={
            "parameter": "artefact",
            "constraint": _ARTEFACT_PROVENANCE_CONSTRAINT,
            "kind": "invalid",
            "provided": type(artefact).__name__,
            "missing_fields": list(absent),
            "unreadable_fields": unreadable,
        },
        recovery_hint=(
            "Pass the return value of fit_ewma(), fit_cusum(), or "
            "fit_shewhart() -- not a custom object that merely satisfies "
            "FittedControlLimits structurally. Its provenance_model_version "
            "and provenance_criteria attributes must both be readable "
            "strings."
        ),
    )


def compare_provenance(result: ScoringResult, artefact: FittedControlLimits) -> None:
    """Compare a Phase II scoring result's provenance against a fitted artefact's.

    Parameters
    ----------
    result
        The Phase II observation whose provenance is being checked.
    artefact
        Any chart type's fitted artefact. Compared uniformly via the
        shared ``FittedControlLimits`` protocol -- no chart-type-specific
        branching (BR-6).

    Returns
    -------
    None
        On success. Mirrors ``Baseline.record()``'s precedent: a
        validation-gate operation that raises on failure and returns
        nothing meaningful on success.

    Raises
    ------
    ProvenanceMismatchError
        ``result``'s provenance differs from ``artefact``'s on either
        dimension. Both dimensions are checked before raising, so a dual
        mismatch is reported in a single raise covering both.
    InvalidParameterError
        ``artefact``'s ``provenance_model_version``/``provenance_criteria``
        attributes are absent, or raise when accessed (BIN-127) -- an
        object that satisfies ``FittedControlLimits`` structurally but not
        behaviourally.
    """
    model_version_probe = probe_attribute(artefact, "provenance_model_version")
    criteria_probe = probe_attribute(artefact, "provenance_criteria")
    _reject_if_artefact_provenance_unreadable(
        artefact, model_version_probe, criteria_probe
    )

    mismatches = build_mismatches(
        expected_model_version=model_version_probe.value,
        received_model_version=result.provenance.model_version.value,
        expected_criteria=criteria_probe.value,
        received_criteria=result.provenance.scoring_criteria.value,
    )
    if not mismatches:
        return

    raise ProvenanceMismatchError(
        "scoring result's provenance differs from the fitted artefact's "
        "baseline provenance",
        context={"mismatches": mismatches},
        recovery_hint=(
            "This Phase II observation was measured by a different judge "
            "model version and/or scoring criteria than the Phase I "
            "baseline the fitted artefact was derived from. Refit control "
            "limits from a new Phase I baseline collected under the "
            "current judge model version and criteria -- there is no "
            "acknowledge or force override for a provenance mismatch."
        ),
    )
