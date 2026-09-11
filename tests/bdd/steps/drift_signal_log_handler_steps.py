"""Step definitions for BIN-76: the built-in log receiver for drift signals.

Binds to
``tests/bdd/features/monitoring/drift-signal-log-handler.feature`` via
``tests/bdd/test_drift_signal_log_handler.py``, the same shape every other
feature file in this repo uses (see
``tests/bdd/test_phase_ii_observation_signal_check.py``).

A prior pass flagged the same Gherkin syntax defect BIN-75's feature file
had, in this story's own file (a step's text wrapped onto a second,
un-keyworded physical line, breaking collection for all six scenarios, not
only the affected one -- verified directly with
``pytest_bdd.parser.FeatureParser``). That defect was the coordinator's own
and has since been fixed (commit ``a686f63``); the file now parses cleanly
and all six scenarios bind against the step definitions below with no
missing-step error (confirmed with a temporary in-process stub for
``log_receiver``, since the real one does not exist until
``domain-implementer`` runs).

Every scenario in this file exercises `caliper.monitoring.log_receiver`
specifically -- unlike BIN-75's steps file, ``receivers`` has no "not
arranged" scenario here, so the base fixture is fixed to ``[log_receiver]``
rather than defaulting to empty and being overridden per scenario.

``caliper.monitoring.log_receiver`` does not exist yet -- importing it
fails until ``domain-implementer`` adds it. That ``ImportError`` is the
correct red state for this ticket.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Protocol, cast

import pytest
from pytest_bdd import given, then, when

from caliper.baseline import (
    DEFAULT_SUFFICIENCY_THRESHOLD,
    Baseline,
    FittedControlLimits,
    FittedShewhart,
    fit_shewhart,
)
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult
from caliper.monitoring import Monitor, MonitoringResult, log_receiver
from tests.factories import ScoringResultFactory

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."
_LOGGER_NAME = "caliper.monitoring"


class _CaliperExtra(Protocol):
    """The ``extra=`` shape ``log_receiver`` attaches to every ``LogRecord``.

    ``logging.LogRecord`` has no static type for arbitrary ``extra=`` keys
    -- they are attached dynamically at runtime. This narrows a record to
    just the fields ``log_receiver`` promises, for type-checking the
    dynamic-attribute assertions below under ``ty``/``mypy --strict``
    without weakening what is actually asserted at runtime.
    """

    caliper_chart_type: str
    caliper_direction: str | None
    caliper_observation_score: float
    caliper_fitted_artefact: FittedControlLimits


def _extra(record: logging.LogRecord) -> _CaliperExtra:
    return cast(_CaliperExtra, record)


# Arbitrary, sufficiently-large target ARL0 -- carries no statistical
# meaning here, matching every sibling fitting test/step file's own
# `_SHAPE_TEST_TARGET_ARL`.
_SHAPE_TEST_TARGET_ARL = 370.0


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


@dataclass
class RecordResult:
    """Outcome of one ``Monitor.record()`` call, plus a flag proving the
    call returned control to the caller."""

    outcome: MonitoringResult
    program_continued: bool


# --- Base fixtures ------------------------------------------------------------------


@pytest.fixture
def artefact() -> FittedShewhart:
    """Default fitted artefact -- every scenario in this file uses Shewhart,
    which needs no accumulation to signal."""
    return _fitted_shewhart()


@pytest.fixture
def receivers() -> list[Callable[[MonitoringResult], None]]:
    """Every scenario in this file exercises the built-in log receiver."""
    return [log_receiver]


@pytest.fixture
def monitor(
    artefact: FittedShewhart,
    receivers: list[Callable[[MonitoringResult], None]],
) -> Monitor:
    return Monitor(artefact, receivers=receivers)


# --- Given: arranging for drift signals to be logged (SC1, SC2, SC5) ---------------


@given("the engineer has arranged for drift signals to be logged")
def arranged_for_drift_signals_to_be_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)


# --- Given: the observation (breaching or in-control) -------------------------------


@given(
    "a newly recorded observation represents a genuine departure from the process "
    "the baseline describes",
    target_fixture="phase_ii_observation",
)
def a_breaching_observation(artefact: FittedShewhart) -> ScoringResult:
    breach_score = artefact.ucl + 100.0 * artefact.sigma_estimate
    return _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=breach_score,
    )


@given(
    "a newly recorded observation's value falls within the calibrated boundaries",
    target_fixture="phase_ii_observation",
)
def an_in_control_observation(artefact: FittedShewhart) -> ScoringResult:
    return _result(
        model_version=artefact.provenance_model_version,
        criteria=artefact.provenance_criteria,
        score=artefact.baseline_mean,
    )


# --- When: the shared single-observation recording step -----------------------------


@when("they record that observation", target_fixture="record_result")
def record_the_observation(
    monitor: Monitor, phase_ii_observation: ScoringResult
) -> RecordResult:
    outcome = monitor.record(phase_ii_observation)
    return RecordResult(outcome=outcome, program_continued=True)


# --- Then: SC1 -- a log entry with full signal content -------------------------------


@then(
    "they see a log entry that identifies the direction of the departure, the "
    "calibrated boundaries that were in force, and the observation that triggered it"
)
def sees_a_log_entry_with_full_signal_content(
    caplog: pytest.LogCaptureFixture, record_result: RecordResult
) -> None:
    assert len(caplog.records) == 1
    extra = _extra(caplog.records[0])
    outcome = record_result.outcome
    assert extra.caliper_direction == outcome.direction
    assert extra.caliper_fitted_artefact == outcome.fitted_artefact
    assert extra.caliper_observation_score == outcome.observation.score


# --- Then: SC2 -- no log entry for routine observations -------------------------------


@then("no log entry is produced for that observation")
def no_log_entry_is_produced(caplog: pytest.LogCaptureFixture) -> None:
    assert caplog.records == []


# --- Scenario: SC3 -- respects the engineer's own logging configuration ---------------


@given(
    "the engineer has configured their application's own logging destination and "
    "format",
    target_fixture="custom_log_stream",
)
def engineer_configured_own_logging_destination() -> Generator[io.StringIO]:
    logger = logging.getLogger(_LOGGER_NAME)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("CUSTOM|%(levelname)s|%(message)s"))
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)


@when(
    "a drift signal is logged as a result of recording that observation",
    target_fixture="record_result",
)
def a_drift_signal_is_logged_as_a_result_of_recording(
    monitor: Monitor, phase_ii_observation: ScoringResult
) -> RecordResult:
    outcome = monitor.record(phase_ii_observation)
    return RecordResult(outcome=outcome, program_continued=True)


@then(
    "it appears through that same destination and format, with no separate logging "
    "system to configure"
)
def appears_through_the_same_destination_and_format(
    custom_log_stream: io.StringIO,
) -> None:
    output = custom_log_stream.getvalue()
    assert output.startswith("CUSTOM|WARNING|")


# --- Scenario: SC4 -- visible with zero additional configuration ----------------------


@given(
    "the engineer has arranged for drift signals to be logged but has not "
    "configured any additional destination for their application's own logs"
)
def arranged_but_no_additional_destination_configured(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Declares ``capsys`` even though this step never reads it.

    ``pytest_bdd``'s ``_execute_step_function`` resolves each step's
    fixtures via ``request.getfixturevalue()`` only when that step
    actually runs (``pytest_bdd/scenario.py``), not once upfront for the
    whole scenario the way a plain pytest test function's parameters are.
    ``capsys`` is otherwise requested for the first time by the ``Then``
    step below, which runs *after* the shared ``When`` step (``record the
    observation``) has already emitted through ``logging.lastResort`` to
    the *original*, not-yet-captured ``sys.stderr`` -- so the later
    ``capsys.readouterr()`` would see nothing, even though the emission
    genuinely happened (visible only in pytest's own global capture, not
    in ``capsys``'s per-fixture buffer). Requesting ``capsys`` here forces
    its stdout/stderr redirection to begin before the ``When`` step runs,
    so the ``Then`` step's ``capsys.readouterr()`` actually observes the
    zero-configuration output SC4 asserts.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    monkeypatch.setattr(logger, "propagate", False)


@then(
    "they still see the log entry through Python's own default logging behaviour, "
    "without needing extra configuration"
)
def still_sees_the_log_entry_via_default_behaviour(
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured = capsys.readouterr()
    assert captured.err != ""


# --- Scenario: SC5 -- multiple signals logged independently, in order -----------------


@given(
    "they record more than one observation that each represents a genuine "
    "departure from the process",
    target_fixture="phase_ii_observations",
)
def multiple_breaching_observations(
    artefact: FittedShewhart,
) -> list[ScoringResult]:
    breach_scores = [
        artefact.ucl + 10.0 * artefact.sigma_estimate,
        artefact.ucl + 20.0 * artefact.sigma_estimate,
        artefact.lcl - 10.0 * artefact.sigma_estimate,
    ]
    return [
        _result(
            model_version=artefact.provenance_model_version,
            criteria=artefact.provenance_criteria,
            score=score,
        )
        for score in breach_scores
    ]


@when(
    "those observations are recorded, one after another",
    target_fixture="record_results",
)
def record_observations_in_sequence(
    monitor: Monitor, phase_ii_observations: list[ScoringResult]
) -> list[MonitoringResult]:
    return [monitor.record(observation) for observation in phase_ii_observations]


@then("each signal produces its own log entry, in the order the signals occurred")
def each_signal_produces_its_own_log_entry_in_order(
    caplog: pytest.LogCaptureFixture, record_results: list[MonitoringResult]
) -> None:
    assert len(caplog.records) == len(record_results)
    assert [_extra(r).caliper_direction for r in caplog.records] == [
        outcome.direction for outcome in record_results
    ]


# --- Scenario: SC6 -- a logging failure does not prevent completion -------------------


@given(
    "the engineer has arranged for drift signals to be logged, and logging is not "
    "currently able to succeed"
)
def arranged_for_logging_but_logging_cannot_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_on_write(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(logging.Logger, "warning", _raise_on_write)


@then(
    "the recording call still completes and returns the signal determination as normal"
)
def recording_call_still_completes(record_result: RecordResult) -> None:
    assert record_result.outcome.is_in_control is False


@then(
    "the engineer can determine, through Caliper's public interface, both that the "
    "signal could not be logged and why"
)
def engineer_can_determine_the_signal_could_not_be_logged_and_why(
    record_result: RecordResult,
) -> None:
    assert len(record_result.outcome.delivery_failures) == 1
    failure = record_result.outcome.delivery_failures[0]
    assert isinstance(failure.error_type, str)
    assert failure.error_type != ""
    assert isinstance(failure.error_message, str)
    assert failure.error_message != ""


@then("that information does not depend on the logging mechanism that just failed")
def information_does_not_depend_on_the_logging_mechanism(
    record_result: RecordResult,
) -> None:
    """Does not assert anything about log *output* -- that would presuppose
    the very mechanism that failed (the feature file's own comment). The
    failure surfaces on the public result instead
    (``tests/unit/monitoring/test_log_receiver.py``'s
    ``test_a_logging_failure_surfaces_via_delivery_failures_not_the_log_itself``
    is the test that actually proves this at the unit level).
    """
    failure = record_result.outcome.delivery_failures[0]
    assert failure.receiver != ""
