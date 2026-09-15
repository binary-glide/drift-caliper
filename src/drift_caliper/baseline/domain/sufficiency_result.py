"""``SufficiencyResult`` -- the read-only outcome of a baseline sufficiency check.

See ``docs/domain-model.md`` (Value Object Inventory -- SufficiencyResult)
and ADR-005 (the library's default minimum threshold).

Produced by ``Baseline.check_sufficiency()``. The five fields are exactly
those ``docs/domain-model.md`` specifies; the domain model requires no
validators beyond field presence.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from drift_caliper.baseline.domain.data_quality_concern import DataQualityConcern


class SufficiencyResult(BaseModel):
    """Whether a ``Baseline`` has enough observations for reliable fitting.

    Read-only inspection (BIN-64 BR-6) -- producing one never modifies the
    baseline it was computed from. Immutable; equality by value.

    ``data_quality_concerns`` is a ``tuple``, not a ``Sequence`` holding a
    list. ``ConfigDict(frozen=True)`` stops a field being *rebound*; it does
    not freeze what the field points at, so a list-typed field left this
    type's documented immutability false -- a caller could ``.append()`` to a
    result the domain model promises cannot change (BIN-108). Pydantic
    coerces a list passed to the constructor into a tuple, so this costs
    callers nothing, and it makes the model hashable, which the list field
    had silently prevented.

    ``Baseline.observations`` wraps in ``tuple()`` for the same reason.
    **Tuples are the house convention for sequence fields on immutable
    domain types** -- see ``docs/domain-model.md``.
    """

    model_config = ConfigDict(frozen=True)

    is_sufficient: bool
    observation_count: int
    threshold: int
    gap: int
    data_quality_concerns: tuple[DataQualityConcern, ...]

    def __bool__(self) -> bool:
        """Truthiness mirrors ``is_sufficient`` (BIN-110 P0).

        Without this, a frozen Pydantic ``BaseModel`` falls back to
        ``object.__bool__`` -- unconditionally ``True`` regardless of
        ``is_sufficient`` -- so ``if baseline.check_sufficiency():`` would
        silently enter the fitting branch on an empty baseline. This type
        already *is* a yes/no answer to "is this baseline ready?", so
        ``bool()`` disagreeing with ``is_sufficient`` would itself be a
        footgun. Contrast with ``ScoringResult``/``Fitted*``, which have no
        such field and forbid ``bool()`` outright -- see
        ``tests/unit/test_truthiness.py``.
        """
        return self.is_sufficient
