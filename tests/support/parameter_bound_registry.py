"""Registry classifying every ``@given`` parameter/factory name BIN-124 round 2 found.

**Pairs with** ``tests/support/hypothesis_bound_scan.py`` **the way
``tests/support/exception_contract_registry.py`` pairs with**
``drift_caliper.__all__``: the scanner enumerates every ``min_value=``/
``max_value=`` bound site in ``tests/`` mechanically, by parsing source; this
module says, for each distinct name the scanner can attach to a site
(a ``@given(...)`` keyword, or a strategy-factory function name), whether it
feeds a parameter the library validates (:class:`GovernedParameter` -- carries
a ``probe`` that asserts a given numeric value is accepted by the *real*
public entry point today) or is a pure simulation/geometry knob that reaches
no library validation (:class:`ExcludedParameter` -- a name plus the reason).

``tests/unit/baseline/test_parameter_strategy_contract.py`` asserts every
name the scanner actually found is classified in exactly one of the two
registries below -- so a ninth file, or a tenth ``@given`` parameter, cannot
silently pass unclassified. That completeness assertion is the mechanical
part. This module -- which name means what -- is not: it is a curated,
human judgement call, made once per distinct name, same as
``exception_contract_registry.py``'s ``EXCLUDED``/``EXERCISABLE`` split.

**Why probe the actual numeric value, not just check the name is known.**
The failure this ticket guards against is not "a strategy uses an
unrecognised name" -- it is "a strategy's bound is a *value* the library no
longer accepts, even though the name importing it is perfectly legitimate".
The literal BIN-131/ADR-011 shape: ``MIN_COHERENT_ARL`` (1.0) is a real,
correctly-exported constant, still imported by test files that
*deliberately* exercise the gap between it and ``MIN_TARGET_ARL`` (100.0,
BIN-124's own reopening comment names this exact pin as the required
regression demonstration). A test file could legally reference
``MIN_COHERENT_ARL`` as a strategy's ``min_value=`` -- no ``ImportError``,
nothing a linter would catch -- and every draw from ``[1.0, ...]`` would
then be silently illegal three-quarters of the time. Checking the *name*
"target_arl" is registered proves nothing about whether *this file's*
bound value is still legal; only calling the real library function with
that exact value does.

**How the numeric value is obtained.** The meta-test resolves each
:class:`~tests.support.hypothesis_bound_scan.BoundSite`'s ``bound_source``
(the exact expression text used as ``min_value=``/``max_value=``, e.g.
``"MIN_TARGET_ARL"`` or ``"_MONOTONICITY_ARL_LOW_MIN"``) against the
*actual* module it was found in -- importing that test module and reading
the name from its namespace, or evaluating the expression there if it is
not a bare name. This is what makes the probe test today's value, not a
value this registry has to duplicate or keep in sync by hand.

**What this registry cannot catch, stated rather than left implicit.**

* **A name this module has never seen is not auto-classified as anything.**
  The completeness test fails loudly instead -- see the module docstring
  above. That failure *is* the mechanism; it is not a gap in it.
* **A bound expression the scanner cannot resolve to a value** (an
  arbitrary computed expression that is not a bare name and does not
  evaluate cleanly against the module's own namespace) is a resolution
  failure the meta-test reports explicitly, not a silently-skipped site.
  Every real site in this suite today is either a bare imported/module-level
  name or a numeric literal (verified directly while writing this file --
  see the meta-test's own docstring for the full enumeration), so this has
  not yet been exercised in practice.
* **A probe only asserts the library accepts the value; it does not assert
  the library rejects anything just outside it.** That is round 1's
  BIN-123-direction concern (over-rejection) and is out of scope here --
  this guard is specifically about under-rejection drift (a strategy
  drawing values the library has started refusing), the ADR-011 pattern.
* **Simulation/geometry knobs are excluded by name, not verified to be
  harmless in general.** ``scale``/``shift``/``arl_gap``/``count`` are
  judged, once, to feed no library validation directly -- if a future
  chart ever validated one of those directly, that judgement would need
  revisiting. Stated as a review point, not hidden.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from drift_caliper.baseline import Baseline, fit_cusum, fit_ewma, fit_shewhart
from drift_caliper.baseline.domain.cusum_fitting import _min_attainable_arl0
from drift_caliper.baseline.domain.parameter_guards import VERIFIED_ARL_FLOOR
from tests.support.baseline_strategies import probe_baseline

# An ordinary, unremarkable fittable baseline -- see `probe_baseline()`
# for why it is deliberately not itself a hostile input.
_PROBE_BASELINE = probe_baseline()


def _probe_target_arl(value: float) -> None:
    """``target_arl``'s ADR-011 range check is shared code (parameter_guards.py),
    called identically by all three ``fit_*`` functions -- ``fit_shewhart`` is
    used here because it is the cheapest of the three (sub-millisecond) and
    exercises the exact same ``classify_target_arl`` call the other two do.
    """
    fit_shewhart(_PROBE_BASELINE, target_arl=value)


def _probe_smoothing_param(value: float) -> None:
    """EWMA-specific: ``smoothing_param`` is only meaningful on ``fit_ewma``."""
    fit_ewma(_PROBE_BASELINE, target_arl=VERIFIED_ARL_FLOOR, smoothing_param=value)


def _probe_reference_value(value: float) -> None:
    """CUSUM-specific.

    ``target_arl`` is chosen so the probe isolates ``reference_value``'s own
    ``[MIN_REFERENCE_VALUE, MAX_REFERENCE_VALUE]`` legality from BIN-117's
    *separate* per-parameter attainability floor, which rises with
    ``reference_value`` (``cusum_fitting.py``: ~1158.3 two-sided at
    ``reference_value=MAX_REFERENCE_VALUE``) -- reusing the same
    ``_min_attainable_arl0`` production import the suite's own CUSUM
    property tests already use (see
    ``test_cusum_arl_simulated_properties.py``), rather than re-deriving or
    guessing a safe constant.
    """
    safe_target_arl = max(
        VERIFIED_ARL_FLOOR, _min_attainable_arl0(value, "two_sided") * 1.01
    )
    fit_cusum(_PROBE_BASELINE, target_arl=safe_target_arl, reference_value=value)


# ``threshold``'s ceiling is currently unbounded, and a probe that merely
# passes would be vacuous rather than reassuring: ``max_value=30`` and
# ``max_value=3_000_000`` would both succeed identically, so the ceiling half
# of this parameter's check tests nothing at all. Raised by ``code-reviewer``
# on BIN-124, which measured it rather than accepting the docstring's softer
# "no upper bound today" framing.
#
# ⚠️ A ``pytest.skip`` would be honest and inert -- it would sit green forever
# and say nothing on the day the situation changes. ``_ABSURD_THRESHOLD``
# instead **pins the absence**: it asserts that an obviously-unreasonable
# threshold is still accepted, which is true today and documents *why* the
# ceiling probe is vacuous. The day an ADR adds a real upper bound, this
# assertion fails and forces whoever added it to revisit this registry --
# turning a silent gap into a prompt at exactly the moment it matters.
#
# That is the same shape as ``test_baseline_package_exports.py``'s
# absence-pinning, and the direct answer to the pattern BIN-128 exists for:
# a caveat that surfaces when the thing it guards changes, rather than one
# that waits to be re-read.
_ABSURD_THRESHOLD = 3_000_000


def _probe_threshold(value: float) -> None:
    """Probe ``threshold``, and pin that its ceiling is genuinely unbounded.

    ``Baseline.check_sufficiency`` enforces only "positive whole number"
    today. See ``_ABSURD_THRESHOLD`` above for why this pins the absence of
    a ceiling rather than skipping.
    """
    Baseline().check_sufficiency(threshold=int(value))
    # Pin the absence, so a future upper bound cannot land unnoticed.
    Baseline().check_sufficiency(threshold=_ABSURD_THRESHOLD)


@dataclass(frozen=True)
class GovernedParameter:
    """A ``@given``/factory name that feeds a parameter the library validates."""

    name: str
    probe: Callable[[float], None]
    note: str


@dataclass(frozen=True)
class ExcludedParameter:
    """A ``@given``/factory name that reaches no library validation."""

    name: str
    reason: str


# ---------------------------------------------------------------------------
# Governed `@given(...)` parameter names
# ---------------------------------------------------------------------------

GOVERNED_GIVEN_PARAMETERS: tuple[GovernedParameter, ...] = (
    GovernedParameter(
        "target_arl",
        _probe_target_arl,
        "ADR-011 hard floor (MIN_TARGET_ARL) / ceiling (MAX_MEANINGFUL_ARL), "
        "enforced identically by all three fit_* functions.",
    ),
    GovernedParameter(
        "arl_low",
        _probe_target_arl,
        "Not itself named target_arl, but passed as fit_cusum's/fit_ewma's/"
        "fit_shewhart's target_arl= directly in every monotonicity property "
        "test (`fit_cusum(baseline, target_arl=arl_low, ...)`) -- same "
        "validated parameter, different local name.",
    ),
    GovernedParameter(
        "smoothing_param",
        _probe_smoothing_param,
        "EWMA's own [MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM] range check.",
    ),
    GovernedParameter(
        "reference_value",
        _probe_reference_value,
        "CUSUM's own [MIN_REFERENCE_VALUE, MAX_REFERENCE_VALUE] range check.",
    ),
    GovernedParameter(
        "threshold",
        _probe_threshold,
        "Baseline.check_sufficiency's positive-whole-number requirement.",
    ),
)

# ---------------------------------------------------------------------------
# Excluded `@given(...)` parameter names -- simulation/geometry knobs
# ---------------------------------------------------------------------------

EXCLUDED_GIVEN_PARAMETERS: tuple[ExcludedParameter, ...] = (
    ExcludedParameter(
        "arl_gap",
        "An offset added to arl_low to derive a second target_arl "
        "(`arl_high = arl_low + arl_gap`) for a monotonicity comparison -- "
        "never itself passed to a fit_* call, and arl_low's own floor "
        "already keeps the derived sum legal (the sum of two values at "
        "or above MIN_TARGET_ARL is always at or above MIN_TARGET_ARL). "
        "Its own min_value=1.0 is a chosen minimum gap size, not a "
        "library-validated bound.",
    ),
    ExcludedParameter(
        "scale",
        "A multiplicative factor applied to raw scores to test invariance "
        "under affine transform -- a simulation parameter over the test's "
        "own input construction, never itself passed to any fit_* call.",
    ),
    ExcludedParameter(
        "shift",
        "An additive offset applied to raw scores, same reasoning as "
        "`scale` above -- feeds test-side input construction, not a "
        "library-validated parameter.",
    ),
    ExcludedParameter(
        "count",
        "The number of observations placed in a baseline fixture in "
        "test_baseline_sufficiency.py's gap/sufficiency property -- a "
        "test-side fixture-construction parameter (how many observations "
        "to record), not itself passed to any validated keyword argument. "
        "`threshold` (the parameter actually validated by "
        "check_sufficiency) is registered separately above.",
    ),
)

# ---------------------------------------------------------------------------
# Strategy-factory function names (Tier 2 -- see hypothesis_bound_scan.py)
# ---------------------------------------------------------------------------

EXCLUDED_FACTORY_FUNCTIONS: tuple[ExcludedParameter, ...] = (
    ExcludedParameter(
        "baseline_scores_strategy",
        "Governed by the sibling meta-test from BIN-124 round 1 -- "
        "tests/unit/baseline/test_baseline_scores_strategy_contract.py -- "
        "which asks the real fit_ewma/fit_cusum/fit_shewhart entry points "
        "directly whether every draw is accepted, over the full scores "
        "list rather than one boundary value. Re-probing its two bounds "
        "(-10.0/10.0) here would duplicate that guard rather than add "
        "coverage, and the `scores` dimension is explicitly out of this "
        "ticket's scope (see this module's own docstring on why "
        "target_arl/reference_value/threshold/smoothing_param are the "
        "surface being added, not scores again).",
    ),
    ExcludedParameter(
        "overflow_prone_scores",
        "BIN-121 part 1: draws near +/-sys.float_info.max to exercise "
        "moving-range overflow. Deliberately outside the fittable range "
        "-- the test asserts fit-or-CaliperError, not fit-successfully. "
        "Probing these bounds against a fit_* call would prove nothing: "
        "every draw is expected to be rejected as degenerate.",
    ),
    ExcludedParameter(
        "underflow_prone_scores",
        "BIN-121 part 1: draws subnormal/near-zero perturbations to "
        "exercise moving-range sigma underflow. Same reasoning as "
        "overflow_prone_scores above -- every draw is expected to be "
        "rejected as degenerate.",
    ),
    ExcludedParameter(
        "signed_zero_scores",
        "BIN-121 part 1: mixes 0.0/-0.0 and optional near-subnormal "
        "values to exercise the zero-variance and sigma-underflow "
        "guards. Same reasoning as the other two BIN-121 factories.",
    ),
)

_GOVERNED_GIVEN_NAMES = frozenset(p.name for p in GOVERNED_GIVEN_PARAMETERS)
_EXCLUDED_GIVEN_NAMES = frozenset(p.name for p in EXCLUDED_GIVEN_PARAMETERS)
_EXCLUDED_FACTORY_NAMES = frozenset(p.name for p in EXCLUDED_FACTORY_FUNCTIONS)


def governed_probe_for(name: str) -> Callable[[float], None]:
    """Look up the probe for a governed ``@given`` parameter name."""
    for governed in GOVERNED_GIVEN_PARAMETERS:
        if governed.name == name:
            return governed.probe
    raise KeyError(name)


__all__ = [
    "EXCLUDED_FACTORY_FUNCTIONS",
    "EXCLUDED_GIVEN_PARAMETERS",
    "GOVERNED_GIVEN_PARAMETERS",
    "ExcludedParameter",
    "GovernedParameter",
    "governed_probe_for",
]
