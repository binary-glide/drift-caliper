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
| Baseline spread | `float` | Variance or standard deviation of Phase I scores. Which of the two is domain-modeller's decision; all chart types report the same measure. |
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
| CUSUM | Reference value (*k*), decision interval (*h*), target value (mu_0), monitored direction, baseline sigma estimate |
| Shewhart I-chart | Sigma estimate (from moving range), sigma multiplier, sigma estimation method, control limits (UCL, LCL, CL) |

**Finding: Shewhart artefact carries two spread measures.** The shared core's
"baseline spread" is the sample variance (or standard deviation) of the baseline
scores -- a descriptive statistic shared by all chart types. The Shewhart I-chart's
"sigma estimate" is the moving-range-based estimate, which is a different quantity
(robust to slow drift within the baseline). The Shewhart artefact carries both:
the shared core's baseline spread and the chart-specific sigma estimate. The
review feature file's SC1 references "the spread measure" in the shared core and
the Shewhart feature file's SC1 references "the sigma estimate" separately. The
domain-modeller must ensure both are present on the Shewhart concrete type.

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

### Finding: Shewhart artefact requires both spread measures

The Shewhart I-chart artefact must carry two spread-related quantities: the shared
core's baseline spread (sample variance or standard deviation, same as EWMA and
CUSUM) and the chart-specific sigma estimate (from the moving-range method). These
are different quantities: the sample standard deviation captures total variation
including any slow drift within the baseline; the moving-range-based sigma captures
short-term variation only (BIN-95 BR-6). Domain-modeller must ensure both are
present. The Shewhart feature file's SC2 asserts the sigma estimate; the review
feature file's SC1 asserts the shared "spread measure." Both must be satisfied.

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
