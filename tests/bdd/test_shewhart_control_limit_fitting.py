"""Runs the BIN-95 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/shewhart_control_limit_fitting_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.shewhart_control_limit_fitting_steps import *  # noqa: F403

scenarios("baseline/shewhart-control-limit-fitting.feature")
