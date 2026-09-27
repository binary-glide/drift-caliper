"""Every dependency list in ``pyproject.toml`` is alphabetical by normalised name.

ADR-015 Decision 4 (BIN-155). Purpose-grouping decayed within a day of being
relied on (``pytest-timeout`` landed at the end of ``dev``), so the rule is
now mechanical, and this test enforces it rather than a reviewer.

**Scope.** ``[project].dependencies`` and every list under
``[dependency-groups]`` (``dev``, ``docs``, and any group added later). Each
list is sorted on its own.

**Sort key.** The distribution name normalised per PEP 503: lowercase, every
run of ``-``, ``_`` or ``.`` collapsed to ``-``. The name is the leading
``[A-Za-z0-9][A-Za-z0-9._-]*`` of the requirement string, before any extra,
specifier, marker or URL. The key compares as a plain string, so ``pytest``
sorts before ``pytest-bdd``, and ``mkdocs`` before ``mkdocs-material`` before
``mkdocstrings``: ``-`` (0x2D) sorts below letters.

**Failures.**
- An entry out of place is reported with the list name and the first entry
  out of place, because the fix is to move that line.
- Two entries with the same normalised name are a duplicate. That is a failure
  in its own right, not a sort question.
- A non-string entry (for example a PEP 735 ``{include-group = ...}`` table)
  fails loudly rather than being skipped, so whoever adds the first one
  decides where it sorts.

**Stdlib only** (``tomllib`` plus a regex). ``packaging`` is only a transitive
dependency of pytest, and a test must not lean on an undeclared import.

**Power checks** (ADR-015 Decision 4 and Verification item 4): the tests at
the end run this same check against copies of the real ``pyproject.toml``
with one entry moved, one duplicated and one non-string entry added, and
require each to fail, naming the list.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SEPARATORS = re.compile(r"[-_.]+")


def _normalised_name(requirement: str) -> str:
    """PEP 503's normalised distribution name of a requirement string."""
    match = _NAME.match(requirement.strip())
    if match is None:
        raise ValueError(f"no distribution name at the start of {requirement!r}")
    return _SEPARATORS.sub("-", match.group(0)).lower()


def _dependency_lists(document: dict[str, Any]) -> dict[str, list[Any]]:
    """Every list in scope, keyed by a name that says where it lives."""
    lists: dict[str, list[Any]] = {
        "[project].dependencies": document.get("project", {}).get("dependencies", [])
    }
    for group, entries in document.get("dependency-groups", {}).items():
        lists[f"[dependency-groups].{group}"] = entries
    return lists


def _order_violation(list_name: str, entries: list[Any]) -> str | None:
    """Describe the first problem with one list, or ``None`` if it is in order."""
    names: list[str] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, str):
            return (
                f"{list_name}: entry {position} is {entry!r}, not a requirement "
                "string -- decide where it sorts and extend this test"
            )
        name = _normalised_name(entry)
        if name in names:
            return f"{list_name}: {name!r} appears twice"
        names.append(name)
    for position, (name, expected) in enumerate(zip(names, sorted(names), strict=True)):
        if name != expected:
            return (
                f"{list_name}: entry {position} is {entries[position]!r}; "
                f"{expected!r} belongs there -- move that line"
            )
    return None


def _violations(pyproject_text: str) -> list[str]:
    lists = _dependency_lists(tomllib.loads(pyproject_text))
    found = (_order_violation(name, entries) for name, entries in lists.items())
    return [violation for violation in found if violation is not None]


_LISTS = _dependency_lists(tomllib.loads(_PYPROJECT.read_text(encoding="utf-8")))


@pytest.mark.parametrize("list_name", list(_LISTS))
def test_every_dependency_list_is_sorted_by_normalised_name(list_name: str) -> None:
    """ADR-015 Decision 4, on the real file."""
    assert _order_violation(list_name, _LISTS[list_name]) is None


def test_the_scope_includes_every_list() -> None:
    """The rule covers the runtime list and every dependency group, including
    groups added after this test was written."""
    assert "[project].dependencies" in _LISTS
    assert {"[dependency-groups].dev", "[dependency-groups].docs"} <= set(_LISTS)


# ---------------------------------------------------------------------------
# The sort key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("numpy>=2.0", "numpy"),
        ("pytest-bdd>=8.1", "pytest-bdd"),
        ("factory_boy>=3.3", "factory-boy"),
        ("Zope.Interface[docs]>=5 ; python_version >= '3.11'", "zope-interface"),
        ("foo--_.bar @ https://example.invalid/foo.whl", "foo-bar"),
        ("  ruff>=0.16.7", "ruff"),
    ],
)
def test_the_key_is_the_pep_503_normalised_name(
    requirement: str, expected: str
) -> None:
    assert _normalised_name(requirement) == expected


def test_a_hyphenated_name_sorts_after_its_prefix_and_before_longer_words() -> None:
    """``-`` sorts below letters: ``mkdocs < mkdocs-material < mkdocstrings``."""
    entries = ["mkdocs>=1", "mkdocs-material>=9", "mkdocstrings>=1", "pytest>=9"]

    assert _order_violation("docs", entries) is None
    assert _order_violation("docs", list(reversed(entries))) is not None


# ---------------------------------------------------------------------------
# Power checks: the real file, broken three ways, must fail (Decision 4)
# ---------------------------------------------------------------------------


def _real_text() -> str:
    return _PYPROJECT.read_text(encoding="utf-8")


def _with_docs_list(replacement: str) -> str:
    """The real file with its ``docs`` group replaced, everything else intact."""
    text = _real_text()
    start = text.index("docs = [")
    end = text.index("]", start) + 1
    return text[:start] + replacement + text[end:]


_SORTED_DOCS = """docs = [
  "mkdocs>=1.6.1",
  "mkdocs-material>=9.7.7",
  "mkdocstrings>=1.0.6",
  "mkdocstrings-python>=2.0.8",
]"""


def test_power_check_the_docs_group_baseline_is_clean() -> None:
    """Premise for the three checks below: with a sorted ``docs`` group, no
    violation is reported for it, so any failure they see is the one they
    inject."""
    violations = _violations(_with_docs_list(_SORTED_DOCS))

    assert not [v for v in violations if v.startswith("[dependency-groups].docs")]


def test_power_check_a_moved_entry_fails_naming_its_list() -> None:
    moved = _SORTED_DOCS.replace(
        '  "mkdocs>=1.6.1",\n  "mkdocs-material>=9.7.7",\n',
        '  "mkdocs-material>=9.7.7",\n  "mkdocs>=1.6.1",\n',
    )

    violations = _violations(_with_docs_list(moved))

    assert any(
        v.startswith("[dependency-groups].docs: entry 0")
        and "'mkdocs-material>=9.7.7'" in v
        for v in violations
    ), violations


def test_power_check_a_duplicate_fails() -> None:
    duplicated = _SORTED_DOCS.replace(
        '  "mkdocs>=1.6.1",\n', '  "mkdocs>=1.6.1",\n  "MkDocs>=1.7",\n'
    )

    violations = _violations(_with_docs_list(duplicated))

    assert any(
        v.startswith("[dependency-groups].docs") and "appears twice" in v
        for v in violations
    ), violations


def test_power_check_a_non_string_entry_fails() -> None:
    with_table = _SORTED_DOCS.replace(
        '  "mkdocs>=1.6.1",\n', '  "mkdocs>=1.6.1",\n  { include-group = "dev" },\n'
    )

    violations = _violations(_with_docs_list(with_table))

    assert any(
        v.startswith("[dependency-groups].docs") and "not a requirement string" in v
        for v in violations
    ), violations
