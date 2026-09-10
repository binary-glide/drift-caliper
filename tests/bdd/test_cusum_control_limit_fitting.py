"""Runs the BIN-94 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/cusum_control_limit_fitting_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.cusum_control_limit_fitting_steps import *  # noqa: F403

scenarios("baseline/cusum-control-limit-fitting.feature")
