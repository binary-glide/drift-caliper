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
"""

from __future__ import annotations

from caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from caliper.baseline.domain.provenance_comparison import build_mismatches
from caliper.errors import ProvenanceMismatchError
from caliper.measurement import ScoringResult


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
    """
    mismatches = build_mismatches(
        expected_model_version=artefact.provenance_model_version,
        received_model_version=result.provenance.model_version.value,
        expected_criteria=artefact.provenance_criteria,
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
