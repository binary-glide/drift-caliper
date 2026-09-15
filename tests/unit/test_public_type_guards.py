"""Unit tests for BIN-126 -- wrong-typed public arguments must leak ``CaliperError``.

**Scope, relative to the existing exception-contract audit.** The 8
BIN-126 cases (``fit_ewma``/``fit_cusum``/``fit_shewhart``'s wrong-typed
``baseline``/``smoothing_param``/``reference_value``/``target_arl``,
``Baseline.check_sufficiency``'s wrong-typed ``threshold``, and
``Judge.score``'s wrong-typed ``agent_output``) **were** pinned as
``xfail(strict=True, raises=<exact type>)`` in
``tests/support/exception_contract_registry.py`` -- that registry, driven
by ``tests/unit/test_exception_contract_audit.py``, was this ticket's
"these 8 leaks must become ``CaliperError``" spec, and all 8 are now
closed (their ``known_leak`` entries deleted). This file never duplicated
that; it covers the two things the brief says that audit alone is not
enough to prove:

1. **The accept direction.** A guard that turns a wrong-typed
   ``AttributeError``/``TypeError`` into an ``InvalidParameterError`` is
   trivially satisfiable by rejecting *everything* non-``float``/
   non-``Baseline`` -- which would also reject ``numpy.float32``,
   ``numpy.int64``, and plain ``int``, all of which a caller can reasonably
   pass today. Nothing in the existing audit proves the fix preserves this.
   The tests in "Numeric acceptance" below do -- every surface, including
   ``fit_ewma``, is a green-today regression guard; see "beartype and
   `fit_ewma`'s numeric-tower gap -- resolved by BIN-130" below for how
   ``fit_ewma`` got here.
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

## beartype and fit_ewma's numeric-tower gap -- resolved by BIN-130 and BIN-126

**This section originally documented a live defect, measured by direct
execution before this ticket's own fix landed.** ``tests/conftest.py`` used
to hook ``beartype_package("drift_caliper.baseline.domain.ewma_fitting")`` --
covering ``fit_ewma`` itself, a public entry point -- and beartype's
default ``is_pep484_tower=False`` (verified against the installed
``beartype==0.22.9``) meant ``fit_ewma``'s ``float``-annotated parameters
did **not** implicitly accept ``int`` at all, numpy or otherwise:
``target_arl=np.float32(370))``, ``np.int64(370)`` and even a plain
``370`` all raised ``BeartypeCallHintParamViolation`` inside this suite
while succeeding in the shipped wheel (which never imports beartype) --
the same load-order instability the registry's ``wrong_type_baseline``/
``wrong_type_smoothing_param`` entries flagged, just for four more inputs.
Only ``np.float64`` (a genuine ``float`` subclass) was unaffected.

**BIN-130 fixed this by moving the calibration internals
(``_calibrate_limit_multiplier``, ``_ewma_asymptotic_std_ratio``,
``_in_control_arl``) into ``drift_caliper.baseline.domain.ewma_numerics``, hooked
there instead, and normalising every value crossing that boundary to
``float`` inside ``fit_ewma`` before calling into it** -- see that
module's docstring and ``ewma_fitting.fit_ewma``'s own comment at the call
site. A pure module split alone was not sufficient: ``fit_ewma`` calling
the still-hooked numerics functions directly with a caller's raw ``int``/
``np.float32``/``np.int64`` value reproduced the identical violation one
call frame deeper, which the numeric-acceptance tests below caught by
direct execution, not by re-reading the ticket's own acceptance criterion.
The ``float(...)`` cast is a boundary normalisation, not a validation
step -- it rejects nothing ``fit_ewma`` did not already accept, and it
makes ``fit_ewma`` consistent with ``fit_cusum``/``fit_shewhart``, whose
own numeric parameters are already normalised the same way by
``drift_caliper.baseline.domain.parameter_guards.require_real_number``.

``fit_ewma``'s numeric-acceptance tests below are therefore now plain,
environment-independent regression guards, exactly like ``fit_cusum``'s
and ``fit_shewhart``'s. What BIN-130 did **not** touch is the *reject*
direction: BIN-130 alone left ``fit_ewma`` with no guard against a
wrong-typed or ``bool``-typed argument. **BIN-126 closes that gap**, adding
the identical ``drift_caliper.baseline.domain.parameter_guards`` guard
``fit_cusum``/``fit_shewhart`` already carried (``require_type`` on
``baseline``, ``require_real_number`` on ``target_arl``/
``smoothing_param``) -- so the bool-rejection tests for ``fit_ewma``
further below now pass outright, exactly like ``fit_shewhart``'s and
``fit_cusum``'s siblings, rather than staying pinned ``xfail``.

``fit_cusum``, ``fit_shewhart`` and ``Baseline.check_sufficiency`` never
carried a beartype hook at all (see ``tests/conftest.py``), so their
acceptance tests below always reflected one real, environment-independent
behaviour -- ``fit_ewma`` now matches them.

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

from drift_caliper.baseline import (
    Baseline,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from drift_caliper.errors import CaliperError, InvalidParameterError
from drift_caliper.measurement import ScoringResult
from drift_caliper.monitoring import Monitor
from tests.factories import ProvenanceFactory, ScoringResultFactory
from tests.support.baseline_strategies import (
    FITTABLE_PROBE_SCORES,
    probe_baseline,
)

# Bound once at import and reused across cases -- `fit_ewma`'s
# Markov-chain calibration is the expensive step in this file. See
# `probe_baseline()` for what the data is.
_BASELINE = probe_baseline()

# The numeric-type acceptance matrix this ticket's brief asks every
# surface to preserve. `python_int` is deliberately included even though
# it is not a numpy type -- it is the most natural thing an engineer
# passes (`target_arl=370`). Used for all four surfaces including
# `fit_ewma`, which needed its own fix (BIN-130) to accept every case here
# -- see the module docstring's "beartype and fit_ewma's numeric-tower gap"
# section.
_NUMERIC_TYPE_CASES = [
    pytest.param(np.float32, id="np_float32"),
    pytest.param(np.float64, id="np_float64"),
    pytest.param(np.int64, id="np_int64"),
    pytest.param(int, id="python_int"),
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
            score=numeric_type(0.5),  # type: ignore[arg-type]
            reasoning="r",
            provenance=provenance,
        )
    )
    assert baseline.observation_count == 1


# ---------------------------------------------------------------------------
# Numeric acceptance -- fit_ewma
#
# Fixed by BIN-130. `fit_ewma` used to be beartype-guarded
# (tests/conftest.py) directly, and separately -- even after BIN-130 moved
# the hook off `fit_ewma` itself -- calling the still-hooked
# `ewma_numerics` functions with a caller's raw numeric type reproduced the
# identical violation one call frame deeper. Both are closed: the hook now
# covers only `ewma_numerics`, and `fit_ewma` normalises to `float` at the
# two call sites crossing into it (see the module docstring's "beartype and
# fit_ewma's numeric-tower gap" section and `ewma_fitting.fit_ewma`'s own
# comment). All four cases below are now plain, environment-independent
# regression guards, exactly like `fit_cusum`'s and `fit_shewhart`'s above.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("numeric_type", _NUMERIC_TYPE_CASES)
def test_fit_ewma_accepts_target_arl_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    artefact = fit_ewma(
        _BASELINE,
        target_arl=numeric_type(370),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "ewma"
    assert math.isfinite(artefact.achieved_arl)


@pytest.mark.parametrize("numeric_type", _NUMERIC_TYPE_CASES)
def test_fit_ewma_accepts_smoothing_param_across_numeric_types(
    numeric_type: Callable[[float], object],
) -> None:
    # Sample value is `1`, not `0.2` -- deliberately. `smoothing_param`'s
    # valid range is `[MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM]` ==
    # `[0.01, 1.0]`; `1` is the only integer inside it, so it is the one
    # value every numeric type here represents identically
    # (`int(1) == np.int64(1) == float(np.float32(1)) == 1.0`). `0.2`
    # silently truncates to `0` under `int`/`np.int64` (`int(0.2) == 0`),
    # which is genuinely, correctly outside the valid range -- found by
    # direct execution during BIN-130 (previously invisible because
    # beartype rejected `int`/`np.int64` outright before the value ever
    # reached validation; that masking is gone now that `fit_ewma` behaves
    # identically inside and outside the suite). This is a test-fixture
    # fix, not a `fit_ewma` behaviour change: `0` was always, correctly,
    # rejected.
    artefact = fit_ewma(
        _BASELINE,
        target_arl=370.0,
        smoothing_param=numeric_type(1),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "ewma"
    assert math.isfinite(artefact.achieved_arl)


# ⚠️ `1` is the *only* value the test above can use across all four numeric
# types, which makes it a weaker test than it looks: a typical smoothing
# parameter is a fraction, and `1.0` is the degenerate end of the range
# (the EWMA reduces to a Shewhart chart -- no smoothing at all). So the
# float-representable types are exercised separately at a realistic value.
# Raised by code-reviewer on BIN-130: the fixture fix above was correct but
# narrowed coverage, and narrowing it silently would have traded one masked
# defect for a quieter one.
_FLOAT_ONLY_TYPE_CASES = [
    pytest.param(float, id="python_float"),
    pytest.param(np.float32, id="np_float32"),
    pytest.param(np.float64, id="np_float64"),
]


@pytest.mark.parametrize("numeric_type", _FLOAT_ONLY_TYPE_CASES)
def test_fit_ewma_accepts_a_fractional_smoothing_param_across_float_types(
    numeric_type: Callable[[float], object],
) -> None:
    """A realistic smoothing parameter works in every float-capable type.

    Complements the all-numeric-types test above, which is pinned to `1`
    because `int`/`np.int64` cannot represent anything else inside
    `[0.01, 1.0]`. `0.2` is the value an engineer would actually pass.
    """
    artefact = fit_ewma(
        _BASELINE,
        target_arl=370.0,
        smoothing_param=numeric_type(0.2),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    assert artefact.chart_type == "ewma"
    assert math.isfinite(artefact.achieved_arl)
    assert artefact.smoothing_param == pytest.approx(0.2, rel=1e-6)


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
#
# `fit_ewma`'s two cases are fixed by BIN-126, the same as `fit_cusum`'s
# and `fit_shewhart`'s below -- no longer pinned `xfail`.
# ---------------------------------------------------------------------------


def test_fit_ewma_rejects_bool_target_arl() -> None:
    """Fixed by BIN-126: ``fit_ewma(target_arl=True)`` used to fit successfully.

    Measured directly before this fix, identically with and without
    ``tests/conftest.py``'s beartype hook (BIN-130 had already closed that
    instability): the call used to succeed everywhere, producing
    ``achieved_arl`` approximately 1.0 -- see the module docstring and
    BIN-131's reproduction. ``fit_ewma`` now carries the same
    ``require_real_number`` guard ``fit_cusum``/``fit_shewhart`` already
    had, so this raises ``InvalidParameterError`` like its siblings.
    """
    with pytest.raises(InvalidParameterError) as exc_info:
        fit_ewma(_BASELINE, target_arl=True)
    _assert_caliper_error(exc_info.value)
    assert exc_info.value.context.get("parameter") == "target_arl"
    assert exc_info.value.context.get("kind") == "invalid"


def test_fit_ewma_rejects_bool_smoothing_param() -> None:
    """Fixed by BIN-126: ``fit_ewma(smoothing_param=True)`` used to fit successfully.

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
        for score in FITTABLE_PROBE_SCORES[:20]
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
        for score in FITTABLE_PROBE_SCORES[:20]
    )
    assert signal_count <= 1, (
        f"{signal_count}/20 in-control observations signalled out-of-control -- "
        "an ARL0 of 1 (from an unrejected bool target_arl) alarms on nearly "
        "every observation of a healthy process"
    )
