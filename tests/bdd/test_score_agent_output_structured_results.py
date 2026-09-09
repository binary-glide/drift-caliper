"""Runs the BIN-59 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/score_agent_output_structured_results_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.score_agent_output_structured_results_steps import *  # noqa: F403

scenarios("measurement/score-agent-output-structured-results.feature")
