"""Shared mismatch-accumulation logic for provenance comparison.

Both the Phase I intra-baseline check (``Baseline.record()``'s
``_reject_if_provenance_differs``) and the Phase I/II boundary check
(``compare_provenance()``) raise the same ``ProvenanceMismatchError`` shape
for the same violation (ADR-002 "Category consistency with Phase I" /
`docs/domain-model.md` OQ-11). This module holds the one place that builds
``context["mismatches"]`` so the two boundaries cannot drift apart -- see
the ADR-002 Amendment's migration note 2, which requires
``_reject_if_provenance_differs`` to stop short-circuiting on the first
differing dimension and check both before raising, exactly as
``compare_provenance()`` does.

Deliberately typed over plain strings rather than ``Provenance`` --
``Baseline.record()`` compares two ``Provenance`` value objects, while
``compare_provenance()`` compares a ``Provenance`` against a
``FittedControlLimits`` artefact's flat ``provenance_model_version``/
``provenance_criteria`` string fields (ADR-004). Strings are the one shape
both call sites already have on hand without inventing a throwaway
``Provenance`` just to satisfy a shared signature.
"""

from __future__ import annotations


def build_mismatches(
    *,
    expected_model_version: str,
    received_model_version: str,
    expected_criteria: str,
    received_criteria: str,
) -> dict[str, dict[str, str]]:
    """Accumulate every differing provenance dimension into one mapping.

    Checks both dimensions unconditionally -- no short-circuit on the
    first difference found -- so a caller can raise once with every
    mismatch already collected (ADR-002 Amendment, "no first-checked-wins
    short-circuit"). Comparison is exact string equality: no stripping, no
    case folding, no Unicode normalisation (`docs/domain-model.md`
    "Criteria equality is exact").

    Returns:
        An empty mapping when both dimensions match; one entry per
        differing dimension otherwise, keyed by ``"model_version"`` and/or
        ``"scoring_criteria"``.
    """
    mismatches: dict[str, dict[str, str]] = {}
    if expected_model_version != received_model_version:
        mismatches["model_version"] = {
            "expected": expected_model_version,
            "received": received_model_version,
        }
    if expected_criteria != received_criteria:
        mismatches["scoring_criteria"] = {
            "expected": expected_criteria,
            "received": received_criteria,
        }
    return mismatches
