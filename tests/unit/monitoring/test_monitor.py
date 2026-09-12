"""Unit tests for ``Monitor`` (BIN-69) -- Phase II recording and signal checking.

Pins the nine acceptance scenarios in
``tests/bdd/features/monitoring/phase-ii-observation-signal-check.feature``
at the unit level, plus boundary/independence/constructor-validation cases
the domain model requires but no scenario names individually (ADR-009,
``docs/domain-model.md`` Object Map -- Monitor).

``Monitor``/``MonitoringResult`` do not exist yet anywhere in ``src/`` --
importing them from ``caliper.monitoring`` fails until ``domain-implementer``
adds ``src/caliper/monitoring/``. That ``ImportError`` is the correct red
state for this ticket (TDD red phase), the same shape every other E2/E3 test
file in this repo starts from.

**Decisions this file makes, flagged rather than guessed silently:**

1. **Constructor validation is tested**
   (``test_constructor_rejects_a_non_artefact``). ``docs/domain-model.md``'s
   Object Map -- Monitor offers ``isinstance(artefact,
   FittedControlLimits)`` raising ``InvalidParameterError(parameter=
   "artefact", kind="invalid")`` as "the obvious, taxonomy-consistent
   default... not a product decision requiring escalation," explicitly for
   ``backend-test-writer``/``domain-implementer`` to confirm. Confirmed
   here: it is cheap, mirrors ``Judge.provider``'s existing structural
   check, and pins a definite contract rather than leaving the
   constructor's failure mode undefined for a later story to discover by
   surprise.

2. **The accumulator-reset-after-signal question (Open Question 12,
   ``BIN-113``) is deliberately NOT tested anywhere in this file.** No test
   below records a signal and then asserts anything about the *next*
   observation's accumulated value -- doing so would encode a guess at one
   of the three undecided behaviours (reset-to-zero, FIR head-start,
   continue-unchanged) as a contract. Every accumulation test stops at
   "eventually signals" or "two ``Monitor``s are independent," never
   "recovers/continues in a specific way after signalling."

3. **CUSUM's exact update formula is assumed from the standardised-CUSUM
   convention ``fit_cusum``'s own module docstring already commits to**
   (``src/caliper/baseline/domain/cusum_fitting.py``: "CUSUM statistic
   accumulates deviations of the *standardised* score from its target...
   S_t = max(0, S_(t-1) + ...)", citing Siegmund 1985 via Montgomery).
   Boundary and accumulation tests below compute an exact input score from
   the fitted artefact's own ``target_value``/``reference_value``/
   ``sigma_estimate``/``decision_interval`` fields under that formula. If
   ``Monitor``'s implementation genuinely departs from that standard
   formula, these are the tests that will surface the discrepancy -- not a
   sign the test is wrong, since the fitting module's own docstring already
   commits to the standard form.

4. **EWMA boundary tests use ``smoothing_param=1.0``** (the documented
   maximum, ``MAX_SMOOTHING_PARAM``) so the very first recorded
   observation's EWMA statistic equals the raw score exactly -- the only
   way to hit an EWMA control limit exactly on the first call without
   depending on unpublished convergence arithmetic.

5. **There is deliberately no CUSUM exact-decision-interval boundary
   test.** Verified empirically while drafting this file (against a
   scratch reference implementation, since deleted) that a score
   engineered to land the CUSUM statistic at exactly ``decision_interval``
   is only exact modulo the specific floating-point rounding of the
   multiply-then-divide round trip used to derive it -- against some
   randomly-fitted baselines this landed one ULP on the wrong side. That
   is a property of reverse-deriving an exact float target, not of the
   strict-inequality convention itself, and it would make the test flaky
   against any correct implementation that computes the standardised
   statistic via a different (still-correct) operation order -- not just
   against this file's own drafting stub. Shewhart's and EWMA's boundary
   tests are exact by construction (a direct field comparison; a
   lambda=1.0 passthrough) and already demonstrate the convention applies
   uniformly to both observation-scale-limit chart types. See the comment
   in place of the removed test, below the invalid-provenance test, for
   the full note.

Uses ``ScoringResultFactory``/``ProvenanceFactory`` (``tests/factories.py``)
for baseline filler observations where the specific score does not matter,
and literal ``ScoringResult``/``Provenance`` construction for the Phase II
observations under test, mirroring
``tests/unit/baseline/test_compare_provenance.py``'s own convention. Fitted
artefacts are obtained by calling ``fit_ewma``/``fit_cusum``/
``fit_shewhart`` -- never constructed directly, mirroring every sibling
fitting test file.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import caliper
from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    FittingAdvisory,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.errors import (
    InvalidObservationError,
    InvalidParameterError,
    ProvenanceMismatchError,
)
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from caliper.monitoring import Monitor, MonitoringResult
from tests.factories import ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."
_DIFFERENT_MODEL_VERSION = "claude-opus-4-5-20260101"
_DIFFERENT_CRITERIA = "Evaluate the response for tone and empathy."

# Arbitrary, sufficiently-large target ARL0 -- carries no statistical
# meaning here, matching every sibling fitting test/step file's own
# `_SHAPE_TEST_TARGET_ARL`.
_SHAPE_TEST_TARGET_ARL = 370.0

# Explicit smoothing_param used across every EWMA test below except the
# boundary tests (which use MAX_SMOOTHING_PARAM = 1.0) -- deterministic
# accumulation arithmetic requires a known lambda, matching the sibling
# fitting test files' own `_SHAPE_TEST_SMOOTHING_PARAM`.
_ACCUMULATION_SMOOTHING_PARAM = 0.3

# Generous cap on repeated recordings while waiting for an accumulating
# chart to signal -- both the EWMA and CUSUM accumulation tests below
# derive a shift that needs roughly 13-20 repeats to cross the boundary
# (see the inline derivations); this cap is a wide, deliberately
# non-tight safety margin, not a claim about the exact number of
# repeats required.
_MAX_ACCUMULATION_ITERATIONS = 200


def _result(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
    score: float = 0.9,
    reasoning: str = "Accurate and concise.",
) -> ScoringResult:
    """Build a ``ScoringResult`` with an explicit, literal provenance."""
    return ScoringResult(
        score=score,
        reasoning=reasoning,
        provenance=Provenance(
            model_version=ModelVersion(value=model_version),
            scoring_criteria=ScoringCriteria(value=criteria),
        ),
    )


def _baseline_with_provenance(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA, count: int
) -> Baseline:
    """Build a ``Baseline`` of ``count`` observations sharing one literal provenance."""
    baseline = Baseline()
    provenance = Provenance(
        model_version=ModelVersion(value=model_version),
        scoring_criteria=ScoringCriteria(value=criteria),
    )
    for _ in range(count):
        baseline.record(ScoringResultFactory(provenance=provenance))
    return baseline


def _fitted_ewma(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
    smoothing_param: float = _ACCUMULATION_SMOOTHING_PARAM,
) -> FittedEWMA:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_ewma(
        baseline, target_arl=_SHAPE_TEST_TARGET_ARL, smoothing_param=smoothing_param
    )


def _fitted_cusum(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedCUSUM:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _fitted_shewhart(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedShewhart:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


@dataclass(frozen=True)
class _FakeConformingArtefact:
    """Satisfies ``FittedControlLimits`` structurally, but not a real chart type.

    BIN-120 (external code review, 2026-09-11, reproduced): exposes every
    attribute name the ``@runtime_checkable`` ``FittedControlLimits``
    protocol requires (ADR-004 section 1) -- so
    ``isinstance(_FakeConformingArtefact(), FittedControlLimits)`` is
    ``True`` -- but is none of the three concrete types
    (``FittedEWMA``/``FittedCUSUM``/``FittedShewhart``) ``Monitor._check()``
    actually knows how to dispatch on. Used only to prove that a structural
    protocol match must not, by itself, be treated as sufficient for
    ``Monitor``'s constructor to accept an artefact -- see ADR-004 section 3
    for why the protocol is deliberately *not* extended with a polymorphic
    detection operation instead (the fix this class's test exercises is
    "narrow the constructor", not "widen the protocol").
    """

    chart_type: str = "unsupported_chart"
    baseline_mean: float = 0.5
    baseline_spread: float = 0.1
    sigma_estimate: float = 0.1
    sigma_estimation_method: str = "moving_range"
    observation_count: int = DEFAULT_SUFFICIENCY_THRESHOLD
    provenance_model_version: str = _MODEL_VERSION
    provenance_criteria: str = _CRITERIA
    requested_arl: float = _SHAPE_TEST_TARGET_ARL
    achieved_arl: float = _SHAPE_TEST_TARGET_ARL
    calibration_method: str = "unsupported_method"
    advisories: tuple[FittingAdvisory, ...] = ()


class _ReprRaisingConformingArtefact:
    """Satisfies ``FittedControlLimits`` structurally; its own ``__repr__`` raises.

    `code-reviewer`'s BIN-120 review (2026-09-11), blocker 2: before the
    fix, ``Monitor.__init__``'s rejection stored the live, rejected
    ``artefact`` object directly in
    ``InvalidParameterError.context["provided"]``. A caller doing exactly
    what ``ADR-008`` says ``context`` is *for* --
    ``except InvalidParameterError as e: log.warning(..., **e.context)`` --
    would crash the moment logging touched ``provided``, for an artefact
    whose own ``__repr__`` fails. The exact ``BIN-118`` hazard
    (``_Hostile``/``_ReprRaisingReceiver`` in ``test_signal_delivery.py``),
    reproduced here at a second boundary. Plain attributes (not a frozen
    dataclass, unlike ``_FakeConformingArtefact``) so the custom
    ``__repr__`` below is the only one defined -- a dataclass would still
    generate its own unless explicitly suppressed.
    """

    chart_type = "unsupported_chart"
    baseline_mean = 0.5
    baseline_spread = 0.1
    sigma_estimate = 0.1
    sigma_estimation_method = "moving_range"
    observation_count = DEFAULT_SUFFICIENCY_THRESHOLD
    provenance_model_version = _MODEL_VERSION
    provenance_criteria = _CRITERIA
    requested_arl = _SHAPE_TEST_TARGET_ARL
    achieved_arl = _SHAPE_TEST_TARGET_ARL
    calibration_method = "unsupported_method"
    advisories: tuple[FittingAdvisory, ...] = ()

    def __repr__(self) -> str:
        raise RuntimeError("repr exploded")


def _ewma_first_call_in_control_shift(
    artefact: FittedEWMA, *, fraction: float = 0.01
) -> float:
    """A score just above ``ucl`` whose *first* EWMA statistic (computed
    from a fresh accumulator, i.e. the baseline mean) still falls below
    ``ucl`` -- yet repeating it drives the EWMA statistic to eventually
    exceed ``ucl``, since the EWMA recursion converges monotonically
    toward whatever score is repeated.

    Derivation: with z_0 = baseline_mean = cl, z_1 = lambda*x + (1-lambda)*cl.
    Requiring z_1 < ucl for x = ucl + delta reduces to
    delta < ((1 - lambda) / lambda) * (ucl - cl). At
    lambda = _ACCUMULATION_SMOOTHING_PARAM (0.3), that bound is
    ~2.33 * (ucl - cl); `fraction=0.01` sits comfortably inside it.
    """
    return artefact.ucl + fraction * (artefact.ucl - artefact.baseline_mean)


def _cusum_score_for_upper_statistic(
    artefact: FittedCUSUM, target_statistic: float
) -> float:
    """The raw score whose first-call standardised CUSUM increment equals
    ``target_statistic`` exactly, starting from a fresh (zero) accumulator.

    Assumes the standard one-sided upper CUSUM recursion
    ``S_hi_t = max(0, S_hi_{t-1} + z_t - k)`` where
    ``z_t = (x_t - target_value) / sigma_estimate`` -- see file docstring
    point 3.
    """
    standardised_increment = artefact.reference_value + target_statistic
    return artefact.target_value + standardised_increment * artefact.sigma_estimate


# --- Happy path: in control (SC1) ----------------------------------------------


def test_confirms_in_control_for_observation_within_calibrated_boundaries() -> None:
    """A production observation within calibrated boundaries is confirmed in control."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    observation = _result(score=artefact.baseline_mean)

    # Act
    outcome = monitor.record(observation)

    # Assert
    assert outcome.is_in_control is True


# --- Signal path: out of control, identifies the observation (SC2) -------------


def test_reports_out_of_control_and_identifies_the_triggering_observation() -> None:
    """A breach is reported out of control, and identifies what triggered it."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    observation = _result(score=breach_score)

    # Act
    outcome = monitor.record(observation)

    # Assert
    assert outcome.is_in_control is False
    assert outcome.observation == observation


# --- Accumulation vs memorylessness (BR-3, BR-4) --------------------------------


def test_ewma_accumulates_evidence_across_a_sustained_small_shift() -> None:
    """A small, sustained shift, individually in control, eventually signals."""
    # Arrange
    artefact = _fitted_ewma(smoothing_param=_ACCUMULATION_SMOOTHING_PARAM)
    monitor = Monitor(artefact)
    shifted_score = _ewma_first_call_in_control_shift(artefact)

    # Act -- first call: in control alone (proves the eventual signal below is
    # not just "this score always signals")
    first_outcome = monitor.record(_result(score=shifted_score))

    # Assert
    assert first_outcome.is_in_control is True

    # Act -- repeat the *same* score; the recursive statistic converges
    # monotonically toward it, which is > ucl by construction
    signalled = False
    for _ in range(_MAX_ACCUMULATION_ITERATIONS):
        outcome = monitor.record(_result(score=shifted_score))
        if outcome.is_in_control is False:
            signalled = True
            break

    # Assert
    assert signalled, (
        "expected the sustained shift to eventually signal within "
        f"{_MAX_ACCUMULATION_ITERATIONS} repeats"
    )


def test_cusum_accumulates_evidence_across_a_sustained_small_shift() -> None:
    """Same contract as the EWMA test above, for CUSUM's accumulating statistic."""
    # Arrange
    artefact = _fitted_cusum()
    monitor = Monitor(artefact)
    small_increment = artefact.decision_interval / 20.0
    shifted_score = _cusum_score_for_upper_statistic(artefact, small_increment)

    # Act -- first call: in control alone
    first_outcome = monitor.record(_result(score=shifted_score))

    # Assert
    assert first_outcome.is_in_control is True

    # Act -- repeat; S_hi accumulates ~small_increment per call, crossing h
    # after roughly 20 repeats
    signalled = False
    for _ in range(_MAX_ACCUMULATION_ITERATIONS):
        outcome = monitor.record(_result(score=shifted_score))
        if outcome.is_in_control is False:
            signalled = True
            break

    # Assert
    assert signalled, (
        "expected the sustained shift to eventually signal within "
        f"{_MAX_ACCUMULATION_ITERATIONS} repeats"
    )


def test_shewhart_evaluates_each_observation_independently_of_prior_outcome() -> None:
    """A chart that evaluates each observation independently ignores a prior outcome."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act -- a prior observation is reported out of control
    prior_outcome = monitor.record(_result(score=breach_score))
    assert prior_outcome.is_in_control is False

    # Act -- a further, in-bounds observation
    outcome = monitor.record(_result(score=artefact.baseline_mean))

    # Assert -- unaffected by the prior out-of-control outcome
    assert outcome.is_in_control is True


# --- Edge: first observation needs no prior history -----------------------------


def test_first_phase_ii_observation_is_checkable_without_prior_history() -> None:
    """The very first Phase II observation after fitting can be checked on its own."""
    # Arrange
    artefact = _fitted_ewma()
    monitor = Monitor(artefact)

    # Act
    outcome = monitor.record(_result(score=artefact.baseline_mean))

    # Assert
    assert isinstance(outcome.is_in_control, bool)


# --- Sad path: provenance mismatch (BR-2, reuses BIN-68) ------------------------


def test_raises_provenance_mismatch_error_when_observation_provenance_differs() -> None:
    """Recording is refused when the observation's provenance doesn't match."""
    # Arrange
    artefact = _fitted_ewma(model_version=_MODEL_VERSION, criteria=_CRITERIA)
    monitor = Monitor(artefact)
    mismatched = _result(model_version=_DIFFERENT_MODEL_VERSION, criteria=_CRITERIA)

    # Act
    with pytest.raises(ProvenanceMismatchError) as exc_info:
        monitor.record(mismatched)

    # Assert
    error = exc_info.value
    assert error.category == "provenance_mismatch"
    assert "model_version" in error.mismatches


# --- Sad path: invalid observation (BR-5) ---------------------------------------


def test_raises_invalid_observation_error_for_an_incomplete_input() -> None:
    """Recording is refused for something that is not a complete scored observation."""
    # Arrange
    monitor = Monitor(_fitted_shewhart())

    # Act
    with pytest.raises(InvalidObservationError) as exc_info:
        monitor.record(None)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_observation"
    assert isinstance(error.context["reason"], str)
    assert error.context["reason"] != ""
    assert set(error.context["missing_fields"]) == {"score", "reasoning", "provenance"}


class _RaisingScoreObservation:
    """Not a ``ScoringResult``; its ``score`` attribute raises rather than being absent.

    Used for BIN-127 -- mirrors ``test_baseline.py``'s identically-named
    fixture, since both entry points now share
    ``caliper.baseline.domain.attribute_probe`` and must report the same
    ``context`` distinction.
    """

    @property
    def score(self) -> float:
        raise RuntimeError("boom-on-score-access")


def test_context_distinguishes_raised_from_absent_field_access() -> None:
    """BIN-127: a field that raises on access is reported distinctly from one

    that is simply absent, in ``context`` -- not flattened into one
    undifferentiated ``missing_fields`` list, and the raw ``RuntimeError``
    never escapes ``record()``.
    """
    # Arrange
    monitor = Monitor(_fitted_shewhart())
    hostile = _RaisingScoreObservation()

    # Act
    with pytest.raises(InvalidObservationError) as exc_info:
        monitor.record(hostile)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_observation"
    assert set(error.context["missing_fields"]) == {"reasoning", "provenance"}
    assert error.context["unreadable_fields"] == {"score": "RuntimeError"}


# --- Edge: signals are not errors (BR-7) ----------------------------------------


def test_out_of_control_determination_does_not_raise_and_program_continues() -> None:
    """An out-of-control determination is a normal result, not an exception."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    program_continued = False

    # Act
    outcome = monitor.record(_result(score=breach_score))
    program_continued = True

    # Assert
    assert outcome.is_in_control is False
    assert program_continued is True


# --- Edge: consistency across chart types (BR-6, ADR-004) -----------------------


def test_checking_works_the_same_way_regardless_of_which_chart_type_was_fitted() -> (
    None
):
    """Every chart type produces a determinable in-control/out-of-control outcome."""
    # Arrange
    baseline = _baseline_with_provenance(count=DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    artefacts: list[FittedControlLimits] = [
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
    ]
    observation = _result(score=baseline.observations[0].score)

    # Act / Assert
    for artefact in artefacts:
        monitor = Monitor(artefact)
        outcome = monitor.record(observation)
        assert isinstance(outcome.is_in_control, bool)
        assert outcome.chart_type == artefact.chart_type


# --- Boundary convention: strict inequality (ADR-009 section 5) -----------------


def test_shewhart_observation_exactly_at_ucl_is_in_control() -> None:
    """A point exactly at the upper control limit is in control, not out."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)

    # Act
    outcome = monitor.record(_result(score=artefact.ucl))

    # Assert
    assert outcome.is_in_control is True


def test_shewhart_observation_exactly_at_lcl_is_in_control() -> None:
    """A point exactly at the lower control limit is in control, not out."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)

    # Act
    outcome = monitor.record(_result(score=artefact.lcl))

    # Assert
    assert outcome.is_in_control is True


def test_ewma_statistic_exactly_at_ucl_is_in_control() -> None:
    """The same strict-inequality convention, for the EWMA statistic itself.

    Uses ``smoothing_param=1.0`` (``MAX_SMOOTHING_PARAM``) so the first
    recorded observation's EWMA statistic equals the raw score exactly --
    see file docstring point 4.
    """
    # Arrange
    artefact = _fitted_ewma(smoothing_param=1.0)
    monitor = Monitor(artefact)

    # Act
    outcome = monitor.record(_result(score=artefact.ucl))

    # Assert
    assert outcome.is_in_control is True


# No CUSUM exact-decision-interval boundary test: deliberately omitted, not
# an oversight. Verified empirically while drafting this file against a
# scratch reference implementation of the standard formula (file docstring
# point 3) -- an input engineered to land the CUSUM statistic at exactly
# `decision_interval` is only exact modulo the specific floating-point
# rounding of the *particular* multiply-then-divide round trip used to
# derive it (`_cusum_score_for_upper_statistic`). Against some (but not
# all) randomly-fitted baselines this landed one ULP on the wrong side of
# the boundary -- a property of the test's own reverse derivation, not of
# the strict-inequality convention it was trying to pin. Since
# `Monitor`'s real implementation may compute the standardised statistic
# via a different (still-correct) operation order, this test would be
# flaky against a correct implementation, not just against this file's
# own scratch stub. Shewhart's and EWMA's boundary tests above are exact
# by construction (direct field comparison; lambda=1.0 passthrough) and
# already demonstrate the convention is applied uniformly at the
# observation-scale-limit charts; `_cusum_score_for_upper_statistic`'s
# accumulation test above tolerates this same imprecision because it only
# needs *eventual* crossing, not an exact landing.


# --- Invariant: accumulator state is private and per-instance -------------------


def test_two_monitors_from_the_same_artefact_have_independent_accumulators() -> None:
    """Two `Monitor`s built from the same artefact never share accumulator state."""
    # Arrange
    artefact = _fitted_ewma(smoothing_param=_ACCUMULATION_SMOOTHING_PARAM)
    shifted_score = _ewma_first_call_in_control_shift(artefact)
    monitor_a = Monitor(artefact)
    monitor_b = Monitor(artefact)

    # Act -- drive monitor_a toward a signal
    for _ in range(_MAX_ACCUMULATION_ITERATIONS):
        outcome = monitor_a.record(_result(score=shifted_score))
        if outcome.is_in_control is False:
            break

    # Act -- monitor_b's very first call with the exact same score
    outcome_b = monitor_b.record(_result(score=shifted_score))

    # Assert -- monitor_b is unaffected by monitor_a's accumulated history
    assert outcome_b.is_in_control is True


# --- Constructor validation (offered by domain-modeller, confirmed here) --------


def test_constructor_rejects_a_non_artefact() -> None:
    """`Monitor(...)` requires a real `FittedControlLimits`-satisfying artefact."""
    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        Monitor("not an artefact")  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "artefact"
    assert error.context["kind"] == "invalid"


def test_constructor_rejects_a_structurally_conforming_but_unsupported_artefact() -> (
    None
):
    """A protocol-satisfying object that is not EWMA/CUSUM/Shewhart is still rejected.

    BIN-120 (external code review, 2026-09-11, reproduced). Before this fix,
    ``isinstance(artefact, FittedControlLimits)`` -- true for
    ``_FakeConformingArtefact``, since the protocol is ``@runtime_checkable``
    (ADR-004 section 1) -- was the constructor's *only* gate, so this object
    was accepted here and only failed later, on its first ``record()`` call,
    with a raw ``AssertionError`` inside ``Monitor._check()``. That is not a
    ``CaliperError`` (ADR-002/ADR-008: no ``category``, no ``context``), and
    it is worse than an ordinary wrong-type error: ``assert`` statements are
    stripped entirely under ``python -O``, so the failure would become
    undefined behaviour rather than an exception under optimisation.

    The fix is option A from the ticket (narrowing the constructor to the
    three supported concrete types, raising ``InvalidParameterError`` on
    anything else) -- not option B (a genuinely polymorphic protocol),
    which would reopen ADR-004 section 3's deliberate rejection of shared
    detection boundaries. This test pins option A's observable contract: an
    object the constructor rejects now, rather than one ``record()`` fails
    on later.
    """
    # Arrange
    fake_artefact = _FakeConformingArtefact()
    # Precondition: this object really does satisfy the protocol
    # structurally -- otherwise this test would not be exercising the
    # defect at all (it would just be testing the already-covered
    # non-artefact case above).
    assert isinstance(fake_artefact, FittedControlLimits)

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        Monitor(fake_artefact)

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "artefact"
    assert error.context["kind"] == "invalid"


def test_constructor_accepts_all_three_concrete_fitted_artefact_types() -> None:
    """The narrowed constructor (BIN-120) still accepts every chart type it supports.

    Direct regression check for the ticket's acceptance criterion "the
    three built-ins still construct ... exactly as before" -- narrowing the
    constructor to reject an unsupported structural match (the test above)
    must not narrow it so far that it also rejects a supported one.
    """
    # Act / Assert -- none of these may raise
    Monitor(_fitted_ewma())
    Monitor(_fitted_cusum())
    Monitor(_fitted_shewhart())


def test_constructor_rejected_artefact_context_is_a_string_not_the_live_object() -> (
    None
):
    """``context["provided"]`` must hold a description, not the caller's live object.

    `code-reviewer`'s BIN-120 review (2026-09-11), blocker 2: every other
    ``"provided"`` value in this codebase holds a scalar the caller passed
    (``measurement/domain/result.py``, ``criteria.py``, ``judge.py``,
    ``model_version.py``, ``baseline.py``, and all three fitting modules)
    -- ``Monitor``'s constructor was the one place storing a live object
    instead. Besides the ``__repr__``-safety hazard the next test covers,
    keeping a caller's object alive inside a raised exception's context is
    an unnecessary lifetime extension and can make ``context``
    unserialisable (e.g. to structured logging).
    """
    # Arrange
    fake_artefact = _FakeConformingArtefact()

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        Monitor(fake_artefact)

    # Assert
    error = exc_info.value
    assert isinstance(error.context["provided"], str)
    # Identity, not equality -- proves this is a *description*, not the
    # caller's live object kept alive inside the exception (mypy flags a
    # str/object `==`/`is` comparison as non-overlapping once the
    # isinstance check above has narrowed the left side to `str`; `id()`
    # sidesteps that while asserting the same thing).
    assert id(error.context["provided"]) != id(fake_artefact)


def test_constructor_rejects_an_artefact_whose_repr_itself_raises() -> None:
    """Describing a rejected artefact for ``context["provided"]`` must not itself raise.

    `code-reviewer`'s BIN-120 review (2026-09-11), blocker 2, reproduced
    directly: before the fix, building ``InvalidParameterError`` from
    ``_ReprRaisingConformingArtefact`` would have stored the live object in
    ``context["provided"]`` without incident (storing a reference never
    calls ``__repr__``) -- but the instant a caller's own ``except`` block
    logged or printed ``e.context``, ``repr()`` would run implicitly and
    raise, crashing code that was only trying to handle the error Caliper
    had already raised correctly. ``Monitor.__init__`` itself must still
    raise ``InvalidParameterError`` cleanly, with ``context["provided"]``
    already a safe string.
    """
    # Arrange
    fake_artefact = _ReprRaisingConformingArtefact()
    # Precondition: this object really does satisfy the protocol
    # structurally -- otherwise this test would not be exercising the
    # rejection path at all.
    assert isinstance(fake_artefact, FittedControlLimits)

    # Act
    with pytest.raises(InvalidParameterError) as exc_info:
        Monitor(fake_artefact)

    # Assert
    error = exc_info.value
    assert error.category == "invalid_parameter"
    assert error.context["parameter"] == "artefact"
    assert error.context["kind"] == "invalid"
    assert isinstance(error.context["provided"], str)
    # The description itself must be safely obtainable -- proof that no
    # exception from `__repr__` escaped while building the error.
    str(error.context)


# --- DX surface: top-level promotion ---------------------------------------------


def test_monitor_is_usable_from_the_top_level_caliper_namespace() -> None:
    """`caliper.Monitor(fitted_artefact)` -- the DX snippet ADR-009 commits to."""
    # Arrange
    artefact = _fitted_shewhart()

    # Act
    monitor = caliper.Monitor(artefact)

    # Assert
    assert isinstance(monitor, Monitor)
    outcome = monitor.record(_result(score=artefact.baseline_mean))
    assert isinstance(outcome, MonitoringResult)
