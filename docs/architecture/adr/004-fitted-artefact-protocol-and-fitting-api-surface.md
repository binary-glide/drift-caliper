# ADR-004: Fitted artefact protocol and fitting API surface

**Status:** Accepted
**Date:** 2026-09-09
**Deciders:** system-architect (BIN-99), ratified by product owner
**Refs:** BIN-99, BIN-65, BIN-66, BIN-68, BIN-69, BIN-94, BIN-95, ADR-001, ADR-002, ADR-003

## Context

Three chart-fitting stories (BIN-65 EWMA, BIN-94 CUSUM, BIN-95 Shewhart I-chart)
each raised "is there a common artefact protocol?" as OQ-2 and each deferred it.
BIN-66 (review fitted limits) is the first consumer that must work across all three
chart types. BIN-69 (Phase II monitoring) is the next. Without a settled protocol,
every downstream consumer branches N ways for M chart types, and adding a chart type
(p-chart in R2) is a breaking change across all consumers.

BIN-66's requirements review took the position: a common protocol with chart-specific
extensions, not three parallel types and not a union type. This ADR tests that
position, settles the protocol mechanism, defines the shared core, resolves the
detection-boundary question (BIN-66 OQ-5), settles the fitting API surface (closing
ADR-002's open dependency on missing-parameter expressibility), and decides the
false alarm tolerance representation (OQ-1 across all three fitting stories).

### Constraints carried forward

- **ADR-001:** Engine in-house behind `SPCPort`. scipy as numerical foundation.
  Published ARL tables as test oracle. Scores are **higher-is-better**: lower arm
  detects degradation, upper arm detects improvement (stale baseline).
- **ADR-002:** Errors assert on type/category plus required `context` field
  presence, never message text. `context["kind"]` on `invalid_parameter` is a
  closed discriminator (`"missing"` / `"invalid"`); `reason` elsewhere is
  descriptive. Nine exception types, flat hierarchy under `CaliperError`.
- **ADR-003:** ARL_0 is the calibration target. Bootstrap approach rejected.
  Published ARL tables remain the verification backstop.
- The artefact is **immutable** (BIN-65 BR-10, BIN-94 BR-11, BIN-95 BR-12) and
  carries **provenance** (BIN-68 compares provenance across the phase boundary).
- No numerical constants are pinned.
- BIN-92 (minimum baseline size) is still open.
- Python 3.11, 3.12, 3.13 (BIN-83).

### Sentry context

Not applicable. Caliper is a library with no runtime to monitor.

## Decision

### 1. Protocol mechanism: `typing.Protocol` with `@runtime_checkable`

The shared artefact contract is a `typing.Protocol` class, decorated with
`@runtime_checkable`. Concrete chart artefacts satisfy it structurally.

**Why `Protocol` over ABC:** A Protocol defines the consumer's contract without
constraining the producer's implementation inheritance. BIN-66 and BIN-69 type-hint
against the Protocol; concrete artefacts are free to be frozen dataclasses, frozen
Pydantic models, or any other immutable type. No base class is required in the MRO.
This matters because the library's domain types should not inherit from a framework
base class merely to satisfy a consumer interface.

**Why `Protocol` over structural convention (duck typing):** A Protocol gives type
checkers a named target. Consumers write `def review(artefact: FittedControlLimits)`
and get static analysis. Duck typing provides no enforcement and no documentation
for the contract's field surface.

**Why `@runtime_checkable`:** Enables `isinstance(artefact, FittedControlLimits)`
for defensive checks in consumer code and BDD step implementations.
`@runtime_checkable` is available on all target Python versions (3.11+). The check
validates structural presence of the protocol's attributes; it does not validate
types at runtime (a known limitation, acceptable for this use case).

The Protocol class name and the exact property signatures are domain-modeller scope.
This ADR establishes the mechanism and the field surface.

### 2. The shared core (protocol field surface)

Every fitted artefact exposes the following through the protocol, regardless of
chart type:

| Field | Type | Purpose |
|-------|------|---------|
| Chart type identifier | `str` | Which chart type this artefact represents. |
| Baseline mean | `float` | Mean of the Phase I baseline scores. |
| Baseline spread | `float` | Sample standard deviation of Phase I scores. A descriptive statistic — total variation including any slow drift within the baseline. NOT the operational sigma used for control limit computation (see sigma estimate). |
| Sigma estimate | `float` | The operational sigma used to compute detection boundaries. Estimated from the average moving range (MR-bar / d_2) for all chart types on individual observations (n=1). A different quantity from baseline spread — see amendment note (2026-09-09). |
| Sigma estimation method | `str` | Identifies how the sigma estimate was produced (e.g. `"moving_range"`). Reported for auditability so the artefact is self-documenting about which estimator entered the control limit computation. |
| Baseline observation count | `int` | Number of observations the limits were fitted from. |
| Provenance: judge model version | `str` | The judge model version from the baseline (BIN-63). Compared by BIN-68 across the phase boundary. |
| Provenance: scoring criteria | `str` | The scoring criteria from the baseline (BIN-63). |
| Requested false alarm tolerance | `float` | The target ARL_0 the engineer specified (see section 4). |
| Achieved false alarm tolerance | `float` | The ARL_0 actually produced by the calibration. May differ from requested due to numerical approximation. |
| Calibration method | `str` | Identifier for the method that produced the limits (e.g. Markov-chain, Siegmund approximation, tail probability). |

**Immutability** is a structural constraint on the concrete type (frozen
dataclass, `ConfigDict(frozen=True)`, `__setattr__` override, etc.), not a
protocol field. The protocol does not enforce immutability -- the concrete type
does. All three fitting stories require immutability in their business rules.

**What is NOT in the shared core:** detection boundaries and chart-specific
parameters. See section 3.

### 3. Detection boundaries are chart-specific, not in the shared protocol

**BIN-66 OQ-5 resolved: chart-specific.**

The shapes differ structurally and the distinction is semantically meaningful:

| Chart | Detection boundary shape | Scale |
|-------|------------------------|-------|
| EWMA | Upper control limit (UCL), lower control limit (LCL), centre line (CL) | Same scale as observations |
| Shewhart I-chart | UCL, LCL, CL | Same scale as observations |
| CUSUM | Decision interval *h* compared against accumulating statistic *S* | Not on the observation scale; *h* is in sigma-standardised units |

A polymorphic accessor that returns both shapes was considered and rejected. The
accessor would either:

**(a)** Return a union or sum type, forcing the consumer to match before accessing
any field -- this is the union type the protocol was designed to avoid, reintroduced
at the accessor level.

**(b)** Return a collapsed common representation (e.g. always a `(lower, upper)`
pair), which would misrepresent CUSUM. CUSUM's decision interval *h* is compared
against the accumulating statistic `S_t`, not against the observation itself. There
is no observation-scale "upper limit" or "lower limit" in CUSUM; mapping *h* to a
limit pair would be misleading and would not support the comparison that Phase II
monitoring actually performs.

**(c)** Return an abstract "boundary description" with a `check(observation)` method.
This is Phase II monitoring logic (BIN-69 scope), not artefact protocol scope. The
fitted artefact is an immutable record of what was computed; it should not contain
monitoring logic.

**Consequence for consumers:**

- **BIN-66 (review):** Detection boundaries appear in the human-readable summary
  (which includes all fields, shared and chart-specific) and through chart-specific
  accessors. The review feature file's SC3 already excludes detection boundaries
  from the shared-mechanism assertion -- this decision is consistent with the
  existing scenarios.

- **BIN-69 (Phase II monitoring):** Must narrow to the chart-specific type to
  access detection boundaries for the observation check. This narrowing is
  appropriate because the comparison logic is necessarily chart-specific: EWMA
  compares the smoothed statistic against UCL/LCL, Shewhart compares the raw
  observation against UCL/LCL, CUSUM compares the accumulating statistic against
  *h*. No single comparison operation covers all three.

- **Adding a chart type (p-chart, R2):** The new chart type implements the shared
  protocol (baseline statistics, provenance, tolerance, calibration method) and
  defines its own detection boundary shape. Existing consumers that operate on the
  shared core work without modification. Consumers that access detection boundaries
  add a branch for the new chart type -- the same cost they would incur with a
  polymorphic accessor that returns a union.

**Chart-specific fields (not on the protocol, accessed through the concrete type):**

| Chart | Fields |
|-------|--------|
| EWMA | Smoothing parameter (lambda), control limits (UCL, LCL, CL) |
| CUSUM | Reference value (*k*), decision interval (*h*), target value (mu_0), monitored direction |
| Shewhart I-chart | Sigma multiplier, control limits (UCL, LCL, CL) |

**Finding: all artefacts carry two spread measures.** The shared core's
"baseline spread" is the sample standard deviation of the baseline scores -- a
descriptive statistic. The shared core's "sigma estimate" is the moving-range-based
estimate (MR-bar / d_2), which captures short-term variation only (robust to slow
drift within the baseline). All artefacts carry both. The review feature file's SC1
references "the spread measure" in the shared core; the Shewhart feature file's SC2
references "the sigma estimate" separately. See amendment note (2026-09-09).

### 4. False alarm tolerance: ARL_0 primary, false alarm rate accepted as convenience

**Resolves OQ-1 across BIN-65, BIN-94, and BIN-95.**

The fitting API accepts the false alarm tolerance as a **target in-control Average
Run Length (ARL_0)** -- a positive number (the expected number of observations
before a false alarm when the process is in control).

**Rationale:**

1. **ARL_0 is what the calibration methods target.** ADR-001 established Lucas &
   Saccucci's Markov-chain approximation (EWMA) and Siegmund's corrected diffusion
   approximation (CUSUM), both parameterised by target ARL_0. The Shewhart I-chart's
   relationship between sigma multiplier and ARL_0 is direct (ARL_0 = 1/alpha where
   alpha is the tail probability).

2. **ARL_0 is what published ARL tables are indexed by.** BIN-84's property-based
   tests verify computed ARLs against published tabulated values. The test oracle is
   in ARL_0 units.

3. **ADR-003 reinforced ARL_0.** The bootstrap approach was rejected partly because
   it calibrates against pointwise false alarm rate rather than ARL, which would
   have abandoned the published-table verification story.

4. **ARL_0 answers the engineer's question.** "On average, how many observations
   before a false alarm?" is more useful for operational planning than "what is the
   probability of a false alarm on any given observation?"

**Convenience conversion:** The library accepts false alarm rate (alpha) as an
alternative input and converts it to ARL_0 for calibration. The conversion is
`ARL_0 = 1/alpha` for Shewhart (exact under normality); for EWMA and CUSUM the
conversion maps the input to a target ARL_0 and the calibration proceeds in ARL_0
space. The exact conversion mechanism is domain-modeller scope.

**Artefact reporting:** The fitted artefact reports both `requested_arl` and
`achieved_arl` as ARL_0 values. If the engineer specified alpha, the artefact
reports the ARL_0 it was converted to (the engineer can recover alpha as
approximately 1/ARL_0). The artefact does not carry a separate alpha field --
ARL_0 is the canonical representation. Whether a convenience `.alpha` property
exists on the concrete type is domain-modeller scope.

### 5. Fitting API surface: optional-with-required-semantics for false alarm tolerance

**Resolves ADR-002's open dependency: missing-parameter expressibility.**

The false alarm tolerance parameter in the fitting API is **optional in the Python
signature** (defaulted to `None`) but **required by Caliper's validation**. When
omitted, Caliper raises `InvalidParameterError` with `context["kind"] == "missing"`
and `context["parameter"]` naming the tolerance parameter.

**This means SC9 (BIN-65), SC9 (BIN-94), and SC8 (BIN-95) assert:**
`InvalidParameterError` with `context["kind"] == "missing"`. Not Python's
`TypeError`. The scenarios are implementable as written. No scenario changes needed.

**Rationale:**

1. **Caliper's error is better than Python's.** Python's `TypeError` says
   `"fit() missing 1 required positional argument: 'target_arl'"`. Caliper's
   `InvalidParameterError` carries structured context (`parameter`, `kind`,
   `constraint`) and a `recovery_hint` explaining *why* this parameter is required
   (the auditability argument). The structured context is testable; the TypeError
   message is not.

2. **Consistency across call patterns.** If the fitting interface is invoked via
   keyword unpacking from a configuration dictionary (`chart.fit(baseline, **config)`
   where config is a dict), a missing key does not raise `TypeError` at the call
   site -- it raises `TypeError` deep in the function body when the default `None`
   is used where a float is expected, or passes silently if the code paths allow
   `None`. Optional-with-required-semantics gives consistent `InvalidParameterError`
   behaviour regardless of call pattern.

3. **ADR-002's taxonomy is preserved.** The missing-parameter case lands in the
   same taxonomy as all other invalid-parameter cases. `context["kind"] == "missing"`
   is positively assertable per ADR-002 section 3. Tests use the same assertion
   pattern across all error scenarios.

4. **All feature files survive without modification.** The SC9/SC8 scenarios assert
   "error classifiable as an invalid parameter" and "the error identifies that a
   false alarm tolerance parameter is required." Both are satisfied by
   `InvalidParameterError(kind="missing", parameter="<tolerance_param>")`.

**The same optional-with-required-semantics pattern applies to the false alarm
tolerance parameter on all three chart types.** The tuning parameters (lambda for
EWMA, reference value for CUSUM) are optional with library defaults -- genuinely
optional in both the Python signature and Caliper's validation. The Shewhart I-chart
has no tuning parameter.

**Fitting signature shape (for domain-modeller):**

```
fit_ewma(baseline, *, target_arl=None, smoothing_param=None) -> FittedEWMA
fit_cusum(baseline, *, target_arl=None, reference_value=None, direction=None) -> FittedCUSUM
fit_shewhart(baseline, *, target_arl=None) -> FittedShewhart
```

Whether these are standalone functions, methods on a chart factory, methods on the
baseline, or methods behind `SPCPort` is domain-modeller scope. This ADR settles
the parameter semantics:

| Parameter | Python signature | Caliper validation |
|-----------|-----------------|-------------------|
| `target_arl` | `float | None = None` | Required. `None` raises `InvalidParameterError(kind="missing")`. |
| `smoothing_param` (EWMA) | `float | None = None` | Optional. `None` uses library default. |
| `reference_value` (CUSUM) | `float | None = None` | Optional. `None` uses library default. |
| `direction` (CUSUM) | `str | None = None` | Optional. `None` uses `"two_sided"` default. See section 6. |

### 6. CUSUM directionality: two-sided default, configurable to one-sided

**Resolves BIN-94 OQ-5. Falls out naturally from the artefact protocol design
because the monitored direction is a reported field on the artefact (BR-13).**

The CUSUM fitting API accepts an optional direction parameter. The valid set is:

| Direction | Meaning | Arms |
|-----------|---------|------|
| `"two_sided"` (default) | Monitor for both degradation and improvement | Lower arm (degradation) + upper arm (improvement/stale baseline) |
| `"lower"` | Monitor for degradation only | Lower arm only |
| `"upper"` | Monitor for improvement only (baseline staleness) | Upper arm only |

**Rationale:**

- ADR-001 established: lower arm detects degradation (score drifts down), upper arm
  detects improvement (score drifts up, baseline stale). Two-sided CUSUM is listed
  as a positive consequence.
- Two-sided is the safe default: it catches drift in both directions. The ARL impact
  is well-characterised in the literature (two-sided ARL approximated from one-sided
  ARLs).
- One-sided is available for advanced users. An engineer who only cares about
  degradation and wants the entire ARL budget spent on one direction for faster
  detection can specify `"lower"`.
- The fitted artefact reports the direction (CUSUM feature file SC1 already asserts
  this). The direction is part of the ARL claim: a two-sided CUSUM has a different
  ARL from either one-sided arm.
- Invalid direction values raise `InvalidParameterError` with `context["kind"] ==
  "invalid"` and `context["parameter"]` naming the direction parameter. The CUSUM
  feature file's SC8c already covers this error path.

**This does not apply to EWMA or Shewhart.** EWMA control limits are inherently
two-sided (UCL/LCL symmetrically placed). The Shewhart I-chart is inherently
two-sided (BIN-95 BR-8). Neither has a direction parameter.

## Amendment 2026-09-12 (BIN-122): the protocol is a *reporting* contract, and gains a `HasProvenance` sibling

**Status:** ✅ ratified by the product owner 2026-09-12.
🚧 **Decision only — NOT YET IMPLEMENTED. Tracked by BIN-135.**
**Refs:** BIN-122 (item 3), BIN-120, BIN-127, BIN-135, ADR-011.

⚠️ **Read the rest of this amendment as a specification, not a description.**
As of `trunk` `bbff502`, `HasProvenance` exists nowhere in `src/`, `tests/` or
`docs/domain-model.md`; `compare_provenance` still annotates
`artefact: FittedControlLimits`; and `FittedControlLimits`' docstring does not
yet carry the disclaimer section 1 below requires of it. Everything section 1
of the original ADR decided **is** implemented — this is the 2026-09-12
amendment alone.

### What surfaced

`BIN-120` narrowed `Monitor.__init__` to the three concrete `Fitted*` types,
because `_check()` dispatches on chart-specific detection logic. `BIN-122`'s
scope survey then found the consequence: **the same protocol now means two
different things at two public entry points.**

| entry point | a structural conformer is | and it is |
|---|---|---|
| `compare_provenance` | **accepted** | **correct** — it detects a genuine mismatch |
| `Monitor` | **rejected** | **also correct** — it needs what a third party cannot supply |

Neither is a defect. `isinstance(x, FittedControlLimits)` simply told a caller
nothing useful about which they would get.

### 🚨 The measurement that settles it

Counting what each entry point actually reads:

```
Monitor reads 10 attributes
  IN the protocol    : baseline_mean, chart_type, sigma_estimate                (3)
  NOT in the protocol: decision_interval, direction, lcl, reference_value,
                       smoothing_param, target_value, ucl                       (7)

compare_provenance reads 2 attributes
  IN the protocol    : provenance_model_version, provenance_criteria            (2)
  NOT in the protocol: none                                                     (0)
```

**`FittedControlLimits` covers `compare_provenance` completely and `Monitor`
barely — 3 of 10.** The seven it misses are precisely the chart-specific
detection boundaries **section 3 of this ADR deliberately excluded**.

⚠️ **So this protocol was never a monitoring contract, and could not have become
one without reversing section 3.** `BIN-120`'s narrowing was not a compromise
forced by an implementation detail; it was the correct reading of a protocol
that describes what a fitted artefact **reports**, not what `Monitor` can
**consume**.

The original decision is unchanged. What was wrong was the *implied* promise
that structural conformance made an object usable everywhere.

### Decision

**1. `FittedControlLimits` is a reporting/audit contract.** It describes what
every fitted artefact exposes for inspection, comparison and provenance
checking. Its 12 attributes stay exactly as section 2 defines them.
⚠️ **It is not, and never was, a plug-in interface for third-party charts.**
Its docstring must say so.

**2. Add `HasProvenance`** — a two-attribute `@runtime_checkable` protocol
(`provenance_model_version`, `provenance_criteria`). `compare_provenance`
accepts it. This is the part of the surface a third party **can** genuinely
satisfy, and satisfying it means something definite: your object can be
provenance-checked.

**3. `Monitor` keeps its concrete-type check** (`BIN-120`), now recorded as
*correct by construction* rather than a narrowing. Monitoring a chart type
Caliper does not implement remains out of scope — `BIN-82` (Western Electric)
is the first plausible caller and would add a concrete type, not a conformer.

### Consequences

**Additive for consumers.** `FittedControlLimits` keeps its name, attributes
and `@runtime_checkable` behaviour; every existing `isinstance` check returns
what it did before. `HasProvenance` is a new export. **No published behaviour
changes.**

⚠️ **`compare_provenance`'s annotation narrows to `HasProvenance`**, which is a
*widening* of what it accepts in principle and identical in practice — every
`FittedControlLimits` conformer also satisfies `HasProvenance`, since the two
provenance attributes are a subset.

**What a caller gains:** `isinstance(x, HasProvenance)` is now a true statement
about capability. `isinstance(x, FittedControlLimits)` means "reports like a
fitted artefact" and no longer implies "can be monitored" — which was the
false half.

⚠️ **`BIN-121`'s exception-contract registry classifies both protocols as
"not an entry point".** Adding a public name means that registry's completeness
meta-test will fail until `HasProvenance` is classified. **That is the gate
working**; classify it rather than routing around it.

## Alternatives considered

### Protocol mechanism: abstract base class (ABC)

**Rejected.** An ABC would require all concrete artefact types to inherit from a
common base class. For a library's own types this is feasible, but it constrains
the implementation unnecessarily. If a consumer creates a mock or fake artefact
for testing, it must inherit from the ABC. A Protocol imposes no such constraint --
structural satisfaction is sufficient. The Protocol can always be refactored into
an ABC later (by adding it to the MRO) as a non-breaking change if runtime method
enforcement is needed. The reverse (ABC to Protocol) is a breaking change for
consumers who `isinstance`-check against the ABC.

### Protocol mechanism: structural convention (no formal type)

**Rejected.** Structural convention (duck typing with no Protocol class) provides no
static analysis, no documentation, and no `isinstance` checking. Consumers cannot
type-hint against "a fitted artefact" without naming a concrete type, which defeats
the purpose of the protocol. The BDD step implementations need `isinstance` to
verify "chart-type-agnostic access" assertions in BIN-66 SC3.

### Detection boundaries in the shared protocol (polymorphic accessor)

**Rejected.** See section 3 for the full analysis. A polymorphic accessor that
returns both limit-pair and decision-interval shapes was evaluated in three forms:
(a) union/sum type return (reintroduces the union pattern at the accessor level),
(b) collapsed common representation (misrepresents CUSUM's decision interval as an
observation-scale limit), (c) abstract boundary with `check()` method (embeds
monitoring logic in an immutable record). All three add complexity without
eliminating the chart-type-specific branching that consumers need for their actual
operations. The cost of chart-specific detection boundaries is that BIN-69 narrows
to the concrete type for the observation check -- but BIN-69's comparison logic is
necessarily chart-specific regardless.

### Detection boundaries as a separate Protocol

**Considered and deferred.** A second Protocol (`DetectionBoundary`) with chart-
specific implementations was considered. This would allow typing detection
boundaries generically without collapsing their shapes. However, this adds a type
for a two-member sum (limit pair vs decision interval) that consumers must still
match on. The benefit over accessing the concrete type directly is marginal. If
a third detection boundary shape emerges (e.g. the p-chart in R2), the case for a
separate Protocol strengthens. Deferred to R2.

### False alarm tolerance: genuinely required Python argument

**Rejected.** Making `target_arl` a required positional or keyword argument would
cause Python's `TypeError` to fire before Caliper code runs. `TypeError` carries
no structured context, no recovery hint, and no `kind` discriminator. SC9's
assertion (`InvalidParameterError` with `context["kind"] == "missing"`) would be
unimplementable as written. The scenarios would need to assert `TypeError` instead,
breaking ADR-002's error taxonomy for this one case. Additionally, `TypeError`
behaves differently across call patterns (keyword unpacking from a dict does not
raise `TypeError` for a missing key if the parameter has no default).

### False alarm tolerance: both ARL_0 and alpha as first-class parameters

**Rejected.** Accepting both `target_arl` and `target_alpha` as independent
parameters invites contradictory specification (the engineer passes both and they
are inconsistent). If only one is accepted, the other must be a convenience
conversion. ARL_0 is the natural primary because it is what the calibration methods
target (ADR-001), what published tables are indexed by (BIN-84), and what ADR-003
established as the canonical metric. Alpha as a convenience conversion
(input-only, converted to ARL_0 before calibration) avoids the contradiction
without adding a second tolerance field to the artefact.

### False alarm tolerance: alpha primary

**Rejected.** ADR-003 rejected the bootstrap approach partly because it calibrates
against pointwise false alarm rate rather than ARL. Using alpha as the primary
representation would be inconsistent with ADR-003's reasoning. Furthermore,
published ARL tables (the test oracle) are indexed by ARL_0, not alpha. The
Markov-chain method (EWMA) and Siegmund's approximation (CUSUM) are parameterised
by ARL_0 directly.

### CUSUM direction: fixed two-sided only

**Considered and rejected.** ADR-001 established two-sided CUSUM as a positive
consequence. Fixing it to two-sided would prevent advanced users from allocating
the full ARL budget to one direction for faster detection of a specific shift
type. Since the direction parameter already appears on the artefact (CUSUM feature
file SC1) and the error path for invalid directions already exists (SC8c), making
it configurable adds minimal API surface. The default is two-sided; the
configuration is strictly additive.

## Consequences

### What changes

- **ADR-002's open dependency is resolved.** The missing-parameter case is
  expressible as `InvalidParameterError(kind="missing")` because the fitting API
  uses optional-with-required-semantics. Domain-modeller and backend-test-writer
  can implement SC9 as written. No amendment to ADR-002 is needed; its decision
  stands and the dependency it recorded is now closed.

- **BIN-66 (review fitted limits):** OQ-5 resolved -- detection boundaries are
  chart-specific. SC3 (shared-mechanism assertion) is already consistent with this
  decision (it does not list detection boundaries). SC1 (detection boundaries in
  review) is satisfied through the human-readable summary, which includes all
  fields. No scenario changes needed.

- **BIN-65 (EWMA fitting):** OQ-1 resolved (ARL_0 primary), OQ-2 resolved (common
  protocol exists). SC9 implementable as written. No scenario changes needed.

- **BIN-94 (CUSUM fitting):** OQ-1 resolved, OQ-2 resolved, OQ-5 resolved
  (two-sided default, configurable). SC8c (invalid direction) already exists and
  survives. No scenario changes needed.

- **BIN-95 (Shewhart I-chart fitting):** OQ-1 resolved, OQ-2 resolved. SC8
  implementable as written. No scenario changes needed.

- **BIN-68 (provenance comparison):** The provenance fields are in the shared
  protocol. BIN-68's comparison works against `FittedControlLimits` (the Protocol)
  without narrowing to a chart-specific type. The provenance mismatch feature file
  SC5 ("same error shape regardless of chart type") is supported by the shared
  provenance fields. No changes needed.

- **BIN-69 (Phase II monitoring):** Must narrow to the chart-specific type for
  detection boundary access and comparison logic. This is by design -- the
  comparison operation is chart-specific. The shared protocol provides provenance
  and baseline statistics for Phase II's non-comparison needs. No existing
  scenarios are affected (BIN-69's feature files are not yet written).

### What does not change

- **ADR-001** is not amended. `SPCPort` is the port for the engine adapter; the
  artefact protocol is the output type. These are complementary.
- **ADR-002** is not amended. The error taxonomy stands; the open dependency is
  resolved, not changed.
- **ADR-003** is not amended. ARL_0 as calibration target is reinforced.
- **No feature files need scenario changes.** All ten existing feature files
  survive all four decisions. The BDD scenario writers wrote resilient scenarios
  that constrain capability without prescribing mechanism.
- **No stories need re-review.** Zero scenario changes means zero re-review cost.

### Finding: all artefacts carry two spread measures (dual-spread)

Every fitted artefact carries two spread-related quantities in the shared core.
They are different quantities that answer different questions:

- **`baseline_spread`** (shared core): the sample standard deviation of all
  Phase I scores. Captures **total** variation, including any slow drift within
  the baseline. A descriptive statistic.
- **`sigma_estimate`** (shared core): the moving-range-based estimate
  (MR-bar / d_2). Captures **short-term** variation only, robust to slow drift.
  The **operational** sigma used by all chart types for control limit computation.

This split applies to **all three chart types**, not only Shewhart. See amendment
note (2026-09-09) for the reasoning and citation status.

The Shewhart feature file's SC2 asserts "the sigma estimate derived from the
baseline"; the review feature file's SC1 asserts "the spread measure" (baseline
spread). Both are present and distinguishable on all artefacts.

### Reversibility

**Low cost to reverse the protocol mechanism.** Migrating from Protocol to ABC
requires adding the ABC to the MRO of each concrete type -- a non-breaking change
for consumers who type-hint against the Protocol (since concrete types would then
satisfy both). Migrating the other direction (ABC to Protocol) would break
`isinstance` checks written against the ABC.

**Medium cost to reverse the detection-boundary decision.** Adding a
`DetectionBoundary` Protocol later requires introducing a new type and retrofitting
accessors onto existing concrete types. This is non-breaking (additive) but
requires work across all chart types. The R2 p-chart is the natural trigger for
re-evaluating this decision.

**High cost to reverse the tolerance representation.** Changing from ARL_0 to alpha
as the primary representation would require changing every artefact's field names,
every test fixture, and every consumer that reads tolerance values. This is
effectively permanent once consumers write code that reads `requested_arl`. This
is acceptable: ARL_0 as the SPC-standard representation is not a controversial
choice.

## Related decisions

- **BIN-59 OQ-1 (score type):** Resolved as `float` in ADR-001. Unaffected.
- **BIN-92 (minimum baseline size):** Still open. This ADR does not assume any
  threshold value.
- **BIN-84 (property-based tests):** Published ARL tables remain the test oracle,
  indexed by ARL_0. Consistent with this ADR's tolerance representation.
- **BIN-66 OQ-1 (serialisable form):** Not resolved here. The protocol does not
  prescribe serialisation. A `to_dict()` method on concrete types is a natural
  extension but is BIN-66/BIN-72/BIN-73 scope.
- **BIN-95 OQ-5 (moving-range span):** Not resolved here. Endorsed as fixed at
  the conventional span for R1, per the PRD's recommendation. If made configurable
  in R2, the span would become a chart-specific field on the Shewhart artefact.
- **BIN-65/94/95 OQ-3 (sufficiency check internal vs external):** Not resolved
  here. Both designs satisfy BR-1. Domain-modeller decides.
- **BIN-65/94/95 OQ-4 (sufficiency override for testing):** Not resolved here.
  Domain-modeller decides.

---

## Amendment (2026-09-09): sigma estimate moves into the shared core

**Trigger:** domain-modeller (BIN-100, PR #18) verified that MR-based sigma
estimation is standard practice for **all** chart types on individual observations
(n=1), not only Shewhart. The original ADR placed the sigma estimate and sigma
estimation method on the Shewhart artefact only and left the shared core's spread
field as "variance or standard deviation -- domain-modeller decides." That split
was incorrect.

### What changed

1. **Shared core gains two fields:** `sigma_estimate` (the operational sigma,
   MR-bar / d_2) and `sigma_estimation_method` (which estimator produced it).
   Both appear in the shared core table (section 2).

2. **`baseline_spread` is now specified** as the sample standard deviation -- a
   descriptive statistic, not the operational sigma. The original "variance or
   standard deviation -- domain-modeller decides" is resolved.

3. **Chart-specific fields updated:** `baseline sigma estimate` removed from CUSUM
   chart-specific fields; `sigma estimate`, `sigma estimation method` removed from
   Shewhart chart-specific fields. These are now shared.

4. **Finding section updated** from "Shewhart artefact requires both spread
   measures" to "all artefacts carry two spread measures" -- the dual-spread
   finding applies to all chart types.

### Why -- structural, not conventional

With individual observations (n=1) there are **no within-subgroup replicates**,
so consecutive differences are the only available estimator of short-term
variation. This is a fact about the data shape, not a per-chart convention.

The argument is **stronger** for EWMA and CUSUM than for Shewhart. Their purpose
is detecting sustained small shifts. A sigma inflated by drift already present in
the baseline produces wider limits and less sensitivity -- desensitising the chart
against exactly what it exists to catch. That is self-defeating in a way it is not
for the I-chart, which targets large acute excursions.

The drift-robustness argument the domain model made for Shewhart was never
Shewhart-specific; it simply had not been followed through.

### ARL tables are unaffected

The Markov-chain (Lucas & Saccucci 1990) and diffusion (Siegmund 1985)
approximations **take sigma as a parameter -- they assume sigma is known.** The
estimator choice is upstream of the ARL calculation, not an assumption inside it.
Published ARL tables remain valid regardless of which estimator is used.

What the estimator affects is how well the estimate approximates the true sigma --
the parameter-estimation-error problem ADR-005 already addressed (Quesenberry
1993; Jones, Champ & Rigdon 2001). These are two separable concerns.

### Citation status -- record the gap honestly

✅ **Closed 2026-09-11 — Montgomery obtained and read directly.** *Introduction to
Statistical Quality Control*, 7th ed. (Wiley, 2013), §6.4, Eq. 6.33, states the
individuals chart explicitly as `UCL = x̄ + 3·MR̄/d₂`, centre line `x̄`,
`LCL = x̄ − 3·MR̄/d₂`, with *"If a moving range of n = 2 observations is used,
then d₂ = 1.128."* MR-based estimation for individuals data is confirmed from the
primary source, not inferred from vendors.

`d₂ = 1.128` also matches Appendix VI (Factors for Constructing Variables Control
Charts) and Caliper's own **derivation**, `2/√π = 1.1283791…`, which
`test_moving_range_d2_matches_the_expected_range_of_two_standard_normals` asserts.
Three independent confirmations; the derivation remains primary, since it is exact
where the table is rounded.

*Superseded text, kept for the record:* supporting sources were **commercial SPC
vendor documentation** (spcforexcel.com, analyse-it, SigmaXL), with Montgomery
Chapter 9 paywalled and not accessed directly.

The NIST/SEMATECH e-Handbook was independently checked: its EWMA section says
only "s is the standard deviation calculated from the historical data" without
addressing n=1, and its CUSUM section covers only m samples of size n. NIST does
not settle it.

Following ADR-001's precedent for calibration constants: the gap is recorded and
marked for **primary-source verification at implementation time**, before BIN-84's
fixtures are written. Vendor documentation is not presented as a primary citation.

### Feature file impact

**No feature files change.** The ten approved feature files on `trunk` do not
name specific sigma estimators. BIN-66 SC1 references "the spread measure"
(baseline_spread); BIN-95 SC2 references "the sigma estimate derived from the
baseline" (sigma_estimate). Both are now in the shared core and remain
distinguishable. Zero re-review cost.
