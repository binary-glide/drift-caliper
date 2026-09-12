"""EWMA Markov-chain ARL0 calibration internals, split from ``ewma_fitting`` (BIN-130).

``fit_ewma`` (``caliper.baseline.domain.ewma_fitting``) is a public entry
point; the Markov-chain calibration machinery below is not -- its only
caller is ``fit_ewma`` itself. Splitting them into separate modules mirrors
the ``spc_numerics`` hoist ``BIN-94`` already performed once (see that
module's docstring for the same reasoning restated there): ``beartype_package``
(``tests/conftest.py``) takes a module, so as long as a public entry point
shared a file with these internals, the dev-only beartype hook (BIN-109) had
to guard either both or neither. It guarded both -- which meant
``BeartypeCallHintParamViolation``, not a ``CaliperError``, could pre-empt any
guard ``fit_ewma`` raised, a defect ``BIN-126`` hit directly (see
``tests/conftest.py``'s beartype section for the full history). This module
has no public entry point at all, so -- like ``spc_numerics`` -- it is the
clean case: nothing needs weighing when deciding whether to hook it, because
there is no public boundary here to guard by accident.

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

``fit_ewma`` (``ewma_fitting.py``) inverts this via ``_calibrate_limit_multiplier``:
given ``lambda`` and a ``target_arl``, it root-finds (``scipy.optimize.brentq``)
the ``L`` whose ``_in_control_arl`` equals ``target_arl``, then reports both the
requested value and the achieved value the calibration actually produced
(ADR-004 section 5, A4).

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

References
----------
.. [1] Lucas, J. M. and Saccucci, M. S. (1990). "Exponentially Weighted
       Moving Average Control Schemes: Properties and Enhancements."
       Technometrics, 32(1), 1-12.

The Brook & Evans (1972) Markov-chain approximation this module also relies
on (see "Calibration method" above) has no full bibliographic entry
verified anywhere in this repository -- only author/year mentions -- so it
is deliberately not listed above.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

# scipy.stats exposes `norm` via a lazy attribute loader with no type stub
# mypy can see, even with `follow_untyped_imports` (pyproject.toml) -- the
# same scipy stub-coverage gap the mypy config's own comment names. Real,
# non-optional at runtime; only the static type is unresolvable.
from scipy.stats import norm  # type: ignore[attr-defined]

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
# [MIN_TARGET_ARL, MAX_MEANINGFUL_ARL] (parameter_guards.py/ewma_fitting.py,
# ADR-011) requires in practice.
_MIN_LIMIT_MULTIPLIER = 1e-6
_MAX_LIMIT_MULTIPLIER = 1e5


def _ewma_asymptotic_std_ratio(smoothing_param: float) -> float:
    """Compute the EWMA statistic's asymptotic std dev as a ratio to process std dev.

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

    Parameters
    ----------
    smoothing_param
        The EWMA smoothing parameter (lambda).
    limit_multiplier
        The control-limit multiplier (L). The fixed limits sit at
        ``+/- limit_multiplier * _ewma_asymptotic_std_ratio(smoothing_param)``.
    num_states
        Number of discretisation cells. Must be odd, so a cell sits
        exactly on the centre line (the zero-state starting point).

    Returns
    -------
    float
        The expected number of in-control observations until the EWMA
        statistic first leaves the control limits, starting from the
        centre line.
    """
    half_width = limit_multiplier * _ewma_asymptotic_std_ratio(smoothing_param)
    half_state_count = num_states // 2
    cell_width = 2.0 * half_width / num_states

    state_indices = np.arange(-half_state_count, half_state_count + 1, dtype=np.float64)
    # Deliberately annotated `np.ndarray` rather than `NDArray[np.float64]`:
    # beartype 0.22.9 cannot parse a parameterised NDArray against numpy
    # 2.5's ScalarT typevar, and its claw hook instruments annotated
    # assignments too (BIN-109). mypy infers the dtype here regardless, so
    # nothing is lost. Revisit if beartype gains numpy 2.5 support.
    midpoints: np.ndarray = state_indices * cell_width
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
    # Z_t = lambda * X_t + (1 - lambda) * Z_{t-1}, so reaching cell j from
    # state S_i requires X_t = (bound - (1 - lambda) * S_i) / lambda.
    #
    # NOTE for anyone mutation-testing this: flipping either sign here is an
    # *equivalent* mutant in control, and deliberately so rather than by luck.
    # The grid is symmetric about zero and the midpoints are antisymmetric, so
    # the flip permutes each row into its mirror image; the in-control problem
    # is symmetric under that reversal and the centre state -- the one the ARL
    # is read from -- is its fixed point. Measured: identical to 4 dp across
    # lambda in {0.03, 0.05, 0.1, 0.5, 0.9}.
    #
    # ⚠️ That equivalence holds ONLY in control. An out-of-control ARL with a
    # mean shift breaks the symmetry and the flip becomes a real bug. If BIN-84
    # or a later story computes out-of-control ARLs, this stops being safe.
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

    Returns
    -------
    tuple[float, float]
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
        # MIN_COHERENT_ARL -- but a finite grid cannot reach exactly 1; in
        # any case ADR-011's MIN_TARGET_ARL floor of 100 keeps target_arl
        # from ever reaching this deep into the discretisation's own limit).
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
