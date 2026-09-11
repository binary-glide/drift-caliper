"""Unit tests for the built-in log receiver (BIN-76) -- ADR-010 section 6.

Pins the six acceptance scenarios in
``tests/bdd/features/monitoring/drift-signal-log-handler.feature`` at the
unit level. See ``docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md``
section 6 and ``docs/domain-model.md`` Glossary -- ``log_receiver``.

``caliper.monitoring.log_receiver`` does not exist yet -- importing it fails
until ``domain-implementer`` adds it. That ``ImportError`` is the correct
red state for this ticket (TDD red phase).

A prior pass of this file flagged a Gherkin syntax defect in
``drift-signal-log-handler.feature`` shared with BIN-75's own file (a
step's text wrapped onto a second, un-keyworded physical line -- invalid
under pytest-bdd 8.1.0's grammar, breaking all six scenarios' collection,
not only the affected one). That defect was the coordinator's own and has
since been fixed (commit ``a686f63``) -- the file now parses cleanly (6
scenarios), verified directly with ``pytest_bdd.parser.FeatureParser``.
``tests/bdd/test_drift_signal_log_handler.py`` now runs these scenarios
against ``tests/bdd/steps/drift_signal_log_handler_steps.py`` -- all six
bind without a missing-step error (confirmed with a temporary in-process
stub for ``log_receiver``, since the real one does not exist until
``domain-implementer`` runs). This unit-test file remains the primary
place BIN-76's acceptance behaviour is pinned, with the BDD layer wired up
alongside it.

**Decisions this file makes, flagged rather than guessed silently:**

1. **`WARNING` is asserted directly on the captured `logging.LogRecord`'s
   `levelno`** (``caplog``), per this agent's brief: a regression to
   ``INFO``/``DEBUG`` would break Python's zero-configuration visibility
   guarantee (``logging.lastResort`` only surfaces `WARNING`+), and a test
   that only checked *content* at whatever level the record happened to
   land on would not catch that regression.
2. **The zero-configuration scenario (SC4) is tested by actually removing
   configuration**, not merely asserting the level in isolation. `caplog`
   itself installs a capturing handler for the test session, which would
   make a "no handler configured anywhere" claim untestable by simply
   using `caplog` -- so
   ``test_log_receiver_is_visible_with_zero_additional_logging_configuration``
   below strips ``"caliper.monitoring"``'s own handlers and sets
   ``propagate = False`` (isolating it from pytest's own root-logger
   capture handler, which `caplog` installs independent of whether a given
   test requests the fixture) and reads real process ``stderr`` via
   `capsys` -- the actual mechanism `logging.lastResort` uses. This is the
   test that would catch a level regression that every other, `caplog`-based
   test in this file would not.
3. **The logging-failure scenario (SC6/OQ-1) patches `logging.Logger.warning`
   directly** rather than a `log_receiver`-internal path, since the
   internal module `log_receiver` will live in is not yet known (not
   implemented). Patching the stdlib method every `Logger` instance shares
   is implementation-path-agnostic and mirrors the feature file's own
   framing ("logging is not currently able to succeed") without presuming
   *how* `log_receiver` calls the standard library.
"""

from __future__ import annotations

import io
import logging
from typing import Protocol, cast

import pytest
from pytest_mock import MockerFixture

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


def _breach_score(artefact: FittedShewhart) -> float:
    return artefact.ucl + 100.0 * artefact.sigma_estimate


# --- SC1: a log entry identifies direction, boundaries, and observation ----------


def test_log_receiver_logs_a_warning_level_entry_with_structured_signal_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A drift signal produces exactly one WARNING-level entry carrying the
    full signal content via `extra=` -- direction, the fitted artefact
    (calibrated boundaries), and the triggering observation's score.
    """
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[log_receiver])

    # Act
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        outcome = monitor.record(_result(score=_breach_score(artefact)))

    # Assert
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.name == _LOGGER_NAME
    extra = _extra(record)
    assert extra.caliper_chart_type == outcome.chart_type
    assert extra.caliper_direction == outcome.direction
    assert extra.caliper_observation_score == outcome.observation.score
    assert extra.caliper_fitted_artefact == outcome.fitted_artefact


# --- SC2: routine observations produce no log entry --------------------------------


def test_no_log_entry_for_a_routine_in_control_observation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No signal, no log noise -- `log_receiver` is only invoked on a signal."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[log_receiver])

    # Act
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        monitor.record(_result(score=artefact.baseline_mean))

    # Assert
    assert caplog.records == []


# --- SC3: respects the engineer's own logging configuration ------------------------


def test_logged_signal_appears_through_the_engineers_own_handler_and_formatter() -> (
    None
):
    """A signal is delivered through whatever handler/formatter the engineer
    has attached to `"caliper.monitoring"` -- no Caliper-owned destination."""
    # Arrange
    logger = logging.getLogger(_LOGGER_NAME)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("CUSTOM|%(levelname)s|%(message)s"))
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[log_receiver])

    # Act
    try:
        monitor.record(_result(score=_breach_score(artefact)))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)

    # Assert -- the engineer's own format string governed the output
    output = stream.getvalue()
    assert output.startswith("CUSTOM|WARNING|")


# --- SC4: visible with zero additional configuration --------------------------------


def test_log_receiver_is_visible_with_zero_additional_logging_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """🚨 Critical: `WARNING` is required, not stylistic.

    Python's `logging.lastResort` only surfaces `WARNING`+ output with zero
    configuration anywhere in the logger hierarchy. `"caliper.monitoring"`'s
    handlers are stripped and `propagate` is set to `False` (isolating it
    from pytest's own root-logger capture handler, which is installed
    independently of whether a test requests `caplog`) so `logging.
    lastResort` is genuinely what produces the visible output here -- a
    level regression to `INFO`/`DEBUG` would make this test fail where a
    `caplog`-based test (which explicitly sets the capture level) would not.
    """
    # Arrange
    logger = logging.getLogger(_LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.handlers = []
    logger.level = logging.NOTSET
    logger.propagate = False
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[log_receiver])

    # Act
    try:
        monitor.record(_result(score=_breach_score(artefact)))
    finally:
        logger.handlers = original_handlers
        logger.level = original_level
        logger.propagate = original_propagate

    # Assert -- logging.lastResort writes WARNING+ to stderr with no config
    captured = capsys.readouterr()
    assert captured.err != ""


# --- SC5: multiple signals logged independently, in order --------------------------


def test_multiple_signals_produce_independent_log_entries_in_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each signal in a session gets its own log entry, in recording order."""
    # Arrange
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[log_receiver])
    breach_scores = [
        artefact.ucl + 10.0 * artefact.sigma_estimate,
        artefact.ucl + 20.0 * artefact.sigma_estimate,
        artefact.lcl - 10.0 * artefact.sigma_estimate,
    ]

    # Act
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        outcomes = [monitor.record(_result(score=score)) for score in breach_scores]

    # Assert
    assert len(caplog.records) == 3
    assert [_extra(r).caliper_direction for r in caplog.records] == [
        outcome.direction for outcome in outcomes
    ]


# --- SC6 / shared OQ-1: a logging failure does not prevent completion --------------


def test_a_logging_failure_surfaces_via_delivery_failures_not_the_log_itself(
    mocker: MockerFixture,
) -> None:
    """`log_receiver` gets no special-casing (ADR-010 §6): a failure inside
    it is caught by `Monitor`'s own generic per-receiver `try`/`except`,
    exactly like any other receiver. The failure surfaces on the PUBLIC
    result, never by attempting to log the failure through the same
    logging call that just failed -- this test deliberately does not
    inspect log output, matching the feature file's own comment: "Does
    not assert the failure appears in the log -- that would presuppose
    the very mechanism that failed."
    """
    # Arrange -- simulate "logging is not currently able to succeed"
    mocker.patch.object(logging.Logger, "warning", side_effect=OSError("disk full"))
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[log_receiver])

    # Act -- must not raise
    outcome = monitor.record(_result(score=_breach_score(artefact)))

    # Assert -- recording still completed normally, and the failure is public
    assert outcome.is_in_control is False
    assert len(outcome.delivery_failures) == 1
    failure = outcome.delivery_failures[0]
    assert failure.error_type == "OSError"
    assert failure.error_message == "disk full"


# --- DX surface: importability -----------------------------------------------------


def test_log_receiver_is_importable_from_caliper_monitoring() -> None:
    """`caliper.monitoring.log_receiver` -- the DX snippet ADR-010 §6 commits to."""
    assert callable(log_receiver)


def test_log_receiver_is_usable_directly_as_a_signal_receiver() -> None:
    """`log_receiver` satisfies the plain `SignalReceiver` shape -- no special
    wiring beyond passing it in `receivers=[...]` (ADR-010 §6)."""
    artefact = _fitted_shewhart()
    monitor = Monitor(artefact, receivers=[log_receiver])

    # Must not raise -- log_receiver is just another configured receiver
    outcome: MonitoringResult = monitor.record(_result(score=_breach_score(artefact)))

    assert outcome.is_in_control is False
