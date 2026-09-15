"""Guarded attribute access -- the shared mechanism behind BIN-118 and BIN-127.

``hasattr(candidate, name)`` swallows only ``AttributeError``. Since Python 3.2,
every other exception raised while resolving the attribute propagates
unchanged. A duck-typing check written as ``if not hasattr(candidate,
"score"): raise ...`` is therefore correct for a candidate that simply *lacks*
``.score``, and leaks raw for a candidate whose ``.score`` **raises** -- a
lazy ORM attribute hitting a detached session, a property reading a closed
file, a ``__getattr__`` doing I/O. Ordinary third-party code, not malice
(BIN-127).

This is the same hazard ``BIN-118`` fixed for *formatting* a caller-supplied
object (``drift_caliper.monitoring.domain.monitor._safe_repr`` falls back through
``repr`` -> ``type(obj).__name__`` -> a constant, rather than letting a
misbehaving ``__repr__`` escape). This module is the equivalent guard for
*accessing* a caller-supplied object's attributes rather than describing the
object itself.

**Placement.** Needed by three call sites across two bounded contexts --
``Baseline.record()`` and ``compare_provenance()`` (``drift_caliper.baseline``), and
``Monitor.record()`` (``drift_caliper.monitoring``). That package already
imports directly from ``drift_caliper.baseline.domain`` for several other
mechanisms (``compare_provenance``, every ``Fitted*`` artefact type) -- the
dependency direction between these two bounded contexts is already
monitoring-depends-on-baseline, never the reverse (verified: nothing under
``src/drift_caliper/baseline/`` imports from ``drift_caliper.monitoring``). Placing this
module here extends that existing, one-directional dependency rather than
introducing a new one, so it does not need the top-level
``src/drift_caliper/errors.py`` treatment -- that placement is justified there by
the error *types* being a two-way contract every bounded context raises and
every caller catches (``CLAUDE.md``'s "Module layout" note). A guarded
attribute probe is not a two-way contract; it is an internal mechanism one
context's domain layer already reaches into the other for, same as it
already does for ``compare_provenance`` itself. Do not promote this to
``src/drift_caliper/`` top level unless a *third*, independent bounded context
needs it and the existing directional dependency no longer covers that use
-- mirroring the promotion trigger ``code-reviewer`` stated on ``BIN-104``
for ``require_type``/``require_instance``.

This is the third time this project has answered a cross-context placement
question (``BIN-104``, ``BIN-126``, now this). The first two reasoned from
precedent (keep it local unless a third context needs it). This one checked
the actual import graph instead of reasoning from the ``errors.py`` analogy
alone, and the analogy did not hold as cleanly as it first looked:
``errors.py`` is genuinely bidirectional (every context raises, every
caller catches), while this probe only needs to travel a direction that
already travels. Reasoning from the real dependency graph, not from the
shape of a prior decision, is what settled it.

**Mechanism, not policy -- except where the policy is genuinely one policy.**
``probe_attribute``/``probe_fields`` never raise and never choose a
``CaliperError`` type or build a ``context`` mapping; ``compare_provenance()``
decides its own (``InvalidParameterError`` -- see that module's docstring for
why, a different failure class from the one below). That split mirrors
``spc_numerics.py``'s shared, policy-free numerical helpers reused by
chart-specific fitting modules that each raise their own errors.

``invalid_observation_error()`` below is the one deliberate exception to
"mechanism, not policy": ``Baseline.record()`` and ``Monitor.record()`` do
not merely use the same probe, they raise the *same* ``InvalidObservationError``
for the *same* reason with the *same* message and ``context`` shape --
this was, before BIN-127's review, a byte-identical pair of private
helpers in ``baseline.py`` and ``monitor.py``, the exact duplication risk
BIN-125 warns about (a future rejection rule added to one copy and missed
in the other). Leaving that pair in place while consolidating
``_missing_observation_fields`` would have fixed one instance of the
pattern and left a fresh one beside it. Hoisted here once both call sites'
policies were confirmed identical, not assumed identical.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from drift_caliper.errors import InvalidObservationError

# Fields a candidate observation must expose to be treated as a complete
# ScoringResult. Shared by Baseline.record() and Monitor.record() -- see
# invalid_observation_error() below.
REQUIRED_OBSERVATION_FIELDS = ("score", "reasoning", "provenance")


@dataclass(frozen=True)
class AttributeProbe:
    """The outcome of one guarded attribute access.

    Exactly one of the following describes ``candidate``'s attribute:

    * ``is_absent`` is ``True`` -- accessing it raised ``AttributeError``,
      the case ``hasattr`` already handles correctly. ``value`` is ``None``.
    * ``raised_type`` is not ``None`` -- accessing it raised something other
      than ``AttributeError`` (its type name, e.g. ``"RuntimeError"``) --
      the failure ``hasattr`` cannot safely paper over. ``value`` is
      ``None``.
    * Neither -- access succeeded. ``value`` holds the attribute's value.

    ``raised_type`` is deliberately a type *name* (``type(exc).__name__``),
    never the exception instance or its message: reading a class attribute
    cannot itself raise, whereas formatting the exception
    (``str(exc)``) can, for the same reason ``repr()`` can (BIN-118). This
    module already sits below that hazard by never formatting anything.
    """

    value: Any = None
    is_absent: bool = False
    raised_type: str | None = None


def probe_attribute(candidate: object, name: str) -> AttributeProbe:
    """Read ``candidate.<name>``, guarding against anything the access raises.

    Parameters
    ----------
    candidate
        The caller-supplied object to probe. May be ``None`` or any other
        object -- ``getattr`` is safe against both once wrapped as below.
    name
        The attribute name to read.

    Returns
    -------
    AttributeProbe
        Describes whether the attribute was present and readable, absent,
        or raised on access -- see :class:`AttributeProbe`.
    """
    try:
        value = getattr(candidate, name)
    except AttributeError:
        return AttributeProbe(is_absent=True)
    except MemoryError:
        # Resource exhaustion, not a contract question -- see
        # tests/unit/test_exception_contract_audit.py's
        # `_NOT_CONTRACT_VIOLATIONS`. Re-raised unwrapped, matching every
        # other site in this codebase that has considered the question:
        # no typed exception can meaningfully wrap an out-of-memory
        # condition, and swallowing it into `unreadable_fields` would make
        # a resource-exhaustion failure indistinguishable from an ordinary
        # duck-typing mismatch.
        raise
    except Exception as exc:
        # Deliberately broad: any exception other than AttributeError (and
        # MemoryError, excluded above) is the hazard this function exists
        # to catch (BIN-127), not a bug to narrow away.
        return AttributeProbe(raised_type=type(exc).__name__)
    return AttributeProbe(value=value)


@dataclass(frozen=True)
class FieldsProbe:
    """Bulk outcome of probing several field names on one candidate.

    Present-and-readable names are not reported here -- a caller that needs
    the actual value of a specific attribute should call
    :func:`probe_attribute` directly instead (``compare_provenance()`` does,
    since it needs the values to compare, not merely their presence).
    """

    absent: tuple[str, ...]
    unreadable: Mapping[str, str]


def probe_fields(candidate: object, names: Sequence[str]) -> FieldsProbe:
    """Probe every name in ``names`` on ``candidate``, partitioning the outcome.

    Replaces the once-duplicated ``_missing_observation_fields`` helper
    (byte-identical in ``drift_caliper.baseline.domain.baseline`` and
    ``drift_caliper.monitoring.domain.monitor`` before BIN-127) -- both call sites
    now share this one implementation instead of guarding two copies
    (BIN-125's sibling finding, for the same reason).

    Parameters
    ----------
    candidate
        The caller-supplied object to probe.
    names
        The attribute names to check.

    Returns
    -------
    FieldsProbe
        ``absent`` holds every name that is genuinely missing (the
        ``hasattr``-safe case); ``unreadable`` maps every name whose access
        raised something else to that exception's type name.
    """
    absent: list[str] = []
    unreadable: dict[str, str] = {}
    for name in names:
        outcome = probe_attribute(candidate, name)
        if outcome.is_absent:
            absent.append(name)
        elif outcome.raised_type is not None:
            unreadable[name] = outcome.raised_type
    return FieldsProbe(absent=tuple(absent), unreadable=unreadable)


def invalid_observation_error(candidate: object) -> InvalidObservationError:
    """Build the ``InvalidObservationError`` for an incomplete candidate.

    Shared by ``Baseline.record()`` and ``Monitor.record()`` -- see the
    module docstring's "one deliberate exception to mechanism, not policy"
    for why this one is hoisted rather than left as each call site's own
    decision.

    Kept as a single expression for a caller to ``raise``, rather than
    requiring it to compute the probe as a preceding statement in its own
    ``record()``: mypy's ``warn_unreachable`` does not flag a lone
    ``raise <expr>`` immediately following an ``isinstance`` guard on a
    parameter whose declared type already satisfies it (a common,
    deliberate defensive pattern -- the guard still matters for a caller
    that violates its own type hints), but it does flag any statement
    placed *before* that ``raise`` in the same branch, since the guard is
    statically always true for a correctly-typed caller. Verified directly
    against this project's mypy configuration, not assumed. Both call
    sites therefore do exactly ``raise invalid_observation_error(candidate)``
    and nothing else in that branch.
    """
    probe = probe_fields(candidate, REQUIRED_OBSERVATION_FIELDS)
    return InvalidObservationError(
        "recorded observation is not a complete scoring result",
        context={
            "reason": (
                "input is missing one or more required ScoringResult "
                "fields (score, reasoning, provenance), or one of those "
                "fields raised when accessed"
            ),
            "missing_fields": list(probe.absent),
            "unreadable_fields": dict(probe.unreadable),
        },
        recovery_hint=(
            "Pass a complete ScoringResult (score, reasoning, "
            "provenance) -- typically the return value of "
            "Judge.score()."
        ),
    )


__all__ = [
    "REQUIRED_OBSERVATION_FIELDS",
    "AttributeProbe",
    "FieldsProbe",
    "invalid_observation_error",
    "probe_attribute",
    "probe_fields",
]
