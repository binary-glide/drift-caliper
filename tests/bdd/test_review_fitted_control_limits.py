"""Runs the BIN-66 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/review_fitted_control_limits_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.review_fitted_control_limits_steps import *  # noqa: F403

scenarios("baseline/review-fitted-control-limits.feature")
