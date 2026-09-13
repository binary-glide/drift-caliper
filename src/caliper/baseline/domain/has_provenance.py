"""``HasProvenance`` -- the two-attribute provenance protocol.

A ``@runtime_checkable`` ``Protocol`` carrying exactly the two provenance
attributes that ``compare_provenance`` reads: ``provenance_model_version``
and ``provenance_criteria``. It is a strict subset of
``FittedControlLimits`` -- every conformer of that protocol satisfies this
one, but not the reverse.

Introduced by ADR-004's 2026-09-12 amendment (BIN-135) to separate the
reporting/audit contract (``FittedControlLimits``) from the provenance-
comparison contract. ``compare_provenance`` accepts any
``HasProvenance``-satisfying object; ``Monitor`` continues to require
the full ``FittedControlLimits`` (and further narrows to the three
concrete ``Fitted*`` types at construction).

This protocol does **not** validate attribute types or semantics at
runtime -- ``@runtime_checkable`` verifies attribute **names** only.
Type and content validation live in ``compare_provenance``'s own guards
(BIN-127/BIN-139), not here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class HasProvenance(Protocol):
    """Two-attribute provenance contract for ``compare_provenance``.

    Any object exposing readable ``provenance_model_version`` and
    ``provenance_criteria`` string attributes satisfies this protocol.
    ``compare_provenance`` uses only these two attributes; it does not
    need the full ``FittedControlLimits`` surface.
    """

    @property
    def provenance_model_version(self) -> str:
        """The judge model version from the baseline's provenance."""
        ...

    @property
    def provenance_criteria(self) -> str:
        """The scoring criteria from the baseline's provenance."""
        ...
