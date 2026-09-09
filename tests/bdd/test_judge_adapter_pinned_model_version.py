"""Runs the BIN-57 BDD scenarios against their step definitions.

Step implementations live in
``tests/bdd/steps/judge_adapter_pinned_model_version_steps.py``.
"""

from pytest_bdd import scenarios

from tests.bdd.steps.judge_adapter_pinned_model_version_steps import *  # noqa: F403

scenarios("measurement/judge-adapter-pinned-model-version.feature")
