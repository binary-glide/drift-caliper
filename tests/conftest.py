"""Shared pytest configuration for the whole suite.

Caliper is a library with no HTTP layer, no database, and no async
surface (see the repo's ``CLAUDE.md``), so most of the fixtures
``test-patterns/references/python.md`` describes for a FastAPI service
(``db_session``, ``client``, cache/Redis fakes) do not apply here.

What this file owns: auto-applying the ``unit`` marker declared in
``pyproject.toml`` to every test under ``tests/unit/`` -- the marker
existed but nothing applied it, so ``pytest -m unit`` silently selected
nothing.

An earlier version of this file also defined ``fake_provider`` and
``configured_judge`` fixtures wrapping ``FakeJudgeProviderPort`` and
``tests.factories.JudgeFactory``. They were removed: every current unit
test needs to configure a specific ``response`` or ``error_to_raise`` at
construction time to exercise the scenario under test, so a generic
pre-built fixture had no real caller and would have been decoration, not
infrastructure. ``tests/factories.py`` is not dead code for the same
reason it is not used here yet -- see its module docstring.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark every test collected from ``tests/unit/`` as ``unit``.

    ``tests/bdd/`` is deliberately left unmarked -- there is no declared
    ``bdd`` marker, and pytest-bdd's own scenario/feature structure already
    separates it from the unit suite via ``testpaths``.
    """
    del config
    for item in items:
        if "tests/unit/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.unit)
