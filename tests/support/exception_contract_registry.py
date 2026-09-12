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

**What this audit found -- read before assuming everything here is green.**
10 cases below reproduce a real, currently-live leak (BIN-126 has now closed
all eight of the original 18 -- see that ticket's completion report). Each is
annotated
with :class:`KnownLeak` (ticket + the exact exception type observed) and
the audit test turns that into ``pytest.mark.xfail(strict=True,
raises=<that type>)`` -- tracked and green, not fixed here and not
silenced. See the module docstring of
``tests/unit/test_exception_contract_audit.py`` for the full, itemised
list, the owning tickets, and why ``strict=True``/``raises=`` matter --
this docstring only explains the registry mechanism.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from caliper.baseline import (
    Baseline,
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
from tests.support.baseline_strategies import baseline_from_scores
from tests.support.fakes import FakeJudgeProviderPort

# ---------------------------------------------------------------------------
# Shared fixtures -- built once, reused across cases. `fit_ewma`'s Markov-chain
# calibration is the expensive step here (~49ms, per
# tests/unit/baseline/test_baseline_scores_strategy_contract.py's own measured
# figure) -- computing it once at import time rather than per-case keeps this
# file's runtime bounded.
# ---------------------------------------------------------------------------

# 0..4 repeating gives a spread of 4.0 -- far above
# tests/support/baseline_strategies.py's MIN_FITTABLE_SPREAD floor, and a
# plain, unremarkable baseline no different from any other test's fixture
# data. Not itself a hostile input; it exists only so the *parameters* below
# can be hostile against a baseline that would otherwise fit cleanly.
_FITTABLE_SCORES = [float(i % 5) for i in range(100)]
_BASELINE = baseline_from_scores(_FITTABLE_SCORES)

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
    a property backed by a closed resource) propagates that failure through
    ``Baseline.record``'s and ``Monitor.record``'s identical
    ``_missing_observation_fields`` helpers.
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


class _RaisingProvenanceArtefact:
    """A ``FittedControlLimits``-shaped object whose model-version property raises.

    ``compare_provenance()`` (unlike ``Monitor``) takes any object
    satisfying ``FittedControlLimits`` and reads
    ``artefact.provenance_model_version``/``artefact.provenance_criteria``
    directly -- with no guard equivalent to ``Monitor``'s ``_safe_repr``
    (``BIN-118``/``BIN-120``'s fix). This reproduces that same hazard at a
    boundary the ``BIN-118``/``BIN-120`` fixes never touched.
    """

    provenance_criteria = "criteria"

    @property
    def provenance_model_version(self) -> str:
        raise RuntimeError("boom-on-provenance-access")


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
    known_leak: KnownLeak | None = None


@dataclass(frozen=True)
class ExercisableEntryPoint:
    """A public name that is a caller-invoked operation, with its hostile cases."""

    name: str
    cases: tuple[HostileCase, ...]


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
    ),
    HostileCase(
        "record_wrong_type_int",
        lambda: Baseline().record(123),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    ),
    HostileCase(
        "record_hostile_raising_attribute",
        lambda: Baseline().record(_RaisingScoreCandidate()),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        known_leak=KnownLeak(ticket="BIN-127", leaked_type=RuntimeError),
    ),
    HostileCase(
        "check_sufficiency_zero_threshold",
        lambda: Baseline().check_sufficiency(threshold=0),
    ),
    HostileCase(
        "check_sufficiency_negative_threshold",
        lambda: Baseline().check_sufficiency(threshold=-1),
    ),
    HostileCase(
        "check_sufficiency_wrong_type_threshold",
        lambda: Baseline().check_sufficiency(
            threshold="not an int"  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
    ),
)

_JUDGE_CASES = (
    HostileCase(
        "create_missing_model_version",
        lambda: Judge.create(model_version=None),
    ),
    HostileCase(
        "create_blank_model_version",
        lambda: Judge.create(model_version="   "),
    ),
    HostileCase(
        "create_wrong_type_model_version",
        lambda: Judge.create(model_version=123),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        known_leak=KnownLeak(ticket="BIN-104", leaked_type=ValidationError),
    ),
    HostileCase(
        "create_wrong_type_criteria",
        lambda: Judge.create(
            model_version="m1",
            criteria=123,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        known_leak=KnownLeak(ticket="BIN-104", leaked_type=ValidationError),
    ),
    HostileCase(
        "score_no_provider",
        lambda: Judge.create(model_version="m1", criteria="c1").score(agent_output="x"),
    ),
    HostileCase(
        "score_no_criteria",
        lambda: Judge.create(
            model_version="m1", provider=FakeJudgeProviderPort()
        ).score(agent_output="x"),
    ),
    HostileCase(
        "score_blank_output",
        lambda: _configured_judge(provider=FakeJudgeProviderPort()).score(
            agent_output="   "
        ),
    ),
    HostileCase(
        "score_wrong_type_output",
        lambda: _configured_judge(provider=FakeJudgeProviderPort()).score(
            agent_output=123  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
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
    ),
    HostileCase(
        "score_provider_returns_nonfinite_score",
        lambda: _configured_judge(
            provider=FakeJudgeProviderPort(
                response=JudgeProviderResponse(score=float("nan"), reasoning="r")
            )
        ).score(agent_output="x"),
    ),
)

_MODEL_VERSION_CASES = (
    HostileCase("blank", lambda: ModelVersion(value="")),
    HostileCase("whitespace_only", lambda: ModelVersion(value="   ")),
    HostileCase(
        "wrong_type_int",
        lambda: ModelVersion(value=123),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        known_leak=KnownLeak(ticket="BIN-104", leaked_type=ValidationError),
    ),
    HostileCase(
        "wrong_type_none",
        lambda: ModelVersion(value=None),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        known_leak=KnownLeak(ticket="BIN-104", leaked_type=ValidationError),
    ),
)

_SCORING_CRITERIA_CASES = (
    HostileCase("blank", lambda: ScoringCriteria(value="")),
    HostileCase("whitespace_only", lambda: ScoringCriteria(value="\t\n")),
    HostileCase(
        "wrong_type_int",
        lambda: ScoringCriteria(value=123),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        known_leak=KnownLeak(ticket="BIN-104", leaked_type=ValidationError),
    ),
)

_SCORING_RESULT_CASES = (
    HostileCase(
        "nan_score",
        lambda: ScoringResult(
            score=float("nan"), reasoning="r", provenance=ProvenanceFactory()
        ),
    ),
    HostileCase(
        "infinite_score",
        lambda: ScoringResult(
            score=float("inf"), reasoning="r", provenance=ProvenanceFactory()
        ),
    ),
    HostileCase(
        "wrong_type_score",
        lambda: ScoringResult(
            score="not a float",  # type: ignore[arg-type]
            reasoning="r",
            provenance=ProvenanceFactory(),
        ),
        known_leak=KnownLeak(ticket="BIN-104", leaked_type=ValidationError),
    ),
)

_PROVENANCE_CASES = (
    HostileCase(
        "wrong_type_model_version",
        lambda: Provenance(
            model_version="not a ModelVersion",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            scoring_criteria=ScoringCriteriaFactory(),
        ),
        known_leak=KnownLeak(ticket="BIN-104", leaked_type=ValidationError),
    ),
)

_MONITOR_CASES = (
    HostileCase(
        "construct_wrong_type",
        lambda: Monitor(
            artefact="not an artefact"  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
    ),
    HostileCase(
        "construct_none",
        lambda: Monitor(artefact=None),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    ),
    HostileCase(
        "construct_structural_third_party",
        lambda: Monitor(artefact=_ThirdPartyArtefact()),
    ),
    HostileCase(
        "record_wrong_type_observation",
        lambda: Monitor(_FITTED_EWMA).record(
            None  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
    ),
    HostileCase(
        "record_hostile_raising_attribute",
        lambda: Monitor(_FITTED_EWMA).record(
            _RaisingScoreCandidate()  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        known_leak=KnownLeak(ticket="BIN-127", leaked_type=RuntimeError),
    ),
    HostileCase(
        "record_provenance_mismatch",
        lambda: Monitor(_FITTED_EWMA).record(_mismatched_scoring_result()),
    ),
    HostileCase(
        "cusum_sigma_underflow_reaching_record_regression_bin119",
        _cusum_monitor_record_after_sigma_underflow,
    ),
    HostileCase(
        "record_absorbs_raising_repr_receiver",
        lambda: Monitor(_FITTED_EWMA, receivers=[_RaisingReprReceiver()]).record(
            _matching_scoring_result(score=_FITTED_EWMA.ucl + 1000.0)
        ),
    ),
)

_COMPARE_PROVENANCE_CASES = (
    HostileCase(
        "matching_provenance",
        lambda: compare_provenance(_matching_scoring_result(), _FITTED_EWMA),
    ),
    HostileCase(
        "mismatched_provenance",
        lambda: compare_provenance(_mismatched_scoring_result(), _FITTED_EWMA),
    ),
    HostileCase(
        "hostile_artefact_raising_on_access",
        lambda: compare_provenance(
            _matching_scoring_result(),
            _RaisingProvenanceArtefact(),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
        known_leak=KnownLeak(ticket="BIN-127", leaked_type=RuntimeError),
    ),
)

_FIT_EWMA_CASES = (
    HostileCase("missing_target_arl", lambda: fit_ewma(_BASELINE, target_arl=None)),
    HostileCase("nan_target_arl", lambda: fit_ewma(_BASELINE, target_arl=math.nan)),
    HostileCase(
        "sigma_overflow_regression_bin119",
        lambda: fit_ewma(
            baseline_from_scores(_SIGMA_OVERFLOW_SCORES), target_arl=370.0
        ),
    ),
    HostileCase(
        "sigma_underflow_regression_bin119",
        lambda: fit_ewma(
            baseline_from_scores(_SIGMA_UNDERFLOW_SCORES), target_arl=370.0
        ),
    ),
    HostileCase(
        "wrong_type_baseline",
        lambda: fit_ewma(
            "not a baseline",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            target_arl=370.0,
        ),
    ),
    HostileCase(
        "wrong_type_smoothing_param",
        lambda: fit_ewma(
            _BASELINE,
            target_arl=370.0,
            smoothing_param="not a float",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
    ),
    HostileCase(
        "out_of_range_smoothing_param",
        lambda: fit_ewma(_BASELINE, target_arl=370.0, smoothing_param=5.0),
    ),
)

_FIT_CUSUM_CASES = (
    HostileCase("missing_target_arl", lambda: fit_cusum(_BASELINE, target_arl=None)),
    HostileCase(
        "wrong_type_baseline",
        lambda: fit_cusum(
            "not a baseline",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            target_arl=370.0,
        ),
    ),
    HostileCase(
        "wrong_type_reference_value",
        lambda: fit_cusum(
            _BASELINE,
            target_arl=370.0,
            reference_value="not a float",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
    ),
    HostileCase(
        "invalid_direction",
        lambda: fit_cusum(_BASELINE, target_arl=370.0, direction="bogus"),
    ),
    HostileCase(
        "unattainable_target_arl",
        lambda: fit_cusum(_BASELINE, target_arl=1.0, reference_value=5.0),
    ),
)

_FIT_SHEWHART_CASES = (
    HostileCase("missing_target_arl", lambda: fit_shewhart(_BASELINE, target_arl=None)),
    HostileCase(
        "wrong_type_baseline",
        lambda: fit_shewhart(
            "not a baseline",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            target_arl=370.0,
        ),
    ),
    HostileCase(
        "wrong_type_target_arl",
        lambda: fit_shewhart(
            _BASELINE,
            target_arl="not a float",  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        ),
    ),
)

EXERCISABLE: tuple[ExercisableEntryPoint, ...] = (
    ExercisableEntryPoint("Baseline", _BASELINE_CASES),
    ExercisableEntryPoint("Judge", _JUDGE_CASES),
    ExercisableEntryPoint("ModelVersion", _MODEL_VERSION_CASES),
    ExercisableEntryPoint("ScoringCriteria", _SCORING_CRITERIA_CASES),
    ExercisableEntryPoint("ScoringResult", _SCORING_RESULT_CASES),
    ExercisableEntryPoint("Provenance", _PROVENANCE_CASES),
    ExercisableEntryPoint("Monitor", _MONITOR_CASES),
    ExercisableEntryPoint("compare_provenance", _COMPARE_PROVENANCE_CASES),
    ExercisableEntryPoint("fit_ewma", _FIT_EWMA_CASES),
    ExercisableEntryPoint("fit_cusum", _FIT_CUSUM_CASES),
    ExercisableEntryPoint("fit_shewhart", _FIT_SHEWHART_CASES),
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
