# ADR-009: Phase II `Monitor` construct, recording semantics, and the in-memory observation store

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** system-architect (combined pass, BIN-69 + BIN-72), ratified by product owner
**Refs:** BIN-69, BIN-72, BIN-112, ADR-001, ADR-002, ADR-004, ADR-006, ADR-008

## Context

Both `requirements-reviewer` runs (BIN-69, 2026-09-10; BIN-72, 2026-09-10) independently
recommended resolving these two stories' open questions in one architecture pass, not two.
BIN-69's own review (M1) found all nine of its scenarios reduce to a single unresolved
question -- where Phase II recording happens and where recursive chart state lives -- and
BIN-72's review (Cross-Story Judgement) confirmed BIN-72's architecture is coupled to BIN-69's
at essentially every point that matters: BIN-72's A2 cannot be designed without knowing where
BIN-69's recording operation lives; BIN-72's OQ-1 (stored-entry shape) is explicitly coupled to
BIN-69's OQ-2 (result shape). Treating these as four to seven independent decisions would
produce two homes for what is structurally one concept -- an object that performs a chart-type-
specific comparison, carries whatever state that comparison needs between calls, and (per
BIN-72) makes what it has seen reviewable. This ADR resolves both stories' open questions
together, mirroring how ADR-006 closed BIN-59's OQ-2/OQ-4/OQ-5/OQ-6 in one pass.

### What already exists and must not be contradicted

- **No `Monitor` construct exists in `docs/domain-model.md`.** ADR-006 explicitly declined to
  invent one when it resolved a *different* question (criteria attachment), on the grounds that
  inventing one to answer an unrelated question would design beyond what that story asked. It
  left the question of whether a future story is the legitimate trigger open -- see ADR-006 §2:
  "This story may be the actual, legitimate trigger for introducing such a construct -- that
  determination is domain-modeller's to make, not this PRD's" (echoed verbatim in the domain
  model).
- **The fitted artefact is immutable and that is load-bearing** (ADR-004; BIN-108 fixed a real
  defect from a sequence field that was not actually frozen). Phase II accumulator state
  (EWMA's smoothed statistic; CUSUM's running $S_{hi}$/$S_{lo}$) cannot live on the artefact.
  The PRD's own scenario wording ("recorded... against this artefact") is ordinary English for
  "using this artefact's calibration," not a claim the artefact holds state --
  `bdd-scenario-writer` flagged this explicitly and it is not read as one here.
- **Detection boundaries are chart-specific, not shared** (ADR-004 §3). EWMA/Shewhart compare an
  observation-scale statistic against UCL/LCL; CUSUM compares an accumulating statistic against
  a decision interval $h$ that is not on the observation scale. ADR-004 names BIN-69 directly:
  "Must narrow to the chart-specific type to access detection boundaries for the observation
  check... the comparison operation is chart-specific... No single comparison operation covers
  all three."
- **Signals are not errors** (ratified 2026-09-08, restated in both PRDs' BR-7). An
  out-of-control determination is a normal return value.
- **Provenance mismatch raises unconditionally, no override** (`compare_provenance()`, BIN-68,
  merged). This ADR reuses that mechanism; it does not redefine it.
- **Truthiness is forbidden unless an explicit field carries the yes/no meaning** (BIN-110). Any
  new result type here must declare an explicit boolean field.
- **`Baseline` already has `__len__`/`__iter__`/`__repr__`.** A second, structurally identical
  collection type is a discoverability failure this project has named as a first-class DX
  concern (`BIN-72` review, M3; CLAUDE.md "Developer experience is a first-class constraint").

### Sentry context

Not applicable. Caliper is a library with no runtime to monitor.

## Decision

### 1. A new `Monitor` construct is introduced -- this is its legitimate trigger

**`Monitor` is a new domain type, in a new bounded context (`Monitoring`, E3), constructed from
one fitted control-limit artefact:**

```python
monitor = caliper.Monitor(fitted_artefact)
```

`Monitor` is the answer to BIN-69 OQ-1 (where the recording-and-checking operation lives) and
BIN-69 A1 (where EWMA/CUSUM accumulated state lives). It is **not** a generalisation invented
for its own sake -- it is instantiated by exactly the pressure ADR-006 predicted: recursive
chart state has nowhere else immutability-safe to live, and BIN-69's own PRD names this as its
central, HIGH-load-bearing, HIGH-feasibility-risk open question, not a nice-to-have.

**Why a stateful object and not a free function with explicit state threading.** The
alternative -- `check_ewma(artefact, prior_state, observation) -> (new_state, result)`, with
the engineer holding and re-passing `prior_state` on every call -- was seriously considered
(see Alternatives). It works, but only by making the engineer personally responsible for never
mixing up which `prior_state` belongs to which artefact, across however many production call
sites their agent has. `Monitor` holds that association once, at construction, and cannot be
handed the wrong state because there is no separate state parameter to hand it.

**Why not a method on the fitted artefact.** Rejected outright: the artefact is immutable by
ADR-004/BIN-108 and shared -- multiple `Monitor`s could legitimately watch the same artefact
(e.g. two different production deployments checking against one shared Phase I baseline).
Putting mutable accumulator state on a value the whole library treats as an immutable historical
record would break an invariant three merged feature files already test.

**Internal shape (implementation detail, not fixed by this ADR):** `Monitor` holds the fitted
artefact reference, private chart-specific accumulator state (nothing for Shewhart -- it is
memoryless by BR-4; the EWMA smoothed statistic for EWMA; the two one-sided running sums for
CUSUM), and delegates the actual comparison to the existing SPC engine machinery behind
`SPCPort` (ADR-001), narrowing to the concrete artefact type exactly as ADR-004 §3 anticipated
for BIN-69's consumer. The exact field names and per-chart representation are
`domain-modeller`'s scope, not this ADR's.

### 2. `Monitor.record()` checks provenance internally (resolves BIN-69 A2)

```python
def record(self, observation: ScoringResult) -> MonitoringResult: ...
```

`record()` calls the existing `compare_provenance()` (BIN-68, merged) internally, before any
chart-specific comparison runs. A mismatch raises `ProvenanceMismatchError` exactly as BIN-68
already defines it -- this ADR does not redefine that error or its `context["mismatches"]`
shape.

**Why internal, not left to the engineer to call first.** This is the same asymmetry every
other "errors raise, the caller decides" decision in this project already resolved: an internal
check means a forgetful engineer *cannot* silently record against mismatched provenance,
because there is no code path that skips it. An external, engineer-called check reintroduces
exactly the silent-invalidation failure mode BIN-68 exists to prevent, at the one point
(recording) where it matters most. The cost -- a small amount of coupling between `Monitor` and
`compare_provenance()` -- is negligible next to that.

### 3. Recording an invalid observation reuses `InvalidObservationError` (resolves BIN-69 OQ-4)

No new exception category. `Monitor.record()` raises `InvalidObservationError` -- the same type
`Baseline.record()` already raises (BIN-63) -- for an incomplete or malformed input. The failure
mode is identical (input is not a complete `ScoringResult`) and the recovery action is identical
(fix your input) to the Phase I case; inventing a tenth category for the Phase II instance of the
same problem would repeat the mistake ADR-002 §"Why `invalid_parameter` subsumes missing
parameters" already reasoned through and rejected for a structurally identical case. ADR-002's
taxonomy is semi-open, but nothing here needs the extension mechanism.

### 4. `MonitoringResult`: an explicit-field result, never raised (resolves BIN-69 OQ-2)

```python
class MonitoringResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_in_control: bool          # explicit field -- BIN-110's truthiness rule
    observation: ScoringResult   # the observation just recorded
    chart_type: str              # which chart produced this determination
```

**Naming (`is_in_control`, not `is_out_of_control` or `signalled`):** matches
`SufficiencyResult.is_sufficient`'s convention -- the field name states the *desired* state
positively, so `if result.is_in_control:` reads the way `if baseline.check_sufficiency():`
would have read had that not been the exact anti-pattern BIN-110 fixed. `ScoringResult` and the
three `Fitted*` artefacts deliberately raise `TypeError` from `__bool__` because they have no
natural yes/no meaning; `MonitoringResult` does have one, so it declares it explicitly rather
than leaning on `__bool__` at all -- consistent with, not an exception to, BIN-110's rule.

⚠️ **Amended during architecture review: `__bool__` must not be left undefined.** The paragraph
above is right that the field carries the meaning and that callers should read the field. But
"declare the field and say nothing about `__bool__`" leaves Pydantic's inherited object-identity
truthiness in place, so `bool(result)` is **always `True`** -- which is exactly the defect BIN-110
fixed on `SufficiencyResult`, where `if baseline.check_sufficiency():` fitted control limits from
an empty baseline.

The hazard here is worse than a no-op, because the natural misreading is inverted. An engineer
writing `if monitor.record(observation):` almost certainly means *"did something happen?"* -- and
a signal is the notable event -- so the intuitive reading is truthy-on-signal, while the field
name makes truthy-on-*in-control* the consistent one. A silent always-`True` satisfies the
careless reading of a monitoring loop that then never alerts.

**BIN-110's rule admits exactly two resolutions, and `domain-modeller` must pick one explicitly:**

1. **`__bool__` returns `is_in_control`** -- follows `SufficiencyResult`'s precedent directly.
   Consistent, but inherits the inverted-intuition hazard above.
2. **`__bool__` raises `TypeError`** -- follows `ScoringResult` and the three `Fitted*` artefacts.
   Forces `result.is_in_control`, which is unambiguous at the call site and is the only form any
   scenario or the DX snippet actually uses.

**This ADR's recommendation is (2), against the surface reading of "it has a yes/no field so it
should be truthy".** BIN-110's rule exists to stop silent always-`True`, not to maximise the number
of truthy types, and `is_in_control` is the rare field where the positive framing and the notable
event point in opposite directions. Raising makes the ambiguity a loud failure at the one call
site that could get it wrong.

**Reversibility: low, but asymmetric in the usual direction.** Loosening a raise into a meaningful
`__bool__` later is backward-compatible; tightening a working `bool()` into a raise is not. That
asymmetry is the same reason ADR-006 resolved empty-output and score-range toward the stricter
default.

**Why `observation` is on the result, satisfying BIN-69 SC2 ("what they see identifies the
observation that triggered it")** without any extra bookkeeping: `Monitor.record()` is called
once per observation and returns once per call, so the triggering observation is simply the one
just passed in. No lookup, no correlation ID needed.

**`Monitor.record()` never raises for a genuine out-of-control result** (BIN-69 BR-7,
SC8) -- only the two precondition violations above (provenance mismatch, invalid observation)
are exceptional. A signal is the successful output of a measurement.

### 5. Detection is strictly-exceeds throughout: a point exactly at a boundary is in control (resolves BIN-69 OQ-3 / BIN-112)

**Decision: `value > UCL`, `value < LCL` (Shewhart, EWMA); CUSUM's $S_{hi} > h$ or $S_{lo} > h$.
Every comparison is strict. An observation exactly at a control limit, or a CUSUM statistic
exactly equal to the decision interval, is classified in control, not out of control.**

This holds uniformly across all three chart types -- the same convention, not three
independently-chosen ones.

✅ **Amended 2026-09-11 — Montgomery obtained; the boundary convention is now verified
from the primary source.** *Introduction to Statistical Quality Control*, 7th ed. (Wiley,
2013) uses strict inequality throughout: §5.3.3 defines the ARL via *"p is the probability
that any point **exceeds** the control limits"*, and §4.1 describes an out-of-control signal
as a point that *"will plot **outside** the control limits"*. Equation 6.20, `ARL₀ = 1/α`,
follows from that definition. **Strict inequality stands, now cited rather than inferred.**

Siegmund (1985) is also effectively closed: Montgomery p. 423 states the approximation in
full, including `b = h + 1.166`, and his worked example (k = ½, h = 5 → one-sided ARL₀ 938.2,
two-sided 469.1) is now asserted by `test_reproduces_montgomery_worked_example`, which the
implementation reproduces to four significant figures.

**Lucas & Saccucci (1990) remains outstanding** — Montgomery does not reproduce its Table 3.
That value is still cross-checked via CRAN `spc`'s Nyström quadrature, an independent method.

*Superseded text, kept for the record:* the primary texts were recorded as paywalled and
unreachable in the session that wrote this ADR. What was checked instead, independently for
each chart type:

- **Shewhart:** A hosted copy of Montgomery's *Statistical Quality Control*, 7th edition,
  Chapter 5 (`just.edu.jo/~haalshraideh/QC/c05.pdf`), quoted directly: *"A point that plots
  **outside of** the control limits is interpreted as evidence that the process is out of
  control."* "Outside of" is strict-exceedance language -- a point exactly on the limit has not
  plotted outside it.
- **EWMA:** Independent search synthesis of secondary sources describing Lucas & Saccucci
  (1990) converges on *"if either statistic **exceeds** its own control limits an out-of-control
  signal is given"* -- again strict.
- **CUSUM:** NIST/SEMATECH e-Handbook §6.3.2.3 (the standard public restatement of the tabular
  CUSUM, itself citing Siegmund-era formulations), quoted directly: *"When either $S_{hi}(i)$ or
  $S_{lo}(i)$ **exceeds** $h$, the process is out of control."* Strict.

All three independent checks, across three unrelated source lineages, use the same
strict-exceedance vocabulary ("outside of," "exceeds," "exceeds") with zero contradicting
source found in this session. This is also, independently, the essentially universal SPC
convention -- no source consulted suggested any chart type in this literature treats "at the
limit" as a signal.

**This is not treated as a fully closed citation the way a numeric constant (d₂, a specific $h$)
would be, and it should not be read as one.** Per this project's own rule, an unverifiable
constant is a blocker, not a detail -- but this is a comparison operator corroborated by three
independent, convergent secondary restatements of three different primary sources, not a single
unverifiable number, and the same standard ADR-004's dual-spread finding already applied
(vendor/secondary corroboration recorded honestly, primary text flagged for verification at
implementation time) is applied here. **`BIN-84` (or whoever writes the CUSUM/EWMA/Shewhart unit
tests against published ARL tables) must re-verify this specific inequality against the actual
primary-source page text when those primary sources are obtained**, before treating it as
permanently settled. If a primary source is later found to use non-strict comparison for any one
chart type, that chart's implementation changes a single comparison operator -- a narrow,
mechanical fix, not a redesign.

**Why this matters enough to verify at all, rather than picking either convention:** the
calibration that produced a fitted artefact's `achieved_arl` assumed a convention. A continuous
score landing exactly on a floating-point boundary has probability zero under any of the
distributions this library's calibration methods assume, so in practice this choice essentially
never changes which observations signal -- but the code must still pick one, consistently, to
avoid contradicting itself between two chart types, and an incorrect convention plus BIN-84's
Monte Carlo verification work would otherwise be free to drift apart from the tables it is
supposed to match.

### 6. The store is `Monitor.history`: a plain `tuple`, not a second collection type (resolves BIN-72 OQ-1, and the "second `Baseline`" risk from BIN-72's review M3)

```python
@property
def history(self) -> tuple[MonitoringResult, ...]: ...

def clear_history(self) -> None: ...
```

Every successfully-recorded `MonitoringResult` (i.e. one that did not raise) is appended, in
order, to `Monitor`'s private backing list; `.history` returns a fresh, immutable `tuple` view.

**This resolves BIN-72's M3 finding structurally, not by naming discipline alone: there is no
second bespoke type.** `Baseline` is a purpose-built collection with its own `__len__`/
`__iter__`/`__repr__` because Phase I observations have baseline-specific semantics
(provenance-signature enforcement, sufficiency checking). Phase II history has no such
semantics beyond "what happened, in order, unmodifiable" -- exactly what a `tuple` already is,
for free, with no risk of ever being confused for `Baseline`'s richer collection type because it
is not a class an engineer could mistake for one. `len(monitor.history)`,
`for entry in monitor.history:`, and `monitor.history[-1]` all work without Caliper writing a
single dunder method.

**Resolves BIN-72 OQ-1 (stored-entry shape) directly:** the entry is `MonitoringResult` itself
(section 4) -- no separate wrapper type, because `MonitoringResult` already pairs the
observation with its determination.

**Resolves BIN-72 SC9 (no `Baseline` leakage) structurally:** `Baseline` and `Monitor` are
unrelated types with entirely separate backing storage; nothing routes data from one into the
other, so the guarantee holds by construction, not by a runtime check that could be forgotten.

### 7. Zero-config by default, with an explicit escape hatch -- OQ-2 forced to a definite R1 answer

**Decision: `Monitor` retains history by default. `retain_history: bool = True` is an optional
constructor parameter; `clear_history()` is a public method. No automatic eviction, sizing, or
TTL policy ships in R1.**

```python
monitor = caliper.Monitor(fitted_artefact)                       # retains, default
monitor = caliper.Monitor(fitted_artefact, retain_history=False)  # opts out entirely
...
monitor.clear_history()                                          # manual reset, any time
```

This directly answers BIN-72's requirements-reviewer finding M2, which required OQ-2 be forced
to a definite R1 answer rather than left open past implementation, given BR-7's own unbounded-
growth risk does not survive BR-7's persona-narrowing argument once A2's zero-config default is
adopted (the reviewer's own point: `Monitor.record()` is the same operation BIN-69 built for
"a Python engineer whose agent is producing live output in production," not only for
development/test sessions).

**Why zero-config-plus-opt-out, not opt-in.** Opt-in (constructing a store object before
anything is retained) reintroduces exactly the configuration step BIN-72's own user story frames
as absent ("review monitoring history without configuring external storage"), and BIN-72's own
review confirmed this reading is the PRD's own recommendation (A2). `retain_history=False` gives
an engineer who already knows they are running an indefinitely-long production loop and does not
want retention a one-line way to say so, without every other engineer -- almost certainly the
common case, per BIN-72's own persona (developing/testing) -- paying a configuration tax for a
risk that mostly does not apply to them.

**Why not a sizing/eviction mechanism now.** BIN-72's own Non-Goals explicitly exclude "a
specific bounding, eviction, or clearing mechanism (not now, mechanism only)" from R1 scope.
Designing one now would be scope creep this ADR is not asked to commit. `clear_history()` is not
that mechanism -- it is the trivial, symmetric complement any append-only collection needs next
to its append operation (the same relationship `list.append`/`list.clear` already have), not a
policy decision about *when* to evict. Adding a real bounding mechanism later (e.g. a
`max_history` cap) is purely additive: existing callers who never pass it keep today's unbounded
behaviour unchanged.

**The accepted risk, stated plainly, not softened:** an engineer who runs one long-lived
`Monitor` across an indefinitely-running production process, with the default settings, and
never calls `clear_history()`, will accumulate `MonitoringResult` entries without bound. This is
a real memory-growth risk in a released, third-party-imported PyPI library. It is accepted
deliberately for R1, mitigated by: the opt-out constructor parameter, the manual clear method,
and a required library-documentation warning (this ADR requires the docstring on `Monitor`'s
`retain_history` parameter and `clear_history()` method to state the risk explicitly, in the
same place an engineer reads to discover the default). It is not mitigated by an automatic
policy, because none was asked for and inventing one would be a real design decision made
without the mechanism-choice work that decision deserves.

### 8. No store *port* in R1 -- concrete-only, with a compatible public surface (resolves BIN-72 A1)

**Decision: no `Protocol` abstraction for the store is introduced in R1.** `docs/domain-model.md`
already states this for the Repository pattern generally ("Does not apply in R1... There is no
persistence to abstract over. The store port is an R2 concern"), and nothing about this design
changes that reasoning. A single concrete implementation does not justify an abstraction shaped
by guessing at a second implementation's (BIN-73's) needs before it exists.

**What makes this safely deferrable rather than a future breaking change:** the public surface
this ADR commits to -- `Monitor.history` returning `tuple[MonitoringResult, ...]`,
`Monitor.record()`, `Monitor.clear_history()`, the `retain_history` constructor parameter -- names
no internal storage type. `BIN-73` can introduce a `Protocol` retroactively (e.g. an internal
`ObservationStorePort` that `Monitor` delegates to, with the current in-process list as the
default in-memory adapter) as a purely additive, non-breaking change, exactly the way
`docs/domain-model.md`'s existing note anticipates. This constrains BIN-73's design -- it must
not require `Monitor.history`'s return type or `.record()`'s signature to change -- without
this ADR needing to design BIN-73's port today.

## Alternatives considered

### Free function with explicit state threading, no `Monitor` object

`check_ewma(artefact, prior_state, observation) -> (new_state, MonitoringResult)`, repeated per
chart type, with the engineer storing and re-passing `prior_state` between calls.

**Rejected.** Technically sufficient -- Shewhart needs no state, so its variant degenerates to a
pure function, which is a point in its favour. But it fails the "write the snippet an engineer
would actually type" test badly for the two chart types (EWMA, CUSUM) that are this story's
entire reason for existing: the engineer's own code becomes responsible for correctly
associating one `prior_state` value with one fitted artefact across however many call sites
their production code has, with no static or runtime guard against passing the wrong pair
together. It also gives BIN-72 no natural attachment point -- "review my session's history"
would require the engineer to also thread a *third* accumulating value (the list of past
results) through the same call sites, compounding the same risk. `Monitor` holds all of this
once, correctly, by construction.

### Recording operation lives on the fitted artefact

Rejected outright in section 1 -- the artefact's immutability is load-bearing (ADR-004,
BIN-108) and shared across potentially many independent monitors.

### A `Monitor.history` returning a bespoke `MonitoringHistory` collection type (mirroring `Baseline`)

Considered, because it would let a future version add store-specific methods (e.g. filtering by
chart type) without a breaking change to a plain tuple's interface. **Rejected for R1.** This is
precisely the risk BIN-72's own review (M3) flagged: a second collection type with its own
`__len__`/`__iter__`/`__repr__`, differently named from `Baseline` but structurally identical to
it, is a discoverability failure on the library's public surface waiting to happen -- and BIN-110
already found two real instances of this class of problem on this exact codebase (`Baseline`
missing `__repr__`; `caliper.baseline` exporting internal constants alongside useful names). A
plain `tuple` cannot be mistaken for `Baseline`, because it is not a class Caliper defines at
all. If a genuine need for store-specific methods appears later (e.g. BIN-73's durable query
surface), that is additive on top of a tuple-returning `.history` -- nothing here forecloses it.

### Store as a standalone object the engineer constructs and passes to `Monitor` (opt-in)

Rejected in section 7 -- reintroduces the configuration step BIN-72's own user story states is
absent, and both PRDs' reviews converged on zero-config as the PRD's own recommendation.

### A store *port* (Protocol) introduced now, ahead of BIN-73

Rejected in section 8 -- no second implementation exists yet to abstract over; the concrete
public surface is designed to make this additive later rather than needed now.

### Non-strict (`>=`) comparison at control limits

Rejected in section 5 -- every corroborating source found, across all three chart types and
three independent source lineages, uses strict-exceedance language. No source found supports
inclusive-boundary treatment for any of the three methods.

## Consequences

### What changes

- A new bounded context, **Monitoring**, is introduced (E3), depending on **Baseline** (for
  `FittedControlLimits`) and **Measurement** (for `ScoringResult`, `Provenance`) -- the same
  dependency-direction discipline the Measurement → Baseline relationship already established.
- Two new domain types: `Monitor` and `MonitoringResult`.
- `InvalidObservationError` gains a second raiser (`Monitor.record()`, alongside
  `Baseline.record()`). No taxonomy change.
- `ProvenanceMismatchError` gains a second call site (`Monitor.record()`, via the existing
  `compare_provenance()`). No shape change to the error itself.
- `docs/domain-model.md` gains a Monitoring bounded-context entry, updated Library Operations
  rows, and an updated Error Contract Reference raised-by column -- full field-level detail is
  `domain-modeller`'s next output, not finished here.

### What does not change

- **ADR-001** is not amended. `SPCPort` remains the seam between the domain and the numerical
  engine; `Monitor` calls into it, narrowing to the concrete artefact type per ADR-004 §3.
- **ADR-002** is not amended. No new exception category. `context["mismatches"]`'s shape
  (amended 2026-09-10) is unchanged and reused as-is.
- **ADR-004** is not amended. The fitted artefact protocol, its immutability, and its
  chart-specific detection boundaries stand exactly as decided; `Monitor` is a new *consumer* of
  the protocol, not a change to it.
- **ADR-006** is not amended. `Judge`, `ScoringResult`, `Provenance` are read, not written, by
  this design.
- **No `.feature` file changes.** Both `phase-ii-observation-signal-check.feature` and
  `in-memory-observation-store.feature` were written mechanism-neutrally, specifically to survive
  whichever construct this ADR chose -- verified scenario-by-scenario against the design above;
  every one binds against `Monitor` as designed.

### Reversibility

- **The `Monitor` construct (section 1):** medium cost once released -- it is new, additive
  public API surface with no existing consumer to break today, but once an engineer holds a
  `Monitor` instance in production code, changing its constructor or `record()` signature is a
  breaking change like any other public type. Low cost *now*, because nothing outside this ADR
  depends on it yet.
- **Internal provenance check (section 2):** low cost to reverse in the unsafe direction only
  (removing the internal check to require an external call would be a silent-safety regression,
  effectively never done); tightening further is not meaningful here since the check is already
  unconditional.
- **`InvalidObservationError` reuse (section 3):** low cost. A dedicated Phase-II-specific
  category could be split out later as a non-breaking, additive taxonomy change if a genuine
  need for a separate recovery path ever appears; nothing here forecloses it.
- **`MonitoringResult` shape (section 4):** medium cost, the same class as `ScoringResult`
  (ADR-006) -- adding fields is additive; removing or renaming `is_in_control`, `observation`,
  or `chart_type` breaks every consumer, including `Monitor.history`'s entries.
- **Boundary convention (section 5):** low mechanical cost (one comparison operator per chart
  type) but a real behaviour change if reversed -- previously-computed in-control/out-of-control
  determinations at the exact boundary would flip. This is why it is verified now rather than
  deferred, even though the practical exposure (a continuous score landing exactly on a
  floating-point boundary) is small.
- **`Monitor.history` as a plain tuple (section 6):** medium-high cost to reverse into a bespoke
  collection type later -- would need to preserve tuple-like iteration/length/indexing behaviour
  for existing callers while adding whatever new surface motivated the change, which is
  achievable (a custom `Sequence` subclass could stay drop-in compatible) but is real,
  deliberate migration work, not automatic.
- **Zero-config default + `clear_history()` (section 7):** low cost. Adding a real bounding
  mechanism (e.g. `max_history`) later is purely additive. Flipping the *default* from
  retain-on to retain-off later would be a breaking behaviour change for any caller relying on
  today's default; this is why the default was chosen deliberately now rather than left for
  later convenience.
- **No store port in R1 (section 8):** low cost, by design -- the public surface exposes no
  internal type, so introducing a `Protocol` later (BIN-73) is additive, not corrective.

## Related decisions

- **BIN-69 OQ-1, A1, A2, OQ-3, OQ-4:** all resolved above (sections 1, 1, 2, 5, 3 respectively).
- **BIN-72 A1, A2, OQ-1, OQ-2:** all resolved above (sections 8, 7, 6, 7 respectively).
- **BIN-112:** resolved by section 5.
- **BIN-69 OQ-2** (result shape): resolved by section 4.
- **ADR-004 §3** (chart-specific detection boundaries): reused, not amended -- `Monitor.record()`
  is the consumer ADR-004 anticipated needing to narrow to the concrete type.
- **BIN-68** (`compare_provenance()`): reused, not redefined -- see section 2.
- **BIN-73** (durable SQLite store, R2): shaped but not designed by section 8 -- must introduce
  any store port as an additive change against the public surface this ADR commits to.
- **BIN-70 / BIN-71** (decorator, context manager, R2): out of scope. Whatever these wrap, they
  wrap `Monitor.record()` as designed here; their own wrapper failure policy remains open,
  per CLAUDE.md, and is not decided by this ADR.
