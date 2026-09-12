"""Unit tests for BIN-126 -- wrong-typed public arguments must leak ``CaliperError``.

**Scope, relative to the existing exception-contract audit.** The 8
BIN-126 cases (``fit_ewma``/``fit_cusum``/``fit_shewhart``'s wrong-typed
``baseline``/``smoothing_param``/``reference_value``/``target_arl``,
``Baseline.check_sufficiency``'s wrong-typed ``threshold``, and
``Judge.score``'s wrong-typed ``agent_output``) are **already** pinned as
``xfail(strict=True, raises=<exact type>)`` in
``tests/support/exception_contract_registry.py`` -- that registry, driven
by ``tests/unit/test_exception_contract_audit.py``, already is this
ticket's "these 8 leaks must become ``CaliperError``" spec. This file does
not duplicate that; it covers the two things the brief says that audit is
not enough on its own to prove:

1. **The accept direction.** A guard that turns a wrong-typed
   ``AttributeError``/``TypeError``/``BeartypeCallHintParamViolation`` into
   an ``InvalidParameterError`` is trivially satisfiable by rejecting
   *everything* non-``float``/non-``Baseline`` -- which would also reject
   ``numpy.float32``, ``numpy.int64``, and plain ``int``, all of which a
   caller can reasonably pass today. Nothing in the existing audit proves
   the fix preserves this. The tests in "Numeric acceptance" below do --
   for the surfaces where it is already true, they are regression guards
   (green today, must stay green); for ``fit_ewma`` specifically, see the
   "beartype's numeric-tower gap" note below -- three of its four cases
   are RED today, not because of a real design decision, but because of an
   already-broken current state this ticket must also fix.
2. **The bool-specific defect the audit cannot see at all.**
   ``bool`` is an ``int`` subclass, so ``isinstance(True, int)`` and
   Python's own duck typing let it satisfy every numeric parameter in this
   file silently -- producing, on at least two charts, an artefact whose
   ``achieved_arl`` is approximately 1 (an in-control false-alarm rate of
   "every observation"). See
   ``BIN-131`` for the
   full write-up; this file pins only its Scope item 1 ("reject bool
   wherever a numeric parameter is expected"), which that document already
   states is settled. **Scope item 2 (what the real ARL0 floor should be)
   is an unratified product decision and is deliberately NOT touched
   here** -- no test in this file asserts a specific ``MIN_MEANINGFUL_ARL``
   value, and the behavioural regression tests below pass under either
   acceptable resolution (bool rejected outright, or a floor that makes
   the resulting chart not alarm on nearly every observation).

## beartype's numeric-tower gap -- measured, not assumed

**The brief's own "established facts" table is only half right, and this
was verified by direct execution before writing anything below, not
inferred from source reading.** Under ``tests/conftest.py``'s dev-only
``beartype_package("caliper.baseline.domain.ewma_fitting")`` hook -- the
only environment this test suite ever runs in --
``beartype.BeartypeConf().is_pep484_tower`` is ``False`` (the library
default; verified against the installed ``beartype==0.22.9``), so
``fit_ewma``'s ``float``-annotated parameters do **not** implicitly accept
``int`` at all, numpy or otherwise:

```
fit_ewma(target_arl=np.float64(370))  -> OK   (np.float64 IS a float subclass)
fit_ewma(target_arl=np.float32(370))  -> BeartypeCallHintParamViolation
fit_ewma(target_arl=np.int64(370))    -> BeartypeCallHintParamViolation
fit_ewma(target_arl=370)              -> BeartypeCallHintParamViolation (plain int!)
fit_ewma(target_arl=True)             -> BeartypeCallHintParamViolation (bool, by luck)
```

identically for ``smoothing_param``. Every one of those four failing calls
is measurably a **currently-broken, non-``CaliperError`` leak already** --
it is simply not one of the 8 the registry named, because the registry's
own ``wrong_type_baseline``/``wrong_type_smoothing_param`` cases use a
string, not a numeric near-miss. **This means the acceptance-matrix tests
below for ``fit_ewma`` are three-quarters RED for a reason distinct from
BIN-126's headline defect, but caused by the exact same missing
boundary-level guard** -- and it means the fix cannot be "catch
``BeartypeCallHintParamViolation`` and re-raise as ``InvalidParameterError``"
alone: that would satisfy the reject direction while leaving the accept
direction broken for ``int``/``np.float32``/``np.int64``, which is exactly
the trap this brief warns about, just arriving via a different mechanism
than a hand-written ``isinstance`` check. The beartype guard on
``ewma_fitting``'s public functions has to go (or be reconfigured), not
just be wrapped.

Without the hook (i.e. the actual shipped wheel, which never imports
beartype -- see ``tests/conftest.py``'s own docstring), every one of those
four calls succeeds instead, matching the brief's table exactly and
reproducing BIN-131's ``achieved_arl = 1.0000013`` figure for
``target_arl=True``. This is the identical instability the registry's own
``wrong_type_baseline``/``wrong_type_smoothing_param`` entries already
flag ("a caller cannot write an except against a type that depends on how
the library was loaded") -- measured here for four more inputs, not
merely asserted.

``fit_cusum``, ``fit_shewhart`` and ``Baseline.check_sufficiency`` carry no
beartype hook at all (see ``tests/conftest.py``), so their acceptance
tests below reflect one real, environment-independent behaviour.

## Error type asserted for the new (non-registry) cases

Every codebase-wide "supplied value violates a constraint" path already
in ``src/`` -- ``out_of_range_smoothing_param``, ``invalid_direction``,
``check_sufficiency``'s non-positive ``threshold`` -- raises
``InvalidParameterError`` with ``context["kind"] == "invalid"`` (ADR-002).
A wrong-typed or bool-typed numeric argument is the same class of
violation, so the bool-rejection tests below assert
``InvalidParameterError`` specifically, not merely ``CaliperError`` --
flagged here as a deliberate choice consistent with the rest of this
codebase's convention, not a silent assumption. Per ADR-002/ADR-008, no
test asserts on message text; only type, ``category``, and a documented
``context`` key.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest
from beartype.roar import BeartypeCallHintParamViolation

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.errors import CaliperError, InvalidParameterError
from caliper.measurement import ScoringResult
from caliper.monitoring import Monitor
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.baseline_strategies import baseline_from_scores

# A plain, unremarkable, non-degenerate 100-observation baseline -- built
# once and reused (mirrors the registry's own `_BASELINE` for the same
# reason: `fit_ewma`'s Markov-chain calibration is the expensive step in
# this file). Cycling 0..4 gives a spread of 4.0, far above
# `tests.support.baseline_strategies.MIN_FITTABLE_SPREAD`.
_FITTABLE_SCORES = [float(i % 5) for i in range(DEFAULT_SUFFICIENCY_THRESHOLD)]
_BASELINE = baseline_from_scores(_FITTABLE_SCORES)

# The numeric-type acceptance matrix this ticket's brief asks every
# surface to preserve. `python_int` is deliberately included even though
# it is not a numpy type -- it is the most natural thing an engineer
# passes (`target_arl=370`), and it is also the case beartype's
# numeric-tower gap breaks on `fit_ewma` (see module docstring).
_NUMERIC_TYPE_CASES = [
    pytest.param(np.float32, id="np_float32"),
    pytest.param(np.float64, id="np_float64"),
    pytest.param(np.int64, id="np_int64"),
    pytest.param(int, id="python_int"),
]

# --- fit_ewma is blocked, not fixed here -- see "beartype's numeric-tower
# gap" above. Tracked as BIN-130 rather than left to fail the suite outright.
_EWMA_BEARTYPE_BLOCKER_REASON = (
    "BIN-130: blocked on splitting ewma_fitting.py so beartype's dev-only "
    "import hook (tests/conftest.py) stops guarding fit_ewma, a public "
    "boundary; a guard added to fit_ewma's body today is preempted by "
    "BeartypeCallHintParamViolation and cannot be exercised by this suite. "
    "When BIN-130 lands these XPASS and fail the build until removed."
)

# `raises=BeartypeCallHintParamViolation` is deliberate, not an oversight
# of its own harness-dependence. It is **only** correct under
# `tests/conftest.py`'s dev-only beartype hook -- outside this suite (the
# shipped wheel, which never imports beartype) the same calls raise
# nothing at all (the three numeric-tower cases) or leak a bare
# `TypeError`/`AttributeError` instead (the bool-rejection cases,
# mirroring `wrong_type_baseline`/`wrong_type_smoothing_param` in
# `tests/support/exception_contract_registry.py`, which pins the exact
# same type for the exact same reason). Pinning it anyway matches that
# registry's own established precedent for this identical root cause,
# verified directly in this environment rather than assumed, and
# `strict=True` still does its job either way: when the module split
# lands, `fit_ewma` either raises `InvalidParameterError` (this mark
# XPASSes) or -- if the split changes what leaks first -- raises some
# other foreign type (this mark's own `raises=` stops matching, and the
# case fails for real rather than quietly staying green). Both outcomes
# surface the moment they happen; neither can hide behind this marker.
_EWMA_BLOCKED_NUMERIC_TYPE_CASES = [
    pytest.param(
        np.float32,
        id="np_float32",
        marks=pytest.mark.xfail(
            reason=_EWMA_BEARTYPE_BLOCKER_REASON,
            raises=BeartypeCallHintParamViolation,
            strict=True,
        ),
    ),
    # np.float64 IS a float subclass -- beartype's is_pep484_tower=False
    # gap does not bite here, so this case is green today and must stay
    # unmarked (see module docstring).
    pytest.param(np.float64, id="np_float64"),
    pytest.param(
        np.int64,
        id="np_int64",
        marks=pytest.mark.xfail(
            reason=_EWMA_BEARTYPE_BLOCKER_REASON,
            raises=BeartypeCallHintParamViolation,
            strict=True,
        ),
    ),
    pytest.param(
        int,
        id="python_int",
        marks=pytest.mark.xfail(
            reason=_EWMA_BEARTYPE_BLOCKER_REASON,
            raises=BeartypeCallHintParamViolation,
            strict=True,
        ),
    ),
]


def _assert_caliper_error(exc: CaliperError) -> None:
    """Structural assertion only -- ADR-002/ADR-008: type + context shape, not text."""
    assert exc.category, f"{type(exc).__name__} raised with an empty category"
    assert isinstance(exc.context, dict) or hasattr(exc.context, "items"), (
        f"{type(exc).__name__}.context is not a mapping: {type(exc.context).__name__}"
    )


# ---------------------------------------------------------------------------
# Numeric acceptance -- fit_cusum, fit_shewhart, check_sufficiency, record
#
# None of these four surfaces carries a beartype hook (tests/conftest.py),
# so every case below is a plain, environment-independent regression guard:
# ALL of them pass today. They exist so that whoever fixes BIN-126 cannot
# satisfy the ticket by rejecting numpy/int types these callers already
# rely on -- the exact failure mode the brief warns a naive isinstance(x,
# float) guard would cause.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("numeric_type", _NUMERIC_TYPE_CASES)
def test_fit_cusum_accepts_target_arl_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    artefact = fit_cusum(
        _BASELINE,
        target_arl=numeric_type(370),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "cusum"
    assert math.isfinite(artefact.achieved_arl)


@pytest.mark.parametrize("numeric_type", _NUMERIC_TYPE_CASES)
def test_fit_cusum_accepts_reference_value_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    artefact = fit_cusum(
        _BASELINE,
        target_arl=370.0,
        reference_value=numeric_type(1),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "cusum"
    assert math.isfinite(artefact.achieved_arl)


@pytest.mark.parametrize("numeric_type", _NUMERIC_TYPE_CASES)
def test_fit_shewhart_accepts_target_arl_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    artefact = fit_shewhart(
        _BASELINE,
        target_arl=numeric_type(370),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "shewhart"
    assert math.isfinite(artefact.achieved_arl)


@pytest.mark.parametrize("numeric_type", _NUMERIC_TYPE_CASES)
def test_check_sufficiency_accepts_threshold_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    result = Baseline().check_sufficiency(
        threshold=numeric_type(50)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert result.threshold == 50


def test_check_sufficiency_reports_an_accepted_threshold_back_unchanged() -> None:
    """BIN-126 review: what goes in comes out -- no silent truncation.

    A regression pinned after review measured a boundary flip: an earlier
    version of this fix truncated any real-valued ``threshold`` (e.g.
    ``50.7`` -> ``50``), which both changed what "sufficient" meant at the
    boundary and reported back a threshold the caller never passed
    (``CLAUDE.md``'s "what goes in should come out"). Every integral-valued
    input below -- across ``int``, ``float``, and numpy's numeric types --
    must report back exactly ``50``, never a value implicitly rounded or
    coerced from something else.
    """
    for value in (50, 50.0, np.int64(50), np.float64(50.0), np.float32(50)):
        result = Baseline().check_sufficiency(
            threshold=value  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )
        assert result.threshold == 50


def test_check_sufficiency_rejects_non_integral_threshold() -> None:
    """BIN-126 review: a fractional threshold is a confident wrong answer, not a nicety.

    ``threshold`` is a count of observations -- ``50.7`` is not one.
    Measured directly before this guard existed: a baseline of exactly 50
    observations checked against ``threshold=50.7`` used to report
    ``is_sufficient=True`` with ``threshold=50`` -- silently lowering the
    boundary from "at least 51" to "at least 50" and reporting a number the
    caller never passed. Rejecting outright (rather than rounding either
    direction) is the only choice that does not invent a meaning for input
    the caller did not intend (``CLAUDE.md`` "errors raise; the caller
    decides").
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        Baseline().check_sufficiency(
            threshold=50.7  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "threshold"
    assert exc_info.value.context.get("kind") == "invalid"


@pytest.mark.parametrize("numeric_type", _NUMERIC_TYPE_CASES)
def test_baseline_record_accepts_score_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    baseline = Baseline()
    provenance = ProvenanceFactory()
    baseline.record(
        ScoringResult(
            score=numeric_type(0.5),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            reasoning="r",
            provenance=provenance,
        )
    )
    assert baseline.observation_count == 1


# ---------------------------------------------------------------------------
# Numeric acceptance -- fit_ewma
#
# Beartype-guarded (tests/conftest.py). Only np_float64 is green today --
# see the module docstring's "beartype's numeric-tower gap" section. The
# other three cases are RED today for a real, measured reason: beartype's
# default `is_pep484_tower=False` rejects int/np.float32/np.int64 against
# a `float`-annotated parameter, regardless of BIN-126's own fix. Whoever
# closes this ticket must also resolve that -- catching and re-raising
# BeartypeCallHintParamViolation as InvalidParameterError is not sufficient
# on its own, because these calls must SUCCEED, not merely raise the right
# type.
#
# BIN-126 review: pinned `xfail(strict=True)` rather than left to fail the
# suite outright -- see `_EWMA_BLOCKED_NUMERIC_TYPE_CASES`'s comment above
# for the reasoning, including the deliberate call on `raises=`.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("numeric_type", _EWMA_BLOCKED_NUMERIC_TYPE_CASES)
def test_fit_ewma_accepts_target_arl_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    artefact = fit_ewma(
        _BASELINE,
        target_arl=numeric_type(370),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "ewma"
    assert math.isfinite(artefact.achieved_arl)


@pytest.mark.parametrize("numeric_type", _EWMA_BLOCKED_NUMERIC_TYPE_CASES)
def test_fit_ewma_accepts_smoothing_param_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    artefact = fit_ewma(
        _BASELINE,
        target_arl=370.0,
        smoothing_param=numeric_type(0.2),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "ewma"
    assert math.isfinite(artefact.achieved_arl)


# ---------------------------------------------------------------------------
# bool rejection -- the defect the exception-contract audit cannot see,
# because most of these currently succeed rather than raise anything.
#
# `isinstance(True, int)` is `True`, so ordinary duck typing lets `bool`
# satisfy every numeric parameter below. Per BIN-131's Scope
# item 1 (settled -- distinct from item 2's unratified ARL floor
# question), every one of these must instead raise a typed
# InvalidParameterError, checking `isinstance(x, bool)` before any
# `isinstance(x, int)` narrowing (bool is an int subclass).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=_EWMA_BEARTYPE_BLOCKER_REASON,
    raises=BeartypeCallHintParamViolation,
    strict=True,
)
def test_fit_ewma_rejects_bool_target_arl() -> None:
    """BLOCKED (BIN-126): raises ``BeartypeCallHintParamViolation``, not our error.

    Without the dev-only beartype hook (the shipped wheel), this call
    currently *succeeds* instead, producing ``achieved_arl`` approximately
    1.0 -- see the module docstring and BIN-131's reproduction.
    Either way it is wrong today; only the observed failure mode differs
    by environment. Cannot be fixed without also splitting
    ``ewma_fitting.py`` (see ``_EWMA_BEARTYPE_BLOCKER_REASON``) -- pinned
    ``xfail(strict=True)`` rather than left red so the suite stays green
    while this stays visibly tracked, and so the fix landing (this XPASSes)
    is what actually closes the loop, not a marker someone forgets to
    remove.
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        fit_ewma(_BASELINE, target_arl=True)
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "target_arl"
    assert exc_info.value.context.get("kind") == "invalid"


@pytest.mark.xfail(
    reason=_EWMA_BEARTYPE_BLOCKER_REASON,
    raises=BeartypeCallHintParamViolation,
    strict=True,
)
def test_fit_ewma_rejects_bool_smoothing_param() -> None:
    """BLOCKED (BIN-126): raises ``BeartypeCallHintParamViolation``, not our error.

    See ``test_fit_ewma_rejects_bool_target_arl``'s docstring -- identical
    reasoning, ``smoothing_param`` rather than ``target_arl``.
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        fit_ewma(_BASELINE, target_arl=370.0, smoothing_param=True)
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "smoothing_param"
    assert exc_info.value.context.get("kind") == "invalid"


def test_fit_shewhart_rejects_bool_target_arl() -> None:
    """Fixed by BIN-126: ``fit_shewhart(target_arl=True)`` used to fit successfully.

    Reproduced BIN-131's exact reported behaviour
    (``achieved_arl == 1.0``) -- no beartype hook guards ``shewhart_fitting``,
    so nothing at all used to raise for this call.
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        fit_shewhart(_BASELINE, target_arl=True)
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "target_arl"
    assert exc_info.value.context.get("kind") == "invalid"


def test_fit_cusum_rejects_bool_target_arl_even_when_otherwise_attainable() -> None:
    """Fixed by BIN-126 -- proves CUSUM's prior protection was accidental, not a guard.

    At the library default ``reference_value`` (0.5), ``target_arl=True``
    (i.e. 1) already raised ``InvalidParameterError`` before this fix -- but
    only because BIN-117's attainability floor happens to sit above 1 at
    that reference value (measured: ~1.043). Measured directly: at
    ``reference_value=0.1``, the minimum attainable ARL0 drops to ~0.736,
    so ``target_arl=True`` was well within the *attainable* range and
    ``fit_cusum`` used to fit it successfully (``achieved_arl`` ==
    1.0000000000000018, verified by direct execution before this fix). A
    real bool guard rejects this regardless of ``reference_value`` --
    BIN-117's attainability check is a different, orthogonal concern.
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        fit_cusum(
            _BASELINE, target_arl=True, reference_value=0.1, direction="two_sided"
        )
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "target_arl"
    assert exc_info.value.context.get("kind") == "invalid"


def test_fit_cusum_rejects_bool_reference_value() -> None:
    """Fixed by BIN-126: ``reference_value=True`` used to fit successfully."""
    with pytest.raises(InvalidParameterError) as exc_info:
        fit_cusum(_BASELINE, target_arl=370.0, reference_value=True)
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "reference_value"
    assert exc_info.value.context.get("kind") == "invalid"


def test_check_sufficiency_rejects_bool_threshold() -> None:
    """Fixed by BIN-126: ``check_sufficiency(threshold=True)`` used to succeed.

    Used to return ``SufficiencyResult(threshold=1, ...)`` -- a threshold
    of 1 was technically "valid" per the existing positive-integer check,
    but a caller who passed a boolean almost certainly did not intend a
    sufficiency threshold of exactly 1.
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        Baseline().check_sufficiency(threshold=True)
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "threshold"
    assert exc_info.value.context.get("kind") == "invalid"


# ---------------------------------------------------------------------------
# Behavioural regression -- the assertion that would have caught the bug
# without relying on anything raising at all (BIN-121's audit structurally
# cannot make this assertion; see its module docstring's "structural
# limit" section).
#
# Each test accepts either acceptable resolution: `target_arl=True` is
# rejected outright (the early return below), or -- if some future change
# permits it to fit at all -- the resulting chart must not signal on
# nearly every in-control observation. Deliberately does NOT assert a
# specific MIN_MEANINGFUL_ARL value (that is an unratified product
# decision -- see the module docstring).
# ---------------------------------------------------------------------------


def test_shewhart_monitor_does_not_signal_on_every_in_control_observation() -> None:
    """Reproduced BIN-131's defect via behaviour -- now fixed.

    Fixed by BIN-126: ``fit_shewhart(target_arl=True)`` used to succeed,
    and the resulting chart's control limits collapsed to a single point
    (``ucl == lcl == cl``, since the sigma multiplier for ARL0=1 is
    exactly 0) -- so any in-control observation that is not *exactly* the
    baseline mean signalled. Measured directly before this fix: 16 of 20
    in-control observations, drawn from the baseline's own distribution,
    signalled out-of-control. Now takes the early-return branch below,
    since ``target_arl=True`` is rejected outright.
    """
    try:
        artefact = fit_shewhart(_BASELINE, target_arl=True)
    except CaliperError:
        return  # bool rejected outright -- the acceptable, safer resolution

    monitor = Monitor(artefact)
    provenance = _BASELINE.provenance_signature
    signal_count = sum(
        not monitor.record(
            ScoringResultFactory(provenance=provenance, score=score)
        ).is_in_control
        for score in _FITTABLE_SCORES[:20]
    )
    assert signal_count <= 1, (
        f"{signal_count}/20 in-control observations signalled out-of-control -- "
        "an ARL0 of 1 (from an unrejected bool target_arl) alarms on nearly "
        "every observation of a healthy process"
    )


def test_cusum_monitor_does_not_signal_on_every_in_control_observation() -> None:
    """CUSUM sibling of the Shewhart regression above, at a reference_value where
    CUSUM's accidental attainability protection does not apply (see
    ``test_fit_cusum_rejects_bool_target_arl_even_when_otherwise_attainable``).

    Fixed by BIN-126: measured directly before this fix, this used to fit
    successfully and every one of 20 in-control observations used to
    signal out-of-control. Now takes the early-return branch below.
    """
    try:
        artefact = fit_cusum(
            _BASELINE, target_arl=True, reference_value=0.1, direction="two_sided"
        )
    except CaliperError:
        return  # bool rejected outright -- the acceptable, safer resolution

    monitor = Monitor(artefact)
    provenance = _BASELINE.provenance_signature
    signal_count = sum(
        not monitor.record(
            ScoringResultFactory(provenance=provenance, score=score)
        ).is_in_control
        for score in _FITTABLE_SCORES[:20]
    )
    assert signal_count <= 1, (
        f"{signal_count}/20 in-control observations signalled out-of-control -- "
        "an ARL0 of 1 (from an unrejected bool target_arl) alarms on nearly "
        "every observation of a healthy process"
    )
