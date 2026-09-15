"""BIN-121 (part 2) -- the exception-contract audit.

**The rule:** any exception escaping a public entry point in
``drift_caliper.__all__`` must be a ``CaliperError`` (ADR-002/ADR-008), carrying a
non-empty ``category`` and a ``context`` mapping. The rule was already
written down -- ``CLAUDE.md``'s ``BIN-109`` note states it in as many
words. Nothing enforced it, and five separate leaks
(``BIN-104``/``ValidationError``, ``BIN-119``/``ZeroDivisionError``,
``BIN-120``/``AssertionError``, ``BIN-123``/``OverflowError``, and the
``BIN-109`` note's own beartype hypothetical) were each found by accident,
on a different ticket, over the space of a few days. This file is what
turns "we know the rule" into a gate.

See ``tests/support/exception_contract_registry.py`` for the registry this
file drives: a mapping from every name in ``drift_caliper.__all__`` to either how
it is exercised (a tuple of :class:`HostileCase`\\s) or why it is excluded
(a stated reason, never a silent omission).

## The scoreboard -- read this line first

**Zero known leaks remain. All 18 of the original findings from this
audit are closed** -- ``BIN-104`` (7), ``BIN-126`` (8), and now ``BIN-127``
(the last 3) each closed their share, and none has a live
``pytest.mark.xfail`` entry left in the registry. That is the milestone
this file exists to reach: every case ``EXERCISABLE`` describes either
raises a well-formed ``CaliperError`` or does not raise at all, with
nothing pinned as a known, tracked exception. The :class:`KnownLeak` /
``xfail(strict=True, raises=...)`` machinery is retained (see below) as
the mechanism that would track the *next* leak this audit finds, not as a
vestige of these three -- ``strict=True`` means a fix silently makes its
case XPASS, which fails the suite until the now-stale marker is deleted,
so a real regression cannot quietly reappear behind a stale marker either.

**BIN-104 was originally 7 cases; all 7 are now closed** and it no longer
appears in the tally above. ``ModelVersion``, ``ScoringCriteria``,
``ScoringResult`` and ``Provenance`` each gained a ``mode="before"``
``@field_validator`` (``drift_caliper.measurement.domain.type_guards``) that
runs ahead of Pydantic's core type coercion and raises
``InvalidParameterError`` for a wrong-typed constructor argument, instead
of letting Pydantic's own coercion reject it first as a raw
``pydantic_core.ValidationError``. ``Provenance`` is the interesting one:
ADR-006 deliberately gave it no content validator at all, reasoning that
its invariant was structural (inherited from ``ModelVersion``/
``ScoringCriteria``, which already cannot hold blank text) -- that
reasoning covers *content*, not *type*, since a wrong-typed
``model_version``/``scoring_criteria`` never constructs one of those value
objects in the first place. See the amendment note at the end of
ADR-006 for the full record.

**BIN-126 was originally 8 cases; all 8 are now closed** and it no longer
appears in the tally above. The wrong-typed-argument guards for
``fit_cusum``'s ``baseline``/``reference_value``, ``fit_shewhart``'s
``baseline``/``target_arl``, ``Baseline.check_sufficiency``'s
``threshold``, ``Judge.score``'s ``agent_output``, and -- closing the
final two -- ``fit_ewma``'s ``baseline``/``smoothing_param`` all now raise
``InvalidParameterError`` and every ``known_leak`` entry for them is
deleted. **``BIN-130`` (done first)** removed the thing that had been
blocking the last two: ``ewma_fitting.py``'s dev-only beartype hook, which
used to intercept those two calls with its own environment-dependent
``BeartypeCallHintParamViolation`` before either leaked anything else.
Both used to leak a stable, ordinary ``AttributeError``/``TypeError``
instead -- identically with or without the beartype hook installed --
which is what let ``BIN-126`` add the same
``drift_caliper.baseline.domain.parameter_guards`` guard the other charts
already carried, rather than designing a fourth convention.

## Why three tickets, not one

The grouping is load-bearing -- none of the three fixes solves either of
the other two:

* **``BIN-104`` (closed -- all 7 of an original 7, no longer in the tally
  above)** -- Pydantic's core type coercion runs *before* a
  ``@field_validator``, so a wrong-*typed* constructor argument
  (``ModelVersion(value=123)``, ``Judge.create(model_version=123)``, ...)
  never reached Caliper's own validation code at all. ``ModelVersion``,
  ``ScoringCriteria``, ``ScoringResult`` and ``Provenance`` now each carry
  a ``mode="before"`` ``@field_validator``
  (``drift_caliper.measurement.domain.type_guards``) that runs ahead of that
  core coercion. ⚠️ ``Provenance`` was in scope despite having **no field
  validator by design** (ADR-006: "there is nothing left to validate
  here" -- its invariant is structural, inherited from ``ModelVersion``/
  ``ScoringCriteria``). That reasoning covers *blank content*, not *type*
  -- a wrong-typed ``model_version``/``scoring_criteria`` never constructs
  one of those value objects at all, so the structural guarantee never
  engages. ``Provenance`` gained the same kind of ``mode="before"``
  validator, checking ``isinstance`` against ``ModelVersion``/
  ``ScoringCriteria`` directly -- see ADR-006's amendment note for the
  full record.
* **``BIN-126`` (closed -- all 8 of an original 8, no longer in the tally
  above)** -- A wrong-typed *argument to a function or method* (not a
  Pydantic model field) used to fail on its first use inside the function
  body, before any Caliper validation ran: ``math.isfinite("x")`` raised
  bare ``TypeError``, ``"x".check_sufficiency()`` raised bare
  ``AttributeError`` (a plain ``str`` has no such method). ``fit_cusum``,
  ``fit_shewhart``, ``Baseline.check_sufficiency``, ``Judge.score`` and --
  closing the last two -- ``fit_ewma`` all now validate with a shared,
  behavioural (not nominal) guard
  (``drift_caliper.baseline.domain.parameter_guards``) that keeps accepting
  ``int``/``np.float32``/``np.float64``/``np.int64`` and rejects ``bool``
  explicitly, before falling back to a plain ``isinstance`` check for
  non-numeric parameters like ``baseline``. ``BIN-130`` removed the thing
  that had been blocking the last two: the environment-dependent leaked
  type (``ewma_fitting``'s dev-only beartype hook) that used to sit ahead
  of them; see the scoreboard note above.
* **``BIN-127`` (closed -- all 3 of an original 3, no longer in the tally
  above)** -- An object that duck-types past an ``isinstance`` check but
  misbehaves on actual attribute access. ``Baseline.record()``/
  ``Monitor.record()``'s once-duplicated ``_missing_observation_fields``
  (``hasattr`` only swallows ``AttributeError``) and ``compare_provenance()``
  (no guard equivalent to ``Monitor``'s ``_safe_repr``) used to read a
  caller-supplied object's attributes directly and let whatever that access
  raised propagate unchanged. All three now go through
  ``drift_caliper.baseline.domain.attribute_probe`` -- one shared, guarded probe
  used by both bounded contexts (``baseline`` and ``monitoring``) rather
  than two independently-guarded copies -- which distinguishes "attribute
  absent" from "attribute access raised" in ``context`` rather than
  flattening the two, and never itself raises. ``Baseline.record()``/
  ``Monitor.record()`` keep raising ``InvalidObservationError``;
  ``compare_provenance()`` raises ``InvalidParameterError`` (not
  ``ProvenanceMismatchError`` -- see that module's
  ``_reject_if_artefact_provenance_unreadable`` docstring for why: there is
  no actual "received" value to report when the read itself failed, only a
  malformed ``artefact`` parameter to reject).

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

**No case below currently carries a** :class:`~tests.support.
exception_contract_registry.KnownLeak` -- the registry's last three were
deleted when ``BIN-127`` closed. The mechanism stays wired up in
``_all_cases()`` for whenever the *next* one is found: a case annotated
with :class:`~tests.support.exception_contract_registry.KnownLeak`
(ticket + the *exact* exception type observed) turns into
``pytest.mark.xfail(strict=True, raises=<that type>)``:

* **``raises=<exact type>``, not ``Exception``.** If a future change
  makes the same entry point leak a *different* foreign type, ``raises``
  will not match it, and the case fails for real rather than quietly
  staying green under a marker that no longer describes what actually
  happens. That is new information, not confirmation of the same bug --
  ``RuntimeError`` was exactly what BIN-127's three hostile objects' own
  attribute access raised, the same reasoning that previously
  distinguished ``BIN-104``'s ``ValidationError`` and ``BIN-126``'s bare
  ``AttributeError``/``TypeError`` before each of those closed in turn.
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

import drift_caliper
from drift_caliper.errors import CaliperError
from tests.support.exception_contract_registry import (
    EXCLUDED,
    EXERCISABLE,
    GRID_KINDS,
    ExercisableEntryPoint,
    InputKind,
)

_EXCLUDED_NAMES = frozenset(entry.name for entry in EXCLUDED)
_EXERCISABLE_NAMES = frozenset(entry.name for entry in EXERCISABLE)

# Exceptions that signal a genuine runtime condition, not a contract
# violation -- see the module docstring's closing section for why each is
# excluded. Checked in an explicit tuple (not a bare `except Exception`)
# because `MemoryError` is an `Exception` subclass and would otherwise be
# swept into the CaliperError assertion below.
_NOT_CONTRACT_VIOLATIONS: tuple[type[BaseException], ...] = (MemoryError,)


def test_every_public_name_is_classified() -> None:
    """Every name in ``drift_caliper.__all__`` is either exercisable or excluded.

    This is the meta-test the whole registry exists to make possible
    (mirrors ``BIN-124``'s
    ``test_baseline_scores_strategy_never_draws_a_baseline_the_library_rejects``):
    adding a new export to ``drift_caliper.__all__`` without adding it to either
    registry in ``tests/support/exception_contract_registry.py`` fails
    here immediately, rather than silently shipping unaudited. Also
    guards against the opposite mistake -- a name classified in *both*
    registries, or a registry entry for a name no longer exported at all.
    """
    public_names = frozenset(drift_caliper.__all__)

    unclassified = public_names - _EXCLUDED_NAMES - _EXERCISABLE_NAMES
    assert not unclassified, (
        f"drift_caliper.__all__ names with no classification in "
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
        f"longer in drift_caliper.__all__: {sorted(stale_registry_entries)} -- "
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


def test_every_entry_point_covers_or_excuses_every_input_kind() -> None:
    """The grid is complete: each entry point x each kind is a case or a reason.

    **This is BIN-136's whole mechanism**, and it is one dimension wider
    than ``test_every_public_name_is_classified`` above. That test forces
    *name* coverage -- a new export cannot ship unaudited. It says nothing
    about *which hostile inputs* a name is probed with, and that gap is
    not theoretical: ``compare_provenance`` was registered, exercised, and
    reported clean while leaking a raw ``RuntimeError``, because no case
    anywhere passed an object whose comparison raises. A missing name
    failed the build; a missing input **kind** was invisible.

    ⚠️ **``GRID_KINDS`` is derived from ``InputKind``, not listed**, so
    adding a member fails this test for every entry point that has not yet
    considered it. That is deliberate and is the point -- a new kind is a
    question to be asked of the whole surface, not of whoever happens to
    remember.

    ⚠️ **An ``n/a`` reason is a claim about the code and must be able to
    become false.** "Takes no string argument" stops being true the day a
    string parameter is added, and a reader can check it. "Not applicable"
    cannot be wrong, which is why the length floor below exists -- it is a
    crude proxy for "someone thought about this", and it is the difference
    between this grid and a rubber stamp.
    """
    failures: list[str] = []

    for entry_point in EXERCISABLE:
        covered = {
            case.kind
            for case in entry_point.cases
            if case.kind is not InputKind.REGRESSION_ANCHOR
        }
        excused = set(entry_point.not_applicable)

        both = covered & excused
        if both:
            failures.append(
                f"{entry_point.name}: {sorted(k.value for k in both)} is both "
                "exercised and excused -- if a case exists, the kind applies; "
                "delete the not_applicable entry."
            )

        missing = [k for k in GRID_KINDS if k not in covered and k not in excused]
        if missing:
            failures.append(
                f"{entry_point.name}: no case and no stated reason for "
                f"{sorted(k.value for k in missing)}. Add a HostileCase, or a "
                "not_applicable entry saying why the kind cannot reach it."
            )

        stale = excused - set(GRID_KINDS)
        if stale:
            failures.append(
                f"{entry_point.name}: excuses {sorted(k.value for k in stale)}, "
                "which is not a grid kind -- REGRESSION_ANCHOR is excluded from "
                "the grid and needs no excuse."
            )

    assert not failures, "\n".join(failures)


@pytest.mark.parametrize(
    "entry_point", EXERCISABLE, ids=lambda entry_point: entry_point.name
)
def test_not_applicable_reasons_are_substantive(
    entry_point: ExercisableEntryPoint,
) -> None:
    """Every ``n/a`` reason says something specific enough to be checked.

    🚨 **The failure mode this guards is the one that would make BIN-136
    worse than useless.** A grid filled with "not applicable" is a
    completeness claim backed by nothing, and it would read as stronger
    than the curated list it replaced -- the precise defect BIN-136 was
    filed to fix, reintroduced with more ceremony.

    A length floor cannot verify that a reason is *true*; nothing
    automatic can. It only makes the empty gesture inconvenient enough to
    notice in review. The real check is a reader asking "would I know if
    this stopped being true?" -- and the worked reasons on ``Baseline``,
    ``Provenance`` and ``compare_provenance`` are the standard to match.

    ⚠️ **That limitation is measured, not assumed** (2026-09-13). Two
    mutations were run against the completed grid:

    * deleting ``Monitor``'s ``COMPARISON_RAISES`` excuse -- **caught**,
      naming the entry point and the kind
    * prefixing a real reason with *"This is not applicable here at all
      for any reason whatsoever truly and the remainder is unused padding
      text"* -- **passed**

    **The second is the honest ceiling of this test.** Do not read a green
    run as evidence the reasons are sound; read it as evidence none is
    *blank*. Reviewing the reasons is a human job and stays one.
    """
    for kind, reason in entry_point.not_applicable.items():
        assert len(reason.split()) >= 8, (
            f"{entry_point.name}/{kind.value}: {reason!r} is too short to be "
            "a reason. State what about this entry point makes the kind "
            "unreachable, in terms a reader can check against the code."
        )
        assert reason.strip().lower() not in {"n/a", "not applicable", "none"}, (
            f"{entry_point.name}/{kind.value}: placeholder reason."
        )
