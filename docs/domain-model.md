---
created: 2026-09-09
updated: 2026-09-10
feature: BIN-100 — Domain model — aggregates, ubiquitous language, value objects
bounded_context: measurement, baseline
canonical: true
---

# Domain Model: Caliper SPC Library

> **Canonical copy.** This file (`docs/domain-model.md`, in the repo, reviewed
> via PR like any other source change) is the canonical domain model.
> `Projects/caliper/domain-model.md` in the Obsidian vault had drifted from
> this file by the time of this refresh (BIN-100) — the vault copy was
> missing three glossary rows (`Requested ARL`, `Achieved ARL`, `Signal`), the
> entire Validation Checklist section, and several detail sentences (specific
> ticket/scenario citations in the Error Contract Reference and Open
> Questions tables) that this copy has and it does not. Neither copy was
> "ahead" on substance — both reflected the same 2026-09-09 amendment — the
> vault copy was simply a lossier hand-condensation of this one made at the
> same time. Rather than re-reconcile two editable copies indefinitely (the
> same structural problem CLAUDE.md's "Structural cause not addressed" note
> already flags for scenarios existing in three places), the vault copy has
> been replaced with a pointer to this file. This file is the one to read,
> edit, and cite going forward.
>
> **Human gate note:** most of what this document presented as open when it
> was first written yesterday is now settled — ADR-006 closed four of the
> eleven original Open Questions the same day E1 shipped. The only question
> below that is a live product decision, as opposed to something an E2 story
> will settle when it gets there, is **OQ-9** (provenance-change override
> between Phase I and Phase II). See the Open Questions section.

---

## E1 Status — Implemented, Tested, Merged

Everything the Measurement context describes below (`Judge`, `ModelVersion`,
`ScoringCriteria`, `Provenance`, `ScoringResult`, `JudgeProviderPort`) is
implemented in `src/caliper/measurement/`, per the module layout BIN-103
introduced:

```
src/caliper/errors.py                        # shared across bounded contexts
src/caliper/measurement/domain/
    criteria.py         # ScoringCriteria
    judge.py             # Judge
    model_version.py     # ModelVersion
    provenance.py         # Provenance
    result.py             # ScoringResult
src/caliper/measurement/ports/
    judge_provider.py     # JudgeProviderPort, JudgeProviderResponse
```

Where this document and the code disagree, **the code is right** — this
refresh corrects the document to match it. The Baseline context (`Baseline`,
`FittedControlLimits` and its chart-specific artefacts) remains unimplemented
design at this point; nothing in this refresh changes that part of the model.

## Bounded Contexts

Two bounded contexts, visible in the feature-file directory layout (`tests/bdd/features/`).

### Measurement

**Responsible for:** creating judges with pinned model versions, defining scoring criteria, scoring agent outputs, and producing structured results with provenance.

**Stories:** BIN-57 (judge adapter), BIN-58 (scoring criteria), BIN-59 (scoring and structured results).

**Boundary:** ends at the production of a `ScoringResult`. The Measurement context knows nothing about baselines, fitting, or control charts. Its output — the `ScoringResult` with its `Provenance` — is the input to the Baseline context.

### Baseline

**Responsible for:** collecting Phase I observations, checking sufficiency, fitting control limits (EWMA, CUSUM, Shewhart), reviewing fitted artefacts, and comparing provenance across the Phase I/II boundary.

**Stories:** BIN-63 (collection), BIN-64 (sufficiency), BIN-65 (EWMA fitting), BIN-66 (review), BIN-68 (provenance comparison), BIN-94 (CUSUM fitting), BIN-95 (Shewhart fitting).

**Boundary:** begins where a `ScoringResult` enters the baseline; ends at the fitted artefact and Phase II provenance comparison. The Baseline context depends on Measurement's `ScoringResult` and `Provenance` value objects.

### Cross-context dependency

Baseline depends on Measurement. Measurement is independent. The shared vocabulary between contexts is `ScoringResult` and `Provenance` — both are immutable value objects, so the dependency is on stable, frozen types.

---

## Structural Departures from Service-Oriented DDD

Caliper is a library, not a service. Several standard DDD constructs have no referent here. Forcing them would produce a model that misleads implementers.

| Construct | Status | Reason |
|-----------|--------|--------|
| Aggregate root with transactional boundary | **Does not apply.** | No transactions exist. The library operates synchronously in-process. The closest analogue is the `Baseline` collection, which enforces invariants on its contents — but there is no unit of work, no commit, and no rollback. |
| Repository (DDD sense) | **Does not apply in R1.** | R1 is in-memory only (BIN-72 is a separate story for in-memory store; BIN-73 for SQLite). There is no persistence to abstract over. The store port is an R2 concern. |
| Domain events | **None in R1's specified scope.** | The ten feature files establish a synchronous call-and-return pattern. The signal handler chain (E4: BIN-75 through BIN-81) has no written requirements. `context.md` sketches a `SignalEvent`, but E4 is not yet specified. Inventing events for unspecified behaviour would be worse than omitting them. |
| Identity (UUID) | **Not needed.** | All objects are in-process references held by the engineer's code. There is no persistence, no lookup-by-ID, no cross-process references. Every object is identified by the variable that holds it. Inventing UUIDs would add complexity with no consumer. If R2 persistence (BIN-72/73) requires identity, it should be added then — not pre-emptively. |
| Multi-tenancy / `org_id` | **Does not apply.** | Caliper is a single-process library. There is no tenancy. |

**What the model provides instead:** the objects an engineer manipulates in code, their invariants, their immutability guarantees, and the two bounded contexts that organise them.

---

## Object Map

### Baseline — the one mutable collection

The `Baseline` is the only mutable object in the domain. Everything else is immutable after creation.

**What it is:** an ordered collection of `ScoringResult` observations recorded under consistent provenance, from which control limits are fitted.

**Invariants:**

1. **Provenance homogeneity.** All observations must share the same provenance (model version and scoring criteria). The first recorded observation establishes the baseline's provenance signature; subsequent observations whose provenance differs are rejected with `ProvenanceMismatchError`. This is the primary guard against baseline contamination — mixing measurements from different instruments silently invalidates control limits.

2. **Insertion order is arithmetic, not presentational.** Observations are stored in the order they were recorded (BIN-63 BR-2). This ordering is load-bearing: the Shewhart I-chart's sigma estimate is computed from consecutive differences (BIN-95 BR-7), so reordering the same observations changes the moving range, the sigma estimate, and therefore the control limits. EWMA and CUSUM are also sequential — shuffled observations produce different chart statistics.

3. **Observation immutability.** Once recorded, an observation cannot be modified (BIN-63 BR-3). Observations are historical measurement records; modifying one would break the audit chain and could invalidate control limits fitted from the baseline.

4. **Recording requires a complete `ScoringResult`.** Attempting to record an input that is not a complete scoring result (score, reasoning, provenance) is rejected with `InvalidObservationError` before the baseline is modified.

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `observations` | `Sequence[ScoringResult]` | Ordered, append-only in R1 |
| `provenance_signature` | `Provenance | None` | `None` when empty; set by the first recorded observation |
| `observation_count` | `int` | Derived from `len(observations)` |

**Operations on Baseline:**

| Operation | Input | Output | Errors |
|-----------|-------|--------|--------|
| `record(result)` | `ScoringResult` | `None` (mutates baseline) | `ProvenanceMismatchError`, `InvalidObservationError` |
| `check_sufficiency(threshold?, chart_type?)` | Optional threshold override, optional chart type | `SufficiencyResult` | `InvalidParameterError` (non-positive threshold) |
| `len(baseline)`, `iter(baseline)`, `repr(baseline)` | — | `int`, iterator of `ScoringResult`, `str` | — |
| Read: inspect count, inspect provenance signature | — | — | — |

**Baseline is a collection; result types are not (BIN-110).** `Baseline`
implements `__len__`, `__iter__` and `__repr__`, so it behaves the way an
engineer already expects a container to behave — including being falsy when
empty, which Python derives from `__len__` without a `__bool__` of its own.
Iteration yields from the same fresh tuple `observations` returns, so no
caller reaches the mutable internal list.

`SufficiencyResult` defines `__bool__` returning `is_sufficient`. Before
BIN-110 it inherited object identity truthiness, so `if
baseline.check_sufficiency():` was always true and would fit control limits
from an empty baseline — authoritative-looking limits derived from nothing,
the exact failure this library exists to prevent.

`ScoringResult` and the three fitted artefacts raise `TypeError` from
`__bool__`. None of them has a “failed” instance, so any truth value would
have to be invented; leaving Python's default would relocate the same trap
onto four more types. The rule is: truthiness is forbidden unless a yes/no
field already carries the meaning.

**Design note:** The Baseline has aggregate-like properties (enforces invariants on its contents, controls access to its observations) without the transactional semantics that define an aggregate in DDD. No transaction wraps a `record()` call; the invariant is enforced synchronously in a single-threaded library call.

---

### Judge — immutable configured adapter

The `Judge` is the measurement instrument. It wraps an LLM provider (behind a
port — see below), holds a pinned model version, optionally holds judge-level
scoring criteria, and scores agent outputs against criteria.

**Not a traditional entity:** the Judge has no lifecycle beyond creation, no mutable state, and no need for identity. Two judges with the same model version configured against the same provider are functionally interchangeable.

**Not a pure value object:** the Judge has side-effecting behaviour — calling an LLM provider to score. It sits at the boundary between the domain and the external world.

**Best characterised as:** an immutable configured adapter behind a port boundary. The domain model defines its configuration contract; the implementation is an adapter concern.

**Implemented** (`src/caliper/measurement/domain/judge.py`, BIN-59/ADR-006). A
Pydantic `BaseModel` with `ConfigDict(frozen=True, arbitrary_types_allowed=True)`
— `arbitrary_types_allowed` is required because `provider` is typed as
`JudgeProviderPort`, a `Protocol`, which Pydantic cannot build a validation
schema for; it is `@runtime_checkable`, so Pydantic still isinstance-checks a
supplied provider against the protocol's method set rather than accepting
anything.

**Configuration constraints:**

| Field | Type | Constraint | Source |
|-------|------|-----------|--------|
| `model_version` | `ModelVersion` | Required (by Caliper validation, not the Python signature), non-empty, immutable, preserved exactly as provided | BIN-57 |
| `provider` | `JudgeProviderPort \| None` | Optional at creation. A functional dependency, not user data — no scenario tests "create with no provider" as a structured-error case, so it is not wrapped in optional-with-required-semantics the way `model_version` is. Its absence surfaces as `MissingPrerequisiteError` at `score()` time. | ADR-006 §2 |
| `criteria` | `ScoringCriteria \| None` | Optional at creation. May also be supplied (or overridden, for that call only) per call to `score()`. **Settles former OQ-1** — see Open Questions. | ADR-006 §2, BIN-58 |

**Operations:**

| Operation | Input | Output | Errors |
|-----------|-------|--------|--------|
| `create(model_version, provider=None, criteria=None)` | `model_version: str \| None` (optional-with-required-semantics — `None` raises), `provider`, `criteria` (both genuinely optional) | `Judge` | `InvalidParameterError` (`kind="missing"` when `model_version` omitted; `kind="invalid"` when empty/whitespace-only, raised from `ModelVersion`'s validator; also raised from `ScoringCriteria`'s validator if `criteria` is supplied but blank) |
| `score(agent_output, *, agent_input=None, criteria=None)` | `agent_output: str` (required, positional); `agent_input: str \| None` (optional, not validated for emptiness, **not** carried onto `Provenance` or `ScoringResult`); `criteria: str \| None` (per-call override, does not mutate the frozen `Judge`) | `ScoringResult` | `MissingPrerequisiteError` (no provider configured; or no criteria resolvable from either the call or the judge — checked in that order, both before any provider call), `InvalidParameterError` (`agent_output` empty/whitespace-only — **settles former OQ-10**), `ProviderError`, `MalformedResponseError`, `JudgeRefusalError` (all propagated unchanged from the provider) |
| Inspect | — | `model_version`, `provider`, `criteria` | — |

**Criteria resolution order inside `score()`** (ADR-006 §2): per-call
`criteria` argument, if given → else judge-level `self.criteria`, if set → else
raise `MissingPrerequisiteError` before the provider is ever called. "Monitoring
setup" is explicitly **not** a third attachment point in R1 — no `Monitor`
construct exists anywhere in this domain model, and inventing one to give
criteria a third home would design beyond what BIN-59 asked for. If a
monitor-like construct is introduced later (R2 decorator/context-manager
stories), it becomes an additive fourth fallback in the same resolution order,
not a redesign.

**`agent_output` vs `agent_input` naming** is deliberate, not a stylistic
choice: bare `input` shadows a Python builtin and this project's `ruff`
configuration (`flake8-builtins`, rule `A002`) rejects it. The `agent_` prefix
also matches the feature files' own ubiquitous language ("agent output",
"agent input").

---

### The judge provider port — `JudgeProviderPort`

A **real hexagonal port** (`src/caliper/measurement/ports/judge_provider.py`,
ADR-006 §1) — the seam between `Judge` and whatever actually calls an LLM. No
concrete adapter exists yet; only `FakeJudgeProviderPort` (test code,
`tests/support/fakes.py`) implements it, which is what makes `Judge.score()`
testable without a network call.

```python
@runtime_checkable
class JudgeProviderPort(Protocol):
    def score(
        self,
        *,
        model_version: str,
        criteria: str,
        agent_output: str,
        agent_input: str | None = None,
    ) -> JudgeProviderResponse: ...
```

The port returns an already-parsed `(score, reasoning)` pair
(`JudgeProviderResponse`), not a raw provider payload — interpreting a
provider's structured-output shape (OpenAI JSON mode, Anthropic tool use, or
anything else) is an infrastructure concern specific to each provider's API,
and belongs in the adapter, not in `Judge`. This mirrors the `SPCPort` pattern
ADR-001 already established.

`JudgeProviderResponse` is a value object in its own right — a frozen Pydantic
`BaseModel` (`score: float`, `reasoning: str`) — internal to `Judge.score()`'s
orchestration and not exposed to the engineer; `Judge.score()` attaches
`Provenance` after receiving it.

**Exception contract** (normative on the Protocol, not expressible in Python's
type system): a conforming implementation raises `ProviderError` if the
provider call fails or is unreachable, `MalformedResponseError` if the
response can't be interpreted as a `(score, reasoning)` pair, or
`JudgeRefusalError` if the provider declines on content/safety grounds.
`MissingPrerequisiteError` is never raised by the port itself — it is raised
by `Judge.score()` before the port is ever called.

**No retry inside the library in R1** (ADR-006 §4, settling BIN-59 OQ-4,
which this document did not previously carry as a numbered open question but
is worth recording here since it bears directly on the port's contract): a
`JudgeProviderPort` implementation calls the provider once from Caliper's
point of view and raises immediately on failure; `Judge.score()` does not
catch and retry. Retry, if ever added, lives entirely inside a future
concrete adapter (e.g. wrapped with `stamina`) — additive, not a change to
the port contract.

---

## Fitted Artefact Protocol (ADR-004)

The fitted artefact is the immutable record produced by fitting control limits from a Phase I baseline. It carries everything needed for Phase II monitoring and auditability.

### Shared Core — `FittedControlLimits` Protocol

Mechanism: `typing.Protocol` with `@runtime_checkable` (ADR-004 section 1). Concrete chart artefacts satisfy it structurally — no base class inheritance required.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class FittedControlLimits(Protocol):
    """Consumer contract for any fitted artefact, regardless of chart type."""

    @property
    def chart_type(self) -> str: ...

    @property
    def baseline_mean(self) -> float: ...

    @property
    def baseline_spread(self) -> float:
        """Sample standard deviation of Phase I scores.

        A descriptive statistic capturing TOTAL variation in the baseline,
        including any slow drift. Useful for characterising the data, but
        NOT the sigma used for control limit computation — see
        sigma_estimate below and the dual-spread note.
        """
        ...

    @property
    def sigma_estimate(self) -> float:
        """Moving-range-based sigma estimate (MR-bar / d_2).

        The OPERATIONAL sigma used by ALL chart types for control limit
        computation on individual observations. Captures SHORT-TERM
        variation only, robust to slow drift within the baseline.
        This is a DIFFERENT quantity from baseline_spread — see the
        dual-spread note below.
        """
        ...

    @property
    def sigma_estimation_method(self) -> str:
        """Identifies how sigma_estimate was computed.

        For R1 (individual observations, moving-range span 2):
        'moving_range' in all cases. Reported for auditability.
        """
        ...

    @property
    def observation_count(self) -> int: ...

    @property
    def provenance_model_version(self) -> str: ...

    @property
    def provenance_criteria(self) -> str: ...

    @property
    def requested_arl(self) -> float:
        """The target ARL_0 the engineer specified."""
        ...

    @property
    def achieved_arl(self) -> float:
        """The ARL_0 actually produced by the calibration.
        May differ from requested due to numerical approximation."""
        ...

    @property
    def calibration_method(self) -> str: ...
```

**Immutability** is a structural constraint on the concrete type (frozen dataclass, `ConfigDict(frozen=True)`, `__setattr__` override), not a protocol property. All three fitting stories require immutability (BIN-65 BR-10, BIN-94 BR-11, BIN-95 BR-12).

### Detection boundaries are chart-specific (ADR-004 section 3)

Detection boundaries are deliberately excluded from the shared protocol. The shapes differ structurally:

- **EWMA and Shewhart:** UCL, LCL, CL — on the observation scale.
- **CUSUM:** Decision interval *h* compared against the accumulating statistic *S* — not on the observation scale.

A common representation would misrepresent CUSUM's decision interval as an observation-scale limit. Consumers that need detection boundaries narrow to the concrete type — this is by design, because the comparison logic is necessarily chart-specific.

### Chart-Specific Artefacts

#### FittedEWMA

| Field | Type | Notes |
|-------|------|-------|
| *(shared core)* | | All FittedControlLimits properties |
| `smoothing_param` | `float` | Lambda; library default when not specified |
| `ucl` | `float` | Upper control limit |
| `lcl` | `float` | Lower control limit |
| `cl` | `float` | Centre line (= baseline mean) |

#### FittedCUSUM

| Field | Type | Notes |
|-------|------|-------|
| *(shared core)* | | All FittedControlLimits properties (including `sigma_estimate` — the MR-based sigma used for CUSUM standardisation) |
| `reference_value` | `float` | *k* — shift size to detect, in sigma units (of the shared `sigma_estimate`) |
| `decision_interval` | `float` | *h* — derived from *k* and target ARL_0 via Siegmund's approximation; the engineer does not specify this directly |
| `target_value` | `float` | mu_0 — typically the baseline mean |
| `direction` | `str` | `"two_sided"` (default), `"lower"`, or `"upper"` |

#### FittedShewhart

| Field | Type | Notes |
|-------|------|-------|
| *(shared core)* | | All FittedControlLimits properties (including `sigma_estimate` — the MR-based sigma, same as EWMA and CUSUM) |
| `sigma_multiplier` | `float` | *k* — number of sigma units defining control limits; derived from the false alarm tolerance, not engineer-specified |
| `ucl` | `float` | Upper control limit = `baseline_mean + sigma_multiplier * sigma_estimate` |
| `lcl` | `float` | Lower control limit = `baseline_mean - sigma_multiplier * sigma_estimate` |
| `cl` | `float` | Centre line (= baseline mean) |

### The Dual-Spread Distinction — All Charts (corrected from ADR-004 finding)

Every fitted artefact carries **two** spread-related quantities in the shared core. They are different quantities that answer different questions:

| Field | Source | What it captures | How it is computed |
|-------|--------|------------------|--------------------|
| `baseline_spread` (shared core) | Sample standard deviation of all Phase I scores | **Total** variation, including any slow drift within the baseline | Standard sample std dev formula over all observations |
| `sigma_estimate` (shared core) | Moving-range method: MR-bar / d_2 | **Short-term** variation only, robust to slow drift | Average of absolute consecutive differences, divided by the unbiasing constant d_2 for span 2 |

**Why both exist:** The sample standard deviation captures ALL variation in the baseline, including slow trends or step changes within the collection period. The moving-range sigma captures only the variation between consecutive observations — the short-term noise. SPC uses the moving-range sigma for control limits on individual observations precisely because it isolates the variation relevant to individual-observation monitoring. If the baseline contains a slow upward trend, the sample standard deviation is inflated (wider limits, fewer signals), but the MR sigma is unaffected (correct limits for the point-to-point noise).

**Why this matters:** Conflating the two silently produces wrong limits. Using `baseline_spread` (sample std dev) as the operational sigma would over-estimate process variation when the baseline contains any drift, producing limits that are too wide and that miss genuine shifts. This applies equally to EWMA, CUSUM, and Shewhart.

**Correction from initial model:** The original model (following an inference in ADR-005) placed the MR-based sigma only on `FittedShewhart`, with EWMA and CUSUM using the sample standard deviation. This was wrong. Standard SPC practice estimates sigma from the moving range for **all** chart types on individual observations (n=1), not just the Shewhart I-chart. The reasoning is the same: individual-observation monitoring requires an estimate of short-term variation, and the moving range provides exactly that.

**Verification (2026-09-09):** SPC for Excel formulas reference (spcforexcel.com) explicitly confirms: "If the subgroup size is 1, sigma is estimated from the moving range for n=2" for both EWMA and CUSUM charts, not just Shewhart. Multiple SPC software implementations (analyse-it, SigmaXL) confirm the same convention. Montgomery's Chapter 9 (*Introduction to Statistical Quality Control*) could not be accessed directly (O'Reilly paywall), but all secondary sources citing Montgomery confirm MR-based estimation for individuals data across all chart types.

**What could not be verified from primary sources:** Whether Lucas and Saccucci (1990) or Siegmund (1985) prescribe a specific sigma estimator, or whether they assume known sigma. Both methods take sigma as a parameter — the ARL calibration works with whatever sigma is supplied. The choice of estimator affects how closely the estimated sigma approximates the true sigma, which in turn affects how closely the achieved ARL matches the nominal ARL_0. **If the published ARL tables assume a particular sigma estimator and the implementation uses a different one, the calibration departs from nominal in a way BIN-84's table comparison would not detect** — the tests would pass while the achieved ARL_0 departed from the published values. This must be verified from the primary papers at implementation time.

**ADR-004 impact:** The shared core gains two fields (`sigma_estimate`, `sigma_estimation_method`) that ADR-004 placed on Shewhart only. ADR-005's statement "EWMA and CUSUM use the sample standard deviation" was an inference not established by ADR-004 and is contradicted by standard SPC practice. ADR-004 should be amended to reflect the corrected shared core. This domain model does not amend ADR-004 directly — it documents the finding for the system-architect to act on.

**The review feature file (BIN-66) asserts both:** SC1 references "the spread measure" (shared core's `baseline_spread`); the Shewhart feature file's SC2 separately references "the sigma estimate derived from the baseline" (shared core's `sigma_estimate`). Both are present and distinguishable on all artefacts.

**Moving-range span:** Fixed at the conventional value (span 2) for R1, per BIN-95 OQ-5 endorsed by ADR-004. The unbiasing constant d_2 is coupled to the span — changing one without the other invalidates the limits.

---

## Value Object Inventory

All value objects below are implemented as Pydantic `BaseModel` subclasses
with `ConfigDict(frozen=True)` and `@field_validator`, per the house standard
(`architecture/references/ddd.md`) — **not** stdlib frozen dataclasses (that
was a conformance gap remediated under BIN-103) and **not** `Result[...]`-
returning factories (see the correction below). Equality is by value (all
fields) unless noted otherwise, using Pydantic's default field-wise equality.

**Two implementation details worth carrying forward, because they are not
obvious from the pattern alone:**

1. **Validators raise `InvalidParameterError` directly, not `ValueError`.**
   `architecture/references/ddd.md`'s example has `@field_validator` raise
   `ValueError` and translate it to a domain error "at a service boundary."
   Caliper has no service layer, so there is no boundary to translate at —
   **the value object's validator is the boundary**, and raises the
   `CaliperError` subclass directly. This works because of a specific,
   verified Pydantic behaviour: Pydantic wraps `ValueError`/`AssertionError`
   raised inside a validator in its own `pydantic.ValidationError`; any other
   exception type propagates unwrapped. Verified empirically against
   pydantic 2.13.5 (not assumed from the docs).
2. **Immutability violations raise `pydantic_core.ValidationError`, not
   `dataclasses.FrozenInstanceError`.** This changed with the BIN-103
   dataclass→Pydantic migration; ADR-002 §7 keeps immutability violations
   outside the `CaliperError` taxonomy either way — they are programming
   mistakes, not operational failures, and are asserted by tests as a raw
   Pydantic exception, never as a `CaliperError`.

### Correction — no `Result[...]` factories

This document previously specified `ModelVersion.create(raw: str) ->
Result[ModelVersion, InvalidParameterError]` and equivalent
`Result`-returning factories for `ScoringCriteria`, `Provenance` and
`ScoringResult`. **These raise directly instead** — Caliper has no `returns`
dependency and is instructed never to add one for this.

To be fair to the standard this deviated from rather than just calling the
original wording wrong: `coding-standards/references/python.md` does list
`returns`/`Result` for typed error handling, but its own "When NOT to use
`returns`" section is explicit that *"for simple single-failure-point
functions, plain exceptions remain cleaner"*, and its own counter-example —
`get_market(market_id) -> Market`, raising `NotFoundError` rather than
returning a `Result` — is structurally identical to `ModelVersion.create`,
`ScoringCriteria.create` and friends: one validation check, one failure mode,
one exception type. `returns` would still be the right tool for a genuine
multi-stage pipeline with heterogeneous failure types, should Caliper ever
grow one; nothing here has that shape.

### `ModelVersion`

**Carried by:** `Judge.model_version`, `Provenance.model_version`
**Equality:** by value (wraps a single `str` field, `value`)
**Constraints:**
- Must be a non-empty string (BIN-57 BR-1, BR-2)
- Whitespace-only strings are rejected (BIN-57 SC4)
- Preserved exactly as provided, including leading/trailing whitespace (BIN-57 SC5, SC7)
- Immutable after creation (BIN-57 SC6) — enforced by Pydantic (`pydantic_core.ValidationError` on reassignment, per the note above)

**Construction:** `ModelVersion(value=raw)` — validated by a `@field_validator`, raising `InvalidParameterError` directly (not returning a `Result`) when `raw` is empty or whitespace-only. Also constructed indirectly via `Judge.create(model_version=raw)`, which raises its own `InvalidParameterError(kind="missing")` first if `raw` is `None` (the "missing" case is a distinct condition Caliper checks before a `ModelVersion` is ever built — `ModelVersion` itself never sees `kind="missing"`, only `kind="invalid"`).
**Rejects (as a `CaliperError`):** empty string, whitespace-only string.

**⚠️ Known gap — BIN-104, not yet fixed:** the claim above ("no way to build a
`ModelVersion` that wraps an empty or whitespace-only `str`") holds only for
*blank* values. A wrong-*typed* argument, e.g. `ModelVersion(value=123)`, is
rejected by Pydantic's own core type coercion, which runs **before** the
`@field_validator` — so it surfaces as `pydantic_core.ValidationError`, not a
`CaliperError`. "The value object is the boundary" is therefore true for
blank values and not (yet) true for wrong types. This is not a regression —
the stdlib-dataclass version raised an unhandled `AttributeError` from
`.strip()` on an `int`, which was no better — but it is a real gap, filed as
BIN-104 with a scenario still to be written. `ModelVersion` and
`ScoringCriteria`'s docstrings have already been narrowed to claim only what
holds.

### `ScoringCriteria`

**Carried by:** `Provenance.scoring_criteria`, `Judge.criteria` (judge-level, optional), and the `criteria` parameter of `Judge.score()` (per-call, optional). **Former OQ-1 (criteria attachment point) is settled** — see Open Questions.
**Equality:** by value (wraps a single `str` field, `value`)
**Constraints:**
- Must be a non-empty string (BIN-58 BR-1)
- Whitespace-only strings are rejected (BIN-58 SC3)
- Multi-line text is accepted (BIN-58 SC5)
- Preserved exactly as provided, including surrounding whitespace (BIN-58 SC4, SC7)
- Immutable after creation

**Construction:** `ScoringCriteria(value=raw)` — validated by a `@field_validator`, raising `InvalidParameterError` directly. Unlike `ModelVersion`, there is no "missing" case for this value object in the feature file — every scenario supplies a value, including blank ones — so `context["kind"]` is always `"invalid"` here.
**Rejects (as a `CaliperError`):** empty string, whitespace-only string.
**Same BIN-104 gap as `ModelVersion` applies** — a wrong-typed argument leaks `pydantic_core.ValidationError`, not `InvalidParameterError`.

### `Provenance`

**Carried by:** `ScoringResult.provenance`, `Baseline.provenance_signature`, `FittedControlLimits` (via two protocol properties)
**Equality:** compares both dimensions (model version AND criteria), via Pydantic's field-wise equality on the wrapped `ModelVersion`/`ScoringCriteria` instances — which is **exact string comparison**, settled 2026-09-10 (was OQ-2). No stripping, no case folding, no Unicode normalisation. See "Criteria equality is exact" in Open Questions.
**Constraints:**
- Both dimensions required
- Immutable after creation
- **No validator.** There is nothing left to validate — `Provenance` cannot hold a blank or whitespace-only model version or criteria string, because `ModelVersion` and `ScoringCriteria` already cannot. The invariant is structural, not re-checked.

**Structure:**

| Field | Type | Source |
|-------|------|--------|
| `model_version` | `ModelVersion` | Carried through from the Judge — **not** `str`. Confirmed correct as this document originally worded it ("Carried by: ... `Provenance.model_version`" was read literally: the *type*, `ModelVersion`, is carried, not just the string concept). ADR-006 §7 was revised to match this reading after a draft briefly typed both fields as `str`; that draft is not what shipped. |
| `scoring_criteria` | `ScoringCriteria` | Carried through from the criteria configuration — likewise a value object, not `str` |

**Construction:** `Provenance(model_version=..., scoring_criteria=...)`, built directly from the already-validated `ModelVersion`/`ScoringCriteria` a `Judge` holds — no unwrapping to `str` and back. Reading a dimension follows the `.value` idiom already established for `Judge.model_version`: `result.provenance.model_version.value`. Comparing two provenance dimensions for equality does not need `.value` at all — `ModelVersion` and `ScoringCriteria` are value-equal, so `result.provenance.model_version == judge.model_version` holds directly.

**Usage across five stories:**
- BIN-57: originates model version
- BIN-59: attaches provenance to each ScoringResult (implemented)
- BIN-63: enforces provenance consistency within the baseline; exposes provenance signature (**implemented**)
- BIN-65/94/95: carries provenance onto the fitted artefact (**implemented**)
- BIN-68: compares provenance across the Phase I/II boundary; raises `ProvenanceMismatchError` on divergence (**implemented**)

### `ScoringResult`

**Carried by:** returned from `Judge.score()`, recorded into `Baseline`
**Equality:** by value (all fields)
**Constraints:**
- All three fields required (BIN-59 BR-1, BR-2)
- Immutable after creation (BIN-59 BR-3)
- `score` must be a **finite** float — NaN and ±infinity are rejected (ADR-006 §5, **settles former OQ-5**; see Open Questions)

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `score` | `float` | Scalar quality score (ADR-001: `float`, higher-is-better). **Unconstrained range otherwise** — no fixed `[0,1]`, no engineer-declared range; the SPC maths works on any bounded continuous range and normalisation is out of scope for this story (ADR-006 §5). |
| `reasoning` | `str` | Judge's textual reasoning for the score. No emptiness constraint — not tested by any scenario. |
| `provenance` | `Provenance` | Measurement configuration that produced this score |

**Construction:** `ScoringResult(score=..., reasoning=..., provenance=...)` — a `@field_validator` on `score` raises `InvalidParameterError` (`context["parameter"]=="score"`, `context["kind"]=="invalid"`) when the value is not finite. `reasoning` and `provenance` presence are enforced by the type signature; no additional content constraint on `reasoning`.
**Rejects (as a `CaliperError`):** non-finite `score` (`NaN`, `+inf`, `-inf`).

### `JudgeProviderResponse`

**Carried by:** the return value of `JudgeProviderPort.score()`
**Equality:** by value (both fields)
**Constraints:** none beyond field presence — no finiteness check on `score` here (that check lives on `ScoringResult`, once `Judge.score()` has attached provenance). Frozen Pydantic `BaseModel`.
**Not exposed to the engineer** — internal to `Judge.score()`'s orchestration; carries no provenance of its own.

| Field | Type | Notes |
|-------|------|-------|
| `score` | `float` | Raw score from the provider, before provenance is attached |
| `reasoning` | `str` | Raw reasoning text from the provider |

### `SufficiencyResult`

**Carried by:** returned from `Baseline.check_sufficiency()`
**Equality:** by value
**Constraints:**
- Immutable after creation
- Read-only inspection — does not modify the baseline (BIN-64 BR-6)

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `is_sufficient` | `bool` | Whether the baseline meets the threshold |
| `observation_count` | `int` | Current count in the baseline |
| `threshold` | `int` | The minimum that was applied (configured or default) |
| `gap` | `int` | Observations still needed; 0 when sufficient |
| `data_quality_concerns` | `tuple[DataQualityConcern, ...]` | E.g., zero variance (BIN-64 SC7). A tuple, not a list — see the convention below (BIN-108) |

### Sequence fields on immutable types are tuples

**Convention, settled under `BIN-108`: any sequence-typed field on an
immutable domain type is a `tuple`, never a `list`.**

`ConfigDict(frozen=True)` stops a field being **rebound**. It does not freeze
what the field points at. So while `SufficiencyResult.data_quality_concerns`
held a list, this document's "Immutable after creation" was simply false — a
caller could `.append()` to a result and it took, with no error:

```python
r = baseline.check_sufficiency()
r.data_quality_concerns.append("injected")   # succeeded; length went 1 -> 2
```

`Baseline.observations` already wrapped in `tuple()` for exactly this reason;
`SufficiencyResult` did not, which is what made it an oversight rather than a
decision.

Three things worth knowing before typing the next one:

- **It costs callers nothing.** Pydantic coerces a list passed to the
  constructor into a tuple, so constructor ergonomics are unchanged.
- **It restores hashability.** A list field silently made an "equality by
  value" type unhashable — it could not go in a set or serve as a dict key.
- **`mypy` enforces it at the call site, Pydantic does not.** Runtime coercion
  hides a producer still returning a list; the strict type check does not. Fix
  the producer's return type rather than leaning on coercion.

⚠️ **Line coverage cannot see this class of defect.** The field was at 100%
coverage while its documented immutability was false. Pin it with a test that
attempts in-place mutation.

### `DataQualityConcern`

**Carried by:** `SufficiencyResult.data_quality_concerns`
**Equality:** by value

| Field | Type | Notes |
|-------|------|-------|
| `kind` | `str` | E.g., `"zero_variance"` |
| `description` | `str` | Human-readable explanation |

### `ControlLimitTriplet`

**Carried by:** `FittedEWMA`, `FittedShewhart` (as `ucl`, `lcl`, `cl` fields)
**Equality:** by value

This is a presentational grouping, not necessarily a separate type. The three values may be individual fields on the artefact rather than a composite VO. Whether to group them is an implementation decision.

| Field | Type | Notes |
|-------|------|-------|
| `ucl` | `float` | Upper control limit |
| `lcl` | `float` | Lower control limit |
| `cl` | `float` | Centre line |

---

## Ubiquitous Language Glossary

Every term below appears in at least one feature file or ADR. Where the PRD and feature files use different words for the same concept, the canonical term is listed and the variant is noted.

| Term | Definition | Context | Source |
|------|-----------|---------|--------|
| **Judge** | An immutable configured adapter that wraps an LLM provider to score agent outputs against a rubric. The measurement instrument. | Measurement | BIN-57, BIN-59 |
| **Model version** | The pinned version string identifying the specific LLM model a judge uses. Required, non-empty, preserved exactly. The primary statistical integrity concern — a silent model update invalidates all downstream claims. | Measurement | BIN-57 |
| **Scoring criteria** | A text rubric defining what the judge evaluates. Required, non-empty, preserved exactly. Anchors the judge's assessment to the engineer's use case. | Measurement | BIN-58 |
| **Provenance** | The measurement configuration that produced a score: model version + scoring criteria. A first-class value object with equality semantics. Carried on every scoring result, baseline observation, and fitted artefact. | Both | BIN-59, BIN-63, BIN-68 |
| **Provenance signature** | The provenance established by the first observation in a baseline. All subsequent observations must match. | Baseline | BIN-63 SC8 |
| **Scoring result** | The immutable output of a single scoring operation: a float score, textual reasoning, and provenance. The unit of measurement. | Measurement | BIN-59 |
| **Score** | A scalar `float` quality value produced by an LLM judge. Higher is better (ADR-001): a falling score indicates degradation (lower arm); a rising score indicates improvement or stale baseline (upper arm). | Both | ADR-001, BIN-59 |
| **Observation** | A scoring result recorded into a baseline. Observations are the unit of baseline data. In R1, an observation IS a `ScoringResult` — no additional fields. **OQ-8 (open)** may add a timestamp or sequence index — see Open Questions; this is also the recorded trigger for adding `whenever` as a dependency (CLAUDE.md, "Stack Members Not Yet Used" — zero `datetime` usage anywhere in `src/caliper` today; a timestamp on `Observation` is named as the first plausible caller). | Baseline | BIN-63 |
| **Baseline** (Phase I baseline) | An ordered, provenance-consistent collection of observations from which control limits are fitted. The only mutable object in the domain. | Baseline | BIN-63 |
| **Phase I** | The baseline collection and fitting phase. The engineer collects observations, checks sufficiency, and fits control limits. | Baseline | BIN-63, BIN-65/94/95 |
| **Phase II** | The ongoing monitoring phase. Partially in scope: BIN-68 covers provenance comparison across the phase boundary. Phase II monitoring logic (BIN-69) is not yet specified. | Baseline | BIN-68 |
| **Sufficiency** | Whether a baseline has enough observations for reliable control limit fitting. The check is advisory (reports status); fitting is where enforcement occurs. | Baseline | BIN-64 |
| **Sufficiency threshold** | The minimum number of observations required. Configurable per engineer and per chart type (BIN-64 BR-3, BR-5). Library default: 100 individual observations (ADR-005). Must be positive (BIN-64 BR-8). | Baseline | BIN-64, ADR-005 |
| **Degenerate baseline** | A baseline that meets the count threshold but is statistically unusable. The primary case is zero variance — all scores identical, causing sigma to collapse to zero and limits to collapse to the mean. | Baseline | BIN-65 SC6, BIN-94 SC6, BIN-95 SC6 |
| **Fitted artefact** / **fitted control limits** | An immutable record produced by fitting. Carries the statistical parameters, provenance, and ARL information needed for Phase II monitoring and auditability. Satisfies the `FittedControlLimits` protocol (ADR-004). | Baseline | BIN-65/66/94/95, ADR-004 |
| **False alarm tolerance** | The target in-control ARL_0. The expected number of observations before a false alarm when the process is in control. Primary representation: ARL_0. False alarm rate (alpha) accepted as convenience input, converted to ARL_0. Required parameter — no silent default (ADR-004 section 5). | Baseline | ADR-004, BIN-65/94/95 |
| **ARL_0** (in-control Average Run Length) | The canonical representation of false alarm tolerance. What published ARL tables are indexed by (BIN-84). What the calibration methods target. | Baseline | ADR-001, ADR-003, ADR-004 |
| **Requested ARL** | The ARL_0 the engineer specified when fitting. | Baseline | ADR-004 |
| **Achieved ARL** | The ARL_0 actually produced by the calibration. May differ from requested due to numerical approximation (Markov-chain for EWMA, Siegmund for CUSUM). Under normality, Shewhart's is exact. | Baseline | ADR-004 |
| **Control limits** | UCL (upper control limit) and LCL (lower control limit) defining the in-control region, plus CL (centre line). Used by EWMA and Shewhart charts. On the observation scale — a score beyond UCL or below LCL triggers a signal. | Baseline | BIN-65, BIN-95 |
| **Decision interval** (*h*) | The CUSUM threshold. Compared against the accumulating CUSUM statistic *S*, NOT against observations directly. Not on the observation scale. Derived from the reference value and target ARL_0 via Siegmund's approximation — the engineer does not specify it. | Baseline | BIN-94, ADR-004 |
| **Reference value** (*k*) | The CUSUM shift size parameter, in sigma units. The size of shift the CUSUM is optimised to detect. Has a library default. | Baseline | BIN-94, ADR-004 |
| **Smoothing parameter** (lambda) | The EWMA weighting parameter controlling sensitivity to recent vs historical observations. Has a library default. | Baseline | BIN-65, ADR-004 |
| **Baseline spread** | The sample standard deviation of Phase I scores. A shared descriptive statistic on all fitted artefacts (part of the `FittedControlLimits` protocol). Captures TOTAL variation including any slow drift within the baseline. **Not the operational sigma** — see sigma estimate. | Baseline | ADR-004 |
| **Sigma estimate** / **moving-range sigma** | The short-term variation estimate from consecutive-observation differences: MR-bar / d_2 for span 2. Used by **all three chart types** (EWMA, CUSUM, Shewhart) for control limit computation on individual observations. Part of the shared core. Captures SHORT-TERM variation only, robust to slow drift. **Different from baseline spread** — see dual-spread note above. | Baseline | ADR-004, standard SPC practice (verified) |
| **Sigma multiplier** | The number of sigma units defining Shewhart control limits. Derived from the false alarm tolerance — not specified by the engineer. | Baseline | BIN-95, ADR-004 |
| **Calibration method** | The numerical procedure that determined the chart's parameters from the target ARL_0. EWMA: Markov-chain (Lucas and Saccucci 1990). CUSUM: Siegmund's corrected diffusion approximation (1985). Shewhart: direct tail probability. | Baseline | ADR-001, ADR-004 |
| **Chart type** | One of EWMA, CUSUM, or Shewhart I-chart in R1. Reported on every fitted artefact. | Baseline | ADR-004 |
| **Direction** (CUSUM) | Which direction(s) of drift are monitored. `"two_sided"` (default): both arms. `"lower"`: degradation only (score drifts down). `"upper"`: improvement only (baseline staleness). Two-sided default, configurable to one-sided (ADR-004 section 6). | Baseline | ADR-004 |
| **Higher-is-better** | Caliper's score orientation (ADR-001). A falling score = degradation (lower CUSUM arm). A rising score = improvement / stale baseline (upper CUSUM arm). This mapping holds throughout the library. | Both | ADR-001 |
| **Signal** | An out-of-control indication from Phase II monitoring. E4 (BIN-75 through BIN-81) has no written requirements. Not modelled in R1. | — | context.md (sketch only) |
| **SPCPort** | The port interface for the SPC engine (ADR-001). The boundary between the domain and the statistical computation layer. Fitting operations are behind this port. | Baseline | ADR-001 |
| **Agent output** | The text produced by the engineer's agent, the subject being scored. Required, rejected if empty or whitespace-only (**settles former OQ-10**). Named `agent_output`, not `output`, to keep the `agent_` prefix consistent with `agent_input` and the feature files' own wording. | Measurement | BIN-59, ADR-006 §3, §6 |
| **Agent input** | The input that produced the agent output, when the caller has it. Optional, not validated for emptiness (a proactively-acting agent may legitimately have none), and **not** carried onto `Provenance` or `ScoringResult` — it is the subject being measured, not the measurement configuration. Named `agent_input`, not `input`, because bare `input` shadows a Python builtin and this project's `ruff` config (`flake8-builtins`, rule `A002`) rejects it. | Measurement | BIN-59, ADR-006 §3 |
| **Judge provider** / **`JudgeProviderPort`** | The port through which a `Judge` obtains a score and reasoning from an LLM (or any scoring backend). A real hexagonal port — `@runtime_checkable Protocol`, no concrete adapter yet, only `FakeJudgeProviderPort` in test code. Interpreting a provider's raw response shape is the adapter's job, never the domain's. | Measurement | ADR-006 §1 |

**Consistency notes:**
- "False alarm tolerance" is used throughout the feature files as a neutral term. ADR-004 resolved this to ARL_0 as the primary representation.
- "Spread measure" in BIN-66 SC1 refers to `baseline_spread` (shared core sample standard deviation). "Sigma estimate" in BIN-95 SC2 refers to `sigma_estimate` (shared core MR-based estimate). These are explicitly different quantities, both in the shared core.
- "Observation" and "scoring result" are the same data — the term shifts at the context boundary. A "scoring result" becomes an "observation" when recorded into a baseline.
- "Output"/"input" in earlier drafts of the PRD and feature file text are the informal predecessors of the canonical `agent_output`/`agent_input` terms ADR-006 settled on. Same concepts, more precise names.

---

## Domain Event Catalogue

**There are no domain events in R1's specified scope.**

The ten feature files establish a synchronous call-and-return pattern:
- `Judge.score()` returns a `ScoringResult` — no event published.
- `Baseline.record()` mutates the baseline and returns — no event published.
- Fitting operations return a fitted artefact — no event published.
- Provenance comparison raises or confirms — no event published.

The signal handler chain (E4: BIN-75 through BIN-81) is the natural location for domain events (`SignalEvent` as sketched in `context.md`). Those stories have no written requirements — no PRDs, no feature files, no ADR. Modelling events for unspecified behaviour would be speculative.

**When this changes:** E4 requirements will introduce events. The `SignalEvent` sketch in `context.md` (signal, judgement result, consecutive signal count, severity) is indicative but not contractual. The domain model should be extended when E4 requirements are written.

**Confirmed still true after E1 shipped (BIN-100 refresh):** ADR-006 introduced no events. `Judge.score()` is a synchronous call-and-return, exactly as this section already described.

---

## Error Contract Reference

ADR-002 defines the error taxonomy. Nine typed exceptions under `CaliperError`, each with required `context` fields. The full specification is in `docs/architecture/adr/002-error-contract-exception-taxonomy.md`. **ADR-008** additionally settles how tests assert against this taxonomy: `isinstance` plus required `context` key presence, **never** message text — `recovery_hint` is human-facing prose and deliberately untested. This governs even where it conflicts with `test-patterns`' general Pydantic-validation guidance (which assumes an HTTP boundary Caliper does not have).

| Exception | Category string | Required context fields | Raised by |
|-----------|----------------|------------------------|-----------|
| `InvalidParameterError` | `invalid_parameter` | `parameter`, `constraint`, `kind` (`"missing"` or `"invalid"`) | Judge creation (BIN-57), criteria config (BIN-58), sufficiency threshold (BIN-64), fitting parameters (BIN-65/94/95) |
| `MissingPrerequisiteError` | `missing_prerequisite` | `prerequisite`, `operation` | Scoring without criteria (BIN-59) |
| `ProviderError` | `provider_failure` | `provider`, `operation` | LLM provider failure during scoring (BIN-59) |
| `MalformedResponseError` | `malformed_response` | `operation`, `expected_shape` | Unparseable judge response (BIN-59) |
| `JudgeRefusalError` | `judge_refusal` | `provider`, `operation` | Judge safety-filter refusal (ADR-002) |
| `ProvenanceMismatchError` | `provenance_mismatch` | `mismatches: dict[str, dict[str, str]]` (amended 2026-09-10, was `dimension`/`expected`/`received` — see ADR-002 Amendment) | Baseline recording (BIN-63), Phase II comparison (BIN-68) |
| `InvalidObservationError` | `invalid_observation` | `reason`, `missing_fields` | Incomplete input to baseline (BIN-63) |
| `InsufficientBaselineError` | `insufficient_baseline` | `have`, `need` | Fitting from too-small baseline (BIN-65/94/95) |
| `DegenerateBaselineError` | `degenerate_baseline` | `reason` | Fitting from zero-variance baseline (BIN-65/94/95) |

**Immutability violations** (BIN-57 SC6, BIN-59 SC6, BIN-63 SC9, BIN-65 SC11, BIN-94 SC12, BIN-95 SC12) raise **`pydantic_core.ValidationError`**, not `CaliperError` (ADR-002 §7, corrected 2026-09-09 under BIN-103 — value objects were stdlib frozen dataclasses, raising `dataclasses.FrozenInstanceError`, when §7 was originally written and this document previously said `AttributeError`/`FrozenInstanceError`). These are programming mistakes caught by the type system, not operational failures. One capability was lost in the dataclass→Pydantic migration and is worth knowing: mypy used to catch frozen-*dataclass* assignment statically; it cannot see that a Pydantic model is frozen, so this guarantee is now runtime-only, asserted by tests rather than by the type checker (ADR-007).

**Known gap outside this taxonomy — BIN-104:** a wrong-*typed* constructor argument (e.g. `ModelVersion(value=123)`) is rejected by Pydantic's core type coercion *before* the value object's `@field_validator` runs, so it surfaces as `pydantic_core.ValidationError`, not `InvalidParameterError`. "The value object is the boundary" (see Value Object Inventory) holds for blank values, not yet for wrong types. See the Value Object Inventory's `ModelVersion` entry for detail; not fixed by this refresh.

---

## Library Operations

These are the operations the ten feature files establish. They replace the "service operations" section that a service-oriented model would include.

| Operation | Feature file | Input | Output | Context |
|-----------|-------------|-------|--------|---------|
| Create judge | BIN-57 | `model_version: str \| None`, optional `provider`, optional `criteria` | `Judge` | Measurement — **implemented** |
| Configure criteria | BIN-58 | `criteria: str` | `ScoringCriteria` (attachment point **settled**: judge creation and/or per-call — former OQ-1) | Measurement — **implemented** |
| Score agent output | BIN-59 | `agent_output: str` (required), optional `agent_input: str`, optional `criteria: str` | `ScoringResult` | Measurement — **implemented** (ADR-006) |
| Create baseline | BIN-63 | (none) | `Baseline` (empty) | Baseline — **implemented** |
| Record observation | BIN-63 | `ScoringResult` | Mutates baseline | Baseline — **implemented** |
| Check sufficiency | BIN-64 | Optional keyword-only: `threshold`, `chart_type` | `SufficiencyResult` | Baseline — **implemented** (advisory; never raises) |
| Fit EWMA | BIN-65 | `Baseline`, `target_arl`, optional `smoothing_param` | `FittedEWMA` | Baseline — **implemented** (BIN-65) |
| Fit CUSUM | BIN-94 | `Baseline`, `target_arl`, optional `reference_value`, optional `direction` | `FittedCUSUM` | Baseline — **implemented** (BIN-94) |
| Fit Shewhart | BIN-95 | `Baseline`, `target_arl` | `FittedShewhart` | Baseline — **implemented** (BIN-95) |
| Review artefact | BIN-66 | Any `FittedControlLimits` | Read properties; `audit_summary()` | Baseline — **implemented** (BIN-66) |
| Compare provenance | BIN-68 | `ScoringResult`, `FittedControlLimits` | Confirms compatibility or raises `ProvenanceMismatchError` | Baseline — **implemented** (BIN-68) |

**Fitting parameter semantics (ADR-004 section 5):**
- `target_arl`: **optional in Python signature** (default `None`), **required by Caliper validation**. Omitting raises `InvalidParameterError(kind="missing")`.
- `smoothing_param` (EWMA), `reference_value` (CUSUM): genuinely optional. `None` uses library default.
- `direction` (CUSUM): genuinely optional. `None` defaults to `"two_sided"`.

---

## Open Questions

**Reader's guide:** four of the original eleven questions were settled by
ADR-006, alongside E1 shipping. Of the seven still open, six belong to E2
stories that will settle them as a byproduct of doing that story's design
work (BIN-63, BIN-64, BIN-65/94/95, BIN-66, BIN-68) — they are not blocked on
anyone deciding anything today.

**OQ-9 was the exception, and it is now settled: ratified 2026-09-10 —
there is no escape hatch. A changed judge requires a new baseline.** It was
the one free-standing product decision here, because it asked whether to
carve an exception into Caliper's strictest integrity rule rather than how
to implement a story. All eleven original questions now have an owner and a
disposition.

| # | Question | Owner | Blocks | Source | Status |
|---|----------|-------|--------|--------|--------|
| 1 | ~~Where do scoring criteria attach? At judge creation, at monitoring setup, or per-call?~~ | — | — | BIN-58 OQ-3 | **SETTLED** — ADR-006 §2: judge creation *and/or* per-call; per-call wins for that call only, without mutating the frozen `Judge`. "Monitoring setup" explicitly rejected as a third point in R1 (no `Monitor` construct exists). |
| 2 | ~~Criteria comparison mechanism.~~ | — | — | BIN-63 OQ-6, BIN-68 OQ-2 | **SETTLED** — product owner, 2026-09-10: **exact string match.** No normalisation of any kind. See "Criteria equality is exact" below. |
| 3 | **Sufficiency check: internal or external to fitting?** Does fitting call sufficiency internally, or does the engineer call it first? Both designs satisfy the feature files. | domain-modeller | Fitting operation structure | BIN-65/94/95 OQ-3 | **Open.** Untouched by ADR-006/007/008. Belongs to BIN-65/94/95. |
| 4 | **Sufficiency override for testing.** Should the engineer be able to bypass sufficiency enforcement for exploratory fitting? | domain-modeller | Fitting operation parameters | BIN-65/94/95 OQ-4 | **Open.** Untouched. Belongs to BIN-65/94/95. |
| 5 | ~~Score range. Fixed [0, 1], engineer-declared range, or unconstrained?~~ | — | — | BIN-59 OQ-2 | **SETTLED** — ADR-006 §5: unconstrained (no fixed or engineer-declared range), but the score must be a **finite** float — `NaN` and `±inf` are rejected as `InvalidParameterError`. A future fitting-time range check remains additive and is not foreclosed. |
| 6 | ~~Scoring input shape. Both agent input and output, or output alone?~~ | — | — | BIN-59 OQ-6 | **SETTLED** — ADR-006 §3: both accepted — `agent_output` required, `agent_input` optional. Neither is echoed onto `Provenance` or `ScoringResult` (they are the subject measured, not the measurement configuration). |
| 7 | ~~Serialisable form for audit logging. Should the artefact provide a `to_dict()` or equivalent?~~ | — | — | BIN-66 OQ-1 | **SETTLED** — BIN-66, 2026-09-10: a **textual** `audit_summary()` only. No `to_dict()`. None of BIN-66's five scenarios asks for a machine-readable form, and Pydantic already gives every artefact `model_dump()` for free — a hand-written `to_dict()` would be a second, divergent serialisation of the same fields. A structured export remains **additive** if a concrete consumer appears. |
| 8 | **Observation identity.** Do observations carry a timestamp, sequence index, or neither? The feature files assert ordering without assuming a mechanism. | domain-modeller | `Observation` structure | BIN-63 OQ-3 | **Open.** Untouched. Belongs to BIN-63. Doubles as the recorded trigger for adding `whenever` as a dependency — see CLAUDE.md "Stack Members Not Yet Used" and the Glossary's Observation entry. |
| 9 | ~~Explicit override for known provenance change between phases.~~ | — | — | BIN-68 OQ-3 | **SETTLED** — product owner, 2026-09-10: **no override. The engineer refits.** `ProvenanceMismatchError` raises unconditionally; `compare_provenance()` takes no acknowledgement or force parameter. See "Provenance change requires a refit" below. |
| 10 | ~~Whether scoring accepts empty agent output.~~ | — | — | BIN-59 OQ-5 | **SETTLED** — ADR-006 §6: rejected. Empty or whitespace-only `agent_output` raises `InvalidParameterError` before any provider call. An engineer who wants "no response" scored passes their own sentinel string. |
| 11 | ~~Dual mismatch representation. When both provenance dimensions differ, what shape does the error context take?~~ | — | — | BIN-68 OQ-1 | **SETTLED** — system-architect, 2026-09-10: `context["mismatches"]`, a `dict[str, dict[str, str]]` keyed by dimension name (`"model_version"`, `"scoring_criteria"`), each holding `{"expected": ..., "received": ...}`. Replaces `dimension`/`expected`/`received`. `Baseline.record()` (BIN-63) and `compare_provenance()` (BIN-68) both produce this shape — required by the merged dual-mismatch scenario. See ADR-002 Amendment (2026-09-10). |

### Criteria equality is exact (OQ-2, settled 2026-09-10)

**Decision: provenance comparison is exact string equality on both
dimensions.** No stripping, no whitespace collapsing, no case folding, no
Unicode normalisation. `Provenance` equality is Pydantic's field-wise
equality over `ModelVersion` and `ScoringCriteria`, which is exactly this —
so **no comparison code is needed**, and none should be written.

**Rationale — this follows from decisions already taken, rather than being a
fresh call.**

`ModelVersion` and `ScoringCriteria` *deliberately* preserve surrounding
whitespace byte-for-byte. That is not incidental: `BIN-57` `SC7` and
`BIN-58`'s boundary scenario both assert it, and both were written to pin it
against exactly the well-meaning "helpful" trimming a normalising comparison
would reintroduce at the other end. Preserving a value on the way in and then
ignoring part of it on the way out would be incoherent.

Normalisation is also a claim about what does not matter *semantically* in
someone else's rubric, and Caliper cannot know that. Whitespace is the
obvious candidate — but is case? A rubric that says "MUST be accurate" is
plausibly emphasising something a lowercase "must" does not. Every
normalisation rule is a guess about another team's intent.

An engineer who wants insensitivity has a clean route: normalise the criteria
text before passing it in. That is the caller deciding, consistent with every
other boundary in this library.

**Asymmetry settles the direction.** Relaxing exact to normalised later is
non-breaking for anyone whose criteria already match. Tightening normalised
to exact later would break every consumer relying on the leniency. Start
strict — the same reasoning as the fail-loudly ruling on unpinned models
(`BIN-57`) and the empty-output rejection (ADR-006 §6).

⚠️ **Known cost, and it compounds.** A trivial reformat of a rubric — a
reflowed line, an added trailing newline — invalidates a baseline and, under
`OQ-9`'s no-override ruling, forces a full refit at ADR-005's 100-observation
minimum. That is a real papercut on the OMTM.

**`BIN-105` is the mitigation** (refit by re-scoring retained outputs), and
this makes its case stronger rather than weaker. If a report ever arrives of
someone losing a baseline to a whitespace change, that is a signal to revisit
this decision with evidence — not a reason to pre-emptively soften it now.

### Provenance change requires a refit (OQ-9, settled 2026-09-10)

**Decision: there is no acknowledgement path. An engineer who knowingly
changes the judge model or the scoring criteria must fit a new baseline.**
`compare_provenance()` gains no `acknowledge=`, `force=` or equivalent
parameter, and none should be added without reopening this decision.

**Rationale.** An acknowledged mismatch is still a mismatch. Knowing that the
instrument changed does not make measurements taken with the old instrument
comparable to measurements taken with the new one — the control limits were
estimated from a distribution the new judge does not produce, so every
subsequent ARL₀ claim, every signal and every in-control run is computed
against a baseline that no longer describes the process. An override would let
an engineer keep a chart that looks authoritative and reports numbers that mean
nothing, which is the precise failure Caliper exists to prevent.

Refitting is not a punishment for the engineer; it is the only operation that
restores the guarantee.

⚠️ **The cost is real and compounds with ADR-005, and should not be
soft-pedalled.** ADR-005 set the minimum Phase I baseline at **100 individual
observations** — already a materially larger adoption barrier than the 20–25
figure `context.md` originally assumed, and Phase I→II conversion is the
project's OMTM. This decision means a judge-model change resets that cost in
full: 100 fresh observations before monitoring resumes, with no shortcut.

That is accepted deliberately, not overlooked. The alternative trades a
one-off cost the engineer can see for a silent, permanent invalidation they
cannot.

**What this does not foreclose.** Nothing here prevents Caliper from making
the refit *easier* — carrying forward configuration, warning early when a
provider version drifts, or offering a helper that begins a new baseline from
a running stream. Those are ergonomics, and they are additive. What is closed
is proceeding on the old baseline with the new judge.

---

> **Keeping this table honest.** The status column drifted through `BIN-63` and
> `BIN-64` — both shipped while their rows still read "not yet implemented",
> because the first omission was then read as precedent by the next story.
> **Update the row in the same PR that implements the operation.** This document
> is canonical (the vault copy is a pointer), so a stale status here is a wrong
> answer to the question a new agent most often asks of it: what already exists?

## Validation Checklist

- [x] Every observation in the ten feature files is satisfiable by this model
- [x] No new aggregate duplicates an existing one — checked against `src/caliper/measurement/` (E1's actual implementation), not just other docs
- [x] Every domain event name is past tense and unambiguous — N/A, no events in R1; confirmed still true after ADR-006/E1
- [x] Every VO raises its typed error directly at the point of construction and has at least one constraint — **not** a `create()` → `Result[...]` factory (corrected this refresh; see Value Object Inventory)
- [x] No collection references another collection by object — only by value (Provenance)
- [x] Every term in the glossary appears in at least one feature file or ADR
- [x] Open Questions lists every ambiguity rather than resolving it silently — four marked SETTLED with citation, not deleted; seven still genuinely open
- [x] Both Shewhart spread quantities are present and distinguished (ADR-004 finding) — untouched by this refresh, still prominent
- [x] Provenance modelled as first-class VO holding `ModelVersion`/`ScoringCriteria` (not `str`), with equality semantics left open (OQ-2) — this document's original "Carried by" wording confirmed correct by ADR-006 §7
- [x] No numerical constants pinned (no d_2, h, k, L, or ARL_0 values)
- [x] Error contract references ADR-002's nine types without inventing parallel concepts; ADR-008's type-and-context-only assertion convention noted
- [x] Identity question addressed honestly: not needed in R1
- [x] BIN-104's known gap (wrong-typed constructor args leak `pydantic_core.ValidationError`) recorded, not silently left for a reader to discover
- [x] Repo (`docs/domain-model.md`) and vault (`Projects/caliper/domain-model.md`) copies reconciled — vault now points here; this file is canonical

---

## Changelog

- 2026-09-10 (BIN-100 refresh): Reconciled against ADR-006 (scoring API surface and judge provider port), ADR-007 (two type checkers), ADR-008 (error assertions over message text), and the merged, tested E1 implementation in `src/caliper/measurement/`. Settled OQ-1 (criteria attachment), OQ-5 (score range), OQ-6 (scoring input shape), OQ-10 (empty agent output) — each marked SETTLED with ADR section and resolution, not deleted. Corrected the `Result[...]`-returning VO factories (VOs raise `InvalidParameterError` directly; explained why the `returns`-standard's own "single-failure-point" exception applies here, not a misapplication of house style). Rewrote the `Judge` section for `provider`/`criteria`/`score()`. Added `JudgeProviderPort` and `JudgeProviderResponse` as a real hexagonal port and its response VO. Documented BIN-103's module layout (`measurement/domain/`, `measurement/ports/`, top-level `errors.py`). Recorded BIN-104's known gap (wrong-typed constructor args bypass the value-object boundary). Corrected immutability-violation exception type (`pydantic_core.ValidationError`, not `FrozenInstanceError`/`AttributeError`) per the BIN-103 dataclass→Pydantic migration. Reconciled the vault copy (`Projects/caliper/domain-model.md`), which had drifted into a lossier condensation of this file, into a pointer — this file is now the single canonical copy. Left untouched, as instructed: OQ-2/3/4/7/8/9/11 (still open at the time of this entry), all numerical constants (still unpinned), the dual-spread finding (still prominent), and the absence of domain events (E4 still unspecified).
- 2026-09-10 (BIN-100 gate): OQ-9 settled by the product owner — a changed judge requires a refit; `compare_provenance()` gains no acknowledgement or force parameter. See "Provenance change requires a refit". The cost this imposes (ADR-005's 100-observation minimum, reset in full) is recorded rather than soft-pedalled, and making the refit *easier* stays open — BIN-105 (refit by re-scoring retained outputs) and BIN-106 (paired judge-difference report). **All eleven original open questions now have an owner and a disposition.**
- 2026-09-09 (amendment): Sigma estimator correction — `sigma_estimate` (MR-based) and `sigma_estimation_method` moved from Shewhart chart-specific to the shared core. Standard SPC practice uses MR/d_2 for ALL chart types on individual observations, not just Shewhart. ADR-005's inference that "EWMA and CUSUM use the sample standard deviation" was incorrect. FittedCUSUM and FittedShewhart chart-specific sigma fields removed (now shared). Dual-spread section reframed from "Shewhart-specific" to "all artefacts." ADR-004 shared core affected — flagged for system-architect amendment. Amendment 2 (CUSUM duplication invariant) rendered moot — the fields now hold genuinely different quantities.
- 2026-09-09: Initial model — BIN-100
