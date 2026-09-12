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

🚨 **Surfaces 1 and 2 were weakened 2026-09-12 (BIN-124 round 3,
code-reviewer's Blocker 3) -- read this before trusting what they cover.**

They used to parse the reported *text* (``context["constraint"]``,
``FittingAdvisory.description``) to prove the number an engineer actually
reads matches the number Caliper enforces -- catching drift between the
two, which is the exact BIN-122 Instance 3 shape (the reported bound and
the enforced bound came from the same computation and still disagreed).
That is what "round-trips" meant for these two surfaces originally, and
it is a genuinely stronger claim than the one below.

**It was removed because it violated ADR-008** (*"error assertions use
type + context keys, never message text"*) -- regexing ``constraint`` and
``description`` is exactly the message-text assertion ADR-008 forbids,
raised by ``code-reviewer`` and correctly not overridden: the existing
``min_attainable_arl`` precedent this file's own module docstring cites as
its worked pattern is a **structured numeric field already in ``context``**,
not parsed prose -- that precedent argues for *adding a field*, not for
regexing a message, and no such field exists yet for ``MIN_TARGET_ARL`` or
``VERIFIED_ARL_FLOOR``.

**What surfaces 1 and 2 verify now, stated precisely, so this is not
misread the way three other disclosed limitations already were this
week:** ``test_min_target_arl_is_accepted_when_fed_back_after_rejection``
and ``test_verified_arl_floor_is_accepted_cleanly_when_fed_back`` verify
only that **the imported constant itself is accepted** when fed back --
**not** that the value reported in the error/advisory text still matches
that constant. **A future drift between the reported number and the
enforced number -- the exact BIN-122 Instance 3 class of bug -- would not
be caught by either test below**, because neither reads the reported text
any more.

**The stronger version is ticketed, not abandoned: BIN-134.** It needs a
structured field before it can be rewritten honestly -- proposed:
``InvalidParameterError.context["min_value"]``/``["max_value"]`` (floats,
alongside the existing ``constraint`` string) for surface 1, and a
``FittingAdvisory.boundary: float`` field for surface 2. Restore the
text-parsing assertion (or, better, a structured-field assertion) once
either lands.

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

import pytest

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline, fit_shewhart
from caliper.baseline.domain.parameter_guards import MIN_TARGET_ARL, VERIFIED_ARL_FLOOR
from caliper.errors import InsufficientBaselineError, InvalidParameterError
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.baseline_strategies import probe_baseline

# A fixed, ordinary, fittable baseline -- one per module, not one per
# test; see `probe_baseline()`.
_PROBE_BASELINE = probe_baseline()


# --- Surface 1: MIN_TARGET_ARL (ADR-011 hard floor) ---------------------------


def test_min_target_arl_is_accepted_when_fed_back_after_rejection() -> None:
    """``MIN_TARGET_ARL`` itself round-trips: refused just below it, accepted at it.

    🚨 **Weakened 2026-09-12 (BIN-124 round 3, code-reviewer's Blocker 3) --
    see this file's module docstring before trusting what this covers.**
    This asserts only that the **imported constant** ``MIN_TARGET_ARL`` is
    accepted when fed back -- it does **not** parse or check
    ``context["constraint"]`` any more, so it does **not** verify that the
    floor named in the error text an engineer actually reads still equals
    ``MIN_TARGET_ARL``. A future drift between the two (BIN-122's Instance
    3 class of bug) would pass this test silently. The stronger,
    text-verifying version is ticketed as **BIN-134**, blocked on adding a
    structured numeric field to ``InvalidParameterError.context`` (ADR-008
    forbids regexing ``constraint`` to get there another way).
    """
    with pytest.raises(InvalidParameterError):
        fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL - 1.0)

    # The round-trip this test still proves: the floor itself is accepted
    # (ADR-011's hard floor is inclusive -- refused strictly *below*
    # MIN_TARGET_ARL, accepted at it).
    result = fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL)
    assert result.requested_arl == MIN_TARGET_ARL


# --- Surface 2: VERIFIED_ARL_FLOOR (ADR-011 advisory line) --------------------


def test_verified_arl_floor_is_accepted_cleanly_when_fed_back() -> None:
    """``VERIFIED_ARL_FLOOR`` itself round-trips clean: flagged below it, clean at it.

    🚨 **Weakened 2026-09-12 (BIN-124 round 3, code-reviewer's Blocker 3) --
    see this file's module docstring before trusting what this covers.**
    This asserts only that the **imported constant** ``VERIFIED_ARL_FLOOR``
    is accepted with no advisory attached -- it does **not** parse or check
    ``FittingAdvisory.description`` any more, so it does **not** verify
    that the floor named in the advisory text an engineer actually reads
    still equals ``VERIFIED_ARL_FLOOR``. A future drift between the two
    (BIN-122's Instance 3 class of bug) would pass this test silently. The
    stronger, text-verifying version is ticketed as **BIN-134**, blocked
    on adding a structured numeric field to ``FittingAdvisory`` (ADR-008
    forbids regexing ``description`` to get there another way).
    """
    flagged = fit_shewhart(_PROBE_BASELINE, target_arl=200.0)
    assert len(flagged.advisories) == 1, (
        "expected exactly one flagged-tier advisory at target_arl=200.0 -- "
        "test precondition, not the assertion under test"
    )

    # The round-trip this test still proves: the floor itself lands clean.
    # classify_target_arl uses a strict `<` comparison against
    # VERIFIED_ARL_FLOOR (parameter_guards.py), so the floor value itself
    # must land in the CLEAN tier, not the flagged one.
    clean = fit_shewhart(_PROBE_BASELINE, target_arl=VERIFIED_ARL_FLOOR)
    assert clean.advisories == (), (
        f"target_arl=VERIFIED_ARL_FLOOR ({VERIFIED_ARL_FLOOR!r}) still "
        "carries a flagged-tier advisory -- the floor is being treated as "
        "inside its own flagged range, an off-by-one-boundary version of "
        "BIN-122's Instance 3."
    )


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
