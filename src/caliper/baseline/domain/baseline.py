"""``Baseline`` -- an ordered, provenance-consistent collection of observations.

See ``docs/domain-model.md`` (Object Map -- Baseline, the one mutable
collection) and ``docs/architecture/adr/002-error-contract-exception-taxonomy.md``
for the error contract enforced by ``record()``.

.. note::
    Scaffold only, written by ``backend-test-writer`` (BIN-63) so that
    ``tests/unit/baseline/test_baseline.py`` and
    ``tests/bdd/steps/phase_i_baseline_collection_steps.py`` import and run
    without ``ImportError``/``ModuleNotFoundError`` -- the tests are red
    because ``record()`` raises ``NotImplementedError``, not because the
    module is missing. ``domain-implementer`` (BIN-63) replaces
    ``record()``'s body with the four invariants described in
    ``docs/domain-model.md``:

    1. Provenance homogeneity -- reject a differing model version or
       criteria with ``ProvenanceMismatchError``.
    2. Insertion order is preserved (load-bearing, not presentational).
    3. Recorded observations are immutable -- already guaranteed by
       ``ScoringResult`` being a frozen Pydantic model; nothing extra is
       needed here beyond not copying or rebuilding the observation.
    4. Recording requires a complete ``ScoringResult`` -- reject anything
       else with ``InvalidObservationError`` before the baseline is
       modified.
"""

from __future__ import annotations

from collections.abc import Sequence

from caliper.measurement import Provenance, ScoringResult


class Baseline:
    """An ordered, provenance-consistent collection of scored observations.

    The one mutable object in Caliper's domain model. A new ``Baseline`` is
    empty and accepts observations via ``record()`` -- see
    ``docs/domain-model.md`` (Object Map -- Baseline) for the four
    invariants this scaffold does not yet enforce.
    """

    def __init__(self) -> None:
        self._observations: list[ScoringResult] = []
        self._provenance_signature: Provenance | None = None

    @property
    def observations(self) -> Sequence[ScoringResult]:
        """The recorded observations, in the order they were recorded."""
        return tuple(self._observations)

    @property
    def observation_count(self) -> int:
        """The number of observations currently in the baseline."""
        return len(self._observations)

    @property
    def provenance_signature(self) -> Provenance | None:
        """The provenance every observation must match, or ``None`` if empty."""
        return self._provenance_signature

    def record(self, result: ScoringResult) -> None:
        """Record a scoring result as a new observation.

        Not yet implemented -- see ``docs/domain-model.md`` (Object Map --
        Baseline) for the four invariants ``domain-implementer`` (BIN-63)
        must enforce: provenance homogeneity, insertion order, observation
        immutability, and rejecting an incomplete scoring result.

        Args:
            result: The scoring result to record. Only a complete
                ``ScoringResult`` (score, reasoning, provenance) is
                accepted; anything else is rejected with
                ``InvalidObservationError`` once implemented.

        Raises:
            NotImplementedError: always, in this scaffold.
        """
        raise NotImplementedError(
            "Baseline.record() is not yet implemented -- see BIN-63 "
            "(domain-implementer) and docs/domain-model.md (Object Map -- "
            "Baseline)"
        )
