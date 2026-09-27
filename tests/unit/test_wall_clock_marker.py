"""Tests that assert on elapsed time carry ``wall_clock``, and only they do.

ADR-015 Decision 2 and Decision 5 point 5 (BIN-155). CI runs the suite in
parallel (``-n auto --dist worksteal``), and parallel load can falsify a
measurement of how fast the library is. So a test that asserts on elapsed
time runs in a separate serial step, selected by ``-m wall_clock``. A test
that only needs to *terminate* uses ``@pytest.mark.timeout`` and stays in the
parallel run.

That split holds only if the marker is on exactly the right tests:

- a timing assertion **without** the marker runs under parallel load, where
  it can fail for a reason that is not a regression, or pass by luck;
- the marker **without** a timing assertion moves a test out of the parallel
  run for nothing.

This checks both directions by reading every test module's source (AST), so
it needs no collection run. A test "measures elapsed time" when it calls
``time.monotonic``/``time.perf_counter`` (or their ``_ns`` forms, or
``time.time``). It is the mechanised form of ADR-015 Verification item 2 ("
``-m wall_clock`` collects exactly the two elapsed-time tests").
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
_THIS_FILE = Path(__file__).resolve()
# The stdlib ``time`` functions that read a clock a test could assert against.
_CLOCKS = frozenset(
    {"monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns", "time", "time_ns"}
)


def _clock_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Resolve, for one module, the names that reach ``time``'s clocks.

    Returns ``(module_names, function_names)``: every name bound to the
    ``time`` module (``import time``, ``import time as t``) and every name
    bound to one of its clock functions (``from time import perf_counter``,
    ``... import monotonic as m``). Imports anywhere in the module count,
    including inside a function.
    """
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "time":
                    modules.add(alias.asname or "time")
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            for alias in node.names:
                if alias.name in _CLOCKS:
                    functions.add(alias.asname or alias.name)
    return modules, functions


def _reads_a_clock(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    modules: set[str],
    functions: set[str],
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _CLOCKS
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        ):
            return True
        if isinstance(func, ast.Name) and func.id in functions:
            return True
    return False


def _is_wall_clock_mark(expression: ast.expr) -> bool:
    target = expression.func if isinstance(expression, ast.Call) else expression
    return isinstance(target, ast.Attribute) and target.attr == "wall_clock"


def _module_is_marked(tree: ast.Module) -> bool:
    """A module-level ``pytestmark = pytest.mark.wall_clock`` (or a list or tuple
    containing it) marks every test in the module."""
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets
            ):
                continue
            value = node.value
            if value is None:
                continue
            marks = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
            if any(_is_wall_clock_mark(mark) for mark in marks):
                return True
    return False


def _classify_source(source: str, relative: str) -> tuple[set[str], set[str]]:
    """Return (tests reading a clock, tests carrying the marker) as node ids."""
    tree = ast.parse(source)
    modules, functions = _clock_names(tree)
    module_marked = _module_is_marked(tree)
    reading, marked = set(), set()

    def visit(
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        node_id: str,
        inherited: bool,
    ) -> None:
        if _reads_a_clock(function, modules, functions):
            reading.add(node_id)
        if inherited or any(_is_wall_clock_mark(d) for d in function.decorator_list):
            marked.add(node_id)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_marked = module_marked or any(
                _is_wall_clock_mark(d) for d in node.decorator_list
            )
            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and item.name.startswith("test"):
                    visit(item, f"{relative}::{node.name}::{item.name}", class_marked)
        elif isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef
        ) and node.name.startswith("test"):
            visit(node, f"{relative}::{node.name}", module_marked)
    return reading, marked


def _classify() -> tuple[set[str], set[str]]:
    """Classify every test module under ``tests/`` except this one."""
    reading, marked = set(), set()
    for path in sorted(_TESTS.rglob("test_*.py")):
        if path.resolve() == _THIS_FILE:
            continue
        relative = path.relative_to(_TESTS.parent).as_posix()
        module_reading, module_marked = _classify_source(
            path.read_text(encoding="utf-8"), relative
        )
        reading |= module_reading
        marked |= module_marked
    return reading, marked


def test_every_test_that_reads_a_clock_carries_the_marker() -> None:
    reading, marked = _classify()

    assert reading - marked == set(), (
        "these tests assert on elapsed time but would run under parallel load; "
        "mark them @pytest.mark.wall_clock (ADR-015 Decision 2)"
    )


def test_only_tests_that_read_a_clock_carry_the_marker() -> None:
    reading, marked = _classify()

    assert marked - reading == set(), (
        "these tests carry @pytest.mark.wall_clock without measuring time; a "
        "hang guard uses @pytest.mark.timeout and stays in the parallel run"
    )


def test_exactly_the_two_elapsed_time_tests_are_marked() -> None:
    """ADR-015 Decision 2 names them; a search on 2026-09-27 found no others."""
    _, marked = _classify()

    assert marked == {
        "tests/unit/baseline/test_bernoulli_cusum_two_sided_refusal.py::"
        "TestEqualSplitBound::test_refusal_completes_within_the_measured_budget",
        "tests/unit/baseline/test_bernoulli_cusum_lattice_fix.py::"
        "TestBoundedTimeWorstCorner::"
        "test_worst_corner_completes_or_raises_within_budget",
    }


# ---------------------------------------------------------------------------
# Power: every known evasion must be caught (code review, BIN-155)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "from time import perf_counter as clock\n"
        "def test_x():\n    start = clock()\n    assert clock() - start < 1\n",
        "from time import monotonic as m\ndef test_x():\n    assert m() > 0\n",
        "import time as t\ndef test_x():\n    assert t.perf_counter() > 0\n",
        "def test_x():\n    import time\n    assert time.monotonic_ns() > 0\n",
        "from time import perf_counter\n"
        "class TestX:\n    def test_x(self):\n        assert perf_counter() > 0\n",
    ],
    ids=[
        "from_import_aliased",
        "from_import_aliased_monotonic",
        "module_aliased",
        "import_inside_the_test",
        "unaliased_in_a_class",
    ],
)
def test_a_timing_test_is_detected_however_it_imports_the_clock(source: str) -> None:
    reading, marked = _classify_source(source, "fixture.py")

    assert reading, "the clock read was not detected"
    assert reading - marked == reading


@pytest.mark.parametrize(
    "mark",
    [
        "pytestmark = pytest.mark.wall_clock",
        "pytestmark = [pytest.mark.slow, pytest.mark.wall_clock]",
        "pytestmark: object = (pytest.mark.wall_clock,)",
    ],
    ids=["single", "list", "annotated_tuple"],
)
def test_a_module_level_pytestmark_marks_every_test(mark: str) -> None:
    source = (
        f"import pytest\nimport time as t\n{mark}\n"
        "def test_a():\n    assert t.monotonic() > 0\n"
        "class TestB:\n    def test_b(self):\n        assert t.monotonic() > 0\n"
    )

    reading, marked = _classify_source(source, "fixture.py")

    assert reading == marked == {"fixture.py::test_a", "fixture.py::TestB::test_b"}


def test_an_unrelated_name_is_not_mistaken_for_a_clock() -> None:
    """``monotonic`` or ``time`` that does not come from the ``time`` module is
    not a clock read -- the check resolves imports rather than matching names."""
    source = (
        "from datetime import time\n"
        "def monotonic():\n    return 1\n"
        "def test_x():\n    assert monotonic() == 1 and time(1) is not None\n"
    )

    reading, _ = _classify_source(source, "fixture.py")

    assert reading == set()
