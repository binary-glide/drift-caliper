"""``fit_ewma`` -- fit EWMA control limits from a Phase I baseline (BIN-65).

See ``docs/domain-model.md`` (Library Operations -- Fit EWMA) and
``docs/architecture/adr/004-fitted-artefact-protocol-and-fitting-api-surface.md``
section 5 for the fitting signature shape and parameter semantics, and
ADR-001/ADR-003 for the calibration method (Markov-chain approximation,
Lucas & Saccucci 1990).

## Calibration method

A two-sided EWMA with fixed limits, standardised so the in-control process
mean is 0 and the in-control process standard deviation is 1 -- the
in-control (zero-state) ARL0 of such a chart depends only on the smoothing
parameter ``lambda`` and the control-limit multiplier ``L``, never on the
process's actual mean or sigma (see
``tests/unit/baseline/test_ewma_arl_published_values.py``, "Why sigma does
not need to be controlled"). The EWMA statistic

    Z_i = lambda * X_i + (1 - lambda) * Z_(i-1),  Z_0 = 0

has asymptotic (steady-state) standard deviation ``sqrt(lambda / (2 -
lambda))`` (Roberts 1959; Lucas & Saccucci 1990 eq. 3), so fixed limits at
multiplier ``L`` sit at ``+/- L * sqrt(lambda / (2 - lambda))`` in
standardised units.

``_in_control_arl`` computes the zero-state ARL0 for a given ``(lambda,
L)`` pair via the Brook & Evans (1972) Markov-chain approximation, the
method Lucas & Saccucci (1990) themselves use: the interval between the
limits is discretised into ``_MARKOV_CHAIN_STATES`` cells (an odd count, so
one cell sits exactly on the centre line -- required for a *zero-state*
ARL, which starts the chain there); transition probabilities between cells
follow from the Normal CDF of the EWMA recursion; the expected number of
steps to absorption (leaving the interval) from the centre state is
``(I - Q)^-1 @ ones`` evaluated at that state, where ``Q`` is the
transient-state transition matrix (a standard first-step-analysis result
for absorbing Markov chains).

``fit_ewma`` inverts this: given ``lambda`` and a ``target_arl``, it
root-finds (``scipy.optimize.brentq``) the ``L`` whose ``_in_control_arl``
equals ``target_arl``, then reports both the requested value and the
achieved value the calibration actually produced (ADR-004 section 5, A4).

## Verification performed before trusting this implementation

Per ``CLAUDE.md`` ("Fitting stories carry their own numerical proof") and
the BIN-65 brief's explicit instruction, this calibration was validated
against a closed form *before* being trusted, independently of
``tests/unit/baseline/test_ewma_arl_published_values.py``:

As ``lambda -> 1`` an EWMA degenerates to a Shewhart individuals chart
(only the latest observation carries any weight), whose two-sided
in-control ARL0 has the closed form ``1 / (2 * Phi(-L))``. At
``lambda = 0.999``, ``_in_control_arl`` reproduces this closed form to
five decimal places for ``L`` in ``{2.0, 3.0, 4.0}`` (absolute differences
of order 1e-5 to 1e-4 against closed-form values ranging from ~22 to
~15787) -- the same self-test this module's author used to catch a
first-draft factor-of-2 discretisation bug (the interval spanned twice its
true width) before it was ever committed.

Separately, ``(lambda=0.5, L=3.071)`` and ``(lambda=0.03, L=2.437)`` --
Lucas & Saccucci (1990) Table 3's own published pairs, both calibrated by
the paper's authors to hit ARL0=500 -- reproduce ARL0 of approximately
499.9 and 499.6 respectively under this implementation, within the 2%
tolerance ``test_ewma_arl_published_values.py`` enforces and consistent
with that file's own independently-recomputed reference figures (499.9,
499.8) documented in its module docstring.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq

# scipy.stats exposes `norm` via a lazy attribute loader with no type stub
# mypy can see, even with `follow_untyped_imports` (pyproject.toml) -- the
# same scipy stub-coverage gap the mypy config's own comment names. Real,
# non-optional at runtime; only the static type is unresolvable.
from scipy.stats import norm  # type: ignore[attr-defined]

from caliper.baseline.domain.baseline import Baseline
from caliper.baseline.domain.fitted_ewma import FittedEWMA
from caliper.errors import (
    DegenerateBaselineError,
    InsufficientBaselineError,
    InvalidParameterError,
)

# --- Smoothing parameter (lambda) valid range -------------------------------
#
# The EWMA statistic itself is defined for 0 < lambda <= 1 (Roberts 1959;
# Hunter 1986; Lucas & Saccucci 1990 sec. 2) -- lambda=1 degenerates to a
# Shewhart individuals chart (only the most recent observation matters),
# lambda=0 is undefined (no weight ever falls on a new observation).
# Confirmed against the NIST/SEMATECH e-Handbook of Statistical Methods,
# section 6.3.2.4 ("EWMA Control Charts"): "the valid range for lambda is
# 0 < lambda <= 1". MAX_SMOOTHING_PARAM = 1.0 follows directly from that
# closed upper bound.
MAX_SMOOTHING_PARAM = 1.0

# MIN_SMOOTHING_PARAM has no smallest element to inherit from the chart's own
# mathematical definition -- (0, 1] is open at zero -- so a library
# implementation must choose a concrete floor. This is an engineering
# default, not a published constant, chosen for two reasons:
#
# 1. It must not exclude lambda=0.03, the smaller of the two (lambda, L)
#    pairs this story's own numerical proof verifies against Lucas &
#    Saccucci (1990) Table 3 (see test_ewma_arl_published_values.py) --
#    Table 3 itself tabulates lambda values at least that small, so 0.03 is
#    inside the range the primary source treats as meaningful.
# 2. An EWMA's weight on an observation k steps in the past decays as
#    (1 - lambda)^k, so its half-life is ln(2) / -ln(1 - lambda)
#    observations -- a direct algebraic consequence of the recursion, not a
#    citation-requiring constant. At lambda = 0.01 that half-life is
#    approximately 69 observations, already comparable to
#    DEFAULT_SUFFICIENCY_THRESHOLD (100, ADR-005) -- the library's own floor
#    for a usable Phase I baseline. A smaller lambda would need a baseline
#    larger than the library's own recommended minimum just for the chart's
#    memory to be shorter than the data it was calibrated from, which is not
#    a useful default to allow silently.
MIN_SMOOTHING_PARAM = 0.01

# --- Library default smoothing parameter ------------------------------------
#
# ADR-004 section 5: "smoothing_param (EWMA) ... Optional. None uses library
# default" -- deliberately left unpinned by the ADR (ADR-001's "no numerical
# constants" discipline). The NIST/SEMATECH e-Handbook of Statistical
# Methods, section 6.3.2.4, states: "The value of lambda is usually set
# between 0.2 and 0.3 (Hunter, 1986) although this choice is somewhat
# arbitrary." 0.2 is the low end of that commonly-cited range -- consistent
# with Lucas & Saccucci's (1990) own discussion that small lambda affords
# better sensitivity to small, sustained shifts (the failure mode Caliper
# exists to catch: gradual agent quality drift, not a single anomalous
# response), at some cost to large-shift responsiveness.
DEFAULT_SMOOTHING_PARAM = 0.2

# --- False alarm tolerance (target ARL0) meaningful range -------------------
#
# MIN_MEANINGFUL_ARL = 1.0 is not an engineering choice -- it is a
# mathematical floor. ARL0 is defined as the expectation of a stopping time
# (the count of in-control observations until the first false alarm), and
# that count is a positive integer -- it is always at least 1, because the
# very first observation is itself a trial that can trigger an alarm.
# E[N] >= 1 for any N supported on {1, 2, 3, ...} follows directly from the
# definition of expectation; no value below 1 is a coherent ARL0 to request.
MIN_MEANINGFUL_ARL = 1.0

# MAX_MEANINGFUL_ARL has no comparable mathematical ceiling -- ARL0 grows
# without bound as L -> infinity. 1,000,000 is an engineering default, not a
# published constant: at any realistic scoring cadence this already
# represents a false alarm tolerance of years to millennia (e.g. roughly
# 2,700 years of daily scoring), well past the point where a larger number
# is practically distinguishable, and it keeps the calibration's root-finder
# search bracket (see _calibrate_limit_multiplier) bounded rather than
# needing to expand indefinitely.
MAX_MEANINGFUL_ARL = 1_000_000.0

# --- Moving-range sigma estimation -------------------------------------------
#
# The unbiasing constant d_2 for a moving-range span of 2 (consecutive
# individual observations, R1 -- docs/domain-model.md "Moving-range span").
# d_2 = 1.128 is one of the most widely reproduced constants in SPC practice
# (Montgomery's Introduction to Statistical Quality Control, Appendix VI --
# not directly accessible in this environment, an O'Reilly paywall, the same
# access gap docs/domain-model.md already records for this exact constant).
# Cross-verified against three independent secondary sources reproducing the
# standard control-chart-constants table for n=2: r-bar.net
# ("Control Chart Constants | Tables and Brief Explanation"), the MIT-hosted
# reproduction of the AIAG SPC reference manual's constants table
# (web.mit.edu/2.810/www/files/readings/ControlChartConstantsAndFormulae.pdf),
# and andrewmilivojevich.com's "D2 values for the Distribution of the
# Average Range" -- all three agree on d_2 = 1.128 for n = 2.
_MOVING_RANGE_D2 = 1.128
_MOVING_RANGE_METHOD = "moving_range"

# --- Markov-chain calibration parameters -------------------------------------
#
# Number of discretisation cells for the Brook & Evans (1972) Markov-chain
# approximation (see module docstring). Not a published constant -- an
# engineering choice balancing accuracy against calibration speed, empirically
# validated (not merely assumed) against both a closed form and the published
# Lucas & Saccucci (1990) Table 3 entries before being trusted; see the module
# docstring's "Verification performed" section. Must be odd so a cell sits
# exactly on the centre line, which the zero-state ARL calculation requires.
_MARKOV_CHAIN_STATES = 301

# Search bracket for the control-limit multiplier L during root-finding.
# L = 0 exactly would collapse the limits onto the centre line (dividing by
# zero is not the failure mode -- an exactly-zero interval is), so the
# bracket's lower edge is a small positive floor rather than 0. The upper
# edge is expanded geometrically (see _calibrate_limit_multiplier) up to
# this ceiling, which comfortably exceeds any L a target_arl within
# [MIN_MEANINGFUL_ARL, MAX_MEANINGFUL_ARL] requires in practice.
_MIN_LIMIT_MULTIPLIER = 1e-6
_MAX_LIMIT_MULTIPLIER = 1e5

_CHART_TYPE = "ewma"
_CALIBRATION_METHOD = "markov_chain"

_ZERO_VARIANCE_REASON = "zero_variance"


# --- Parameter validation ----------------------------------------------------


def _require_target_arl(target_arl: float | None) -> float:
    """Validate ``target_arl`` and return it narrowed to ``float``.

    ``target_arl`` is optional in the Python signature but required by
    Caliper's validation (ADR-004 section 5, closing ADR-002's open
    dependency): omitting it is a classifiable ``CaliperError``, never
    Python's ``TypeError``. Returning the validated value (rather than
    ``None``) lets callers avoid a redundant ``is None`` narrowing check
    after this function has already ruled that case out.
    """
    constraint = (
        f"must be a finite float in [{MIN_MEANINGFUL_ARL}, {MAX_MEANINGFUL_ARL}]"
    )
    if target_arl is None:
        raise InvalidParameterError(
            "target_arl is required to fit EWMA control limits",
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
    if not math.isfinite(target_arl) or not (
        MIN_MEANINGFUL_ARL <= target_arl <= MAX_MEANINGFUL_ARL
    ):
        raise InvalidParameterError(
            "target_arl is outside the meaningful range",
            context={
                "parameter": "target_arl",
                "constraint": constraint,
                "kind": "invalid",
                "provided": target_arl,
            },
            recovery_hint=(
                "Choose a target_arl within "
                f"[{MIN_MEANINGFUL_ARL}, {MAX_MEANINGFUL_ARL}], e.g. 370 or "
                "500 -- common in-control ARL0 targets in the SPC literature."
            ),
        )
    return target_arl


def _validate_smoothing_param(smoothing_param: float | None) -> None:
    """Raise ``InvalidParameterError`` if a supplied ``smoothing_param`` is invalid.

    ``smoothing_param`` is genuinely optional -- ``None`` is not validated
    here at all; ``fit_ewma`` substitutes ``DEFAULT_SMOOTHING_PARAM``.
    """
    if smoothing_param is None:
        return
    constraint = (
        f"must be a finite float in [{MIN_SMOOTHING_PARAM}, {MAX_SMOOTHING_PARAM}]"
    )
    if not math.isfinite(smoothing_param) or not (
        MIN_SMOOTHING_PARAM <= smoothing_param <= MAX_SMOOTHING_PARAM
    ):
        raise InvalidParameterError(
            "smoothing_param is outside the valid range",
            context={
                "parameter": "smoothing_param",
                "constraint": constraint,
                "kind": "invalid",
                "provided": smoothing_param,
            },
            recovery_hint=(
                "Choose a smoothing_param within "
                f"[{MIN_SMOOTHING_PARAM}, {MAX_SMOOTHING_PARAM}], or omit it "
                f"entirely to use the library default ({DEFAULT_SMOOTHING_PARAM})."
            ),
        )


# --- Baseline statistics ------------------------------------------------------


def _has_zero_variance(scores: Sequence[float]) -> bool:
    """Report whether every score in ``scores`` is identical."""
    return len(set(scores)) <= 1


def _moving_range_sigma(scores: Sequence[float]) -> float:
    """Estimate short-term sigma from the mean moving range (span 2).

    ``scores`` must have at least one pair of unequal consecutive-difference
    contributions -- guaranteed by the time this is called, because
    ``fit_ewma`` has already rejected an all-identical baseline (a baseline
    containing any two distinct values has at least one non-zero
    consecutive difference, so the mean moving range is strictly positive).
    """
    moving_ranges = [abs(b - a) for a, b in itertools.pairwise(scores)]
    mean_moving_range = statistics.fmean(moving_ranges)
    return mean_moving_range / _MOVING_RANGE_D2


# --- Markov-chain ARL0 calibration --------------------------------------------


def _ewma_asymptotic_std_ratio(smoothing_param: float) -> float:
    """The ratio of the EWMA statistic's asymptotic std dev to the process std dev.

    ``sqrt(lambda / (2 - lambda))`` -- Roberts (1959); Lucas & Saccucci
    (1990) eq. 3.
    """
    return math.sqrt(smoothing_param / (2.0 - smoothing_param))


def _in_control_arl(
    smoothing_param: float, limit_multiplier: float, num_states: int
) -> float:
    """Zero-state in-control ARL0 for a two-sided EWMA with fixed limits.

    Brook & Evans (1972) Markov-chain approximation, the method Lucas &
    Saccucci (1990) use for their own tables. Works entirely in
    process-sigma-standardised units (process mean 0, process std dev 1) --
    see the module docstring's "why sigma does not need to be controlled".

    Args:
        smoothing_param: The EWMA smoothing parameter (lambda).
        limit_multiplier: The control-limit multiplier (L). The fixed
            limits sit at ``+/- limit_multiplier *
            _ewma_asymptotic_std_ratio(smoothing_param)``.
        num_states: Number of discretisation cells. Must be odd, so a cell
            sits exactly on the centre line (the zero-state starting point).

    Returns:
        The expected number of in-control observations until the EWMA
        statistic first leaves the control limits, starting from the
        centre line.
    """
    half_width = limit_multiplier * _ewma_asymptotic_std_ratio(smoothing_param)
    half_state_count = num_states // 2
    cell_width = 2.0 * half_width / num_states

    state_indices = np.arange(-half_state_count, half_state_count + 1, dtype=np.float64)
    midpoints: NDArray[np.float64] = state_indices * cell_width
    lower_bounds = midpoints - cell_width / 2.0
    upper_bounds = midpoints + cell_width / 2.0

    # Z_new = lambda * X + (1 - lambda) * Z_old, X ~ N(0, 1) in-control.
    # Given Z_old = midpoints[i] (a row), Z_new falls in cell j (a column)
    # when X falls in [(lower_j - (1-lambda) z_i)/lambda, (upper_j - (1-lambda)
    # z_i)/lambda] -- broadcast across every (from-state, to-state) pair at
    # once rather than looping.
    one_minus_lambda = 1.0 - smoothing_param
    from_state = midpoints.reshape(-1, 1)
    to_lower = lower_bounds.reshape(1, -1)
    to_upper = upper_bounds.reshape(1, -1)
    standardised_lower = (to_lower - one_minus_lambda * from_state) / smoothing_param
    standardised_upper = (to_upper - one_minus_lambda * from_state) / smoothing_param
    transition_matrix = norm.cdf(standardised_upper) - norm.cdf(standardised_lower)

    # First-step analysis for absorbing Markov chains: the expected number
    # of steps to absorption from every transient state solves
    # (I - Q) @ arl = 1. The centre state (index half_state_count) is the
    # zero-state starting point.
    identity = np.eye(num_states)
    steps_to_absorption = np.linalg.solve(
        identity - transition_matrix, np.ones(num_states)
    )
    return float(steps_to_absorption[half_state_count])


def _calibrate_limit_multiplier(
    smoothing_param: float, target_arl: float
) -> tuple[float, float]:
    """Solve for the control-limit multiplier L achieving ``target_arl``.

    Root-finds via ``scipy.optimize.brentq`` on ``L -> _in_control_arl(L) -
    target_arl``. In-control ARL0 is monotonically increasing in L (wider
    limits mean fewer false alarms), so the root, when bracketed, is unique.

    Returns:
        A ``(limit_multiplier, achieved_arl)`` pair -- the solved L and the
        ARL0 this implementation's own calibration computes for it (which
        may differ very slightly from ``target_arl`` due to numerical
        approximation, per ADR-004 section 5 / feature file assumption A4).
    """

    def arl_gap(limit_multiplier: float) -> float:
        return (
            _in_control_arl(smoothing_param, limit_multiplier, _MARKOV_CHAIN_STATES)
            - target_arl
        )

    lower_bound = _MIN_LIMIT_MULTIPLIER
    if arl_gap(lower_bound) >= 0:
        # target_arl is at or below the smallest ARL0 this discretisation can
        # represent near L=0 (its mathematical infimum is 1 -- see
        # MIN_MEANINGFUL_ARL -- but a finite grid cannot reach exactly 1).
        # The smallest sensible L already meets or exceeds the target.
        achieved = _in_control_arl(smoothing_param, lower_bound, _MARKOV_CHAIN_STATES)
        return lower_bound, achieved

    upper_bound = 1.0
    while arl_gap(upper_bound) < 0:
        upper_bound *= 2.0
        if upper_bound > _MAX_LIMIT_MULTIPLIER:
            achieved = _in_control_arl(
                smoothing_param, upper_bound, _MARKOV_CHAIN_STATES
            )
            return upper_bound, achieved

    # scipy.optimize.brentq has no type stub mypy can see (same scipy
    # stub-coverage gap as the `norm` import above); it returns a float here
    # since `full_output` is left at its default of False.
    limit_multiplier: float = brentq(  # type: ignore[no-untyped-call]
        arl_gap, lower_bound, upper_bound, xtol=1e-9, rtol=1e-12, maxiter=200
    )
    achieved = _in_control_arl(smoothing_param, limit_multiplier, _MARKOV_CHAIN_STATES)
    return limit_multiplier, achieved


# --- Public API ----------------------------------------------------------------


def fit_ewma(
    baseline: Baseline,
    *,
    target_arl: float | None = None,
    smoothing_param: float | None = None,
) -> FittedEWMA:
    """Fit EWMA control limits from ``baseline`` (BIN-65).

    Validates parameters first (fail fast), then enforces baseline
    sufficiency by calling ``baseline.check_sufficiency()`` internally
    (OQ-3: this fitting operation owns enforcement rather than duplicating
    BIN-64's threshold logic in a second guard -- both designs the feature
    file names are consistent with its scenarios, since none of them assert
    on the mechanism), then refuses a zero-variance baseline, then
    calibrates the control-limit multiplier via a Brook & Evans (1972)
    Markov-chain approximation (see module docstring) and reports both the
    requested and achieved false alarm tolerance on the returned artefact.

    Args:
        baseline: The Phase I baseline to fit from.
        target_arl: The target in-control ARL0 (false alarm tolerance).
            Optional in the signature, required by validation -- omitting
            it raises ``InvalidParameterError`` with
            ``context["kind"] == "missing"``.
        smoothing_param: The EWMA smoothing parameter (lambda). ``None``
            uses ``DEFAULT_SMOOTHING_PARAM``.

    Returns:
        A ``FittedEWMA`` artefact.

    Raises:
        InvalidParameterError: ``target_arl`` is missing or outside
            ``[MIN_MEANINGFUL_ARL, MAX_MEANINGFUL_ARL]``, or
            ``smoothing_param`` is supplied but outside
            ``[MIN_SMOOTHING_PARAM, MAX_SMOOTHING_PARAM]``.
        InsufficientBaselineError: ``baseline`` does not meet the
            sufficiency threshold (BIN-65 A1/BR-1).
        DegenerateBaselineError: every observation in ``baseline`` has an
            identical score (BIN-65 A2/BR-2).
    """
    validated_target_arl = _require_target_arl(target_arl)
    _validate_smoothing_param(smoothing_param)
    effective_smoothing_param = (
        smoothing_param if smoothing_param is not None else DEFAULT_SMOOTHING_PARAM
    )

    sufficiency = baseline.check_sufficiency()
    if not sufficiency.is_sufficient:
        raise InsufficientBaselineError(
            "baseline does not have enough observations to fit EWMA control "
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
            "baseline has zero score variance -- EWMA control limits cannot "
            "be fitted from it",
            context={"reason": _ZERO_VARIANCE_REASON},
            recovery_hint=(
                "Every recorded observation has an identical score, so "
                "fitted control limits would collapse to the centre line "
                "and be unable to detect any deviation. Collect "
                "observations that reflect the agent's genuine output "
                "variation before fitting."
            ),
        )

    baseline_mean = statistics.fmean(scores)
    baseline_spread = statistics.stdev(scores)
    sigma_estimate = _moving_range_sigma(scores)

    limit_multiplier, achieved_arl = _calibrate_limit_multiplier(
        effective_smoothing_param, validated_target_arl
    )
    half_width = (
        limit_multiplier
        * sigma_estimate
        * _ewma_asymptotic_std_ratio(effective_smoothing_param)
    )

    provenance = baseline.provenance_signature
    if provenance is None:  # pragma: no cover
        # Unreachable: sufficiency requires observation_count >= threshold
        # > 0, and Baseline sets provenance_signature on its first recorded
        # observation -- an internal invariant, not a CaliperError path.
        raise RuntimeError(
            "fit_ewma invariant violation: a sufficient baseline has no "
            "provenance signature"
        )

    return FittedEWMA(
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
        smoothing_param=effective_smoothing_param,
        ucl=baseline_mean + half_width,
        lcl=baseline_mean - half_width,
        cl=baseline_mean,
    )
