"""Runs the BIN-133 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/bernoulli_cusum_control_limit_fitting_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.bernoulli_cusum_control_limit_fitting_steps import *  # noqa: F403

scenarios("baseline/bernoulli-cusum-control-limit-fitting.feature")
