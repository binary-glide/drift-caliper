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

_TESTS = Path(__file__).resolve().parents[1]
_THIS_FILE = Path(__file__).resolve()
_CLOCKS = frozenset(
    {"monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns", "time"}
)


def _reads_a_clock(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _CLOCKS
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        ):
            return True
        if isinstance(func, ast.Name) and func.id in _CLOCKS - {"time"}:
            return True
    return False


def _is_wall_clock_mark(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr == "wall_clock"


def _classify() -> tuple[set[str], set[str]]:
    """Return (tests reading a clock, tests carrying the marker) as node ids."""
    reading, marked = set(), set()
    for path in sorted(_TESTS.rglob("test_*.py")):
        if path.resolve() == _THIS_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(_TESTS.parent).as_posix()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_marked = any(_is_wall_clock_mark(d) for d in node.decorator_list)
                for item in node.body:
                    if isinstance(
                        item, ast.FunctionDef | ast.AsyncFunctionDef
                    ) and item.name.startswith("test"):
                        node_id = f"{relative}::{node.name}::{item.name}"
                        if _reads_a_clock(item):
                            reading.add(node_id)
                        if class_marked or any(
                            _is_wall_clock_mark(d) for d in item.decorator_list
                        ):
                            marked.add(node_id)
            elif isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef
            ) and node.name.startswith("test"):
                node_id = f"{relative}::{node.name}"
                if _reads_a_clock(node):
                    reading.add(node_id)
                if any(_is_wall_clock_mark(d) for d in node.decorator_list):
                    marked.add(node_id)
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
