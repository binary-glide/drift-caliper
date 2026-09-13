"""``fit_cusum`` -- fit CUSUM control limits from a Phase I baseline (BIN-94).

See ``docs/domain-model.md`` (Library Operations -- Fit CUSUM) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
sections 5-6 for the fitting signature shape and parameter semantics, and
ADR-001 for the calibration method (Siegmund's (1985) corrected diffusion
approximation, a closed form -- unlike EWMA, which needs a Markov-chain
method).

## Calibration method

Caliper standardises CUSUM in sigma units, exactly as ``fit_ewma`` does (see
that module's "Why sigma does not need to be controlled" note): a one-sided
CUSUM statistic accumulates deviations of the *standardised* score from its
target, i.e. ``S_t = max(0, S_(t-1) + (Z_t - k))`` where ``Z_t`` is the score
standardised by the shared ``sigma_estimate`` and ``k`` (the reference value)
is itself expressed in sigma units. The chart signals when ``S_t`` first
exceeds the decision interval ``h``, also in sigma units -- this is exactly
why ``FittedCUSUM.decision_interval`` is not on the observation scale
(ADR-004 section 3).

**Siegmund's (1985) approximation** for the in-control (zero-shift) average
run length of a one-sided CUSUM with reference value ``k`` and decision
interval ``h`` is, per D. C. Montgomery's *Introduction to Statistical
Quality Control* (7th ed.), equation 9.6 (p. 423) -- itself citing Siegmund
(1985), *Sequential Analysis: Tests and Confidence Intervals*, and reproduced
with full citation in S. Maghsoodloo's Auburn University INSY 7330 lecture
notes (``https://www.eng.auburn.edu/~maghssa/INSY7330/Cusum-Control-Charts-M2013-Maghsoodloo.pdf``,
fetched and verified during BIN-94's numerical-proof research; Siegmund
(1985) itself and Montgomery's 7th edition were both inaccessible directly in
this environment -- the same paywall gap ADR-004's amendment already recorded
for Montgomery Chapter 9):

    ARL(shift) = [exp(-2 * Delta * b) - 1 + 2 * Delta * b] / (2 * Delta^2)

where ``b = h + 1.166`` (Siegmund's correction constant -- corroborated by an
independent web search returning the identical ``b = h + 1.166`` relation)
and ``Delta = shift - k`` for a chart detecting an *increase*. At
``shift = 0`` (in control), ``Delta = -k``, which simplifies the formula
(algebraically, substituting ``Delta = -k``) to the in-control ARL0:

    ARL0(k, h) = [exp(2 * k * b) - 1 - 2 * k * b] / (2 * k^2)

This is ``_cusum_arl0`` below. See
``tests/unit/baseline/test_cusum_arl_published_values.py`` for the full
verification chain, including independent corroboration against an
externally-published exact (non-approximation) figure and a closed-form
self-check of the checker itself, per the BIN-65 carried finding that a
verification routine must be validated before it is trusted.

**Two-sided combination.** For a two-sided CUSUM built from two symmetric
one-sided arms (same ``k``/``h`` magnitude on each side), Montgomery's
equation 9.7 (same source) gives the combined ARL0 as the harmonic
combination of the two arms' individual ARL0s:

    1 / ARL0_two_sided = 1 / ARL0_lower_arm + 1 / ARL0_upper_arm

For a symmetric design (``ARL0_lower_arm == ARL0_upper_arm``), this reduces
to ``ARL0_two_sided = ARL0_one_sided_arm / 2``. ``fit_cusum`` reports
``requested_arl``/``achieved_arl`` as the ARL0 an engineer configuring
``direction="two_sided"`` actually experiences from the deployed monitor
(the combined, two-sided figure) -- **not** the per-arm one-sided figure.
This reading is not pinned verbatim by ADR-004's text (which specifies the
*representation*, ARL0, but not explicitly whether it is per-arm or
combined for the two-sided case); it is the interpretation
``backend-test-writer`` judged most consistent with "false alarm tolerance"
as an auditable, engineer-facing commitment (ADR-004 section 4) -- the
engineer specifies one number and the deployed two-sided monitor's overall
false-alarm behaviour should match it. **Confirmed during BIN-94
implementation**: a per-arm reading would mean an engineer requesting
ARL0 = 500 sees a false alarm roughly every 250 observations, which is not
the auditable commitment ADR-004 describes; the Monte Carlo simulation in
``tests/unit/baseline/test_cusum_arl_published_values.py`` independently
corroborates the harmonic two-arm combination this reading relies on. See
that file's module docstring for the settled statement.

References
----------
.. [1] Montgomery, D. C. (2013). *Introduction to Statistical Quality
       Control* (7th ed.). Wiley, p. 423, eqs. 9.6-9.7 -- states
       Siegmund's (1985) approximation, ``b = h + 1.166``, and the
       two-sided combination formula.
"""

from __future__ import annotations

import math
import statistics

from scipy.optimize import brentq

from caliper.baseline.domain.baseline import Baseline
from caliper.baseline.domain.ewma_fitting import MAX_MEANINGFUL_ARL
from caliper.baseline.domain.fitted_cusum import FittedCUSUM
from caliper.baseline.domain.fitting_advisory import FittingAdvisory
from caliper.baseline.domain.parameter_guards import (
    MIN_TARGET_ARL,
    classify_target_arl,
    require_real_number,
    require_type,
)
from caliper.baseline.domain.spc_numerics import (
    _has_zero_variance,
    _moving_range_sigma,
    _overflow_safe_mean,
)
from caliper.errors import (
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)

# --- Reference value (k) valid range -----------------------------------------
#
# The CUSUM statistic's own mathematical definition (S_t = max(0, S_(t-1) +
# (Z_t - k))) places no upper bound on k and only excludes k <= 0 as a matter
# of the chart being degenerate at or below that point -- the open interval
# (0, infinity) has no smallest or largest element to inherit a bound from,
# so both floor and ceiling below are engineering defaults, not published
# constants (mirroring ewma_fitting.py's MIN_SMOOTHING_PARAM, which is the
# identical situation for lambda's open-at-zero range).
#
# k is conventionally half the standardised shift size a CUSUM design is
# tuned to detect (Delta = 2k -- see the SAS/STAT and MetricGate worked
# examples cited below for DEFAULT_REFERENCE_VALUE): the published guidance
# found during BIN-94's research names a *practical* range of Delta from
# about 0.5 to 2 sigma (k roughly 0.25 to 1.0), not a hard mathematical
# limit -- no source found states a numeric floor or ceiling on k itself,
# because k is a design choice tied to the shift an engineer cares about,
# not a quantity the chart's own mathematics bounds beyond positivity.
#
# MIN_REFERENCE_VALUE = 0.01 mirrors ewma_fitting.py's MIN_SMOOTHING_PARAM
# floor for consistency across the library's two closed-form/Markov
# calibration methods, and has an independent justification from the
# formula itself: as k -> 0, _cusum_arl0(k, h) -> (h + 1.166)^2 (see
# _cusum_arl0's docstring) -- independent of k entirely. Below some small
# k, the reference value stops meaningfully distinguishing chart designs
# from each other (the calibration degenerates to "solve for h from a
# k-independent formula"), which is not a useful design point to allow
# silently. 0.01 (Delta = 0.02 sigma) is comfortably below the smallest
# shift any of the sources above discuss as practically meaningful, while
# staying an order of magnitude above where that degeneracy bites.
#
# MAX_REFERENCE_VALUE = 5.0 (Delta = 10 sigma) is grounded in Caliper's own
# domain rather than the general CUSUM literature: judge scores are bounded
# in [0, 1] (ADR-001), so a baseline's total spread can never exceed 1.0 on
# the raw scale, and a design tuned to detect a 10-sigma shift is already
# far beyond any shift a bounded [0, 1] scoring baseline could exhibit --
# comfortably generous headroom above the 0.25-1.0 range the sources above
# treat as the practically useful band, without being unbounded.
#
# At k=MAX_REFERENCE_VALUE the smallest attainable ARL0 (~1158.3 two-sided,
# see _min_attainable_arl0) sits well above ADR-011's MIN_TARGET_ARL policy
# floor (100) -- BIN-117's attainability check and ADR-011's policy floor
# are independent bounds, and the attainability floor is the one that binds
# here, not the policy floor.
MIN_REFERENCE_VALUE = 0.01
MAX_REFERENCE_VALUE = 5.0

# --- Library default reference value -----------------------------------------
#
# k = 0.5 (detecting a 1-sigma shift, since k is conventionally half the
# standardised shift size the chart is tuned for) is the design point used
# in every worked example found during BIN-94's research: the NIST/SEMATECH
# e-Handbook of Statistical Methods' CUSUM section states the rule of thumb
# "choose k to be half the delta shift" with a delta=1 example giving k=0.5;
# the SAS/STAT QC procedure documentation's own worked CUSUM example
# (https://www.sfu.ca/sasdoc/sashtml/qc/chap12/sect6.htm) also uses k=0.5;
# and multiple independent SPC references (qimacros.com, spcplot.com)
# describe k=0.5 paired with h=4 or h=5 as the conventional choice. This is
# corroborated from several independent secondary sources but not read
# directly from Siegmund (1985) or Montgomery -- domain-implementer should
# confirm against a primary source before shipping, per CLAUDE.md's
# constant-verification discipline.
DEFAULT_REFERENCE_VALUE = 0.5

# --- Direction -----------------------------------------------------------------
#
# ADR-004 section 6: two-sided default, configurable to one-sided. Lower arm
# detects degradation (score drifts down); upper arm detects improvement
# (score drifts up, baseline stale) -- ADR-001's higher-is-better mapping.
DEFAULT_DIRECTION = "two_sided"
_VALID_DIRECTIONS = frozenset({"two_sided", "lower", "upper"})

# --- Siegmund's (1985) correction constant -----------------------------------
#
# b = h + SIEGMUND_CORRECTION. See module docstring's "Calibration method"
# section for the full citation chain (Siegmund 1985, via Montgomery (2013)
# 7th ed. Eq. 9.6, reproduced with citation in Maghsoodloo's Auburn INSY 7330
# lecture notes) and tests/unit/baseline/test_cusum_arl_published_values.py
# for the independent numeric corroboration performed before this constant
# was trusted.
_SIEGMUND_CORRECTION = 1.166

# Search bracket for the decision interval *h* during root-finding. Mirrors
# ``ewma_fitting.py``'s ``_MIN_LIMIT_MULTIPLIER``/``_MAX_LIMIT_MULTIPLIER``
# reasoning exactly: h=0 exactly is not itself the failure mode (b is still
# positive, since b = h + _SIEGMUND_CORRECTION), but a small positive floor
# keeps the bracket well away from any degenerate edge, and the upper edge
# is expanded geometrically (see _calibrate_decision_interval) up to this
# ceiling, which comfortably exceeds any h a target_arl within
# [MIN_TARGET_ARL, MAX_MEANINGFUL_ARL] (ADR-011) requires in practice --
# verified during research across the full valid (reference_value,
# target_arl) grid, including both boundary corners, without the geometric
# expansion coming close to this ceiling or to a floating-point overflow in
# `math.exp`.
_MIN_DECISION_INTERVAL = 1e-6
_MAX_DECISION_INTERVAL = 1e5

_MOVING_RANGE_METHOD = "moving_range"

_CHART_TYPE = "cusum"
_CALIBRATION_METHOD = "siegmund_approximation"
_ZERO_VARIANCE_REASON = "zero_variance"


# --- Parameter validation ----------------------------------------------------


def _require_target_arl(
    target_arl: float | None,
) -> tuple[float, FittingAdvisory | None]:
    """Validate ``target_arl``, returning it narrowed to ``float`` plus any advisory.

    Mirrors ``ewma_fitting._require_target_arl`` -- ``target_arl`` is
    optional in the Python signature but required by Caliper's validation
    (ADR-004 section 5): omitting it is a classifiable ``CaliperError``,
    never Python's ``TypeError``. The range check and ADR-011's
    flagged-tier disclosure are delegated to
    ``parameter_guards.classify_target_arl``, shared verbatim with
    ``ewma_fitting``/``shewhart_fitting`` rather than tripled.
    """
    constraint = f"must be a finite float in [{MIN_TARGET_ARL}, {MAX_MEANINGFUL_ARL}]"
    if target_arl is None:
        raise InvalidParameterError(
            "target_arl is required to fit CUSUM control limits",
            context={
                "parameter": "target_arl",
                "constraint": constraint,
                "kind": "missing",
            },
            recovery_hint=(
                "Specify target_arl explicitly -- the in-control ARL0 (false "
                "alarm tolerance) you want the fitted chart to achieve, e.g. "
                "370 or 500. Caliper will not choose this on your behalf: it "
                "is a statistical commitment the engineer must own."
            ),
        )
    # BIN-126: reject a bool or a non-numeric value (e.g. a string) before
    # any arithmetic comparison is attempted against it -- see
    # parameter_guards.require_real_number's docstring for why this is a
    # behavioural, not nominal, check.
    numeric_target_arl = require_real_number(
        target_arl, parameter="target_arl", constraint=constraint
    )
    # ADR-011: refuses below MIN_TARGET_ARL (100) or above MAX_MEANINGFUL_ARL;
    # returns a FittingAdvisory when inside [MIN_TARGET_ARL, VERIFIED_ARL_FLOOR).
    # BIN-117's own attainability check runs separately, after this --
    # a different bound that can sit far above this one (see
    # _min_attainable_arl0/_require_attainable_target_arl below).
    advisory = classify_target_arl(
        numeric_target_arl, max_target_arl=MAX_MEANINGFUL_ARL
    )
    return numeric_target_arl, advisory


def _validate_reference_value(reference_value: float | None) -> float | None:
    """Validate a supplied ``reference_value``, narrowed to ``float`` if given.

    ``reference_value`` is genuinely optional -- ``None`` is not validated
    here at all; ``fit_cusum`` substitutes ``DEFAULT_REFERENCE_VALUE``.
    """
    if reference_value is None:
        return None
    constraint = (
        f"must be a finite float in [{MIN_REFERENCE_VALUE}, {MAX_REFERENCE_VALUE}]"
    )
    # BIN-126: reject a bool or a non-numeric value before any arithmetic
    # comparison is attempted against it.
    numeric_reference_value = require_real_number(
        reference_value, parameter="reference_value", constraint=constraint
    )
    if not math.isfinite(numeric_reference_value) or not (
        MIN_REFERENCE_VALUE <= numeric_reference_value <= MAX_REFERENCE_VALUE
    ):
        raise InvalidParameterError(
            "reference_value is outside the valid range",
            context={
                "parameter": "reference_value",
                "constraint": constraint,
                "kind": "invalid",
                "provided": reference_value,
                "min_value": MIN_REFERENCE_VALUE,
                "max_value": MAX_REFERENCE_VALUE,
                "min_inclusive": True,
                "max_inclusive": True,
            },
            recovery_hint=(
                "Choose a reference_value within "
                f"[{MIN_REFERENCE_VALUE}, {MAX_REFERENCE_VALUE}], or omit it "
                f"entirely to use the library default ({DEFAULT_REFERENCE_VALUE})."
            ),
        )
    return numeric_reference_value


def _validate_direction(direction: str | None) -> str:
    """Validate ``direction`` and return it narrowed to a concrete ``str``.

    ``direction`` is genuinely optional -- ``None`` resolves to
    ``DEFAULT_DIRECTION``. A supplied value outside ``_VALID_DIRECTIONS``
    raises ``InvalidParameterError(kind="invalid")`` (ADR-004 section 6,
    feature file SC8c).
    """
    if direction is None:
        return DEFAULT_DIRECTION
    if direction not in _VALID_DIRECTIONS:
        constraint = f"must be one of {sorted(_VALID_DIRECTIONS)}"
        raise InvalidParameterError(
            "direction is not a recognised value",
            context={
                "parameter": "direction",
                "constraint": constraint,
                "kind": "invalid",
                "provided": direction,
            },
            recovery_hint=(
                f"Choose a direction from {sorted(_VALID_DIRECTIONS)}, or "
                f"omit it entirely to use the library default "
                f"({DEFAULT_DIRECTION!r})."
            ),
        )
    return direction


# --- Siegmund (1985) ARL0 calibration -----------------------------------------


def _cusum_arl0(reference_value: float, decision_interval: float) -> float:
    """One-sided in-control ARL0 via Siegmund's (1985) approximation.

    ``ARL0(k, h) = [exp(2*k*b) - 1 - 2*k*b] / (2*k^2)``, ``b = h +
    _SIEGMUND_CORRECTION``. See module docstring's "Calibration method" for
    the full derivation and citation chain.

    This is exactly the kind of helper the BIN-94 brief warns divides itself
    out of any assertion made only against ``fit_cusum``'s public output, if
    it is used both to calibrate ``decision_interval`` (by root-finding on
    this function) and to compute the reported ``achieved_arl`` (by calling
    this function again on the solved value). See
    ``tests/unit/baseline/test_cusum_arl_published_values.py``, which tests
    this function directly against a published/independently-computed value
    rather than reading a derived quantity back off a ``FittedCUSUM``.

    Parameters
    ----------
    reference_value
        The CUSUM reference value (*k*), in sigma units. Must be strictly
        positive -- the formula has a removable singularity at ``k = 0``
        (the limit as ``k -> 0`` is ``b ** 2``, verified separately in the
        test file) but is not evaluable there directly.
    decision_interval
        The CUSUM decision interval (*h*), in sigma units.

    Returns
    -------
    float
        The one-sided, zero-shift (in-control) ARL0.

    References
    ----------
    .. [1] Montgomery, D. C. (2013). *Introduction to Statistical Quality
           Control* (7th ed.). Wiley, p. 423, eq. 9.6 -- states
           Siegmund's (1985) approximation, ``b = h + 1.166``.
    """
    b = decision_interval + _SIEGMUND_CORRECTION
    exponent = 2.0 * reference_value * b
    return (math.exp(exponent) - 1.0 - exponent) / (2.0 * reference_value**2)


def _combine_two_sided_arl0(lower_arm_arl0: float, upper_arm_arl0: float) -> float:
    """Combine two one-sided in-control ARL0s into the two-sided ARL0.

    Montgomery (2013) 7th ed. Eq. 9.7 (same source as ``_cusum_arl0``'s
    citation chain): ``1 / ARL0_two_sided = 1 / ARL0_lower + 1 /
    ARL0_upper``. For a symmetric design (equal arms), this is exactly
    ``lower_arm_arl0 / 2``.
    """
    return 1.0 / (1.0 / lower_arm_arl0 + 1.0 / upper_arm_arl0)


def _min_attainable_arl0(reference_value: float, direction: str) -> float:
    """Compute the smallest ARL0 actually attainable at ``reference_value`` (BIN-117).

    ⚠️ **This is deliberately evaluated at ``h = _MIN_DECISION_INTERVAL``, not
    at the mathematical limit ``h = 0``.** As ``decision_interval -> 0+``,
    Siegmund's correction constant ``b`` tends to exactly
    ``_SIEGMUND_CORRECTION`` (``b = h + _SIEGMUND_CORRECTION``), so
    ``_cusum_arl0(reference_value, 0.0)`` computes that limit directly --
    but it is an *open* bound, approached as ``h`` shrinks and never itself
    attained by any ``h`` that ``_calibrate_decision_interval`` will
    actually return, since its search bracket's own floor is
    ``_MIN_DECISION_INTERVAL`` (1e-6), not 0. Reporting the ``h=0`` figure
    as "the minimum attainable ARL0" was itself a defect (found in review
    of the first BIN-117 fix): for a whole band of inputs strictly between
    the two values, the pre-check that compared against it would pass, yet
    calibration would still bottom out at ``_MIN_DECISION_INTERVAL`` and
    report a higher achieved ARL0 than requested -- silently reproducing
    the exact class of miscalibration this ticket exists to close, and
    handing the caller a ``min_attainable_arl`` in its error ``context``
    that the library would not actually accept back. Evaluating at
    ``h = _MIN_DECISION_INTERVAL`` instead -- the same floor
    ``_calibrate_decision_interval`` itself searches from -- makes this
    figure genuinely attainable: passing it straight back as ``target_arl``
    succeeds (see ``test_fits_successfully_when_target_arl_equals_the_``
    ``minimum_attainable_exactly`` in ``test_cusum_fitting.py``).

    For ``"two_sided"``, the symmetric two-arm combination
    (``_combine_two_sided_arl0``, Montgomery Eq. 9.7) of two identical
    one-sided values gives the two-sided figure.

    No non-negative decision interval can attain an ARL0 below this value:
    ``_cusum_arl0(k, h)`` is strictly increasing in ``h`` for ``h >= 0``
    (visible from the formula: ``d(ARL0)/dh > 0`` since the exponential
    term dominates), and ``_calibrate_decision_interval`` never searches
    below ``_MIN_DECISION_INTERVAL``, so this is the true floor of what it
    can return. ``fit_cusum`` uses this to reject an unattainable
    ``target_arl`` before ever invoking ``_calibrate_decision_interval`` --
    see that function's external-review defect history (Linear BIN-117):
    without this check, root-finding silently bottomed out at
    ``_MIN_DECISION_INTERVAL`` and reported the (far higher) achieved ARL0
    as if it were a successful fit.
    """
    one_sided = _cusum_arl0(reference_value, _MIN_DECISION_INTERVAL)
    if direction == "two_sided":
        return _combine_two_sided_arl0(one_sided, one_sided)
    return one_sided


def _require_attainable_target_arl(
    target_arl: float, reference_value: float, direction: str
) -> None:
    """Enforce that ``target_arl`` is attainable at ``reference_value``/``direction``.

    Raises ``InvalidParameterError`` (BIN-117) if no decision interval can
    reach it.

    Distinct from ``_require_target_arl``'s ordinary out-of-range check:
    this constraint depends on *two* other parameters, not one, so it
    cannot be expressed as a fixed bound on ``target_arl`` alone --
    ``MIN_TARGET_ARL`` (ADR-011) is a library-wide *policy* floor (the
    smallest ARL0 the field's own literature tabulates at all), not a
    per-``(reference_value, direction)`` guarantee that every ARL0 at or
    above it is reachable. This function's floor can sit far *above*
    ``MIN_TARGET_ARL`` (e.g. ~1158.3 at ``reference_value=5.0``,
    two-sided) -- the two checks are independent and both are needed.

    Uses the identical floor (``_min_attainable_arl0``, evaluated at
    ``h = _MIN_DECISION_INTERVAL``) that ``_calibrate_decision_interval``
    itself searches from, so a ``target_arl`` this function accepts is
    *provably* reachable by that function's own search bracket -- not
    merely reachable in an unattained mathematical limit. That equivalence
    is what makes a separate post-calibration bound-hit check unnecessary:
    an earlier version of this fix kept one as a safety net, believing the
    two could disagree; they cannot, because both now read the same
    ``_MIN_DECISION_INTERVAL`` floor through the same formula.
    """
    min_attainable = _min_attainable_arl0(reference_value, direction)
    if target_arl < min_attainable:
        raise InvalidParameterError(
            "target_arl is below the minimum ARL0 attainable for this "
            "reference_value and direction -- no decision interval can "
            "reach it",
            context={
                "parameter": "target_arl",
                "constraint": (
                    "must be >= the minimum ARL0 attainable at the given "
                    "reference_value and direction "
                    f"({min_attainable} here)"
                ),
                "kind": "invalid",
                "provided": target_arl,
                "reference_value": reference_value,
                "direction": direction,
                "min_attainable_arl": min_attainable,
            },
            recovery_hint=(
                f"No decision interval can reach target_arl={target_arl} at "
                f"reference_value={reference_value} and "
                f"direction={direction!r} -- the minimum attainable ARL0 "
                f"here is {min_attainable}, and that value is itself "
                "achievable. Choose a target_arl at or above it, or lower "
                "reference_value so smaller shifts become detectable at a "
                "reachable false alarm rate."
            ),
        )


def _calibrate_decision_interval(
    reference_value: float, target_arl: float, direction: str
) -> tuple[float, float]:
    """Solve for the decision interval *h* achieving ``target_arl``.

    Root-finds ``h`` such that the ARL0 implied by ``(reference_value, h)``
    -- combined across both arms if ``direction == "two_sided"``, per
    ``_combine_two_sided_arl0`` -- equals ``target_arl``. Mirrors
    ``ewma_fitting._calibrate_limit_multiplier``'s root-finding shape
    (``scipy.optimize.brentq``), but Siegmund's approximation is closed-form
    where the Markov-chain method is not (ADR-001).

    ``target_arl`` under ``direction == "two_sided"`` is the COMBINED
    two-sided ARL0 (see module docstring's flagged reading) -- the
    root-find therefore targets the per-arm ARL0 that combines to it
    (``target_arl * 2`` for a symmetric two-sided design, per Montgomery
    Eq. 9.7), and ``achieved_arl`` is reported back combined, not per-arm.

    Returns
    -------
    tuple[float, float]
        A ``(decision_interval, achieved_arl)`` pair.
    """
    per_arm_target = target_arl * 2.0 if direction == "two_sided" else target_arl

    def arl_gap(decision_interval: float) -> float:
        return _cusum_arl0(reference_value, decision_interval) - per_arm_target

    def achieved_from_one_sided(one_sided_arl: float) -> float:
        if direction == "two_sided":
            return _combine_two_sided_arl0(one_sided_arl, one_sided_arl)
        return one_sided_arl

    lower_bound = _MIN_DECISION_INTERVAL
    if arl_gap(lower_bound) >= 0:
        # target_arl is at or below the smallest per-arm ARL0 this formula
        # can represent near h=0 -- the smallest sensible h already meets
        # or exceeds the target.
        one_sided_achieved = _cusum_arl0(reference_value, lower_bound)
        return lower_bound, achieved_from_one_sided(one_sided_achieved)

    upper_bound = 1.0
    while arl_gap(upper_bound) < 0:
        upper_bound *= 2.0
        if upper_bound > _MAX_DECISION_INTERVAL:
            one_sided_achieved = _cusum_arl0(reference_value, upper_bound)
            return upper_bound, achieved_from_one_sided(one_sided_achieved)

    # scipy.optimize.brentq has no type stub mypy can see (same scipy
    # stub-coverage gap ewma_fitting.py's `brentq` call works around);
    # it returns a float here since `full_output` is left at its default
    # of False.
    decision_interval: float = brentq(  # type: ignore[no-untyped-call]
        arl_gap, lower_bound, upper_bound, xtol=1e-9, rtol=1e-12, maxiter=200
    )
    one_sided_achieved = _cusum_arl0(reference_value, decision_interval)
    return decision_interval, achieved_from_one_sided(one_sided_achieved)


# --- Baseline statistics ------------------------------------------------------


# --- Public API ----------------------------------------------------------------


def fit_cusum(
    baseline: Baseline,
    *,
    target_arl: float | None = None,
    reference_value: float | None = None,
    direction: str | None = None,
) -> FittedCUSUM:
    """Fit CUSUM control limits from ``baseline`` (BIN-94).

    Validates parameters first (fail fast), then enforces baseline
    sufficiency by calling ``baseline.check_sufficiency()`` internally
    (OQ-3, resolved the same way ``fit_ewma`` resolved it on BIN-65: fitting
    owns enforcement rather than duplicating BIN-64's threshold logic in a
    second guard), then refuses a zero-variance baseline, then calibrates
    the decision interval via Siegmund's (1985) approximation (see module
    docstring) and reports both the requested and achieved false alarm
    tolerance, the reference value used, and the monitored direction on the
    returned artefact.

    Parameters
    ----------
    baseline
        The Phase I baseline to fit from.
    target_arl
        The target in-control ARL0 (false alarm tolerance), as experienced
        by the deployed monitor -- the two-sided combined figure when
        ``direction == "two_sided"`` (see module docstring's flagged
        reading). Optional in the signature, required by validation --
        omitting it raises ``InvalidParameterError`` with
        ``context["kind"] == "missing"``.
    reference_value
        The CUSUM reference value (*k*), in sigma units. ``None`` uses
        ``DEFAULT_REFERENCE_VALUE``.
    direction
        ``"two_sided"``, ``"lower"``, or ``"upper"``. ``None`` uses
        ``DEFAULT_DIRECTION`` (``"two_sided"``).

    Returns
    -------
    FittedCUSUM
        The fitted artefact. Carries a non-empty ``advisories`` when
        ``target_arl`` is inside ADR-011's flagged tier (``[100, 370)``).

    Raises
    ------
    InvalidParameterError
        ``target_arl`` is missing or outside ``[MIN_TARGET_ARL,
        MAX_MEANINGFUL_ARL]`` (ADR-011); ``reference_value`` is supplied but
        outside ``[MIN_REFERENCE_VALUE, MAX_REFERENCE_VALUE]``; ``direction``
        is supplied but not in ``_VALID_DIRECTIONS``; or ``target_arl`` is
        below the minimum ARL0 attainable at the given
        ``reference_value``/``direction`` -- no non-negative decision
        interval can reach it (BIN-117).
    InsufficientBaselineError
        ``baseline`` does not meet the sufficiency threshold (BIN-94
        A1/BR-1).
    DegenerateBaselineError
        Every observation in ``baseline`` has an identical score (BIN-94
        A2/BR-2).

    References
    ----------
    .. [1] Montgomery, D. C. (2013). *Introduction to Statistical Quality
           Control* (7th ed.). Wiley, p. 423, eqs. 9.6-9.7 -- states
           Siegmund's (1985) approximation, ``b = h + 1.166``, and the
           two-sided combination formula.
    """
    # BIN-126: reject a wrong-typed baseline before any attribute on it is
    # accessed -- previously left to leak AttributeError the moment
    # `baseline.check_sufficiency()` below was reached.
    baseline = require_type(
        baseline, Baseline, parameter="baseline", type_name="Baseline"
    )
    validated_target_arl, target_arl_advisory = _require_target_arl(target_arl)
    validated_reference_value = _validate_reference_value(reference_value)
    effective_reference_value = (
        validated_reference_value
        if validated_reference_value is not None
        else DEFAULT_REFERENCE_VALUE
    )
    effective_direction = _validate_direction(direction)
    _require_attainable_target_arl(
        validated_target_arl, effective_reference_value, effective_direction
    )

    sufficiency = baseline.check_sufficiency()
    if not sufficiency.is_sufficient:
        raise InsufficientBaselineError(
            "baseline does not have enough observations to fit CUSUM control "
            "limits reliably",
            context={
                "have": sufficiency.observation_count,
                "need": sufficiency.threshold,
            },
            recovery_hint=(
                "Collect more observations before fitting -- record "
                f"at least {sufficiency.gap} more scoring results with "
                "Baseline.record() to reach the sufficiency threshold."
            ),
        )

    scores = [observation.score for observation in baseline.observations]
    if _has_zero_variance(scores):
        raise DegenerateBaselineError(
            "baseline has zero score variance -- CUSUM control limits cannot "
            "be fitted from it",
            context={"reason": _ZERO_VARIANCE_REASON},
            recovery_hint=(
                "Every recorded observation has an identical score, so the "
                "CUSUM statistic would never accumulate any deviation to "
                "detect. Collect observations that reflect the agent's "
                "genuine output variation before fitting."
            ),
        )

    # statistics.fmean(scores) would raise OverflowError here on a baseline
    # whose running sum overflows float64 even though the mean itself is
    # representable (BIN-123) -- see _overflow_safe_mean's docstring.
    baseline_mean = _overflow_safe_mean(scores)
    baseline_spread = statistics.stdev(scores)
    sigma_estimate = _moving_range_sigma(scores)

    decision_interval, achieved_arl = _calibrate_decision_interval(
        effective_reference_value, validated_target_arl, effective_direction
    )
    # No post-calibration bound-hit guard here (deliberately, BIN-117
    # review): _require_attainable_target_arl above and
    # _calibrate_decision_interval's own search bracket both read
    # _MIN_DECISION_INTERVAL through the identical _min_attainable_arl0/
    # _cusum_arl0 formula, so a target_arl that survives the pre-check is
    # provably reachable by this call, not merely reachable in the
    # unattained h=0 limit a defensive post-check could no longer
    # distinguish from a genuine, minimal-h fit. A prior version of this
    # fix kept such a guard; see _min_attainable_arl0's docstring for why
    # it was both unreachable and wrong.

    provenance = baseline.provenance_signature
    if provenance is None:  # pragma: no cover
        # Unreachable: sufficiency requires observation_count >= threshold
        # > 0, and Baseline sets provenance_signature on its first recorded
        # observation -- an internal invariant, not a CaliperError path.
        raise RuntimeError(
            "fit_cusum invariant violation: a sufficient baseline has no "
            "provenance signature"
        )

    return FittedCUSUM(
        chart_type=_CHART_TYPE,
        baseline_mean=baseline_mean,
        baseline_spread=baseline_spread,
        sigma_estimate=sigma_estimate,
        sigma_estimation_method=_MOVING_RANGE_METHOD,
        observation_count=len(scores),
        provenance_model_version=provenance.model_version.value,
        provenance_criteria=provenance.scoring_criteria.value,
        requested_arl=validated_target_arl,
        achieved_arl=achieved_arl,
        calibration_method=_CALIBRATION_METHOD,
        reference_value=effective_reference_value,
        decision_interval=decision_interval,
        target_value=baseline_mean,
        direction=effective_direction,
        advisories=(target_arl_advisory,) if target_arl_advisory is not None else (),
    )


__all__ = [
    "DEFAULT_DIRECTION",
    "DEFAULT_REFERENCE_VALUE",
    "MAX_MEANINGFUL_ARL",
    "MAX_REFERENCE_VALUE",
    "MIN_REFERENCE_VALUE",
    "MIN_TARGET_ARL",
    "fit_cusum",
]
