"""Scores must be exact ``float``s before anything hashes them (BIN-149).

``_has_zero_variance`` calls ``set(scores)`` and ``Baseline``'s sufficiency
probe builds a set comprehension over the same values — **and ``set()`` hashes
every element.** A ``float`` subclass whose ``__hash__`` raises therefore
escaped all three ``fit_*`` functions and ``check_sufficiency()`` as a bare
``RuntimeError``.

⚠️ **Reachable despite ``ScoringResult``'s validator.** It coerces a ``float``
subclass to an exact ``float`` — but ``model_construct()`` and
``model_copy(update=...)`` skip validation **by design**, and
``Baseline.record()``'s ``isinstance`` check passes such an instance. **A
Pydantic field annotation is a validation-time guarantee, not a storage-time
one**, which is the third time that fact has produced a defect on this project.

🚨 **Found by the audit BIN-143 mandated, not by the bug it was chasing.**
Recorded then as a strict-xfail ``known_leak`` rather than fixed in passing;
this module is what let those markers be deleted.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from drift_caliper.baseline import Baseline, fit_cusum, fit_ewma, fit_shewhart
from drift_caliper.errors import InvalidObservationError
from drift_caliper.measurement import ScoringResult
from tests.factories import ProvenanceFactory, ScoringResultFactory

_TARGET_ARL = 370.0
_ENOUGH = 120


class _HashRaisingFloat(float):
    """A ``float`` subclass whose ``__hash__`` raises. BIN-149's input.

    ⚠️ ``__eq__`` is defined alongside ``__hash__`` even though only the hash
    is under test. CodeQL's *inconsistent equality and hashing* rule flags a
    class overriding one without the other, and it is right to: a type whose
    hash and equality disagree misbehaves in sets and dicts in ways that are
    miserable to debug. Defining both is also what BIN-121's ``_HostileStr``
    already does, so this follows the convention rather than suppressing the
    rule.
    """

    def __hash__(self) -> int:
        raise RuntimeError("float hash exploded")

    def __eq__(self, other: object) -> bool:
        return float.__eq__(self, other)


class _FloatRaisingFloat(float):
    """Hijacks ``__float__`` as well, to pin which primitive is used.

    🚨 ``float(value)`` dispatches here and raises; ``float.__float__(value)``
    cannot be overridden and returns a clean ``float``. A fix written with the
    former would pass every other test in this file and still leak.
    """

    def __hash__(self) -> int:
        raise RuntimeError("float hash exploded")

    def __eq__(self, other: object) -> bool:
        # Defined for the same reason as _HashRaisingFloat's -- see above.
        return float.__eq__(self, other)

    def __float__(self) -> float:
        raise RuntimeError("float conversion exploded")


def _baseline_containing(first: ScoringResult) -> Baseline:
    """A sufficient baseline whose first observation is ``first``."""
    provenance = first.provenance
    baseline = Baseline()
    baseline.record(first)
    # Deterministic by seed -- these are baseline scores, not secrets.
    rng = random.Random(20260916)  # noqa: S311
    for _ in range(_ENOUGH):
        baseline.record(
            ScoringResultFactory(provenance=provenance, score=rng.gauss(8.0, 0.5))
        )
    return baseline


def _bypassing_validation(score: object) -> ScoringResult:
    """A ``ScoringResult`` built without validation, as Pydantic permits."""
    fields: dict[str, Any] = {
        "score": score,
        "reasoning": "constructed without validation",
        "provenance": ProvenanceFactory(),
    }
    return ScoringResult.model_construct(None, **fields)


_ENTRY_POINTS = [
    pytest.param(lambda b: b.check_sufficiency(), id="check_sufficiency"),
    pytest.param(lambda b: fit_ewma(b, target_arl=_TARGET_ARL), id="fit_ewma"),
    pytest.param(lambda b: fit_cusum(b, target_arl=_TARGET_ARL), id="fit_cusum"),
    pytest.param(lambda b: fit_shewhart(b, target_arl=_TARGET_ARL), id="fit_shewhart"),
]


@pytest.mark.parametrize("call", _ENTRY_POINTS)
@pytest.mark.parametrize(
    "hostile", [_HashRaisingFloat, _FloatRaisingFloat], ids=["hash", "hash_and_float"]
)
def test_a_hash_raising_score_never_escapes(
    call: Callable[[Baseline], object], hostile: type[float]
) -> None:
    """No entry point leaks a non-``CaliperError`` for a hostile score.

    All four are parametrised because ``set(scores)`` is reached through the
    shared ``spc_numerics`` helper — ⚠️ but that sharing is exactly what a
    future per-chart "optimisation" would undo, and then only one of these
    would fail.
    """
    baseline = _baseline_containing(_bypassing_validation(hostile(8.0)))

    call(baseline)


@pytest.mark.parametrize("call", _ENTRY_POINTS)
def test_a_non_float_score_raises_a_caliper_error(
    call: Callable[[Baseline], object],
) -> None:
    """A score that is not a float at all is an invalid observation."""
    baseline = _baseline_containing(_bypassing_validation("not a number"))

    with pytest.raises(InvalidObservationError):
        call(baseline)


# ---------------------------------------------------------------------------
# The contract the rejection tests cannot state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call", _ENTRY_POINTS)
def test_numpy_float64_scores_are_still_accepted(
    call: Callable[[Baseline], object],
) -> None:
    """🚨 The test that fails the tempting fix.

    ``numpy.float64`` **is** a ``float`` subclass and hashes perfectly well.
    Narrowing to ``type(value) is float`` would close every leak above and
    reject this — trading a leak for a false rejection of an input any
    numerically-minded caller will produce. That is the BIN-123 class, and it
    is the reason the guard is ``isinstance`` plus normalisation.
    """
    provenance = ProvenanceFactory()
    baseline = Baseline()
    # Deterministic by seed -- these are baseline scores, not secrets.
    rng = random.Random(20260916)  # noqa: S311
    for _ in range(_ENOUGH + 1):
        baseline.record(
            ScoringResultFactory(
                provenance=provenance, score=np.float64(rng.gauss(8.0, 0.5))
            )
        )

    call(baseline)


def test_normalisation_preserves_the_value_exactly() -> None:
    """Normalisation is of **type** only — never of value.

    A fitted mean computed from normalised scores must equal one computed from
    the raw values. Pinned because the obvious alternative, rounding or casting
    through a narrower type, would silently change every control limit.
    """
    provenance = ProvenanceFactory()
    raw = [8.0, 8.25, 7.5, 8.125] * 40
    baseline = Baseline()
    for score in raw:
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))

    fitted = fit_ewma(baseline, target_arl=_TARGET_ARL)

    assert fitted.baseline_mean == sum(raw) / len(raw)
