"""Runs the BIN-63 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/phase_i_baseline_collection_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.phase_i_baseline_collection_steps import *  # noqa: F403

scenarios("baseline/phase-i-baseline-collection.feature")
