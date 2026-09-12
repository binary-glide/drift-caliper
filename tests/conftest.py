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
from beartype.claw import beartype_package

# --- beartype: dev-only runtime type enforcement (BIN-109) --------------------
#
# Applied here rather than in ``src/`` on purpose. ``beartype`` is a dev
# dependency, so the shipped wheel imports it nowhere and consumers inherit
# nothing. The import hook instruments the package at import time, which is why
# it must run before anything imports ``caliper``.
#
# What it buys, concretely: ``mypy --strict`` covers ``src/``, but there are two
# places where it is explicitly silenced -- ``# type: ignore[attr-defined]`` on
# the ``scipy.stats.norm`` import and ``# type: ignore[no-untyped-call]`` on the
# ``brentq`` call, both in ``ewma_numerics.py``. scipy is largely untyped, so
# those are holes in static coverage: the annotation claims ``float`` and
# nothing verifies it. beartype checks at runtime exactly what mypy was told to
# stop checking. BIN-94's Siegmund approximation adds more scipy calls and more
# such holes.
#
# ⚠️ Scoped to individual entry-point-free modules deliberately, and it must
# never be widened to a package whose public entry points engineers call.
# beartype raises ``BeartypeCallHintParamViolation``, which is **not** a
# ``CaliperError`` -- no ``category``, no ``context`` to branch on. Guarding a
# public boundary would replace the typed exception ADR-002 requires and break
# the six merged feature files asserting on it. Catching and translating it
# does not work either: the violation carries prose rather than structure, so
# ``missing_fields`` cannot be recovered from it. See BIN-109.
beartype_package("caliper.baseline.domain.ewma_numerics")

# ``spc_numerics`` (hoisted during BIN-94) and ``ewma_numerics`` (split out of
# ``ewma_fitting`` during BIN-130) have no public entry point at all -- their
# only callers are other domain modules, never an engineer -- so both are the
# clean case: nothing above needs weighing, because there is no public
# boundary in either to guard by accident.
#
# ``ewma_fitting`` (which now holds only ``fit_ewma`` and its parameter
# validation), ``cusum_fitting`` and ``shewhart_fitting`` are deliberately NOT
# hooked: each contains a public entry point.
#
# ⚠️ Until BIN-130, ``fit_ewma`` **was** hooked, unavoidably --
# ``beartype_package`` takes a module, and ``fit_ewma`` shared a file
# (``ewma_fitting.py``) with these numerics. BIN-109 accepted that after
# checking it displaced nothing at the time: ``fit_ewma`` already leaked
# ``AttributeError`` on a wrong-typed baseline before beartype existed, so no
# typed exception was replaced (unlike ``Baseline.record``, which has one --
# hooking its package broke five tests). That premise expired the moment
# BIN-126 gave ``fit_ewma`` a guard to displace -- a guard added to a hooked
# ``fit_ewma`` was pre-empted by ``BeartypeCallHintParamViolation`` before its
# body ever ran, unreachable inside this suite even though it worked in the
# shipped wheel, which never imports beartype. BIN-130 split
# ``caliper.baseline.domain.ewma_numerics`` out of ``ewma_fitting`` specifically
# so this hook could stop covering ``fit_ewma`` while still covering the scipy
# calls it exists for. **Do not read the surviving numerics hook as a
# precedent for hooking a boundary that does raise properly** -- it is hooked
# because it has no boundary to guard, not despite having one.
beartype_package("caliper.baseline.domain.spc_numerics")


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
