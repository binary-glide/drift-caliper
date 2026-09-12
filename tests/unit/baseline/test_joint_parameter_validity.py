"""Contract-composition tests (BIN-122 item 1): joint-parameter validity.

**The category.** Every input this file draws is individually legal and
documented -- a ``target_arl``/``smoothing_param``/``reference_value``
inside its own published ``[MIN_*, MAX_*]`` range, per ``fit_ewma``'s /
``fit_cusum``'s / ``fit_shewhart``'s own docstrings. Nothing here is
hostile, extreme, or malformed -- that category is ``BIN-121``'s job, not
this one (see ``BIN-122``'s own "The category" section). The defect class
this guards against is a **combination** the specification permits that the
implementation cannot honour: ``BIN-117`` found exactly one --
``reference_value=5.0``, ``target_arl=370`` -- where both values are
individually inside their documented range and the pair together produced
a ``FittedCUSUM`` reporting an ``achieved_arl`` 3.1x the request, silently.

**The property, stated once.** For every ``(parameters)`` combination the
documented per-parameter ranges permit, a fitting function must **either**

1. fit successfully, and the returned artefact's ``achieved_arl`` must be
   close to the requested ``target_arl`` (within a tolerance justified
   below, per chart), **or**
2. raise a ``CaliperError`` (in every case observed, ``InvalidParameterError``)
   whose ``context`` identifies which parameter the combination made
   unattainable.

What must never happen -- the literal ``BIN-117`` outcome -- is a returned
artefact silently delivering an ``achieved_arl`` that is not what was
asked, with no exception and no disclosure. A rejection is always a pass
here; the property is "never silently wrong", not "always fits" (BIN-122's
own wording).

**Why a permanent guard replaces the one-off sweep.** BIN-122's scope
survey (2026-09-12 Linear comment) ran a 120-combination
``(reference_value, target_arl)`` script over CUSUM by hand before this file
existed: 0 mismatches, but "a script, not a test" -- nothing re-runs it, and
nothing catches a future regression. This file is that guard, permanent,
plus the two products the script did not cover at all: EWMA's
``(smoothing_param, target_arl)`` and Shewhart's ``target_arl`` alone
(Shewhart has no second tuning parameter -- BIN-95 A3/A5 -- so its own
"product" is one-dimensional, and is included here anyway per BIN-122's
explicit scope list rather than assumed safe because it is simple).

**What this file additionally found, run before being trusted (not merely
asserted).** Beyond the 120 CUSUM combinations BIN-122's own scope survey
already swept, a wider manual grid was run directly against the live
library while writing this file, covering ground the property below now
covers permanently:

* CUSUM at every ``reference_value`` in ``{0.01, 0.05, 0.1, 0.5, 1.0, 2.0,
  3.0, 5.0}`` (the full ``[MIN_REFERENCE_VALUE, MAX_REFERENCE_VALUE]``
  span) crossed with every ``direction`` at ``target_arl =
  MAX_MEANINGFUL_ARL`` (1,000,000) -- the ceiling corner BIN-117's own fix
  never checked, since BIN-117 was about the *floor* (a target silently
  unreachable from below). No combination pinned ``decision_interval`` at
  ``_MAX_DECISION_INTERVAL`` (the symmetric failure mode: a ceiling-side
  echo of BIN-117 would look identical -- an artefact reporting a lower
  ``achieved_arl`` than requested because calibration silently bottomed out
  at its search bracket's other end). Worst observed relative error:
  ``7.8e-10`` -- numerical noise, not a defect.
* EWMA at every ``smoothing_param`` in ``{0.01, 0.03, 0.05, 0.1, 0.2, 0.5,
  0.9, 1.0}`` (spanning ``[MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM]``)
  crossed with ``target_arl`` in ``{100, 370, 1e3, 1e4, 1e5, 1e6}``. Worst
  observed relative error: ``2.3e-9``.

**No joint-validity defect was found in either product.** CUSUM is the only
one of the three fitting functions with a genuine joint constraint
(attainability depends on *both* ``reference_value`` and ``direction`` --
see ``cusum_fitting._min_attainable_arl0``); EWMA and Shewhart's in-control
ARL0 has no mathematical ceiling reachable within their documented ranges,
so every legal combination fits (confirmed by the grid above, and now by
the Hypothesis property below, rather than assumed from that grid alone).

**Tolerance, per chart, and why each figure is what it is.**

* **EWMA: 2% relative.** Identical to, and directly inherited from, the
  tolerance ``test_ewma_arl_published_values.py`` already established and
  justifies at length (Markov-chain discretisation vs. an independent
  Nystroem-quadrature reference implementation) -- not re-derived here.
* **CUSUM: 1% relative.** **Citation corrected 2026-09-12 (BIN-124 round
  3)** -- this previously attributed
  ``result.achieved_arl == pytest.approx(requested, rel=0.01)`` to
  ``test_cusum_fitting.py``. **That line is not in that file** -- checked
  by grep -- so the citation was written from recollection rather than
  verified against the file it named, which this project treats as a
  categorical defect regardless of whether the underlying number is right
  (``CLAUDE.md``: *"every constant must come from the primary source,
  never from recall"*). The assertion itself is real, and matches this
  file's figure exactly -- it is just in a different file:
  ``test_cusum_arl_published_values.py:503``,
  ``test_achieved_arl_matches_the_requested_arl_in_either_direction``
  (``assert result.achieved_arl == pytest.approx(requested, rel=0.01)``).
  This file's property is that same comparison, generalised to the full
  legal ``(reference_value, target_arl, direction)`` product rather than
  one fixed point (``reference_value=0.5``, ``requested=500.0``). Worst
  observed relative error across the product: ``7.8e-10``, far inside the
  1% budget either way.
* **Shewhart: ``1e-6`` relative.** Matches
  ``test_shewhart_arl_published_values.py``'s own tolerance for its
  closed-form round trips: the sigma-multiplier inversion is an exact
  bijection with no discretisation or approximation step, so a far tighter
  bound is appropriate and a looser one would hide a real defect.

**Runtime, measured.** ``fit_cusum``/``fit_shewhart`` are closed-form and
effectively free (~0.1 ms/call, including the pre-check on unattainable
draws); ``fit_ewma``'s Markov-chain root-find measured at ~55 ms/call
against this file's fixed probe baseline (301x301 linear solve per
``brentq`` iteration -- see ``ewma_numerics.py``). This is the reason the
three properties below use different ``max_examples``: EWMA's product is
deliberately smaller (60 examples, ~3-4s) than CUSUM's/Shewhart's (150),
per BIN-122's own instruction to state the cost and split rather than
silently cut ``max_examples`` on a guard that would otherwise become too
slow to keep. Splitting further (e.g. one file per chart) was considered
and rejected: three ``@given``-decorated functions in one file, each with
its own ``max_examples``, already gives each chart its own budget without
the docstring duplication three separate files would cost.

**A fixed, shared probe baseline, not a fresh one per draw.** All three
fitting functions' ``achieved_arl`` depends only on the chart-calibration
parameters (``target_arl``, ``smoothing_param``/``reference_value``/
``direction``) -- never on the baseline's actual scores, beyond meeting the
sufficiency threshold and having non-zero variance (see each fitting
module's docstring, "why sigma does not need to be controlled"/"CUSUM
standardises in sigma units" -- the in-control ARL0 is computed entirely in
standardised units). Building a fresh ``Baseline`` per Hypothesis example
would cost real time for zero additional coverage of the property under
test; the same fixed, ordinary, non-degenerate baseline used throughout
``tests/support/parameter_bound_registry.py`` and
``tests/support/exception_contract_registry.py`` is reused here rather than
re-derived, following that established local convention.

**What this guard cannot catch, stated rather than left implicit.**

* **Only the parameters each chart's own signature exposes.** A future
  fourth chart type, or a new tuning parameter added to an existing one,
  is not covered until this file (or a sibling) is extended to draw it --
  nothing here discovers new joint constraints automatically, unlike
  ``BIN-124``'s bound-completeness scanner, which is a different kind of
  guard (it audits *strategy bounds already in the suite*, not the
  fitting functions' own signatures).
* **Only ``achieved_arl`` vs. ``target_arl``.** A fit that lands close on
  ``achieved_arl`` but computes a wrong ``ucl``/``lcl``/``decision_interval``
  from an otherwise-correct calibration is a different defect class,
  already covered by each chart's own published-value and simulated-property
  test files (BIN-84), not duplicated here.
* **A ``CaliperError`` on the rejection branch is accepted as a pass
  whenever its ``context`` names the offending parameter** -- this file
  does not additionally re-verify the *numeric* correctness of
  ``min_attainable_arl`` itself (that is
  ``test_cusum_arl_published_values.py``'s and this ticket's own
  round-trip file's job); it only asserts that a rejection, when one
  occurs, is classifiable rather than a defect being caught silently as
  "well, it raised something".
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caliper.baseline import fit_cusum, fit_ewma, fit_shewhart
from caliper.baseline.domain.cusum_fitting import (
    MAX_REFERENCE_VALUE,
    MIN_REFERENCE_VALUE,
)
from caliper.baseline.domain.ewma_fitting import (
    MAX_MEANINGFUL_ARL,
    MAX_SMOOTHING_PARAM,
    MIN_SMOOTHING_PARAM,
)
from caliper.baseline.domain.parameter_guards import MIN_TARGET_ARL
from caliper.errors import CaliperError, InvalidParameterError
from tests.support.baseline_strategies import probe_baseline

# See the module docstring's "A fixed, shared probe baseline" section for
# why one baseline is bound here rather than a fresh one per Hypothesis
# draw; `probe_baseline()`'s own docstring covers what the data is and why
# it is deliberately unremarkable.
_PROBE_BASELINE = probe_baseline()

# ⚠️ Deliberately NOT a shared module-level `st.floats(...)` constant reused
# across all three `@given(...)` calls below, even though the three
# `target_arl` strategies are identical. tests/support/hypothesis_bound_scan.py
# (BIN-124) only recognises a `min_value=`/`max_value=` bound when it sits
# either directly inside a `@given(...)` decorator's own keyword subtree
# (Tier 1) or inside a plain function's body (Tier 2, a strategy factory) --
# a bound assigned to a bare module-level constant and referenced by name is
# neither, and the scanner's AST walk would silently never see it. Inlining
# the identical `st.floats(...)` call three times is the established Tier-1
# idiom already used throughout this suite (e.g.
# test_cusum_arl_simulated_properties.py's own fixed-strategy `@given`
# blocks) precisely because it keeps every bound visible to that guard --
# see CLAUDE.md's instruction not to work around BIN-124's guard, and this
# is the concrete choice that instruction rules out here.


# --- EWMA: (smoothing_param, target_arl) --------------------------------------

_EWMA_RELATIVE_TOLERANCE = 0.02  # see module docstring's "Tolerance" section


@settings(max_examples=60, deadline=None)
@given(
    smoothing_param=st.floats(
        min_value=MIN_SMOOTHING_PARAM,
        max_value=MAX_SMOOTHING_PARAM,
        allow_nan=False,
        allow_infinity=False,
    ),
    target_arl=st.floats(
        min_value=MIN_TARGET_ARL,
        max_value=MAX_MEANINGFUL_ARL,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_ewma_delivers_the_requested_arl0_or_raises_naming_the_combination(
    smoothing_param: float, target_arl: float
) -> None:
    """Every legal ``(smoothing_param, target_arl)`` pair fits cleanly or is refused.

    Measured (module docstring): no combination in this product was found
    unattainable -- EWMA's in-control ARL0 has no ceiling reachable within
    ``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]`` at any legal
    ``smoothing_param``. The property is still written as an either/or
    (rather than asserting success unconditionally) so a future change
    narrowing either range is caught by the rejection branch's own
    assertion, not by this test breaking uninformatively.
    """
    try:
        result = fit_ewma(
            _PROBE_BASELINE, target_arl=target_arl, smoothing_param=smoothing_param
        )
    except CaliperError as exc:
        assert isinstance(exc, InvalidParameterError), (
            f"expected InvalidParameterError naming the offending combination, "
            f"got {type(exc).__name__}"
        )
        assert exc.context.get("parameter") in {"target_arl", "smoothing_param"}, (
            f"rejection did not identify which parameter was at fault: "
            f"{dict(exc.context)!r}"
        )
        return

    tolerance = target_arl * _EWMA_RELATIVE_TOLERANCE
    assert abs(result.achieved_arl - target_arl) <= tolerance, (
        f"fit_ewma(smoothing_param={smoothing_param!r}, target_arl={target_arl!r}) "
        f"succeeded but achieved_arl={result.achieved_arl!r} is not within "
        f"{tolerance!r} of the request -- a BIN-117-class silent misdelivery."
    )


# --- CUSUM: (reference_value, target_arl, direction) --------------------------

_CUSUM_RELATIVE_TOLERANCE = 0.01  # see module docstring's "Tolerance" section


@settings(max_examples=150, deadline=None)
@given(
    reference_value=st.floats(
        min_value=MIN_REFERENCE_VALUE,
        max_value=MAX_REFERENCE_VALUE,
        allow_nan=False,
        allow_infinity=False,
    ),
    target_arl=st.floats(
        min_value=MIN_TARGET_ARL,
        max_value=MAX_MEANINGFUL_ARL,
        allow_nan=False,
        allow_infinity=False,
    ),
    direction=st.sampled_from(("two_sided", "lower", "upper")),
)
def test_cusum_delivers_the_requested_arl0_or_raises_naming_the_combination(
    reference_value: float, target_arl: float, direction: str
) -> None:
    """Every legal ``(reference_value, target_arl, direction)`` triple fits or refuses.

    **This is the direct, generalised regression guard for BIN-117.** The
    exact combination BIN-117 found wrong (``reference_value=5.0``,
    ``target_arl=370``, ``direction="two_sided"``) is inside the product
    this property draws from -- see
    ``test_regression_bin_117_reference_value_five_target_arl_370_is_rejected``
    below for that combination pinned directly and deterministically, in
    addition to this generative property finding it (and every other
    unattainable combination) by construction.
    """
    try:
        result = fit_cusum(
            _PROBE_BASELINE,
            target_arl=target_arl,
            reference_value=reference_value,
            direction=direction,
        )
    except CaliperError as exc:
        assert isinstance(exc, InvalidParameterError), (
            f"expected InvalidParameterError naming the offending combination, "
            f"got {type(exc).__name__}"
        )
        assert exc.context.get("parameter") == "target_arl", (
            f"rejection did not identify target_arl as the parameter made "
            f"unattainable by this combination: {dict(exc.context)!r}"
        )
        # BIN-117's own fix: the error must name the *combination*, not just
        # the parameter in isolation -- reference_value/direction/
        # min_attainable_arl are the other half of "which combination is at
        # fault".
        assert exc.context.get("reference_value") == reference_value
        assert exc.context.get("direction") == direction
        assert isinstance(exc.context.get("min_attainable_arl"), float)
        assert exc.context["min_attainable_arl"] > target_arl
        return

    tolerance = target_arl * _CUSUM_RELATIVE_TOLERANCE
    assert abs(result.achieved_arl - target_arl) <= tolerance, (
        f"fit_cusum(reference_value={reference_value!r}, target_arl={target_arl!r}, "
        f"direction={direction!r}) succeeded but achieved_arl="
        f"{result.achieved_arl!r} is not within {tolerance!r} of the request -- "
        "the exact BIN-117 silent-misdelivery shape."
    )


def test_regression_bin_117_reference_value_five_target_arl_370_is_rejected() -> None:
    """The literal BIN-117 combination, pinned deterministically.

    Both values are individually legal and documented:
    ``reference_value=5.0`` is inside ``[MIN_REFERENCE_VALUE,
    MAX_REFERENCE_VALUE]``; ``target_arl=370`` is inside ``[MIN_TARGET_ARL,
    MAX_MEANINGFUL_ARL]``. Together, unattainable -- pre-fix, ``fit_cusum``
    silently returned a decision interval pinned at its solver floor and
    reported an ``achieved_arl`` 3.1x the request as a successful fit. A
    merged, passing BDD step helper was asserting that wrong behaviour as
    correct (BIN-122's own description) before this was caught.
    """
    with pytest.raises(InvalidParameterError) as excinfo:
        fit_cusum(
            _PROBE_BASELINE,
            target_arl=370.0,
            reference_value=5.0,
            direction="two_sided",
        )
    error = excinfo.value
    assert error.context["parameter"] == "target_arl"
    assert error.context["reference_value"] == 5.0
    assert error.context["direction"] == "two_sided"
    assert error.context["min_attainable_arl"] > 370.0


# --- Shewhart: target_arl alone ------------------------------------------------

_SHEWHART_RELATIVE_TOLERANCE = 1e-6  # see module docstring's "Tolerance" section


@settings(max_examples=150, deadline=None)
@given(
    target_arl=st.floats(
        min_value=MIN_TARGET_ARL,
        max_value=MAX_MEANINGFUL_ARL,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_shewhart_delivers_the_requested_arl0_or_raises_naming_the_parameter(
    target_arl: float,
) -> None:
    """Every legal ``target_arl`` fits Shewhart cleanly or is refused.

    Shewhart has no second tuning parameter (BIN-95 A3/A5), so this is a
    one-dimensional "product" -- included per BIN-122's explicit scope list
    rather than assumed safe because it is the simplest of the three.
    Measured: no ``target_arl`` inside ``[MIN_TARGET_ARL,
    MAX_MEANINGFUL_ARL]`` was found unattainable -- the closed-form
    ``sigma_multiplier`` inversion has no ceiling within this range.
    """
    try:
        result = fit_shewhart(_PROBE_BASELINE, target_arl=target_arl)
    except CaliperError as exc:
        assert isinstance(exc, InvalidParameterError), (
            f"expected InvalidParameterError naming target_arl, got "
            f"{type(exc).__name__}"
        )
        assert exc.context.get("parameter") == "target_arl"
        return

    tolerance = target_arl * _SHEWHART_RELATIVE_TOLERANCE
    assert abs(result.achieved_arl - target_arl) <= tolerance, (
        f"fit_shewhart(target_arl={target_arl!r}) succeeded but achieved_arl="
        f"{result.achieved_arl!r} is not within {tolerance!r} of the request."
    )


__all__: list[str] = []
