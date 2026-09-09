"""Runs the BIN-58 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/scoring_criteria_text_rubric_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.scoring_criteria_text_rubric_steps import *  # noqa: F403

scenarios("measurement/scoring-criteria-text-rubric.feature")
