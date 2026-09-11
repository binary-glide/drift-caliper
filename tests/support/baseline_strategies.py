"""Shared Hypothesis strategy and baseline builder for the ARL property tests.

Consolidated under BIN-124 from four byte-identical copies:
``_baseline_scores_strategy()``/``_is_fittable()``/``_MIN_FITTABLE_SPREAD``
and, in a second review pass on the same ticket, ``_baseline_from_scores()``
-- all four had accreted independently across
``tests/unit/baseline/test_{ewma,cusum,shewhart}_arl_simulated_properties.py``
(BIN-84's "Part 3" files) plus this ticket's own new meta-test. Every copy
was verified identical in behaviour before merging -- the only variation
found anywhere was minor docstring wording on ``_baseline_scores_strategy``
itself (each file pointing back to this one as the canonical explanation),
never in a constant, a predicate, or a function body.

**Why one definition matters, not just tidiness (BIN-124).** The floor this
module defines exists to dodge a real, currently-true fact about
``caliper.baseline.domain.spc_numerics._moving_range_sigma``: a baseline
whose consecutive-score spread is too small underflows its moving-range
sigma estimate to exactly zero and is rejected with
``DegenerateBaselineError`` (BIN-119). That fact can change -- the floor
could need to move, tighten, or gain a sibling condition, the next time a
new rejection narrows the legal input space (the general rule this ticket
exists to guard, see ``tests/unit/baseline/test_baseline_scores_strategy_contract.py``).
Triplicated logic means independent edits, found and fixed once and then
discovered to have silently left more latent copies behind -- twice now on
this same ticket (the strategy itself, then ``_baseline_from_scores``,
caught by `code-reviewer` on the first pass). One definition means one
edit.

**Do not reintroduce a per-file copy of anything in this module.** If a new
ARL property (or meta-) test file needs a fittable baseline, import from
here.
"""

from __future__ import annotations

from hypothesis import strategies as st

from caliper.baseline import DEFAULT_SUFFICIENCY_THRESHOLD, Baseline
from tests.factories import ProvenanceFactory, ScoringResultFactory

# BIN-123: `len(set(scores)) > 1` is no longer a sufficient definition of
# "non-degenerate". BIN-119 added a second rejection -- a baseline whose
# *moving-range aggregate* underflows to zero -- and `[0.0] * 149 + [5e-324]`
# satisfies the old filter (two distinct values) while the library now
# correctly refuses to fit it.
#
# That made this strategy generate inputs that are illegal by construction,
# so the property test failed whenever Hypothesis happened to find one.
# It is a latent flake rather than a constant failure: a fresh run passes,
# and the counterexample only replays deterministically once it is in
# `.hypothesis/examples`. CI starts with an empty database, which is why
# PR #46 went green.
#
# The floor below is a *test-side sufficient condition*, deliberately not a
# reimplementation of `_moving_range_sigma` -- duplicating production
# arithmetic here is the self-cancelling-helper pattern this project has
# hit five times. It only has to be strict enough that no drawn baseline can
# underflow, not to agree with the library's exact threshold.
#
# Margin, so the constant is not a magic number: by the triangle inequality
# the sum of consecutive absolute differences is at least `max - min`, so a
# spread of `1e-6` forces a mean moving range of at least
# `1e-6 / (n - 1)` -- about `6.7e-9` here, some 300 orders of magnitude above
# the underflow floor near `4.9e-324`. It does not meaningfully shrink the
# `[-10.0, 10.0]` space the properties explore.
#
# ⚠️ Why a floor rather than catching `DegenerateBaselineError` in the test
# body and calling `assume(False)`: that alternative defers to the library's
# own definition of degenerate, which sounds better and is worse. It would
# silently discard any future case where the library *over-rejects valid
# data* -- which is exactly the BIN-123 failure class, and exactly what this
# project most needs to stay visible. An independent floor turns that into a
# test failure instead of a filtered-away example.
# (Raised by code-reviewer on BIN-123, 2026-09-11.)
#
# ⚠️ Generalisable: every new rejection in `src/` can turn an existing
# Hypothesis strategy into a generator of illegal inputs. BIN-117 taught
# this once (its `arl_low` strategy) and BIN-119 repeated it here -- twice,
# in fact, since the same fix then had to be copied into all three files
# this module now replaces. BIN-124 is the standing guard against a third
# repeat: see the meta-test in
# ``tests/unit/baseline/test_baseline_scores_strategy_contract.py``, which
# asks the library itself whether every draw below is still legal, rather
# than relying on this comment being re-read at the moment of a future fix.
MIN_FITTABLE_SPREAD = 1e-6


def is_fittable(scores: list[float]) -> bool:
    """Reject draws the library legitimately refuses to fit.

    Excludes both the all-identical (zero-variance) draw and the
    vanishing-spread draw whose mean moving range underflows to zero.
    """
    return max(scores) - min(scores) >= MIN_FITTABLE_SPREAD


def baseline_scores_strategy(
    size: int = DEFAULT_SUFFICIENCY_THRESHOLD,
) -> st.SearchStrategy[list[float]]:
    """Hypothesis strategy for a fixed-size, non-degenerate list of baseline scores.

    Fixed size (``min_size == max_size``) so every generated example
    already satisfies ``check_sufficiency()`` -- the property under test is
    about the calibration, not about baseline sufficiency, which BIN-84's
    "Part 1" files already cover. ``.filter`` excludes the all-identical
    (zero-variance) draw and the vanishing-spread draw described in
    ``MIN_FITTABLE_SPREAD``'s comment above, since either is a
    ``DegenerateBaselineError`` -- a different, already-covered code path,
    not the property any caller of this strategy is testing.

    ``size`` defaults to ``DEFAULT_SUFFICIENCY_THRESHOLD`` -- every current
    caller uses the default; a future caller needing a different fixed size
    (while remaining sufficient) may override it.
    """
    return st.lists(
        st.floats(
            min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
        min_size=size,
        max_size=size,
    ).filter(is_fittable)


def baseline_from_scores(scores: list[float]) -> Baseline:
    """Build a ``Baseline`` from an explicit list of scores, one shared provenance.

    Consolidated under BIN-124 (second review pass) from four byte-identical
    copies -- see the module docstring. Carries no rejection logic of its
    own, unlike ``is_fittable()``/``baseline_scores_strategy()`` above; it
    is pure setup, which is exactly why its earlier duplication was lower
    risk than theirs but still worth collapsing to one definition rather
    than a fourth.
    """
    baseline = Baseline()
    provenance = ProvenanceFactory()
    for score in scores:
        baseline.record(ScoringResultFactory(provenance=provenance, score=score))
    return baseline
