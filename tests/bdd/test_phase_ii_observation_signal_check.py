"""Runs the BIN-69 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/phase_ii_observation_signal_check_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.phase_ii_observation_signal_check_steps import *  # noqa: F403

scenarios("monitoring/phase-ii-observation-signal-check.feature")
