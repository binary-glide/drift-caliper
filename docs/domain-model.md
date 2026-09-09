---
created: 2026-09-09
feature: BIN-100 — Domain model — aggregates, ubiquitous language, value objects
bounded_context: measurement, baseline
---

# Domain Model: Caliper SPC Library

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
| Read: iterate observations, inspect count, inspect provenance signature | — | — | — |

**Design note:** The Baseline has aggregate-like properties (enforces invariants on its contents, controls access to its observations) without the transactional semantics that define an aggregate in DDD. No transaction wraps a `record()` call; the invariant is enforced synchronously in a single-threaded library call.

---

### Judge — immutable configured adapter

The `Judge` is the measurement instrument. It wraps an LLM provider, holds a pinned model version, and scores agent outputs against criteria.

**Not a traditional entity:** the Judge has no lifecycle beyond creation, no mutable state, and no need for identity. Two judges with the same model version configured against the same provider are functionally interchangeable.

**Not a pure value object:** the Judge has side-effecting behaviour — calling an LLM provider to score. It sits at the boundary between the domain and the external world.

**Best characterised as:** an immutable configured adapter behind a port boundary. The domain model defines its configuration contract; the implementation is an adapter concern.

**Configuration constraints:**

| Field | Type | Constraint | Source |
|-------|------|-----------|--------|
| `model_version` | `ModelVersion` | Required, non-empty, immutable, preserved exactly as provided | BIN-57 |
| Criteria attachment point | TBD | **OQ-1** — criteria may attach at judge creation, at monitoring setup, or per-call | BIN-58 OQ-3 |

**Operations:**

| Operation | Input | Output | Errors |
|-----------|-------|--------|--------|
| Create | `model_version: str` | `Judge` | `InvalidParameterError` (missing/empty/whitespace-only model version) |
| `score(output, criteria?)` | Agent output, scoring criteria (if not attached at creation) | `ScoringResult` | `ProviderError`, `MalformedResponseError`, `JudgeRefusalError`, `MissingPrerequisiteError` (no criteria available) |
| Inspect | — | `model_version` | — |

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

        This is a descriptive statistic capturing TOTAL variation in the
        baseline, including any slow drift. All chart types compute and
        report this same measure. It is NOT the sigma estimate used by
        the Shewhart I-chart for control limits — see the dual-spread
        note below.
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
| *(shared core)* | | All FittedControlLimits properties |
| `reference_value` | `float` | *k* — shift size to detect, in sigma units |
| `decision_interval` | `float` | *h* — derived from *k* and target ARL_0 via Siegmund's approximation; the engineer does not specify this directly |
| `target_value` | `float` | mu_0 — typically the baseline mean |
| `direction` | `str` | `"two_sided"` (default), `"lower"`, or `"upper"` |
| `sigma_estimate` | `float` | The sigma used for CUSUM standardisation. Currently the sample standard deviation (same value as `baseline_spread`), listed separately for auditability — the artefact must be self-documenting about which sigma was used in the computation. |

#### FittedShewhart

| Field | Type | Notes |
|-------|------|-------|
| *(shared core)* | | All FittedControlLimits properties |
| `sigma_estimate` | `float` | **Moving-range-based estimate (MR-bar / d_2).** This is a DIFFERENT quantity from `baseline_spread` — see dual-spread note. |
| `sigma_multiplier` | `float` | *k* — number of sigma units defining control limits; derived from the false alarm tolerance, not engineer-specified |
| `sigma_estimation_method` | `str` | Identifies the estimation method (moving-range for R1) |
| `ucl` | `float` | Upper control limit = `baseline_mean + sigma_multiplier * sigma_estimate` |
| `lcl` | `float` | Lower control limit = `baseline_mean - sigma_multiplier * sigma_estimate` |
| `cl` | `float` | Centre line (= baseline mean) |

### The Shewhart Dual-Spread Distinction (ADR-004 finding)

The Shewhart I-chart artefact carries **two** spread-related quantities. They are different quantities that answer different questions:

| Field | Source | What it captures | How it is computed |
|-------|--------|------------------|--------------------|
| `baseline_spread` (shared core) | Sample standard deviation of all Phase I scores | **Total** variation, including any slow drift within the baseline | Standard sample std dev formula over all observations |
| `sigma_estimate` (Shewhart-specific) | Moving-range method: MR-bar / d_2 | **Short-term** variation only, robust to slow drift | Average of absolute consecutive differences, divided by the unbiasing constant d_2 for span 2 |

**Why both exist:** The sample standard deviation captures ALL variation in the baseline, including slow trends or step changes within the collection period. The moving-range sigma captures only the variation between consecutive observations — the short-term noise. SPC uses the moving-range sigma for I-chart limits precisely because it isolates the variation relevant to individual-observation monitoring. If the baseline contains a slow upward trend, the sample standard deviation is inflated (wider limits, fewer signals), but the MR sigma is unaffected (correct limits for the point-to-point noise).

**Why this matters:** Conflating the two silently produces wrong limits. Using `baseline_spread` (sample std dev) as the Shewhart sigma would over-estimate process variation when the baseline contains any drift, producing limits that are too wide and that miss genuine shifts. Using the MR sigma as the EWMA or CUSUM sigma would under-estimate variation when baseline drift is present, producing limits that are too tight and that generate false alarms.

**The review feature file (BIN-66) asserts both:** SC1 references "the spread measure" (shared core's `baseline_spread`); the Shewhart feature file's SC2 separately references "the sigma estimate derived from the baseline." Both must be present and distinguishable.

**Moving-range span:** Fixed at the conventional value (span 2) for R1, per BIN-95 OQ-5 endorsed by ADR-004. The unbiasing constant d_2 is coupled to the span — changing one without the other invalidates the limits.

---

## Value Object Inventory

All value objects below are immutable after creation. Equality is by value (all fields) unless noted otherwise.

### `ModelVersion`

**Carried by:** `Judge.model_version`, `Provenance.model_version`
**Equality:** by value (string comparison)
**Constraints:**
- Must be a non-empty string (BIN-57 BR-1, BR-2)
- Whitespace-only strings are rejected (BIN-57 SC4)
- Preserved exactly as provided, including leading/trailing whitespace (BIN-57 SC5, SC7)
- Immutable after creation (BIN-57 SC6)

**Factory:** `ModelVersion.create(raw: str) -> Result[ModelVersion, InvalidParameterError]`
**Rejects:** empty string, whitespace-only string, `None`.

### `ScoringCriteria`

**Carried by:** `Provenance.scoring_criteria`, criteria configuration point (OQ-1)
**Equality:** by value (string comparison)
**Constraints:**
- Must be a non-empty string (BIN-58 BR-1)
- Whitespace-only strings are rejected (BIN-58 SC3)
- Multi-line text is accepted (BIN-58 SC5)
- Preserved exactly as provided, including surrounding whitespace (BIN-58 SC4, SC7)
- Immutable after creation

**Factory:** `ScoringCriteria.create(raw: str) -> Result[ScoringCriteria, InvalidParameterError]`
**Rejects:** empty string, whitespace-only string, `None`.

### `Provenance`

**Carried by:** `ScoringResult.provenance`, `Baseline.provenance_signature`, `FittedControlLimits` (via two protocol properties)
**Equality:** compares both dimensions (model version AND criteria). **OQ-2 (open):** whether comparison is exact string match or normalised is unresolved. The need for equality is established (BIN-63 provenance checking, BIN-68 phase boundary comparison); the mechanism is not.
**Constraints:**
- Both dimensions required and non-empty
- Immutable after creation

**Structure:**

| Field | Type | Source |
|-------|------|--------|
| `model_version` | `str` | From `ModelVersion`, carried through from the Judge |
| `scoring_criteria` | `str` | From `ScoringCriteria`, carried through from the criteria configuration |

**Factory:** `Provenance.create(model_version: str, scoring_criteria: str) -> Result[Provenance, InvalidParameterError]`
**Rejects:** either dimension empty or None.

**Usage across five stories:**
- BIN-57: originates model version
- BIN-59: attaches provenance to each ScoringResult
- BIN-63: enforces provenance consistency within the baseline; exposes provenance signature
- BIN-65/94/95: carries provenance onto the fitted artefact
- BIN-68: compares provenance across the Phase I/II boundary; raises `ProvenanceMismatchError` on divergence

### `ScoringResult`

**Carried by:** returned from `Judge.score()`, recorded into `Baseline`
**Equality:** by value (all fields)
**Constraints:**
- All three fields required (BIN-59 BR-1, BR-2)
- Immutable after creation (BIN-59 BR-3)

**Structure:**

| Field | Type | Notes |
|-------|------|-------|
| `score` | `float` | Scalar quality score (ADR-001: `float`, higher-is-better) |
| `reasoning` | `str` | Judge's textual reasoning for the score |
| `provenance` | `Provenance` | Measurement configuration that produced this score |

**Factory:** `ScoringResult.create(score: float, reasoning: str, provenance: Provenance) -> Result[ScoringResult, InvalidParameterError]`
**Rejects:** missing fields. Score range constraints are **OQ-5** (open: BIN-59 OQ-2).

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
| `data_quality_concerns` | `Sequence[DataQualityConcern]` | E.g., zero variance (BIN-64 SC7) |

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
| **Observation** | A scoring result recorded into a baseline. Observations are the unit of baseline data. In R1, an observation IS a `ScoringResult` — no additional fields. BIN-63 OQ-3 (open) may add a timestamp or sequence index. | Baseline | BIN-63 |
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
| **Baseline spread** | The sample standard deviation of Phase I scores. A shared descriptive statistic on all fitted artefacts (part of the `FittedControlLimits` protocol). Captures TOTAL variation including any slow drift within the baseline. | Baseline | ADR-004 |
| **Moving-range sigma** / **sigma estimate** (Shewhart) | The short-term variation estimate from consecutive-observation differences: MR-bar / d_2 for span 2. Used exclusively by the Shewhart I-chart for control limits. Captures SHORT-TERM variation only, robust to slow drift. **Different from baseline spread** — see dual-spread note above. | Baseline | BIN-95, ADR-004, ADR-005 |
| **Sigma multiplier** | The number of sigma units defining Shewhart control limits. Derived from the false alarm tolerance — not specified by the engineer. | Baseline | BIN-95, ADR-004 |
| **Calibration method** | The numerical procedure that determined the chart's parameters from the target ARL_0. EWMA: Markov-chain (Lucas and Saccucci 1990). CUSUM: Siegmund's corrected diffusion approximation (1985). Shewhart: direct tail probability. | Baseline | ADR-001, ADR-004 |
| **Chart type** | One of EWMA, CUSUM, or Shewhart I-chart in R1. Reported on every fitted artefact. | Baseline | ADR-004 |
| **Direction** (CUSUM) | Which direction(s) of drift are monitored. `"two_sided"` (default): both arms. `"lower"`: degradation only (score drifts down). `"upper"`: improvement only (baseline staleness). Two-sided default, configurable to one-sided (ADR-004 section 6). | Baseline | ADR-004 |
| **Higher-is-better** | Caliper's score orientation (ADR-001). A falling score = degradation (lower CUSUM arm). A rising score = improvement / stale baseline (upper CUSUM arm). This mapping holds throughout the library. | Both | ADR-001 |
| **Signal** | An out-of-control indication from Phase II monitoring. E4 (BIN-75 through BIN-81) has no written requirements. Not modelled in R1. | — | context.md (sketch only) |
| **SPCPort** | The port interface for the SPC engine (ADR-001). The boundary between the domain and the statistical computation layer. Fitting operations are behind this port. | Baseline | ADR-001 |

**Consistency notes:**
- "False alarm tolerance" is used throughout the feature files as a neutral term. ADR-004 resolved this to ARL_0 as the primary representation.
- "Spread measure" in BIN-66 SC1 refers to `baseline_spread` (shared core sample standard deviation). "Sigma estimate" in BIN-95 SC2 refers to the Shewhart-specific MR-based estimate. These are explicitly different quantities.
- "Observation" and "scoring result" are the same data — the term shifts at the context boundary. A "scoring result" becomes an "observation" when recorded into a baseline.

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

---

## Error Contract Reference

ADR-002 defines the error taxonomy. Nine typed exceptions under `CaliperError`, each with required `context` fields. The full specification is in `docs/architecture/adr/002-error-contract-exception-taxonomy.md`.

| Exception | Category string | Required context fields | Raised by |
|-----------|----------------|------------------------|-----------|
| `InvalidParameterError` | `invalid_parameter` | `parameter`, `constraint`, `kind` (`"missing"` or `"invalid"`) | Judge creation (BIN-57), criteria config (BIN-58), sufficiency threshold (BIN-64), fitting parameters (BIN-65/94/95) |
| `MissingPrerequisiteError` | `missing_prerequisite` | `prerequisite`, `operation` | Scoring without criteria (BIN-59) |
| `ProviderError` | `provider_failure` | `provider`, `operation` | LLM provider failure during scoring (BIN-59) |
| `MalformedResponseError` | `malformed_response` | `operation`, `expected_shape` | Unparseable judge response (BIN-59) |
| `JudgeRefusalError` | `judge_refusal` | `provider`, `operation` | Judge safety-filter refusal (ADR-002) |
| `ProvenanceMismatchError` | `provenance_mismatch` | `dimension`, `expected`, `received` | Baseline recording (BIN-63), Phase II comparison (BIN-68) |
| `InvalidObservationError` | `invalid_observation` | `reason`, `missing_fields` | Incomplete input to baseline (BIN-63) |
| `InsufficientBaselineError` | `insufficient_baseline` | `have`, `need` | Fitting from too-small baseline (BIN-65/94/95) |
| `DegenerateBaselineError` | `degenerate_baseline` | `reason` | Fitting from zero-variance baseline (BIN-65/94/95) |

**Immutability violations** (BIN-57 SC6, BIN-59 SC6, BIN-63 SC9, BIN-65 SC11, BIN-94 SC12, BIN-95 SC12) raise Python's built-in `AttributeError` or `FrozenInstanceError`, not `CaliperError`. These are programming mistakes caught by the type system, not operational failures.

---

## Library Operations

These are the operations the ten feature files establish. They replace the "service operations" section that a service-oriented model would include.

| Operation | Feature file | Input | Output | Context |
|-----------|-------------|-------|--------|---------|
| Create judge | BIN-57 | `model_version: str` | `Judge` | Measurement |
| Configure criteria | BIN-58 | `criteria: str` | `ScoringCriteria` (attachment point OQ-1) | Measurement |
| Score agent output | BIN-59 | Agent output, criteria | `ScoringResult` | Measurement |
| Create baseline | BIN-63 | (none) | `Baseline` (empty) | Baseline |
| Record observation | BIN-63 | `ScoringResult` | Mutates baseline | Baseline |
| Check sufficiency | BIN-64 | Optional: threshold, chart type | `SufficiencyResult` | Baseline |
| Fit EWMA | BIN-65 | `Baseline`, `target_arl`, optional `smoothing_param` | `FittedEWMA` | Baseline |
| Fit CUSUM | BIN-94 | `Baseline`, `target_arl`, optional `reference_value`, optional `direction` | `FittedCUSUM` | Baseline |
| Fit Shewhart | BIN-95 | `Baseline`, `target_arl` | `FittedShewhart` | Baseline |
| Review artefact | BIN-66 | Any `FittedControlLimits` | Read properties; human-readable summary | Baseline |
| Compare provenance | BIN-68 | `ScoringResult`, `FittedControlLimits` | Confirms compatibility or raises `ProvenanceMismatchError` | Baseline |

**Fitting parameter semantics (ADR-004 section 5):**
- `target_arl`: **optional in Python signature** (default `None`), **required by Caliper validation**. Omitting raises `InvalidParameterError(kind="missing")`.
- `smoothing_param` (EWMA), `reference_value` (CUSUM): genuinely optional. `None` uses library default.
- `direction` (CUSUM): genuinely optional. `None` defaults to `"two_sided"`.

---

## Open Questions

| # | Question | Owner | Blocks | Source |
|---|----------|-------|--------|--------|
| 1 | **Where do scoring criteria attach?** At judge creation, at monitoring setup, or per-call? The feature files are deliberately neutral. | domain-modeller / product | `Judge` structure, `ScoringResult` creation | BIN-58 OQ-3 |
| 2 | **Criteria comparison mechanism.** Exact string match or normalised comparison for provenance equality? Affects both intra-baseline checking (BIN-63) and cross-phase comparison (BIN-68). | system-architect | `Provenance` equality semantics | BIN-63 OQ-6, BIN-68 OQ-2 |
| 3 | **Sufficiency check: internal or external to fitting?** Does fitting call sufficiency internally, or does the engineer call it first? Both designs satisfy the feature files. | domain-modeller | Fitting operation structure | BIN-65/94/95 OQ-3 |
| 4 | **Sufficiency override for testing.** Should the engineer be able to bypass sufficiency enforcement for exploratory fitting? | domain-modeller | Fitting operation parameters | BIN-65/94/95 OQ-4 |
| 5 | **Score range.** Fixed [0, 1], engineer-declared range, or unconstrained? The maths works on any bounded continuous range. No feature file asserts a range. | system-architect | `ScoringResult.score` constraints | BIN-59 OQ-2 |
| 6 | **Scoring input shape.** Does scoring take both agent input and output, or output alone? Feature files use "agent output" without specifying input. | product | `Judge.score()` signature | BIN-59 OQ-6 |
| 7 | **Serialisable form for audit logging.** Should the artefact provide a `to_dict()` or equivalent? The PRD recommends in-scope for BIN-66. | domain-modeller | `FittedControlLimits` interface | BIN-66 OQ-1 |
| 8 | **Observation identity.** Do observations carry a timestamp, sequence index, or neither? The feature files assert ordering without assuming a mechanism. | domain-modeller | `Observation` structure | BIN-63 OQ-3 |
| 9 | **Explicit override for known provenance change between phases.** Should an engineer who knowingly changed the judge be able to acknowledge and proceed? | product | `compare_provenance()` signature | BIN-68 OQ-3 |
| 10 | **Whether scoring accepts empty agent output.** Not tested in any feature file. | product | `Judge.score()` validation | BIN-59 OQ-5 |
| 11 | **Dual mismatch representation.** When both provenance dimensions differ, what shape does the error context take? (String, list, or paired entries.) | system-architect | `ProvenanceMismatchError.context["dimension"]` | BIN-68 OQ-1 |

---

## Validation Checklist

- [x] Every observation in the ten feature files is satisfiable by this model
- [x] No new aggregate duplicates an existing one (repo has no source code — no conflicts)
- [x] Every domain event name is past tense and unambiguous — N/A, no events in R1
- [x] Every VO has a `create()` factory and at least one constraint
- [x] No collection references another collection by object — only by value (Provenance)
- [x] Every term in the glossary appears in at least one feature file or ADR
- [x] Open Questions lists every ambiguity rather than resolving it silently
- [x] Both Shewhart spread quantities are present and distinguished (ADR-004 finding)
- [x] Provenance modelled as first-class VO with equality semantics left open (OQ-2)
- [x] No numerical constants pinned (no d_2, h, k, L, or ARL_0 values)
- [x] Error contract references ADR-002's nine types without inventing parallel concepts
- [x] Identity question addressed honestly: not needed in R1

---

## Changelog

- 2026-09-09: Initial model — BIN-100
