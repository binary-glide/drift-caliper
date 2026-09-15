"""Contract-composition tests (BIN-122 item 2): every reported bound round-trips.

**The property.** Any number Caliper emits to a caller as a bound, floor,
or recommendation must itself be an accepted input if fed straight back.
The failure this guards against needs no hostile input at all -- BIN-122's
own "Instance 3" found it by doing exactly what Caliper's own error told an
engineer to do:

```
InvalidParameterError.context["min_attainable_arl"] == 1158.3137041946566
recovery_hint: "Choose a target_arl at or above that value"

fit_cusum(target_arl=1158.3137041946566)  ->  InvalidParameterError, again
```

The reported bound was an open infimum; the attainable floor sat slightly
above it. "Errors are UX" (``CLAUDE.md``) and a bound that misdirects the
reader who follows it exactly is the sharpest version of that failure.

**``min_attainable_arl`` itself is already fixed and tested** (BIN-117,
``cusum_fitting._min_attainable_arl0``'s own docstring, and
``test_cusum_fitting.py``'s
``test_fits_successfully_when_target_arl_equals_the_minimum_attainable_exactly``)
-- used here as the worked pattern, per BIN-122's own instruction, not
re-derived. This file covers the three remaining known surfaces named in
BIN-122 and its scope-survey comment:

1. **``MIN_TARGET_ARL`` (100.0, ADR-011's hard floor)** -- reported in
   ``InvalidParameterError.context["constraint"]`` and in the same error's
   ``recovery_hint`` whenever ``target_arl`` is refused as too low.
2. **``VERIFIED_ARL_FLOOR`` (370.0, ADR-011's advisory line)** -- reported
   in ``FittingAdvisory.description`` whenever a fit lands in the flagged
   tier (``[100, 370)``).
3. **``SufficiencyResult``'s reported gap** -- the ``need``/``have``
   figures ``InsufficientBaselineError.context`` carries, and the exact
   observation count its ``recovery_hint`` tells an engineer to collect.

``SufficiencyResult``'s own *threshold-selection* logic, ``adequate()``
(ADR-005's target-dependent middle tier), is explicitly **out of scope**
here -- it is unimplemented (``adequate()`` does not exist yet; see
``CLAUDE.md``'s ADR-005 section and BIN-122's scope-survey comment), so
there is nothing yet to round-trip. That surface belongs to BIN-114.

✅ **Surfaces 1 and 2 were restored 2026-09-13 by BIN-134** — read this,
because the file spent a day asserting materially less than it appeared to.

Between 2026-09-12 and then, both surfaces checked only that the imported
constant was *accepted* when fed back. They could **not** detect drift
between the number an engineer reads and the number the library enforces,
which is the entire point and is BIN-117's Instance 3 class of defect —
where the reported bound and the enforced bound came from the same
computation and still disagreed.

The original version got the property right and the mechanism wrong: it
regexed the number out of ``context["constraint"]`` and
``FittingAdvisory.description``, which ADR-008 forbids (*never assert on
message text*), because wording is free to change without notice. A guard
built on prose fails silently the first time someone rewords an error.

**BIN-134 supplied the missing mechanism** — ``context["min_value"]`` /
``["max_value"]`` / ``["min_inclusive"]`` / ``["max_inclusive"]``, and
``FittingAdvisory.boundary`` — so each surface now asserts *reported ==
enforced* on a structured numeric field, feeds that value back, **and**
checks ``nextafter`` across the edge so the reported boundary is the exact
edge rather than an approximation of one. The prose is still emitted for
humans; it is simply not what these assert on.

**What this file cannot catch, stated rather than left implicit.**

* **Only three surfaces.** A future fourth reported bound (a new ADR, a new
  advisory kind) is not covered until this file -- or a sibling -- is
  extended for it. There is no scanner-style completeness guard here (cf.
  ``BIN-124``'s Hypothesis-bound scanner) because these are hand-written
  probes of specific, individually-known text formats, not a mechanically
  enumerable syntactic pattern.
* **A round-trip test only proves the reported value is *accepted*.** It
  says nothing about whether the *behaviour* at that exact value is
  correct in some other respect (e.g. whether the flagged/clean tier
  boundary is drawn in the statistically right place) -- that is ADR-011's
  and the fitting stories' own job, not this file's.
* **Surfaces 1 and 2 no longer verify that the reported text matches the
  enforced constant -- see the blocked-in-bold section above.** Surface 3
  (``SufficiencyResult``'s gap) is unaffected: ``context["have"]``/
  ``context["need"]`` are already structured numeric fields, not parsed
  prose, so it never depended on the pattern ADR-008 forbids.
"""

from __future__ import annotations

import math

import pytest

from drift_caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, fit_shewhart
from drift_caliper.baseline.domain.parameter_guards import (
    MIN_TARGET_ARL,
    VERIFIED_ARL_FLOOR,
)
from drift_caliper.errors import InsufficientBaselineError, InvalidParameterError
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.baseline_strategies import probe_baseline

# A fixed, ordinary, fittable baseline -- one per module, not one per
# test; see `probe_baseline()`.
_PROBE_BASELINE = probe_baseline()


# --- Surface 1: MIN_TARGET_ARL (ADR-011 hard floor) ---------------------------


def test_reported_min_target_arl_equals_the_enforced_floor() -> None:
    """The floor the error **reports** is the floor the library **enforces**.

    ✅ **Restored 2026-09-13 by BIN-134**, which added
    ``context["min_value"]``/``["max_value"]`` as structured numeric
    fields. Between 2026-09-12 and then this test was knowingly weaker: it
    checked only that the imported constant was accepted, and could not
    detect drift between the number an engineer reads and the number the
    library applies. That is BIN-117's Instance 3 class of defect, where
    both came from the same computation and still disagreed.

    ⚠️ **Reads the bound from the error, never from the message.** ADR-008
    forbids asserting on message text, and an earlier attempt to regex
    ``constraint`` was correctly rejected for exactly that. The prose is
    still emitted for humans; it is simply not what this asserts on.
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)

    context = exc_info.value.context

    # 1. Reported == enforced. The assertion the weakened version lost.
    assert context["min_value"] == MIN_TARGET_ARL
    assert context["min_inclusive"] is True

    # 2. The reported bound round-trips: feeding it straight back is accepted.
    result = fit_shewhart(_PROBE_BASELINE, target_arl=context["min_value"])
    assert result.requested_arl == MIN_TARGET_ARL

    # 3. Inclusive means inclusive -- just below it is still refused, so the
    #    reported boundary is the exact edge and not an approximation of one.
    with pytest.raises(InvalidParameterError):
        fit_shewhart(
            _PROBE_BASELINE, target_arl=math.nextafter(context["min_value"], 0.0)
        )


# --- Surface 2: VERIFIED_ARL_FLOOR (ADR-011 advisory line) --------------------


def test_reported_advisory_boundary_equals_the_enforced_tier_edge() -> None:
    """The boundary the advisory **reports** is the tier edge the library applies.

    ✅ **Restored 2026-09-13 by BIN-134**, which added
    ``FittingAdvisory.boundary``. ADR-011's advisory previously embedded
    ``370.0`` in a sentence and nowhere else, so this could only check that
    the imported constant landed clean -- not that the advisory an engineer
    actually reads names the same number.
    """
    flagged = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
    assert len(flagged.advisories) == 1, (
        "expected exactly one flagged-tier advisory at target_arl=200.0 -- "
        "test precondition, not the assertion under test"
    )

    # 1. Reported == enforced.
    boundary = flagged.advisories[0].boundary
    assert boundary == VERIFIED_ARL_FLOOR

    # 2. The reported boundary round-trips, and lands in the CLEAN tier --
    #    classify_target_arl uses a strict `<`, so the edge itself is clean.
    clean = fit_shewhart(_PROBE_BASELINE, target_arl=boundary)
    assert clean.advisories == ()

    # 3. Just below it is still flagged, so the reported number is the exact
    #    edge rather than somewhere near it.
    below = fit_shewhart(_PROBE_BASELINE, target_arl=math.nextafter(boundary, 0.0))
    assert len(below.advisories) == 1


# --- Surface 3: SufficiencyResult's reported gap ------------------------------


def _insufficient_baseline(short_by: int) -> Baseline:
    """Build a baseline exactly ``short_by`` observations below the default."""
    baseline = Baseline()
    provenance = ProvenanceFactory()
    count = DEFAULT_SUFFICIENCY_THRESHOLD - short_by
    for i in range(count):
        baseline.record(ScoringResultFactory(provenance=provenance, score=float(i % 5)))
    return baseline


def test_reported_observation_gap_is_exactly_enough_to_reach_sufficiency() -> None:
    """The exact shortfall ``InsufficientBaselineError`` reports closes the gap.

    Triggers the rejection from an intentionally-short baseline, reads
    ``context["have"]``/``context["need"]`` (the same two numbers the
    ``recovery_hint`` tells the engineer to act on -- "record at least
    {gap} more scoring results"), records precisely that many additional
    observations, and asserts the identical fitting call now succeeds.
    This is the sufficiency-threshold analogue of the ``min_attainable_arl``
    worked pattern: the number Caliper reports as "how much more you need"
    must, when acted on literally, actually be enough.
    """
    baseline = _insufficient_baseline(short_by=10)

    try:
        fit_shewhart(baseline, target_arl=370.0)
        raised = False
    except InsufficientBaselineError as exc:
        raised = True
        have = exc.context["have"]
        need = exc.context["need"]

    assert raised, "an intentionally-insufficient baseline unexpectedly fitted"
    gap = need - have
    assert gap == 10

    provenance = baseline.observations[0].provenance
    for i in range(gap):
        baseline.record(ScoringResultFactory(provenance=provenance, score=float(i % 5)))

    # The round-trip: recording exactly the reported gap must be enough --
    # not one short, not needing a margin above it.
    result = fit_shewhart(baseline, target_arl=370.0)
    assert result.observation_count == need


__all__: list[str] = []
