"""Contract-composition tests (BIN-122 item 4): docstring range claims vs. behaviour.

**The property.** Every numeric range a public docstring asserts is
demonstrated attainable at both endpoints against the live library, or the
claim is wrong and must be corrected -- never left merely asserted. This
item's own worked example, before this file existed, was
``MIN_MEANINGFUL_ARL = 1.0``: documented (in a module-level comment, not
yet a public docstring at the time) as a floor, and **not attainable at any
reference value** -- the default CUSUM reference value's two-sided infimum
was 1.0431, strictly above the claimed floor. ADR-011 closed that specific
finding (renamed to the internal-only ``MIN_COHERENT_ARL``, replaced as the
*enforced* floor by ``MIN_TARGET_ARL = 100``) before this file was written
-- which is exactly why BIN-122 names it as the item with the *least*
remaining evidence behind it: a category that has already produced one real
finding deserves an automated guard, not a closed ticket.

**Audit performed while writing this file (2026-09-12), against
``trunk`` at the commit this ticket started from.** Every public docstring
in ``caliper.baseline`` naming a numeric range was enumerated by hand
(module docstrings, and every ``fit_ewma``/``fit_cusum``/``fit_shewhart``/
``FittedControlLimits`` docstring -- the only public callables with a
``Raises``/range-shaped claim in this bounded context) and checked against
the live library:

* ``fit_ewma``'s ``Raises`` section: ``target_arl`` outside
  ``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]``; ``smoothing_param`` outside
  ``[MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM]``. **Both ranges' endpoints
  are attainable** -- verified below, deterministically, not merely by the
  Hypothesis sweep in ``test_joint_parameter_validity.py`` happening to
  draw them.
* ``fit_cusum``'s ``Raises`` section: the same ``target_arl`` range, plus
  ``reference_value`` outside ``[MIN_REFERENCE_VALUE,
  MAX_REFERENCE_VALUE]``, plus the attainability caveat ("or target_arl is
  below the minimum ARL0 attainable..."). **This is the one docstring in
  this context that does NOT claim every ``(reference_value, target_arl)``
  combination in the stated ranges is jointly attainable** -- it discloses
  the caveat in the same sentence, so the honest claim is narrower than "the
  full product is achievable", and is exactly what
  ``test_joint_parameter_validity.py`` verifies. Endpoints of each range
  individually attainable (at a suitably chosen partner value) -- verified
  below.
* ``fit_shewhart``'s ``Raises`` section: ``target_arl`` outside
  ``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]``, no caveat needed (no second
  parameter). Endpoints attainable -- verified below.
* The literal ``"[100, 370)"`` figure itself: **corrected 2026-09-12
  (BIN-124 round 3, Blocker 2)** -- this section previously claimed
  ``FittedControlLimits.advisories``'s docstring was the **only** place
  this range appears as literal numbers rather than named constants. That
  undercounted. Grepping the full ``caliper.baseline`` source finds it
  **seven times**: the ``advisories`` docstring, ``fit_ewma``'s,
  ``fit_cusum``'s and ``fit_shewhart``'s own ``Returns`` docstrings (each
  states "carries a non-empty ``advisories`` when ``target_arl`` is
  inside ADR-011's flagged tier (``[100, 370)``)"), and a field comment on
  each of ``FittedEWMA``, ``FittedCUSUM`` and ``FittedShewhart`` (the same
  sentence, as a ``#`` comment rather than a docstring, on the
  ``advisories`` field itself). **All seven are pinned below** --
  ``test_every_literal_100_370_range_in_public_baseline_source_matches_adr011``
  -- rather than the original single-carrier test, so a future change to
  either constant without updating all seven fails by naming exactly
  which carrier disagrees, instead of an audit that claimed completeness
  while checking one occurrence out of seven.

**Finding: no false range claim remains.** The one motivating example
(``MIN_MEANINGFUL_ARL``) was already resolved by ADR-011 before this file
was written; this file's own audit found nothing further wrong, and turns
that audit into a permanent guard rather than a one-time finding -- see
each test below for what specifically is pinned. **Reported, not silently
assumed:** if a future change narrows any of these ranges without updating
the corresponding docstring, the relevant test below fails with the
specific endpoint that stopped being attainable.

**What this file does NOT do**, per BIN-122's explicit constraint: it does
not correct a range it finds wrong. Had a genuine false claim turned up,
the right response is to report it and let a product decision narrow the
range (or fix the docstring) -- not to change ``src/`` from a test-writing
pass. None turned up, so this remains moot for now, but the discipline is
recorded here in case a future run of this file does find one.

**What this file cannot catch.**

* **Only the four docstrings named above.** ``caliper.measurement`` and
  ``caliper.monitoring`` carry no numeric range claim in their own public
  docstrings today (also checked by hand while writing this file -- neither
  bounded context validates a numeric parameter against a fixed
  ``[min, max]`` the way baseline's three fitting functions do), so nothing
  there is audited. A future range claim added to either context needs its
  own audit, not an extension assumed to be covered here.
* **A docstring that omits a range entirely** is not flagged by this file
  -- it audits claims that exist, not silence. A newly-added, undocumented
  validation rule is a documentation gap, not a "false claim", and is a
  different kind of defect (documentation coverage, not documentation
  correctness).
* **Attainability at exactly one endpoint value does not prove the whole
  range is attainable.** ``test_joint_parameter_validity.py`` is the
  file that sweeps the interior of each range generatively; this file
  only pins the two boundary claims a docstring actually makes in words
  (a range's stated floor and ceiling).
"""

from __future__ import annotations

import inspect
import re

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
from caliper.baseline.domain.fitted_control_limits import FittedControlLimits
from caliper.baseline.domain.fitted_cusum import FittedCUSUM
from caliper.baseline.domain.fitted_ewma import FittedEWMA
from caliper.baseline.domain.fitted_shewhart import FittedShewhart
from caliper.baseline.domain.parameter_guards import MIN_TARGET_ARL, VERIFIED_ARL_FLOOR
from tests.support.baseline_strategies import probe_baseline

_PROBE_BASELINE = probe_baseline()

_LITERAL_RANGE_PATTERN = re.compile(r"\[(\d+),\s*(\d+)\)")


# --- The literal-number claim: seven carriers, not one ------------------------


def test_every_literal_100_370_range_in_public_baseline_source_matches_adr011() -> None:
    """Every literal ``"[100, 370)"``-shaped range across the public fitting
    surface still equals ADR-011's actual constants.

    **Replaces a narrower test that checked only one of the seven places
    this literal actually appears (BIN-124 round 3, Blocker 2, found by
    code review 2026-09-12).** This file's own module docstring had
    claimed ``FittedControlLimits.advisories`` was the *only* carrier of
    the literal range -- confirmed false by grep: it recurs in
    ``fit_ewma``'s, ``fit_cusum``'s and ``fit_shewhart``'s own docstrings,
    and as a field comment on each of ``FittedEWMA``, ``FittedCUSUM`` and
    ``FittedShewhart``. An audit that under-counts and claims completeness
    is worse than no audit -- it settles a question that was still open.

    Rather than hand-pin all seven by file and line number (fragile --
    silently stops covering a carrier the moment any of these six files
    is edited and a line shifts), this test finds every occurrence
    mechanically: it reads each carrier's actual text (a docstring via
    ``__doc__``, or a class's full source -- comments included -- via
    ``inspect.getsource``) and asserts every ``[floor, ceiling)`` literal
    found in it equals ``(MIN_TARGET_ARL, VERIFIED_ARL_FLOOR)``, naming
    the offending carrier and literal if one has drifted.

    A ``found_any`` assertion at the end guards against the opposite
    failure mode this project has been bitten by before (``BIN-103``'s
    coverage-measurement gap, this ticket's own round 1/2 vacuous-probe
    findings): a carrier list or regex that silently stops matching
    anything would otherwise leave this test passing over zero literals,
    indistinguishable from "still correct".
    """
    carriers: dict[str, str] = {
        "fit_ewma docstring": fit_ewma.__doc__ or "",
        "fit_cusum docstring": fit_cusum.__doc__ or "",
        "fit_shewhart docstring": fit_shewhart.__doc__ or "",
        "FittedControlLimits.advisories docstring": (
            FittedControlLimits.advisories.__doc__ or ""
        ),
        "FittedEWMA source": inspect.getsource(FittedEWMA),
        "FittedCUSUM source": inspect.getsource(FittedCUSUM),
        "FittedShewhart source": inspect.getsource(FittedShewhart),
    }
    expected = (MIN_TARGET_ARL, VERIFIED_ARL_FLOOR)
    found_any = False
    for carrier_name, text in carriers.items():
        for match in _LITERAL_RANGE_PATTERN.finditer(text):
            found_any = True
            documented = (float(match.group(1)), float(match.group(2)))
            assert documented == expected, (
                f"{carrier_name} states a literal range "
                f"[{match.group(1)}, {match.group(2)}) that no longer "
                f"matches ADR-011's actual (MIN_TARGET_ARL={MIN_TARGET_ARL}, "
                f"VERIFIED_ARL_FLOOR={VERIFIED_ARL_FLOOR})"
            )
    assert found_any, (
        "expected at least one literal '[floor, ceiling)' range across the "
        "seven audited carriers -- found none; the carrier list or the "
        "regex itself may be broken, which would otherwise leave this test "
        "vacuously passing"
    )


# --- The already-fixed worked example: no stale reference survives -----------


def test_the_retired_constant_name_is_absent_from_public_fitting_docstrings() -> None:
    """Neither ``MIN_MEANINGFUL_ARL`` nor ``MIN_COHERENT_ARL`` is cited as a floor.

    This item's own worked example, before ADR-011: a docstring/comment
    claiming ``MIN_MEANINGFUL_ARL = 1.0`` was the floor, when the actually
    enforced (and now correctly documented) floor is
    ``MIN_TARGET_ARL = 100.0``. ADR-011 renamed the coherence-only constant
    to ``MIN_COHERENT_ARL`` specifically so it could never again be
    mistaken for the enforced floor in a docstring or error message.
    Pinning its absence here means a future edit that reintroduces either
    name into one of these three public docstrings is caught immediately,
    rather than waiting for another external review to notice.
    """
    for fit_function in (fit_ewma, fit_cusum, fit_shewhart):
        doc = fit_function.__doc__
        assert doc is not None
        assert "MIN_MEANINGFUL_ARL" not in doc, (
            f"{fit_function.__name__}'s docstring still cites the retired "
            "MIN_MEANINGFUL_ARL name -- ADR-011 renamed it to MIN_COHERENT_ARL "
            "and replaced it as the enforced floor with MIN_TARGET_ARL"
        )
        assert "MIN_COHERENT_ARL" not in doc, (
            f"{fit_function.__name__}'s docstring cites MIN_COHERENT_ARL as "
            "if it were an enforced bound -- it is internal-only (ADR-011) "
            "and is not the floor this function actually enforces "
            "(MIN_TARGET_ARL is)"
        )


# --- fit_ewma: both documented ranges' endpoints are attainable ---------------


def test_fit_ewma_documented_target_arl_range_endpoints_are_attainable() -> None:
    """``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]``, both ends, fit cleanly."""
    low = fit_ewma(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL)
    assert low.requested_arl == MIN_TARGET_ARL

    high = fit_ewma(_PROBE_BASELINE, target_arl=MAX_MEANINGFUL_ARL)
    assert high.requested_arl == MAX_MEANINGFUL_ARL


def test_fit_ewma_documented_smoothing_param_range_endpoints_are_attainable() -> None:
    """``[MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM]``, both ends, fit cleanly."""
    low = fit_ewma(
        _PROBE_BASELINE,
        target_arl=VERIFIED_ARL_FLOOR,
        smoothing_param=MIN_SMOOTHING_PARAM,
    )
    assert low.smoothing_param == MIN_SMOOTHING_PARAM

    high = fit_ewma(
        _PROBE_BASELINE,
        target_arl=VERIFIED_ARL_FLOOR,
        smoothing_param=MAX_SMOOTHING_PARAM,
    )
    assert high.smoothing_param == MAX_SMOOTHING_PARAM


# --- fit_cusum: both documented ranges' endpoints are attainable --------------
# (each at a partner value chosen to keep the *pair* jointly attainable too --
# see this file's module docstring on why fit_cusum's own docstring does not
# claim the full product is achievable, only that each range's ends are.)


def test_fit_cusum_documented_target_arl_range_endpoints_are_attainable() -> None:
    """``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]`` at the default reference value."""
    low = fit_cusum(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL)
    assert low.requested_arl == MIN_TARGET_ARL

    high = fit_cusum(_PROBE_BASELINE, target_arl=MAX_MEANINGFUL_ARL)
    assert high.requested_arl == MAX_MEANINGFUL_ARL


def test_fit_cusum_documented_reference_value_range_endpoints_are_attainable() -> None:
    """``[MIN_REFERENCE_VALUE, MAX_REFERENCE_VALUE]``, each at an attainable target."""
    low = fit_cusum(
        _PROBE_BASELINE,
        target_arl=VERIFIED_ARL_FLOOR,
        reference_value=MIN_REFERENCE_VALUE,
    )
    assert low.reference_value == MIN_REFERENCE_VALUE

    # MAX_REFERENCE_VALUE's own minimum attainable ARL0 (~1158.3, two-sided)
    # sits above VERIFIED_ARL_FLOOR -- use MAX_MEANINGFUL_ARL instead so this
    # test exercises the documented ceiling itself, not an incidental
    # attainability floor from a different guard.
    high = fit_cusum(
        _PROBE_BASELINE,
        target_arl=MAX_MEANINGFUL_ARL,
        reference_value=MAX_REFERENCE_VALUE,
    )
    assert high.reference_value == MAX_REFERENCE_VALUE


# --- fit_shewhart: its one documented range's endpoints are attainable --------


def test_fit_shewhart_documented_target_arl_range_endpoints_are_attainable() -> None:
    """``[MIN_TARGET_ARL, MAX_MEANINGFUL_ARL]``, both ends, fit cleanly.

    Shewhart has no second tuning parameter (BIN-95 A3/A5), so this is the
    only documented range in its docstring.
    """
    low = fit_shewhart(_PROBE_BASELINE, target_arl=MIN_TARGET_ARL)
    assert low.requested_arl == MIN_TARGET_ARL

    high = fit_shewhart(_PROBE_BASELINE, target_arl=MAX_MEANINGFUL_ARL)
    assert high.requested_arl == MAX_MEANINGFUL_ARL


__all__: list[str] = []
