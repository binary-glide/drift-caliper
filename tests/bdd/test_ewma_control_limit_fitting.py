"""Runs the BIN-65 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/ewma_control_limit_fitting_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.ewma_control_limit_fitting_steps import *  # noqa: F403

scenarios("baseline/ewma-control-limit-fitting.feature")
