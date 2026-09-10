"""Runs the BIN-68 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/provenance_mismatch_between_phases_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.provenance_mismatch_between_phases_steps import *  # noqa: F403

scenarios("baseline/provenance-mismatch-between-phases.feature")
