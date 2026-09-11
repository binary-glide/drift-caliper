"""Runs the BIN-75 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/out_of_control_signal_event_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.out_of_control_signal_event_steps import *  # noqa: F403

scenarios("monitoring/out-of-control-signal-event.feature")
