"""Binary (``0.0``/``1.0``) Phase I baselines for the Bernoulli CUSUM tests.

Every observation shares one of two ``ScoringResult`` objects -- one pass,
one fail -- so a 300,000-observation baseline builds in well under a second
(ADR-014 Decision 18 item 3: "Build each baseline with one shared
``ScoringResult``"). A ``Baseline`` only reads each observation's score and
provenance, so sharing the object changes nothing it computes.
"""

from __future__ import annotations

from drift_caliper.baseline import Baseline
from drift_caliper.measurement import Provenance, ScoringResult
from tests.factories import ProvenanceFactory


def binary_baseline(
    m: int, f: int, *, provenance: Provenance | None = None
) -> tuple[Baseline, Provenance]:
    """A baseline of ``m`` observations, the first ``f`` of them failures.

    Returns the baseline and the provenance every observation carries, which
    a Phase II ``Monitor`` test needs for its own observations.
    """
    if not 0 <= f <= m:
        raise ValueError("f must be between 0 and m")
    shared = provenance or ProvenanceFactory()
    passed = ScoringResult(score=1.0, reasoning="", provenance=shared)
    failed = ScoringResult(score=0.0, reasoning="", provenance=shared)
    baseline = Baseline()
    for index in range(m):
        baseline.record(failed if index < f else passed)
    return baseline, shared
