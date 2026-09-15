"""Regression and postcondition tests for BIN-140: EWMA Markov-chain solve instability.

``fit_ewma`` returns a **negative** ``achieved_arl`` for certain legal
``(smoothing_param, target_arl)`` pairs because the Markov-chain linear
solve ``(I - Q) @ arl = 1`` goes ill-conditioned at small lambda with
large target, and **nothing checks the answer is coherent**.

## The defect

```python
fit_ewma(baseline, target_arl=104949.0, smoothing_param=0.013463695801674842)
#   achieved_arl = -9468591415659530.0     <-- a NEGATIVE average run length
```

ARL0 is the expectation of a stopping time supported on {1, 2, 3, ...};
``E[N] >= 1`` by definition (ADR-011). Minus nine quadrillion is not a run
length. Both parameters are documented-valid: ``target_arl=104949`` is
inside ``[100, 1_000_000]``; ``smoothing_param=0.0134`` is above the
minimum (``0.01``, correctly refused below it).

## Root cause

``_in_control_arl`` returns garbage for large ``L`` -- the
``np.linalg.solve(I - Q, 1)`` becomes ill-conditioned (cond ~ 9e15) and
returns values oscillating between +/-1e15. Nothing checks the result is
finite or >= 1. ``_calibrate_limit_multiplier``'s bracket-expansion loop
reads garbage-negative as "still below target" and keeps doubling, until
garbage happens to be positive; ``brentq`` then converges to a spurious
root in the garbage region.

## Why a deterministic pin, not just the Hypothesis property

BIN-124 records the asymmetry: ``.hypothesis/examples`` is gitignored, so
CI starts without the counterexample and would pass. The property
(``test_joint_parameter_validity.py``) found this, but a Hypothesis draw
that finds a bug once and cannot replay it is a bug report, not a guard.
These deterministic tests are the guard.

## Constants

``MIN_COHERENT_ARL = 1.0`` -- the mathematical floor. ``E[N] >= 1`` for
any stopping time ``N`` supported on {1, 2, 3, ...}, from the definition
of expectation. This is the derivation ADR-011 records; it is not
re-derived here, only cited.

## Tolerance for the "near the request" postcondition

2% relative, identical to ``test_ewma_arl_published_values.py``'s own
tolerance (Lucas & Saccucci 1990, Table 3 verification), itself justified
there as the Markov-chain-vs-Nystroem-quadrature discretisation budget.
Not re-derived here.

## CUSUM and Shewhart exposure analysis

**CUSUM uses Siegmund's (1985) closed-form approximation**, not a linear
solve -- ``_cusum_arl0`` computes ``(exp(2*k*b) - 1 - 2*k*b) / (2*k^2)``
(Montgomery 2013, p. 423, eq. 9.6). No matrix, no ``np.linalg.solve``, no
ill-conditioning. Confirmed by reading ``cusum_fitting.py`` lines 335-375.

**Shewhart uses a closed-form tail probability**, ``1 / (2 * Phi(-L))`` --
an exact bijection with no numerical solve at all. Confirmed by reading
``shewhart_fitting.py`` lines 160-178.

**Neither chart type is exposed to this defect class.** Both tests below
that pin this are confirmations-of-absence, not defect regressions.

## Runtime

The two deterministic counterexample tests each call ``fit_ewma`` once
(~55 ms on this codebase's Markov-chain configuration). The
postcondition-sweep parametrisation adds ~20 calls. Total: under 2 seconds.
"""

from __future__ import annotations

import math

import pytest

from drift_caliper.baseline import fit_cusum, fit_ewma, fit_shewhart
from drift_caliper.baseline.domain.ewma_fitting import (
    MAX_MEANINGFUL_ARL,
    MAX_SMOOTHING_PARAM,
    MIN_COHERENT_ARL,
    MIN_SMOOTHING_PARAM,
)
from drift_caliper.baseline.domain.ewma_numerics import (
    _ILL_CONDITIONED_ARL_SENTINEL,
    _MARKOV_CHAIN_STATES,
    _in_control_arl,
)
from drift_caliper.baseline.domain.parameter_guards import MIN_TARGET_ARL
from drift_caliper.errors import CaliperError
from tests.support.baseline_strategies import probe_baseline

# Reuse the same fixed probe baseline every fitting function uses in the
# joint-parameter-validity tests -- the in-control ARL0 depends only on
# calibration parameters, never on the baseline's actual scores, so a
# different baseline would not change any assertion here.
_PROBE_BASELINE = probe_baseline()

# The 2% relative tolerance from test_ewma_arl_published_values.py.
_RELATIVE_TOLERANCE = 0.02


# ---------------------------------------------------------------------------
# Part 1: Deterministic regression tests for the two known counterexamples
# ---------------------------------------------------------------------------


class TestKnownCounterexamples:
    """Deterministic pins for the exact (lambda, target_arl) pairs BIN-140 found.

    Each of these is a legal input -- both parameters are individually inside
    their documented ranges -- that currently produces a nonsense
    ``achieved_arl``. The fix must make them either succeed with a coherent
    ``achieved_arl`` or raise a ``CaliperError`` naming the combination.

    These exist *because* the Hypothesis property that found them is not
    deterministically replayable on CI (BIN-124: ``.hypothesis/examples``
    is gitignored). A named, deterministic test is the guard.
    """

    def test_regression_lambda_0_0134_target_104949_is_coherent(self) -> None:
        """The literal BIN-140 counterexample: negative achieved_arl.

        ``fit_ewma(baseline, target_arl=104949.0,
        smoothing_param=0.013463695801674842)`` returned
        ``achieved_arl = -9468591415659530.0`` on trunk 30aa8b2.

        Both parameters are documented-valid:
        - ``smoothing_param=0.0134...`` is inside ``[0.01, 1.0]``
        - ``target_arl=104949`` is inside ``[100, 1_000_000]``
        """
        smoothing_param = 0.013463695801674842
        target_arl = 104949.0

        try:
            result = fit_ewma(
                _PROBE_BASELINE,
                target_arl=target_arl,
                smoothing_param=smoothing_param,
            )
        except CaliperError:
            # A CaliperError naming the combination is an acceptable outcome:
            # the fix may choose to refuse rather than misdeliver. Either way,
            # the defect (returning a nonsense artefact) is closed.
            return

        # If it succeeds, the result must be coherent.
        assert math.isfinite(result.achieved_arl), (
            f"achieved_arl={result.achieved_arl!r} is not finite -- "
            "the Markov-chain solve returned garbage"
        )
        assert result.achieved_arl >= MIN_COHERENT_ARL, (
            f"achieved_arl={result.achieved_arl!r} is below MIN_COHERENT_ARL "
            f"({MIN_COHERENT_ARL}) -- E[N] >= 1 for any stopping time N "
            "supported on {1, 2, 3, ...} (ADR-011)"
        )
        tolerance = target_arl * _RELATIVE_TOLERANCE
        assert abs(result.achieved_arl - target_arl) <= tolerance, (
            f"achieved_arl={result.achieved_arl!r} is finite and positive but "
            f"not within {_RELATIVE_TOLERANCE:.0%} of the requested "
            f"target_arl={target_arl!r} -- a BIN-117-class silent misdelivery"
        )

    def test_regression_lambda_0_015_target_104949_is_coherent(self) -> None:
        """The second known-bad input from BIN-140's description.

        ``fit_ewma(baseline, target_arl=104949.0, smoothing_param=0.015)``
        returned ``achieved_arl = +6.22e15`` on trunk 30aa8b2. Positive
        but equally garbage -- six quadrillion observations is not a
        meaningful run length.
        """
        smoothing_param = 0.015
        target_arl = 104949.0

        try:
            result = fit_ewma(
                _PROBE_BASELINE,
                target_arl=target_arl,
                smoothing_param=smoothing_param,
            )
        except CaliperError:
            return

        assert math.isfinite(result.achieved_arl), (
            f"achieved_arl={result.achieved_arl!r} is not finite"
        )
        assert result.achieved_arl >= MIN_COHERENT_ARL, (
            f"achieved_arl={result.achieved_arl!r} is below MIN_COHERENT_ARL"
        )
        tolerance = target_arl * _RELATIVE_TOLERANCE
        assert abs(result.achieved_arl - target_arl) <= tolerance, (
            f"achieved_arl={result.achieved_arl!r} is not within "
            f"{_RELATIVE_TOLERANCE:.0%} of target_arl={target_arl!r}"
        )


# ---------------------------------------------------------------------------
# Part 2: General postcondition on _in_control_arl
# ---------------------------------------------------------------------------


class TestInControlArlPostcondition:
    """Every value ``_in_control_arl`` returns must be finite and >= 1.

    ARL0 is the expectation of a stopping time supported on {1, 2, 3, ...}.
    ``E[N] >= 1`` by definition of expectation (ADR-011). A non-finite or
    sub-1 return value is garbage from an ill-conditioned linear solve,
    never a meaningful average run length.

    The parametrisation deliberately places ``limit_multiplier`` values
    near and above the power-of-two boundary where the bracket-expansion
    loop (``_calibrate_limit_multiplier``) crosses into the
    ill-conditioned region. The BIN-140 description traces the trigger:
    the true root lies just above ``L=4.0``, so ``L=8.0`` is the first
    probe that enters garbage territory.
    """

    @pytest.mark.parametrize(
        ("smoothing_param", "limit_multiplier"),
        [
            # The exact L values the bracket-expansion loop probes for the
            # BIN-140 counterexample (smoothing_param=0.013463695801674842,
            # target_arl=104949). At L=8 and above, the solve goes
            # ill-conditioned (cond ~ 9e15) and returns nonsense.
            pytest.param(0.013463695801674842, 4.0, id="counterexample-L-4"),
            pytest.param(0.013463695801674842, 8.0, id="counterexample-L-8"),
            pytest.param(0.013463695801674842, 16.0, id="counterexample-L-16"),
            pytest.param(0.013463695801674842, 32.0, id="counterexample-L-32"),
            pytest.param(0.013463695801674842, 64.0, id="counterexample-L-64"),
            # The second counterexample.
            pytest.param(0.015, 8.0, id="lambda-0.015-L-8"),
            pytest.param(0.015, 16.0, id="lambda-0.015-L-16"),
            pytest.param(0.015, 64.0, id="lambda-0.015-L-64"),
            # Boundary: smallest legal lambda at large L -- the most
            # severe ill-conditioning, since smaller lambda makes the
            # transition matrix approach singularity faster.
            pytest.param(MIN_SMOOTHING_PARAM, 8.0, id="min-lambda-L-8"),
            pytest.param(MIN_SMOOTHING_PARAM, 16.0, id="min-lambda-L-16"),
            pytest.param(MIN_SMOOTHING_PARAM, 64.0, id="min-lambda-L-64"),
            # Well-conditioned region -- these should return cleanly.
            # Included to confirm the postcondition does not reject good
            # values.
            pytest.param(0.2, 3.0, id="typical-lambda-0.2-L-3"),
            pytest.param(0.5, 3.071, id="lucas-saccucci-lambda-0.5-L-3.071"),
            pytest.param(0.03, 2.437, id="lucas-saccucci-lambda-0.03-L-2.437"),
        ],
    )
    def test_returned_arl_is_finite_and_at_least_one(
        self, smoothing_param: float, limit_multiplier: float
    ) -> None:
        """``_in_control_arl`` must never return a non-finite or sub-1 value."""
        result = _in_control_arl(
            smoothing_param, limit_multiplier, _MARKOV_CHAIN_STATES
        )
        assert math.isfinite(result), (
            f"_in_control_arl(smoothing_param={smoothing_param!r}, "
            f"limit_multiplier={limit_multiplier!r}, "
            f"num_states={_MARKOV_CHAIN_STATES}) returned {result!r} -- "
            "not finite"
        )
        assert result >= MIN_COHERENT_ARL, (
            f"_in_control_arl(smoothing_param={smoothing_param!r}, "
            f"limit_multiplier={limit_multiplier!r}, "
            f"num_states={_MARKOV_CHAIN_STATES}) returned {result!r} -- "
            f"below MIN_COHERENT_ARL ({MIN_COHERENT_ARL}). "
            "E[N] >= 1 for any stopping time N supported on "
            "{1, 2, 3, ...} (ADR-011)"
        )


# ---------------------------------------------------------------------------
# Part 3: fit_ewma achieved_arl postcondition over the power-of-two trigger
# ---------------------------------------------------------------------------


class TestFitEwmaAchievedArlPostcondition:
    """``fit_ewma``'s ``achieved_arl`` must be finite, positive, and near the request.

    The BIN-140 trigger fires when the true root in L-space lies just above
    a power of two, so the parametrisation deliberately places ``target_arl``
    values in the trigger zone for several small ``smoothing_param`` values.
    """

    # The exact smoothing_param from the first BIN-140 counterexample,
    # extracted so the parametrised lines fit within the 88-char limit.
    _CE_LAMBDA = 0.013463695801674842

    @pytest.mark.parametrize(
        ("smoothing_param", "target_arl"),
        [
            # --- Trigger zone: target_arl values near the defect ------
            # BIN-140's description shows that at lambda=0.013463...,
            # target=104900 is clean but target=104949 is garbage.
            # Sweep both sides.
            pytest.param(_CE_LAMBDA, 104900.0, id="ce-lambda-near-clean"),
            pytest.param(_CE_LAMBDA, 104949.0, id="ce-lambda-exact"),
            pytest.param(_CE_LAMBDA, 105000.0, id="ce-lambda-105000"),
            pytest.param(_CE_LAMBDA, 110000.0, id="ce-lambda-110000"),
            pytest.param(0.015, 104949.0, id="lambda-0.015-target-104949"),
            # --- Small lambda at high target -- the regime most
            # susceptible to ill-conditioning.
            pytest.param(MIN_SMOOTHING_PARAM, 100000.0, id="min-lam-1e5"),
            pytest.param(MIN_SMOOTHING_PARAM, 500000.0, id="min-lam-5e5"),
            pytest.param(
                MIN_SMOOTHING_PARAM,
                MAX_MEANINGFUL_ARL,
                id="min-lam-max",
            ),
            pytest.param(0.02, 200000.0, id="lambda-0.02-target-2e5"),
            pytest.param(0.03, 500000.0, id="lambda-0.03-target-5e5"),
            # --- Well-conditioned region -- must still hold -----------
            pytest.param(0.2, 500.0, id="typical-500"),
            pytest.param(0.5, 370.0, id="lambda-0.5-370"),
            pytest.param(0.03, 500.0, id="ls-lambda-0.03-500"),
            pytest.param(1.0, 370.0, id="shewhart-limit-370"),
            # --- Corner: smallest legal target ------------------------
            pytest.param(MIN_SMOOTHING_PARAM, MIN_TARGET_ARL, id="min-min"),
            pytest.param(MAX_SMOOTHING_PARAM, MIN_TARGET_ARL, id="max-min"),
        ],
    )
    def test_achieved_arl_is_finite_positive_and_near_request(
        self, smoothing_param: float, target_arl: float
    ) -> None:
        """``fit_ewma`` must never return a nonsense ``achieved_arl``."""
        try:
            result = fit_ewma(
                _PROBE_BASELINE,
                target_arl=target_arl,
                smoothing_param=smoothing_param,
            )
        except CaliperError:
            # A CaliperError naming the combination is acceptable --
            # a refusal is always a pass here (BIN-122's "never silently
            # wrong" property).
            return

        assert math.isfinite(result.achieved_arl), (
            f"fit_ewma(smoothing_param={smoothing_param!r}, "
            f"target_arl={target_arl!r}) returned a non-finite "
            f"achieved_arl={result.achieved_arl!r}"
        )
        assert result.achieved_arl >= MIN_COHERENT_ARL, (
            f"fit_ewma(smoothing_param={smoothing_param!r}, "
            f"target_arl={target_arl!r}) returned "
            f"achieved_arl={result.achieved_arl!r} < MIN_COHERENT_ARL "
            f"({MIN_COHERENT_ARL}). E[N] >= 1 for any stopping time "
            "(ADR-011)"
        )
        tolerance = target_arl * _RELATIVE_TOLERANCE
        assert abs(result.achieved_arl - target_arl) <= tolerance, (
            f"fit_ewma(smoothing_param={smoothing_param!r}, "
            f"target_arl={target_arl!r}) returned "
            f"achieved_arl={result.achieved_arl!r} -- not within "
            f"{_RELATIVE_TOLERANCE:.0%} of the request"
        )


# ---------------------------------------------------------------------------
# Part 4: Published-table tests must still hold (guard against a fix that
# shifts the calibration)
# ---------------------------------------------------------------------------


class TestPublishedTableUnaffected:
    """Confirm the fix does not move the published Lucas & Saccucci (1990) values.

    ``test_ewma_arl_published_values.py`` is the primary guard -- these are
    a subset, duplicated here deliberately so that a reviewer of this file
    can see *in this file* that the counterexample fix did not shift the
    well-conditioned region's calibration.

    Source: Lucas & Saccucci (1990), *Technometrics* 32(1):1-12, Table 3.
    "L values are based on zero-state in-control ARL = 500."
    """

    @pytest.mark.parametrize(
        ("smoothing_param", "published_arl0"),
        [
            pytest.param(0.5, 500.0, id="lambda-0.5-arl-500"),
            pytest.param(0.03, 500.0, id="lambda-0.03-arl-500"),
            pytest.param(0.2, 500.0, id="lambda-0.2-arl-500"),
        ],
    )
    def test_published_arl0_still_holds(
        self, smoothing_param: float, published_arl0: float
    ) -> None:
        """The calibration at a published (lambda, target_arl) pair is unchanged."""
        result = fit_ewma(
            _PROBE_BASELINE,
            target_arl=published_arl0,
            smoothing_param=smoothing_param,
        )
        tolerance = published_arl0 * _RELATIVE_TOLERANCE
        assert abs(result.achieved_arl - published_arl0) <= tolerance, (
            f"fit_ewma(smoothing_param={smoothing_param!r}, "
            f"target_arl={published_arl0!r}) achieved "
            f"{result.achieved_arl!r} -- outside the 2% tolerance "
            "the published-table tests enforce. The fix has shifted "
            "the well-conditioned calibration."
        )


# ---------------------------------------------------------------------------
# Part 5: CUSUM and Shewhart are NOT exposed to this defect class
# ---------------------------------------------------------------------------


class TestCusumNotExposedToSolveInstability:
    """CUSUM uses Siegmund's closed-form approximation, not a linear solve.

    ``_cusum_arl0`` computes ``(exp(2*k*b) - 1 - 2*k*b) / (2*k^2)``
    (Montgomery 2013, p. 423, eq. 9.6) -- no matrix, no
    ``np.linalg.solve``, no ill-conditioning. This test confirms the
    absence by fitting at the corners of the legal parameter space where
    EWMA fails, and asserting coherence.
    """

    @pytest.mark.parametrize(
        "target_arl",
        [
            pytest.param(104949.0, id="ewma-counterexample-target"),
            pytest.param(MAX_MEANINGFUL_ARL, id="max-target"),
            pytest.param(MIN_TARGET_ARL, id="min-target"),
            pytest.param(500.0, id="typical-target"),
        ],
    )
    def test_cusum_achieved_arl_is_always_coherent(self, target_arl: float) -> None:
        """``fit_cusum`` never returns a nonsense ``achieved_arl``."""
        try:
            result = fit_cusum(
                _PROBE_BASELINE,
                target_arl=target_arl,
                reference_value=0.5,
                direction="two_sided",
            )
        except CaliperError:
            # CUSUM has a genuine attainability ceiling (BIN-117), so a
            # refusal is expected for some combinations. That is fine --
            # the property is "never silently wrong".
            return

        assert math.isfinite(result.achieved_arl), (
            f"fit_cusum(target_arl={target_arl!r}) returned "
            f"achieved_arl={result.achieved_arl!r} -- not finite"
        )
        assert result.achieved_arl >= MIN_COHERENT_ARL, (
            f"fit_cusum(target_arl={target_arl!r}) returned "
            f"achieved_arl={result.achieved_arl!r} -- below 1.0"
        )


class TestShewhartNotExposedToSolveInstability:
    """Shewhart uses a closed-form tail probability, not a numerical solve.

    ``_shewhart_arl0`` computes ``1 / (2 * Phi(-L))`` -- an exact
    bijection. This test confirms the absence by fitting at the same
    target values where EWMA fails.
    """

    @pytest.mark.parametrize(
        "target_arl",
        [
            pytest.param(104949.0, id="ewma-counterexample-target"),
            pytest.param(MAX_MEANINGFUL_ARL, id="max-target"),
            pytest.param(MIN_TARGET_ARL, id="min-target"),
            pytest.param(500.0, id="typical-target"),
        ],
    )
    def test_shewhart_achieved_arl_is_always_coherent(self, target_arl: float) -> None:
        """``fit_shewhart`` never returns a nonsense ``achieved_arl``."""
        result = fit_shewhart(_PROBE_BASELINE, target_arl=target_arl)

        assert math.isfinite(result.achieved_arl), (
            f"fit_shewhart(target_arl={target_arl!r}) returned "
            f"achieved_arl={result.achieved_arl!r} -- not finite"
        )
        assert result.achieved_arl >= MIN_COHERENT_ARL, (
            f"fit_shewhart(target_arl={target_arl!r}) returned "
            f"achieved_arl={result.achieved_arl!r} -- below 1.0"
        )


__all__: list[str] = []


def test_sentinel_exceeds_every_legal_target_arl() -> None:
    """The ill-conditioned sentinel is larger than any ``target_arl`` can be.

    🚨 **This pins the relationship BIN-140's fix quietly rests on.**
    ``_in_control_arl`` returns ``_ILL_CONDITIONED_ARL_SENTINEL`` when the
    Markov solve breaks down, and ``_calibrate_limit_multiplier`` has one
    path -- the ``_MAX_LIMIT_MULTIPLIER`` bail-out -- that returns
    ``_in_control_arl``'s value **directly** as ``achieved_arl``, with no
    re-evaluation at a solved root.

    That path cannot currently emit the sentinel, but **only because** a
    sentinel-valued gap is hugely positive for every legal target, so the
    bracket-expansion loop always exits before reaching it. It is
    unreachable by arithmetic, not by construction.

    ⚠️ **If ``MAX_MEANINGFUL_ARL`` ever rose above the sentinel, the
    sentinel would become reportable as an ``achieved_arl``** -- a
    fabricated number presented as the library's own accuracy claim, which
    is precisely the defect class BIN-140 exists to close. Raising that
    ceiling is a plausible future change (ADR-011 calls the 1e6 figure "an
    engineering default, not a published constant"), and nothing else
    would catch it.

    An unreachable error branch was considered instead and rejected: it
    would be untestable dead code, and ``assert`` is not an option because
    ``AssertionError`` is not a ``CaliperError`` (BIN-120).
    """
    assert _ILL_CONDITIONED_ARL_SENTINEL > MAX_MEANINGFUL_ARL, (
        f"sentinel ({_ILL_CONDITIONED_ARL_SENTINEL}) no longer exceeds "
        f"MAX_MEANINGFUL_ARL ({MAX_MEANINGFUL_ARL}) -- the "
        "_MAX_LIMIT_MULTIPLIER bail-out in _calibrate_limit_multiplier can "
        "now return the sentinel as an achieved_arl. Raise the sentinel, or "
        "guard that path."
    )
    # A wide margin, not a bare inequality: the bracket loop must read the
    # sentinel as unambiguously "above target", not marginally so.
    assert _ILL_CONDITIONED_ARL_SENTINEL >= MAX_MEANINGFUL_ARL * 1e6
