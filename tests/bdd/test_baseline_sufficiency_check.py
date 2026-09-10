"""Runs the BIN-64 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/baseline_sufficiency_check_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.baseline_sufficiency_check_steps import *  # noqa: F403

scenarios("baseline/baseline-sufficiency-check.feature")
