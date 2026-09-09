# ADR-002: Error contract — exception taxonomy with structured recovery guidance

**Status:** Accepted
**Date:** 2026-09-09
**Deciders:** system-architect (BIN-96), ratified by product owner
**Refs:** BIN-96, BIN-57, BIN-58, BIN-59, BIN-63, BIN-64, BIN-65

## Context

Caliper's six feature files written to date assert on errors in two incompatible
ways:

1. **Message content** (BIN-57, BIN-58): `"the message should include an example
   of correct usage"` -- requires judging what constitutes an "example" and
   produces brittle substring-matching tests.
2. **Error type/category** (BIN-59, BIN-63, BIN-64, BIN-65): `"programmatically
   classifiable as a <category>"` -- deterministic assertion on type identity.

The `requirements-reviewer` rejected pattern (1) as untestable on both BIN-57
(m1) and BIN-58 (m1). BIN-59 replaced it with pattern (2), and the reviewer
confirmed this genuinely resolves the problem. All E2 stories (BIN-63, BIN-64,
BIN-65) adopted pattern (2), but drift has already appeared: BIN-65 SC9 uses
"error indicating that" instead of "classifiable as", and SC10's distinguishability
test omits SC9's condition.

Nine category names were invented across five stories with no coordinating
contract:

| Source | Categories |
|--------|-----------|
| BIN-59 | provider failure, malformed response, missing prerequisite |
| BIN-63 | provenance mismatch, invalid observation |
| BIN-64 | invalid threshold configuration |
| BIN-65 | insufficient baseline, degenerate baseline, invalid parameter |

Some overlap: "invalid threshold configuration" (BIN-64) is a specific instance
of "invalid parameter" (BIN-65). "Invalid observation" (BIN-63) and "malformed
response" (BIN-59) are superficially similar but have different actors (engineer
vs judge) and different recovery paths. The BIN-59 reviewer (m2) flagged that
judge refusals (safety-filter blocks) fit none of the three BIN-59 categories.

Additionally, "recovery guidance" was required to be "present and distinct per
category" (BIN-59 BR-5), but three separate reviews flagged the step "describes
what the engineer should do next" as retaining residual interpretive quality
(BIN-59 m3, BIN-63 m2, BIN-65 m1). The exact assertable format was deferred to
system-architect as BIN-59 OQ-3.

### Constraints

- **Errors raise; the caller decides.** Ratified 2026-09-08. Caliper raises
  where it cannot do its job; abort/retry/degrade/log is the caller's policy.
- **Signals are not errors.** A drift signal is a successful measurement result,
  not a failure. `RaiseOnSignal` is opt-in.
- **Wrapper failure policy is open for R2.** The decorator (BIN-70) and context
  manager (BIN-71) wrap the caller's agent. This contract does not foreclose any
  failure policy for those wrappers.
- **Python 3.11/3.12/3.13** (BIN-83). No version-specific exception features are
  used (`ExceptionGroup` and `add_note` are available on all three but not needed
  for this design).

### Sentry context

Not applicable. Caliper is a library with no runtime to monitor.

## Decision

### 1. Exception type hierarchy: flat, one base, nine leaf types

```
CaliperError                          # base -- consumers can `except CaliperError`
  InvalidParameterError               # bad or missing parameter value
  MissingPrerequisiteError            # operation before required config is in place
  ProviderError                       # judge LLM provider failure
  MalformedResponseError              # judge response cannot be parsed
  JudgeRefusalError                   # judge declined (safety/content policy)
  ProvenanceMismatchError             # observation provenance != baseline signature
  InvalidObservationError             # input is not a complete scoring result
  InsufficientBaselineError           # baseline below minimum observation count
  DegenerateBaselineError             # baseline data is statistically unusable
```

All nine types inherit directly from `CaliperError`. No intermediate grouping
types. Consumers handle errors at two granularities:

- **Broad:** `except CaliperError` catches every Caliper failure.
- **Specific:** `except InsufficientBaselineError` catches one category.

Intermediate group types (e.g. `JudgeError`, `BaselineError`) can be inserted
into the MRO later as a non-breaking change if consumer demand emerges. They are
not needed at nine leaf types.

### 2. Consolidated taxonomy: nine categories, down from nine names

| Category string | Exception type | Replaces | Rationale |
|---|---|---|---|
| `invalid_parameter` | `InvalidParameterError` | BIN-64 "invalid threshold configuration" + BIN-65 "invalid parameter" | A threshold IS a parameter. One category for all bad/missing parameter values. |
| `missing_prerequisite` | `MissingPrerequisiteError` | BIN-59 "missing prerequisite" | Operation attempted before required config (e.g. scoring without criteria). Distinct from `invalid_parameter`: the system is not ready vs the call is wrong. |
| `provider_failure` | `ProviderError` | BIN-59 "provider failure" | Judge's LLM provider returned an error or was unreachable. |
| `malformed_response` | `MalformedResponseError` | BIN-59 "malformed response" | Judge produced a response that cannot be parsed. |
| `judge_refusal` | `JudgeRefusalError` | NEW (resolves BIN-59 m2) | Judge declined to score due to content/safety policy. Not a provider failure (provider responded), not malformed (response is parseable), not a missing prerequisite (system was configured). |
| `provenance_mismatch` | `ProvenanceMismatchError` | BIN-63 "provenance mismatch" | Observation's provenance differs from baseline's established signature. |
| `invalid_observation` | `InvalidObservationError` | BIN-63 "invalid observation" | Input to baseline recording is not a complete scoring result. NOT the same as `malformed_response` -- different actor (engineer vs judge), different recovery (fix your input vs investigate judge config). |
| `insufficient_baseline` | `InsufficientBaselineError` | BIN-65 "insufficient baseline" | Baseline below minimum observation count for fitting. |
| `degenerate_baseline` | `DegenerateBaselineError` | BIN-65 "degenerate baseline" | Baseline meets count but is statistically unusable (e.g. zero variance). |

**Collapses:** "invalid threshold configuration" (BIN-64) into `invalid_parameter`
-- a threshold is a parameter, and the recovery action is identical (fix the
value you passed).

**Additions:** `judge_refusal` -- resolves the ambiguity the BIN-59 reviewer
identified. BIN-59 BR-4's "at minimum" clause explicitly permits extension.

**Preserved distinctions:**
- `invalid_observation` vs `malformed_response`: different actors, different
  recovery paths. `malformed_response` = the judge returned garbage (investigate
  judge config); `invalid_observation` = the engineer passed an incomplete
  scoring result to the baseline (fix your input).
- `missing_prerequisite` vs `invalid_parameter`: different conditions.
  `missing_prerequisite` = the system isn't in the right state for this
  operation (scoring without criteria configured); `invalid_parameter` = you
  called the function with a bad value. The former is a sequencing problem, the
  latter is a value problem.
- `insufficient_baseline` vs `degenerate_baseline`: both block fitting but
  require different recovery. Insufficient: collect more data. Degenerate:
  investigate why scores show no variation (judge broken? rubric too coarse?).

### 3. Missing required parameter is subsumed under `invalid_parameter`

A missing required parameter (e.g. omitting false alarm tolerance in BIN-65) is
classified as `invalid_parameter`, not a separate category. The sub-case is
discriminated positively by a **required** `context["kind"]` field:

- `kind = "missing"` -- the parameter was not provided at all.
- `kind = "invalid"` -- a value was provided but violates the constraint.

When a value was provided, `context["provided"]` carries that value. When the
parameter was omitted, `context["provided"]` is absent -- but nothing asserts on
its absence. The discriminator is `kind`, which is always present and
positively assertable: `assert error.context["kind"] == "missing"`.

**Rationale:** The recovery action is the same -- fix your configuration. The
distinction between "you didn't pass it" and "you passed a bad value" is captured
in the structured context via a positively assertable field, without inflating
the taxonomy. Python's own `TypeError` (missing arg) vs `ValueError` (bad arg)
distinction exists at the language level; Caliper's domain taxonomy does not need
to replicate it because the consumer's branching decision is "is this a
configuration problem?" not "is this a missing-vs-bad-value problem?"

### 4. Recovery guidance: structured context fields, not prose

Every `CaliperError` carries three attributes:

```python
class CaliperError(Exception):
    category: str                  # stable identifier, e.g. "invalid_parameter"
    context: Mapping[str, Any]     # structured fields -- the testable contract
    recovery_hint: str             # human-readable suggestion -- NOT tested
```

**The testable contract is the `context` dict's key set, not the prose.**

Tests assert on:
1. `isinstance(error, SpecificErrorType)` -- or `error.category == "..."` --
   deterministic type/category check.
2. Required context keys are present with values of the expected types --
   deterministic field-presence check.
3. Different categories produce different `category` strings --
   deterministic string comparison for distinctness.

Tests **never** assert on:
- `str(error)` or `error.args[0]` (the message string)
- `error.recovery_hint` content (human-readable, may change without notice)
- Any substring of any prose field

The `recovery_hint` exists for engineers reading error output in logs and
REPLs. It is non-empty by construction but its content is not part of the
stable API contract. The `context` dict provides the same information in
machine-readable form.

#### Required context fields per category

These are the **guaranteed minimum fields** on every error of that category.
Implementations may add more. Removing a required field is a breaking change.

| Category | Required context keys | Purpose |
|---|---|---|
| `invalid_parameter` | `parameter: str`, `constraint: str`, `kind: str` | Which parameter is invalid, what constraint it violates, and whether the parameter was `"missing"` or `"invalid"`. `provided: Any` carries the supplied value when one was given. |
| `missing_prerequisite` | `prerequisite: str`, `operation: str` | What is missing and what operation it blocks. |
| `provider_failure` | `provider: str`, `operation: str` | Which provider failed and what operation was attempted. |
| `malformed_response` | `operation: str`, `expected_shape: str` | What operation produced the response and what shape was expected. |
| `judge_refusal` | `provider: str`, `operation: str` | Which provider refused and what was being scored. |
| `provenance_mismatch` | `dimension: str`, `expected: str`, `received: str` | Which provenance field differs (model_version or criteria) and the two values. |
| `invalid_observation` | `reason: str`, `missing_fields: list[str]` | Why the observation is invalid and which fields are missing. |
| `insufficient_baseline` | `have: int`, `need: int` | Current observation count and required minimum. |
| `degenerate_baseline` | `reason: str` | What makes the baseline degenerate (e.g. `"zero_variance"`). |

**Naming convention — `kind` vs `reason`.** These are deliberately different
keys because they are different kinds of field. `kind` on `invalid_parameter` is
a **closed discriminator** over a fixed set (`"missing"` / `"invalid"`) telling a
consumer which sub-case occurred. `reason` on `invalid_observation` and
`degenerate_baseline` is **descriptive** — it names what went wrong. Reusing one
key for both would mean a consumer could not interpret it without first
branching on `category`, and would weaken the distinctness argument below by
sharing the one field whose semantics vary.

**How distinctness is tested:** For any two errors from different categories:
- `error_a.category != error_b.category` -- string comparison, deterministic.
- The required context key sets differ structurally -- `insufficient_baseline`
  has `have`/`need`; `degenerate_baseline` has `reason`; `invalid_parameter`
  has `parameter`/`constraint`. No two categories share the same required key
  set.

This resolves BIN-59 OQ-3: the minimum testable contract for error content is
the `category` string and the `context` key set. No string matching required.

### 5. Judge refusals are a distinct category

A safety-filter refusal is:
- Not `provider_failure` -- the provider responded successfully.
- Not `malformed_response` -- the response is well-formed and parseable.
- Not `missing_prerequisite` -- the system was properly configured.
- Recovery differs from all three: investigate whether the evaluated content
  triggered safety filters, or whether the rubric instructions reduce false
  refusals.

`judge_refusal` is added as a ninth category. BIN-59 BR-4's "at minimum" clause
explicitly permits extension. The walking skeleton's three categories (provider
failure, malformed response, missing prerequisite) remain; `judge_refusal` is
available for stories that handle safety-filter responses.

### 6. The taxonomy is semi-open

The library defines a **closed set** of categories with documented context
fields. Third-party code can extend the taxonomy by subclassing `CaliperError`
with a new `category` string.

- `except CaliperError` always catches everything, including extensions.
- Library-defined `category` strings are a stable contract -- removing one is a
  breaking change; adding one is a minor-version change.
- Extensions must use unique `category` strings (enforced by convention, not
  runtime).
- The required context key sets for library categories are a stable contract.

### 7. Immutability violations are not `CaliperError`

BIN-57 SC6 (judge immutability), BIN-59 SC6 (result immutability), BIN-63 SC9
(observation immutability), and BIN-65 SC11 (fitted artefact immutability) test
structural guarantees enforced by Python's type system (frozen dataclasses,
read-only properties). These raise Python's built-in `AttributeError` or
`FrozenInstanceError`, not `CaliperError`. They are not part of the domain error
taxonomy because they are not operational failures -- they are programming
mistakes caught by the type system.

**Amendment (2026-09-09, `BIN-103`):** the value objects this section
describes are Pydantic `BaseModel` + `ConfigDict(frozen=True)` as of
`BIN-103`'s conformance pass, not stdlib frozen dataclasses. Verified
empirically against pydantic 2.13.5: assigning to a field on a frozen
`BaseModel` raises `pydantic_core.ValidationError` (a `ValueError`
subclass, message `"Instance is frozen"`), never `AttributeError` or
`dataclasses.FrozenInstanceError`. The conclusion this section reaches is
unchanged -- it is still not a `CaliperError`, still not part of the
domain taxonomy, still a programming mistake caught by the type system --
only the concrete exception type named above was wrong. Not rewritten in
place because it was a deliberate, ratified statement at the time it was
written (the code was dataclasses then); corrected here instead, per this
vault's convention of annotating rather than rewriting settled decisions.

## Rationale

### Why typed exceptions instead of a category field on one type

Python's exception handling is designed for type-based dispatch. `except
ProviderError` is idiomatic; `except CaliperError as e: if e.category ==
"provider_failure"` is not. Every major Python library (requests, httpx, boto3,
sqlalchemy) uses typed exception hierarchies. Caliper's consumers are Python
engineers embedding the library in their own agents -- they expect the Python
idiom.

### Why flat instead of grouped

Nine leaf types under one base is manageable. An intermediate grouping layer
(`JudgeError`, `BaselineError`, `ConfigurationError`) would add three types for
marginal benefit: `except CaliperError` already catches everything, and the
specific types catch specifics. The intermediate layer can be added later as a
non-breaking change (insert between `CaliperError` and the leaf in MRO).

### Why structured context instead of prose recovery guidance

Three separate reviews flagged "describes what the engineer should do next" as
retaining interpretive quality (BIN-59 m3, BIN-63 m2, BIN-65 m1). A prose
assertion like "the error tells the engineer to collect more observations" is
subjective -- one person's "tells" is another's "vaguely suggests."

Structured fields resolve this completely: `error.context["have"] == 15` and
`error.context["need"] == 25` IS the recovery guidance in machine-readable form.
The human-readable `recovery_hint` string provides the same information as prose
for log output, but tests never depend on it.

### Why `invalid_parameter` subsumes missing parameters

The alternative is a tenth type, `MissingParameterError`. Python distinguishes
`TypeError` (missing arg) from `ValueError` (bad arg), but this distinction
serves a different purpose: Python needs to separate "wrong number of arguments"
(caller used the wrong function signature) from "right number, wrong value."
Caliper's domain concern is "your configuration is wrong" -- whether the wrongness
is absence or invalidity, the recovery is the same: read the `parameter` and
`constraint` context fields, fix it. The sub-case is positively discriminated by
`context["kind"]` (`"missing"` vs `"invalid"`), so a test that needs the
distinction asserts `error.context["kind"] == "missing"` -- a positive check,
consistent with every other assertion in this contract.

## Alternatives considered

### A. Single exception type with a category enum field

A single `CaliperError` with a `category: ErrorCategory` enum. Consumers write
`except CaliperError` and switch on `error.category`.

**Rejected.** Python's exception system IS the dispatch mechanism. Catch-and-
switch is the C/Java pattern; Python engineers expect typed exceptions for control
flow. Type checkers, IDEs, and `except` clauses all work better with typed
exceptions. Every major Python library uses this approach.

### B. Deep hierarchy with intermediate grouping types

`CaliperError -> JudgeError -> ProviderError`. Three intermediate group types
providing `except JudgeError` convenience.

**Rejected for now.** Nine leaf types are manageable without grouping. The
intermediate types add learning cost for marginal benefit. Critically, they can
be added later as a non-breaking change (insert into MRO between base and leaf),
so deferring costs nothing. Building them now without consumer demand is
speculative API surface.

### C. Recovery guidance as prose strings, tested via substrings

Keep the current implicit pattern: guidance is a prose message, tests use
substring matching or subjective assertions.

**Rejected.** This is the pattern that failed. Three reviews flagged it as
retaining interpretive quality. Substring matching is brittle (implementation-
coupled) and produces tests that break when message wording improves. The
structured context approach provides the same information with deterministic
assertions.

### D. Closed taxonomy with no extension mechanism

Seal the category set. New categories require a new library version.

**Rejected.** BIN-59 BR-4's "at minimum" clause acknowledges the set may grow.
Python's class hierarchy naturally supports extension via subclassing. Sealing
the taxonomy would require a major version bump to add any category -- e.g. if
a future story discovers that "judge timeout" (distinct from provider failure)
needs its own category, that should be a minor-version addition, not a breaking
change.

### E. Missing parameter as a distinct tenth category

A `MissingParameterError` alongside `InvalidParameterError`, following Python's
`TypeError`/`ValueError` split.

**Rejected.** The recovery action is identical (fix your configuration). The
sub-case distinction is positively discriminated by `context["kind"]`
(`"missing"` vs `"invalid"`) -- a required field, assertable the same way as
every other context field in the contract. A tenth category for an edge case
of an existing category adds
taxonomy size without proportional clarity. Consumers asking "is this a
configuration problem?" should not need to catch two types.

### F. Error codes (numeric or string) on a single exception type

A single type with integer or string error codes, common in C-style APIs.

**Rejected.** Anti-Pythonic. The language provides typed exceptions as the native
dispatch mechanism. Error codes add an indirection layer that duplicates what
`isinstance` already provides.

## Consequences

### Positive

- **Deterministic test assertions.** Every error scenario can be tested with
  `isinstance` + context field checks. No string matching, no subjective
  judgment, no brittle substring tests.
- **Consistent cross-story contract.** All six feature files (and all future
  stories) use the same assertion pattern: classifiable by type, structured
  context, distinct per category.
- **Consumer-friendly Python idiom.** `except ProviderError` to retry, `except
  CaliperError` for broad handling. No learning curve beyond standard Python.
- **BIN-59 OQ-3 resolved.** The exact assertable format for error content is
  specified: `category` string + `context` key set.
- **BIN-59 m2 resolved.** Judge refusals have a dedicated category.
- **BIN-65 m1 drift resolved.** SC9's "error indicating that" aligns to
  "classifiable as invalid parameter."

### Negative

- **BIN-57 and BIN-58 require material scenario changes and re-review.** Five
  scenarios across two stories change from message-content assertions to
  type-classification assertions. Both stories' APPROVED reviews are
  invalidated for the affected scenarios. Cost: two re-reviews.
- **Nine exception types is a non-trivial API surface.** Consumers must learn
  which types to expect from which operations. Mitigated by: the hierarchy is
  flat, the base type catches everything, and each operation raises at most 3-4
  types (documented per-operation).

### Neutral

- **No new dependencies.** The error contract uses only Python builtins.
- **No version-specific features.** Works on Python 3.11, 3.12, and 3.13
  identically.

### Open dependency: missing-parameter expressibility depends on API surface

BIN-65 SC9 asserts that omitting the false alarm tolerance produces an
`InvalidParameterError` classifiable as `invalid_parameter` with
`kind = "missing"`. This is only possible if the parameter is
**optional-with-required-semantics** in the Python signature (e.g. defaulted to
`None`, or a key absent from a configuration mapping). If the API surface instead
makes the parameter a genuinely required positional or keyword argument, Python's
own `TypeError` is raised at the call site before any Caliper code executes --
no `CaliperError` is produced, and SC9's assertion cannot be written as stated.

Both outcomes are legitimate:
- **Optional-with-required-semantics:** `InvalidParameterError(kind="missing")`
  fires from inside Caliper. SC9 is implementable as written.
- **Genuinely required argument:** Python's `TypeError` fires before Caliper runs.
  SC9 would need to assert `TypeError` instead of `InvalidParameterError`, or
  the scenario would need rewording.

This ADR does not design the API surface. The dependency is recorded so that
`domain-modeller` and `backend-test-writer` confirm SC9's implementability when
the fitting interface is specified. If the API surface uses genuinely required
arguments for false alarm tolerance, the missing case belongs to Python's
`TypeError` and never reaches this taxonomy -- a legitimate outcome that does not
weaken the contract.

### Reversibility

**Medium cost.** The exception types are part of the public API. Removing a type
or renaming a `category` string is a breaking change. Adding types or context
fields is non-breaking. The decision to use typed exceptions over category enums
is effectively permanent once consumers write `except ProviderError` -- but this
is the Python standard, not a controversial choice.

## Related decisions

- **ADR-001 (BIN-91):** Score type resolved as `float`. Not affected by this ADR.
- **BIN-57 OQ-1:** Enforcement mechanism settled -- `InvalidParameterError` with
  `context={"parameter": "model_version", ...}`.
- **BIN-58 OQ-1:** Enforcement mechanism settled -- same pattern.
- **BIN-59 OQ-3:** Recovery guidance assertable format settled -- structured
  `context` fields.
- **BIN-59 m2:** Judge refusals resolved -- `JudgeRefusalError`.
- **BIN-65 m1:** SC9 drift resolved -- "classifiable as invalid parameter."

---

## Migration specification

This section specifies the exact changes required in each of the six existing
feature files to conform to the error contract defined above. Changes are
classified as **cosmetic** (wording alignment, review stands) or **material**
(assertion semantics change, requires re-review).

**Convention:** "classifiable as" means the test asserts `isinstance(error,
SpecificType)` or `error.category == "..."`. "Carries recovery guidance
identifying X" means the test asserts the relevant context field(s) are present.

---

### BIN-57: judge-adapter-pinned-model-version.feature

**Branch:** `trunk`
**Review status:** APPROVED (4 minor findings)
**Change classification:** MATERIAL -- 3 scenarios change assertion semantics

#### SC2: Engineer attempts to create a judge without specifying a model version

**Category:** `invalid_parameter`

Old:
```gherkin
    Then the judge should not be created
    And the engineer should be told that a model version is required for measurement stability
    And the message should include an example of correct usage
```

New:
```gherkin
    Then the creation fails with an error classifiable as an invalid parameter
    And the error identifies that the model version parameter is required
```

#### SC3: Engineer provides an empty string as the model version

**Category:** `invalid_parameter`

Old:
```gherkin
    Then the judge should not be created
    And the engineer should be told that a non-empty model version is required
    And the message should explain that model pinning protects measurement stability
    And the message should include an example of correct usage
```

New:
```gherkin
    Then the creation fails with an error classifiable as an invalid parameter
    And the error identifies which parameter is invalid and what is required
```

#### SC4: Engineer provides a whitespace-only string as the model version

**Category:** `invalid_parameter`

Old:
```gherkin
    Then the judge should not be created
    And the engineer should be told that a non-empty model version is required
    And the message should explain that model pinning protects measurement stability
    And the message should include an example of correct usage
```

New:
```gherkin
    Then the creation fails with an error classifiable as an invalid parameter
    And the error identifies which parameter is invalid and what is required
```

#### Unchanged scenarios

SC1 (happy path), SC5 (preservation), SC6 (immutability), SC7 (whitespace
padding): no change.

#### Re-review required

**Yes.** Three scenarios change from message-content assertions (rejected pattern)
to type-classification assertions (house pattern). The APPROVED review is
invalidated for SC2, SC3, SC4. Unchanged scenarios do not require re-review.

---

### BIN-58: scoring-criteria-text-rubric.feature

**Branch:** `trunk`
**Review status:** APPROVED (4 minor findings)
**Change classification:** MATERIAL -- 2 scenarios change assertion semantics

#### SC2: Engineer attempts to define empty criteria

**Category:** `invalid_parameter`

Old:
```gherkin
    Then the criteria should be rejected
    And the engineer should be told that criteria are required to anchor quality scores
    And the message should include an example of a valid rubric
```

New:
```gherkin
    Then the configuration fails with an error classifiable as an invalid parameter
    And the error identifies that non-empty criteria are required
```

#### SC3: Engineer attempts to define whitespace-only criteria

**Category:** `invalid_parameter`

Old:
```gherkin
    Then the criteria should be rejected
    And the engineer should be told that non-empty criteria are required to anchor quality scores
    And the message should include an example of a valid rubric
```

New:
```gherkin
    Then the configuration fails with an error classifiable as an invalid parameter
    And the error identifies that non-empty criteria are required
```

#### Unchanged scenarios

SC1 (happy path), SC4 (preservation), SC5 (multi-line), SC6 (minimal), SC7
(whitespace padding): no change.

#### Re-review required

**Yes.** Two scenarios change from message-content assertions to type-
classification assertions. The APPROVED review is invalidated for SC2, SC3.

---

### BIN-59: score-agent-output-structured-results.feature

**Branch:** `trunk`
**Review status:** APPROVED (3 minor findings)
**Change classification:** COSMETIC -- 2 scenarios tighten recovery guidance
assertion per OQ-3 resolution. MATERIAL if judge refusal scenario is added.

#### SC3: Provider error during scoring propagates to the engineer

**Category:** `provider_failure`

Old:
```gherkin
    And the error describes what the engineer should do next
```

New:
```gherkin
    And the error carries recovery guidance identifying the provider and the failed operation
```

**Change type:** Cosmetic. The review explicitly deferred the exact assertable
format to system-architect (OQ-3). This resolves it. The classifiability
assertion on the preceding line is unchanged.

#### SC4: Malformed judge response fails visibly

**Category:** `malformed_response`

Old:
```gherkin
    And the error describes what the engineer should do next
```

New:
```gherkin
    And the error carries recovery guidance identifying the expected response shape
```

**Change type:** Cosmetic. Same reasoning as SC3.

#### SC5: Scoring without criteria fails before reaching the judge

**Category:** `missing_prerequisite`

No change. "The error identifies that scoring criteria are required" is already
deterministic and maps to `context["prerequisite"]`.

#### SC7: Different scoring failure categories are distinguishable

No change to existing three-category test. The test remains valid: provider
failure, malformed response, and missing prerequisite are three of the nine
library categories and must be distinguishable within BIN-59's scope.

#### Recommended addition: judge refusal scenario

The BIN-59 reviewer (m2) flagged that judge refusals do not fit the three
existing categories. This ADR defines `judge_refusal` as a ninth category. A
scenario exercising this case should be added to BIN-59, and SC7 should be
updated to test four-category distinguishability.

**This addition is MATERIAL and requires re-review.** It adds a new error case
not in the original requirements.

#### Unchanged scenarios

SC1, SC2 (happy paths), SC5 (missing prerequisite), SC6 (immutability), SC7
(distinguishability): no change.

#### Re-review required

**No** for the cosmetic SC3/SC4 changes alone. **Yes** if the judge refusal
scenario is added (recommended but separable).

---

### BIN-63: phase-i-baseline-collection.feature

**Branch:** `feat/BIN-63/phase-i-baseline-collection` (unmerged)
**Review status:** APPROVED (3 minor findings)
**Change classification:** COSMETIC -- 3 scenarios tighten recovery guidance

#### SC5: Recording fails when model version differs

**Category:** `provenance_mismatch`

Old:
```gherkin
    And the error describes what the engineer should do next
```

New:
```gherkin
    And the error carries recovery guidance identifying which provenance dimension differs
```

#### SC6: Recording fails when criteria differ

**Category:** `provenance_mismatch`

Same change as SC5.

#### SC7: Recording something that is not a complete scoring result fails

**Category:** `invalid_observation`

Old:
```gherkin
    And the error describes what the engineer should do next
```

New:
```gherkin
    And the error carries recovery guidance identifying what the input is missing
```

#### SC10: Recording errors are distinguishable by category

No change. The two-category test (provenance mismatch vs invalid observation)
is valid under the consolidated taxonomy.

#### Unchanged scenarios

SC1-SC4 (happy paths), SC8 (provenance signature), SC9 (immutability), SC10
(distinguishability): no change.

#### Re-review required

**No.** All changes are cosmetic refinements of the recovery guidance assertion
step, resolving the residual interpretive quality flagged in BIN-63 m2. The
APPROVED review stands.

---

### BIN-64: baseline-sufficiency-check.feature

**Branch:** `feat/BIN-64/baseline-sufficiency-check` (unmerged)
**Review status:** APPROVED (re-review, 0 findings)
**Change classification:** COSMETIC -- 1 scenario aligns category name

#### SC11 (Scenario Outline): Engineer configures a threshold that is not positive

**Category:** `invalid_parameter` (was "invalid threshold configuration")

Old:
```gherkin
    Then the check rejects the configuration as an invalid threshold
    And the rejection guides the engineer that the threshold must be a positive value
```

New:
```gherkin
    Then the check fails with an error classifiable as an invalid parameter
    And the error identifies which parameter is invalid and what the valid range is
```

**Change type:** Cosmetic. The BIN-64 re-review added this scenario specifically
to cover invalid threshold values. The assertion intent is identical; only the
category name aligns to the consolidated taxonomy (`invalid_parameter` instead
of `invalid threshold`).

#### Unchanged scenarios

SC1-SC10, SC12: no change.

#### Re-review required

**No.** The category name alignment is a direct consequence of the taxonomy
consolidation and does not change what condition is tested.

---

### BIN-65: ewma-control-limit-fitting.feature

**Branch:** `feat/BIN-65/ewma-control-limit-fitting` (unmerged)
**Review status:** APPROVED (2 minor findings)
**Change classification:** COSMETIC -- 3 scenarios, resolving m1 drift

#### SC5: Fitting fails when baseline is insufficient

**Category:** `insufficient_baseline`

Old:
```gherkin
    And the error guides the engineer to collect more observations before fitting
```

New:
```gherkin
    And the error carries recovery guidance to collect more observations before fitting
```

**Change type:** Cosmetic. Aligns to "carries recovery guidance" convention.
The preceding two lines ("error classifiable as an insufficient baseline" and
"error reports how many observations") are unchanged and already correct.

#### SC6: Fitting fails when baseline has zero variance

**Category:** `degenerate_baseline`

Old:
```gherkin
    And the error guides the engineer on what to do next
```

New:
```gherkin
    And the error carries recovery guidance for addressing the zero-variance condition
```

**Change type:** Cosmetic. Same convention alignment. The preceding line ("error
explains that EWMA control limits require score variation") is unchanged.

#### SC9: Fitting fails when no false alarm tolerance is specified

**Category:** `invalid_parameter`

Old:
```gherkin
    Then the fitting fails with an error indicating that a false alarm tolerance is required
    And no control limits are produced
```

New:
```gherkin
    Then the fitting fails with an error classifiable as an invalid parameter
    And the error identifies that a false alarm tolerance parameter is required
    And no control limits are produced
```

**Change type:** Cosmetic. This is the drift case flagged in BIN-65 m1. The
change aligns SC9 to the "classifiable as" convention already used in SC5-SC8.
The m1 finding explicitly called for this alignment.

#### SC10: Fitting errors are distinguishable by category

No change. The three-category test (insufficient baseline, degenerate baseline,
invalid parameter) is valid. SC9's error (missing tolerance) maps to
`invalid_parameter`, which is already the third case in SC10. This resolves
the m1 finding that SC10 omitted SC9's condition: SC9 IS `invalid_parameter`,
so it IS included.

#### Unchanged scenarios

SC1-SC4 (happy paths), SC7-SC8 (invalid parameter outlines), SC10
(distinguishability), SC11 (immutability), SC12-SC13 (boundary outlines): no
change.

#### Re-review required

**No.** All changes are cosmetic convention alignment. SC9's fix was
specifically requested by the BIN-65 reviewer (m1). The APPROVED review stands.

---

### Migration summary

| File | Branch | Scenarios changed | Change type | Re-review? | Categories mapped |
|---|---|---|---|---|---|
| BIN-57 | trunk | SC2, SC3, SC4 | Material | **Yes** | `invalid_parameter` |
| BIN-58 | trunk | SC2, SC3 | Material | **Yes** | `invalid_parameter` |
| BIN-59 | trunk | SC3, SC4 | Cosmetic | No (unless judge refusal added) | `provider_failure`, `malformed_response`, `missing_prerequisite` |
| BIN-63 | unmerged | SC5, SC6, SC7 | Cosmetic | No | `provenance_mismatch`, `invalid_observation` |
| BIN-64 | unmerged | SC11 | Cosmetic | No | `invalid_parameter` |
| BIN-65 | unmerged | SC5, SC6, SC9 | Cosmetic | No | `insufficient_baseline`, `degenerate_baseline`, `invalid_parameter` |

**Total: 14 scenarios change across 6 files. 5 are material (BIN-57 + BIN-58),
9 are cosmetic (BIN-59 + BIN-63 + BIN-64 + BIN-65). 2 stories require
re-review.**

**Re-review cost:** BIN-57 (3 changed scenarios out of 7) and BIN-58 (2 out
of 7). Both re-reviews are narrowly scoped to the error-handling scenarios;
the happy-path and edge-case scenarios are unaffected.

**`kind` field impact on migration:** The addition of `context["kind"]` as a
required field for `invalid_parameter` (amendment, distinguishing `"missing"`
from `"invalid"`) does not move any scenario from cosmetic to material. BIN-64
SC11 (zero/negative threshold) and BIN-65 SC7/SC8 (invalid smoothing/tolerance)
implicitly describe the `"invalid"` sub-case -- the step text references what is
wrong with the value. BIN-65 SC9 (missing tolerance) implicitly describes the
`"missing"` sub-case -- the step text says the parameter "is required." The step
definitions will assert `kind` internally; the Gherkin wording already
disambiguates the condition without naming the field.

**API-shape dependency (BIN-65 SC9):** Whether a missing false alarm tolerance
surfaces as `InvalidParameterError(kind="missing")` or as Python's `TypeError`
depends on the API surface design (not yet made). If the fitting interface uses
a genuinely required Python argument, `TypeError` fires before Caliper code
runs and SC9 would need rewording. This must be confirmed when the API surface
is designed. See the open dependency note in Consequences.
