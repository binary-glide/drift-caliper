"""BIN-121 (part 2) -- the exception-contract audit.

**The rule:** any exception escaping a public entry point in
``caliper.__all__`` must be a ``CaliperError`` (ADR-002/ADR-008), carrying a
non-empty ``category`` and a ``context`` mapping. The rule was already
written down -- ``CLAUDE.md``'s ``BIN-109`` note states it in as many
words. Nothing enforced it, and five separate leaks
(``BIN-104``/``ValidationError``, ``BIN-119``/``ZeroDivisionError``,
``BIN-120``/``AssertionError``, ``BIN-123``/``OverflowError``, and the
``BIN-109`` note's own beartype hypothetical) were each found by accident,
on a different ticket, over the space of a few days. This file is what
turns "we know the rule" into a gate.

See ``tests/support/exception_contract_registry.py`` for the registry this
file drives: a mapping from every name in ``caliper.__all__`` to either how
it is exercised (a tuple of :class:`HostileCase`\\s) or why it is excluded
(a stated reason, never a silent omission).

## The scoreboard -- read this line first

**18 known leaks are pinned as expected failures below, tracked as
``BIN-104`` (7), ``BIN-126`` (8) and ``BIN-127`` (3). The suite is green
today because of that pinning, not because the leaks are fixed. That
count is expected to fall to zero as each ticket closes** --
``strict=True`` (see below) means a fix silently makes its case XPASS,
which fails the suite until the now-stale marker is deleted, so the count
cannot quietly drift upward either. Anyone reading a file with 18 xfails
needs one number, not an investigation: this is the plan, not a scandal,
and it is a plan with a forcing function attached.

## Why three tickets, not one

The grouping is load-bearing -- none of the three fixes solves either of
the other two:

* **``BIN-104`` (7 cases)** -- Pydantic's core type coercion runs *before*
  a ``@field_validator``, so a wrong-*typed* constructor argument
  (``ModelVersion(value=123)``, ``Judge.create(model_version=123)``, ...)
  never reaches Caliper's own validation code at all. The fix is a
  ``mode="before"`` validator (or equivalent) on each affected model.
  ⚠️ ``Provenance`` is in scope here despite having **no field validator
  by design** (ADR-006: "there is nothing left to validate here" -- its
  invariant is structural, inherited from ``ModelVersion``/
  ``ScoringCriteria``). This ticket must add one where ADR-006
  deliberately specified none, which is exactly the kind of thing a
  targeted sweep catches and a general impression of "the value objects
  validate" does not.
* **``BIN-126`` (8 cases)** -- A wrong-typed *argument to a function or
  method* (not a Pydantic model field) fails on its first use inside the
  function body, before any Caliper validation runs: ``math.isfinite("x")``
  raises bare ``TypeError``, ``"x".check_sufficiency()`` raises bare
  ``AttributeError`` (a plain ``str`` has no such method), and
  ``beartype``'s dev-only import hook on ``ewma_fitting`` raises its own
  ``BeartypeCallHintParamViolation`` ahead of either. Three different
  leaked types, one root cause: nothing validates the argument's *type*
  before using it.
* **``BIN-127`` (3 cases)** -- An object that duck-types past an
  ``isinstance`` check but misbehaves on actual attribute access. Both
  ``Baseline.record()``/``Monitor.record()``'s duplicated
  ``_missing_observation_fields`` (``hasattr`` only swallows
  ``AttributeError``) and ``compare_provenance()`` (no guard equivalent to
  ``Monitor``'s ``_safe_repr``) read a caller-supplied object's attributes
  directly and let whatever that access raises propagate unchanged.

## A structural limit of this whole technique, stated plainly

**This audit can only see a leak that *raises* something.** It cannot see
``BIN-119``'s other half -- a non-finite ``sigma_estimate`` that
constructs a ``FittedEWMA`` *successfully* and silently produces a chart
that can never signal. No exception occurs, so there is nothing here to
catch; that "confident silence" failure mode needs a correctness
assertion against known-good output (``BIN-84``/``BIN-122`` territory),
not an exception-contract test. Keep this in view: a clean run of this
file proves the library *fails loudly* where it fails at all -- it says
nothing about whether it might instead fail *silently*.

**A second, narrower blind spot.** This audit asserts that ``category``
is truthy and ``context`` is a ``Mapping`` -- the *structure* of the
contract. It does **not** assert ADR-002's per-category **required keys**,
so a correctly-typed error raised with ``context={}`` would pass here.
That is deliberate: the required keys are per-category and are pinned by
the per-story unit tests that own each category. But it means a green run
of this file is not on its own proof that an error is *useful* to branch
on, only that it is the right type carrying the right shape.
(Raised by code-reviewer on BIN-121, 2026-09-11.)

## Verified, not merely written down: reintroducing a fixed leak is caught

``Monitor``'s ``BIN-120`` narrowing (the ``isinstance`` check in
``__init__`` plus ``_check()``'s typed fallback) was temporarily reverted
to its pre-fix shape in a local, uncommitted change. A
structurally-conforming third-party artefact then passed construction
again and raised a raw ``AssertionError`` on its first ``record()`` call
-- the exact original leak, reproduced on demand. The revert was undone in
the same turn before anything else happened -- ``git diff trunk -- src/``
is empty on this branch, every commit.

## `known_leak`, `xfail`, and why `raises=` is not decorative

Each of the 18 cases below carries a :class:`~tests.support.
exception_contract_registry.KnownLeak` on its ``HostileCase`` (ticket +
the *exact* exception type observed). ``_all_cases()`` turns that into
``pytest.mark.xfail(strict=True, raises=<that type>)``:

* **``raises=<exact type>``, not ``Exception``.** If a future change
  makes the same entry point leak a *different* foreign type, ``raises``
  will not match it, and the case fails for real rather than quietly
  staying green under a marker that no longer describes what actually
  happens. That is new information, not confirmation of the same bug --
  see each case's comment in the registry for whether a broader type
  would have been safe to assert instead (in every one of these 18, it
  would not: the specific type is exactly what distinguishes ``BIN-104``
  from ``BIN-126`` from ``BIN-127``).
* **``strict=True`` is the point, not a strictness dial.** If the
  underlying leak is fixed -- the entry point now either raises a proper
  ``CaliperError`` or does not raise at all -- the case XPASSes, and
  ``strict=True`` turns that XPASS into a suite failure. The only way to
  make the suite green again is to delete the now-stale ``known_leak``
  entry in the registry, which is what actually closes the loop back to
  the owning ticket.

## Exception types this audit does not treat as violations

``SystemExit``, ``KeyboardInterrupt`` and ``MemoryError`` are explicitly
excluded, per this ticket's own instruction. The first two are already
outside ``Exception`` in CPython (``BaseException`` direct subclasses) and
are never caught by the ``except Exception`` below regardless.
``MemoryError`` *is* an ``Exception`` subclass, so it is checked for and
re-raised before the ``CaliperError`` assertion runs -- a caller that has
exhausted memory is not a contract violation to classify, it is a
resource-exhaustion condition no typed exception can meaningfully wrap.
No other exception type is special-cased: none of the entry points audited
here can plausibly raise ``StopIteration``, ``GeneratorExit`` or
``RecursionError`` from normal operation (no generators, no unbounded
recursion anywhere in the audited call graph), so carving them out would
be speculative rather than considered -- if one ever did escape, that
would itself be worth surfacing as a failure here, not silently exempted
in advance.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest

import caliper
from caliper.errors import CaliperError
from tests.support.exception_contract_registry import EXCLUDED, EXERCISABLE

_EXCLUDED_NAMES = frozenset(entry.name for entry in EXCLUDED)
_EXERCISABLE_NAMES = frozenset(entry.name for entry in EXERCISABLE)

# Exceptions that signal a genuine runtime condition, not a contract
# violation -- see the module docstring's closing section for why each is
# excluded. Checked in an explicit tuple (not a bare `except Exception`)
# because `MemoryError` is an `Exception` subclass and would otherwise be
# swept into the CaliperError assertion below.
_NOT_CONTRACT_VIOLATIONS: tuple[type[BaseException], ...] = (MemoryError,)


def test_every_public_name_is_classified() -> None:
    """Every name in ``caliper.__all__`` is either exercisable or excluded.

    This is the meta-test the whole registry exists to make possible
    (mirrors ``BIN-124``'s
    ``test_baseline_scores_strategy_never_draws_a_baseline_the_library_rejects``):
    adding a new export to ``caliper.__all__`` without adding it to either
    registry in ``tests/support/exception_contract_registry.py`` fails
    here immediately, rather than silently shipping unaudited. Also
    guards against the opposite mistake -- a name classified in *both*
    registries, or a registry entry for a name no longer exported at all.
    """
    public_names = frozenset(caliper.__all__)

    unclassified = public_names - _EXCLUDED_NAMES - _EXERCISABLE_NAMES
    assert not unclassified, (
        f"caliper.__all__ names with no classification in "
        f"tests/support/exception_contract_registry.py: {sorted(unclassified)}. "
        "Add each to EXERCISABLE (with hostile cases) or EXCLUDED (with a "
        "stated reason)."
    )

    double_classified = _EXCLUDED_NAMES & _EXERCISABLE_NAMES
    assert not double_classified, (
        f"names classified as both exercisable and excluded: "
        f"{sorted(double_classified)} -- pick one."
    )

    stale_registry_entries = (_EXCLUDED_NAMES | _EXERCISABLE_NAMES) - public_names
    assert not stale_registry_entries, (
        f"tests/support/exception_contract_registry.py classifies names no "
        f"longer in caliper.__all__: {sorted(stale_registry_entries)} -- "
        "remove the stale entry."
    )


def _all_cases() -> list[Any]:
    """Flatten the registry into parametrize entries, marking known leaks.

    A case with no ``known_leak`` becomes a plain parameter set. A case
    with one becomes ``pytest.param(..., marks=pytest.mark.xfail(...))``
    -- see the module docstring's "``known_leak``, ``xfail``, and why
    ``raises=`` is not decorative" section for why both ``raises=<exact
    type>`` and ``strict=True`` are load-bearing, not defaults left in
    place.
    """
    cases: list[Any] = []
    for entry_point in EXERCISABLE:
        for case in entry_point.cases:
            case_id = f"{entry_point.name}::{case.id}"
            marks = []
            if case.known_leak is not None:
                marks.append(
                    pytest.mark.xfail(
                        reason=(
                            f"{case.known_leak.ticket}: known leak -- "
                            f"{case_id} raises "
                            f"{case.known_leak.leaked_type.__name__}, not a "
                            "CaliperError. Fix lands on that ticket, not "
                            "here; delete this registry entry's known_leak "
                            "when it does."
                        ),
                        raises=case.known_leak.leaked_type,
                        strict=True,
                    )
                )
            cases.append(
                pytest.param(
                    entry_point.name,
                    case.id,
                    case.invoke,
                    case.known_leak,
                    id=case_id,
                    marks=marks,
                )
            )
    return cases


@pytest.mark.parametrize(
    ("entry_point_name", "case_id", "invoke", "known_leak"), _all_cases()
)
def test_exception_escaping_public_entry_point_is_a_caliper_error(
    entry_point_name: str,
    case_id: str,
    invoke: Callable[[], Any],
    known_leak: object,
) -> None:
    """If ``invoke()`` raises, that exception must be a well-formed ``CaliperError``.

    Not raising is not a failure here: some cases exist to confirm a
    boundary condition that is *supposed* to raise a ``CaliperError``
    already does (a sanity check that the fix still holds), and some exist
    to confirm nothing raises at all (``Monitor``'s absorb-but-surface
    regression case). Both are legitimate passes -- including, for a
    ``known_leak`` case, the good kind of pass that ``strict=True`` turns
    into a failure so the stale marker gets noticed and removed.

    A ``CaliperError`` with an empty ``category`` or a non-mapping
    ``context`` is treated exactly like a non-``CaliperError`` leak --
    the contract is the structure, not merely the base class.
    """
    try:
        invoke()
    except _NOT_CONTRACT_VIOLATIONS:
        raise  # resource exhaustion, not a contract question -- see module docstring
    except CaliperError as exc:
        assert exc.category, (
            f"{entry_point_name}::{case_id} raised {type(exc).__name__} with an "
            "empty category -- the contract is the structure, not just the base class"
        )
        assert isinstance(exc.context, Mapping), (
            f"{entry_point_name}::{case_id} raised {type(exc).__name__} with a "
            f"non-mapping context ({type(exc.context).__name__}) -- the contract "
            "is the structure, not just the base class"
        )
    except Exception as exc:
        if known_leak is not None:
            # Let the original exception propagate unwrapped so
            # `xfail(raises=...)` can match its exact type -- wrapping it
            # in `pytest.fail` here would substitute pytest's own
            # `Failed` exception and defeat that matching entirely.
            raise
        pytest.fail(
            f"{entry_point_name}::{case_id} let a non-CaliperError escape: "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        )
