"""``DataQualityConcern`` -- a data-quality issue found during a sufficiency check.

See ``docs/domain-model.md`` (Value Object Inventory -- DataQualityConcern).

Scaffold only: this value object's shape (both fields, frozen, no
validators -- the domain model specifies none beyond field presence) is
already exactly what ``docs/domain-model.md`` documents, so there is
nothing further for ``domain-implementer`` to add here. It exists as its
own module so ``tests/unit/baseline/test_baseline_sufficiency.py`` and
``tests/bdd/steps/baseline_sufficiency_check_steps.py`` can import it
before ``Baseline.check_sufficiency()`` (which actually produces one) is
implemented -- see ``check_sufficiency()``'s docstring in ``baseline.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DataQualityConcern(BaseModel):
    """A single data-quality issue found alongside a sufficiency check.

    E.g. a baseline whose observations all carry an identical score --
    ``kind == "zero_variance"`` (BIN-64 SC7/SC12). Immutable; equality by
    value.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    description: str
