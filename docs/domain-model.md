---
created: 2026-09-09
updated: 2026-09-11
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

### Monitoring (extended, ADR-009 + ADR-010)

**Responsible for:** recording Phase II observations against a fitted control-limit artefact, checking each one for an out-of-control signal (chart-type-specific: recursive for EWMA/CUSUM, memoryless for Shewhart), making a session's recording history reviewable in-memory, and — as of ADR-010 — delivering a signal's full content to zero or more engineer-supplied receivers, absorbing but surfacing any receiver failure.

**Stories:** BIN-69 (record and check), BIN-72 (in-memory history), BIN-75 (signal content + delivery mechanism), BIN-76 (built-in log receiver).

**Boundary:** begins where a `ScoringResult` and a `FittedControlLimits` artefact meet at Phase II; ends at the `MonitoringResult` returned per call (now carrying direction, the fitted artefact, and any delivery failures — ADR-010), the in-memory `history` of those results, and delivery to any configured `SignalReceiver`s. Depends on both Measurement (`ScoringResult`, `Provenance`) and Baseline (`FittedControlLimits`, `compare_provenance()`).

**Established by ADR-009** (`docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md`), settling BIN-69's OQ-1/A1/A2/OQ-3/OQ-4 and BIN-72's A1/A2/OQ-1/OQ-2 together. **Extended by ADR-010** (`docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md`), settling BIN-75's A1/A2/OQ-1(where)/OQ-2/OQ-3 and BIN-76's OQ-1(shared)/OQ-2/OQ-3 together, for the same reason: both stories' requirements reviews found them to be one coupled decision (BIN-76 consumes what BIN-75 defines), not two.

**Central type:** `Monitor(fitted_artefact, *, retain_history=True, receivers=())` — a new domain type, not a service. Holds the fitted artefact reference, private chart-specific accumulator state (nothing for Shewhart — memoryless by design; the smoothed statistic for EWMA; the two running one-sided sums for CUSUM), and — as of ADR-010 — a sequence of `SignalReceiver` callables supplied at construction. `Monitor.record(observation: ScoringResult) -> MonitoringResult` checks provenance internally (reusing BIN-68's `compare_provenance()`, unmodified), raises `ProvenanceMismatchError`/`InvalidObservationError` (the latter reused from Baseline's taxonomy, no new category) for the two precondition violations, and otherwise never raises — an out-of-control determination is a normal return value (`MonitoringResult.is_in_control: bool`, an explicit field per BIN-110's truthiness rule, never a `__bool__`). On a genuine signal (`is_in_control is False`), `record()` synchronously invokes every configured receiver with the result, absorbing any exception a receiver raises into `MonitoringResult.delivery_failures` rather than letting it propagate or discarding it (ADR-010 §§1, 4 — "absorb, but surface", ratified by the product owner 2026-09-11). `Monitor.history` is a plain `tuple[MonitoringResult, ...]` (deliberately not a bespoke collection type — see ADR-009 §6, resolving the "second `Baseline`" discoverability risk BIN-72's review flagged), retained automatically unless `retain_history=False`; `Monitor.clear_history()` is the manual escape hatch for the accepted, documented unbounded-growth risk in a long-running process (ADR-009 §7). No store `Protocol`/port exists in R1 (ADR-009 §8) — the public surface is designed so BIN-73 can add one additively; the receiver surface follows the same discipline (ADR-010 §3) — no `Protocol`/base class for a receiver, a plain `Sequence[SignalReceiver]` instead, chosen specifically so BIN-80 (fan-out, R2) and BIN-81 (formal handler interface, R2) can build on it additively rather than requiring a breaking rewrite.

**Boundary convention (ADR-009 §5, resolving BIN-69 OQ-3 / BIN-112):** every comparison is strict — a point exactly at a control limit, or a CUSUM statistic exactly equal to the decision interval, is in control, not out of control. Verified against convergent secondary corroboration of all three primary sources (Montgomery, Lucas & Saccucci 1990, Siegmund 1985 via NIST's restatement); primary texts remain paywalled and this must be re-checked against their actual page text before `BIN-84`'s property-based tests treat it as permanently settled.

**Full field-level treatment (domain-modeller pass, BIN-69 + BIN-72; extended by this system-architect pass, BIN-75 + BIN-76):** `Monitor` and `MonitoringResult` have complete Object Map and Value Object Inventory entries below — invariants, structure, operations, the constructor-validation decision, the `__bool__` decision ADR-009 §4 delegated (`MonitoringResult.__bool__` raises `TypeError`), and now (ADR-010) the delivery mechanism, the three new `MonitoringResult` fields, and the new `DeliveryFailure` value object. The accumulator-reset-after-signal question remains explicitly open — see Open Questions, `BIN-113`; ADR-010 does not touch it.

**Signal delivery (ADR-010, new this pass):** `MonitoringResult` gains `direction: str | None`, `fitted_artefact: FittedControlLimits`, and `delivery_failures: tuple[DeliveryFailure, ...]`. A receiver is any `Callable[[MonitoringResult], None]` (type-aliased as `SignalReceiver`, no formal `Protocol`) supplied via `Monitor(artefact, receivers=[...])`. Delivery is synchronous, inside `record()`, after the chart-specific check and before the history append, and only on a genuine signal. `caliper.monitoring.log_receiver` is R1's one built-in receiver — stdlib `logging.getLogger("caliper.monitoring")` at `WARNING` (required by BIN-76 SC4's zero-config-visibility scenario, not a style choice — see ADR-010 §6), carrying the full signal content via `extra=`.

### Cross-context dependency

Baseline depends on Measurement. Measurement is independent. Monitoring depends on both Baseline and Measurement. The shared vocabulary between Measurement and Baseline is `ScoringResult` and `Provenance`; Monitoring additionally shares `FittedControlLimits` with Baseline. All are immutable value objects or (Baseline, and now the `Monitor` accumulator's private internals) mutable state deliberately confined to one owning object — so every cross-context dependency is on stable, frozen types except where a context's own single mutable object (`Baseline`, `Monitor`) is that context's entire reason to exist.

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

### Monitor — the domain's second mutable object

**What it is:** an engineer-held object constructed from exactly one fitted control-limit artefact (`FittedControlLimits` — any of `FittedEWMA`, `FittedCUSUM`, `FittedShewhart`). It records Phase II `ScoringResult` observations against that artefact one at a time, returning a `MonitoringResult` per call, and — unless opted out — retains a session-scoped, ordered history of those results.

**Invariants:**

1. **Provenance consistency with its fitted artefact.** Every recorded observation's provenance must match the artefact's provenance on both dimensions (model version, scoring criteria) — checked via `compare_provenance()` (BIN-68, reused unmodified) before any chart-specific comparison runs (ADR-009 §2). A mismatch raises `ProvenanceMismatchError`; the observation is not recorded and never enters history.

2. **Recording requires a complete `ScoringResult`.** An incomplete or malformed input is rejected with `InvalidObservationError` before any comparison runs and before anything is appended to history — reuses Baseline's Phase I category (BIN-63); no new taxonomy entry (ADR-009 §3).

3. **Accumulator state is private, chart-specific, and belongs to exactly one `Monitor` instance.** Nothing for Shewhart (memoryless by design — BR-4); the EWMA smoothed statistic; CUSUM's two one-sided running sums (`S_hi`, `S_lo`). State is never read from or written to the fitted artefact (the artefact remains immutable per ADR-004/BIN-108) and is never shared between two `Monitor` instances, even two constructed from the same artefact — each holds an entirely independent accumulator, initialised fresh at construction (ADR-009 §1, resolving BIN-69's A1 feasibility risk and SC5's "first observation needs no prior history").

4. **A genuine signal is never raised.** An out-of-control determination is a normal, successful return value (`MonitoringResult.is_in_control = False`), never an exception (BR-7, ratified project-wide — "signals are not errors"). Only the two precondition violations above are exceptional.

5. **History is append-only and insertion-ordered.** Every successfully recorded `MonitoringResult` — one that did not raise — is appended to history in the order `record()` was called; a refused attempt never appears, by construction (invariants 1 and 2 both gate before any append happens — there is no separate "don't record refused attempts" check to forget).

6. **Strict-inequality boundary convention, uniform across chart types.** A point exactly at a control limit (EWMA/Shewhart) or exactly at the decision interval (CUSUM) is in control, not out (ADR-009 §5). One convention, not three independently-chosen ones.

7. **Delivery is attempted only for a genuine signal, and never lets an exception escape `record()`.** *(New, ADR-010 §4.)* Every configured receiver is invoked, in order, with the result, only when `is_in_control is False`. A receiver that raises does not stop the next receiver from being attempted, and never propagates out of `record()` — "absorb, but surface" (ratified by the product owner, 2026-09-11): the failure is captured into `MonitoringResult.delivery_failures`, not raised and not silently discarded.

8. **A `Monitor`'s receivers are fixed at construction.** *(New, ADR-010 §3.)* No method adds or removes a receiver after `Monitor.__init__` returns — R1 needs exactly this, and it keeps `record()`'s delivery step free of any mutable-configuration-during-iteration hazard.

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `artefact` (private) | `FittedControlLimits` | The fitted artefact this monitor was constructed from — referenced, never copied or mutated |
| accumulator (private, chart-specific) | implementation detail, not public | Nothing for Shewhart; EWMA's smoothed statistic; CUSUM's `(S_hi, S_lo)` pair. Not part of the public surface (ADR-009 §1) |
| `retain_history` (constructor parameter) | `bool` | Default `True`. `False` opts this monitor out of retaining any history at all (ADR-009 §7) |
| `receivers` (constructor parameter) | `Sequence[SignalReceiver]` | Default `()` — no receivers configured. `SignalReceiver = Callable[[MonitoringResult], None]`, a plain type alias, not a `Protocol` (ADR-010 §3). Fixed for the `Monitor`'s lifetime — no add/remove method in R1 |
| history (private backing store) | implementation detail, not public — a `list[MonitoringResult]` is the obvious choice, per ADR-009's own "What domain-modeller still owns" | Append-only; exposed publicly only via `.history`, which returns a fresh `tuple` view — never the backing store itself |

**Operations on Monitor:**

| Operation | Input | Output | Errors |
|-----------|-------|--------|--------|
| `Monitor(artefact, retain_history=True, receivers=())` | `FittedControlLimits`, optional `retain_history: bool`, optional `receivers: Sequence[SignalReceiver]` | `Monitor` | See "Constructor validation" below |
| `record(observation)` | `ScoringResult` | `MonitoringResult` (now carrying `direction`, `fitted_artefact`, `delivery_failures` — ADR-010) | `ProvenanceMismatchError`, `InvalidObservationError`. Never raises for a delivery failure — absorbed into the returned result (ADR-010) |
| `history` (property) | — | `tuple[MonitoringResult, ...]` | — |
| `clear_history()` | — | `None` | — |

🚨 **Constructor validation — SUPERSEDED 2026-09-12, corrected here 2026-09-14.**

**`Monitor.__init__` narrows to the three concrete types**, `FittedEWMA`/`FittedCUSUM`/`FittedShewhart` — **not** a structural `isinstance(artefact, FittedControlLimits)` check.

⚠️ **This section previously specified the structural check, and that specification was wrong.** `BIN-120` found the defect it causes: a duck-typed object satisfies the protocol, passes construction, and then raises `AssertionError` from `record()`, because `Monitor` reads **ten** attributes of which **seven are outside the protocol** (`decision_interval`, `direction`, `lcl`, `reference_value`, `smoothing_param`, `target_value`, `ucl`).

ADR-004's 2026-09-12 amendment settles why: **`FittedControlLimits` is a *reporting* contract, not a *monitoring* one.** `isinstance(x, FittedControlLimits)` means *"reports like a fitted artefact"* and never meant *"can be monitored"*. `BIN-135` added **`HasProvenance`** as the two-attribute protocol a third party genuinely can satisfy, and `compare_provenance` accepts that.

**The concrete-type check is correct by construction, not a narrowing of intent.** Monitoring a chart type Caliper does not implement is out of scope; the first plausible caller (`BIN-82`, Western Electric rules) would add a concrete type, not a structural conformer.

⚠️ **The correction was recorded in this document's changelog but not here**, so the normative section continued to specify superseded behaviour for two days — found by external review 2026-09-14. **A changelog entry does not correct a specification.**

On failure, raise `InvalidParameterError` (`context["parameter"] == "artefact"`, `context["kind"] == "invalid"`), consistent with every other constructor-time rejection in the taxonomy. On failure, raise `InvalidParameterError` (`context["parameter"] == "artefact"`, `context["kind"] == "invalid"`), consistent with every other constructor-time rejection in the taxonomy. None of BIN-69's nine scenarios or BIN-72's nine scenarios constructs a `Monitor` from something that is not a real fitted artefact, so this is not a tested requirement — it is offered as the obvious, taxonomy-consistent default for `backend-test-writer`/`domain-implementer` to confirm, not a product decision requiring escalation.

**Design note:** Like `Baseline`, `Monitor` has aggregate-like properties — it enforces invariants on what it accepts and encapsulates its own accumulator and history — without the transactional semantics that define an aggregate in DDD: no unit of work wraps a `record()` call, no commit, no rollback (see "Structural Departures from Service-Oriented DDD" above, which already establishes this for `Baseline` and applies identically here). `Monitor` is **not** an aggregate root in the strict DDD sense; it is the domain's second, and — after this pass — only other, mutable single-owner object, alongside `Baseline`. Unlike `Baseline`, `Monitor` is not itself a collection: `.history` returns a plain `tuple`, and `Monitor` defines no `__len__`/`__iter__`/`__repr__` of its own — an engineer inspects `monitor.history`, never `monitor` directly (ADR-009 §6, deliberately rejecting a bespoke `MonitoringHistory` collection type to avoid a second, structurally-identical-to-`Baseline` type on the public surface — see BIN-72's review finding M3).

⚠️ **Open — not settled by this pass (`BIN-113`):** what happens to a chart's accumulator *after* a signal — reset to zero, reset to a head-start/FIR level (Lucas & Crosier 1982), or continue unchanged — is explicitly undecided. ADR-009 did not settle it and this domain model does not invent an answer. The only thing invariant 3 above commits to is that the accumulator persists *across* `record()` calls (so BR-3/SC3's accumulation behaviour holds) — not what value it takes immediately following a signal. Do not assume any of the three options when implementing; `BIN-113` owns this.

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
        """The ARL_0 the calibration targets, given the Phase I baseline's
        *estimate* of the process — not the true process. A finite baseline
        makes the realised false-alarm rate a random variable around this
        figure, not a guarantee (Quesenberry 1993; Jones, Champ & Rigdon
        2001). Smaller baselines relative to the requested target produce
        more spread; see ADR-005's 2026-09-11 amendment for the measured
        adequacy tiers and the structured advisory this triggers.
        May also differ from requested due to numerical approximation."""
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

**`sigma_estimate` invariant (BIN-119, amended 2026-09-11 after `code-reviewer`'s BIN-119/BIN-120 review; moved to a shared base under BIN-142):** all three concrete types above validate `sigma_estimate` at construction — a `@field_validator` mirroring `ScoringResult.must_be_finite`, now inherited from `FittedArtefactBase` rather than written out three times — raising `InvalidParameterError` (`context["parameter"] == "sigma_estimate"`, `kind == "invalid"`) for `NaN`, `+/-inf`, `0.0`, or a negative value. This is deliberately a *second*, independent guard alongside `_moving_range_sigma`'s own `DegenerateBaselineError` (see the Error Contract Reference below): the fitting-time guard diagnoses an unusable *baseline*, while this one is an invariant of the *type itself* — no `Fitted*` instance may ever hold an unusable sigma, regardless of how it is constructed, not only through `fit_ewma`/`fit_cusum`/`fit_shewhart`. `code-reviewer`'s review caught that the original BIN-119 fix guarded only the fitting path and left every `Fitted*` type constructible directly with `sigma_estimate=inf`/`0.0`/`nan` — the acceptance criterion "no artefact with `sigma_estimate=inf` can be constructed" was not actually met until this validator was added. Per `CLAUDE.md`'s own rule ("Validation belongs in the value object, not the caller").

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

### `MonitoringResult`

**Carried by:** returned from `Monitor.record()`; each entry of `Monitor.history`
**Equality:** by value (all six fields)
**Constraints:**
- All fields required by the type signature except `direction` (nullable) and `delivery_failures` (defaults to `()`); no additional content constraint (mirrors `ScoringResult.reasoning`'s treatment: no emptiness check, since no scenario in either feature file tests one)
- Immutable after creation (mirrors every other result/VO type — `pydantic_core.ValidationError` on reassignment attempt, not a `CaliperError`)
- `chart_type` mirrors the producing artefact's own `FittedControlLimits.chart_type` — not independently re-validated against a closed set here, since the artefact already constrains it
- `direction` is `None` exactly when `is_in_control` is `True` — no scenario tests the inverse being enforced as a hard invariant (i.e. nothing constructs an in-control result with a non-`None` direction directly), so this is a construction-discipline expectation on `Monitor.record()`, not a `@field_validator`-enforced cross-field constraint (ADR-010 §2)

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `is_in_control` | `bool` | Explicit field carrying the determination (BIN-110's truthiness rule). `True` = the observation (Shewhart) or the accumulated pattern (EWMA/CUSUM) is within the calibrated boundary; `False` = a signal |
| `observation` | `ScoringResult` | The Phase II observation just passed to `record()` — satisfies BIN-69 SC2 ("what they see identifies the observation that triggered it") with no separate lookup or correlation id, because `record()` is called once per observation and returns once per call |
| `chart_type` | `str` | Which chart type produced this determination (e.g. `"ewma"`) — satisfies BIN-69 SC9 (checking is uniform across chart types from the engineer's side) by making the chart type inspectable on every result, the same field name as `FittedControlLimits.chart_type` |
| `direction` | `str \| None` | *(New, ADR-010 §2.)* `"upper"` or `"lower"`, reusing `FittedCUSUM.direction`'s existing vocabulary. `None` when `is_in_control` is `True`. `"upper"`: process departed above the calibrated upper boundary. `"lower"`: departed below the lower boundary. Satisfies BIN-75 SC1/SC3, BIN-76 SC1. ⚠️ **Domain-modeller note, this pass: only two of `FittedCUSUM.direction`'s three words are legal here.** `FittedCUSUM.direction` is a *configuration* field with three values (`"two_sided"`, `"lower"`, `"upper"` — which arm(s) `Monitor` checks). `MonitoringResult.direction` is an *outcome* field with only three legal states in total: `"upper"`, `"lower"`, or `None` — `"two_sided"` is never a legal value here, even when the underlying artefact's `direction` is configured `"two_sided"`, because a specific departure is always uni-directional (whichever arm actually crossed `h`). ADR-010's "reusing the existing vocabulary" phrasing is correct in spirit (same two words, same meaning) but could mislead an implementer into treating this as a direct pass-through of the three-valued configuration field. `Monitor._check_cusum` already gets this right in practice (`signalled` is derived per-arm, not from echoing `artefact.direction`) — this note exists so `backend-test-writer`/`domain-implementer` do not "simplify" the eventual `direction=` assignment on `MonitoringResult` into `direction=artefact.direction` for the CUSUM case, which would leak `"two_sided"` onto a signal result and break BIN-75 SC1/SC3's "identifies the direction" requirement (a signal that says "two_sided" identifies no direction at all). |
| `fitted_artefact` | `FittedControlLimits` | *(New, ADR-010 §2.)* The same immutable artefact `Monitor` was constructed from — referenced, never copied. Present on every result, signal or not. Satisfies BIN-75 SC1/SC3 (calibrated parameters "in the same form" regardless of chart type) and BIN-76 SC1, without duplicating any chart-specific field ADR-004 already places on the concrete artefact type |
| `delivery_failures` | `tuple[DeliveryFailure, ...]` | *(New, ADR-010 §1.)* Empty when every configured receiver succeeded (or none were configured, or no signal occurred to attempt delivery for). One entry per receiver that raised during this `record()` call. Populated by `Monitor`'s own delivery loop, never by the receiver reporting on itself — satisfies BIN-75 SC9 / BIN-76 SC6's "does not depend on the [receiver/logging] mechanism that just failed" |

**Construction:** built internally by `Monitor.record()` only — no scenario in either feature file constructs one directly, so no public factory is specified. As of ADR-010, construction is two-step internally: a provisional result (with `delivery_failures=()`) is built first and passed to each receiver, then — only if any receiver raised — `model_copy(update={"delivery_failures": ...})` produces the final, returned/stored result (ADR-010 §4). This is an implementation detail of `Monitor.record()`, not a second public construction path.
**Rejects:** nothing beyond field presence and type — no numeric constraint the way `ScoringResult.score` has finiteness.

### `DeliveryFailure`

*(New, ADR-010 §1.)* **Carried by:** `MonitoringResult.delivery_failures` — never constructed or held anywhere else.
**Equality:** by value (all three fields)
**Constraints:** immutable after creation; no content constraint on any field beyond type — `receiver`, `error_type`, `error_message` are all free-form strings, since a receiver is arbitrary engineer-supplied (or `caliper.monitoring.log_receiver`'s built-in) code and its raised exception is not assumed to be a `CaliperError`.

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `receiver` | `str` | Identifies which receiver failed (e.g. its `repr`/`__qualname__`). Meaningful once more than one receiver exists (BIN-80, R2); in R1 there is at most one configured receiver, so this is forward-compatible metadata, not yet load-bearing for disambiguation |
| `error_type` | `str` | `type(exc).__name__` — the machine-branchable "why". Deliberately a string, not the live exception object, to avoid retaining tracebacks/closures in `Monitor.history`'s already-accepted unbounded-growth risk (ADR-009 §7; ADR-010 §1) |
| `error_message` | `str` | `str(exc)` — the human-readable "why" |

**Construction:** built internally by `Monitor.record()`'s delivery step only — no public factory.
**Rejects:** nothing — see Constraints.

### Domain-modeller verification, this pass (BIN-75 + BIN-76, following ADR-010)

ADR-010 was written as a combined system-architect pass and already carried its
domain-model updates through to this file directly (see the 2026-09-11
"system-architect" changelog entry below) — an efficient departure from the
usual architecture → domain-modeller handoff, but one the pipeline still asks
this pass to check, not rubber-stamp. Three judgement calls were named
explicitly as this pass's to make, not inherited from the ADR. Verified/decided
below; none change any field, type, or scenario binding ADR-010 already
established.

**1. Is `DeliveryFailure` a value object in the inventory, or an implementation
detail of `MonitoringResult`? — Confirmed: a value object, correctly given full
inventory treatment.** It fails the "implementation detail" test on every axis
that matters: it is reachable from `MonitoringResult.delivery_failures`, a
field on the public result every `record()` call returns, with no private
prefix and no accessor gate; an engineer is expected to read it directly
(BIN-75 SC9 / BIN-76 SC6's whole point is that this information is public and
mechanism-independent); it has value equality and immutability like every
other VO in this inventory; and `code-reviewer`/`domain-implementer` need a
named type to type-hint `receiver`/`error_type`/`error_message` against
without falling back to an untyped tuple or dict. The one thing that would
have argued for "implementation detail" — that it is only ever constructed
internally by `Monitor.record()`, with no public factory — is already true of
`MonitoringResult` itself (Value Object Inventory, "Construction" note above)
and has never disqualified a type from this inventory before. Confirmed
correct as written; no change.

**2. Does `fitted_artefact` on `MonitoringResult` create a reference cycle or
memory concern given `Monitor.history` retains every result? — Checked, not
assumed: no cycle exists, and the marginal cost is one pointer per result, not
a duplicated artefact.** Tracing the actual reference graph:
`Monitor._artefact` → the `FittedControlLimits`-satisfying artefact (a frozen
Pydantic model of scalars — chart type, means, sigma, ARL figures, calibration
method, and chart-specific fields such as `ucl`/`lcl` or `decision_interval`).
`Monitor._history` → a list of `MonitoringResult`s, each now also holding
`fitted_artefact` pointing at that *same* artefact instance (ADR-010 §2:
"referenced, never copied"). For a cycle to exist, the artefact would need to
hold a reference back to `Monitor` or to any `MonitoringResult` — it does not:
every field on `FittedControlLimits` and its three concrete types is a scalar
(`float`/`str`/`int`), per the Fitted Artefact Protocol above, with no
back-reference of any kind. The graph is a DAG (`Monitor` → history entries →
shared artefact), not a cycle: CPython's refcounting alone can reclaim it, the
cycle-collector is never needed for this structure, and there is no
traceback/frame-retention risk of the kind that made holding a live exception
on `DeliveryFailure` the wrong call (§1 above) — an artefact is inert data, not
a raised exception carrying closures. On marginal memory cost: because the
artefact is referenced, not copied, adding `fitted_artefact` to every
historical `MonitoringResult` costs one pointer (~8 bytes plus a refcount
increment) per entry, regardless of how large the artefact itself is — it does
not multiply the artefact's own footprint across history the way embedding a
copy of its fields would. This does not compound `Monitor.history`'s
already-accepted unbounded-growth risk (ADR-009 §7) in any material way; it is
a rounding error against the per-entry cost `MonitoringResult` already carries
via `observation: ScoringResult` (three fields, one of them a nested
`Provenance`). No action needed — `fitted_artefact` is safe to keep as a plain
reference field exactly as ADR-010 §2 specifies.

**3. Does `direction: str | None` want a closed discriminator like `kind`, or
does it track `FittedCUSUM.direction`'s vocabulary semi-openly? — Semi-open
plain `str`, matching this codebase's established convention for
chart-specific vocabulary — and explicitly *not* the same axis as `kind`
vs. `reason`.** CLAUDE.md's warning not to unify `kind` (closed
discriminator, `invalid_parameter`'s two fixed values) with `reason`
(descriptive, open text on `invalid_observation`/`degenerate_baseline`) is
about two *error-context* keys serving different jobs; `direction` is neither
— it is a result field, not an error context key, so it is not a candidate for
unifying with either. The real comparison is to this codebase's other
enumerable-but-not-`Literal` string fields: `chart_type`, `calibration_method`,
`sigma_estimation_method`, and `FittedCUSUM.direction` itself are all plain
`str` despite each having a small, closed value set in practice — ADR-004
established no `Literal` precedent anywhere in the Fitted Artefact Protocol,
and a `Literal` on `MonitoringResult.direction` would be the first
introduction of that pattern into a codebase that has deliberately avoided it
everywhere else, for a value set no less likely to be extended carefully than
`chart_type`'s own three values. Plain `str | None` is correct, and ADR-010's
choice stands — but see the ⚠️ note on the `direction` field row above: the
"reuses the vocabulary" framing needs the caveat that only two of
`FittedCUSUM.direction`'s three words are ever legal outcomes here, which is
a distinction worth keeping explicit precisely because CLAUDE.md's `kind`/
`reason` precedent already established that this project polices this kind of
flattening deliberately.

---

#### `MonitoringResult.__bool__` — decided: raises `TypeError` (ADR-009's delegated decision)

ADR-009 §4 identified two BIN-110-legal resolutions and explicitly delegated the choice to this pass rather than picking one itself. Both are legal because `MonitoringResult` has an explicit yes/no field (`is_in_control`), which is BIN-110's precondition for allowing truthiness at all — leaving `__bool__` undefined was never one of the options, because Pydantic's inherited object-identity truthiness would make `bool(result)` unconditionally `True`, the exact P0 defect BIN-110 fixed on `SufficiencyResult`.

**Decision: `__bool__` raises `TypeError`, the same treatment as `ScoringResult` and the three `Fitted*` artefacts.** `bool(result)` is forbidden; callers read `result.is_in_control` explicitly.

```python
def __bool__(self) -> NoReturn:
    raise TypeError(
        "MonitoringResult has no True/False meaning; check `is_in_control` "
        "directly instead of using it in a boolean context"
    )
```

**Why — engaging with both options rather than inheriting ADR-009's recommendation unexamined:**

`SufficiencyResult.__bool__` returning `is_sufficient` works precisely because "is this baseline ready?" has exactly one natural reading, and the field name states it positively — `bool()` and the field can never disagree about which reading was intended. `MonitoringResult` does not have that property. An engineer writing `if monitor.record(observation):` is really asking one of two different questions depending on which word they are mentally emphasising — "is everything still fine?" (→ truthy-on-in-control, matching the field) or "did something notable just happen?" (→ truthy-on-signal, the opposite). A monitoring signal is, definitionally, the notable event; nothing about the call site disambiguates which reading the author intended, unlike `SufficiencyResult` where only one reading exists in the first place.

Making `__bool__` return `is_in_control` (the alternative) does not just risk the same "always `True`" failure BIN-110 fixed — it risks something distinct, and arguably worse: a **silently inverted** monitoring loop. `if monitor.record(observation): alert(...)` under that alternative alerts on the boring, in-control majority of calls and stays silent on the rare, genuine signal — the exact case this library exists to surface. That bug would not look broken: false alerts would likely get noticed and the condition "fixed" back to correct, or dismissed as noise, while real degradations passed through unalerted the whole time. This is a materially worse failure mode than a no-op always-`True`, which at least fails the same way every time and is easier to notice as clearly wrong.

Raising forecloses both failure modes at once, at the one call site — `monitor.record()` — used far more densely than any single scoring or fitting call in the library (once per production observation, indefinitely, in a long-running process). Every occurrence of the DX snippet across ADR-009, both architecture.md summaries, and both feature files already reads `outcome.is_in_control` (or an equivalent observable-outcome Gherkin phrasing), never a bare truth test — so raising costs the common case nothing; it only removes a way to write code that reads correctly and behaves backwards.

**Reversibility — the same asymmetry ADR-009 names, applied here explicitly:** loosening a raise into a meaningful `__bool__` later is backward-compatible for every existing caller (none can be calling `bool()` today, since it currently raises). Tightening a working `bool()` into a raise later would break any caller who had started relying on it — the same direction every other close call in this project has resolved (empty-output rejection, score-range, criteria equality): start strict, loosen only on evidence of real need.

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
| **Observation** | A scoring result recorded into a baseline. Observations are the unit of baseline data. In R1, an observation IS a `ScoringResult` — no additional fields. **OQ-8 (open)** may add a timestamp or sequence index — see Open Questions; this is also the recorded trigger for adding `whenever` as a dependency (CLAUDE.md, "Stack Members Not Yet Used" — zero `datetime` usage anywhere in `src/caliper` today; a timestamp on `Observation` is named as the first plausible caller). The same term is reused for Phase II: a "Phase II observation" is a `ScoringResult` recorded via `Monitor.record()` rather than `Baseline.record()` — same underlying type, different context, different invariants enforced on recording (ADR-009). | Baseline, Monitoring | BIN-63, BIN-69 |
| **Monitor** | The engineer-held object that records Phase II observations against one fitted control-limit artefact, holds that artefact's chart-specific accumulator state privately, and (unless opted out) retains a session-scoped history of what it has recorded. The domain's second, and only other, mutable single-owner object alongside `Baseline` — but not itself a collection; see its Object Map entry. | Monitoring | ADR-009, BIN-69, BIN-72 |
| **Monitoring result** | The immutable, per-call outcome of `Monitor.record()`: an explicit in-control/out-of-control determination, the observation that produced it, and which chart type produced it. Never raised for a genuine signal — a signal is simply a `MonitoringResult` with `is_in_control=False`. `bool()` is forbidden; see the Value Object Inventory. | Monitoring | ADR-009 §4, BIN-69 |
| **Monitoring history** | The ordered, session-scoped sequence of `MonitoringResult`s a `Monitor` has recorded, returned as a plain `tuple[MonitoringResult, ...]` via `Monitor.history` — deliberately not a bespoke collection type, to avoid a second `Baseline`-shaped type on the public surface. Retained automatically by default; `retain_history=False` opts out; `clear_history()` is the manual escape hatch. Never durable across process runs — that is `BIN-73`'s, unbuilt, concern. Distinct from `Baseline.observations` — different collection, different owning type, never mixed (BIN-72 SC9). | Monitoring | ADR-009 §6-§8, BIN-72 |
| **Accumulator** | A `Monitor`'s private, chart-specific carried-forward state between `record()` calls: none for Shewhart (memoryless), the smoothed statistic for EWMA, the two one-sided running sums for CUSUM. Lives on `Monitor`, never on the immutable fitted artefact. What happens to it immediately after a signal is open — see `BIN-113` in Open Questions. | Monitoring | ADR-009 §1 |
| **Session** | Informal term (used throughout BIN-72's feature file) for the lifetime of one running Python process holding one `Monitor` instance. Not a domain type — there is no `Session` object. A new process constructing a new `Monitor` starts with empty history by construction, which is what "does not carry over between runs" (BIN-72 SC5) means concretely. | Monitoring | BIN-72 |
| **Baseline** (Phase I baseline) | An ordered, provenance-consistent collection of observations from which control limits are fitted. The only mutable object in the domain. | Baseline | BIN-63 |
| **Phase I** | The baseline collection and fitting phase. The engineer collects observations, checks sufficiency, and fits control limits. | Baseline | BIN-63, BIN-65/94/95 |
| **Phase II** | The ongoing monitoring phase. BIN-68 covers provenance comparison across the phase boundary; BIN-69/BIN-72 (ADR-009) now cover Phase II monitoring logic itself — recording an observation against a fitted artefact, checking it for a signal, and reviewing the session's history of what was recorded. | Baseline, Monitoring | BIN-68, ADR-009, BIN-69, BIN-72 |
| **Sufficiency** | Whether a baseline has enough observations for reliable control limit fitting. The check is advisory (reports status); fitting is where enforcement occurs. | Baseline | BIN-64 |
| **Sufficiency threshold** | The minimum number of observations required to fit at all — the hard floor. Configurable per engineer and per chart type (BIN-64 BR-3, BR-5). Library default: 100 individual observations (ADR-005). Must be positive (BIN-64 BR-8). Below it, fitting raises `InsufficientBaselineError`. **Distinct from adequacy (below) — see ADR-005 amendment 2026-09-11.** | Baseline | BIN-64, ADR-005 |
| **Adequate baseline size** *(new, ADR-005 amendment 2026-09-11, BIN-114)* | A second, target-dependent line above the sufficiency threshold: `adequate(target_arl)`, measured (not derived) at ≈300 observations for `target_arl` ≤ 200 and ≈500 for `target_arl` > 200. A baseline at or above the sufficiency threshold but below `adequate(target_arl)` still fits successfully — it is never blocked — but carries a structured, non-raising advisory (`DataQualityConcern`-shaped) naming the gap. Below the sufficiency threshold, fitting is refused regardless of `adequate()`; the two lines are independent. **Provisional**, pending Jones, Champ & Rigdon (2001) — see ADR-005 amendment for the full derivation, caveats, and the still-open exact API carrier (BIN-114 OQ-3). | Baseline | BIN-114, ADR-005 (2026-09-11 amendment) |
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
| **Signal** | An out-of-control determination from Phase II monitoring — concretely, a `MonitoringResult` with `is_in_control=False`, carrying `direction` and `fitted_artefact` (ADR-010 §2). The determination itself was modelled by ADR-009 (BIN-69); its R1 *delivery* — a `SignalReceiver` callable invoked synchronously on a genuine signal, absorbing but surfacing any receiver failure — is modelled by ADR-010 (BIN-75, BIN-76). Severity, webhooks, `RaiseOnSignal`, fan-out, and a formal handler interface remain unmodelled — BIN-77 through BIN-82, Release 2. | Monitoring | ADR-009, ADR-010 |
| **Signal receiver** / **`SignalReceiver`** | Any `Callable[[MonitoringResult], None]` supplied to `Monitor(artefact, receivers=[...])`. A plain type alias, not a `Protocol` or base class — no formal interface exists in R1 (ADR-010 §3). Invoked synchronously by `Monitor.record()`, once per configured receiver, only when a genuine signal occurs. A receiver that raises does not stop the recording call or the next receiver; its exception is captured, not propagated (see Delivery failure, below). | Monitoring | ADR-010 §§3–4 |
| **`log_receiver`** | R1's one built-in `SignalReceiver` (`caliper.monitoring.log_receiver`). Logs to `logging.getLogger("caliper.monitoring")` at `WARNING` — the level is required, not stylistic, to satisfy BIN-76 SC4's zero-configuration visibility guarantee against Python's `logging.lastResort` default. Carries the full signal content (`direction`, `fitted_artefact`, `observation`) via the stdlib `LogRecord`'s `extra=` mapping. Uses no third-party structured-logging library (BR-1, CLAUDE.md's ratified stdlib-`logging` decision). | Monitoring | ADR-010 §6 |
| **Delivery failure** / **`DeliveryFailure`** | The record of one `SignalReceiver` raising during delivery: which receiver (`receiver: str`), and why (`error_type: str`, `error_message: str`). Never raised itself — absorbed by `Monitor.record()` into `MonitoringResult.delivery_failures`, "absorb, but surface" (ratified by the product owner, 2026-09-11). Reachable only through the public result the recording call already returns — never through the receiver mechanism that just failed (ADR-010 §1). | Monitoring | ADR-010 §1 |
| **SPCPort** | The port interface for the SPC engine (ADR-001). The boundary between the domain and the statistical computation layer. Fitting operations are behind this port. | Baseline | ADR-001 |
| **Agent output** | The text produced by the engineer's agent, the subject being scored. Required, rejected if empty or whitespace-only (**settles former OQ-10**). Named `agent_output`, not `output`, to keep the `agent_` prefix consistent with `agent_input` and the feature files' own wording. | Measurement | BIN-59, ADR-006 §3, §6 |
| **Agent input** | The input that produced the agent output, when the caller has it. Optional, not validated for emptiness (a proactively-acting agent may legitimately have none), and **not** carried onto `Provenance` or `ScoringResult` — it is the subject being measured, not the measurement configuration. Named `agent_input`, not `input`, because bare `input` shadows a Python builtin and this project's `ruff` config (`flake8-builtins`, rule `A002`) rejects it. | Measurement | BIN-59, ADR-006 §3 |
| **Judge provider** / **`JudgeProviderPort`** | The port through which a `Judge` obtains a score and reasoning from an LLM (or any scoring backend). A real hexagonal port — `@runtime_checkable Protocol`, no concrete adapter yet, only `FakeJudgeProviderPort` in test code. Interpreting a provider's raw response shape is the adapter's job, never the domain's. | Measurement | ADR-006 §1 |

**Consistency notes:**
- "False alarm tolerance" is used throughout the feature files as a neutral term. ADR-004 resolved this to ARL_0 as the primary representation.
- "Spread measure" in BIN-66 SC1 refers to `baseline_spread` (shared core sample standard deviation). "Sigma estimate" in BIN-95 SC2 refers to `sigma_estimate` (shared core MR-based estimate). These are explicitly different quantities, both in the shared core.
- "Observation" and "scoring result" are the same data — the term shifts at the context boundary. A "scoring result" becomes an "observation" when recorded into a baseline.
- "Output"/"input" in earlier drafts of the PRD and feature file text are the informal predecessors of the canonical `agent_output`/`agent_input` terms ADR-006 settled on. Same concepts, more precise names.
- "History" (`Monitor.history`, Phase II `MonitoringResult`s) is distinct from "observations" (`Baseline.observations`, Phase I `ScoringResult`s) — different collections, different owning types, different invariants, never mixed (BIN-72 SC9).

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

**Confirmed still true after ADR-009 (BIN-69/BIN-72):** `Monitor.record()` is likewise a synchronous call-and-return — it returns a `MonitoringResult` directly, never publishes an event.

**Updated after ADR-010 (BIN-75/BIN-76, this pass):** E4's signal-delivery mechanism is now specified for R1 — but it remains a synchronous callback (`SignalReceiver`), not a domain event. `Monitor.record()` invokes each configured receiver directly and synchronously; it does not construct, queue, or publish an event object of any kind, and `context.md`'s `SignalEvent` sketch (signal, judgement result, consecutive signal count, severity) is not adopted — consecutive-signal-count and severity remain unspecified (BIN-77, R2) and a synchronous callable has no need for an event envelope. **The Domain Event Catalogue remains empty for R1** — this is a deliberate, re-confirmed absence, not an oversight: ADR-010 was the natural point at which an event *could* have been introduced, and it was not, because nothing in either BIN-75 or BIN-76's fifteen scenarios requires one. Should BIN-78 (webhook, R2) or BIN-80 (fan-out, R2) later need queuing, retry, or at-least-once delivery semantics, an event-based redesign becomes worth reconsidering then — not pre-emptively here.

---

## Error Contract Reference

ADR-002 defines the error taxonomy. Nine typed exceptions under `CaliperError`, each with required `context` fields. The full specification is in `docs/architecture/adr/002-error-contract-exception-taxonomy.md`. **ADR-008** additionally settles how tests assert against this taxonomy: `isinstance` plus required `context` key presence, **never** message text — `recovery_hint` is human-facing prose and deliberately untested. This governs even where it conflicts with `test-patterns`' general Pydantic-validation guidance (which assumes an HTTP boundary Caliper does not have).

| Exception | Category string | Required context fields | Raised by |
|-----------|----------------|------------------------|-----------|
| `InvalidParameterError` | `invalid_parameter` | `parameter`, `constraint`, `kind` (`"missing"` or `"invalid"`) | Judge creation (BIN-57), criteria config (BIN-58), sufficiency threshold (BIN-64), fitting parameters (BIN-65/94/95), `Monitor` construction from a non-artefact or a structurally-conforming-but-unsupported artefact (BIN-69/BIN-120), direct construction of any `Fitted*` type with a non-finite or non-positive `sigma_estimate` (BIN-119, amended 2026-09-11) |
| `MissingPrerequisiteError` | `missing_prerequisite` | `prerequisite`, `operation` | Scoring without criteria (BIN-59) |
| `ProviderError` | `provider_failure` | `provider`, `operation` | LLM provider failure during scoring (BIN-59) |
| `MalformedResponseError` | `malformed_response` | `operation`, `expected_shape` | Unparseable judge response (BIN-59) |
| `JudgeRefusalError` | `judge_refusal` | `provider`, `operation` | Judge safety-filter refusal (ADR-002) |
| `ProvenanceMismatchError` | `provenance_mismatch` | `mismatches: dict[str, dict[str, str]]` (amended 2026-09-10, was `dimension`/`expected`/`received` — see ADR-002 Amendment) | Baseline recording (BIN-63), Phase II comparison (BIN-68), Phase II monitor recording (BIN-69, `Monitor.record()`, calls `compare_provenance()` internally — ADR-009 §2) |
| `InvalidObservationError` | `invalid_observation` | `reason`, `missing_fields` | Incomplete input to baseline (BIN-63), incomplete input to Phase II monitor recording (BIN-69, `Monitor.record()`, reused not a new category — ADR-009 §3) |
| `InsufficientBaselineError` | `insufficient_baseline` | `have`, `need` | Fitting from too-small baseline (BIN-65/94/95) |
| `DegenerateBaselineError` | `degenerate_baseline` | `reason` (`"zero_variance"`, or, since BIN-119, `"non_finite_sigma_estimate"` / `"sigma_estimate_underflow"`, or, since BIN-142, `"non_representable_control_limits"`) | Fitting from zero-variance baseline (BIN-65/94/95); fitting from a baseline whose moving-range sigma estimate overflows to `inf` or underflows to exactly `0.0` (BIN-119, `_moving_range_sigma` in `spc_numerics.py`, shared by all three chart types) |

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
| Check sufficiency | BIN-64 | Optional keyword-only: `threshold`, `chart_type` | `SufficiencyResult` | Baseline — **implemented** (advisory; never raises). ⚠️ **Signature does not yet carry `target_arl`** — the target-dependent adequacy advisory ADR-005's 2026-09-11 amendment specifies (`BIN-114`) is domain-modelled at the policy level only; exact carrier (extend this signature vs. a field on `Fitted*`) is still open (`BIN-114` OQ-3), not yet implemented. |
| Fit EWMA | BIN-65 | `Baseline`, `target_arl`, optional `smoothing_param` | `FittedEWMA` | Baseline — **implemented** (BIN-65) |
| Fit CUSUM | BIN-94 | `Baseline`, `target_arl`, optional `reference_value`, optional `direction` | `FittedCUSUM` | Baseline — **implemented** (BIN-94) |
| Fit Shewhart | BIN-95 | `Baseline`, `target_arl` | `FittedShewhart` | Baseline — **implemented** (BIN-95) |
| Review artefact | BIN-66 | Any `FittedControlLimits` | Read properties; `audit_summary()` | Baseline — **implemented** (BIN-66) |
| Compare provenance | BIN-68 | `ScoringResult`, `FittedControlLimits` | Confirms compatibility or raises `ProvenanceMismatchError` | Baseline — **implemented** (BIN-68) |
| Create monitor | BIN-69, BIN-75 | one of `FittedEWMA`/`FittedCUSUM`/`FittedShewhart` (⚠️ **not** any `FittedControlLimits` — BIN-120), optional `retain_history: bool`, optional `receivers: Sequence[SignalReceiver]` (ADR-010) | `Monitor` | Monitoring — **implemented** |
| Record Phase II observation | BIN-69, BIN-75 | `ScoringResult` | `MonitoringResult` (now carrying `direction`, `fitted_artefact`, `delivery_failures` — ADR-010) | Monitoring — **implemented**. Raises `ProvenanceMismatchError`, `InvalidObservationError`; never raises for a signal or a delivery failure. |
| Review monitoring history | BIN-72 | (none) | `tuple[MonitoringResult, ...]` | Monitoring — **implemented**. Zero-config by default. |
| Clear monitoring history | BIN-72 | (none) | `None` | Monitoring — **implemented**. Manual escape hatch, no automatic eviction policy in R1. |
| Deliver a signal to configured receivers | BIN-75 | (implicit — part of `record()`) | Each configured `SignalReceiver` invoked with the `MonitoringResult`; failures absorbed into `delivery_failures` | Monitoring — **implemented**. Synchronous, inside `record()`, only on a genuine signal. Never raises. |
| Log a signal via the built-in receiver | BIN-76 | `MonitoringResult` (as any `SignalReceiver`) | `None` (writes a `WARNING`-level record to `logging.getLogger("caliper.monitoring")`) | Monitoring — **implemented** as `log_receiver` (a function, not a `LogReceiver` class). `caliper.monitoring.log_receiver`, stdlib `logging` only. |

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

**Three new questions, added this pass (domain-modeller, BIN-69 + BIN-72,
following ADR-009) — numbered 12-14, continuing on from the original eleven
rather than belonging to that original set.** Two are settled here; one
(#12) is explicitly not this pass's to close.

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
| 12 | **What happens to a `Monitor`'s chart-specific accumulator immediately after a signal** — reset to zero, reset to a head-start/FIR level (Lucas & Crosier 1982), or continue unchanged? | Whoever picks up `BIN-113` | `Monitor`'s per-`record()` accumulator update logic for EWMA/CUSUM | ADR-009 §1 (deliberately left unsettled) | **Open — explicitly not this pass's to close.** ADR-009 delegates it to `BIN-113`. This model commits only to the accumulator persisting *across* `record()` calls (BR-3/SC3); not to its value immediately after a signal. Background: Lucas & Crosier (1982) on the FIR feature, held at `Projects/caliper/references/papers/`. |
| 13 | ~~Whether `Monitor`'s constructor validates the fitted artefact beyond its type.~~ | — | — | ADR-009, "What domain-modeller still owns" | **SETTLED, this pass** — `isinstance(artefact, FittedControlLimits)`, mirroring `Judge.provider`'s existing structural check against a `@runtime_checkable` Protocol; raises `InvalidParameterError` (`kind="invalid"`) on failure. Not scenario-tested by either feature file — offered as the taxonomy-consistent default, not a product decision. See Object Map — Monitor. |
| 14 | ~~`MonitoringResult.__bool__` — return `is_in_control`, or raise?~~ | — | — | ADR-009 §4 (explicitly delegated to domain-modeller) | **SETTLED, this pass** — raises `TypeError`, the same treatment as `ScoringResult`/`Fitted*`. See Value Object Inventory — `MonitoringResult`, "Truthiness decision" for the full reasoning, including why this pass did not simply inherit ADR-009's recommendation without engaging with it. |
| 15 | ~~WHERE does a delivery failure surface, given the "absorb, but surface" ratification?~~ | — | — | BIN-75 OQ-1, BIN-76 OQ-1 (shared) | **SETTLED, ADR-010 §1** — an in-band field, `MonitoringResult.delivery_failures`, populated by `Monitor` itself, never by asking the failed receiver to report on itself. Public, carries both "that" and "why" (`error_type`/`error_message`), satisfying the tightened scenario wording both requirements reviews required. |
| 16 | ~~Where does an engineer arrange to be told about a signal?~~ | — | — | BIN-75 OQ-2 | **SETTLED, ADR-010 §3** — `Monitor(artefact, receivers=[...])`, a keyword-only constructor parameter accepting `Sequence[SignalReceiver]`. No `Protocol`, no registration method, no module-level state. Fixed for the `Monitor`'s lifetime in R1. |
| 17 | ~~Is signal delivery synchronous within `record()`, or deferred?~~ | — | — | BIN-75 OQ-3 | **SETTLED, ADR-010 §4** — synchronous, required by the ordering guarantees (BIN-75 SC6, BIN-76 SC5) and the "told without separately inspecting the outcome" guarantee (BIN-75 SC4). |
| 18 | ~~What standard-library logging level does a drift signal use?~~ | — | — | BIN-76 OQ-2 | **SETTLED, ADR-010 §6** — `WARNING`. Required, not stylistic: only `WARNING` and above are visible via Python's `logging.lastResort` default handler, which BIN-76 SC4 requires without any engineer configuration. |
| 19 | ~~What logger namespace does Caliper log signals under?~~ | — | — | BIN-76 OQ-3 | **SETTLED, ADR-010 §6** — `"caliper.monitoring"`, following CLAUDE.md's ratified `logging.getLogger("caliper")`-family convention, scoped to the Monitoring bounded context specifically. |

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

> 🚨 **Keeping this table honest — and this note did not work.** The status
> column drifted through `BIN-63` and `BIN-64`, which prompted the warning
> below. **It then drifted again through the entire `Monitor` family** —
> create, record, review history, clear history, signal delivery, log receiver —
> all shipped under `BIN-69`/`BIN-72`/`BIN-75`/`BIN-76` while their rows still
> read "not yet implemented". Found by external review on 2026-09-14, not by
> anyone reading this note.
>
> **Update the row in the same PR that implements the operation.** This document
> is canonical (the vault copy is a pointer), so a stale status here is a wrong
> answer to the question a new agent most often asks of it: what already exists?
>
> ⚠️ **Treat the recurrence as evidence about the mechanism, not about
> diligence.** A warning sitting beside the thing it guards, naming the exact
> failure and its exact cause, still did not prevent that failure a second time.
> That is `BIN-128`'s thesis in its purest form: **a rule with no mechanical
> representation is enforced by attention, and attention is what fails.** If
> this drifts a third time, the answer is a test that reads this table and
> checks each claimed-unimplemented operation is genuinely absent from
> `caliper.__all__` — not a more strongly worded note.

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
- [x] `Monitor` given full field-level Object Map treatment; not modelled as a DDD aggregate, same discipline as `Baseline` (this pass)
- [x] `MonitoringResult.__bool__` explicitly decided, not left undefined — resolves ADR-009 §4's delegated decision, with reasoning engaging both options, not just adopting the ADR's recommendation (this pass)
- [x] All 18 scenarios across `phase-ii-observation-signal-check.feature` (9) and `in-memory-observation-store.feature` (9) verified bindable against this model, with no `.feature` file changes needed (this pass)
- [x] Accumulator-reset-after-signal left open, not invented — `BIN-113` (this pass)
- [x] `MonitoringResult` extended (not replaced) with `direction`, `fitted_artefact`, `delivery_failures` — no second, near-identical result type introduced (ADR-010 §2, BIN-75 A1)
- [x] New `DeliveryFailure` value object given full Value Object Inventory treatment (this pass)
- [x] Signal receiver surface (`SignalReceiver`, `Monitor(..., receivers=...)`) designed additively — no `Protocol`/base class for a single R1 consumer, but shaped so BIN-80/BIN-81 do not require a breaking rewrite (ADR-010 §3, applying the ADR-009 §8 precedent both PRDs cited)
- [x] All 15 scenarios across `out-of-control-signal-event.feature` (9) and `drift-signal-log-handler.feature` (6) verified bindable against this model, with no `.feature` file changes needed (this pass) — see ADR-010's Bindability tables
- [x] Domain Event Catalogue re-confirmed empty for R1, with reasoning for why ADR-010 did not introduce an event despite being the natural point to do so (this pass)
- [x] Independent second bindability check: all 15 scenarios across `out-of-control-signal-event.feature` (9) and `drift-signal-log-handler.feature` (6) re-verified bindable against this model by reading the actual scenario text directly (not just ADR-010's own table) — no discrepancy found (domain-modeller pass, following ADR-010)
- [x] Three judgement calls decided explicitly, not inherited from ADR-010 without independent reasoning: `DeliveryFailure`'s VO-vs-implementation-detail status (confirmed VO), `fitted_artefact`'s reference-cycle/memory risk (checked — no cycle, marginal cost is one pointer, does not compound the accepted history-growth risk), and `direction`'s discriminator shape (confirmed plain `str`, not `Literal`, not unified with `kind`/`reason` — with a caveat added that only two of `FittedCUSUM.direction`'s three words are ever legal on `MonitoringResult.direction`) — see "Domain-modeller verification, this pass" above (domain-modeller pass, following ADR-010)

---

## Changelog

- 2026-09-15 (BIN-142): **Every float field on every `Fitted*` type must be finite**, enforced by a new shared `FittedArtefactBase` rather than field-by-field. `fit_ewma`/`fit_shewhart` had been returning `ucl=inf`/`lcl=-inf` from a *finite* `sigma_estimate` — an artefact reporting `achieved_arl == 370.0` while being incapable of signalling, since nothing exceeds infinity. ⚠️ **Two defects shared one symptom, and only one was a refusal.** EWMA's `L * sigma * ratio` associates left-to-right, so `L * sigma` overflowed as an *intermediate* even where the final product was representable (at `sigma = 7.09e307`: `inf` versus `6.998e307`); fixed by regrouping to `(L * ratio) * sigma`, because `ratio = sqrt(lambda / (2 - lambda))` is strictly below 1 and can only shrink the operand. **Refusing there would have been over-rejection** — the BIN-123 class — discarding an answer the library could compute. Shewhart's `3 * sigma` has no sub-1 factor to absorb, so it genuinely exceeds float64 and now raises `DegenerateBaselineError` (`reason == "non_representable_control_limits"`) via a shared `spc_numerics.require_representable_limits`, alongside the type-level backstop. `FittedArtefactBase` also absorbs the `sigma_estimate` validator that had existed three times identically (the BIN-125 pattern). 🚨 **BIN-140 had added a postcondition to `achieved_arl` one day earlier, with the stated lesson "any number a numerical routine hands to a caller needs a postcondition" — and this appeared in `ucl`, a field that postcondition never examined. A postcondition on one field is not a postcondition on the artefact.** ⚠️ The property test that should have caught it checked three *named shared-core* fields, and `ucl`/`lcl` are chart-specific by ADR-004's design, so a helper typed against the protocol could not see them; it now enumerates float fields from the model. Extending it was necessary and **not sufficient**: measured with the fix disabled, `overflow_prone_scores` reached the defect region **0 times in 200 draws**, because it draws each score independently and sigma estimation rejects almost every such baseline first. A structured alternating strategy was added; over 200 draws EWMA fits all 200 while Shewhart refuses 128. `fit_cusum` is structurally immune (no observation-scale limit) — asserted, not argued.
- 2026-09-11 (domain-implementer, BIN-119 + BIN-120, `code-reviewer` CHANGES REQUIRED addressed): Two blockers from `code-reviewer`'s review of the entry below, both confirmed as genuine gaps the original fix's tests did not demand. **Blocker 1:** the BIN-119 acceptance criterion "no artefact with `sigma_estimate=inf` can be constructed" was not met by guarding `_moving_range_sigma` alone -- every `Fitted*` type had no field validator of its own, so direct construction (bypassing all three `fit_*()` functions) could still build one with `sigma_estimate=inf`, `0.0`, or (not named by the original review, found while fixing this) `nan`. Fixed by adding a `@field_validator("sigma_estimate")` to `FittedEWMA`/`FittedCUSUM`/`FittedShewhart` (mirroring `ScoringResult.must_be_finite`), raising `InvalidParameterError` -- not `DegenerateBaselineError`, which is a Phase I baseline diagnosis with no baseline in scope at a bare constructor call. Kept alongside, not instead of, the `_moving_range_sigma` fitting-time guard -- see the new "`sigma_estimate` invariant" note under Chart-Specific Artefacts above and the `InvalidParameterError` row below. **Blocker 2:** `Monitor`'s `InvalidParameterError.context["provided"]` (both the constructor rejection and `_check()`'s unreachable fallback) stored the live, rejected `artefact` object directly, unlike every other `"provided"` value in the codebase (which holds a scalar the caller passed). Reproduced: an artefact whose own `__repr__` raises turned a caller's `except InvalidParameterError as e: log(e.context)` into an unhandled crash -- the exact BIN-118 hazard, at a second boundary, using a fix pattern (`_describe_receiver`/`_describe_exception`) already present in the same file but not reused. Fixed by generalising that pattern into a shared `_safe_repr` helper and a new `_describe_artefact`, used at both `context["provided"]` sites -- now always a guarded string (`repr()`, falling back to the type name, then a fixed constant), never the live object. Twenty new tests added (`tests/unit/baseline/test_fitted_artefact_sigma_invariant.py`, two new tests in `tests/unit/monitoring/test_monitor.py`); all four gates re-verified green; `BIN-123`'s `OverflowError` re-confirmed unchanged.
- 2026-09-11 (domain-implementer, BIN-119 + BIN-120, external-review exception-contract fixes): Two `DegenerateBaselineError` context reasons added to the Error Contract Reference table: `"non_finite_sigma_estimate"` and `"sigma_estimate_underflow"`, both raised by `_moving_range_sigma` (`baseline/domain/spc_numerics.py`) -- the shared moving-range sigma estimator all three `fit_*()` entry points delegate to, so the fix covers EWMA, CUSUM, and Shewhart identically rather than three independent guards. Closes BIN-119: a moving-range aggregate that overflows to `inf` (chart with `+/-inf` control limits -- confident, permanent silence) or underflows to exactly `0.0` (`ucl == lcl`, or a raw `ZeroDivisionError` at CUSUM's `record()`-time standardisation) is now rejected at fit time, before any artefact is constructed. Additive to, not a replacement for, the existing `"zero_variance"` guard each `fit_*()` function applies to the raw scores first. Also closes BIN-120: `Monitor.__init__`'s `isinstance(artefact, FittedControlLimits)` check (the `@runtime_checkable` protocol -- true for any structurally conforming object) is narrowed to `isinstance(artefact, (FittedEWMA, FittedCUSUM, FittedShewhart))`, so an object that satisfies the protocol but is none of the three supported chart types is rejected at construction with `InvalidParameterError` (`context["parameter"] == "artefact"`, `kind == "invalid"`) rather than reaching `Monitor._check()`'s dispatch and failing there. `InvalidParameterError`'s raised-by list in the Error Contract Reference updated accordingly. Option A per the ticket's recommendation -- ADR-004 section 3's deliberate rejection of a shared/polymorphic detection boundary is not reopened. `_check()`'s former `raise AssertionError` fallback (unreachable now that the constructor narrows the type, but still required by the type checker for exhaustiveness) is replaced with the same typed `InvalidParameterError`, so no non-`CaliperError` exception type remains reachable, even in principle, from this path. **`BIN-123`** (all three `fit_*()` leaking a raw `OverflowError` from `statistics.fmean` on a baseline whose mean and sigma are representable but whose running sum overflows) is a distinct, deliberately out-of-scope defect for this pass -- verified empirically that this fix's guard sits downstream of that raise and cannot intercept it; confirmed via `docs/domain-model.md`'s "Known gap" convention rather than silently merging the two failure classes.
- 2026-09-11 (domain-modeller, combined BIN-75 + BIN-76 pass, following ADR-010): Reviewed ADR-010's already-applied domain-model updates rather than re-deriving them (the ADR's own system-architect pass wrote them directly into this file — see the entry immediately below). Independently re-verified all 15 scenarios across `out-of-control-signal-event.feature` (9) and `drift-signal-log-handler.feature` (6) bind against the model as written, by reading the actual scenario text rather than taking ADR-010's bindability table on trust — no discrepancy found. Made the three judgement calls the pipeline named as this pass's to decide explicitly: confirmed `DeliveryFailure` is correctly a public Value Object Inventory entry, not an implementation detail (public field, value equality, immutability, no disqualifying trait `MonitoringResult` itself doesn't also have); checked (not assumed) that `fitted_artefact` referenced from every retained `MonitoringResult` creates no reference cycle — traced the actual object graph, confirmed it is a DAG with the artefact as a shared, inert, back-reference-free leaf, and that the marginal memory cost is one pointer per history entry, not a duplicated artefact, so it does not compound ADR-009 §7's already-accepted unbounded-history-growth risk; confirmed `direction: str | None` should stay a semi-open plain `str` (matching `chart_type`/`calibration_method`/`FittedCUSUM.direction`'s own precedent, no `Literal` anywhere in this codebase's Fitted Artefact Protocol) rather than a closed discriminator, and added an explicit caveat to the `direction` field's Notes that only two of `FittedCUSUM.direction`'s three vocabulary words (`"upper"`/`"lower"`) are ever legal outcomes on `MonitoringResult.direction` — `"two_sided"` never is, even when the underlying artefact is configured that way — flagging a risk that `direction=artefact.direction` could leak the wrong value onto a CUSUM signal if implemented carelessly. See "Domain-modeller verification, this pass" under the Value Object Inventory for the full reasoning on all three. No field, type, or scenario binding changed from ADR-010's design.
- 2026-09-11 (system-architect, combined BIN-75 + BIN-76 pass, ADR-010): Extended `MonitoringResult` with `direction: str | None`, `fitted_artefact: FittedControlLimits`, and `delivery_failures: tuple[DeliveryFailure, ...]` — additive, no field removed or renamed (settles BIN-75 Assumption A1: extend, not a second type). Added a new value object, `DeliveryFailure` (`receiver`, `error_type`, `error_message`). Added `Monitor`'s new `receivers: Sequence[SignalReceiver] = ()` constructor parameter and the `SignalReceiver` type alias (`Callable[[MonitoringResult], None]`, no `Protocol`) — settles BIN-75 OQ-2 (where an engineer arranges to be told). Documented `Monitor.record()`'s new delivery step: synchronous, after the chart-specific check, only on a genuine signal (settles BIN-75 Assumption A2 and OQ-3), absorbing any receiver exception into `delivery_failures` rather than raising or discarding it (settles BIN-75/BIN-76's shared OQ-1 "WHERE" sub-question — the WHAT, "absorb, but surface", was already product-owner-ratified before this pass). Added `caliper.monitoring.log_receiver`, R1's one built-in receiver, logging to `"caliper.monitoring"` at `WARNING` (settles BIN-76 OQ-2, OQ-3 — both grounded in scenario requirements, not stylistic choices: `WARNING` is required for BIN-76 SC4's zero-config visibility guarantee against Python's `logging.lastResort` default). Verified all 15 scenarios across `out-of-control-signal-event.feature` (9) and `drift-signal-log-handler.feature` (6) bind against this model exactly as written, with no `.feature` file changes required. Added five Glossary entries (Signal receiver, `SignalReceiver`, `log_receiver`, Delivery failure, `DeliveryFailure`) and updated the Signal entry to reflect that R1 delivery is now modelled. Re-confirmed the Domain Event Catalogue remains empty for R1, with explicit reasoning for why ADR-010 — the natural point to introduce an event — did not. Updated Library Operations (Create monitor, Record Phase II observation, two new rows for delivery and the log receiver) and Open Questions (three new settled entries, 15–19, continuing the numbering from ADR-009's pass).
- 2026-09-11 (domain-modeller, combined BIN-69 + BIN-72 pass, following ADR-009): Added full field-level Object Map treatment for `Monitor` (invariants, structure, operations table, constructor-validation decision, and a design note distinguishing it from a DDD aggregate — same discipline already applied to `Baseline`). Added a Value Object Inventory entry for `MonitoringResult` (structure, construction, and the `__bool__` decision ADR-009 §4 explicitly delegated to this pass — raises `TypeError`, with reasoning that engages both options rather than inheriting the ADR's recommendation unexamined). Added five Ubiquitous Language Glossary entries (Monitor, Monitoring result, Monitoring history, Accumulator, Session) and updated three existing ones (Signal, Phase II, Observation) to reflect that Phase II monitoring is now modelled, not merely anticipated. Confirmed the Monitoring context introduces no domain events, for the same reason as Measurement and Baseline (E4 unspecified). Updated the four Monitoring rows in Library Operations from "architecture settled, not yet implemented" to "domain-modelled, ready for backend-test-writer". Added three new Open Questions (12: accumulator-reset-after-signal, deliberately left open, tracked as `BIN-113`; 13 and 14: constructor validation and `__bool__`, both settled this pass). Verified all 18 scenarios across both feature files (`phase-ii-observation-signal-check.feature`, `in-memory-observation-store.feature`) bind against this model exactly as written, with no `.feature` file changes required — matching ADR-009's own scenario-by-scenario verification.
- 2026-09-11 (ADR-009, combined BIN-69 + BIN-72 architecture pass): Added the **Monitoring** bounded context (E3), depending on Baseline and Measurement. Introduced `Monitor` and `MonitoringResult` at the architecture level (full field-level domain-modeller treatment still to come). Settled BIN-69's OQ-1 (operation lives on `Monitor`), A1 (accumulator state lives privately on `Monitor`, keyed to the artefact), A2 (provenance checked internally via `compare_provenance()`), OQ-2 (`MonitoringResult` with explicit `is_in_control: bool`), OQ-3/**BIN-112** (strict inequality at control limits/decision interval — a boundary point is in control, uniformly across EWMA/CUSUM/Shewhart, corroborated against Montgomery/Lucas & Saccucci/Siegmund via secondary sources, primary text verification still pending for BIN-84), and OQ-4 (reuses `InvalidObservationError`, no new category). Settled BIN-72's A1 (no store port in R1, concrete-only), A2 (zero-config default, `retain_history=False` opt-out), OQ-1 (`Monitor.history` is a plain `tuple[MonitoringResult, ...]`, not a bespoke collection type — deliberately resolves the "second `Baseline`" discoverability risk BIN-72's review flagged), and OQ-2 (no automatic eviction/bounding mechanism in R1, but a manual `clear_history()` escape hatch ships and the unbounded-growth risk is documented as an accepted R1 risk, not left open indefinitely). Updated Library Operations and the Error Contract Reference's raised-by column accordingly. No `.feature` file required any change — both were written mechanism-neutrally and bind against this design as verified scenario-by-scenario in each story's `architecture.md`.
- 2026-09-10 (BIN-100 refresh): Reconciled against ADR-006 (scoring API surface and judge provider port), ADR-007 (two type checkers), ADR-008 (error assertions over message text), and the merged, tested E1 implementation in `src/caliper/measurement/`. Settled OQ-1 (criteria attachment), OQ-5 (score range), OQ-6 (scoring input shape), OQ-10 (empty agent output) — each marked SETTLED with ADR section and resolution, not deleted. Corrected the `Result[...]`-returning VO factories (VOs raise `InvalidParameterError` directly; explained why the `returns`-standard's own "single-failure-point" exception applies here, not a misapplication of house style). Rewrote the `Judge` section for `provider`/`criteria`/`score()`. Added `JudgeProviderPort` and `JudgeProviderResponse` as a real hexagonal port and its response VO. Documented BIN-103's module layout (`measurement/domain/`, `measurement/ports/`, top-level `errors.py`). Recorded BIN-104's known gap (wrong-typed constructor args bypass the value-object boundary). Corrected immutability-violation exception type (`pydantic_core.ValidationError`, not `FrozenInstanceError`/`AttributeError`) per the BIN-103 dataclass→Pydantic migration. Reconciled the vault copy (`Projects/caliper/domain-model.md`), which had drifted into a lossier condensation of this file, into a pointer — this file is now the single canonical copy. Left untouched, as instructed: OQ-2/3/4/7/8/9/11 (still open at the time of this entry), all numerical constants (still unpinned), the dual-spread finding (still prominent), and the absence of domain events (E4 still unspecified).
- 2026-09-10 (BIN-100 gate): OQ-9 settled by the product owner — a changed judge requires a refit; `compare_provenance()` gains no acknowledgement or force parameter. See "Provenance change requires a refit". The cost this imposes (ADR-005's 100-observation minimum, reset in full) is recorded rather than soft-pedalled, and making the refit *easier* stays open — BIN-105 (refit by re-scoring retained outputs) and BIN-106 (paired judge-difference report). **All eleven original open questions now have an owner and a disposition.**
- 2026-09-09 (amendment): Sigma estimator correction — `sigma_estimate` (MR-based) and `sigma_estimation_method` moved from Shewhart chart-specific to the shared core. Standard SPC practice uses MR/d_2 for ALL chart types on individual observations, not just Shewhart. ADR-005's inference that "EWMA and CUSUM use the sample standard deviation" was incorrect. FittedCUSUM and FittedShewhart chart-specific sigma fields removed (now shared). Dual-spread section reframed from "Shewhart-specific" to "all artefacts." ADR-004 shared core affected — flagged for system-architect amendment. Amendment 2 (CUSUM duplication invariant) rendered moot — the fields now hold genuinely different quantities.
- 2026-09-09: Initial model — BIN-100
