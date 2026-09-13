"""Registry for BIN-121's exception-contract audit.

**The rule being enforced (ADR-002/ADR-008, restated in ``CLAUDE.md``'s
``BIN-109`` note):** any exception escaping a public entry point must be a
``CaliperError``, carrying a non-empty ``category`` and a ``context``
mapping the caller can branch on. That rule was written down and understood
before this ticket -- nothing enforced it. Five instances leaked a foreign
exception type before this audit was written (``BIN-104``, ``BIN-119``,
``BIN-120``, ``BIN-123``, and the ``BIN-109`` note's hypothetical about
beartype), each found separately, by accident, on a different ticket. This
module is what turns "we know the rule" into "the suite fails if the rule
is broken."

**Design, following the ``BIN-124`` precedent
(``tests/support/baseline_strategies.py`` /
``tests/unit/baseline/test_baseline_scores_strategy_contract.py``):** a
registry maps every name in ``caliper.__all__`` to either *how to exercise
it* (an :class:`ExercisableEntryPoint` -- a tuple of :class:`HostileCase`\\
s, each a zero-argument callable that attempts one hostile invocation) or
an explicit *not-an-entry-point* classification (:class:`ExcludedEntryPoint`
-- a name plus the reason it is not something an engineer invokes with
adversarial input). A meta-test
(``tests/unit/test_exception_contract_audit.py::
test_every_public_name_is_classified``) asserts every name in
``caliper.__all__`` appears in exactly one of the two registries -- so
adding a new export *forces* a classification decision before this file
compiles a passing test suite around it; it cannot silently go unaudited.
The audit test itself then runs every :class:`HostileCase` and asserts:
if the call raised, the raised exception is a ``CaliperError`` with a
non-empty ``category`` and a mapping ``context``. If the call did not
raise, that is not a failure here -- some cases exist specifically to
confirm a case that already IS a ``CaliperError`` (e.g. a provider's
``ProviderError`` passing through ``Judge.score()`` unchanged), or that a
signal is genuinely absorbed rather than raised at all (``BIN-118``'s
regression, ``Monitor``'s receivers).

**Coverage is automatic; inputs are curated -- not a fuzzing campaign.**
Every case below is a fixed, deterministic invocation, chosen to
reproduce one of: a wrong-typed argument, an empty/whitespace string, a
non-finite float, an object that satisfies a protocol structurally but
raises when a specific attribute is actually read, or an already-covered
boundary condition re-run here as a sanity check that the fix still holds.

**What this audit found -- read before assuming this was always green.**
**Zero cases below are currently known leaks.** All 18 of the original
findings this audit turned up are now closed: ``BIN-126`` closed its
eight, ``BIN-104`` closed its seven, and ``BIN-127`` closed the
remaining three -- an object that duck-types past an ``isinstance`` check
but raises on actual attribute access, at ``Baseline.record()``,
``Monitor.record()``, and ``compare_provenance()`` (see each ticket's
completion report). The :class:`KnownLeak` machinery below is retained,
not removed, since it is the mechanism that would track the *next* one: a
case is annotated with :class:`KnownLeak` (ticket + the exact exception
type observed) and the audit test turns that into
``pytest.mark.xfail(strict=True, raises=<that type>)`` -- tracked and
green, not silenced. See the module docstring of
``tests/unit/test_exception_contract_audit.py`` for the full, itemised
history and why ``strict=True``/``raises=`` matter -- this docstring only
explains the registry mechanism.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from caliper.baseline import (
    Baseline,
    FittingAdvisory,
    compare_provenance,
    fit_cusum,
    fit_ewma,
    fit_shewhart,
)
from caliper.errors import JudgeRefusalError, MalformedResponseError, ProviderError
from caliper.measurement import (
    Judge,
    JudgeProviderResponse,
    ModelVersion,
    Provenance,
    ScoringCriteria,
    ScoringResult,
)
from caliper.monitoring import Monitor
from tests.factories import (
    ProvenanceFactory,
    ScoringCriteriaFactory,
    ScoringResultFactory,
)
from tests.support.baseline_strategies import baseline_from_scores, probe_baseline
from tests.support.fakes import FakeJudgeProviderPort

# ---------------------------------------------------------------------------
# Shared fixtures -- built once, reused across cases. `fit_ewma`'s Markov-chain
# calibration is the expensive step here (~49ms, per
# tests/unit/baseline/test_baseline_scores_strategy_contract.py's own measured
# figure) -- computing it once at import time rather than per-case keeps this
# file's runtime bounded.
# ---------------------------------------------------------------------------

# Not itself a hostile input; it exists only so the *parameters* below can
# be hostile against a baseline that would otherwise fit cleanly. See
# `probe_baseline()`.
_BASELINE = probe_baseline()

# BIN-119 regression fixtures -- each has two distinct values (so the
# ordinary zero-variance guard does not fire first) but its moving-range
# *aggregate* is not finite/positive in float64 arithmetic. Reproduces the
# exact two halves of BIN-119: alternating +-1e308 overflows every
# consecutive difference to `inf`; one subnormal among 99 zeros underflows
# the mean moving range to exactly `0.0`. Built fresh per case (not part of
# `_BASELINE`) since these are deliberately NOT ordinary fittable data.
_SIGMA_OVERFLOW_SCORES = [1e308, -1e308] * 50
_SIGMA_UNDERFLOW_SCORES = [0.0] * 99 + [5e-324]
_SHARED_PROVENANCE = _BASELINE.provenance_signature
assert _SHARED_PROVENANCE is not None  # a sufficient baseline always has one
_FITTED_EWMA = fit_ewma(_BASELINE, target_arl=370.0)


def _matching_scoring_result(score: float = 0.5) -> ScoringResult:
    """A ``ScoringResult`` whose provenance matches ``_FITTED_EWMA``'s baseline."""
    return ScoringResultFactory(provenance=_SHARED_PROVENANCE, score=score)


def _mismatched_scoring_result() -> ScoringResult:
    """A ``ScoringResult`` whose provenance deliberately differs from the shared one."""
    return ScoringResultFactory(provenance=ProvenanceFactory(), score=0.5)


def _configured_judge(
    *, provider: FakeJudgeProviderPort | None = None, criteria: str | None = "c1"
) -> Judge:
    return Judge.create(model_version="m1", provider=provider, criteria=criteria)


def _cusum_monitor_record_after_sigma_underflow() -> object:
    """Fit CUSUM from an underflowing baseline, then record against it.

    Reproduces BIN-119's Half 2 at the exact boundary the original defect
    report names: ``fit_cusum`` on this baseline currently raises
    ``DegenerateBaselineError`` before a ``FittedCUSUM`` is ever
    constructed -- both the shared ``_moving_range_sigma`` guard
    (``spc_numerics.py``) and ``FittedCUSUM``'s own field validator would
    have to be bypassed for this to reach ``Monitor.record()`` at all. If
    both ever regress simultaneously, this is the case that would surface
    the original raw ``ZeroDivisionError`` at
    ``Monitor._check_cusum``'s ``(score - target_value) / sigma_estimate``
    -- not merely at fit time, which is where every other BIN-119 case in
    this registry stops.
    """
    baseline = baseline_from_scores(_SIGMA_UNDERFLOW_SCORES)
    artefact = fit_cusum(baseline, target_arl=370.0)
    provenance = baseline.provenance_signature
    assert provenance is not None
    observation = ScoringResultFactory(provenance=provenance, score=0.5)
    return Monitor(artefact).record(observation)


# ---------------------------------------------------------------------------
# Hostile objects -- structurally shaped, deliberately misbehaving on access.
# ---------------------------------------------------------------------------


class _RaisingScoreCandidate:
    """Not a ``ScoringResult``; its ``score`` attribute raises rather than being absent.

    Reproduces the case ``hasattr(candidate, "score")`` cannot safely paper
    over: ``hasattr`` only swallows ``AttributeError``, so a candidate whose
    attribute access itself misbehaves (a lazy-loading ORM-style descriptor,
    a property backed by a closed resource) used to propagate that failure
    through ``Baseline.record``'s and ``Monitor.record``'s identical
    ``_missing_observation_fields`` helpers. Both now go through the shared,
    guarded ``caliper.baseline.domain.attribute_probe.probe_fields`` instead
    (BIN-127) -- this case is a regression test for that fix, not a live
    leak.
    """

    @property
    def score(self) -> float:
        raise RuntimeError("boom-on-score-access")


class _ThirdPartyArtefact:
    """Structurally satisfies ``FittedControlLimits`` but is none of the concrete types.

    Reproduces ``BIN-120``'s exact scenario -- every property the
    ``@runtime_checkable`` protocol checks for is present, so
    ``isinstance(obj, FittedControlLimits)`` is ``True``, yet this is not
    ``FittedEWMA``/``FittedCUSUM``/``FittedShewhart``. Used to confirm
    ``Monitor.__init__``'s narrowed ``isinstance`` check (the ``BIN-120``
    fix) still rejects it with a typed error rather than accepting it and
    failing later.
    """

    chart_type = "third_party"
    baseline_mean = 0.5
    baseline_spread = 0.1
    sigma_estimate = 0.05
    sigma_estimation_method = "third_party_method"
    observation_count = 100
    provenance_model_version = "third-party-model"
    provenance_criteria = "third-party-criteria"
    requested_arl = 370.0
    achieved_arl = 370.0
    calibration_method = "third_party"
    advisories: tuple[FittingAdvisory, ...] = ()


class _RaisingProvenanceArtefact:
    """A ``FittedControlLimits``-shaped object whose model-version property raises.

    ``compare_provenance()`` (unlike ``Monitor``) takes any object
    satisfying ``FittedControlLimits`` and reads
    ``artefact.provenance_model_version``/``artefact.provenance_criteria``
    directly. It used to do so with no guard equivalent to ``Monitor``'s
    ``_safe_repr`` (``BIN-118``/``BIN-120``'s fix) -- a hazard neither of
    those fixes touched. It now reads both through
    ``caliper.baseline.domain.attribute_probe.probe_attribute`` and raises
    ``InvalidParameterError`` instead (BIN-127); this case is a regression
    test for that fix, not a live leak.
    """

    provenance_criteria = "criteria"

    @property
    def provenance_model_version(self) -> str:
        raise RuntimeError("boom-on-provenance-access")


class _NonStrProvenanceArtefact:
    """Provenance attributes read cleanly and return the wrong type (BIN-121 B).

    Distinct from :class:`_RaisingProvenanceArtefact`, whose attributes
    raise on *access*. Here the read succeeds -- and hands back something
    that is not a ``str``, which then flowed into
    ``context["mismatches"]``, declared ``dict[str, dict[str, str]]``.
    """

    provenance_model_version = 123
    provenance_criteria = "rubric"


class _HostileStr(str):
    """A ``str`` **subclass** whose comparison raises -- BIN-139's input.

    🚨 **The subclassing is the whole point, and an earlier draft of this
    case missed it.** BIN-121's guard is ``isinstance(value, str)``, so a
    plain hostile object is rejected as ``ATTRIBUTE_RETURNS_HOSTILE``
    *before any comparison happens* -- the case passed, was named for the
    comparison, and never reached one. A ``str`` subclass is the only
    input that satisfies the guard **and** still hijacks ``__eq__``, so it
    is the only input that genuinely exercises ``COMPARISON_RAISES`` here.

    ⚠️ **A distinct failure shape from the one BIN-136 was built for**:
    not a missing cell, but a cell filled by a case that could not reach
    the behaviour it claimed. The grid makes a cell visible; it cannot
    verify the case is aimed correctly. Aiming it correctly exposed
    BIN-139 immediately.
    """

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("eq exploded")

    def __ne__(self, other: object) -> bool:
        raise RuntimeError("ne exploded")

    def __hash__(self) -> int:
        return 0


class _HostileComparisonArtefact:
    """Provenance whose value passes the str guard and then raises on compare.

    See :class:`_HostileStr`. BIN-139's reproduction, kept as the
    ``COMPARISON_RAISES`` case for ``compare_provenance`` now that the
    guard normalises probed values to exact ``str``.

    ⚠️ **The version deliberately differs from the result's**, so this
    reaches the comparison *and* the error path. A matching hostile value
    returns silently -- correct, since the content matches, but it would
    exercise only half of what the fix has to get right. The matching
    variant is pinned in ``tests/unit/test_hostile_objects.py``.
    """

    provenance_model_version = _HostileStr("a-different-version")
    provenance_criteria = "rubric"


class _RaisingReprReceiver:
    """A ``SignalReceiver`` that raises, and whose own ``__repr__`` also raises.

    The exact ``BIN-118`` shape: describing the failure must not itself
    raise. Used as a *positive* case -- ``Monitor.record()`` is expected to
    absorb this without letting anything escape (ADR-010 "absorb, but
    surface"), so this case's success is a regression test for the
    ``BIN-118`` fix, not a hostile-input probe expected to fail.
    """

    def __call__(self, signal: object) -> None:
        raise RuntimeError("receiver boom")

    def __repr__(self) -> str:
        raise RuntimeError("repr boom")


# ---------------------------------------------------------------------------
# Registry data model
# ---------------------------------------------------------------------------


class InputKind(Enum):
    """The kinds of hostile input an entry point can be probed with.

    **This enumeration is the point of BIN-136.** Before it, the registry
    forced *name* coverage -- every name in ``caliper.__all__`` must be
    classified -- but said nothing about *which hostile inputs* each name
    was probed with. A missing name failed the build; a missing input
    **kind** was invisible.

    That is not hypothetical. ``compare_provenance`` was registered,
    exercised, and reported clean while leaking a raw ``RuntimeError``,
    because no case anywhere passed an object whose *comparison* raises
    (BIN-121 part 3, found by a hand audit that happened to run).

    ⚠️ **The enumeration is global, not per-entry-point, and that is the
    load-bearing choice.** Letting each entry point declare which kinds
    *it* considers applicable would not have caught the defect above --
    nobody would have thought to declare ``COMPARISON_RAISES`` relevant to
    ``compare_provenance``, which is exactly why it was missed. Every kind
    is crossed against every entry point, and inapplicability must be
    *stated and justified* rather than assumed by omission.

    **Adding a member here deliberately fails the build** until every
    entry point either covers it or records why it cannot apply. That cost
    is the feature.
    """

    WRONG_TYPE = "wrong_type"
    """An argument of an entirely wrong type -- ``None``, ``int`` for a model."""

    EMPTY_STRING = "empty_string"
    """An empty or whitespace-only string where text is required."""

    NON_FINITE_FLOAT = "non_finite_float"
    """``NaN`` or ``±inf`` where a real number is required."""

    ATTRIBUTE_ACCESS_RAISES = "attribute_access_raises"
    """A duck-typed object that satisfies a protocol structurally but raises
    when an attribute is actually read (BIN-127's class)."""

    ATTRIBUTE_RETURNS_HOSTILE = "attribute_returns_hostile"
    """A duck-typed object whose attribute *returns* successfully, but
    returns something unusable -- the wrong type, or an object that
    misbehaves later.

    ⚠️ **Distinct from ``ATTRIBUTE_ACCESS_RAISES``, and the distinction is
    exactly what BIN-127's fix did not cover.** Guarding the read says
    nothing about what the read produced."""

    COMPARISON_RAISES = "comparison_raises"
    """An object whose ``__eq__``/``__ne__`` raises when Caliper compares
    it. The kind that escaped the pre-BIN-136 registry entirely."""

    OUT_OF_RANGE_VALUE = "out_of_range_value"
    """The right type, an illegal value -- ``threshold=0``, a negative
    count, a ``target_arl`` below ADR-011's floor, a smoothing parameter
    outside ``(0, 1]``.

    ⚠️ **Added while prototyping BIN-136 on three entry points, which is
    what the prototype was for.** The taxonomy was seeded from the five
    kinds the old registry's prose enumerated plus BIN-121's two, and this
    kind was in none of them -- yet ``Baseline``'s existing
    ``check_sufficiency(threshold=0)`` and ``threshold=-1`` cases had been
    probing it all along, unnamed. **A kind the registry was already
    exercising, that its own description did not mention**, is the
    clearest possible evidence that the prose enumeration was never a
    coverage claim.

    ⚠️ Do not merge this into ``WRONG_TYPE``. Type rejection happens at a
    different boundary (Pydantic ``mode="before"`` guards, BIN-104/126)
    from range rejection (explicit checks in ``parameter_guards``), and
    conflating them would let an entry point look covered for one while
    missing the other entirely."""

    REGRESSION_ANCHOR = "regression_anchor"
    """Not a hostile input at all -- a legitimate call kept here to pin a
    previously-broken path, or to confirm an already-correct
    ``CaliperError`` still passes through unchanged.

    ⚠️ **Excluded from the grid** (see ``GRID_KINDS``): it is not a
    question one can ask of every entry point, so requiring an ``n/a``
    reason for it everywhere would be noise. It exists as a member rather
    than by making ``kind`` optional, because an optional field is one a
    new case can silently forget to set -- which is the precise failure
    mode this ticket is closing, and it would be perverse to reintroduce
    it in the fix."""


GRID_KINDS: tuple[InputKind, ...] = tuple(
    kind for kind in InputKind if kind is not InputKind.REGRESSION_ANCHOR
)
"""The kinds every entry point must either exercise or excuse.

Derived from :class:`InputKind` rather than listed, so a new member joins
the grid automatically -- and immediately fails the completeness test for
every entry point that has not considered it. **That failure is the
mechanism, not an inconvenience.**
"""


@dataclass(frozen=True)
class KnownLeak:
    """A currently-known, ticketed exception-contract violation.

    Attaching this to a :class:`HostileCase` is what lets the audit test
    turn that one case into ``pytest.mark.xfail(strict=True,
    raises=leaked_type)`` (see
    ``tests/unit/test_exception_contract_audit.py``) instead of a hard
    failure -- tracked, not silenced.

    ``leaked_type`` is the **exact** exception type observed escaping this
    case at the time this entry was written -- never a broad supertype
    like ``Exception``, and not necessarily the same type another case
    with the same ``ticket`` observes (``BIN-126`` alone covers a
    beartype violation, a bare ``TypeError``, and a bare
    ``AttributeError`` -- three different types, one root cause). Pinning
    the specific type is what makes ``xfail(raises=...)`` a real
    assertion rather than a blank check: if a future change makes this
    entry point leak a *different* foreign type, ``raises`` will not
    match, and the case fails for real -- new information, not
    confirmation of the same bug. If the entry point is fixed to raise a
    proper ``CaliperError`` instead, the case passes outright, and
    ``strict=True`` turns that pass into a failure -- forcing whoever
    fixes it to also delete this entry, rather than leaving a stale
    marker hiding a closed ticket.
    """

    ticket: str
    leaked_type: type[BaseException]


@dataclass(frozen=True)
class HostileCase:
    """One invocation to try against an entry point.

    ``invoke`` is a zero-argument callable; calling it either returns
    normally (no assertion made -- see the module docstring on why a
    non-raising case is not itself a failure) or raises, in which case the
    audit test asserts the raised exception satisfies the ``CaliperError``
    contract.

    ``known_leak`` is ``None`` for every case that either passes today or
    has not yet been triaged into a ticket. Set it only once a leak has
    been confirmed and filed -- see :class:`KnownLeak`.
    """

    id: str
    invoke: Callable[[], Any]
    kind: InputKind
    known_leak: KnownLeak | None = None


@dataclass(frozen=True)
class ExercisableEntryPoint:
    """A public name that is a caller-invoked operation, with its hostile cases.

    ``not_applicable`` records, per :class:`InputKind` this entry point has
    no case for, *why the kind cannot reach it*. The completeness meta-test
    requires every kind to be either exercised or excused here, so omission
    is not an option.

    ⚠️ **The reasons carry the whole value and must be falsifiable.** "This
    entry point takes no string argument" stays true, or visibly stops
    being true when a string parameter is added. "Not applicable" is a
    shrug that will be copied into the next thirty cells and audited by
    nobody.
    """

    name: str
    cases: tuple[HostileCase, ...]
    not_applicable: Mapping[InputKind, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExcludedEntryPoint:
    """A public name that is deliberately NOT exercised, with the reason why."""

    name: str
    reason: str


# ---------------------------------------------------------------------------
# Exercisable entry points
# ---------------------------------------------------------------------------

_BASELINE_CASES = (
    HostileCase(
        "record_none",
        lambda: Baseline().record(None),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "record_wrong_type_int",
        lambda: Baseline().record(123),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "record_hostile_raising_attribute",
        lambda: Baseline().record(_RaisingScoreCandidate()),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        kind=InputKind.ATTRIBUTE_ACCESS_RAISES,
    ),
    HostileCase(
        "check_sufficiency_zero_threshold",
        lambda: Baseline().check_sufficiency(threshold=0),
        kind=InputKind.OUT_OF_RANGE_VALUE,
    ),
    HostileCase(
        "check_sufficiency_negative_threshold",
        lambda: Baseline().check_sufficiency(threshold=-1),
        kind=InputKind.OUT_OF_RANGE_VALUE,
    ),
    HostileCase(
        "check_sufficiency_wrong_type_threshold",
        lambda: Baseline().check_sufficiency(
            threshold="not an int"  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
)

_BASELINE_NA: Mapping[InputKind, str] = {
    InputKind.EMPTY_STRING: (
        "record() takes a ScoringResult, check_sufficiency() an int. "
        "Neither takes a string; the strings inside a ScoringResult are "
        "already non-blank by ModelVersion/ScoringCriteria construction."
    ),
    InputKind.NON_FINITE_FLOAT: (
        "The only float is ScoringResult.score, which its own "
        "@field_validator rejects as non-finite before a Baseline sees it "
        "(ADR-006 OQ-2) -- covered under ScoringResult. check_sufficiency "
        "takes an int and rejects non-integral values outright."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "record() reads attributes off the candidate via probe_fields "
        "(BIN-127), but every value read is then handed to Pydantic "
        "construction or compared against Caliper's own Provenance, both "
        "of which reject a wrong type. ⚠️ This is the kind that broke "
        "compare_provenance -- the difference is that record() validates "
        "what it read and compare_provenance did not."
    ),
    InputKind.COMPARISON_RAISES: (
        "record() compares provenance, but both sides are Caliper's own "
        "Provenance objects: the stored one and the candidate's, the "
        "latter already Pydantic-validated. A caller-supplied object "
        "never reaches the comparison. Verified during BIN-121, which "
        "deliberately left Baseline.record() unchanged for this reason."
    ),
}

_JUDGE_CASES = (
    HostileCase(
        "create_missing_model_version",
        lambda: Judge.create(model_version=None),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "create_blank_model_version",
        lambda: Judge.create(model_version="   "),
        kind=InputKind.EMPTY_STRING,
    ),
    HostileCase(
        "create_wrong_type_model_version",
        lambda: Judge.create(model_version=123),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "create_wrong_type_criteria",
        lambda: Judge.create(
            model_version="m1",
            criteria=123,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "score_no_provider",
        lambda: Judge.create(model_version="m1", criteria="c1").score(agent_output="x"),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "score_no_criteria",
        lambda: Judge.create(
            model_version="m1", provider=FakeJudgeProviderPort()
        ).score(agent_output="x"),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "score_blank_output",
        lambda: _configured_judge(provider=FakeJudgeProviderPort()).score(
            agent_output="   "
        ),
        kind=InputKind.EMPTY_STRING,
    ),
    HostileCase(
        "score_wrong_type_output",
        lambda: _configured_judge(provider=FakeJudgeProviderPort()).score(
            agent_output=123  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "score_provider_error_passthrough",
        lambda: _configured_judge(
            provider=FakeJudgeProviderPort(
                error_to_raise=ProviderError(
                    "boom",
                    context={"provider": "p", "operation": "score"},
                    recovery_hint="retry",
                )
            )
        ).score(agent_output="x"),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "score_malformed_response_passthrough",
        lambda: _configured_judge(
            provider=FakeJudgeProviderPort(
                error_to_raise=MalformedResponseError(
                    "boom",
                    context={"operation": "score", "expected_shape": "score+reasoning"},
                    recovery_hint="investigate",
                )
            )
        ).score(agent_output="x"),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "score_judge_refusal_passthrough",
        lambda: _configured_judge(
            provider=FakeJudgeProviderPort(
                error_to_raise=JudgeRefusalError(
                    "boom",
                    context={"provider": "p", "operation": "score"},
                    recovery_hint="review policy",
                )
            )
        ).score(agent_output="x"),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "score_provider_returns_nonfinite_score",
        lambda: _configured_judge(
            provider=FakeJudgeProviderPort(
                response=JudgeProviderResponse(score=float("nan"), reasoning="r")
            )
        ).score(agent_output="x"),
        kind=InputKind.NON_FINITE_FLOAT,
    ),
)

_JUDGE_NA: Mapping[InputKind, str] = {
    InputKind.OUT_OF_RANGE_VALUE: (
        "Neither Judge.create() nor Judge.score() takes a bounded numeric "
        "parameter. model_version and criteria are strings; agent_output is "
        "a string; provider is a protocol object. The score itself is "
        "validated by ScoringResult's field_validator, not Judge."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "Judge.create() takes str/None for model_version and criteria, "
        "and a concrete JudgeProviderPort for provider -- no duck-typed "
        "object is ever probed for attributes by Judge. score() delegates "
        "to the provider's .score() method, which is protocol-dispatched, "
        "not attribute-probed."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same as ATTRIBUTE_ACCESS_RAISES -- Judge never reads attributes "
        "off a caller-supplied duck-typed object. model_version, criteria, "
        "and agent_output are scalars; the provider is called, not probed."
    ),
    InputKind.COMPARISON_RAISES: (
        "Neither Judge.create() nor Judge.score() compares a "
        "caller-supplied object. model_version and criteria are wrapped "
        "into Pydantic value objects at creation; score() delegates to "
        "the provider and assembles a ScoringResult -- no equality check "
        "on any caller-supplied value occurs."
    ),
}

_MODEL_VERSION_CASES = (
    HostileCase(
        "blank",
        lambda: ModelVersion(value=""),
        kind=InputKind.EMPTY_STRING,
    ),
    HostileCase(
        "whitespace_only",
        lambda: ModelVersion(value="   "),
        kind=InputKind.EMPTY_STRING,
    ),
    HostileCase(
        "wrong_type_int",
        lambda: ModelVersion(value=123),  # type: ignore[arg-type]
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "wrong_type_none",
        lambda: ModelVersion(value=None),  # type: ignore[arg-type]
        kind=InputKind.WRONG_TYPE,
    ),
)

_MODEL_VERSION_NA: Mapping[InputKind, str] = {
    InputKind.NON_FINITE_FLOAT: (
        "Has no numeric field. ModelVersion wraps a single str value; "
        "no float reaches its constructor or any validator."
    ),
    InputKind.OUT_OF_RANGE_VALUE: (
        "Has no bounded field. The only invariant is non-blankness, "
        "which is EMPTY_STRING's concern -- there is no range a valid "
        "string can fall outside."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "Takes a str, not a duck-typed object. The mode='before' "
        "field_validator (BIN-104) rejects anything that is not "
        "already a str before any attribute would be read."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same as ATTRIBUTE_ACCESS_RAISES -- no attribute of a "
        "caller-supplied object is read. The constructor takes "
        "a single str value."
    ),
    InputKind.COMPARISON_RAISES: (
        "Constructing a ModelVersion compares nothing. ModelVersion "
        "values are compared elsewhere (Provenance equality inside "
        "Baseline.record and compare_provenance), but by then both "
        "sides are Caliper's own validated value objects."
    ),
}

_SCORING_CRITERIA_CASES = (
    HostileCase(
        "blank",
        lambda: ScoringCriteria(value=""),
        kind=InputKind.EMPTY_STRING,
    ),
    HostileCase(
        "whitespace_only",
        lambda: ScoringCriteria(value="\t\n"),
        kind=InputKind.EMPTY_STRING,
    ),
    HostileCase(
        "wrong_type_int",
        lambda: ScoringCriteria(value=123),  # type: ignore[arg-type]
        kind=InputKind.WRONG_TYPE,
    ),
)

_SCORING_CRITERIA_NA: Mapping[InputKind, str] = {
    InputKind.NON_FINITE_FLOAT: (
        "Has no numeric field. ScoringCriteria wraps a single str value; "
        "no float reaches its constructor or any validator."
    ),
    InputKind.OUT_OF_RANGE_VALUE: (
        "Has no bounded field. The only invariant is non-blankness, "
        "which is EMPTY_STRING's concern -- there is no range a valid "
        "string can fall outside."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "Takes a str, not a duck-typed object. The mode='before' "
        "field_validator (BIN-104) rejects anything that is not "
        "already a str before any attribute would be read."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same as ATTRIBUTE_ACCESS_RAISES -- no attribute of a "
        "caller-supplied object is read. The constructor takes "
        "a single str value."
    ),
    InputKind.COMPARISON_RAISES: (
        "Constructing a ScoringCriteria compares nothing. "
        "ScoringCriteria values are compared elsewhere (Provenance "
        "equality inside Baseline.record and compare_provenance), but "
        "by then both sides are Caliper's own validated value objects."
    ),
}

_SCORING_RESULT_CASES = (
    HostileCase(
        "nan_score",
        lambda: ScoringResult(
            score=float("nan"), reasoning="r", provenance=ProvenanceFactory()
        ),
        kind=InputKind.NON_FINITE_FLOAT,
    ),
    HostileCase(
        "infinite_score",
        lambda: ScoringResult(
            score=float("inf"), reasoning="r", provenance=ProvenanceFactory()
        ),
        kind=InputKind.NON_FINITE_FLOAT,
    ),
    HostileCase(
        "wrong_type_score",
        lambda: ScoringResult(
            score="not a float",  # type: ignore[arg-type]
            reasoning="r",
            provenance=ProvenanceFactory(),
        ),
        kind=InputKind.WRONG_TYPE,
    ),
)

_SCORING_RESULT_NA: Mapping[InputKind, str] = {
    InputKind.EMPTY_STRING: (
        "The only string field is reasoning, which has no non-blank "
        "requirement (ADR-006 section 7: 'No constraint is placed on "
        "reasoning content'). score is a float and provenance is a "
        "Provenance -- neither is a string. An empty reasoning is a "
        "valid ScoringResult."
    ),
    InputKind.OUT_OF_RANGE_VALUE: (
        "score is 'unconstrained but must be finite' (ADR-006 OQ-2). "
        "There is no range to fall outside -- every finite float is a "
        "valid score. The finiteness check is NON_FINITE_FLOAT, not a "
        "range bound."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "Takes concrete Pydantic types: float for score, str for "
        "reasoning, Provenance for provenance. No duck-typed object "
        "is ever probed for attributes -- the mode='before' "
        "field_validators (BIN-104) reject anything that is not the "
        "expected type before any attribute would be read."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same as ATTRIBUTE_ACCESS_RAISES -- no attribute of a "
        "caller-supplied object is read. All three constructor "
        "parameters are concrete types validated at the Pydantic "
        "boundary."
    ),
    InputKind.COMPARISON_RAISES: (
        "Constructing a ScoringResult compares nothing. ScoringResult "
        "values are compared later (Provenance equality in "
        "Baseline.record and compare_provenance), but by then both "
        "sides are Caliper's own validated value objects."
    ),
}

_PROVENANCE_CASES = (
    HostileCase(
        "wrong_type_model_version",
        lambda: Provenance(
            model_version="not a ModelVersion",  # type: ignore[arg-type]
            scoring_criteria=ScoringCriteriaFactory(),
        ),
        kind=InputKind.WRONG_TYPE,
    ),
)

# The sparsest entry point in the registry -- one case, five excuses. It is
# the honest worst case for the grid's cost, and the reasons are still
# specific: `Provenance` is a two-field frozen value object over two other
# value objects, so most kinds genuinely cannot reach it.
_PROVENANCE_NA: Mapping[InputKind, str] = {
    InputKind.EMPTY_STRING: (
        "Holds ModelVersion and ScoringCriteria, not str -- deliberately, "
        "per ADR-006: `Provenance holds ModelVersion and ScoringCriteria, "
        "not str, and has no field validator of its own` because those "
        "value objects already cannot hold blank text. A blank string "
        "cannot reach this constructor without first being rejected by "
        "one of them, which ModelVersion/ScoringCriteria cover here."
    ),
    InputKind.NON_FINITE_FLOAT: (
        "Has no numeric field. Both fields are value objects "
        "(ModelVersion and ScoringCriteria), each wrapping a str."
    ),
    InputKind.OUT_OF_RANGE_VALUE: (
        "Has no bounded field. Both fields are value objects whose only "
        "invariant is non-blankness, which is EMPTY_STRING's concern and "
        "theirs to enforce, not a range."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "Takes no duck-typed object. Both fields are concrete Pydantic "
        "value-object types, coerced and validated at construction; a "
        "structural look-alike is rejected as WRONG_TYPE above rather "
        "than having its attributes read."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same reason as ATTRIBUTE_ACCESS_RAISES -- no attribute of a "
        "caller-supplied object is ever read."
    ),
    InputKind.COMPARISON_RAISES: (
        "Constructing a Provenance compares nothing. Provenance values ARE "
        "compared, but by Baseline.record() and compare_provenance(), "
        "which carry that kind themselves -- and by then both sides are "
        "Caliper's own value objects."
    ),
}

_MONITOR_CASES = (
    HostileCase(
        "construct_wrong_type",
        lambda: Monitor(
            artefact="not an artefact"  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "construct_none",
        lambda: Monitor(artefact=None),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "construct_structural_third_party",
        lambda: Monitor(artefact=_ThirdPartyArtefact()),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "record_wrong_type_observation",
        lambda: Monitor(_FITTED_EWMA).record(
            None  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "record_hostile_raising_attribute",
        lambda: Monitor(_FITTED_EWMA).record(
            _RaisingScoreCandidate()  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.ATTRIBUTE_ACCESS_RAISES,
    ),
    HostileCase(
        "record_provenance_mismatch",
        lambda: Monitor(_FITTED_EWMA).record(_mismatched_scoring_result()),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "cusum_sigma_underflow_reaching_record_regression_bin119",
        _cusum_monitor_record_after_sigma_underflow,
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "record_absorbs_raising_repr_receiver",
        lambda: Monitor(_FITTED_EWMA, receivers=[_RaisingReprReceiver()]).record(
            _matching_scoring_result(score=_FITTED_EWMA.ucl + 1000.0)
        ),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
)

_MONITOR_NA: Mapping[InputKind, str] = {
    InputKind.EMPTY_STRING: (
        "Takes no string parameter. __init__ takes a FittedControlLimits "
        "artefact (narrowed to three concrete types via isinstance), a "
        "bool, and a sequence of callables. record() takes a "
        "ScoringResult (isinstance check). No string reaches either "
        "entry point directly."
    ),
    InputKind.NON_FINITE_FLOAT: (
        "Takes no direct numeric parameter. The only float is "
        "ScoringResult.score, which its own @field_validator rejects "
        "as non-finite before Monitor.record() ever sees it (ADR-006 "
        "OQ-2). Monitor's chart-specific arithmetic operates on "
        "already-validated ScoringResult.score values."
    ),
    InputKind.OUT_OF_RANGE_VALUE: (
        "Takes no bounded numeric parameter. retain_history is a bool "
        "(configuration, not an SPC quantity); receivers is a sequence "
        "of callables. Neither has a range to fall outside. The "
        "artefact's own parameters (ARL, sigma, etc.) are already "
        "validated at fit time."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Monitor.__init__'s isinstance check narrows the artefact to "
        "one of three concrete Pydantic types (FittedEWMA/FittedCUSUM/"
        "FittedShewhart) -- a duck-typed look-alike is rejected at the "
        "gate (construct_structural_third_party above). record()'s "
        "isinstance check requires a real ScoringResult. No duck-typed "
        "object survives to have its attributes read for their values."
    ),
    InputKind.COMPARISON_RAISES: (
        "Monitor.record() delegates provenance comparison to "
        "compare_provenance(), but by then both sides are Caliper's "
        "own types: the artefact is a concrete Fitted* (narrowed at "
        "construction) and the observation is a real ScoringResult "
        "(isinstance check). No caller-supplied object whose "
        "__eq__/__ne__ could raise reaches a comparison."
    ),
}

_COMPARE_PROVENANCE_CASES = (
    HostileCase(
        "matching_provenance",
        lambda: compare_provenance(_matching_scoring_result(), _FITTED_EWMA),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "mismatched_provenance",
        lambda: compare_provenance(_mismatched_scoring_result(), _FITTED_EWMA),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "wrong_type_artefact",
        lambda: compare_provenance(_matching_scoring_result(), 123),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "hostile_artefact_raising_on_access",
        lambda: compare_provenance(
            _matching_scoring_result(),
            _RaisingProvenanceArtefact(),
        ),
        kind=InputKind.ATTRIBUTE_ACCESS_RAISES,
    ),
    # 🚨 The two cases BIN-136 exists for. Both were absent while this
    # entry point was registered, exercised and reported clean.
    HostileCase(
        "artefact_provenance_returns_non_str",
        lambda: compare_provenance(
            _matching_scoring_result(),
            _NonStrProvenanceArtefact(),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.ATTRIBUTE_RETURNS_HOSTILE,
    ),
    HostileCase(
        "artefact_provenance_comparison_raises",
        lambda: compare_provenance(
            _matching_scoring_result(),
            _HostileComparisonArtefact(),
        ),
        kind=InputKind.COMPARISON_RAISES,
    ),
)

_COMPARE_PROVENANCE_NA: Mapping[InputKind, str] = {
    InputKind.OUT_OF_RANGE_VALUE: (
        "Takes no bounded value. Comparison is exact string equality on "
        "two dimensions; neither has a range to fall outside."
    ),
    InputKind.EMPTY_STRING: (
        "Takes no string argument. Both parameters are objects; the only "
        "strings reached are ModelVersion.value/ScoringCriteria.value, "
        "which their own value objects already reject when blank "
        "(BIN-57, BIN-58) and which ScoringCriteria/ModelVersion cover here."
    ),
    InputKind.NON_FINITE_FLOAT: (
        "Takes no numeric argument. Provenance comparison is exact string "
        "equality on two dimensions (`Criteria equality is exact`); no "
        "float reaches this call."
    ),
}

_FIT_EWMA_CASES = (
    HostileCase(
        "missing_target_arl",
        lambda: fit_ewma(_BASELINE, target_arl=None),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "nan_target_arl",
        lambda: fit_ewma(_BASELINE, target_arl=math.nan),
        kind=InputKind.NON_FINITE_FLOAT,
    ),
    HostileCase(
        "out_of_range_target_arl",
        lambda: fit_ewma(_BASELINE, target_arl=50.0),
        kind=InputKind.OUT_OF_RANGE_VALUE,
    ),
    HostileCase(
        "sigma_overflow_regression_bin119",
        lambda: fit_ewma(
            baseline_from_scores(_SIGMA_OVERFLOW_SCORES), target_arl=370.0
        ),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "sigma_underflow_regression_bin119",
        lambda: fit_ewma(
            baseline_from_scores(_SIGMA_UNDERFLOW_SCORES), target_arl=370.0
        ),
        kind=InputKind.REGRESSION_ANCHOR,
    ),
    HostileCase(
        "wrong_type_baseline",
        lambda: fit_ewma(
            "not a baseline",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            target_arl=370.0,
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "wrong_type_smoothing_param",
        lambda: fit_ewma(
            _BASELINE,
            target_arl=370.0,
            smoothing_param="not a float",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "out_of_range_smoothing_param",
        lambda: fit_ewma(_BASELINE, target_arl=370.0, smoothing_param=5.0),
        kind=InputKind.OUT_OF_RANGE_VALUE,
    ),
)

_FIT_EWMA_NA: Mapping[InputKind, str] = {
    InputKind.EMPTY_STRING: (
        "Takes Baseline and floats only -- no string parameter. "
        "smoothing_param and target_arl are floats; baseline is "
        "a Baseline instance. No string reaches this call."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "baseline is narrowed to Baseline via require_type() "
        "(parameter_guards) before any attribute is accessed. "
        "smoothing_param and target_arl are scalar floats validated "
        "by require_real_number(). No duck-typed object survives "
        "to have its attributes probed."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same as ATTRIBUTE_ACCESS_RAISES -- no attribute of a "
        "caller-supplied duck-typed object is read. baseline is "
        "type-checked, and both numeric parameters are scalar floats."
    ),
    InputKind.COMPARISON_RAISES: (
        "fit_ewma() compares nothing caller-supplied. Numeric "
        "comparisons are against constants (MIN_TARGET_ARL, "
        "MAX_MEANINGFUL_ARL, smoothing param bounds), never against "
        "another caller-supplied object."
    ),
}

_FIT_CUSUM_CASES = (
    HostileCase(
        "missing_target_arl",
        lambda: fit_cusum(_BASELINE, target_arl=None),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "nan_target_arl",
        lambda: fit_cusum(_BASELINE, target_arl=math.nan),
        kind=InputKind.NON_FINITE_FLOAT,
    ),
    HostileCase(
        "wrong_type_baseline",
        lambda: fit_cusum(
            "not a baseline",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            target_arl=370.0,
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "wrong_type_reference_value",
        lambda: fit_cusum(
            _BASELINE,
            target_arl=370.0,
            reference_value="not a float",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "invalid_direction",
        lambda: fit_cusum(_BASELINE, target_arl=370.0, direction="bogus"),
        kind=InputKind.OUT_OF_RANGE_VALUE,
    ),
    HostileCase(
        "unattainable_target_arl",
        lambda: fit_cusum(_BASELINE, target_arl=1.0, reference_value=5.0),
        kind=InputKind.OUT_OF_RANGE_VALUE,
    ),
)

_FIT_CUSUM_NA: Mapping[InputKind, str] = {
    InputKind.EMPTY_STRING: (
        "Takes Baseline, floats, and a direction string from a fixed "
        "set ('two_sided'/'upper'/'lower'). direction is validated "
        "against _VALID_DIRECTIONS membership, not as freeform text -- "
        "an empty string is rejected the same way 'bogus' is "
        "(invalid_direction above), which is OUT_OF_RANGE_VALUE, not "
        "EMPTY_STRING. No parameter accepts freeform text."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "baseline is narrowed to Baseline via require_type() "
        "(parameter_guards) before any attribute is accessed. "
        "target_arl and reference_value are scalar floats validated "
        "by require_real_number(). direction is a str checked "
        "against a fixed set. No duck-typed object survives to have "
        "its attributes probed."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same as ATTRIBUTE_ACCESS_RAISES -- no attribute of a "
        "caller-supplied duck-typed object is read. All parameters "
        "are concrete types validated before use."
    ),
    InputKind.COMPARISON_RAISES: (
        "fit_cusum() compares nothing caller-supplied against another "
        "caller-supplied object. Numeric comparisons are against "
        "constants (MIN_TARGET_ARL, reference_value bounds); "
        "direction is compared against a frozenset of string "
        "literals. No __eq__/__ne__ on caller-supplied objects is "
        "invoked."
    ),
}

_FIT_SHEWHART_CASES = (
    HostileCase(
        "missing_target_arl",
        lambda: fit_shewhart(_BASELINE, target_arl=None),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "nan_target_arl",
        lambda: fit_shewhart(_BASELINE, target_arl=math.nan),
        kind=InputKind.NON_FINITE_FLOAT,
    ),
    HostileCase(
        "out_of_range_target_arl",
        lambda: fit_shewhart(_BASELINE, target_arl=50.0),
        kind=InputKind.OUT_OF_RANGE_VALUE,
    ),
    HostileCase(
        "wrong_type_baseline",
        lambda: fit_shewhart(
            "not a baseline",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            target_arl=370.0,
        ),
        kind=InputKind.WRONG_TYPE,
    ),
    HostileCase(
        "wrong_type_target_arl",
        lambda: fit_shewhart(
            _BASELINE,
            target_arl="not a float",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        kind=InputKind.WRONG_TYPE,
    ),
)

_FIT_SHEWHART_NA: Mapping[InputKind, str] = {
    InputKind.EMPTY_STRING: (
        "Takes Baseline and a float only -- no string parameter. "
        "Unlike fit_cusum, there is no direction discriminator or "
        "any other string input."
    ),
    InputKind.ATTRIBUTE_ACCESS_RAISES: (
        "baseline is narrowed to Baseline via require_type() "
        "(parameter_guards) before any attribute is accessed. "
        "target_arl is a scalar float validated by "
        "require_real_number(). No duck-typed object survives "
        "to have its attributes probed."
    ),
    InputKind.ATTRIBUTE_RETURNS_HOSTILE: (
        "Same as ATTRIBUTE_ACCESS_RAISES -- no attribute of a "
        "caller-supplied duck-typed object is read. Both parameters "
        "are concrete types validated before use."
    ),
    InputKind.COMPARISON_RAISES: (
        "fit_shewhart() compares nothing caller-supplied against "
        "another caller-supplied object. The only comparison is "
        "target_arl against numeric constants (MIN_TARGET_ARL, "
        "MAX_MEANINGFUL_ARL). No __eq__/__ne__ on caller-supplied "
        "objects is invoked."
    ),
}

EXERCISABLE: tuple[ExercisableEntryPoint, ...] = (
    ExercisableEntryPoint("Baseline", _BASELINE_CASES, _BASELINE_NA),
    ExercisableEntryPoint("Judge", _JUDGE_CASES, _JUDGE_NA),
    ExercisableEntryPoint("ModelVersion", _MODEL_VERSION_CASES, _MODEL_VERSION_NA),
    ExercisableEntryPoint(
        "ScoringCriteria", _SCORING_CRITERIA_CASES, _SCORING_CRITERIA_NA
    ),
    ExercisableEntryPoint("ScoringResult", _SCORING_RESULT_CASES, _SCORING_RESULT_NA),
    ExercisableEntryPoint("Provenance", _PROVENANCE_CASES, _PROVENANCE_NA),
    ExercisableEntryPoint("Monitor", _MONITOR_CASES, _MONITOR_NA),
    ExercisableEntryPoint(
        "compare_provenance", _COMPARE_PROVENANCE_CASES, _COMPARE_PROVENANCE_NA
    ),
    ExercisableEntryPoint("fit_ewma", _FIT_EWMA_CASES, _FIT_EWMA_NA),
    ExercisableEntryPoint("fit_cusum", _FIT_CUSUM_CASES, _FIT_CUSUM_NA),
    ExercisableEntryPoint("fit_shewhart", _FIT_SHEWHART_CASES, _FIT_SHEWHART_NA),
)

# ---------------------------------------------------------------------------
# Excluded entry points -- every reason is a stated design fact, not a shrug.
# ---------------------------------------------------------------------------

EXCLUDED: tuple[ExcludedEntryPoint, ...] = (
    ExcludedEntryPoint(
        "CaliperError",
        "The taxonomy's base exception type. Callers catch it "
        "(`except CaliperError`); it is never itself an operation an "
        "engineer invokes with adversarial input.",
    ),
    ExcludedEntryPoint(
        "DegenerateBaselineError",
        "A leaf exception type in the taxonomy. Callers catch it; "
        "constructing one directly is not a caller-invoked operation "
        "this audit's contract applies to.",
    ),
    ExcludedEntryPoint(
        "InsufficientBaselineError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason, identical for all nine leaf types.",
    ),
    ExcludedEntryPoint(
        "InvalidObservationError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason.",
    ),
    ExcludedEntryPoint(
        "InvalidParameterError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason.",
    ),
    ExcludedEntryPoint(
        "JudgeRefusalError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason. Exercised as a passthrough "
        "value via Judge's `score_judge_refusal_passthrough` case.",
    ),
    ExcludedEntryPoint(
        "MalformedResponseError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason. Exercised as a passthrough "
        "value via Judge's `score_malformed_response_passthrough` case.",
    ),
    ExcludedEntryPoint(
        "MissingPrerequisiteError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason. Exercised indirectly: Judge's "
        "`score_no_provider`/`score_no_criteria` cases confirm it is "
        "actually raised where the contract requires it.",
    ),
    ExcludedEntryPoint(
        "ProvenanceMismatchError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason. Exercised indirectly via "
        "Monitor's and compare_provenance's mismatch cases.",
    ),
    ExcludedEntryPoint(
        "ProviderError",
        "A leaf exception type in the taxonomy -- see "
        "DegenerateBaselineError's reason. Exercised as a passthrough "
        "value via Judge's `score_provider_error_passthrough` case.",
    ),
    ExcludedEntryPoint(
        "DataQualityConcern",
        "A pure output value object produced only internally by "
        "Baseline.check_sufficiency() -- never constructed by an engineer "
        "with caller-supplied input. No validators beyond field presence.",
    ),
    ExcludedEntryPoint(
        "FittingAdvisory",
        "A pure output value object produced only internally by "
        "fit_ewma()/fit_cusum()/fit_shewhart() (ADR-011) when target_arl is "
        "inside the flagged tier -- never constructed by an engineer with "
        "caller-supplied input. No validators beyond field presence, "
        "identical reasoning to DataQualityConcern above.",
    ),
    ExcludedEntryPoint(
        "DeliveryFailure",
        "A pure output value object built only internally by "
        "Monitor._deliver() from an already-caught exception -- never "
        "constructed by an engineer with caller-supplied input.",
    ),
    ExcludedEntryPoint(
        "FittedControlLimits",
        "A `@runtime_checkable` typing.Protocol, not a callable or "
        "constructible entry point -- it exists for `isinstance` checks "
        "and type hints. The concrete artefact types it describes "
        "(FittedEWMA/FittedCUSUM/FittedShewhart) are handled separately "
        "below.",
    ),
    ExcludedEntryPoint(
        "HasProvenance",
        "A `@runtime_checkable` typing.Protocol (ADR-004 amendment "
        "2026-09-12, BIN-135), not a callable or constructible entry "
        "point -- it exists for `isinstance` checks and type hints on "
        "compare_provenance's artefact parameter. A strict subset of "
        "FittedControlLimits carrying only the two provenance attributes; "
        "same exclusion reasoning as FittedControlLimits above.",
    ),
    ExcludedEntryPoint(
        "FittedEWMA",
        "An output artefact type. Its own docstring states the "
        "convention directly: 'tests obtain a FittedEWMA by calling "
        "[fit_ewma], never by constructing one directly.' fit_ewma() -- "
        "the caller-facing construction path -- is exercised directly "
        "above; hostile-constructing this type by hand would duplicate "
        "that coverage rather than exercise a distinct caller operation.",
    ),
    ExcludedEntryPoint(
        "FittedCUSUM",
        "An output artefact type -- see FittedEWMA's reason, identical "
        "for all three concrete Fitted* types (fit_cusum() is exercised "
        "directly above).",
    ),
    ExcludedEntryPoint(
        "FittedShewhart",
        "An output artefact type -- see FittedEWMA's reason (fit_shewhart() "
        "is exercised directly above).",
    ),
    ExcludedEntryPoint(
        "JudgeProviderPort",
        "A `@runtime_checkable` typing.Protocol implemented by "
        "provider-adapter authors, not called directly by an engineer -- "
        "Judge.score() is what invokes a conforming provider, and its "
        "three documented failure modes (ProviderError/"
        "MalformedResponseError/JudgeRefusalError passthrough) are "
        "exercised via Judge's cases above.",
    ),
    ExcludedEntryPoint(
        "JudgeProviderResponse",
        "A plain data carrier constructed by provider-adapter authors "
        "from their own already-parsed provider data, not by an engineer "
        "calling into Caliper's own logic. Its `.score` flows into "
        "ScoringResult's finite-score guard once Judge.score() builds "
        "the result -- exercised via Judge's "
        "`score_provider_returns_nonfinite_score` case above.",
    ),
    ExcludedEntryPoint(
        "MonitoringResult",
        "A pure output value object built only internally by "
        "Monitor.record() -- 'no public factory is specified' per its "
        "own docstring. Never constructed by an engineer with "
        "caller-supplied input.",
    ),
    ExcludedEntryPoint(
        "SignalReceiver",
        "A plain typing.TypeAlias (`Callable[[MonitoringResult], None]`), "
        "not a runtime construct at all -- there is nothing to call or "
        "construct.",
    ),
    ExcludedEntryPoint(
        "SufficiencyResult",
        "A pure output value object produced only by "
        "Baseline.check_sufficiency() -- exercised via Baseline's "
        "`check_sufficiency_*` cases above, which construct it through "
        "that one legitimate path.",
    ),
    ExcludedEntryPoint(
        "log_receiver",
        "Genuinely borderline, not silently waved through -- see the "
        "audit report's 'design boundary' note. `log_receiver` is a "
        "`SignalReceiver` implementation whose failure mode is, by "
        "ADR-010's 'absorb, but surface' design, meant to be caught by "
        "`Monitor._deliver()`'s own per-receiver try/except -- not by the "
        "receiver satisfying the CaliperError contract on its own. "
        "Verified directly (not assumed): calling `log_receiver` "
        "standalone with a MonitoringResult-shaped object whose "
        "`chart_type` raises on access leaks that raw exception "
        "unchanged, because nothing wraps it outside `Monitor`. Excluded "
        "because it is not, by design, meant to be called except from "
        "inside that wrapper -- but this is a judgement call about where "
        "the contract's boundary sits, not a fact with only one possible "
        "reading, and it is flagged as such rather than decided quietly.",
    ),
)

_EXCLUDED_NAMES = frozenset(entry.name for entry in EXCLUDED)
_EXERCISABLE_NAMES = frozenset(entry.name for entry in EXERCISABLE)
