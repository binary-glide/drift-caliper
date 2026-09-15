"""``direction`` must be narrowed before it is hashed (BIN-143).

`x in frozenset(...)` calls ``x.__hash__()`` **before** comparing anything, so
testing membership on a caller-supplied value hands control to the caller. A
list or dict leaked ``TypeError: unhashable type``; a ``str`` subclass with a
raising ``__hash__`` leaked whatever it chose. Three non-``CaliperError``
escapes from a public entry point.

🚨 **The reason it survived BIN-136's input-coverage grid is the more useful
finding.** ``direction`` was excused from ``COMPARISON_RAISES`` on the grounds
that it is *"compared against a frozenset of string literals"* — true of
``__eq__``, and **silent about ``__hash__``**. The grid makes a missing cell
visible; it cannot tell you that the reasoning filling a cell was aimed at the
wrong operation.

⚠️ **Rejection tests alone cannot express the whole contract here**, which is
why ``test_legitimate_str_subclass_is_still_accepted`` exists. The tempting fix
is ``type(value) is str``: it closes every leak below and refuses every
legitimate subclass with it. That test fails such a fix, and nothing else in
this file would.

The rejection cases themselves live in ``tests/support/exception_contract_registry``
so the grid counts them. This module holds what the grid cannot express.
"""

from __future__ import annotations

from typing import Any

import pytest

from drift_caliper.baseline import Baseline, FittedCUSUM, fit_cusum
from drift_caliper.errors import InvalidParameterError
from drift_caliper.measurement import ScoringResult
from drift_caliper.monitoring import Monitor
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.baseline_strategies import probe_baseline

_TARGET_ARL = 370.0


class _PlainSubclass(str):
    """A legitimate ``str`` subclass: no dunder overridden, nothing hostile."""


class _HashRaises(str):
    """Satisfies ``isinstance(x, str)`` and still hijacks ``__hash__``."""

    def __hash__(self) -> int:
        raise RuntimeError("hash exploded")


@pytest.fixture
def baseline() -> Baseline:
    return probe_baseline()


# ---------------------------------------------------------------------------
# The contract the rejection tests cannot state
# ---------------------------------------------------------------------------


def test_legitimate_str_subclass_is_still_accepted(baseline: Baseline) -> None:
    """A plain ``str`` subclass is a valid direction and must be accepted.

    🚨 **This is the test that fails the tempting fix.** Narrowing to
    ``type(value) is str`` would reject this, trading a leak for a false
    rejection of a valid input — the BIN-123 class. `isinstance` plus
    normalisation is the shape that satisfies both halves.
    """
    fitted = fit_cusum(
        baseline, target_arl=_TARGET_ARL, direction=_PlainSubclass("lower")
    )

    assert fitted.direction == "lower"


def test_an_accepted_subclass_is_normalised_to_exact_str(baseline: Baseline) -> None:
    """The stored value is an **exact** ``str``, not the subclass instance.

    ⚠️ Validating without normalising is not enough, and that is BIN-139's
    lesson arriving at a second site. An accepted subclass that reached the
    membership test — or was stored and hashed later — would still be able to
    raise from ``__hash__``. What reaches the hash has to *be* a ``str``.
    """
    fitted = fit_cusum(
        baseline, target_arl=_TARGET_ARL, direction=_HashRaises("two_sided")
    )

    assert type(fitted.direction) is str
    assert hash(fitted.direction) == hash("two_sided")


def test_normalisation_preserves_content_exactly(baseline: Baseline) -> None:
    """Normalisation is of **type only** — never content.

    ``str.__str__`` changes no characters. Pinned because the obvious
    alternative, ``str(value)``, dispatches to a hijackable ``__str__`` and
    could return anything at all.
    """
    fitted = fit_cusum(baseline, target_arl=_TARGET_ARL, direction=_HashRaises("upper"))

    assert fitted.direction == "upper"


# ---------------------------------------------------------------------------
# The second site, which the audit found rather than the report
# ---------------------------------------------------------------------------


def test_monitor_survives_a_hostile_direction_on_the_artefact(
    baseline: Baseline,
) -> None:
    """``Monitor.record()`` must not leak from a caller-supplied artefact.

    ⚠️ Reachable despite ``__init__``'s ``isinstance`` narrowing and the
    ``str`` field annotation: Pydantic coerces a subclass to an exact ``str``
    during *validation*, and ``model_copy(update=...)`` skips validation by
    design. **A field annotation is a validation-time guarantee, not a
    storage-time one.**
    """
    provenance = baseline.provenance_signature
    assert provenance is not None
    artefact = fit_cusum(baseline, target_arl=_TARGET_ARL).model_copy(
        update={"direction": _HashRaises("two_sided")}
    )

    result = Monitor(artefact).record(ScoringResultFactory(provenance=provenance))

    assert result.chart_type == "cusum"


def test_monitor_rejects_a_non_str_direction_on_the_artefact(
    baseline: Baseline,
) -> None:
    """A non-``str`` direction raises a ``CaliperError``, not ``TypeError``.

    ``model_construct`` bypasses validation entirely, so the field can hold
    anything. The guard reports the offending **type** rather than the value:
    describing a hostile object with ``repr()`` can itself raise, which is the
    BIN-118 hazard inside the error path.
    """
    good = fit_cusum(baseline, target_arl=_TARGET_ARL)
    # `model_construct` skips validation entirely, so the field can hold
    # anything. Typed as `dict[str, Any]` because ty otherwise reads the
    # unpacking as a candidate for `_fields_set`, which is `set[str] | None`.
    fields: dict[str, Any] = {**good.model_dump(), "direction": 7}
    artefact = FittedCUSUM.model_construct(None, **fields)
    observation: ScoringResult = ScoringResultFactory(
        provenance=baseline.provenance_signature or ProvenanceFactory()
    )

    with pytest.raises(InvalidParameterError) as exc_info:
        Monitor(artefact).record(observation)

    context = exc_info.value.context
    assert context["parameter"] == "direction"
    assert context["kind"] == "invalid"
    assert context["provided_type"] == "int"
