---
created: 2026-09-09
updated: 2026-09-24
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

**Stories:** BIN-63 (collection), BIN-64 (sufficiency), BIN-65 (EWMA fitting), BIN-66 (review), BIN-68 (provenance comparison), BIN-94 (CUSUM fitting), BIN-95 (Shewhart fitting), BIN-133 (Bernoulli CUSUM fitting for binary pass/fail rubrics — domain-modelled per ADR-012/013/014 and both ADR-014 amendments; **not on `trunk`**. The original ADR-014 plus Amendment 1 are built on unmerged PR #29, whose re-review found six blockers; Amendment 2 is built nowhere. See "BIN-133 implementation status" under `FittedBernoulliCUSUM` below).

**Boundary:** begins where a `ScoringResult` enters the baseline; ends at the fitted artefact and Phase II provenance comparison. The Baseline context depends on Measurement's `ScoringResult` and `Provenance` value objects. **Since BIN-133 (ADR-014), not every fitted artefact in this context satisfies `FittedControlLimits`** — `FittedBernoulliCUSUM` satisfies only the narrower `HasProvenance` protocol (see "Fitted Artefact Protocol" below). The context boundary is otherwise unchanged: a binary-rubric baseline is still a `Baseline` of `ScoringResult`s, inferred as binary at fit time (ADR-014 Decision 1), not a new collection type.

### Monitoring (extended, ADR-009 + ADR-010)

**Responsible for:** recording Phase II observations against a fitted control-limit artefact, checking each one for an out-of-control signal (chart-type-specific: recursive for EWMA/CUSUM, memoryless for Shewhart), making a session's recording history reviewable in-memory, and — as of ADR-010 — delivering a signal's full content to zero or more engineer-supplied receivers, absorbing but surfacing any receiver failure.

**Stories:** BIN-69 (record and check), BIN-72 (in-memory history), BIN-75 (signal content + delivery mechanism), BIN-76 (built-in log receiver).

**Boundary:** begins where a `ScoringResult` and a `FittedControlLimits` artefact meet at Phase II; ends at the `MonitoringResult` returned per call (now carrying direction, the fitted artefact, and any delivery failures — ADR-010), the in-memory `history` of those results, and delivery to any configured `SignalReceiver`s. Depends on both Measurement (`ScoringResult`, `Provenance`) and Baseline (`FittedControlLimits`, `compare_provenance()`).

**Established by ADR-009** (`docs/architecture/adr/009-phase-ii-monitor-and-observation-store.md`), settling BIN-69's OQ-1/A1/A2/OQ-3/OQ-4 and BIN-72's A1/A2/OQ-1/OQ-2 together. **Extended by ADR-010** (`docs/architecture/adr/010-signal-delivery-and-absorb-but-surface.md`), settling BIN-75's A1/A2/OQ-1(where)/OQ-2/OQ-3 and BIN-76's OQ-1(shared)/OQ-2/OQ-3 together, for the same reason: both stories' requirements reviews found them to be one coupled decision (BIN-76 consumes what BIN-75 defines), not two.

**Central type:** `Monitor(fitted_artefact, *, retain_history=True, receivers=())` — a new domain type, not a service. Holds the fitted artefact reference, private chart-specific accumulator state (nothing for Shewhart — memoryless by design; the smoothed statistic for EWMA; the two running one-sided sums for CUSUM), and — as of ADR-010 — a sequence of `SignalReceiver` callables supplied at construction. `Monitor.record(observation: ScoringResult) -> MonitoringResult` checks provenance internally (reusing BIN-68's `compare_provenance()`, unmodified), raises `ProvenanceMismatchError`/`InvalidObservationError` (the latter reused from Baseline's taxonomy, no new category) for the two precondition violations, and otherwise never raises — an out-of-control determination is a normal return value (`MonitoringResult.is_in_control: bool`, an explicit field per BIN-110's truthiness rule, never a `__bool__`). On a genuine signal (`is_in_control is False`), `record()` synchronously invokes every configured receiver with the result, absorbing any exception a receiver raises into `MonitoringResult.delivery_failures` rather than letting it propagate or discarding it (ADR-010 §§1, 4 — "absorb, but surface", ratified by the product owner 2026-09-11). `Monitor.history` is a plain `tuple[MonitoringResult, ...]` (deliberately not a bespoke collection type — see ADR-009 §6, resolving the "second `Baseline`" discoverability risk BIN-72's review flagged), retained automatically unless `retain_history=False`; `Monitor.clear_history()` is the manual escape hatch for the accepted, documented unbounded-growth risk in a long-running process (ADR-009 §7). No store `Protocol`/port exists in R1 (ADR-009 §8) — the public surface is designed so BIN-73 can add one additively; the receiver surface follows the same discipline (ADR-010 §3) — no `Protocol`/base class for a receiver, a plain `Sequence[SignalReceiver]` instead, chosen specifically so BIN-80 (fan-out, R2) and BIN-81 (formal handler interface, R2) can build on it additively rather than requiring a breaking rewrite.

**Boundary convention (ADR-009 §5, resolving BIN-69 OQ-3 / BIN-112):** every comparison is strict — a point exactly at a control limit, or a CUSUM statistic exactly equal to the decision interval, is in control, not out of control. Verified against convergent secondary corroboration of all three primary sources (Montgomery, Lucas & Saccucci 1990, Siegmund 1985 via NIST's restatement); primary texts remain paywalled and this must be re-checked against their actual page text before `BIN-84`'s property-based tests treat it as permanently settled.

**Extended for BIN-133 (ADR-014; on unmerged PR #29, which accumulates in floats and so needs Amendment 2's integer stepping, not yet built):** `Monitor` must also accept a `FittedBernoulliCUSUM` — an artefact that does not satisfy `FittedControlLimits` (it satisfies only `HasProvenance`), so `Monitor.__init__`'s accepted-type signature widens rather than narrows further. `record()` gains a third precondition ahead of the chart-specific dispatch — a Phase II observation checked against a `FittedBernoulliCUSUM` must be exactly `0.0` or `1.0`, or `InvalidObservationError` (`context["reason"] == "score_not_binary"`) is raised, reusing the existing category rather than adding a tenth — and a fourth `_check` branch, `_check_bernoulli_cusum`. **ADR-014 Amendment 2 (Decision 14) also requires that branch to step each arm's integer lattice in integer units, re-validating the caller-supplied lattices first.** It must not accumulate floats. Full detail in the Object Map's `Monitor` entry below.

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

3. **Accumulator state is private, chart-specific, and belongs to exactly one `Monitor` instance.** Nothing for Shewhart (memoryless by design — BR-4); the EWMA smoothed statistic; CUSUM's two one-sided running sums (`S_hi`, `S_lo`); for the Bernoulli CUSUM, two **integer** per-arm statistics in lattice units (invariant 10). State is never read from or written to the fitted artefact (the artefact remains immutable per ADR-004/BIN-108) and is never shared between two `Monitor` instances, even two constructed from the same artefact — each holds an entirely independent accumulator, initialised fresh at construction (ADR-009 §1, resolving BIN-69's A1 feasibility risk and SC5's "first observation needs no prior history").

4. **A genuine signal is never raised.** An out-of-control determination is a normal, successful return value (`MonitoringResult.is_in_control = False`), never an exception (BR-7, ratified project-wide — "signals are not errors"). Only the two precondition violations above are exceptional.

5. **History is append-only and insertion-ordered.** Every successfully recorded `MonitoringResult` — one that did not raise — is appended to history in the order `record()` was called; a refused attempt never appears, by construction (invariants 1 and 2 both gate before any append happens — there is no separate "don't record refused attempts" check to forget).

6. **Strict-inequality boundary convention, uniform across chart types.** A point exactly at a control limit (EWMA/Shewhart) or exactly at the decision interval (CUSUM) is in control, not out (ADR-009 §5). One convention, not three independently-chosen ones.

7. **Delivery is attempted only for a genuine signal, and never lets an exception escape `record()`.** *(New, ADR-010 §4.)* Every configured receiver is invoked, in order, with the result, only when `is_in_control is False`. A receiver that raises does not stop the next receiver from being attempted, and never propagates out of `record()` — "absorb, but surface" (ratified by the product owner, 2026-09-11): the failure is captured into `MonitoringResult.delivery_failures`, not raised and not silently discarded.

8. **A `Monitor`'s receivers are fixed at construction.** *(New, ADR-010 §3.)* No method adds or removes a receiver after `Monitor.__init__` returns — R1 needs exactly this, and it keeps `record()`'s delivery step free of any mutable-configuration-during-iteration hazard.

9. **A Phase II observation against a `FittedBernoulliCUSUM` must be exactly `0.0` or `1.0`.** *(BIN-133, ADR-014 Decision 2. Built on unmerged PR #29; not on `trunk`.)* Checked as a third precondition, after provenance comparison and before the chart-specific dispatch (`_check`). A continuous-valued score — even a legal, finite, in-range one for every other chart — is rejected with `InvalidObservationError` (`context["reason"] == "score_not_binary"`, `context["missing_fields"] == ()` — nothing is missing; the value present is simply outside the domain this chart can interpret). No tolerance band: an epsilon around `{0.0, 1.0}` would itself be an invented, uncited constant, and a continuous score reaching a binary-fitted `Monitor` more plausibly indicates the wrong chart was called than floating-point noise. This precondition applies only when `self._artefact` is a `FittedBernoulliCUSUM` — the three continuous chart types are unaffected.

10. **A `Monitor` over a `FittedBernoulliCUSUM` runs exactly the integer chain whose ARLs the artefact reports.** *(ADR-014 Amendment 2, Decision 14.4–14.5. **Not built.** PR #29 accumulates `max(0, S + x − r)` in binary floating point from the derived float fields. The ADR measured that path signalling earlier than the exact chain: 211 of 400 in-control runs at m=300 f=3, never later. That is defect 3.)*
    - **The artefact's lattices are the only input.** The accumulators read `artefact.lattice_lower` and `artefact.lattice_upper` (`BernoulliArmLattice`, below) and never the derived float fields. Each arm's statistic is an `int` in units of `1/denominator`, initialised to `0`.
    - **Transitions** (with `N`, `r`, `h` being that arm's `denominator`, `reference_units` and `decision_interval_units`):
      - on a failure (`score == 0.0`): `s_lo += N_lo − r_lo`; `s_up = max(0, s_up − r_up)`;
      - on a success (`score == 1.0`): `s_lo = max(0, s_lo − r_lo)`; `s_up += N_up − r_up`.

      This is exactly the transition structure the solver inverts, so the reported ARLs belong to the chart `Monitor` runs.
    - **Signal** on `s_lo > h_lo` or `s_up > h_up`, strictly, gated by `direction` (invariant 6, ADR-009 §5 / BIN-112). A statistic sitting exactly on `h` is in control.
    - **Lattices are re-validated at use** (Decision 14.5). The artefact is caller-supplied, and `model_copy(update=...)`/`model_construct()` skip validation. So before stepping, each lattice integer must be an exact `int` (not a `bool`, not a subclass) and inside `BernoulliArmLattice`'s bounds. A violation raises `InvalidParameterError` (row M2 in the Error Contract Reference: `parameter="artefact"`, `constraint`, `kind="invalid"`, `field`, e.g. `"lattice_upper.reference_units"`, and, per C6, `provided_type` for a non-exact `int` or `provided` for an exact `int` out of bounds). The placement and the reasoning are the same as the existing `require_exact_str` on `direction` (BIN-143, row M3).
    - **Only checked arms exist** (corrigendum C3). A fitted artefact carries `lattice_X` exactly when its `direction` checks arm X, so `Monitor` accumulates only the checked arms. The former "both sums always updated regardless of `direction`" convention does not apply to this chart.
    - **A caller-supplied artefact whose `direction` checks an arm with no lattice** (corrigendum C4, settling OQ-30) raises `InvalidParameterError` in `record()` **before any state changes**, beside the integer checks. The keys are `parameter="artefact"`, `constraint` (e.g. `"must be a BernoulliArmLattice when direction checks this arm"`), `kind="invalid"`, `field="lattice_upper"` or `"lattice_lower"`, and `provided_type="NoneType"`. It must never leak `AttributeError`/`TypeError` (BIN-121).

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `artefact` (private) | `FittedControlLimits \| FittedBernoulliCUSUM` | *(Type widened for BIN-133, ADR-014 §6a. Built on unmerged PR #29.)* The fitted artefact this monitor was constructed from — referenced, never copied or mutated. `FittedBernoulliCUSUM` does not satisfy `FittedControlLimits` (it satisfies only `HasProvenance`), so the accepted-type union grows explicitly rather than the protocol being loosened to fit it — ADR-004 section 3's rejection of a shared/polymorphic detection boundary is not reopened |
| accumulator (private, chart-specific) | implementation detail, not public | Nothing for Shewhart; EWMA's smoothed statistic; CUSUM's `(S_hi, S_lo)` pair; the Bernoulli CUSUM's two `int` lattice-unit statistics (invariant 10; only the lower one when `lattice_upper is None`). Not part of the public surface (ADR-009 §1) |
| `retain_history` (constructor parameter) | `bool` | Default `True`. `False` opts this monitor out of retaining any history at all (ADR-009 §7) |
| `receivers` (constructor parameter) | `Sequence[SignalReceiver]` | Default `()` — no receivers configured. `SignalReceiver = Callable[[MonitoringResult], None]`, a plain type alias, not a `Protocol` (ADR-010 §3). Fixed for the `Monitor`'s lifetime — no add/remove method in R1 |
| history (private backing store) | implementation detail, not public — a `list[MonitoringResult]` is the obvious choice, per ADR-009's own "What domain-modeller still owns" | Append-only; exposed publicly only via `.history`, which returns a fresh `tuple` view — never the backing store itself |

**Operations on Monitor:**

| Operation | Input | Output | Errors |
|-----------|-------|--------|--------|
| `Monitor(artefact, retain_history=True, receivers=())` | `FittedControlLimits`, optional `retain_history: bool`, optional `receivers: Sequence[SignalReceiver]` | `Monitor` | See "Constructor validation" below |
| `record(observation)` | `ScoringResult` | `MonitoringResult` (now carrying `direction`, `fitted_artefact`, `delivery_failures` — ADR-010) | `ProvenanceMismatchError`, `InvalidObservationError` (incomplete `ScoringResult`; or, for BIN-133 under ADR-014 Decision 2, a non-binary score checked against a `FittedBernoulliCUSUM`: `context["reason"] == "score_not_binary"`, row M1, built on PR #29). `InvalidParameterError` for a caller-supplied `FittedBernoulliCUSUM` whose lattice integers are not exact or are out of bounds (row M2, ADR-014 Decision 14.5, not built) or whose `direction` is not an exact `str` (row M3, BIN-143). Never raises for a delivery failure — absorbed into the returned result (ADR-010) |
| `history` (property) | — | `tuple[MonitoringResult, ...]` | — |
| `clear_history()` | — | `None` | — |

🚨 **Constructor validation — SUPERSEDED 2026-09-12, corrected here 2026-09-14; widened here 2026-09-23 (the widening is built on unmerged PR #29).**

**`Monitor.__init__` narrows to the concrete types it knows how to check** — `FittedEWMA`/`FittedCUSUM`/`FittedShewhart` today, plus `FittedBernoulliCUSUM` once BIN-133 lands (ADR-014 §6a) — **not** a structural `isinstance(artefact, FittedControlLimits)` check. `FittedBernoulliCUSUM` does not itself satisfy `FittedControlLimits` (see "Fitted Artefact Protocol" below), so this is a genuine widening of the accepted-type tuple, not a narrowing to a stricter protocol — the check remains "is this one of the concrete types `_check` can dispatch on", now four instead of three.

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

**Since BIN-133 (ADR-014 §6a; not on `trunk`), each concrete artefact has one further chart-specific shape decision worth naming here: `FittedBernoulliCUSUM` reports two decision intervals (`decision_interval_lower`, `decision_interval_upper`, one per arm), not one — a direct consequence of the two-sided-by-default design (ADR-012 amendment) combined with the shared-core protocol's continued exclusion of detection boundaries. This is additive to, not a revision of, the reasoning above.** *Amendment 2 (Decision 14) refines it without changing the reasoning. The authoritative boundary is each arm's integer `BernoulliArmLattice`, and the two float intervals are derived from it. At f = 0 a two-sided request produces a lower-arm-only chart, whose upper interval is `None` (Decision 19.2).*

### `HasProvenance` — the narrower protocol a non-conforming artefact can still satisfy

*(ADR-004's 2026-09-12 amendment; documented here for the first time under BIN-133, because `FittedBernoulliCUSUM` is the first concrete artefact that needs it. `HasProvenance` itself is on `trunk` (BIN-135). Its first non-conforming user, `FittedBernoulliCUSUM`, is only on unmerged PR #29.)*

```python
@runtime_checkable
class HasProvenance(Protocol):
    """Two-attribute provenance contract for compare_provenance."""

    @property
    def provenance_model_version(self) -> str: ...

    @property
    def provenance_criteria(self) -> str: ...
```

`compare_provenance()` (BIN-68) only ever reads these two attributes — it does not need the full twelve-attribute `FittedControlLimits` surface. `HasProvenance` exists so a third-party or chart-specific artefact that cannot honestly satisfy the full reporting contract (because it has no sigma-based quantity, no `baseline_mean`, etc.) can still participate in provenance comparison, which is the one piece of shared machinery every fitted artefact — conformer or not — genuinely needs. `FittedEWMA`/`FittedCUSUM`/`FittedShewhart` satisfy `HasProvenance` incidentally, as a strict subset of `FittedControlLimits`; `FittedBernoulliCUSUM` (below) satisfies `HasProvenance` **and nothing more** — this is the distinction ADR-014 §6a's decision turns on.

🚨 **`FittedControlLimits`'s own protocol docstring — "the OPERATIONAL sigma used by ALL chart types" — is no longer accurate the moment `FittedBernoulliCUSUM` ships**, and this is a deliberately accepted, narrow precedent break (ADR-014 §6a), not an oversight. Forcing conformance by populating a mechanically-computable-but-operationally-unused `sigma_estimate` on `FittedBernoulliCUSUM` was considered and rejected — it would make the protocol's own documented contract false while misleading a reader into thinking the figure does something. A future ADR-004 amendment could formalise the narrowing ("used by all *continuous* chart types") explicitly; not done here, per ADR-014.

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

#### FittedBernoulliCUSUM

*(BIN-133, following ADR-012/013/014, ADR-014 Amendment 1 (Decisions 7–11, 2026-09-23) ADR-014 Amendment 2 (Decisions 12–19, ratified 2026-09-24) and the **Amendment 2 corrigendum (C1–C11, ratified 2026-09-24)**. **Not on `trunk`.** For what is built where, see "BIN-133 implementation status" at the end of this entry.)*

🚨 **Does not satisfy `FittedControlLimits`.** It is the first fitted artefact type that does not (ADR-014 Decision 6a). Its statistic accumulates the raw pass/fail value directly against a probability-space reference value, which is derived from a log-likelihood ratio over each arm's own design pair. No sigma estimate enters its calibration anywhere. It satisfies `HasProvenance` (above) and is otherwise its own type, reporting its own, honestly-scoped field set.

**Each arm is designed on the side that is conservative for the shift it detects** (Decision 19.1, superseding Decision 6d):

| arm | detects | designed at | `r` derived from | calibrated at |
|---|---|---|---|---|
| lower | a rise in failure rate (degradation) | `p_U`, the Clopper–Pearson **upper** bound, α = 0.10 (ADR-013, unchanged) | `(p_U, M·p_U)` on the failure indicator | `p_U` |
| upper | a fall in failure rate (improvement) | **`p_L`, the Clopper–Pearson lower bound, α = 0.10** | `(1 − p_L, 1 − p_L/M)` on the success indicator | `1 − p_L` (success rate) |

The upper arm's statistic signals on successes, so its ARL₀ **falls** as the true failure rate falls. Designing it at `p_U`, as shipped, calibrated it at the rate where it alarms least. Decision 19.0 measured that design breaching ADR-013 §3's ≤5% appetite by up to 20 times. Decision 19.1 derives the mirrored GICP guarantee for `p_L` by a coupling argument. Heidema et al. (2026) is **not** cited for the decrease direction. Decision 19.3 then verifies the guarantee on 55 cells, p₀ ∈ [0.002, 0.30] and m ∈ [100, 1000], by two independent methods. The worst appetite measured is 1.727% exact and 2.32% on the Monte Carlo upper bound.

| Field | Type | Notes |
|-------|------|-------|
| `chart_type` | `str` | `"bernoulli_cusum"` |
| `observed_failure_rate` | `float` | `p̂ = f / m`. The one summary statistic ADR-012/013's vocabulary uses throughout, and the one Story 1's scenario names directly ("reports the observed failure rate"). There is no separate `baseline_mean`; reporting the complement too would be redundant |
| `observation_count` | `int` | m |
| `provenance_model_version` | `str` | `HasProvenance` |
| `provenance_criteria` | `str` | `HasProvenance` |
| `requested_arl` | `float` | The engineer's requested false-alarm ARL₀ |
| `achieved_arl` | `float` | The exact in-control ARL of the constructed integer chart, on the lattices below (Decision 13.1). **Its meaning depends on which arms are checked:** <br>• **`"lower"`**: the lower arm's exact one-sided ARL₀ at `p_U`. <br>• **`"upper"`**: the upper arm's exact one-sided ARL₀ at `p_L`, that is, at success rate `1 − p_L`. <br>• **`"two_sided"`**: **`B`, the guaranteed floor** (Decision 19.4). `B` is the exact expected run length of the *coupled three-outcome chain*: one uniform per step, which counts as a failure for both arms when `U < p_L`, as a failure for the lower arm and a success for the upper when `p_L ≤ U < p_U`, and as a success for both when `U ≥ p_U`. It is solved exactly on the Decision 8 joint state space. See "What the two-sided `achieved_arl` guarantees" below. <br>In every successful fit, **`achieved_arl ≥ requested_arl`**. One-sided, this follows from Decision 12.1: the search returns the smallest `h` meeting the target, and ARL₀ is non-decreasing in `h`. Two-sided, it follows from calibration D's `B ≥ T` (Decision 19.4 / Decision 18 item 16). The gap can be large when the lower arm is at its floor (Decision 12) |
| `expected_detection_arl` | `float` | ADR-013 §4's detection-performance disclosure, **amended by Decision 15**. It is the exact ARL₁ of the constructed chart, evaluated at **the shift the checked arm(s) are tuned to detect**. It is unconditional and first-class, not routed through `FittingAdvisory` (Decision 4, which stands). <br>• `"lower"`: the lower arm at failure rate `p̂ × M`, or `p_U × M` when f = 0. That includes a `"lower"` produced by a two-sided request at f = 0. <br>• `"two_sided"` (f ≥ 1 only): the ordinary joint chain at the single rate `p̂ × M`. <br>• `"upper"` (f ≥ 1 only): the upper arm at failure rate **`p̂ / M`**, the improvement it is tuned for. It is **not** `p̂ × M`: the shipped code evaluated the upper-only chart at a degradation it is built never to signal on. At m=150 f=40 that reported 357,451.6. The tuned figure, with the upper arm at `p_L`, is 72.1128 (corrigendum C1). Amendment 2's 32.8 was computed with the upper arm at `p_U` and is withdrawn. <br>Decision 15's `p_U / M` fallback for `"upper"` at f = 0 is **withdrawn** (Decision 19.2): `"upper"` refuses at f = 0 (row F15), so the fallback is unreachable. So is the `"two_sided"` row's f = 0 fallback (corrigendum C8), because a two-sided request at f = 0 becomes `"lower"` and takes the `"lower"` row |
| `expected_improvement_detection_arl` | `float \| None` | *(New, Decision 19.6.)* **Non-`None` exactly when the chart checks both arms**, i.e. `direction == "two_sided"`, which implies f ≥ 1. It is the exact ARL of the two-sided joint chain (Decision 8 state space, Decision 13 integer lattices, calibration D's intervals) at the single true failure rate **`p̂ / M`**: the improvement the upper arm is tuned to detect. It mirrors `expected_detection_arl`'s `p̂ · M`. It is a number, not a warning: there is no threshold and no advisory tied to it. `None` for `"lower"`, whether requested or forced by f = 0, because no upper arm is checked. `None` for `"upper"`, because `expected_detection_arl` already *is* the improvement figure there, and carrying it twice would give two fields one meaning. **`p̂ = 0` never reaches it, so no fallback exists or is needed.** It can exceed `achieved_arl`. At m=1000 f=5 it is 580.9 against `B` = 370.3: the chart signals no sooner at the design improvement than it would false-alarm (see "Improvement-detection power" below) |
| `calibration_method` | `str` | *(Corrigendum C5.)* **`"gicp_markov_chain"`** for one-sided fits (`"lower"`/`"upper"`): exact, at the checked arm's own conservative bound. **`"gicp_markov_chain_coupled_bound"`** for `"two_sided"`: `achieved_arl` is the coupled floor `B` under calibration D. The string differs so that an auditor can tell a post-Amendment-2 two-sided figure from a pre-Amendment-2 one. **§6c's `"gicp_markov_chain_harmonic_combination"` fallback is withdrawn:** no approximate path may ship |
| `advisories` | `tuple[FittingAdvisory, ...]` | Defaults to `()`. **Two producers now exist for this chart** (Decisions 12 and 19.2). `FittingAdvisory` is the existing `kind`/`description`/`boundary: float` type (`fitting_advisory.py`); `description` is prose and not part of the contract. <br>• **`kind="lower_arm_signals_on_first_failure"`**, `boundary` = the exact one-sided lower-arm ARL₀ at `h_units = 1`, which equals `1/p_U`. It is present exactly when `direction` checks the lower arm (`"lower"` or `"two_sided"`) **and** `lattice_lower.decision_interval_units < lattice_lower.denominator − lattice_lower.reference_units`, which is an integer test. <br>• **`kind="upper_arm_not_designable"`**, `boundary=1.0`, the smallest baseline failure count at which the improvement arm can be designed. It is present exactly on a two-sided request against a zero-failure baseline (Decision 19.2). <br>The two can co-occur: an f = 0 two-sided request whose lower-only chart is floored, such as m=10,000 f=0 in 19.4's table. Forward-compatible with ADR-005's unbuilt middle-tier adequacy advisory (ADR-013 §2) |
| `detect_rate_multiple` | `float` | *M*, the shift lever: a multiple of the in-control failure rate rather than a sigma multiple (ADR-012 §1, a structural consequence of a Bernoulli process having one parameter). It moves the lower design point *up* (`M·p_U`) and the upper design point *down* (`p_L/M`). Default `2.0` (ADR-012 §1, extended ADR-013 §6a). **Legal range** (corrigendum C2, option A ratified): `M` must be finite (F7) and greater than a **per-fit computed lower bound** that is always `> 1` (F16). `M ≤ 1` is refused: `M = 1` detects no shift, and `M < 1` would mislabel the arms. Just above 1, the design outruns double precision: every baseline measured is constructible down to `M − 1 = 10⁻⁷`, and fails at `10⁻⁸`–`10⁻⁹`. The bound is the smallest verifiably constructible `M` and round-trips by construction. At the top, F11's `max_detect_rate_multiple` is unchanged |
| `alpha` | `float` | `0.10` (ADR-013 §3), fixed. It is the level of **both** one-sided bounds, `p_U` and `p_L` (Decision 19.1; not re-derived). Reported for auditability, **not settable** (ADR-014 Decision 5) |
| `p_u` | `float` | The one-sided Clopper–Pearson **upper** bound on the failure rate: the `1 − α` quantile of `Beta(f+1, m−f)`. The lower arm's design and calibration rate (ADR-013 §1) |
| `p_l` | `float` | *(New, Decision 19.1/19.5.)* The one-sided Clopper–Pearson **lower** bound on the failure rate: the `α` quantile of `Beta(f, m − f + 1)`. Closed form at f = 1: `1 − (1 − α)^(1/m)`. **`0.0` when f = 0** (19.2: "`p_L = 0`"). The upper arm's design and calibration rate. Reported beside `p_u` |
| `direction` | `str` | `"two_sided"` (default), `"lower"` or `"upper"`, the same vocabulary as `FittedCUSUM.direction`. It is **the chart that actually runs, not the request**. A two-sided request against a zero-failure baseline returns `"lower"` (Decision 19.2), avoiding Decision 6d's rejected "silently only checking the lower arm". Only outcomes, not this configuration field, are restricted to two of the three words (see `MonitoringResult.direction`) |
| `lattice_lower` | `BernoulliArmLattice \| None` | *(New, Decision 14.2; presence rule from corrigendum C3.)* **The stored, authoritative definition of the lower arm**: `(denominator, reference_units, decision_interval_units)` as exact integers. **Present exactly when `direction` checks the lower arm** (`"lower"` or `"two_sided"`), and `None` for `"upper"`. See the Value Object Inventory |
| `lattice_upper` | `BernoulliArmLattice \| None` | *(New, Decision 14.2; presence rule from corrigendum C3, replacing 19.5's "only when f = 0 forced lower".)* The same for the upper arm. **Present exactly when `direction` checks the upper arm** (`"upper"` or `"two_sided"`), and `None` for `"lower"`. That includes a `"lower"` produced from a two-sided request at f = 0, and a directly requested `"lower"` at any f |
| `reference_value_lower` | `float \| None` (computed) | *r* for the lower arm, `= lattice_lower.reference_units / lattice_lower.denominator`; `None` when `lattice_lower is None`. **A read-only `@computed_field`, not a stored field** (Decision 14.3). It keeps its meaning and still appears in `repr`, `model_dump` and `audit_summary()`. Unquantised design point `p₁ = M · p_U` |
| `decision_interval_lower` | `float \| None` (computed) | *h* for the lower arm, `= lattice_lower.decision_interval_units / lattice_lower.denominator`; `None` when `lattice_lower is None`. Computed, as above |
| `reference_value_upper` | `float \| None` (computed) | *r* for the upper arm, derived from `lattice_upper`; `None` when `lattice_upper is None`. Design pair `(1 − p_L, 1 − p_L/M)` on the success indicator (Decision 19.1). This was `p_U / M` before Amendment 2: superseded |
| `decision_interval_upper` | `float \| None` (computed) | *h* for the upper arm, derived from `lattice_upper`; `None` when `lattice_upper is None` |

**One source of truth.** The two lattices are the chart. The four float fields are derived from them and can never disagree with them (Decision 14.3). Two stored copies of one number is this project's recurring failure. **What goes in comes out:** `FittedBernoulliCUSUM.model_validate(chart.model_dump())` equals `chart`, drives `Monitor` identically, and each float equals `units / denominator` exactly (Decision 18 item 11). An engineer can fit in one process and monitor in another without losing the exact chart. That is why the integers are public fields, not `PrivateAttr` (Decision 14).

~~Both arms' lattices are present whatever the `direction`, whenever both arms are designable.~~ **SUPERSEDED 2026-09-24 by corrigendum C3 (ratified C-Q2), which reverses ADR-014 §6b.** **An artefact carries only the arms its `direction` checks.** `lattice_X is None` exactly when `direction` does not check arm X. A one-sided fit designs and calibrates **only** its checked arm; F12's `direction` key names that arm, and `Monitor` accumulates only the checked arms. The cost: an engineer can no longer read off what a direction change would produce without refitting. That was already not literally true, since two-sided and one-sided arms are calibrated differently. A refit is cheap and `direction` is frozen anyway. The benefit: the unchecked arm no longer costs fit time (4.4–6.0 s at large `T`). Its feared spurious F12 was shown unreachable anyway, since an f ≥ 1 upper arm has `ARL(h) ≥ h + 1`, giving `h ≤ T − 1 ≤ 999,999`.

No `target_value`, `sigma_estimate`, `sigma_estimation_method` or `baseline_spread` fields. They are deliberately absent (see `HasProvenance` above and the Dual-Spread narrowing note below): this chart has no raw-scale target or operational sigma to report.

> ~~**`p_U` substitutes for `p₀` in *both* arms' design-point formulas, consistently** (ADR-014 §6d). ⚠️ The upper arm's own false-alarm coverage under this substitution is unverified — flagged, not resolved.~~
>
> **SUPERSEDED 2026-09-24 by ADR-014 Decision 19.** The upper arm is designed and calibrated at `p_L`. Its coverage is derived (19.1) and measured (19.3). OQ-23 is settled. The struck paragraph is kept so the history of the design stays readable.

**What the two-sided `achieved_arl` guarantees, and what it does not** (Decision 19.4).

- **It guarantees** that `B ≤ true joint ARL₀(p)` for **every** true failure rate `p ∈ [p_L, p_U]`. This follows from 19.1's coupling: the lower arm's run length is non-increasing in `p`, and the upper arm's is non-decreasing in `p`. So `B` is a guaranteed floor, not a plug-in estimate, and it is exactly the conservative "false-alarm promise" `achieved_arl` exists to state (ADR-013 §4). Calibration D makes `B ≥ requested_arl`.
- **It does not guarantee** anything for a true rate outside `[p_L, p_U]`. Each bound is a one-sided Clopper–Pearson bound at α = 0.10, so the true rate can fall outside the interval.
  - How often the resulting chart still breaches the target is **measured, not derived**, on ADR-013 §3's criterion.
  - Under calibration D on 19.4's 55 cells, the worst appetite `P(true ARL₀ < T/2)` is 1.781%, against the ratified 5% bar. The worst `P(true ARL₀ < T)` is 7.88%.
  - An independent from-scratch implementation confirms the worst cell at 1.98% on its upper 95% bound.
- **It is not the expected spacing at the observed rate.**
  - At `p̂` the chart typically alarms much *less* often than `B` says: m=300 f=3 reports `B` = 370.4 against a true joint ARL₀ at `p̂` of 1,809.8.
  - This conservatism is the price ADR-013 §4 already accepts. It is the direction the ratified appetite permits, and `expected_detection_arl` discloses what it costs.
  - The pre-Amendment-2 figure did the opposite: it overstated the spacing at `p̂` by up to 2.6×.
- **It is not a single-rate ARL at all.** The two arms have different design rates, so no single rate evaluates the pair. It is also not the minimum over a grid of `p`, which is rejected in 19.4 as inexact between grid points. `B` is provably at or below that minimum.

**Calibration D, the two-sided calibration** (Decision 19.4, superseding the shipped equal split). The lower arm keeps its equal-split design: one-sided to `2T` at `p_U`. The upper arm's decision interval is the **smallest** `h_up` for which `B ≥ T`. The bisection is valid because `B` is non-decreasing in `h_up`, by the same coupling. The rejected alternative was ES: both arms one-sided to `2T`. It also passes the appetite, but it over-delivers (median `B/T` 1.01–1.27) and detects degradation 27–31% more slowly at `p₀ ≤ 0.005`. D never increased `h_up` over ES in any measured cell, so it costs no memory. A per-arm search-cap hit inside D's bisection routes to the joint-state refusal F13 (Decision 16, unchanged by 19.5).

**The zero-failure (f = 0) shape** (Decision 19.2). At f = 0, `p_L = 0`: the upper arm's in-control success rate would be exactly 1, there is no improvement left to detect, and its reference-value formula is undefined.
- **`direction="two_sided"` at f = 0 → fit the lower arm only, calibrated to the full `T` (not `2T`).** The artefact carries:
  - `direction="lower"`, `lattice_upper=None`, and `reference_value_upper` and `decision_interval_upper` both `None`;
  - `expected_improvement_detection_arl=None` and `p_l=0.0`;
  - `FittingAdvisory(kind="upper_arm_not_designable", boundary=1.0)`, plus the floor advisory if the lower arm is floored.

  `achieved_arl` equals that of a one-sided `"lower"` fit at `T`, and `calibration_method` is `"gicp_markov_chain"`, as for any `"lower"` fit (C5). A **directly requested** `"lower"` at f = 0 has the same shape **minus** the `upper_arm_not_designable` advisory: its upper arm is simply not checked (C3). It fits rather than refuses because the ratified default must not refuse the healthiest baselines (Decision 12's reasoning, same population). This changes the ratified field shape **only at f = 0** (Q10, accepted).
- **`direction="upper"` at f = 0 → refused** with `InvalidParameterError`, row F15: `reason="no_baseline_failures"`, and no round-trip key, since no value the engineer can pass would fix it.
- **Small f is valid, with a cost.** At f = 1, 2 the design is valid at every `m` measured, from 100 to 300,000 (19.2). The upper arm then has `reference_units = 1`: its statistic counts consecutive successes, and `h ≈ T`. `N_upper` reaches about 3.4 million at m=300,000 f=1, which is why Decision 13's integer-exact path is required.

**Improvement-detection power** (Decision 19.2, disclosed by 19.6, **deliberately not refused**). When `p̂·T ≪ 1`, the upper arm has essentially no power. Its ARL at its own target improvement is about equal to its in-control ARL₀, or higher: 398.1 against 370.1 at m=1000 f=1. That is a property of the process, not of this design. No refusal, drop rule or advisory is adopted, because any "too little power" threshold would be an invented number (ADR-013 §4's disclosure-over-floor ruling). The number is disclosed by `expected_detection_arl` for `"upper"` and by `expected_improvement_detection_arl` for `"two_sided"`. The power threshold is recorded as open by design, OQ-28.

**The lower arm's floor is `1/p_U`, and the chart fits and discloses rather than refusing** (Decision 12, **replacing the original Decision 3 item 2's computed-attainability-floor refusal**; see OQ-20's superseded note).
- **The floor is a property of the chart, not of the lattice.** For any `h < 1 − r`, a single failure lifts the lower statistic past `h`, so the run length is the waiting time to the first failure: geometric, mean exactly `1/p`.
  - This holds for any lower-arm Bernoulli CUSUM, on any lattice, and for the continuous-`r` chart too.
  - Measured equal to `1/p_U` to 1e-9 from m=100 to m=300,000, unchanged on lattices 2–16× finer.
- **It is a gap, not only a floor.** The next attainable value is about 2.8–3.3× the floor, and refining `N` moves it by a few percent. A target inside the gap gets the next value up. That is ADR-012 §3's "report, don't chase", with `achieved_arl` computed exactly beside `requested_arl`.
- **Refusal would have been wrong here**, though it is right for the continuous CUSUM (BIN-117):
  - it has no lever: the floor depends on neither `M`, `N` nor `direction`;
  - its only recovery rebuilds the identical chart;
  - combined with the 1,000,000 joint-state cap, it would have left every f = 0 baseline of m ≥ 5,000 unfittable two-sided at **any** target.
- **The disclosure** is `FittingAdvisory(kind="lower_arm_signals_on_first_failure", boundary=<1/p_U, exactly>)`, under the integer condition in the `advisories` row. `boundary` is the smallest in-control ARL₀ any lower-arm Bernoulli CUSUM can have on this baseline. It tells the engineer that no parameter they control changes it.

**Integer lattices end to end — the chart is the integers** (Decision 13, completing Amendment 1's Decision 8).
- **One-sided and joint solvers take `(N, r_units, h_units)` for each arm directly.** Nothing is rebuilt from floats.
  - `limit_denominator`, `_lattice_denominator` and `_DENOMINATOR_RECONSTRUCTION_CAP` are removed from production code. Decision 18 item 7 pins that structurally.
  - The float rebuild was defect 2. At m=200,000 f=0 it turned a 1,474-state problem into a 16.5-million-state one, bypassing the 1M cap check. `two_sided` then segfaulted in SuperLU, and `upper` reported the ill-conditioning sentinel `1e15` as its ARL.
- **No bound on baseline size, and no bound on `N`.** Every legal f = 0 configuration up to m = 3,000,000 fits one-sided at `MAX_MEANINGFUL_ARL` and two-sided at 370. A bound on `m` would refuse the healthiest agents precisely because they are healthy.
- **Postcondition, raising** (Decision 13.4, extended by 19.6). Every ARL copied onto the artefact must satisfy all of:
  - it is finite;
  - it is `≥ 1.0`;
  - it is not `_ILL_CONDITIONED_ARL_SENTINEL`;
  - the solved chain's state count is `h_units + 1` (one-sided) or `(h_lower_units + 1) × (h_upper_units + 1)` (joint, including `B`'s coupled chain, which has the same state space).

  This covers `achieved_arl`, `expected_detection_arl` and, when present, `expected_improvement_detection_arl`. A violation raises `DegenerateBaselineError(reason="arl_not_computable")`, row F14. The sentinel may steer the calibration search but must **never** be copied into a field. No measured input reaches this path after Decisions 13.1–13.3, so it is a guard, not an expected outcome.

**Lattice quantisation invariant: a per-arm adaptive denominator with centring tolerance** *(ADR-014 Amendment 1 Decision 7. **Built on PR #29** (`_adaptive_lattice_denominator`, `_EPSILON = 0.25`), replacing the earlier fixed `N = 100`, but as the linear scan that corrigendum C2 replaces.)*
- **The rule.** Each arm computes its own lattice denominator `N` independently, as the smallest integer for which the quantised reference value `r_q = round(r × N) / N` satisfies both:
  - (a) `r_q` lies strictly inside the arm's own design interval (the open interval ADR-012's derivation requires);
  - (b) `|r_q − r| ≤ ε × (interval width)`, with `ε = 0.25`. This centring tolerance keeps `r_q` near `r` rather than at the interval's edge. Without centring, `r_q` positions of 0.96–1.00 inflate joint state counts 2.5–3.5×.
- **The interval per arm.** For the lower arm it is `(p_U, M·p_U)`. For the upper arm, after Decision 19, it is `(1 − p_L, 1 − p_L/M)` on the success indicator.
- **How `N` is found** (corrigendum C2 part 1, a specification correction). `N` is the **smallest denominator of any rational in the closed interval `[r − ε·gap, r + ε·gap]`**, found by the continued-fraction (Stern–Brocot) construction in exact `Fraction` arithmetic. Then `r_units = round(r·N)` at that `N`, and both invariants (a) and (b) are verified exactly.
  - It is the same decision rule as Decision 7's upward scan from `N = 2`, with the same output. They were measured identical on 797 of 797 real design points.
  - It is O(log N): 0.1–0.2 ms per design even at `M − 1 = 10⁻⁷`.
  - The linear scan is **replaced**. It was bounded only by `⌈1/(2ε·gap)⌉`, so it hung as `M → 1⁺` (reproduced on PR #29 at `M = 1.0000001`).
  - Neither method uses the closed-form bound as `N`: that overshoots the minimum by about 3.4×, giving about 12× more joint states.
- **Why per arm.** The two arms need very different granularities. So a single shared denominator would have to be the larger of the two, or worse their LCM. The independent per-arm approach avoids this entirely.

🚨 **This invariant is the correctness fix Amendment 1 exists for.** A fixed `N = 100` lattice denominator places `r_q` outside the design interval whenever the interval is narrower than one lattice step. For the lower arm that is every `f = 0` baseline at `m ≥ 300`. The consequences range from destroyed detection to unbounded calibration. See Amendment 1 §0.

**Resource bounds on `fit_bernoulli_cusum`** (Amendment 1 Decisions 9, 10a and 10b, as amended by Amendment 2 Decisions 13.3, 13.5, 16 and 17). The full `context` for each refusal is in the Error Contract Reference's Bernoulli table (rows F5, F12, F13).

1. **`target_arl` ceiling at `MAX_MEANINGFUL_ARL` (= 1,000,000)** (Decision 9). It is a cost bound, not a verification boundary, and it is checked before calibration. Amendment 2 merges it with the lower bound and non-finiteness into **one** refusal, F5: `constraint`, `kind="invalid"`, `provided`, `min_value=1.0`, `max_value=MAX_MEANINGFUL_ARL`, and both inclusive. That is the key set `parameter_guards.classify_target_arl` already emits. It should come from a shared helper, because hand-rolling it is how `constraint` was lost on PR #29.
2. **Per-arm calibration search cap** (Decision 10a, amended). `_MAX_DECISION_INTERVAL_UNITS` becomes **999,999** (`_MAX_JOINT_STATES − 1`; Decision 13.3, ratified Q3). It was 2,000,000 on PR #29, which allowed a one-sided solve peaking near 2 GB.
   - **No single solve, one-sided or joint, exceeds 1,000,000 transient states**, about 958 MB.
   - **In `"lower"`/`"upper"` mode**, reaching the cap raises F12. It reports `max_attainable_arl`, which round-trips as a one-sided target, plus `provided` and `direction`. Since only the checked arm is designed (C3), `direction` names that arm.
   - **In `"two_sided"` mode, a per-arm cap hit is reported as the joint-state refusal F13, never F12** (Decision 16). If either arm's `h_units` exceeds 999,999, then `(h_lo+1)(h_up+1) ≥ 1,000,001` is over the joint cap whatever the other arm is. A per-arm `max_attainable_arl` would not round-trip as a two-sided target, whose per-arm target is `2T`.
3. **Joint two-sided state cap of 1,000,000** (Decision 10b, unchanged). It raises F13, with `reason="joint_state_count_exceeded"` and `max_two_sided_target_arl`, which round-trips.
   - **How the value is computed** (corrigendum C11, ratified C-Q3). It is `floor(T_ES)`, capped at `MAX_MEANINGFUL_ARL`, where `T_ES = max over a ≥ 1 of min(A_lo(a), A_up(H(a))) / 2` and `H(a) = floor(1,000,000/(a+1)) − 1`. `A_lo`/`A_up` are the one-sided in-control ARLs of the lower arm at `p_U` and the upper arm at `1 − p_L`. `T_ES` is the largest two-sided target whose **equal-split** design fits the joint cap. It is found by a bisection on `a` (about 19 probes, two one-sided solves each, no joint solve), which is valid by proof, not by measurement.
   - **It is conservative, not the true maximum.** Calibration D may fit a larger two-sided target: measured 0–31% below the true D maximum (e.g. 252,207 against 367,937 at m=3,000,000 f=1).
   - **It round-trips by construction, through a one-solve guard.** At the reported value, the refusal path computes the ES design and one coupled solve. If `B_ES ≥ T` and the ES states are within the cap, D provably fits there. If the guard ever fails, the path falls back to the exact D maximum (slow, and never observed). The premise "D needs no more states than ES" is empirical: 302 of 302 designs held, with a smallest margin of `B_ES/T = 1.0025`. Correctness does not rest on it.
   - An ill-conditioned one-sided solve during the search steers it as "+∞" under BIN-140's rule, and is never reported.
   - **Budget.** The refusal's overhead (the ES bound plus the guard, beyond the fit's own feasibility check) must be ≤ 30 s locally at every C11 refusal cell; the measured maximum is 25.8 s. This replaces Decision 18 item 12's ≤ 5 s, which was never met, and Amendment 1's "under 1 s", which was withdrawn as unmeasured. The fit's own feasibility check is not budgeted here; iterative solvers are a separate ticket.

⚠️ **Corrections to what this section previously said** (Amendment 2 §0):
- "one-sided state count at 10⁶ is at most ~40,000 at any tested baseline" was **wrong at the edges**. Measured: 300,924 states at m=300,000 and 742,099 at m=3,000,000, T = 10⁶. So `direction="lower"`/`"upper"` does **not** "always succeed up to `MAX_MEANINGFUL_ARL`": F12 can fire.
- `"upper"` also refuses at f = 0 (F15).
- "`target_arl = 370` fits every baseline" held on PR #29 only because the floor it would have collided with was never built. Under Decision 12 it holds because nothing refuses below the floor.
- The recovery hint suggesting a one-sided direction remains legitimate, but it is no longer a guarantee.

**Every reported bound must round-trip as an accepted input.** This covers `MAX_MEANINGFUL_ARL`, `max_attainable_arl`, `max_two_sided_target_arl` (by C11's guard), `max_detect_rate_multiple`, and F16's computed `min_value` (by construction, C2). F7's former `min_value=0.0` is withdrawn. It is BIN-122's discipline, stated as an invariant of `fit_bernoulli_cusum`'s design. Decision 12's `boundary` is a disclosure, not a refusal bound. Passing it back as `target_arl` is accepted, and it reproduces the same floored chart.

**`FittedArtefactBase` finite-float postcondition (BIN-142) still applies**, and its `sigma_estimate` field-validator (`check_fields=False`) does not fire on this type. **Corrigendum C7 (settles OQ-34): the validator must cover fields annotated `float` *and* `float | None`, skipping `None`.** The computed float properties need no check, because each is `units / denominator` over validated `int`s with `denominator ≥ 2`. A directly constructed artefact with a `NaN`/`inf` `expected_improvement_detection_arl` must raise the existing BIN-142 `InvalidParameterError`. *The gap that motivated it, as found on PR #29:* `every_float_field_must_be_finite` iterates `model_fields` and skips any field whose annotation is not exactly `float`. After Amendment 2:
- `expected_improvement_detection_arl` (`float | None`) would escape BIN-142's type-level backstop;
- so would the four computed properties, which are not `model_fields` at all.

The computed ones derive from validated integers and cannot be non-finite. The optional field is covered on the fitting path only, by Decision 13.4's postcondition, and not against direct construction. The invariant BIN-142 ratified ("every float field on every `Fitted*` type is finite") stands for it when present, now enforced as C7 specifies.

`__bool__` forbidden, `ConfigDict(frozen=True)`, `audit_summary()`: the same conventions as every other `Fitted*` type (BIN-110, BIN-108). `audit_summary()` gains two lattice lines (Decision 14 cost) and must show `p_l` and the improvement figure.

**BIN-133 implementation status (checked against PR #29 at `5b7e3a1`, 2026-09-24, not inferred from ADR text).** Nothing below is on `trunk`.

| Decision | On PR #29 (`feat/BIN-133/bernoulli-cusum`, unmerged)? |
|---|---|
| Original ADR-014 (Decisions 1–6): artefact type, `fit_bernoulli_cusum`, `Monitor` widening, binary-score checks | Built. Upper arm designed at `p_U` (`q0_upper = 1 − p_u`), which is superseded by 19 |
| Amendment 1, Decision 7: adaptive per-arm `N`, ε = 0.25 | Built |
| Amendment 1, Decision 8: independent per-arm joint lattices | Built, **but** the solvers are fed floats rebuilt through `Fraction.limit_denominator(100_000)` (`_lattice_denominator`, `_DENOMINATOR_RECONSTRUCTION_CAP`), which is defect 2 |
| Amendment 1, Decisions 9, 10a, 10b: ceiling, search cap, joint cap | Built, with the key gaps Decision 17 lists. The ceiling has no `constraint`. The search cap has no `provided` or `direction`. The joint cap has no `constraint`. `score_not_binary` has no `provided`. The cap is 2,000,000, not 999,999 |
| Amendment 2, Decision 12: fit-and-disclose, floor advisory | **Not built.** No floor refusal exists either: Decision 3 item 2 was never built, which is defect 1. `advisories=()` always |
| Amendment 2, Decision 13: integer path, 999,999 cap, raising postcondition, cheap bisection | **Not built** |
| Amendment 2, Decision 14: `BernoulliArmLattice`, lattice fields, computed floats, integer `Monitor`, M2 | **Not built.** Four stored float fields. `Monitor` accumulates floats (`_bernoulli_s_lower/_upper`) |
| Amendment 2, Decision 15: direction-aware `expected_detection_arl` | **Not built.** `"upper"` evaluates at `p̂·M`, the degradation |
| Amendment 2, Decision 16: two-sided cap hit → F13 | **Not built** |
| Amendment 2, Decision 17: full `context` table, F14, F15 | **Not built** |
| Amendment 2, Decision 19: `p_L`, `B`, calibration D, f = 0 shape, `expected_improvement_detection_arl` | **Not built.** No `p_l`. Two-sided uses the equal split at `p_u`. f = 0 two-sided fits both arms and reports `"two_sided"` |
| Corrigendum C2–C7, C11: F16 and the per-fit `M` bound, the continued-fraction finder, only-checked-arms, the missing-lattice M2, the `calibration_method` strings, `provided`/`provided_type`, the `float \| None` backstop, `floor(T_ES)` | **Not built.** PR #29 leaks `ZeroDivisionError` at `M=1.0` and `ValueError` at `M=0.5`, and hangs at `M=1.0000001`; it always designs both arms |

**`sigma_estimate` invariant (BIN-119, amended 2026-09-11 after `code-reviewer`'s BIN-119/BIN-120 review; moved to a shared base under BIN-142):** all three concrete types above validate `sigma_estimate` at construction — a `@field_validator` mirroring `ScoringResult.must_be_finite`, now inherited from `FittedArtefactBase` rather than written out three times — raising `InvalidParameterError` (`context["parameter"] == "sigma_estimate"`, `kind == "invalid"`) for `NaN`, `+/-inf`, `0.0`, or a negative value. This is deliberately a *second*, independent guard alongside `_moving_range_sigma`'s own `DegenerateBaselineError` (see the Error Contract Reference below): the fitting-time guard diagnoses an unusable *baseline*, while this one is an invariant of the *type itself* — no `Fitted*` instance may ever hold an unusable sigma, regardless of how it is constructed, not only through `fit_ewma`/`fit_cusum`/`fit_shewhart`. `code-reviewer`'s review caught that the original BIN-119 fix guarded only the fitting path and left every `Fitted*` type constructible directly with `sigma_estimate=inf`/`0.0`/`nan` — the acceptance criterion "no artefact with `sigma_estimate=inf` can be constructed" was not actually met until this validator was added. Per `CLAUDE.md`'s own rule ("Validation belongs in the value object, not the caller").

### The Dual-Spread Distinction — All *Continuous* Charts (corrected from ADR-004 finding; narrowed BIN-133/ADR-014)

⚠️ **Narrowed this pass.** This section's "All Charts" heading and the "applies equally to EWMA, CUSUM, and Shewhart" line below predate BIN-133. They now describe the three **continuous** chart types only. `FittedBernoulliCUSUM` (ADR-014, modelled above; not on `trunk`) has no sigma-based quantity at all: its statistic accumulates the raw pass/fail value directly against a probability-space reference value, so neither `baseline_spread` nor `sigma_estimate` has a referent for it, and the type declares neither field. This is not a gap to fill later — see `HasProvenance` above for why forcing a mechanically-computed-but-unused `sigma_estimate` onto it was considered and rejected.

Every **continuous** fitted artefact carries **two** spread-related quantities in the shared core. They are different quantities that answer different questions:

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

### `BernoulliArmLattice`

*(New, ADR-014 Amendment 2 Decision 14.1, ratified 2026-09-24 (Q5). **Not built.**)*

**Carried by:** `FittedBernoulliCUSUM.lattice_lower` and `FittedBernoulliCUSUM.lattice_upper`, each present **exactly when the artefact's `direction` checks that arm** (corrigendum C3).
**Equality:** by value (all three integers).
**What it is:** the exact integer definition of one arm of a Bernoulli CUSUM. It is **the stored, authoritative chart**, and every float that describes the arm is derived from it. The three numbers are meaningless apart, which is why they form one named object per arm rather than six flat fields beside the floats. Six flat fields were rejected as two stored records of the same number, plus namespace noise.

| Field | Type | Constraint | Meaning |
|-------|------|-----------|---------|
| `denominator` | `int` | `>= 2` | `N`, the lattice step is `1/N` (Decision 7's rule, found by C2's continued-fraction finder). **No upper bound** (Decision 13.2; its "stays under 2×10⁶" sentence is withdrawn by C9). `N` = 3,364,300 for the upper arm at m=300,000 f=1, and is unbounded in principle as `M → 1⁺`. Nothing depends on its size: state counts depend on `h_units` |
| `reference_units` | `int` | `0 < reference_units < denominator` | `r_units`; the reference value is `r_units / N` |
| `decision_interval_units` | `int` | `1 <= decision_interval_units <= _MAX_DECISION_INTERVAL_UNITS` (999,999, Decision 13.3) | `h_units`; the decision interval is `h_units / N`. The arm signals when its integer statistic strictly exceeds this (ADR-009 §5) |

**Derived, read-only:** `reference_value = reference_units / denominator` and `decision_interval = decision_interval_units / denominator` (both `float`).

**Constraints:**
- Validators enforce each bound above, and reject `bool` and any integer that is not an exact `int` (Decision 14.1). Validation raises `InvalidParameterError` directly, per this inventory's convention. The ADR names no `context` keys for *construction-time* rejection of this type. The Monitor-time re-validation has its own row, M2.
- Immutable (`ConfigDict(frozen=True)`), and `__bool__` raises `TypeError` like every other domain type (BIN-110).
- `repr` shows the three integers. A `Fraction`-style `r=8/9, h=40/9` form is equally acceptable; the choice is the implementer's (Decision 14.1).

**Construction:** only by `fit_bernoulli_cusum` in the normal path. Engineers read it; they do not construct it. It is **exported from `drift_caliper.baseline`**, because it appears in a public field's type, but **not** from the top-level `drift_caliper` namespace (Decision 14).
**Rejects (as a `CaliperError`):** a non-exact or `bool` integer, and any integer outside its bound.
**Re-validated at use by `Monitor`** (Decision 14.5, row M2), because `model_copy(update=...)` and `model_construct()` bypass these validators on a caller-supplied artefact.

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
| **Accumulator** | A `Monitor`'s private, chart-specific carried-forward state between `record()` calls: none for Shewhart (memoryless), the smoothed statistic for EWMA, the two one-sided running sums for CUSUM, and two integer lattice-unit statistics for the Bernoulli CUSUM (ADR-014 Decision 14.4). Lives on `Monitor`, never on the immutable fitted artefact. What happens to it immediately after a signal is open — see `BIN-113` in Open Questions. | Monitoring | ADR-009 §1 |
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
| **Achieved ARL** | The ARL_0 actually produced by the calibration. May differ from requested due to numerical approximation (Markov-chain for EWMA, Siegmund for CUSUM). Under normality, Shewhart's is exact. **For the Bernoulli CUSUM it is exact, and it is always `≥` requested.** One-sided, it is the checked arm's exact ARL₀ at its own design rate: `p_U` for the lower arm, `p_L` for the upper. Two-sided, it is the guaranteed floor `B` (below). Neither is the expected spacing at the observed rate `p̂` (ADR-014 Decisions 12, 19.4). | Baseline | ADR-004, ADR-014 Amendment 2 |
| **Control limits** | UCL (upper control limit) and LCL (lower control limit) defining the in-control region, plus CL (centre line). Used by EWMA and Shewhart charts. On the observation scale — a score beyond UCL or below LCL triggers a signal. | Baseline | BIN-65, BIN-95 |
| **Decision interval** (*h*) | The CUSUM threshold. Compared against the accumulating CUSUM statistic *S*, NOT against observations directly. Not on the observation scale. Derived from the reference value and target ARL_0 via Siegmund's approximation — the engineer does not specify it. | Baseline | BIN-94, ADR-004 |
| **Reference value** (*k*) | The CUSUM shift size parameter, in sigma units. The size of shift the CUSUM is optimised to detect. Has a library default. | Baseline | BIN-94, ADR-004 |
| **Smoothing parameter** (lambda) | The EWMA weighting parameter controlling sensitivity to recent vs historical observations. Has a library default. | Baseline | BIN-65, ADR-004 |
| **Baseline spread** | The sample standard deviation of Phase I scores. A shared descriptive statistic on all fitted artefacts (part of the `FittedControlLimits` protocol). Captures TOTAL variation including any slow drift within the baseline. **Not the operational sigma** — see sigma estimate. | Baseline | ADR-004 |
| **Sigma estimate** / **moving-range sigma** | The short-term variation estimate from consecutive-observation differences: MR-bar / d_2 for span 2. Used by **all three chart types** (EWMA, CUSUM, Shewhart) for control limit computation on individual observations. Part of the shared core. Captures SHORT-TERM variation only, robust to slow drift. **Different from baseline spread** — see dual-spread note above. | Baseline | ADR-004, standard SPC practice (verified) |
| **Sigma multiplier** | The number of sigma units defining Shewhart control limits. Derived from the false alarm tolerance — not specified by the engineer. | Baseline | BIN-95, ADR-004 |
| **Calibration method** | The numerical procedure that determined the chart's parameters from the target ARL_0. EWMA: Markov-chain (Lucas and Saccucci 1990). CUSUM: Siegmund's corrected diffusion approximation (1985). Shewhart: direct tail probability. | Baseline | ADR-001, ADR-004 |
| **Chart type** | One of EWMA, CUSUM, or Shewhart I-chart in R1. Reported on every fitted artefact. | Baseline | ADR-004 |
| **Direction** (CUSUM) | Which direction(s) of drift are monitored. `"two_sided"` (default): both arms. `"lower"`: degradation only (score drifts down). `"upper"`: improvement only (baseline staleness). Two-sided default, configurable to one-sided (ADR-004 section 6). Same vocabulary and default on `FittedBernoulliCUSUM` (ADR-012 amendment; BIN-133). There it reports the chart that **runs**, not the one requested: a two-sided request against a zero-failure baseline returns `"lower"`, and `"upper"` is refused there (ADR-014 Decision 19.2). | Baseline | ADR-004 |
| **Bernoulli CUSUM** | The CUSUM control chart for a binary (pass/fail) rubric — a sequential likelihood-ratio test accumulating `max(0, · )` against a decision interval, exactly like the continuous CUSUM, but on a raw `0`/`1` statistic rather than an observation standardised by sigma. Ships ahead of the deferred Bernoulli EWMA because its ARL₀ is exact (a finite Markov chain), not approximate (ADR-012 §4/§5). Modelled under BIN-133 (ADR-012/013/014 and both ADR-014 amendments). Not on `trunk`: see "BIN-133 implementation status" under `FittedBernoulliCUSUM`. | Baseline | ADR-012, ADR-013, ADR-014, BIN-133 |
| **`detect_rate_multiple`** (*M*) | The Bernoulli CUSUM's shift lever — the design point is `M` times the in-control failure rate, rather than a sigma multiple, because a Bernoulli process has one parameter (its variance, `p(1−p)`, is determined entirely by the rate). Default `2.0`, measured (not conventional) as the largest multiple defined across the whole legal domain (`p₀ < 0.5`). Replaces `reference_value` for this chart family. **Legal range** (ADR-014 corrigendum C2): finite and greater than a per-fit computed lower bound, always `> 1`. `M ≤ 1` detects no shift or mislabels the arms, and just above 1 the design outruns double precision. Violations raise F16, whose `min_value` round-trips. | Baseline | ADR-012 §1, ADR-014 corrigendum C2 |
| **Guaranteed In-Control Performance (GICP)** | The design principle the Bernoulli CUSUM is calibrated under. **Each arm is designed at the confidence bound on the baseline's failure rate that is conservative for the shift it detects**, not at the plain estimate `p̂`. The lower (degradation) arm uses the upper bound `p_U`; the upper (improvement) arm uses the lower bound `p_L` (ADR-014 Decision 19.1). As a result `P(true ARL₀ ≥ target) ≥ 1 − α` holds per baseline for each one-sided arm, not merely on average across baselines. From Heidema et al. (2026), *Biometrical Journal*, originally for Poisson counts. Bernoulli's exact analogue of the paper's Garwood construction is Clopper–Pearson. The paper's proof covers increases only; the decrease case is derived in ADR-014 19.1 by coupling and measured in 19.3. Supersedes the provisional uniform baseline floor (ADR-013 §2). | Baseline | ADR-013, ADR-014 Decision 19 |
| **`p_U`** / **Clopper–Pearson upper bound** | The one-sided Clopper–Pearson upper confidence bound on the baseline's failure rate, `p_U(f, m, α)`: the quantile of `Beta(f+1, m−f)` at `1−α`, with closed form `1 − α^(1/m)` when `f=0`. **The lower (degradation) arm's design and calibration rate** (ADR-013 §1). ~~It is used in both arms of the two-sided design (ADR-014 §6d).~~ Superseded for the upper arm by `p_L` (ADR-014 Decision 19). `1/p_U` is also the lower arm's floor; see Lower-arm floor. | Baseline | ADR-013 §1, ADR-014 Decision 19 |
| **`alpha`** (α) | GICP's own risk-appetite parameter: the guarantee's chance of failing to hold, `P(true ARL₀ < target) ≤ α`. Ratified `0.10` (ADR-013 §3, the largest of five tested values that clears ADR-005's ≤5% baseline-adequacy appetite on its *upper confidence bound*, not merely its point estimate). Reported on the fitted artefact for auditability; **not** an engineer-facing parameter in this release (ADR-014 Decision 5) — exposing it would let an engineer choose a value outside the verified five-point grid. **Distinct from, and bounds a different event than, ADR-005's ratified ≤5% baseline-adequacy appetite** — do not conflate the two "5%-ish numbers" (ADR-013 §3's own warning). | Baseline | ADR-013 §3 |
| **`expected_detection_arl`** | The Bernoulli CUSUM's detection-performance disclosure: the exact `ARL₁` of the constructed chart, evaluated at **the shift the checked arm(s) are tuned to detect** (ADR-014 Decision 15). For `"lower"` and `"two_sided"` that is a degradation, `p̂ × M`. For `"lower"` at `f = 0` it is `p_U × M`, since "a rise from zero" is otherwise undefined. For `"upper"` it is an improvement, `p̂ / M`, and `f ≥ 1` always holds there because `"upper"` refuses at `f = 0`. It answers "how fast will this plausibly catch the shift it is tuned for", as distinct from `achieved_arl`'s "is my false-alarm promise safe". It is a first-class, unconditional field, not routed through `FittingAdvisory` (ADR-014 Decision 4), so that a chart safe-but-practically-inert at a small, low-rate baseline never discloses only its reassuring half (ADR-013 §4). On a two-sided chart the second arm's figure is `expected_improvement_detection_arl`. | Baseline | ADR-013 §4, ADR-014 Decisions 4, 15 |
| **`p_L`** / **Clopper–Pearson lower bound** | The one-sided Clopper–Pearson lower confidence bound on the baseline's failure rate: the `α` quantile of `Beta(f, m − f + 1)`, at the same ratified `α = 0.10` as `p_U`. Closed form at `f = 1`: `1 − (1 − α)^(1/m)`. It is `0` at `f = 0`, where no upper arm can be designed. **The upper (improvement) arm's design and calibration rate.** It is conservative for that arm because the arm's ARL₀ falls as the true failure rate falls. Reported as `FittedBernoulliCUSUM.p_l`. | Baseline | ADR-014 Decision 19.1 |
| **Guaranteed floor** (`B`) | The two-sided Bernoulli CUSUM's `achieved_arl`: the exact expected run length of the **coupled three-outcome chain**. One uniform per step counts as a failure for both arms below `p_L`, as a failure for the lower arm and a success for the upper between `p_L` and `p_U`, and as a success for both above `p_U`. It is **at or below the true two-sided ARL₀ for every true failure rate in `[p_L, p_U]`**, so it is a floor that holds there, not an estimate. It promises nothing for a true rate outside that interval (the breach rate there is measured, not guaranteed: worst appetite 1.781% under calibration D). It is not the spacing at `p̂`, which is usually much longer. | Baseline | ADR-014 Decision 19.4 |
| **Calibration D** | The two-sided Bernoulli CUSUM's calibration, ratified 2026-09-24. The lower arm keeps its **equal-split** design: one-sided to `2T` at `p_U`. The upper arm's decision interval is the **smallest** for which the guaranteed floor `B` meets `T`. It delivers `B` close to the request (median `B/T` 1.001–1.08) and detects degradation faster at low `p₀` than the equal split. Formerly "option (d)". | Baseline | ADR-014 Decisions 12 (option d), 19.4 |
| **Equal split** (ES) | The two-sided calibration shipped on PR #29, where each arm is calibrated one-sided to `2T` at its own design rate. It passes the appetite but over-delivers (`B/T` 1.01–1.27). Calibration D keeps it for the lower arm only. It survives in one more place: the F13 refusal's `max_two_sided_target_arl` is the ES maximum `floor(T_ES)` (corrigendum C11). | Baseline | ADR-014 Decision 19.4, corrigendum C11 |
| **`T_ES`** / **equal-split bound** | The largest two-sided `target_arl` whose **equal-split** design fits the 1,000,000 joint-state cap: `max over a ≥ 1 of min(A_lo(a), A_up(H(a))) / 2`, with `H(a) = floor(1,000,000/(a+1)) − 1`. Found by a bisection on `a` with no joint solve. `floor(T_ES)`, capped at `MAX_MEANINGFUL_ARL`, is what F13 reports as `max_two_sided_target_arl`. It is **conservative**: it may sit below the true calibration-D maximum (0–31% measured). It is guaranteed to round-trip by a one-solve guard that falls back to the exact D maximum. | Baseline | ADR-014 corrigendum C11 |
| **`expected_improvement_detection_arl`** | On a two-sided Bernoulli CUSUM only, the exact ARL of the two-sided chart at the single true failure rate `p̂ / M`: the improvement its upper arm is tuned to detect, the mirror of `expected_detection_arl`'s `p̂ · M`. It is `None` whenever the chart does not check both arms: `"lower"` (including at `f = 0`), and `"upper"`, where `expected_detection_arl` already is the improvement figure. It is a number, not a warning, with no threshold attached. It makes visible when the upper arm has essentially no power (`p̂·T ≪ 1`). | Baseline | ADR-014 Decision 19.6 |
| **`BernoulliArmLattice`** | The exact integer definition of one Bernoulli CUSUM arm: `denominator` (`N`), `reference_units` (`r_units`) and `decision_interval_units` (`h_units`), with `r = r_units/N` and `h = h_units/N`. It is **the stored, authoritative chart**. The arm's float `reference_value_*`/`decision_interval_*` are derived from it, and `Monitor` steps its integers directly. Carried as `lattice_lower` and `lattice_upper`, each present exactly when the artefact's `direction` checks that arm (corrigendum C3). Exported from `drift_caliper.baseline`, not the top level. | Baseline, Monitoring | ADR-014 Decision 14 |
| **Lattice units** | The integer scale a Bernoulli CUSUM arm's statistic lives on: one unit is `1/N` of that arm's own denominator. The two arms have independent denominators (Amendment 1 Decision 8). Every reported ARL is solved on, and every `Monitor` step taken in, these integers; nothing is rebuilt from floats (ADR-014 Decision 13). | Baseline, Monitoring | ADR-014 Decisions 8, 13, 14 |
| **Lower-arm floor** | The smallest in-control ARL₀ any lower-arm Bernoulli CUSUM can have on a given baseline: exactly `1/p_U`. At that floor a single failure signals. It is a property of the chart, independent of the lattice, `M` and `direction`. A requested `target_arl` below it is **fitted and disclosed**, not refused (`FittingAdvisory(kind="lower_arm_signals_on_first_failure")`), and `achieved_arl` reports the true value. This replaces ADR-014 Decision 3 item 2's refusal. | Baseline | ADR-014 Decision 12 |
| **Upper arm not designable** | The zero-failure-baseline case, where `p_L = 0` and no improvement-detecting arm can be built. A two-sided request fits the lower arm alone, reports `direction="lower"`, and carries `FittingAdvisory(kind="upper_arm_not_designable", boundary=1.0)`, the smallest failure count at which the arm becomes designable. An `"upper"` request is refused (F15). A directly requested `"lower"` does not carry the advisory, because its upper arm is not checked at all (corrigendum C3). | Baseline | ADR-014 Decision 19.2 |
| **Continued-fraction lattice finder** | How a Bernoulli CUSUM arm's lattice denominator `N` is found: the smallest denominator of any rational in `[r − ε·gap, r + ε·gap]`, by the Stern–Brocot construction in exact `Fraction` arithmetic. It gives the same result as Decision 7's upward scan in O(log N), and replaces that scan, which hung as `M → 1⁺`. | Baseline | ADR-014 corrigendum C2 |
| **Higher-is-better** | Caliper's score orientation (ADR-001). A falling score = degradation (lower CUSUM arm). A rising score = improvement / stale baseline (upper CUSUM arm). This mapping holds throughout the library. | Both | ADR-001 |
| **Signal** | An out-of-control determination from Phase II monitoring — concretely, a `MonitoringResult` with `is_in_control=False`, carrying `direction` and `fitted_artefact` (ADR-010 §2). The determination itself was modelled by ADR-009 (BIN-69); its R1 *delivery* — a `SignalReceiver` callable invoked synchronously on a genuine signal, absorbing but surfacing any receiver failure — is modelled by ADR-010 (BIN-75, BIN-76). Severity, webhooks, `RaiseOnSignal`, fan-out, and a formal handler interface remain unmodelled — BIN-77 through BIN-82, Release 2. | Monitoring | ADR-009, ADR-010 |
| **Signal receiver** / **`SignalReceiver`** | Any `Callable[[MonitoringResult], None]` supplied to `Monitor(artefact, receivers=[...])`. A plain type alias, not a `Protocol` or base class — no formal interface exists in R1 (ADR-010 §3). Invoked synchronously by `Monitor.record()`, once per configured receiver, only when a genuine signal occurs. A receiver that raises does not stop the recording call or the next receiver; its exception is captured, not propagated (see Delivery failure, below). | Monitoring | ADR-010 §§3–4 |
| **`log_receiver`** | R1's one built-in `SignalReceiver` (`caliper.monitoring.log_receiver`). Logs to `logging.getLogger("caliper.monitoring")` at `WARNING` — the level is required, not stylistic, to satisfy BIN-76 SC4's zero-configuration visibility guarantee against Python's `logging.lastResort` default. Carries the full signal content (`direction`, `fitted_artefact`, `observation`) via the stdlib `LogRecord`'s `extra=` mapping. Uses no third-party structured-logging library (BR-1, CLAUDE.md's ratified stdlib-`logging` decision). | Monitoring | ADR-010 §6 |
| **Delivery failure** / **`DeliveryFailure`** | The record of one `SignalReceiver` raising during delivery: which receiver (`receiver: str`), and why (`error_type: str`, `error_message: str`). Never raised itself — absorbed by `Monitor.record()` into `MonitoringResult.delivery_failures`, "absorb, but surface" (ratified by the product owner, 2026-09-11). Reachable only through the public result the recording call already returns — never through the receiver mechanism that just failed (ADR-010 §1). | Monitoring | ADR-010 §1 |
| **SPCPort** | The port interface for the SPC engine (ADR-001). The boundary between the domain and the statistical computation layer. Fitting operations are behind this port. | Baseline | ADR-001 |
| **`HasProvenance`** | The narrower, two-attribute `@runtime_checkable` protocol (`provenance_model_version`, `provenance_criteria`) that `compare_provenance()` actually reads — a strict subset of `FittedControlLimits`. Lets an artefact that cannot honestly satisfy the full twelve-attribute reporting contract (because it has no sigma-based quantity, no `baseline_mean`, etc.) still participate in provenance comparison. `FittedEWMA`/`FittedCUSUM`/`FittedShewhart` satisfy it incidentally; `FittedBernoulliCUSUM` satisfies it and nothing more (ADR-004's 2026-09-12 amendment; documented in this file for the first time under BIN-133). | Baseline | ADR-004 (2026-09-12 amendment), ADR-014 §6a |
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
| `InvalidParameterError` | `invalid_parameter` | `parameter`, `constraint`, `kind` (`"missing"` or `"invalid"`) | Judge creation (BIN-57), criteria config (BIN-58), sufficiency threshold (BIN-64), fitting parameters (BIN-65/94/95), `Monitor` construction from a non-artefact or a structurally-conforming-but-unsupported artefact (BIN-69/BIN-120), direct construction of any `Fitted*` type with a non-finite or non-positive `sigma_estimate` (BIN-119, amended 2026-09-11); direct construction of any `Fitted*` type with **any** non-finite `float` field, not only `sigma_estimate` (BIN-142); a `direction` that is not a `str` at `fit_cusum` or at `Monitor.record()` (BIN-143); **`fit_bernoulli_cusum` and `Monitor` over a `FittedBernoulliCUSUM` (BIN-133):** rows F1–F8, F10–F13, F15, F16, M2 and M3 of the complete Bernoulli CUSUM refusal contract below (ADR-014 Decision 17 + 19.5 + corrigendum). *(The per-refusal descriptions that used to sit in this cell, from ADR-014 §1/§6b and Amendment 1 Decisions 9/10a/10b, are superseded by that table.)* |
| `MissingPrerequisiteError` | `missing_prerequisite` | `prerequisite`, `operation` | Scoring without criteria (BIN-59) |
| `ProviderError` | `provider_failure` | `provider`, `operation` | LLM provider failure during scoring (BIN-59) |
| `MalformedResponseError` | `malformed_response` | `operation`, `expected_shape` | Unparseable judge response (BIN-59) |
| `JudgeRefusalError` | `judge_refusal` | `provider`, `operation` | Judge safety-filter refusal (ADR-002) |
| `ProvenanceMismatchError` | `provenance_mismatch` | `mismatches: dict[str, dict[str, str]]` (amended 2026-09-10, was `dimension`/`expected`/`received` — see ADR-002 Amendment) | Baseline recording (BIN-63), Phase II comparison (BIN-68), Phase II monitor recording (BIN-69, `Monitor.record()`, calls `compare_provenance()` internally — ADR-009 §2). **Unchanged for the Bernoulli CUSUM** (PRD BR-2/Story 3) — `compare_provenance()` is reused unmodified; `FittedBernoulliCUSUM` satisfying `HasProvenance` is exactly what keeps this true without a chart-specific carve-out |
| `InvalidObservationError` | `invalid_observation` | `reason`, `missing_fields` | Incomplete input to baseline (BIN-63), incomplete input to Phase II monitor recording (BIN-69, `Monitor.record()`, reused not a new category — ADR-009 §3); **BIN-133, row M1** (ADR-014 Decision 2; built on unmerged PR #29): a Phase II observation checked against a `FittedBernoulliCUSUM` whose `.score` is not exactly `0.0` or `1.0` — `context["reason"] == "score_not_binary"`, `context["missing_fields"] == ()` (nothing is missing; the value present is simply outside the domain this chart can interpret — a docstring broadening, not a new category, per ADR-002 §3's existing conditional-presence precedent on `InvalidParameterError.provided`) |
| `InsufficientBaselineError` | `insufficient_baseline` | `have`, `need` | Fitting from too-small baseline (BIN-65/94/95); **BIN-133, row F9**: `fit_bernoulli_cusum` below ADR-005's unchanged 100-observation floor (ADR-013 §2 — no new, higher, binary-specific floor ships) |
| `DegenerateBaselineError` | `degenerate_baseline` | `reason` (`"zero_variance"`, or, since BIN-119, `"non_finite_sigma_estimate"` / `"sigma_estimate_underflow"`, or, since BIN-142, `"non_representable_control_limits"`, or, for BIN-133 (ADR-014 Decision 13.4, row F14), `"arl_not_computable"` with `chart_type` and `figure`) | Fitting from zero-variance baseline (BIN-65/94/95); fitting from a baseline whose moving-range sigma estimate overflows to `inf` or underflows to exactly `0.0` (BIN-119, `_moving_range_sigma` in `spc_numerics.py`, shared by all three chart types). ~~**`fit_bernoulli_cusum` never raises this category**~~ **SUPERSEDED 2026-09-24 by ADR-014 Decision 13.4 (Q4 accepted): it raises it for exactly one reason, `arl_not_computable` (row F14), a raising postcondition on every reported ARL; for every *baseline-shaped* reason the original reasoning below still holds** (BIN-133, ADR-013 §5) — a zero-variance-shaped baseline for a binary chart is either `p̂=0` (designed normally at `p_U`) or `p̂=1` (refused as `InvalidParameterError`, the `p₁ ≥ 1` path above), and GICP's confidence-bound construction means neither needs the "statistically unusable despite meeting the count threshold" diagnosis this category exists for |

### Bernoulli CUSUM refusal contract — complete (ADR-014 Decision 17, extended by Decision 19.5 and the Amendment 2 corrigendum)

*(Ratified 2026-09-24. **Not built as a whole.** PR #29 emits most of these rows, but it lacks the keys marked "new" and the rows F14 and F15, and has no registry coverage.)* **These rows are the whole contract.** Every row is an emission site, and every key listed is required. The ADR-002 rules that apply here:
- §4 requires `parameter`, `constraint` and `kind` on every `invalid_parameter`;
- §3 requires `provided` whenever `kind == "invalid"`;
- BIN-134 adds `min_value`/`max_value` and `min_inclusive`/`max_inclusive` wherever a numeric bound is reported;
- BIN-122 requires every reported bound to round-trip.

Tests assert `isinstance` plus the full key set, never message text (ADR-008).

**`provided` vs `provided_type`** (corrigendum C6, settling OQ-35; the documented exception to ADR-002 §3 that BIN-143 already practises). A **type** failure reports `provided_type` and never the value, because a hostile object's `repr` can raise inside the error path. A **value** failure on an already exact-typed value reports `provided`. The registry test asserts exactly one of the two on every invalid-kind row, as assigned below.

**`fit_bernoulli_cusum`**

| # | Condition | Type | Required `context` |
|---|---|---|---|
| F1 | `baseline` is not a `Baseline` | `InvalidParameterError` | `parameter="baseline"`, `constraint`, `kind="invalid"`, `provided` (existing `require_type`). ⚠️ This is a type failure, for which C6's rule prescribes `provided_type` — OQ-38 |
| F2 | a baseline score is not exactly `0.0`/`1.0` | `InvalidParameterError` | `parameter="baseline"`, `constraint`, `kind="invalid"`, **`provided`** (new: the `Baseline` passed, the same meaning `require_type` gives it in F1), `reason="score_not_binary"`, `invalid_score`, `position` |
| F3 | `target_arl` omitted | `InvalidParameterError` | `parameter="target_arl"`, `constraint`, `kind="missing"` (no `provided`) |
| F4 | `target_arl` is not a real number, or is a `bool` | `InvalidParameterError` | `parameter`, `constraint`, `kind="invalid"`, `provided` (existing `require_real_number`, as Decision 17 lists it). ⚠️ This is a type failure; see OQ-38 |
| F5 | **new, merged:** `target_arl` is non-finite, `< 1.0` or `> MAX_MEANINGFUL_ARL` | `InvalidParameterError` | `parameter="target_arl"`, `constraint` (e.g. `"must be a finite float in [1.0, 1000000.0]"`), `kind="invalid"`, `provided`, `min_value=1.0`, `max_value=MAX_MEANINGFUL_ARL`, `min_inclusive=True`, `max_inclusive=True`. It replaces two separate raises, one of which had no `constraint`, and should come from a shared, bounds-parameterised helper (the `classify_target_arl` key set) |
| F6 | `detect_rate_multiple` is not a real number | `InvalidParameterError` | `parameter`, `constraint`, `kind="invalid"`, `provided`. ⚠️ This is a type failure; see OQ-38 |
| F7 | **narrowed (C2):** `detect_rate_multiple` is non-finite | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`. ~~`min_value=0.0`, `min_inclusive=False`~~ withdrawn, because F16 owns every lower bound |
| F8 | `direction` is not recognised, or is not an exact `str` | `InvalidParameterError` | `parameter="direction"`, `constraint`, `kind="invalid"`, plus **`provided_type`** on the not-an-exact-`str` path or **`provided`** on the unknown-string path (C6; existing `require_exact_str`/`_validate_direction`) |
| F9 | fewer than 100 observations | `InsufficientBaselineError` | `have`, `need` |
| F10 | every judgement failed | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`, `reason="all_baseline_judgements_failed"`; **no** `max_detect_rate_multiple` |
| F11 | `p_U × M ≥ 1` | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`, `max_detect_rate_multiple` (round-trips; computed from `p_U`, not `p̂`, per ADR-013 §6b; key name ratified and unchanged) |
| F12 | the one-sided search reaches `_MAX_DECISION_INTERVAL_UNITS` (999,999), for `"lower"`/`"upper"` only (Decision 16) | `InvalidParameterError` | `parameter="target_arl"`, `constraint`, `kind="invalid"`, **`provided`** (new: the caller's `target_arl`, not the per-arm figure), `max_attainable_arl` (round-trips as a one-sided target; OQ-25), **`direction`**, which names the one arm a one-sided fit designs (C3) |
| F13 | two-sided joint states exceed `_MAX_JOINT_STATES` (1,000,000), **or** a per-arm search-cap hit in two-sided mode, including inside calibration D's bisection (Decision 16, 19.5) | `InvalidParameterError` | `parameter="target_arl"`, **`constraint`** (new: e.g. `"the two-sided joint state count must not exceed max_joint_states"`), `kind="invalid"`, `provided`, `reason="joint_state_count_exceeded"`, `joint_state_count`, `max_joint_states`, `max_two_sided_target_arl`. **Since C11 that value is `floor(T_ES)`, the equal-split conservative bound** (possibly below the true D maximum, by 0–31% measured). It round-trips through a one-solve guard with an exact-D fallback. Reachable at f ≥ 1, e.g. m=300,000 f=1 T=10⁶ (C1). When a per-arm hit triggered it, `joint_state_count` is the lower bound `(h_lo+1)(h_up+1)` at the capped arm, which is still over the cap |
| F14 | **new:** a reported ARL fails its postcondition (Decision 13.4): non-finite, `< 1`, the sentinel, or a wrong state count | `DegenerateBaselineError` | `reason="arl_not_computable"`, `chart_type="bernoulli_cusum"`, `figure`, one of `"achieved_arl"`, `"expected_detection_arl"` or `"expected_improvement_detection_arl"` (the third added by 19.6, and confirmed by C10; the registry enumerates all three) |
| F15 | **new (Decision 19.5):** `direction="upper"` and the baseline has zero failures | `InvalidParameterError` | `parameter="direction"`, `constraint` (e.g. `"'upper' requires at least one failed judgement in the baseline"`), `kind="invalid"`, `provided="upper"`, `reason="no_baseline_failures"`; **no round-trip key**, since no value the engineer can pass would fix it (mirrors F10) |
| F16 | **new (corrigendum C2, option A ratified C-Q1):** `detect_rate_multiple` ≤ 1, or below the smallest multiple the design can resolve, or no multiple works | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`, and `reason`: <br>• `"no_shift_to_detect"` for `M ≤ 1`; <br>• `"shift_below_numerical_resolution"` for `1 < M < min_value`; <br>• `"no_valid_multiple"` when the computed `min_value` exceeds F11's `max_detect_rate_multiple` (only when `p_U` is near 1/2), with **no** `min_value`, mirroring F10. <br>For the first two reasons, also `min_value` (computed per fit by bisection on `log(M − 1)` with ≤ 64 probes of the lattice finder; the smallest `M` whose design is constructible and verified in double precision; round-trips by construction) and `min_inclusive=True`. ⚠️ See OQ-37 on which arms the bound is computed over |

**Not refusals: the two disclosures.** Both are carried on `FittedBernoulliCUSUM.advisories`. See that type's `advisories` row for the exact conditions.
- `FittingAdvisory(kind="lower_arm_signals_on_first_failure", description, boundary=<one-sided lower-arm ARL₀ at h_units = 1, i.e. 1/p_U>)` (Decision 12). **This replaces the original Decision 3 item 2's computed-attainability-floor refusal**, which is superseded and was never built. See OQ-20.
- `FittingAdvisory(kind="upper_arm_not_designable", description, boundary=1.0)` on a two-sided request against a zero-failure baseline (Decision 19.2).

**`Monitor`** (over a `FittedBernoulliCUSUM`)

| # | Condition | Type | Required `context` |
|---|---|---|---|
| M1 | Phase II score is not exactly `0.0`/`1.0` | `InvalidObservationError` | `reason="score_not_binary"`, `missing_fields=()` (existing, Decision 2) |
| M2 | **new:** a lattice on a caller-supplied `FittedBernoulliCUSUM` has an integer that is not exact, or is out of bounds (Decision 14.5); **or** `direction` checks an arm whose lattice is `None` (corrigendum C4) | `InvalidParameterError` | `parameter="artefact"`, `constraint`, `kind="invalid"`, `field`, plus: <br>• for a non-exact `int`: `provided_type`, with `field` e.g. `"lattice_upper.reference_units"`; <br>• for an exact `int` out of bounds: `provided`; <br>• for a missing lattice: `provided_type="NoneType"`, with `field` = `"lattice_upper"`/`"lattice_lower"` (C6). <br>Checked in `record()` before any state changes |
| M3 | the artefact's `direction` is not an exact `str` | `InvalidParameterError` | the existing `require_exact_str` keys (BIN-143): `parameter="direction"`, `constraint`, `kind="invalid"`, `provided_type` (C6) |

**Enforcement** (Decision 17): every row is registered in `tests/support/exception_contract_registry.py`. One parametrised test drives each site through the public API and asserts the full key set, and the round-trip for bounds. A site added later without a registry row must fail the BIN-121 exception-contract audit.

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
| Fit Bernoulli CUSUM | BIN-133 | `Baseline` (inferred binary at fit time — no declared "kind"), `target_arl`, optional `detect_rate_multiple`, optional `direction` | `FittedBernoulliCUSUM` | Baseline — **domain-modelled (ADR-012/013/014 + Amendment 1, 2026-09-23 + Amendment 2, 2026-09-24). Not on `trunk`.** PR #29 (`5b7e3a1`, unmerged) builds the original ADR and Amendment 1, with the gaps its re-review found. Amendment 2 (Decisions 12–19) is not built. Raises exactly the rows of the Bernoulli CUSUM refusal contract (F1–F16, Error Contract Reference). The artefact carries only the arms `direction` checks (corrigendum C3). Since Amendment 2 it **never refuses a `target_arl` for being below what is attainable**: a floored lower arm is fitted and disclosed (Decision 12). **`DegenerateBaselineError` is raised for one reason only**, `arl_not_computable` (F14, a postcondition guard, reversing the former "never raises"). A two-sided request on a zero-failure baseline returns a lower-only chart; `"upper"` there is refused (F15) |
| Review artefact | BIN-66 | Any `FittedControlLimits` | Read properties; `audit_summary()` | Baseline — **implemented** (BIN-66) |
| Compare provenance | BIN-68 | `ScoringResult`, `FittedControlLimits` | Confirms compatibility or raises `ProvenanceMismatchError` | Baseline — **implemented** (BIN-68) |
| Create monitor | BIN-69, BIN-75 | one of `FittedEWMA`/`FittedCUSUM`/`FittedShewhart` (⚠️ **not** any `FittedControlLimits` — BIN-120), plus `FittedBernoulliCUSUM` once BIN-133 lands (on unmerged PR #29; integer stepping per ADR-014 Decision 14 not built), optional `retain_history: bool`, optional `receivers: Sequence[SignalReceiver]` (ADR-010) | `Monitor` | Monitoring — **implemented** |
| Record Phase II observation | BIN-69, BIN-75 | `ScoringResult` | `MonitoringResult` (now carrying `direction`, `fitted_artefact`, `delivery_failures` — ADR-010) | Monitoring — **implemented**. Raises `ProvenanceMismatchError`, `InvalidObservationError`; never raises for a signal or a delivery failure. |
| Review monitoring history | BIN-72 | (none) | `tuple[MonitoringResult, ...]` | Monitoring — **implemented**. Zero-config by default. |
| Clear monitoring history | BIN-72 | (none) | `None` | Monitoring — **implemented**. Manual escape hatch, no automatic eviction policy in R1. |
| Deliver a signal to configured receivers | BIN-75 | (implicit — part of `record()`) | Each configured `SignalReceiver` invoked with the `MonitoringResult`; failures absorbed into `delivery_failures` | Monitoring — **implemented**. Synchronous, inside `record()`, only on a genuine signal. Never raises. |
| Log a signal via the built-in receiver | BIN-76 | `MonitoringResult` (as any `SignalReceiver`) | `None` (writes a `WARNING`-level record to `logging.getLogger("caliper.monitoring")`) | Monitoring — **implemented** as `log_receiver` (a function, not a `LogReceiver` class). `caliper.monitoring.log_receiver`, stdlib `logging` only. |

**Fitting parameter semantics (ADR-004 section 5):**
- `target_arl`: **optional in Python signature** (default `None`), **required by Caliper validation**. Omitting raises `InvalidParameterError(kind="missing")`. **Same optional-with-required-semantics shape for `fit_bernoulli_cusum`** (BIN-133) — but see the Open Questions note below: ADR-011's hard-floor/advisory-band *numbers* do not transfer to this chart, even though the missing-value mechanism does. **`fit_bernoulli_cusum` additionally enforces a ceiling at `MAX_MEANINGFUL_ARL` (= 1,000,000)** — ADR-014 amendment Decision 9, a cost bound (not a verification boundary), checked before calibration. Since Amendment 2 the non-finite, `< 1.0` and `> MAX_MEANINGFUL_ARL` cases are **one** refusal (F5) reporting both bounds, each of which round-trips. There is **no** below-attainable refusal (Decision 12 supersedes Decision 3 item 2).
- `smoothing_param` (EWMA), `reference_value` (CUSUM): genuinely optional. `None` uses library default.
- `direction` (CUSUM): genuinely optional. `None` defaults to `"two_sided"`. **Same for `fit_bernoulli_cusum`'s `direction`** (BIN-133, ADR-012 amendment).
- `detect_rate_multiple` (Bernoulli CUSUM, BIN-133; not on `trunk`): genuinely optional. It sets the lower arm's design point `M·p_U` and the upper arm's `p_L/M` (ADR-014 Decision 19.1). It must be finite and above a per-fit computed lower bound that is always `> 1` (F16, corrigendum C2). `None` uses the library default, `2.0` — the shift lever, expressed as a multiple of the in-control failure rate rather than a sigma multiple, because a Bernoulli process has one parameter and its variance is determined entirely by the rate (ADR-012 §1). Not a new *pattern* on the fitting surface — it replaces `reference_value` for this chart family rather than adding a fourth kind of optional parameter.

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

**Five more, added 2026-09-23 (domain-modeller, BIN-133, following
ADR-012/013/014) — numbered 20-24.** Three (20-22) are the PRD's own
OQ-2/OQ-4/OQ-5, settled by ADR-014 and recorded here rather than left to
drift between the two documents. Two (23-24) were genuinely new, introduced
by ADR-014 itself: the upper arm's own false-alarm coverage under the GICP
substitution (Decision 6d, **still open**), and the exact joint two-armed
Markov-chain construction (§6c, **now settled** by the 2026-09-23
amendment's Decision 8 — see OQ-24).

**Three more, added 2026-09-23 (domain-modeller, BIN-133, following
ADR-014 amendment Decisions 7-11) — numbered 25-27.** All arise from
the amendment's "what this deliberately does not decide" section or from
context keys the amendment leaves unspecified. #25 and #26 were settled

**Amendment 2 (ADR-014 Decisions 12–19, ratified 2026-09-24): OQ-23 is now settled by Decision 19, OQ-20's attainability-floor refusal is superseded by Decision 12, and OQ-24/OQ-27 are updated. Nine questions, numbered 28–36, are added (domain-modeller, 2026-09-24).** One of them, #28, is left open deliberately by the ADR itself. The others are places where Amendment 2 leaves a case unstated, where it disagrees with itself, or where it disagrees with the code on PR #29. None is resolved here by invention.

**Amendment 2 corrigendum (C1–C11, ratified 2026-09-24): OQ-29 to OQ-36 are settled** (C1, C2, C3, C4, C5, C6, C7). OQ-28 stays open by design. **Two new questions, 37 and 38, record where the corrigendum conflicts with itself or with Decision 17.**
by the product owner the same day; #27 remains open.

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
| 20 | ~~Does ADR-011's three-tier `target_arl` policy (hard floor 100, advisory band `[100, 370)`, clean `≥370`) apply unchanged to the Bernoulli CUSUM, given its oracle is an exact derivation rather than a published table?~~ | — | — | PRD OQ-2 | **SETTLED, ADR-014 Decision 3.** Two narrower things transfer, the numbers do not. The coherence floor (`ARL₀ ≥ 1`, a definitional fact about any stopping time's expectation) transfers unchanged, no measurement needed. A *computed* attainability floor transfers *in kind* — `fit_bernoulli_cusum` must, exactly as `BIN-117` established for the continuous CUSUM, compute the smallest `ARL₀` its own lattice-quantised design can actually reach and refuse a `target_arl` below it, reporting the true floor so it round-trips. ADR-011's hard floor (100) and advisory band (`[100, 370)`) do **not** transfer as numbers — both exist to disclose a gap between an *approximation* and the *published table* that verifies it at a handful of points, and the Bernoulli CUSUM has no approximation to verify this way (ADR-012 §4/§5: exact, finite Markov chain, no discretisation error beyond the reference value's own lattice quantisation, which `achieved_arl` vs. `requested_arl` already discloses at every target). Whether lattice-quantisation error grows large enough at *low* `target_arl` to warrant its own advisory is explicitly left unmeasured — no advisory of that shape ships this release.  ⚠️ **Partly SUPERSEDED 2026-09-24 by ADR-014 Decision 12.** The sentence above requiring `fit_bernoulli_cusum` to "compute the smallest `ARL₀` its own lattice-quantised design can actually reach and refuse a `target_arl` below it" (Decision 3 item 2) **no longer holds**, and it was never built on PR #29. The lower arm's floor is exactly `1/p_U`, a property of any lower-arm Bernoulli CUSUM and not of the lattice. A target below it is fitted, reported exactly, and disclosed via `FittingAdvisory(kind="lower_arm_signals_on_first_failure")`. The rest of this answer stands: the coherence floor transfers, ADR-011's numbers do not, and there is no low-target lattice advisory. |
| 21 | ~~Does `Baseline`/`ScoringResult` need a declared score "kind" (continuous vs. binary), or does the binary fitting entry point simply interpret any baseline of pass/fail-valued observations as binary at fit time?~~ | — | — | PRD OQ-4 | **SETTLED, ADR-014 Decision 1.** Inferred, not declared. `Baseline`/`ScoringResult` gain no new field; `fit_bernoulli_cusum` validates that every `baseline.observations[i].score` is exactly `0.0` or `1.0` itself, at fit time, as the second step of its validation order (after `require_type(baseline, Baseline, ...)`, before `target_arl`/`detect_rate_multiple`/`direction` validation, before sufficiency, before the GICP design). Out of PRD scope for this release (Non-Goals is explicit); interacts with the still-open `BIN-61` (multiple scoring dimensions); and inference costs nothing extra — every `fit_*` already validates its baseline's content, and "is every score in `{0.0, 1.0}`" is the same shape of check on the same data. A `kind: Literal[...]` field and a separate `BinaryBaseline` wrapper type were both considered and rejected. |
| 22 | ~~What happens when a Phase II observation checked against a binary-fitted chart is not exactly a pass or fail value?~~ | — | — | PRD OQ-5 (contested at review — `bdd-scenario-writer`'s type-boundary exemption vs. `requirements-reviewer`'s counter-argument) | **SETTLED, ADR-014 Decision 2, on the merits of the contest rather than by inheriting either side.** Rejected via `InvalidObservationError` (`context["reason"] == "score_not_binary"`), no tolerance band — see the `Monitor` Object Map entry's new invariant 9 and the Error Contract Reference. Decided *for* `requirements-reviewer`'s reading: Caliper's `float` score type is not an accidental type-system gap (the shape the project's "type-boundary defects do not need a scenario" rule exempts) — it is ADR-006's own deliberate, ratified decision ("Score is unconstrained but must be finite"), applied uniformly, on purpose, to every chart including this one. A `0.73` reaching a Bernoulli-fitted `Monitor` is Caliper's own chosen design offering a value this chart's statistics cannot interpret, not Python letting a wrong type through an undesigned gap — so it does not qualify for the exemption. No tolerance band, deliberately: an epsilon around `{0.0, 1.0}` would itself be an invented, uncited constant. |
| 23 | ~~Does `p_U` (the Clopper–Pearson upper confidence bound) preserve the `1 − α` false-alarm coverage guarantee for the *upper* (improvement-detecting) arm, or does that direction need a *lower* confidence bound instead?~~ | — | — | ADR-013 §1 / ADR-014 §6d | **SETTLED by ADR-014 Decision 19 (ratified by the product owner 2026-09-24, Q7 and Q8).** It needed a lower bound. Designing the upper arm at `p_U` was measured to breach ADR-013 §3's ≤5% appetite by up to 20× (19.0), because that arm's ARL₀ falls as the true failure rate falls. The upper arm is now designed and calibrated at **`p_L`**, the Clopper–Pearson lower bound at the ratified α = 0.10. GICP is derived for it by coupling (19.1) and verified on a 55-cell grid extending below p₀ = 0.02 by two independent methods: worst appetite 1.727% exact, 2.32% Monte Carlo upper bound (19.3). The two-sided figure became the guaranteed floor `B` under calibration D (19.4). See `FittedBernoulliCUSUM`. |
| 24 | ~~What is the exact joint two-armed Markov-chain construction for the two-sided `FittedBernoulliCUSUM`'s `achieved_arl`/`expected_detection_arl`?~~ | — | — | ADR-014 §6c, settled by ADR-014 amendment Decision 8 | **SETTLED — ADR-014 amendment Decision 8 (ratified 2026-09-23).** Each arm's CUSUM accumulator lives on its own lattice with its own adaptive denominator (Decision 7). State `(i, j)` means the lower arm is at `i` units of `1/N_lower`, the upper at `j` units of `1/N_upper`. A single Bernoulli(*p*) draw transitions both; absorption when either arm strictly exceeds its own decision interval. State count `(h_lower_units + 1) × (h_upper_units + 1)`. The two arms share a single source of randomness, not a single lattice denominator — the exact property (`(I − Q)m = 1`) is preserved. The implementation on `feat/BIN-133/bernoulli-cusum` already has a working joint solve (pre-amendment, using an LCM-shared denominator); updating it to use independent per-arm lattices is the amendment's primary implementation task. One-sided configurations remain unaffected (ADR-012's existing single-arm solve). The fallback `calibration_method = "gicp_markov_chain_harmonic_combination"` still exists if the exact joint solve proves intractable, but is not expected to be needed given the measured state counts in Decision 8's table.  ⚠️ **Updated 2026-09-24 (Amendment 2).** The construction stands. Decision 13 requires the solvers to take each arm's integers directly, because PR #29 rebuilds them from floats (defect 2). The two-sided `achieved_arl` is now the **coupled three-outcome chain `B`** on this same state space, rather than this chain at the single rate `p_U` (Decision 19.4). `expected_detection_arl` and `expected_improvement_detection_arl` still use this single-rate chain, at `p̂·M` and `p̂/M`. The harmonic-combination fallback named above is **withdrawn** by corrigendum C5 (OQ-33). |
| 25 | ~~What are the exact `context` key names for the per-arm calibration search cap's achievable-ARL₀ report (Decision 10a)?~~ | — | — | ADR-014 amendment Decision 10a | **SETTLED by the product owner 2026-09-23: `context["max_attainable_arl"]`.** Mirrors `min_attainable_arl`, the key `fit_cusum` already reports for its computed attainability floor (BIN-117, `cusum_fitting.py`), so the floor and the cap read as a pair. The value is the achievable ARL₀ at `_MAX_DECISION_INTERVAL_UNITS` and round-trips as an accepted input. |
| 26 | ~~Should the per-arm adaptive lattice denominator have a floor (e.g. `max(scan_result, 100)`)?~~ | — | — | ADR-014 amendment "what this deliberately does not decide" | **SETTLED by the product owner 2026-09-23: no floor.** Decision 7's ε-centring invariant is what protects the design; `achieved_arl` is exact at any denominator (the solve describes the lattice chart itself), so a floor would add joint states against the 1,000,000 cap and buy nothing. ADR-013 §1's `N = 100` convergence finding concerned the fixed-lattice design it measured and does not bind the adaptive one; follow-up measurement at low `p₀` stays under OQ-27. |
| 27 | **Should lattice-quantisation error measurement (ADR-012 §3's table) be extended to the adaptive-N regime at low `p₀`?** ADR-012 §3 measured the `achieved_arl` vs `requested_arl` gap only at `p₀ ∈ {0.02, 0.05, 0.10, 0.20}` with `N = 100`. With the per-arm adaptive denominator, the residual at low `p₀` is a property of the adaptively chosen `N`, not of a fixed `N = 100`. The existing "report, don't chase" mechanism (`achieved_arl ≠ requested_arl`) handles this honestly regardless of the denominator, so no new measurement gates the fix — but extending the table is follow-up verification work. | Follow-up verification | Does not block shipping — the gap is disclosed honestly by the existing `achieved_arl`/`requested_arl` comparison | ADR-014 amendment "Consequence for ADR-013's GICP grid" (new) | **Open — noted as follow-up verification, not a gate.** ADR-013's GICP coverage guarantee itself holds for any `p₀ ∈ (0, 1)` because the proof is analytic (the Clopper-Pearson construction) — the grid does not need extending below `p₀ = 0.02` for the guarantee. What needs extending is lattice-quantisation error measurement under the adaptive denominator.  ⚠️ **Affected by Amendment 2, and still open.** (a) Decision 12 shows the largest `achieved`-vs-`requested` gap at low `p₀` is **not** lattice quantisation. It is the lower arm's structural floor `1/p_U` and the 2.8–3.3× gap above it, both measured independent of `N`. So any extended table must separate floor-and-gap from quantisation, or it will misattribute. (b) Decision 19.4 measured part of the question: for **two-sided at T = 370 under calibration D**, the median `B/T` is 1.001–1.08 across p₀ ∈ [0.002, 0.30] and m ∈ [100, 1000], with the adaptive `N`. One-sided arms and other targets remain unmeasured. |
| 28 | **Is there a power threshold below which an upper arm with no detection power should be refused, dropped or flagged?** When `p̂·T ≪ 1`, the improvement arm's ARL at its own target shift is about equal to, or above, its in-control ARL₀ (19.2: 398.1 vs 370.1 at m=1000 f=1). | product owner | Nothing. The number is disclosed by `expected_detection_arl` (`"upper"`) and `expected_improvement_detection_arl` (`"two_sided"`) | ADR-014 Amendment 2, "What Amendment 2 deliberately does not decide" | **Open by design, not a gap.** The ADR declines to decide because any threshold would be an invented number. It is consistent with ADR-013 §4's disclosure-over-floor ruling. Do not add an advisory or refusal for it without a new ruling. |
| 29 | ~~For a directly requested `direction="lower"` at f = 0, is `lattice_upper` `None`? 19.5 says `lattice_upper` is `None` "only when f = 0 forced `direction = "lower"`". But at f = 0, `p_L = 0` and the upper arm is undesignable whatever was requested, so a requested `"lower"` cannot carry an upper lattice either. Does that fit also carry `upper_arm_not_designable`? 19.2 attaches it only to the two-sided case.~~ | — | — | ADR-014 19.2 / 19.5 wording | **SETTLED by corrigendum C3 (ratified C-Q2, 2026-09-24).** `lattice_X is None` **exactly when `direction` does not check arm X**. So a directly requested `"lower"` at f = 0 has `lattice_upper is None`, as does every `"lower"` fit. It carries **no** `upper_arm_not_designable` advisory, which attaches only to a two-sided request forced to `"lower"`. This replaces 19.5's "only when f = 0 forced lower" and reverses §6b's both-arms rule. See `FittedBernoulliCUSUM`. |
| 30 | ~~What does `Monitor` do with a caller-supplied `FittedBernoulliCUSUM` whose `direction` checks the upper arm (`"upper"`/`"two_sided"`) but whose `lattice_upper is None`? No fit produces this shape (19.2), but `model_copy(update=...)` and `model_construct()` can. Decision 14.5 re-validates lattice *integers*, not a lattice's absence against `direction`.~~ | — | — | ADR-014 Decisions 14.5, 17, 19.2 | **SETTLED by corrigendum C4.** M2 is extended. When `direction` checks an arm whose lattice is `None`, `record()` raises `InvalidParameterError` before any state changes, with `parameter="artefact"`, `constraint`, `kind="invalid"`, `field="lattice_upper"`/`"lattice_lower"` and `provided_type="NoneType"`. It never leaks `AttributeError`/`TypeError`. |
| 31 | ~~In a one-sided fit, is the unchecked arm still calibrated, and can its search cap (F12) refuse a fit whose checked arm is fine? PR #29 calibrates both arms to the one-sided target whatever the direction, and 6b's "both arms present regardless of direction" requires an unchecked lattice. By extrapolation, not measurement: an f = 1 upper arm has `h ≈ T` units (19.2), so a `"lower"` fit at `T` near `MAX_MEANINGFUL_ARL` on such a baseline could hit the 999,999-unit cap on the arm it does not check.~~ | — | — | ADR-014 6b, Decisions 13.3, 16, 19.2 | **SETTLED by corrigendum C3 (ratified C-Q2).** A one-sided fit designs and calibrates **only** its checked arm, so the unchecked arm's cap cannot refuse it, and F12's `direction` names the checked arm. The feared case was also shown unreachable before the ruling. It was measured never to hit the cap up to m=3,000,000 f=1 at T=10⁶, and proved: an f ≥ 1 upper arm has `ARL(h) ≥ h + 1`, so `h ≤ T − 1 ≤ 999,999`. |
| 32 | ~~`detect_rate_multiple` in `(0, 1]` has no refusal row. F7 accepts any finite `M > 0`, but ADR-012's reference value needs `p₀ < p₁`, so `M ≤ 1` has no valid lower-arm design interval. Under Decision 19 the upper design point `p_L/M` also leaves `(0, 1)` when `M < p_L`. Reproduced on PR #29 at `5b7e3a1` (m=200, f=20, T=370): `M=1.0` leaks `ZeroDivisionError` and `M=0.5` leaks `ValueError` from the public entry point.~~ | — | — | ADR-014 Decision 17 row F7; ADR-012 §1 | **SETTLED by corrigendum C2 (option A, ratified C-Q1).** `M ≤ 1` and `M` below the per-fit resolvable bound are refused by new row **F16**, with `reason` `no_shift_to_detect`, `shift_below_numerical_resolution` or `no_valid_multiple`, and a computed `min_value` (inclusive) that round-trips by construction. F7 is narrowed to non-finite. Decision 7's linear scan, which hung at `M = 1.0000001`, is replaced by the O(log N) continued-fraction finder, with identical output. Fixed bounds (1.25, or 1 + 10⁻⁶) were rejected. (See OQ-37 for a remaining wording conflict with C3.) |
| 33 | ~~Does `calibration_method` change now that the two-sided `achieved_arl` is the guaranteed floor `B` under calibration D? And is §6c's `"gicp_markov_chain_harmonic_combination"` fallback withdrawn, given D bisects on the exact `B`?~~ | — | — | ADR-014 §6c vs Decision 19.4 | **SETTLED by corrigendum C5.** `"gicp_markov_chain"` for one-sided fits; `"gicp_markov_chain_coupled_bound"` for two-sided fits, whose `achieved_arl` is `B` under calibration D. §6c's harmonic-combination fallback is withdrawn. |
| 34 | ~~How is BIN-142's "every float field finite" backstop enforced for `expected_improvement_detection_arl: float \| None` and for the computed float properties? PR #29's `FittedArtefactBase.every_float_field_must_be_finite` inspects only `model_fields` annotated exactly `float`.~~ | — | — | BIN-142; ADR-014 Decisions 14.3, 19.6 | **SETTLED by corrigendum C7.** The BIN-142 validator covers fields annotated `float` **and** `float \| None`, skipping `None`. The computed floats need no check, being `units/denominator` over validated ints. Verification item 21. |
| 35 | ~~`provided` vs `provided_type`. Decision 17's F8 lists `provided` for a `direction` that is "not an exact `str`", and M2 lists `provided` for a non-exact lattice integer. But BIN-143's `require_exact_str` deliberately reports `provided_type`, not the value (a hostile object's `repr` can raise inside the error path), and M3 inherits exactly that. ADR-002 §3 requires `provided` whenever `kind == "invalid"`.~~ | — | — | ADR-014 Decision 17; ADR-002 §3; BIN-143 | **SETTLED by corrigendum C6.** A type failure reports `provided_type`, never the value; a value failure on an exact-typed value reports `provided`. F8 splits by path, M2/C4 split by case, and M3 uses `provided_type`. This is the documented exception to ADR-002 §3, and the registry asserts exactly one of the two per invalid-kind row. (See OQ-38: F1, F4 and F6 as listed do not follow the rule.) |
| 36 | ~~Decision 18's f = 0 verification expectations predate Decision 19.2 and now contradict it. Item 5 expects m=5,000 f=0 `"two_sided"` at T=370 to fit at 552.2; under 19.2 it returns `direction="lower"` at `1/p_U` ≈ 2,172. Item 3 expects `upper` at 370 = 370.5273, `two_sided` at 370 = 735.9166 with 1,476 joint states, and `two_sided` at 10⁶ to raise F13, all at m=300,000 f=0; under 19.2 `"upper"` raises F15 and `"two_sided"` has no joint chain. Item 8's `p_U/M` = 314.1 at m=1,000 f=0 is withdrawn. Item 12's F13 budget case is at f=0, where F13 cannot fire. Decision 16's reachability measurement (m=3,000,000 f=0 T=10⁶ two-sided) likewise no longer describes a two-sided fit.~~ | — | — | ADR-014 Decisions 16, 18 vs 19.2 | **SETTLED by corrigendum C1.** Decision 18's f = 0 cells are re-based and re-measured under the ratified behaviour. m=5,000 f=0 two-sided returns `"lower"` at 2,171.9724 with both advisories. The large-baseline item moves to f=1 and f=30 at m=300,000. Item 8's upper figures become 72.1128 / 157.6429 / 398.1379. Item 5's m=300 f=3 floored cell becomes T=40 (T=50 is kept as the gap case, advisory absent). Item 12's refusal-budget case moves to f ≥ 1, and its budget is replaced by C11's. Decision 16's reachability is re-measured at f ≥ 1 (m=300,000 f=1 T=10⁶). |
| 37 | **Over which arms is F16's `min_value` computed?** C2 defines it as the smallest `M` "for which **both arms'** design is constructible and verified". But under C3 a one-sided fit designs only its checked arm, and at f = 0 the upper arm is never designable. Read literally, a `"lower"` fit, or any f = 0 fit, either could never compute the bound, or would be bounded by an arm it does not build. | system-architect | F16's `min_value` for one-sided and f = 0 fits; verification item 20 | Corrigendum C2 vs C3 | **Open.** The natural reading is "every arm the fit designs", but it is not the ratified wording, so it is not adopted here. |
| 38 | **Do F1, F4 and F6 report `provided` or `provided_type`?** C6 says its rule "applies to every row in Decision 17": a type failure reports `provided_type`, never the value. But F1 (`baseline` not a `Baseline`), F4 (`target_arl` not a real number) and F6 (`detect_rate_multiple` not a real number) are type failures that Decision 17 lists with `provided`. On PR #29, `require_type` and `require_real_number` do emit `provided` (the value). C6 enumerates only F8, M2, C4 and M3. | system-architect | Registry key sets for F1/F4/F6 (verification item 23); the continuous charts share these guards | Corrigendum C6 vs Decision 17 F1/F4/F6 | **Open.** The table keeps Decision 17's `provided` with a pointer here. Changing the shared guards would also change `fit_ewma`/`fit_cusum`/`fit_shewhart`'s contracts, so this is not the model's call. |

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
- [x] `FittedBernoulliCUSUM` given full Chart-Specific Artefact treatment, explicitly modelled as **not** a `FittedControlLimits` conformer — the first such case — satisfying `HasProvenance` only (ADR-014 §6a; this pass, BIN-133)
- [x] `HasProvenance` documented for the first time in this file (previously only in ADR-004's amendment and `src/`), since `FittedBernoulliCUSUM` is the first concrete artefact that needs it (this pass)
- [x] `Monitor`'s Object Map entry updated for the widened accepted-artefact-type union, the new third `record()` precondition (Decision 2 — binary score check), and the fourth `_check` dispatch branch — none implemented yet, all flagged as domain-modelled-not-implemented (this pass)
- [x] Error Contract Reference updated: `InvalidObservationError` gains `reason == "score_not_binary"`; `InvalidParameterError` gains `parameter == "baseline"`/`reason == "score_not_binary"` and `parameter == "detect_rate_multiple"` (both the round-trippable case, computed from `p_U` not `p̂`, and the non-round-trippable all-failed-baseline case); `DegenerateBaselineError`'s row notes `fit_bernoulli_cusum` never raises it (this pass)
- [x] Dual-Spread Distinction section narrowed from "All Charts" to "All *Continuous* Charts", with an explicit note that `FittedBernoulliCUSUM` has no sigma-based quantity at all (ADR-014 §6a; this pass)
- [x] No numerical constants invented for this pass — `detect_rate_multiple`'s default (`2.0`), `alpha` (`0.10`), and every ARL figure are cited to ADR-012/013, never re-derived or guessed here
- [x] Two things ADR-014 originally recorded as open, modelled as Open Questions (#23, #24): the upper arm's own false-alarm coverage under the `p_U` substitution (still open, #23), and the exact joint two-armed Markov-chain solve (settled by the 2026-09-23 amendment's Decision 8, #24 now SETTLED) — neither invented, both correctly tracked (original pass; #24 updated this pass)
- [x] PRD OQ-2/OQ-4/OQ-5 reconciled into this file's own numbered Open Questions table (20-22), settled by ADR-014, rather than left to drift between the PRD and this canonical document (this pass)
- [x] All 17 scenarios across `bernoulli-cusum-control-limit-fitting.feature` checked against this model by reading the feature file directly (not a summary) — every `Given`/`When`/`Then` maps onto a field, error condition, or default already modelled above; no scenario names a field, formula, or numeric literal this model would need to contradict (this pass)
- [x] Existing model searched before adding anything new (`src/drift_caliper/`: no `bernoulli`/`clopper_pearson`/`gicp` module exists; `HasProvenance`, `FittingAdvisory`, `FittedArtefactBase`, `Monitor` all read directly rather than assumed) — no duplication of an existing aggregate, port, or value object (this pass)
- [x] ADR-014 amendment Decisions 7-11 (lattice correctness defect and cost-bounding, ratified 2026-09-23) reflected: lattice invariant (Decision 7 — per-arm adaptive denominator with centring tolerance), independent per-arm lattices in the joint solve (Decision 8), `target_arl` ceiling at `MAX_MEANINGFUL_ARL` (Decision 9), search-cap enforcement (Decision 10a), joint state count cap at 1,000,000 (Decision 10b) — all with round-trip guarantees stated as invariants (this pass, following the amendment)
- [x] OQ-24 marked SETTLED by Decision 8 — the exact joint two-armed construction is decided (independent per-arm lattices, state `(i, j)`, single Bernoulli draw), not struck through until settled, consistent with the existing settled-OQ convention (this pass)
- [x] Three new Open Questions (25-27) added for items the amendment explicitly leaves open or unspecified: search-cap context key names (10a), adaptive denominator floor (amendment's "deliberately does not decide"), lattice-quantisation error measurement at low `p₀` under adaptive N (follow-up verification) — none invented, all flagged (this pass)
- [x] No numerical constants invented for this pass — `ε = 0.25`, `_MAX_JOINT_STATES = 1,000,000`, `MAX_MEANINGFUL_ARL`, and all measured state counts are cited to the amendment, never re-derived or guessed here (this pass)
- [x] Implementation branch checked against the amendment: `feat/BIN-133/bernoulli-cusum` uses fixed `N = 100`, LCM-shared denominator, silent search-cap return, no `MAX_MEANINGFUL_ARL`, no `_MAX_JOINT_STATES` — all pre-amendment; discrepancies noted in the model as "not yet implemented" rather than assumed to match (this pass) *(Historical, true when written. By 2026-09-24 PR #29 at `5b7e3a1` had built Decisions 7–10; see the Amendment 2 items below.)*
- [x] Error Contract Reference updated with three new `InvalidParameterError` cases: `target_arl` ceiling, search cap, joint state cap — each with the exact `context` keys the amendment specifies, the one key it left unnamed settled as `max_attainable_arl` (OQ-25) (this pass)
- [x] ADR-014 Amendment 2 (Decisions 12–19, ratified 2026-09-24) read in full, alongside Amendment 1 and the original ADR, before editing (this pass)
- [x] `FittedBernoulliCUSUM` field table brought into line with Amendment 2 (this pass):
  - the new `BernoulliArmLattice` value object, carried as `lattice_lower`/`lattice_upper`, is the single source of truth, and the four floats are computed properties that keep their meaning;
  - new fields `p_l` and `expected_improvement_detection_arl` (non-`None` exactly for two-sided);
  - `achieved_arl` stated per direction, with the two-sided guaranteed floor `B`'s guarantee and non-guarantees made explicit;
  - `expected_detection_arl` made direction-aware (Decision 15);
  - the f = 0 shape (`direction="lower"`, `lattice_upper=None`, optional upper fields, `upper_arm_not_designable`)
- [x] `BernoulliArmLattice` given full Value Object Inventory treatment: bounds, exact-`int` rule, derived floats, export location, `__bool__` and re-validation at use (this pass)
- [x] Design invariants recorded (this pass):
  - each arm is designed on its conservative side (lower at `p_U`, upper at `p_L`, α = 0.10);
  - integer lattices end to end, with no float reconstruction;
  - `Monitor` steps in integer units and re-validates lattices (invariant 10);
  - the raising ARL postcondition (F14);
  - the lower-arm floor `1/p_U`, fitted and disclosed
- [x] Decision 3 item 2's refusal **marked superseded, not deleted**: OQ-20 is annotated, the `DegenerateBaselineError` "never raises" line is struck through with the replacement stated, and the struck `p_U`-for-both-arms paragraph is kept (this pass)
- [x] Error Contract Reference carries Decision 17's complete table (F1–F15, M1–M3) with every `context` key exactly as the ADR names it, including F14 `arl_not_computable` and F15 `no_baseline_failures`. The two keys the ADR leaves ambiguous (`provided`/`provided_type`; the `M ≤ 1` row) are recorded as OQ-35 and OQ-32, not invented (this pass)
- [x] Glossary covers every term Amendment 2 introduces: `p_L`, guaranteed floor `B`, calibration D, equal split, `expected_improvement_detection_arl`, `BernoulliArmLattice`, lattice units, lower-arm floor, and upper arm not designable. GICP, `p_U`, `expected_detection_arl`, Achieved ARL, Direction and Accumulator are updated (this pass)
- [x] OQ-23 marked SETTLED by Decision 19 (struck through, with reference). OQ-24 and OQ-27 updated for Amendment 2's effect. OQ-28 (power threshold) is recorded as open **by design**. OQ-29–36 are recorded for cases the amendment leaves unstated or contradicts. Nothing Amendment 2 settles was re-opened (this pass)
- [x] Implementation status checked against PR #29 at `5b7e3a1` by reading `bernoulli_cusum_fitting.py`, `fitted_bernoulli_cusum.py`, `fitting_advisory.py`, `fitted_artefact_base.py`, `monitor.py` and `parameter_guards.py`, not inferred from ADR text. "Not yet implemented" markers were replaced with a per-decision status table, and every Amendment 2 decision is marked not built (this pass)
- [x] Feature file re-checked against Amendment 2 (this pass). The default-direction scenario uses a mixed baseline (f ≥ 1), so it still sees `"two_sided"`. The zero-failure scenario (m=105) now gets `direction="lower"`, which it does not assert against. Its "matches their request to within the chart's stated tolerance" step asserts only field types, so it binds but is vacuous. No `.feature` change is required by the model
- [x] No numerical constants invented for this pass. Every figure (`1/p_U`, 2.8–3.3×, 999,999, 1.727%/2.32%, 1.781%, 7.88%, 370.4/1,809.8, 580.9/370.3, 3.4 million, 44.8 s/≤ 5 s) is cited to ADR-014 Amendment 2 (this pass)
- [x] ADR-014 Amendment 2 corrigendum (C1–C11, ratified 2026-09-24) read in full and reflected, with every item applied (corrigendum pass):
  - C1: re-based f = 0 figures; upper `expected_detection_arl` 72.1128, not 32.8.
  - C2: F16, per-fit `M` bound, F7 narrowed, continued-fraction finder.
  - C3: only-checked-arms; §6b's "both arms" reversal marked superseded.
  - C4: missing-lattice M2.
  - C5: `calibration_method` strings; harmonic fallback withdrawn.
  - C6: `provided`/`provided_type`.
  - C7: `float | None` backstop.
  - C8: two-sided f = 0 fallback unreachable.
  - C9: N claim withdrawn.
  - C10: three F14 `figure` values.
  - C11: `floor(T_ES)` with guard; ≤ 30 s overhead budget.
- [x] Error Contract Reference table updated to the corrigendum's final rows (F1–F16, M1–M3) (corrigendum pass)
- [x] OQ-29–36 marked SETTLED (struck through, with corrigendum reference). OQ-28 left open by design. Two genuine new conflicts recorded (OQ-37: C2's "both arms" vs C3; OQ-38: C6's universal rule vs F1/F4/F6 as listed and built), not resolved by invention (corrigendum pass)
- [x] Glossary: `T_ES`/equal-split bound and the continued-fraction lattice finder added; Equal split, `BernoulliArmLattice`, `detect_rate_multiple` and Upper arm not designable updated (corrigendum pass)
- [x] Implementation status re-stated: every corrigendum item is **not built** on PR #29 (corrigendum pass)

---

## Changelog

- 2026-09-24 (domain-modeller, BIN-133, following the ADR-014 **Amendment 2 corrigendum** C1–C11, ratified 2026-09-24; working tree only, awaiting product-owner review):
  - **`FittedBernoulliCUSUM`:**
    - `lattice_lower` and `lattice_upper` are both optional, present exactly when `direction` checks that arm (C3, reversing §6b). The "both arms regardless of direction" paragraph is struck through and superseded. The lower-arm computed floats become `float | None`.
    - `calibration_method` is `"gicp_markov_chain"` / `"gicp_markov_chain_coupled_bound"`, and the harmonic fallback is withdrawn (C5).
    - The `detect_rate_multiple` legal range is F7 plus F16 with a per-fit computed bound (C2 option A).
    - Decision 7's linear scan is replaced by the continued-fraction finder (C2).
    - `max_two_sided_target_arl` is `floor(T_ES)`, conservative and guarded; the refusal budget is ≤ 30 s overhead (C11).
    - The finite-float backstop covers `float | None` (C7).
    - The upper `expected_detection_arl` example is corrected to 72.1128 (C1), and the two-sided f = 0 fallback is unreachable (C8).
    - A requested `"lower"` at f = 0 has no upper lattice and no `upper_arm_not_designable` (C3).
    - A corrigendum row is added to the status table.
  - **`BernoulliArmLattice`:** presence rule (C3) and the withdrawn N claim (C9).
  - **`Monitor` invariant 10:** only checked arms exist; a missing lattice on a checking direction raises the extended M2 (C4); M2 carries `provided_type`/`provided` per C6.
  - **Refusal contract:** new F16; F7 narrowed; F8/M2/M3 carry `provided_type`/`provided` per C6; F12 `direction` names the checked arm; F13 reports `floor(T_ES)`; F14 lists three `figure` values (C10).
  - **Glossary:** two terms added, four updated.
  - **Library Operations:** updated.
  - **Open Questions:** OQ-24 updated. OQ-29–36 SETTLED (C3, C4, C3, C2, C5, C7, C6, C1). New OQ-37 (F16 bound "both arms" vs C3) and OQ-38 (C6's rule vs F1/F4/F6).
- 2026-09-24 (domain-modeller, BIN-133, following ADR-014 Amendment 2, Decisions 12–19, ratified in full 2026-09-24, working tree only, awaiting product-owner review):
  - **`FittedBernoulliCUSUM` rewritten to Amendment 2.**
    - Added `lattice_lower`/`lattice_upper: BernoulliArmLattice` as the stored, authoritative chart. The four `reference_value_*`/`decision_interval_*` floats become computed properties with unchanged meaning (Decision 14).
    - Added `p_l` and `expected_improvement_detection_arl` (Decision 19.5/19.6).
    - `achieved_arl` is now defined per direction. Two-sided it is the coupled-chain guaranteed floor `B` under calibration D, with what it guarantees and what it does not stated explicitly (19.4).
    - `expected_detection_arl` is now direction-aware: `"upper"` is evaluated at `p̂/M` (Decision 15), and the f = 0 upper fallback is withdrawn (19.2).
    - Added the f = 0 shape: a two-sided request returns `"lower"` with `lattice_upper=None` and `upper_arm_not_designable`, and `"upper"` is refused (19.2).
    - Added the upper-arm-at-`p_L` design (19.1, superseding 6d, whose paragraph is struck through and kept).
    - Added the lower-arm floor `1/p_U` with fit-and-disclose (Decision 12, **replacing Decision 3 item 2's refusal**), integer lattices end to end with a raising postcondition (Decision 13), and the 999,999-unit cap with two-sided cap hits routed to F13 (Decisions 13.3, 16).
    - Corrected Amendment 1's "one-sided ≤ ~40,000 states" and "always succeeds" claims.
    - Added a per-decision implementation-status table checked against PR #29 at `5b7e3a1`.
  - **New `BernoulliArmLattice` value object** in the Value Object Inventory.
  - **`Monitor`:** new invariant 10 covers integer stepping, lattice re-validation (M2) and the absent upper arm. Structure, operations and markers are updated.
  - **Error Contract Reference:** the Bernoulli refusal prose is replaced by Decision 17's complete F1–F15/M1–M3 table. `DegenerateBaselineError` gains `arl_not_computable` (F14), and its "never raises" line is struck through as superseded.
  - **Glossary:** nine terms added and six updated.
  - **Library Operations:** updated.
  - **Open Questions:**
    - OQ-23 SETTLED by Decision 19.
    - OQ-20 annotated: its attainability-floor refusal is superseded by Decision 12.
    - OQ-24 and OQ-27 updated.
    - OQ-28–36 added: the power threshold (open by design), requested-`"lower"` at f = 0, `Monitor` with an absent upper lattice, unchecked-arm calibration and F12, `M ≤ 1` leaking non-`CaliperError`s on PR #29 (reproduced), `calibration_method` under B/D, the BIN-142 backstop for optional or computed floats, `provided` vs `provided_type`, and Decision 18's f = 0 expectations contradicting 19.2.
- 2026-09-23 (domain-modeller, BIN-133, following ADR-014 amendment 2026-09-23 — lattice correctness defect and cost-bounding): Updated `FittedBernoulliCUSUM`'s calibration description to specify independent per-arm lattices in the joint two-sided solve (Decision 8), replacing the "unverified numerical work" language. Added the **lattice quantisation invariant** — per-arm adaptive denominator with centring tolerance `ε = 0.25`, quantised `r_q` strictly inside `(p₀, p₁)` and within `ε·(p₁−p₀)` of unquantised `r`, both arms (Decision 7). Recorded the correctness defect: fixed `N = 100` violates the `(p₀, p₁)` interval invariant at low failure rates (`m ≥ 300, f = 0`); the implementation on `feat/BIN-133/bernoulli-cusum` predates the amendment and requires updating. Added three **resource-bound refusals** to the Error Contract Reference and Library Operations: `target_arl` ceiling at `MAX_MEANINGFUL_ARL` (Decision 9, `context["max_value"]`, `context["max_inclusive"]`); per-arm search cap raising with achievable ARL₀ (Decision 10a); joint two-sided state count cap at 1,000,000 reporting `context["max_two_sided_target_arl"]` (Decision 10b, ratified by the product owner). All reported bounds round-trip as accepted inputs (BIN-122). Marked **OQ-24 as SETTLED** by Decision 8 — the exact joint two-armed construction is decided: independent per-arm lattices, state `(i, j)`, single Bernoulli draw. Added three new Open Questions: OQ-25 (search-cap error's exact context key names, unspecified by Decision 10a), OQ-26 (whether the adaptive denominator needs a floor to preserve ADR-013's convergence property, explicitly left open by the amendment), OQ-27 (lattice-quantisation error measurement at low `p₀` under the adaptive denominator — follow-up verification, not a gate). Updated the Validation Checklist. Product owner then settled OQ-25 (`max_attainable_arl`) and OQ-26 (no denominator floor) the same day; OQ-27 stays open.
- 2026-09-23 (domain-modeller, BIN-133, following ADR-012/013/014 — domain-modelled, not yet implemented): Added `FittedBernoulliCUSUM` as a new Chart-Specific Artefact — the first fitted artefact that does **not** satisfy `FittedControlLimits`, satisfying only the narrower `HasProvenance` protocol (ADR-014 §6a), documented in this file for the first time. Added a new `fit_bernoulli_cusum` row to Library Operations. Narrowed the Dual-Spread Distinction section from "All Charts" to "All *Continuous* Charts" — `FittedBernoulliCUSUM` has no sigma-based quantity at all. Extended `Monitor`'s Object Map entry: the accepted-artefact-type union widens (`FittedControlLimits | FittedBernoulliCUSUM`), a ninth invariant and a third `record()` precondition are added (a Phase II observation against a `FittedBernoulliCUSUM` must be exactly `0.0`/`1.0`, else `InvalidObservationError` with `context["reason"] == "score_not_binary"` — ADR-014 Decision 2), and the constructor-validation note is updated from three concrete types to four. Updated the Error Contract Reference: `InvalidObservationError` gains the `score_not_binary` reason; `InvalidParameterError` gains two new raised-by cases on `fit_bernoulli_cusum` (`baseline`/`score_not_binary`, and `detect_rate_multiple` — both the round-trippable not-a-valid-probability case, computed from `p_U` not `p̂` per ADR-013 §6b/BIN-122, and the non-round-trippable all-failed-baseline case); `DegenerateBaselineError`'s row notes that `fit_bernoulli_cusum` never raises it (ADR-013 §5 folds both former degenerate cases elsewhere). Added six new Ubiquitous Language Glossary entries (Bernoulli CUSUM, `detect_rate_multiple`, Guaranteed In-Control Performance, `p_U`, `alpha`, `expected_detection_arl`) and one more (`HasProvenance`) documenting a mechanism that existed in `src/`/ADR-004 but had never been written up here. Added five new Open Questions (20-22: the PRD's own OQ-2/OQ-4/OQ-5, all settled by ADR-014 and reconciled into this file rather than left to drift; 23-24: genuinely new, introduced — not closed — by ADR-014 itself, modelled as open per the instruction not to invent numbers or resolve what no ADR has decided: the upper arm's own false-alarm coverage under the `p_U` substitution, ADR-014 §6d; and the exact joint two-armed Markov-chain solve the two-sided artefact's `achieved_arl`/`expected_detection_arl` depend on, ADR-014 §6c). Verified all 17 scenarios in `tests/bdd/features/baseline/bernoulli-cusum-control-limit-fitting.feature` (branch `feat/BIN-133/bernoulli-cusum`) bind against this model by reading the feature file directly — no scenario names a field, formula, or numeric literal this model would need to contradict. Searched `src/drift_caliper/` directly before writing: no `bernoulli`/`clopper_pearson`/`gicp` module exists, confirming nothing here duplicates an existing type. Left deliberately unresolved, per instruction: the two items ADR-014 itself records as open (Open Questions 23-24, above) — no number invented for either.
- 2026-09-15 (BIN-143): **`direction` is narrowed to an exact `str` before any membership test**, at *both* sites that perform one. `x in frozenset(...)` calls `x.__hash__()` before comparing anything, so testing a caller-supplied value first hands control to the caller: a list or dict leaked `TypeError: unhashable type`, and a `str` subclass with a raising `__hash__` leaked whatever it chose. ⚠️ **The audit this ticket mandated found the second site**, `Monitor._check_cusum`, which membership-tests `artefact.direction` — **reachable despite `Monitor.__init__`'s `isinstance` narrowing and the `str` field annotation**, because Pydantic coerces a subclass only during *validation* and `model_copy(update=...)`/`model_construct()` skip validation by design. 🚨 **A Pydantic field annotation is a validation-time guarantee, not a storage-time one** — anything reading a field off a caller-supplied model is reading `Any` in practice. The fix reuses BIN-139's shape (`isinstance` plus normalisation via the unbound `str.__str__`) in a shared `require_exact_str` guard; ⚠️ **not `type(x) is str`**, which closes every leak and refuses every legitimate subclass with it (the BIN-123 class) — four of the five new tests fail that version deliberately. The guard reports `context["provided_type"]` rather than the value, because `repr()` on a hostile object can itself raise inside the error path (BIN-118/BIN-120); `parameter`, `constraint` and `kind` are unchanged, so the required-key contract above still holds. A third site — `set(scores)` in `_has_zero_variance`, which hashes every caller-supplied score — is a different parameter with a different error contract and is **tracked as BIN-149 via strict-xfail `known_leak` registry entries** rather than fixed in passing.

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
