"""``SufficiencyResult`` -- the read-only outcome of a baseline sufficiency check.

See ``docs/domain-model.md`` (Value Object Inventory -- SufficiencyResult)
and ADR-005 (the library's default minimum threshold).

Scaffold only: this value object's shape (the five fields, frozen, no
validators -- the domain model specifies none beyond field presence) is
already exactly what ``docs/domain-model.md`` documents, so there is
nothing further for ``domain-implementer`` to add here. It exists as its
own module so ``tests/unit/baseline/test_baseline_sufficiency.py`` and
``tests/bdd/steps/baseline_sufficiency_check_steps.py`` can import it
before ``Baseline.check_sufficiency()`` (which actually produces one) is
implemented -- see ``check_sufficiency()``'s docstring in ``baseline.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from caliper.baseline.domain.data_quality_concern import DataQualityConcern


class SufficiencyResult(BaseModel):
    """Whether a ``Baseline`` has enough observations for reliable fitting.

    Read-only inspection (BIN-64 BR-6) -- producing one never modifies the
    baseline it was computed from. Immutable; equality by value.
    """

    model_config = ConfigDict(frozen=True)

    is_sufficient: bool
    observation_count: int
    threshold: int
    gap: int
    data_quality_concerns: Sequence[DataQualityConcern]
