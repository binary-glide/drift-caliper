"""Meta-test (BIN-124): the shared baseline-scores strategy stays legal.

**The general rule this file exists to guard, stated once so it need not be
re-derived at the next incident:** every new rejection added in ``src/``
narrows the legal input space, and any Hypothesis strategy that already
draws from the old, wider space silently becomes a generator of illegal
inputs. The strategy does not fail the moment the rejection lands -- it
fails later, randomly, once Hypothesis's search happens to find the
now-illegal region, in whichever branch is unlucky enough to be running at
the time (``BIN-117``, then ``BIN-119`` again the same day: see
``tests/support/baseline_strategies.py``'s module docstring for the
incident history and the counterexample that made PR #46 go green when it
should not have).

**What this test actually does.** ``tests/support/baseline_strategies.py``
now holds the one definition of ``baseline_scores_strategy()`` shared by
all three ``test_{ewma,cusum,shewhart}_arl_simulated_properties.py`` files
(consolidated from three identical copies under this same ticket). This
test draws from that shared strategy and asserts, for every draw, that
**all three public fitting entry points accept it** --
``drift_caliper.baseline.fit_ewma``/``fit_cusum``/``fit_shewhart``, the exact
functions an engineer calls, at a fixed, already-proven-attainable
``target_arl``. Nothing here reimplements ``is_fittable()``'s predicate,
``_has_zero_variance()``, or ``_moving_range_sigma()`` -- it asks the
library whether a draw fits, it does not model whether one should.

**This deliberately catches failure in both directions, and that is not
incidental.**

1. **The BIN-124 direction.** A new rejection lands in ``src/`` (a chart's
   own zero-variance guard, or the shared moving-range sigma guard in
   ``spc_numerics.py``, or anything else reachable from a scores-only
   baseline) and ``baseline_scores_strategy()``'s ``is_fittable()`` filter
   was not updated to exclude the newly-illegal region. This test fails
   with the offending draw and the exception the library raised.
2. **The BIN-123 direction, and it matters just as much.** If a future
   change makes the library *over-reject* data it should fit -- exactly
   the class of bug ``BIN-123`` itself was (a perfectly representable
   mean, rejected because an unrelated intermediate overflowed) -- this
   test also fails, because ``is_fittable()`` still says the draw should
   have been accepted. **The fix for a failure here is never to narrow the
   strategy until it stops failing.** That would launder a real library
   regression into "the test suite is passing" the same way
   ``assume(False)`` on a caught ``CaliperError`` would (rejected as an
   option on ``BIN-124`` for exactly this reason -- see
   ``tests/support/baseline_strategies.py``). Work out which direction the
   failure is in first: does this baseline look like data Caliper should
   be able to fit? If yes, this is a library bug. If no,
   ``is_fittable()``'s floor needs to move to exclude it.

**Entry-point choice, and the budget it costs.** All three public
``fit_*`` functions are called per draw, not just one. Measured directly:
for the *scores* dimension specifically, ``fit_ewma``/``fit_cusum``/
``fit_shewhart`` share the exact same sufficiency check and delegate to
the exact same ``spc_numerics._moving_range_sigma`` for the guard
``MIN_FITTABLE_SPREAD`` exists to dodge -- so any one of them would already
exercise that shared path. But each chart's *zero-variance* guard
(``_has_zero_variance``) is a separately maintained, currently-identical
copy in each of the three ``*_fitting.py`` modules, not a shared helper --
so a future change that diverges only one chart's copy (e.g. a chart
deciding to also reject near-zero variance below some new epsilon) would
be invisible to a single-chart check. Calling all three is the cost of
covering that duplication; calling only one would be cheaper but would
silently exclude exactly the kind of single-chart drift this project has
already hit once (``_has_zero_variance`` itself, BIN-94/95).

Measured: ``fit_cusum``/``fit_shewhart`` cost well under a millisecond
each; ``fit_ewma``'s Markov-chain calibration dominates at ~49ms per call
(warmed up, not import overhead). At ``max_examples=100`` that is
~4.9 seconds of ``fit_ewma`` time plus negligible cost for the other two
and for building each draw's ``Baseline`` (~0.1ms) -- measured total
runtime for this file is stated in the implementing story's completion
report; not marked ``slow`` at that figure.

**What this test cannot catch, stated rather than left implicit.**

* **Random draws are confined to ``[-10.0, 10.0]`` and cannot reach an
  extreme magnitude like ``1e307`` -- not "rarely", *cannot*, by
  construction** (``code-reviewer``, first review pass on this ticket).
  That range is what makes the three ARL property tests meaningful (they
  simulate run lengths through it), so it must not widen to chase this.
  Extreme-magnitude coverage -- the ``BIN-123`` shape itself, a
  representable mean whose intermediate running sum overflows -- comes
  from the pinned ``@example(scores=[1e307, 0.0] * 50)`` below, **not**
  from the random search. Any *other* extreme-magnitude shape than the one
  pinned is still unreached by this file; widening that coverage means
  adding another pinned example, not loosening the strategy.
* **Only the scores dimension.** ``target_arl``, ``smoothing_param``,
  ``reference_value`` and ``direction`` are held fixed at values already
  proven attainable by the passing invariance tests in the three ARL
  simulated property files (``_CONTRACT_TARGET_ARL`` below matches their
  ``_INVARIANCE_TARGET_ARL``). Those parameters have their own
  chart-specific strategies (e.g. CUSUM's ``arl_low``, bounded by
  ``_min_attainable_arl0`` since BIN-117) which were never triplicated
  across files the way the scores strategy was, so BIN-124's Part A scope
  -- and this meta-test's scope -- does not extend to them. A future
  rejection tied to one of *those* parameters needs its own guard, not
  this one.
* **Baseline sufficiency cannot drift out from under this test by
  construction**, since the strategy always draws exactly
  ``DEFAULT_SUFFICIENCY_THRESHOLD`` scores by importing the same constant
  the library validates against -- but that also means this test can never
  exercise ``InsufficientBaselineError``, nor would it notice a change to
  what "sufficient" means unless it also changed what "fittable" means.
* **Not an exception-contract audit.** This test only checks that a legal
  draw does not raise; it does not assert that every exception raised
  anywhere in the library is a ``CaliperError`` (that is ``BIN-121``'s
  job, over the full public surface, not just baseline fitting).
* **Not hostile-object or repr-raising receiver coverage** (``BIN-118``'s
  class) -- out of scope for a scores-only strategy.
"""

from __future__ import annotations

import pytest
from hypothesis import example, given, settings

from drift_caliper.baseline import fit_cusum, fit_ewma, fit_shewhart
from drift_caliper.errors import CaliperError
from tests.support.baseline_strategies import (
    baseline_from_scores,
    baseline_scores_strategy,
)

# Already proven attainable, at each chart's default calibration parameters
# (CUSUM: reference_value=DEFAULT_REFERENCE_VALUE, direction="two_sided"),
# by the passing invariance tests in all three ARL simulated property files
# -- each fits at this exact target_arl today.
_CONTRACT_TARGET_ARL = 370.0

_CHART_ENTRY_POINTS = (
    ("ewma", fit_ewma),
    ("cusum", fit_cusum),
    ("shewhart", fit_shewhart),
)


# BIN-123-shape pin (code-reviewer, first pass on this ticket): the random
# strategy draws from `[-10.0, 10.0]` and so can NEVER reach a magnitude
# like `1e307` -- not "rarely", *cannot*, by construction (see the module
# docstring's "What this test cannot catch"). The BIN-123 defect was a
# perfectly representable mean (`5e306`) whose *intermediate* running sum
# overflowed -- a shape only reachable at that magnitude. `@example` pins it
# so this exact shape is exercised on every run regardless of what the
# random search draws, rather than relying on the range ever being widened
# (which the ARL properties this strategy also feeds cannot tolerate -- see
# the module docstring). 50 repeats of `[1e307, 0.0]` is exactly
# `DEFAULT_SUFFICIENCY_THRESHOLD` (100) scores, alternating so every
# consecutive pair's moving range is `1e307` (representable) while the
# running sum of all 100 terms overflows float64 before division.
# `is_fittable()` accepts it (spread = `1e307`, far above the floor), and
# `@example` bypasses the strategy's own filter entirely by supplying the
# value directly rather than drawing it.
@example(scores=[1e307, 0.0] * 50)
@settings(max_examples=100, deadline=None)
@given(scores=baseline_scores_strategy())
def test_baseline_scores_strategy_never_draws_a_baseline_the_library_rejects(
    scores: list[float],
) -> None:
    """Every draw from ``baseline_scores_strategy()`` fits on all three charts.

    See the module docstring for why this assertion is deliberately
    double-edged: it fails both when the strategy has drifted into a
    region the library now (correctly) rejects (BIN-124's own concern) and
    when the library has started rejecting a region it should still fit
    (the BIN-123 class of bug). Which direction a failure here is in is
    for whoever reads the failure message to determine -- this test cannot
    tell them, only that the two have diverged.
    """
    # Arrange
    baseline = baseline_from_scores(scores)

    # Act -- ask the library, not a model of it: the real public entry
    # points, not `is_fittable()`, not `_has_zero_variance`, not
    # `_moving_range_sigma`.
    rejections: list[tuple[str, CaliperError]] = []
    for chart_name, fit in _CHART_ENTRY_POINTS:
        try:
            fit(baseline, target_arl=_CONTRACT_TARGET_ARL)
        except CaliperError as exc:
            rejections.append((chart_name, exc))

    # Assert -- name the offending input and every rejection that fired, so
    # whoever hits this can immediately tell whether to narrow the strategy
    # (BIN-124) or treat it as a library over-rejection bug (BIN-123).
    if rejections:
        spread = max(scores) - min(scores)
        detail = "; ".join(
            f"{chart_name}: {type(exc).__name__}"
            f"(category={exc.category!r}, context={dict(exc.context)!r})"
            for chart_name, exc in rejections
        )
        pytest.fail(
            "baseline_scores_strategy() drew scores that "
            f"{len(rejections)}/{len(_CHART_ENTRY_POINTS)} chart(s) reject: "
            f"{detail}. min={min(scores)!r} max={max(scores)!r} "
            f"spread={spread!r} n={len(scores)}.\n"
            "If this baseline is illegitimate (the library is now correctly "
            "rejecting it), narrow tests/support/baseline_strategies.py's "
            "MIN_FITTABLE_SPREAD/is_fittable() to exclude this region -- a "
            "new src/ rejection has narrowed the legal input space (BIN-124). "
            "If this baseline looks like data Caliper SHOULD be able to fit, "
            "do NOT narrow the strategy to silence this failure -- that is "
            "the library over-rejecting valid data (the BIN-123 class), and "
            "the fix belongs in src/, not here."
        )


__all__: list[str] = []
