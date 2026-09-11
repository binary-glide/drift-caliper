"""Runs the BIN-76 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/drift_signal_log_handler_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.drift_signal_log_handler_steps import *  # noqa: F403

scenarios("monitoring/drift-signal-log-handler.feature")
