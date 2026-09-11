"""Runs the BIN-72 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/in_memory_observation_store_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.in_memory_observation_store_steps import *  # noqa: F403

scenarios("monitoring/in-memory-observation-store.feature")
