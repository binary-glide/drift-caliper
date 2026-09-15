"""Unit tests for signal content and delivery (BIN-75) -- ADR-010.

Pins the nine acceptance scenarios in
``tests/bdd/features/monitoring/out-of-control-signal-event.feature`` at the
unit level. See ``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``
and ``docs/domain-model.md`` (Object Map -- Monitor invariants 7-8; Value
Object Inventory -- ``MonitoringResult``, ``DeliveryFailure``).

``DeliveryFailure``, ``Monitor(..., receivers=...)``, and
``MonitoringResult.direction``/``.fitted_artefact``/``.delivery_failures`` do
not exist yet -- importing them fails until ``domain-implementer`` extends
``src/drift_caliper/monitoring/``. That ``ImportError`` is the correct red state
for this ticket (TDD red phase), the same shape every other E2/E3/E4 test
file in this repo starts from.

A prior pass of this file flagged a Gherkin syntax defect in
``out-of-control-signal-event.feature`` (a step's text wrapped onto a
second, un-keyworded physical line -- invalid under pytest-bdd 8.1.0's
grammar, and because the parser fails for the whole file, not just the
offending scenario, it made all nine scenarios uncollectable). That defect
was the coordinator's own, introduced while applying
``requirements-reviewer``'s tightened wording, and has since been fixed
(commit ``a686f63``) -- both files now parse cleanly (9 scenarios here, 6
in BIN-76's file), verified directly with
``pytest_bdd.parser.FeatureParser``. ``tests/bdd/test_out_of_control_signal_event.py``
now runs these scenarios against the step definitions in
``tests/bdd/steps/out_of_control_signal_event_steps.py`` -- all nine bind
without a single missing-step error; they still fail at runtime with the
same red-state ``TypeError``/``AttributeError`` this file's own tests hit,
since ``domain-implementer`` has not run yet. This unit-test file remains
the primary place BIN-75's acceptance behaviour is pinned -- it is faster
to run and easier to debug than the BDD layer -- with the BDD layer now
wired up alongside it as the shared, mechanism-neutral acceptance record.

**Decisions this file makes, flagged rather than guessed silently:**

1. **The "absorb, but surface" tests are the ones that matter most** (see
   ``test_delivery_failure_content_comes_from_monitor_not_the_receiver``
   below). ADR-010 §1 is explicit that ``delivery_failures`` must be
   populated entirely from ``Monitor``'s own ``try``/``except`` around each
   receiver call, never by asking the receiver to describe its own failure.
   A receiver below deliberately exposes WRONG ``error_type``/
   ``error_message``-shaped attributes under those exact names, so a future
   implementation that mistakenly consulted receiver-supplied self-reporting
   instead of the real raised exception would produce visibly wrong values
   here rather than silently passing.
2. **The CUSUM ``"two_sided"``-leak test is written for both arms**, not
   just the upper one -- ``domain-model.md``'s explicit warning is that a
   careless ``direction=artefact.direction`` would leak the three-valued
   *configuration* vocabulary onto the two-valued (plus ``None``) *outcome*
   field, and that risk is symmetric across both arms.
3. **``fitted_artefact`` identity, not equality, is asserted** (``is``, not
   ``==``) wherever it matters -- ADR-010 §2 requires it be "referenced,
   never copied," and an equality check alone would not catch an
   implementation that accidentally rebuilt/copied the artefact.
4. **``_MAX_ACCUMULATION_ITERATIONS``/helper functions mirror
   ``tests/unit/monitoring/test_monitor.py`` exactly** (same derivations,
   same constants) rather than importing them -- this file owns its own
   literal-construction helpers, per this codebase's established
   convention (see that file's own docstring point 4-5).
"""

from __future__ import annotations

from collections.abc import Callable

import drift_caliper
from drift_caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedCUSUM,
    FittedEWMA,
    FittedShewhart,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from drift_caliper.measurement import (
    ModelVersion,
    Provenance,
    ScoringCriteria,
    ScoringResult,
)
from drift_caliper.monitoring import DeliveryFailure, Monitor, MonitoringResult
from tests.factories import ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."

# Arbitrary, sufficiently-large target ARL0 -- carries no statistical
# meaning here, matching every sibling fitting test/step file's own
# `_SHAPE_TEST_TARGET_ARL`.
_SHAPE_TEST_TARGET_ARL = 370.0

# Generous cap on repeated recordings while waiting for an accumulating
# chart to signal -- mirrors `tests/unit/monitoring/test_monitor.py`'s
# identical constant and derivation.
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


def _fitted_shewhart(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedShewhart:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _fitted_ewma(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedEWMA:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    # smoothing_param=1.0 (MAX_SMOOTHING_PARAM): the first recorded
    # observation's EWMA statistic equals the raw score exactly -- mirrors
    # test_monitor.py docstring point 4.
    return fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL, smoothing_param=1.0)


def _fitted_cusum(
    *, model_version: str = _MODEL_VERSION, criteria: str = _CRITERIA
) -> FittedCUSUM:
    baseline = _baseline_with_provenance(
        model_version=model_version,
        criteria=criteria,
        count=DEFAULT_SUFFICIENCY_THRESHOLD + 5,
    )
    return fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL)


def _cusum_score_for_upper_statistic(
    artefact: FittedCUSUM, target_statistic: float
) -> float:
    """Raw score whose first-call standardised CUSUM upper-arm increment
    equals ``target_statistic`` exactly, starting from a fresh (zero)
    accumulator. Mirrors ``test_monitor.py``'s identical helper.
    """
    standardised_increment = artefact.reference_value + target_statistic
    return artefact.target_value + standardised_increment * artefact.sigma_estimate


def _cusum_score_for_lower_statistic(
    artefact: FittedCUSUM, target_statistic: float
) -> float:
    """The lower-arm mirror of ``_cusum_score_for_upper_statistic``.

    ``S_lo_t = max(0, S_lo_(t-1) - z_t - k)`` -- so a score *below*
    ``target_value`` (not above) is what drives the lower arm.
    """
    standardised_increment = artefact.reference_value + target_statistic
    return artefact.target_value - standardised_increment * artefact.sigma_estimate


def _drive_to_signal(monitor: Monitor, score: float) -> MonitoringResult:
    """Repeat ``score`` until ``monitor`` signals, or fail the test."""
    for _ in range(_MAX_ACCUMULATION_ITERATIONS):
        outcome = monitor.record(_result(score=score))
        if outcome.is_in_control is False:
            return outcome
    raise AssertionError(
        f"expected a signal within {_MAX_ACCUMULATION_ITERATIONS} repeats"
    )


class _FailingReceiver:
    """A receiver that always raises.

    A named class, not a lambda, so ``repr()``/``__qualname__`` gives
    ``DeliveryFailure.receiver`` a meaningful, deterministic value to
    identify -- meaningful once more than one receiver exists (BIN-80, R2).
    """

    def __call__(self, result: MonitoringResult) -> None:
        raise RuntimeError("receiver exploded")


class _Hostile:
    """The external review's exact reproduction (BIN-118, 2026-09-11).

    Both `__repr__` and `__call__` raise. `Monitor._deliver()` builds
    `DeliveryFailure` from `repr(receiver)`/`str(exc)` *outside* the
    `try`/`except` that catches the receiver's own call -- so before the
    fix, this receiver's `__repr__` failure propagates out of `record()`
    itself, destroying an already-successful measurement and preventing
    any later receiver from running. See
    `test_bin_118_reproduction_...` below for the full reproduction.
    """

    def __repr__(self) -> str:
        raise RuntimeError("repr exploded")

    def __call__(self, result: MonitoringResult) -> None:
        raise ValueError("receiver failed")


class _ReprRaisingReceiver:
    """A receiver whose `__repr__` raises -- BIN-118's `repr()` hazard in
    isolation, distinct from `_Hostile` (which also raises inside
    `__call__`) so each defensive-formatting path is exercised on its own.
    """

    def __repr__(self) -> str:
        raise RuntimeError("repr exploded")

    def __call__(self, result: MonitoringResult) -> None:
        raise ValueError("receiver failed")


class _StrRaisingError(Exception):
    """An exception whose own `__str__` raises -- BIN-118's second hazard.

    `type(exc).__name__` is unaffected (a class attribute, no user code
    executes) -- only `str(exc)` is hazardous here, per the ticket's own
    distinction.
    """

    def __str__(self) -> str:
        raise RuntimeError("str exploded")


class _RaisesStrRaisingExceptionReceiver:
    """A receiver that raises an exception whose own `__str__` raises."""

    def __call__(self, result: MonitoringResult) -> None:
        raise _StrRaisingError("irrelevant -- __str__ itself raises")


class _SelfMisreportingReceiver:
    """Raises one real exception but exposes deliberately WRONG
    self-reported failure information under the exact attribute names
    (``error_type``/``error_message``) a self-reporting implementation
    might mistakenly consult instead of catching the real exception
    itself. See file docstring point 1 -- this is the test that would
    catch a regression to "ask the receiver," not "absorb the exception."
    """

    error_type = "ThisIsNotTheRealErrorType"
    error_message = "this is not the real error message either"

    def __call__(self, result: MonitoringResult) -> None:
        raise ValueError("the actual raised failure")


# --- SC1: direction, calibrated boundaries, and the observation -----------------


def test_signal_identifies_direction_and_artefact_and_observation() -> None:
    """A signal identifies direction, the fitted artefact, and the observation."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    observation = _result(score=breach_score)

    # Act
    outcome = monitor.record(observation)

    # Assert
    assert outcome.is_in_control is False
    assert outcome.direction == "upper"
    assert outcome.fitted_artefact is artefact
    assert outcome.observation == observation


def test_signal_identifies_lower_direction_for_a_downward_breach() -> None:
    """The symmetric case: a downward breach identifies `"lower"`."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)
    breach_score = artefact.lcl - 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert outcome.direction == "lower"


# --- SC2: no signal for an in-control observation --------------------------------


def test_in_control_observation_has_no_direction_but_carries_artefact() -> None:
    """No signal: `direction` is `None`, but `fitted_artefact` is still present
    (ADR-010 §2: present on every result, signal or not)."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)

    # Act
    outcome = monitor.record(_result(score=artefact.baseline_mean))

    # Assert
    assert outcome.is_in_control is True
    assert outcome.direction is None
    assert outcome.fitted_artefact is artefact


# --- SC3: consistent form across chart types --------------------------------------


def test_signal_content_is_consistent_across_all_three_chart_types() -> None:
    """Every chart type's signal carries a real direction and its own artefact,
    in the same form (ADR-004 §3: no flattening of chart-specific boundaries)."""
    # Arrange
    baseline = _baseline_with_provenance(count=DEFAULT_SUFFICIENCY_THRESHOLD + 5)
    artefacts: list[FittedControlLimits] = [
        fit_ewma(baseline, target_arl=_SHAPE_TEST_TARGET_ARL, smoothing_param=1.0),
        fit_cusum(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
        fit_shewhart(baseline, target_arl=_SHAPE_TEST_TARGET_ARL),
    ]

    # Act / Assert
    for artefact in artefacts:
        monitor = Monitor(artefact)
        breach_score = artefact.baseline_mean + 1000.0 * artefact.sigma_estimate
        outcome = _drive_to_signal(monitor, breach_score)
        assert outcome.direction in ("upper", "lower")
        assert outcome.fitted_artefact is artefact
        assert isinstance(outcome.fitted_artefact, FittedControlLimits)


# --- SC4: told about a signal without polling -------------------------------------


def test_receiver_is_invoked_synchronously_when_a_signal_occurs() -> None:
    """A configured receiver is invoked, with the result, before `record()` returns."""
    # Arrange
    received: list[MonitoringResult] = []
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[received.append])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert -- delivered by the time record() returns, no separate inspection needed
    assert received == [outcome]


# --- SC5: not told for routine observations ---------------------------------------


def test_receiver_is_not_invoked_for_a_routine_in_control_observation() -> None:
    """A configured receiver is never invoked when nothing signalled."""
    # Arrange
    received: list[MonitoringResult] = []
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[received.append])

    # Act
    monitor.record(_result(score=artefact.baseline_mean))

    # Assert
    assert received == []


# --- SC6: multiple signals delivered, in order ------------------------------------


def test_multiple_signals_are_delivered_to_the_receiver_in_order() -> None:
    """Each signal in a session is delivered once, in recording order."""
    # Arrange
    received: list[MonitoringResult] = []
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[received.append])
    breach_scores = [
        artefact.ucl + 10.0 * artefact.sigma_estimate,
        artefact.ucl + 20.0 * artefact.sigma_estimate,
        artefact.lcl - 10.0 * artefact.sigma_estimate,
    ]

    # Act
    outcomes = [monitor.record(_result(score=score)) for score in breach_scores]

    # Assert
    assert received == outcomes


# --- SC7: no receivers configured -- still get the determination -----------------


def test_no_receivers_configured_still_returns_the_determination() -> None:
    """Zero-config default: `receivers=()` still returns a full determination."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact)  # receivers defaults to ()
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert outcome.is_in_control is False
    assert outcome.delivery_failures == ()


# --- SC8: recording a signal still completes and returns normally ----------------


def test_recording_a_signal_completes_normally_even_with_receivers() -> None:
    """A genuine signal never raises, even with a (successful) receiver configured."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[lambda result: None])
    program_continued = False
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))
    program_continued = True

    # Assert
    assert outcome.is_in_control is False
    assert program_continued is True


# --- SC9: absorb, but surface -- a failing receiver -------------------------------


def test_a_failing_receiver_does_not_prevent_recording_from_completing() -> None:
    """A receiver raising must not let the exception escape `record()`."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_FailingReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act -- must not raise
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert outcome.is_in_control is False


def test_a_failing_receivers_failure_surfaces_with_type_and_message() -> None:
    """The engineer can determine both THAT delivery failed and WHY, from the
    public result -- `error_type`/`error_message` on `DeliveryFailure`."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_FailingReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert len(outcome.delivery_failures) == 1
    failure = outcome.delivery_failures[0]
    assert isinstance(failure, DeliveryFailure)
    assert failure.error_type == "RuntimeError"
    assert failure.error_message == "receiver exploded"
    assert isinstance(failure.receiver, str)
    assert failure.receiver != ""


def test_delivery_failures_is_a_tuple_not_a_list() -> None:
    """Sequence fields on immutable domain types are tuples (BIN-108)."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_FailingReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert isinstance(outcome.delivery_failures, tuple)


def test_delivery_failure_content_comes_from_monitor_not_the_receiver() -> None:
    """🚨 The subtlest test in this file.

    ``DeliveryFailure`` must be built entirely from ``Monitor``'s own
    ``try``/``except`` around the receiver call -- never by asking the
    receiver to report on itself (ADR-010 §1: "populated by `Monitor`'s own
    delivery loop, never by the receiver reporting on itself"). The
    receiver below raises a real ``ValueError("the actual raised failure")``
    but also exposes deliberately WRONG ``error_type``/``error_message``
    attributes under those exact names. If a future implementation ever
    started consulting a receiver-supplied self-report (an attribute, a
    special return value, a second callback) instead of catching the real
    exception itself, this test would fail with the WRONG (misreported)
    values -- that is the whole point of writing it this way rather than
    simply asserting *some* failure was recorded.
    """
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_SelfMisreportingReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert -- the REAL raised exception, not the receiver's own misleading attrs
    failure = outcome.delivery_failures[0]
    assert failure.error_type == "ValueError"
    assert failure.error_message == "the actual raised failure"


# --- BIN-118: describing a failing receiver/exception must not itself
# --- escape record(), breaking absorb-but-surface -----------------------------
#
# `Monitor._deliver()` catches the receiver's own exception, then calls
# `repr(receiver)` and `str(exc)` to build `DeliveryFailure` -- outside any
# protection. Reproduced by external code review, 2026-09-11:
#
#   record() PROPAGATED RuntimeError: repr exploded | later receiver ran: 0
#
# Three guarantees broken at once: the exception escapes record() (absorb
# fails), later receivers never run, and no result is returned at all --
# destroying a measurement that had already succeeded. `type(exc).__name__`
# is already safe (a class attribute, no user code) -- only `repr()` and
# `str()` are hazardous, so only those two need a defensive fallback.


def test_bin_118_reproduction_a_receiver_that_fails_and_cannot_even_be_described() -> (
    None
):
    """The exact external-review reproduction. `record()` must return
    normally, the later receiver must still run, and a `DeliveryFailure`
    with a fallback identifier must be recorded -- all three guarantees
    the review found broken at once, from a single receiver whose
    `__repr__` and `__call__` both raise.
    """
    # Arrange
    artefact = _fitted_shewhart()
    received: list[MonitoringResult] = []
    monitor = Monitor(artefact, receivers=[_Hostile(), received.append])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act -- must not raise (this is BIN-118: before the fix, `repr(receiver)`
    # inside `Monitor._deliver` propagates RuntimeError here)
    outcome = monitor.record(_result(score=breach_score))

    # Assert -- all three guarantees ADR-010 requires
    assert outcome.is_in_control is False  # a result WAS returned
    assert len(received) == 1  # the later receiver still ran
    assert len(outcome.delivery_failures) == 1  # the failure was recorded, not lost
    failure = outcome.delivery_failures[0]
    assert isinstance(failure, DeliveryFailure)
    assert isinstance(failure.receiver, str)
    assert failure.receiver != ""


def test_a_receiver_whose_repr_raises_does_not_prevent_recording_from_completing() -> (
    None
):
    """The `repr()` hazard in isolation (no `__call__`-description confusion
    from a receiver that also misbehaves some other way)."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_ReprRaisingReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act -- must not raise
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert outcome.is_in_control is False


def test_a_receiver_whose_repr_raises_reports_delivery_failure_with_fallback_id() -> (
    None
):
    """`repr(receiver)` falling back to `type(receiver).__name__` -- the
    exact fallback the ticket specifies -- and the REAL raised exception's
    type/message still coming through unaffected by the repr() failure.
    """
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_ReprRaisingReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert len(outcome.delivery_failures) == 1
    failure = outcome.delivery_failures[0]
    assert isinstance(failure, DeliveryFailure)
    assert failure.receiver == type(_ReprRaisingReceiver()).__name__
    assert failure.error_type == "ValueError"
    assert failure.error_message == "receiver failed"


def test_a_receiver_with_a_raising_repr_does_not_block_the_next_receiver() -> None:
    """Per-receiver isolation (ADR-010 §4 step 3) must hold even when
    describing the FIRST receiver's own failure also raises -- the same
    property `test_one_failing_receiver_does_not_block_the_next_receiver`
    pins for an ordinary failing receiver, now for one that cannot even be
    described.
    """
    # Arrange
    artefact = _fitted_shewhart()
    received: list[MonitoringResult] = []
    monitor = Monitor(artefact, receivers=[_ReprRaisingReceiver(), received.append])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert -- the second receiver still ran, and the final result carries
    # exactly the one failure.
    assert len(received) == 1
    assert received[0].is_in_control is False
    assert len(outcome.delivery_failures) == 1


def test_an_exception_whose_str_raises_does_not_prevent_recording_from_completing() -> (
    None
):
    """The sibling hazard: `str(exc)` raising must not escape `record()`
    either."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_RaisesStrRaisingExceptionReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act -- must not raise
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert outcome.is_in_control is False


def test_an_exception_whose_str_raises_reports_delivery_failure_with_fallback() -> None:
    """`str(exc)` falling back to `type(exc).__name__` -- the exact fallback
    the ticket specifies. `error_type` needs no fallback at all: it is
    already `type(exc).__name__`, a class attribute that cannot itself
    raise, and must stay exact here -- this is the ticket's own explicit
    "only repr() and str() are hazardous" distinction, pinned directly.
    """
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[_RaisesStrRaisingExceptionReceiver()])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert len(outcome.delivery_failures) == 1
    failure = outcome.delivery_failures[0]
    assert isinstance(failure, DeliveryFailure)
    assert failure.error_type == "_StrRaisingError"
    assert failure.error_message == type(_StrRaisingError()).__name__


def test_an_exception_whose_str_raises_does_not_block_the_next_receiver() -> None:
    """Per-receiver isolation holds even when describing the raised
    exception itself also raises."""
    # Arrange
    artefact = _fitted_shewhart()
    received: list[MonitoringResult] = []
    monitor = Monitor(
        artefact, receivers=[_RaisesStrRaisingExceptionReceiver(), received.append]
    )
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert len(received) == 1
    assert received[0].is_in_control is False
    assert len(outcome.delivery_failures) == 1


def test_one_failing_receiver_does_not_block_the_next_receiver() -> None:
    """Per-receiver isolation (ADR-010 §4 step 3): one failure does not stop
    the next receiver from being attempted.

    Does NOT assert the object the second receiver observed equals the
    final returned ``outcome`` -- ADR-010 §4 passes every receiver the
    *same* unmodified provisional result (`delivery_failures=()`), and
    only the single, post-loop `model_copy` (step 4) produces the final
    result carrying every collected failure. A receiver has no business
    observing a sibling receiver's failure, so this only checks what the
    scenario actually requires: that the second receiver still ran, and
    that the final result carries the one failure that did occur.
    """
    # Arrange
    artefact = _fitted_shewhart()
    received: list[MonitoringResult] = []
    monitor = Monitor(artefact, receivers=[_FailingReceiver(), received.append])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    # Act
    outcome = monitor.record(_result(score=breach_score))

    # Assert -- the second receiver still ran (not blocked by the first's
    # failure), and the final result carries exactly the one failure.
    assert len(received) == 1
    assert received[0].is_in_control is False
    assert len(outcome.delivery_failures) == 1


# --- CUSUM "two_sided" must never leak onto MonitoringResult.direction -----------


def test_cusum_two_sided_upper_arm_signal_reports_upper_not_two_sided() -> None:
    """🚨 Critical: `FittedCUSUM.direction` is a *configuration* field with
    three legal values (`"two_sided"`/`"lower"`/`"upper"`);
    `MonitoringResult.direction` is an *outcome* field with only
    `"upper"`/`"lower"`/`None` as legal states. A careless
    `direction=artefact.direction` would leak `"two_sided"` onto a signal,
    which identifies no direction at all (domain-model.md's explicit
    warning). This drives the UPPER arm of a default (`"two_sided"`)
    CUSUM artefact and asserts the reported direction is exactly
    `"upper"` -- never `"two_sided"`.
    """
    # Arrange
    artefact = _fitted_cusum()  # direction not passed -> DEFAULT_DIRECTION
    assert artefact.direction == "two_sided"  # sanity: this is the risky case
    monitor = Monitor(artefact)
    small_increment = artefact.decision_interval / 20.0
    shifted_score = _cusum_score_for_upper_statistic(artefact, small_increment)

    # Act
    outcome = _drive_to_signal(monitor, shifted_score)

    # Assert
    assert outcome.direction == "upper"
    assert outcome.direction != "two_sided"


def test_cusum_two_sided_lower_arm_signal_reports_lower_not_two_sided() -> None:
    """The symmetric case for the lower arm -- see the test above."""
    # Arrange
    artefact = _fitted_cusum()
    assert artefact.direction == "two_sided"
    monitor = Monitor(artefact)
    small_increment = artefact.decision_interval / 20.0
    shifted_score = _cusum_score_for_lower_statistic(artefact, small_increment)

    # Act
    outcome = _drive_to_signal(monitor, shifted_score)

    # Assert
    assert outcome.direction == "lower"
    assert outcome.direction != "two_sided"


# --- Invariant 8: receivers are fixed at construction -----------------------------


def test_monitor_has_no_receiver_mutation_method() -> None:
    """No add/remove-receiver method exists in R1 (ADR-010 §3, invariant 8)."""
    # Arrange
    monitor = Monitor(_fitted_shewhart())

    # Assert
    assert not hasattr(monitor, "add_receiver")
    assert not hasattr(monitor, "remove_receiver")


# --- DX surface: top-level promotion and importability ----------------------------


def test_monitor_is_constructible_with_receivers_from_top_level_namespace() -> None:
    """`caliper.Monitor(fitted_artefact, receivers=[...])` -- the DX snippet
    ADR-010 §3 commits to."""
    # Arrange
    artefact = _fitted_shewhart()
    received: list[MonitoringResult] = []

    # Act
    monitor = drift_caliper.Monitor(artefact, receivers=[received.append])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    outcome = monitor.record(_result(score=breach_score))

    # Assert
    assert isinstance(monitor, Monitor)
    assert received == [outcome]


def test_delivery_failure_is_importable_from_caliper_monitoring() -> None:
    """`DeliveryFailure` is a public value object on `drift_caliper.monitoring`."""
    assert issubclass(DeliveryFailure, object)


def test_signal_receiver_type_alias_is_importable_from_caliper_monitoring() -> None:
    """`SignalReceiver` -- a plain `TypeAlias`, offered for engineers' own type
    hints (ADR-010 §3), not a `Protocol`."""
    from drift_caliper.monitoring import SignalReceiver

    assert SignalReceiver is not None


def test_a_plain_function_is_a_valid_receiver_with_no_special_registration() -> None:
    """No `Protocol`, no base class, no registration method -- any callable
    taking a `MonitoringResult` and returning `None` qualifies (ADR-010 §3)."""

    calls: list[MonitoringResult] = []

    def my_receiver(result: MonitoringResult) -> None:
        calls.append(result)

    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[my_receiver])
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    outcome = monitor.record(_result(score=breach_score))

    assert calls == [outcome]


def test_a_bound_method_is_a_valid_receiver() -> None:
    """A bound method is a plain callable -- confirms ADR-010 §3's forward
    compatibility claim for BIN-81's eventual `on_signal`-style interface."""

    class _Handler:
        def __init__(self) -> None:
            self.received: list[MonitoringResult] = []

        def on_signal(self, result: MonitoringResult) -> None:
            self.received.append(result)

    handler = _Handler()
    artefact = _fitted_shewhart()
    receivers: list[Callable[[MonitoringResult], None]] = [handler.on_signal]
    monitor = Monitor(artefact, receivers=receivers)
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate

    outcome = monitor.record(_result(score=breach_score))

    assert handler.received == [outcome]
