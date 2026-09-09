# ADR-006: Scoring API surface and judge provider port

**Status:** Accepted
**Date:** 2026-09-09
**Deciders:** system-architect (BIN-102), ratified by product owner
**Refs:** BIN-102, BIN-59, BIN-58, BIN-57, ADR-001, ADR-002, ADR-004

## Context

`BIN-59` ("Score a single agent output and receive structured results") cannot be
implemented without settling six open questions its feature file names explicitly
as owned by `system-architect`. The scenarios in
`tests/bdd/features/measurement/score-agent-output-structured-results.feature`
were written to survive any resolution -- they constrain capability without
prescribing mechanism -- but step definitions cannot be written that way. They
must call a concrete API, so whoever writes them settles every open question by
accident unless it is settled deliberately here.

This is the fourth architecture spike (`BIN-91` SPC engine, `BIN-96` error
contract, `BIN-99` fitted artefact protocol, this one). Two pieces of the domain
already exist and must not be contradicted:

- `src/caliper/measurement/judge.py` -- `ModelVersion`, `Judge.create(model_version)`.
  `Judge` is currently a frozen dataclass with a single field, `model_version`.
  Its BDD-approved test suite (`tests/unit/measurement/test_judge.py`,
  `tests/bdd/steps/judge_adapter_pinned_model_version_steps.py`) calls
  `Judge.create()` and `Judge.create(model_version=...)` with no other arguments,
  and asserts specific `InvalidParameterError` behaviour for a missing/empty/
  whitespace-only `model_version`. Any change to `Judge` must not require
  changing these calls or their expected errors.
- `src/caliper/measurement/criteria.py` -- `ScoringCriteria`, deliberately left
  unwired to `Judge` so `BIN-58` OQ-3 (criteria attachment point) could be
  decided freely here.
- `src/caliper/errors.py` -- the nine-type exception taxonomy (ADR-002),
  implemented and merged.

### Constraints carried forward

- **ADR-001:** score type is `float`; scores are higher-is-better.
- **ADR-002:** errors raise typed `CaliperError` subclasses; tests assert
  `isinstance` plus required `context` keys, never message text. `kind` on
  `InvalidParameterError` is a closed discriminator (`"missing"` / `"invalid"`);
  `reason` elsewhere is descriptive -- the two are not unified.
- **ADR-004:** `typing.Protocol` with `@runtime_checkable` is the established
  mechanism for a structural, non-inheriting seam (`FittedControlLimits`). The
  "optional-with-required-semantics" pattern (Python default `None`, Caliper
  raises `InvalidParameterError(kind="missing")` if still `None`) is the
  established way to give a business-required parameter a structured error
  instead of Python's `TypeError`, and is used **only** where a scenario
  actually asserts on it.
- **Errors raise; the caller decides** (ratified 2026-09-08). Caliper does not
  swallow, warn-and-continue, or return a default.
- **Judge model pinning fails loudly** (`BIN-57`, implemented).
- **No feature file changes permitted.** If a design requires editing
  `score-agent-output-structured-results.feature`, the design is wrong.
- **No new dependency is introduced by this ADR.** No live-version verification
  is therefore required here; a concrete LLM-provider adapter is a separate,
  later implementation concern.

### Sentry context

Not applicable. Caliper is a library with no runtime for Sentry to observe.

## Decision

### 1. The judge provider port: `JudgeProviderPort`

A new `typing.Protocol`, `@runtime_checkable`, following ADR-004's precedent
exactly: a structural contract a fake can satisfy without inheriting from
anything, so `Judge.score()` is testable without a network call.

```python
@runtime_checkable
class JudgeProviderPort(Protocol):
    """Port through which a Judge obtains a score and reasoning.

    A conforming implementation owns everything infrastructure-specific: the
    call to an LLM provider (or any other scoring backend), and interpreting
    its raw response into a score and reasoning. Caliper's domain layer never
    sees a provider SDK, an HTTP client, or a raw response payload.

    Exception contract (part of this Protocol -- cannot be expressed in
    Python's type system, so it is normative here):

    Raises:
        ProviderError: the call to the provider failed or the provider was
            unreachable. `context["provider"]`, `context["operation"]`.
        MalformedResponseError: the provider responded, but the response
            cannot be interpreted as a (score, reasoning) pair.
            `context["operation"]`, `context["expected_shape"]`.
        JudgeRefusalError: the provider declined to score due to a content or
            safety policy. `context["provider"]`, `context["operation"]`.
    """

    def score(
        self,
        *,
        model_version: str,
        criteria: str,
        agent_output: str,
        agent_input: str | None = None,
    ) -> JudgeProviderResponse: ...
```

```python
@dataclass(frozen=True, slots=True)
class JudgeProviderResponse:
    """Raw (score, reasoning) pair returned by a provider, before Caliper
    attaches provenance. Not exposed to the engineer -- internal to
    `Judge.score()`'s orchestration."""

    score: float
    reasoning: str
```

A test fake (`FakeJudgeProviderPort`) implements `score()` to either return a
fixed `JudgeProviderResponse`, or raise `ProviderError`, `MalformedResponseError`,
or `JudgeRefusalError` directly -- no network call, no provider SDK. This
satisfies the "provider returns an error" and "judge produces an
uninterpretable response" scenarios exactly as the feature file states them.

**Suggested location:** `src/caliper/measurement/provider.py`. Final placement
is domain-modeller's call.

**Why the port returns an already-parsed pair, not a raw payload:**
interpreting provider-specific structured-output mechanisms (OpenAI JSON mode,
Anthropic tool use, or anything else) is an infrastructure concern specific to
each provider's API shape. Pushing that interpretation into the domain layer
would leak infrastructure into `Judge`; pushing it into the port's
implementation keeps `Judge` provider-agnostic, matching the port pattern
`SPCPort` already established (ADR-001).

### 2. `Judge` gains a `score()` method; provider and criteria both attach optionally at creation (resolves "score method vs. separate collaborator" and `BIN-58` OQ-3)

**`Judge` gains a `score()` method.** The domain model already characterised
`Judge` as "an immutable configured adapter" with a `score(output, criteria?)`
operation; a separate collaborator (e.g. a `Scorer` that takes a `Judge` plus
criteria) would add indirection with no benefit, since `Judge` already holds
everything `score()` needs once it also holds a provider reference.

**`Judge` gains two new optional fields, both defaulted to `None`:**

```python
@dataclass(frozen=True, slots=True)
class Judge:
    model_version: ModelVersion
    provider: JudgeProviderPort | None = None
    criteria: ScoringCriteria | None = None

    @classmethod
    def create(
        cls,
        model_version: str | None = None,
        provider: JudgeProviderPort | None = None,
        criteria: str | None = None,
    ) -> Judge: ...
```

This is **purely additive** -- `model_version` validation order and behaviour
are unchanged, so every existing `test_judge.py` and
`judge_adapter_pinned_model_version_steps.py` call
(`Judge.create()`, `Judge.create(model_version=...)`, `Judge.create(model_version="")`)
continues to pass unmodified. No migration is required.

**`BIN-58` OQ-3 resolved: a combination of judge-creation and per-call attachment.**
Criteria may be supplied at `Judge.create(criteria=...)` (optional) and/or
per-call at `Judge.score(criteria=...)` (optional). Per-call criteria, when
given, is used for that call only -- it does not mutate the frozen `Judge` and
does not persist beyond the call. If neither is present, scoring fails with
`MissingPrerequisiteError` before the provider is ever called:

```python
def score(
    self,
    agent_output: str,
    *,
    agent_input: str | None = None,
    criteria: str | None = None,
) -> ScoringResult:
    if self.provider is None:
        raise MissingPrerequisiteError(
            "scoring requires a configured judge provider",
            context={"prerequisite": "judge_provider", "operation": "score"},
            recovery_hint="Pass provider=... to Judge.create().",
        )
    effective_criteria_raw = criteria if criteria is not None else (
        self.criteria.value if self.criteria is not None else None
    )
    if effective_criteria_raw is None:
        raise MissingPrerequisiteError(
            "scoring requires criteria",
            context={"prerequisite": "scoring_criteria", "operation": "score"},
            recovery_hint="Pass criteria=... to Judge.create() or to score().",
        )
    effective_criteria = ScoringCriteria(value=effective_criteria_raw)  # validates
    # ... output validation (section 6), provider call, ScoringResult assembly
```

**"Monitoring setup" is explicitly not a third attachment point in R1** -- no
`Monitor` construct exists anywhere in the current domain model (`docs/domain-model.md`
lists only `Baseline`, `Judge`, and the value objects). Inventing one now to
give criteria a third home would design beyond what `BIN-59` asks. If a
monitor-like construct is introduced later (`context.md`'s R2 decorator/context
manager stories), it becomes a third fallback in the same resolution order --
additive, not a redesign.

**`provider` is a functional dependency, not user data, and is not wrapped in
optional-with-required-semantics.** No scenario tests "create a judge with no
provider" as a structured-error case (only "score with no criteria" is
tested). Per the established rule -- optional-with-required-semantics is used
only where a scenario asserts on it -- a `Judge` with no provider is valid to
construct (mirrors how `criteria` can be absent at creation); the absence
surfaces as `MissingPrerequisiteError` at `score()` time, exactly like the
missing-criteria case. This also keeps `Judge.create()` fully backward
compatible with `BIN-57`'s tests.

### 3. Scoring signature: agent output required, agent input optional (resolves OQ-6)

> **Naming.** The parameters are `agent_output` and `agent_input`, not `output`
> and `input`. `input` shadows a Python builtin, which this project's own lint
> gate rejects -- `ruff` has `flake8-builtins` enabled and `A002` fires on it,
> verified against the configured ruleset rather than assumed. The `agent_`
> prefix also matches the ubiquitous language the feature files already use
> ("agent output", "agent input"), and costs nothing at the common call site
> because `agent_output` is positional.


```python
def score(
    self,
    agent_output: str,
    *,
    agent_input: str | None = None,
    criteria: str | None = None,
) -> ScoringResult
```

**Decision:** accept both, with `agent_output` required and `agent_input` optional. This
adopts the PRD's own recommendation (load-bearing: MEDIUM). Many judge rubrics
(relevance, instruction-following) are only meaningful with the input in view;
excluding it would make some criteria unscorable and would make the audit
trail incomplete for anyone reconstructing what was assessed later from logs
the caller kept.

**`agent_input` is not part of `Provenance` and is not carried onto `ScoringResult`.**
Provenance is the *measurement configuration* (model version + criteria) --
what instrument, calibrated how. `agent_input`/`agent_output` are the *subject being
measured*, and the engineer already holds both values they just passed in;
echoing them back onto the result is redundant and the feature file's
scenarios do not assert their presence there. This keeps `ScoringResult` at
the three fields the domain model already specifies (score, reasoning,
provenance) -- see section 7. If a later story needs the result to be
self-describing without the caller's copy of the input (e.g. persisted
observations, `BIN-63`), that story can add the field additively; it is not
required now.

`agent_input` is not validated for emptiness -- an agent that legitimately received
no input (a proactive/autonomous action) is a valid case, unlike an empty
`output`, which is the thing under assessment (section 6).

### 4. Retry: no retry inside the library in R1; the caller owns retry policy (resolves OQ-4)

**Decision: Caliper does not retry transient provider failures.** A
`JudgeProviderPort` implementation calls the provider once (from Caliper's
point of view -- "once" from the port's perspective) and raises `ProviderError`
immediately on failure. `Judge.score()` does not catch and retry it.

**This resolves the tension `BIN-102` named explicitly.** The ratified "errors
raise; the caller decides" rule states that transient provider failures are
"absorbed by retry inside the adapter before any of this applies" -- but that
sentence described an architectural *option* for where retry could live if it
existed; it never asserted that such retry exists, and left `BIN-59` OQ-4 open
precisely because nobody had decided. This ADR settles it: **for R1, that
retry layer does not exist.** The "errors raise" rule is unaffected -- it
governs what happens once Caliper has decided a call has failed, which is
still true on the very first attempt when there is no retry.

**Why no retry, not "give it a recommendation, not a survey":**

1. **The PRD's own Non-Goals section already settles this for `BIN-59`:**
   *"Retrying failed scoring calls (not now)... This story requires that
   failures propagate visibly; it does not require retry logic."* That PRD
   passed `requirements-reviewer` with zero blockers. This ADR is confirming
   an already-product-approved scope boundary, not making a fresh call that
   needs new ratification.
2. **Caliper is a library, not a service it operates.** Callers embedding
   Caliper into an LLM agent very likely already have a retry policy (their
   own HTTP client, their own provider SDK wrapper, `stamina`, `tenacity`, or
   similar) wrapping the same provider call elsewhere in their stack. A
   second, library-internal retry layer underneath the caller's own retry
   compounds latency and attempt count in a way the caller cannot see or
   configure -- the caller asked for 3 attempts and silently got 9.
3. **Retrying inside a measurement call changes its latency
   characteristics unpredictably.** A scoring call that can silently take
   3-8x longer under provider flakiness is a surprising thing for a
   synchronous library call to do without being asked.
4. **`ProviderError`'s meaning stays simple.** With no retry, `ProviderError`
   means exactly "this attempt to call the provider failed." Adding retry
   later does not change that meaning -- it only narrows *when* it is raised
   (after retries are exhausted, rather than after the first attempt). That
   is why this decision is safely reversible (see Consequences).

**Where a future retry would live, if added:** entirely inside a concrete
`JudgeProviderPort` implementation (e.g. wrapping calls with `stamina`,
already the standard's cross-project choice for exponential backoff), never
in `Judge.score()`. The Protocol's contract does not change -- callers of the
port still see either a `JudgeProviderResponse` or one of the three named
exceptions. This is additive, not a breaking change, whenever it happens.

**Flag for product owner:** none required beyond what the approved PRD
already settled. Recorded here for visibility since `BIN-102` asked for this
tension to be surfaced explicitly.

### 5. Score range: unconstrained, but must be a finite float (resolves OQ-2)

**Decision:** `ScoringResult.score` accepts any finite `float` -- no fixed
range (e.g. `[0.0, 1.0]`), no engineer-declared range. `NaN` and `+/-inf` are
rejected.

**Why not a fixed range:** LLM-judge rubrics use varying scales in practice
(0-1, 0-10, -1 to +1). Forcing every judge into `[0, 1]` would require
per-provider normalisation work this story's Non-Goals explicitly excludes
("Score normalisation or scaling (not now)... a downstream concern for
control limit fitting"). ADR-001 already noted the SPC maths (EWMA, CUSUM,
Shewhart) works on **any** bounded continuous range -- mean and sigma are
estimated empirically from whatever the observed scores are, with no
dependency on a declared scale.

**Why not an engineer-declared range:** would add configuration surface
(a `min`/`max` the engineer must supply and keep consistent with their judge's
actual rubric) to buy validation that is not needed until baseline fitting
(`E2-S3`, a later story) -- exactly the boundary the PRD draws between this
story and normalisation/scaling.

**Why reject non-finite values, given "unconstrained" otherwise:** this is
not a range constraint (fixed/declared/unconstrained) in the OQ-2 sense -- it
is a basic value-object invariant, the same class of check `ModelVersion` and
`ScoringCriteria` already apply in `__post_init__`. `BR-1` (PRD) requires
"every scoring call must produce either a complete result or a visible error
-- never a partial result, sentinel value, or silent failure." A `NaN` score
is exactly the kind of degenerate sentinel this rule exists to prevent from
silently entering a Phase I baseline; rejecting it is a direct, narrow
extension of `BR-1`, not new scope. Raised as `InvalidParameterError` with
`context = {"parameter": "score", "kind": "invalid", ...}`.

**Deferred, not decided here:** whether a later story (`E2-S3` fitting)
introduces its own range assumption is out of scope. This ADR does not
foreclose that -- adding a range check later is additive validation on
`ScoringResult` construction, which is a compatible change for scores that
already fall in range.

### 6. Empty agent output: rejected (resolves OQ-5)

**Decision:** `Judge.score(output=...)` rejects an empty or whitespace-only
`output`, raising `InvalidParameterError` (`context["kind"] == "missing"` when
`output` is `None`, `context["kind"] == "invalid"` when it is empty or
whitespace-only; `context["parameter"] == "output"`).

**Rationale:**

1. **Consistency with the codebase's existing validation posture.**
   `ModelVersion` and `ScoringCriteria` both reject empty/whitespace-only
   strings via `__post_init__`. Silently accepting an empty `output` -- the
   one string in this call that is the actual subject being measured -- would
   be an unexplained exception to that posture.
2. **The PRD names the ambiguity and this resolves it toward the safer
   default.** "The agent failed to respond" is a legitimate thing to want
   scored, but the PRD itself flags that an empty string is at least as
   likely to indicate a caller bug (forgot to capture the agent's actual
   output) as a real quality signal. If an engineer genuinely wants to score
   "the agent produced nothing," they can pass a caller-controlled
   non-empty sentinel string (e.g. `"[no response]"`) that a judge can
   evaluate meaningfully -- Caliper does not need to treat emptiness as
   content.
3. **Fails fast, protecting `BR-1`.** Rejecting immediately, before any
   provider call, surfaces a likely caller bug at the call site instead of
   producing a low-information score that could silently contaminate a Phase
   I baseline.
4. **Reversibility favours rejecting now.** Loosening a rejection later (to
   accept empty output) is backward compatible for existing callers.
   Tightening an acceptance into a rejection later would break any caller
   who came to rely on empty-output scoring. Starting strict is the
   direction that keeps optionality open.

### 7. `Provenance` and `ScoringResult` value objects

Both are frozen dataclasses with `__post_init__` validation, following the
pattern `ModelVersion` and `ScoringCriteria` already established -- **not**
the `Result[...]`-returning factories `docs/domain-model.md` specifies at
lines 277, 291, 309 and 335, which are wrong (logged on `BIN-100`, contradicts
ADR-002 and the ratified "errors raise" decision). This ADR does not
re-litigate that finding; it applies the correct pattern directly.

```python
@dataclass(frozen=True, slots=True)
class Provenance:
    """The measurement configuration that produced a score: model version +
    scoring criteria. Equality by value (both fields)."""

    model_version: str
    scoring_criteria: str

    def __post_init__(self) -> None:
        # Raises InvalidParameterError(kind="invalid") if either field is
        # empty or whitespace-only. Constructed only internally by
        # Judge.score() from already-validated ModelVersion/ScoringCriteria
        # values, so this is a defensive invariant, not a new engineer-facing
        # error path.
        ...


@dataclass(frozen=True, slots=True)
class ScoringResult:
    """Returned by Judge.score(). Immutable; equality by value (all fields)."""

    score: float
    reasoning: str
    provenance: Provenance

    def __post_init__(self) -> None:
        # Raises InvalidParameterError(kind="invalid", parameter="score") if
        # score is NaN or +/-infinite (section 5). reasoning and provenance
        # presence are enforced by the type signature; no additional
        # constraint on reasoning content is introduced (not tested by any
        # scenario).
        ...
```

**Suggested location:** `src/caliper/measurement/provenance.py` (`Provenance`)
and `src/caliper/measurement/result.py` (`ScoringResult`), mirroring the
existing one-value-object-per-module convention (`judge.py`, `criteria.py`).
Final placement is domain-modeller's call.

**Not decided here, deliberately:** `Provenance` equality mechanism (exact
string match vs. normalised comparison -- `docs/domain-model.md` Open Question
#2) is out of scope for `BIN-102`. It is owned by `BIN-63` OQ-6 / `BIN-68`
OQ-2, which are the stories that actually compare provenance across
boundaries; `BIN-59` only constructs and reads `Provenance`, it never compares
two instances for equality-with-tolerance. Deciding it here would be scope
creep.

## Alternatives considered

### Retry inside `Judge.score()` or inside a default provider adapter

**Rejected.** Considered wrapping the provider call in a bounded
retry-with-backoff before raising `ProviderError`. Rejected because: (a) the
PRD's Non-Goals already excludes retry from this story's scope; (b) it risks
compounding with a caller's own retry policy invisibly; (c) it would make
`ProviderError`'s latency-until-raised unpredictable for a synchronous library
call. Left as a fully reversible, purely additive option for a future,
concrete provider adapter -- never for the port contract or `Judge.score()`
itself.

### Scoring input shape: output only

**Rejected.** Would satisfy the feature file (which only names "agent
output"), but the PRD explicitly recommends including input, load-bearing
MEDIUM, on the grounds that many rubrics need the input in view and an
audit trail without the input is weaker. Excluding it is an option to revisit
only if a real rubric is shown to need output alone -- adding `agent_input` later
as optional-keyword is what this ADR already does, so there is nothing left
to add.

### Criteria attachment: monitoring setup as a third point, or judge-only, or per-call-only

**Judge-only (no per-call override) rejected:** would prevent an engineer
scoring several outputs with different, ad hoc rubrics through one judge
without constructing a new `Judge` per rubric -- unnecessary friction, and
the feature file's "no criteria available" scenario requires per-call absence
to be expressible regardless of judge-level state.

**Per-call-only (no judge-level attachment) rejected:** would force every
`score()` call to repeat the criteria argument even for the common case of
one judge scoring many outputs against one fixed rubric -- worse ergonomics
for the dominant use case, with no compensating benefit.

**Monitoring setup as a third attachment point, rejected for R1:** no
`Monitor` construct exists in the domain model. Inventing one to hold criteria
would design a new domain concept the PRD never asked for, purely to answer
an attachment-point question that judge-creation + per-call already answers
completely for every scenario in the feature file.

### Score range: fixed `[0.0, 1.0]`

**Rejected.** Would match "conventional ML score" intuition but forces every
judge rubric into that scale, which is exactly the normalisation work the
PRD's Non-Goals defers to `E2-S3`. ADR-001 already established the SPC maths
does not need a fixed scale. Fixing the range now and lifting it later would
be the safe direction reversibility-wise, but there is no signal in any
scenario or business rule that a fixed range is needed yet, so fixing it now
would be an unrequested constraint on judges whose native rubric is not
`[0, 1]`.

### Score range: engineer-declared range parameter on `Judge` or `ScoringResult`

**Rejected.** Adds configuration surface (a `min`/`max` that must be kept
consistent with the judge's actual rubric) for a benefit -- knowing the scale
for control-limit fitting -- that a later story (`E2-S3`) can add when it
actually needs it, without this story pre-committing to *where* that
declaration should live (`Judge`? `ScoringResult`? the fitting call itself?).

### Empty agent output: accepted, judge evaluates the absence

**Rejected.** Considered because "the agent failed to respond" is a
legitimate quality signal per the PRD. Rejected because it is indistinguishable,
from Caliper's position, from a caller bug (forgot to pass the real output),
and the codebase already rejects the structurally analogous empty/whitespace
case for every other string value object. The caller can represent "no
response" explicitly with their own sentinel text if they want it scored,
which achieves the PRD's stated goal without weakening the validation
posture.

### `Judge` requires a provider at construction (no `None` default)

**Rejected.** Would make `provider` follow the same shape as `model_version`
(required, validated, structurally enforced) which is more conceptually
consistent with "Judge is the measurement instrument" -- but it would break
every existing `BIN-57` test that calls `Judge.create()` or
`Judge.create(model_version=...)` with no `provider` argument, none of which
this ADR is permitted to touch without a migration story, and no scenario in
any feature file requires a structured error for a missing provider. Treating
`provider` the same way `criteria` is already treated (optional at creation,
required by the time `score()` actually runs) achieves the same safety with
zero migration cost.

### `Provenance`/`ScoringResult` as `Result[T, InvalidParameterError]` factories

**Rejected.** This is `docs/domain-model.md`'s specified shape, already
logged as wrong on `BIN-100`. It contradicts ADR-002 and the ratified
"errors raise; the caller decides" decision, and would require adding an
errors-as-values dependency this project does not have and is instructed
never to add.

## Consequences

### What changes

- `Judge` gains two new optional fields (`provider`, `criteria`), both
  defaulted to `None`. **Purely additive** -- no existing call site or test
  changes behaviour.
- `Judge` gains a `score()` method -- new capability, no existing behaviour
  affected.
- Two new modules are needed: the `JudgeProviderPort` protocol (+
  `JudgeProviderResponse`), and the `Provenance` / `ScoringResult` value
  objects. None of these existed before this ADR.
- `BIN-58` OQ-3 is resolved: criteria attach at judge creation and/or per
  call, with per-call taking precedence for that call.
- `BIN-59` OQ-2, OQ-4, OQ-5, OQ-6 are resolved as above.

### What does not change

- **ADR-001** is not amended. Score type remains `float`; higher-is-better
  convention is unaffected by an unconstrained range.
- **ADR-002** is not amended. The exception taxonomy is used as specified;
  no new category is introduced. `JudgeRefusalError`, already in the
  taxonomy, is wired into the port contract but was not invented here.
- **ADR-004** is not amended. Its Protocol/`@runtime_checkable` mechanism and
  optional-with-required-semantics pattern are reused, not altered.
- **No feature file changes.** Every scenario in
  `score-agent-output-structured-results.feature` is satisfiable exactly as
  written against the design above: the happy paths get score + reasoning +
  provenance; the provider-error and malformed-response paths propagate
  through the port unchanged; the missing-criteria path fails via
  `MissingPrerequisiteError` before any provider call; immutability holds
  because `ScoringResult` is frozen; the four error categories remain
  distinguishable by type and required context keys. **Confirmed: no change
  required.**

### Reversibility

- **Judge provider port (section 1):** low cost to reverse. It is a
  Protocol; a second, differently-shaped port could be introduced alongside
  it without touching `Judge` as long as `Judge.score()`'s orchestration is
  updated to call the new shape. No consumer outside `Judge` type-hints
  against it yet.
- **Criteria/provider attachment (section 2):** low cost to reverse.
  Removing the per-call override (narrowing to judge-only) would be a
  breaking change for any caller using it, but adding a third attachment
  point later (a future `Monitor`) is purely additive.
- **Scoring signature (section 3):** low cost to reverse. `agent_input` is
  optional-keyword; removing it later breaks any caller passing it, but nothing
  currently requires this ADR's shape to be final.
- **Retry (section 4):** low cost to reverse. Adding retry inside a future
  concrete provider adapter changes nothing about the port contract or
  `Judge.score()`; `ProviderError`'s meaning narrows (fires after retries
  exhausted, not after one attempt) but does not change type or required
  context.
- **Score range (section 5):** low-to-medium cost to reverse. Adding a range
  check later is compatible with all in-range historical data; rejecting
  previously-accepted out-of-range scores would break callers relying on
  wide-range judges, so any future range constraint should be opt-in
  (declared, not silently fixed).
- **Empty output (section 6):** low cost to reverse in the safe direction
  (loosening to accept empty output later is backward compatible); high cost
  in the other direction, which is exactly why the strict default was chosen
  now.
- **Provenance/ScoringResult shape (section 7):** medium cost to reverse.
  Adding fields (e.g. a timestamp) is additive; removing or renaming the
  existing three `ScoringResult` fields would break every consumer, including
  the not-yet-written `BIN-63` baseline recording.

## Related decisions

- **`BIN-59` OQ-1 (score type) and error-message-content OQ:** already
  resolved by ADR-001 and ADR-002 respectively. Not re-opened here.
- **`Provenance` equality mechanism** (`docs/domain-model.md` Open Question
  #2, `BIN-63` OQ-6 / `BIN-68` OQ-2): not resolved here. Deliberately deferred
  -- see section 7.
- **`ProvenanceMismatchError`'s dual-mismatch context shape** (`BIN-68` OQ-1):
  not resolved here. `BIN-59` never raises `ProvenanceMismatchError` --
  `Provenance` is only constructed and read in this story, never compared
  across a Phase I/II boundary.
- **`BIN-63` (record observations into baseline):** consumes `ScoringResult`
  and `Provenance` exactly as specified in section 7. No changes anticipated
  from this ADR's decisions.
- **A concrete `JudgeProviderPort` implementation** (wrapping a real LLM
  provider SDK): out of scope for this ADR. Whoever implements it must
  verify the SDK's current version live before pinning it as a dependency,
  per the project's standing rule -- this ADR introduces no such dependency
  itself.

## Note for `backend-test-writer`

- A `FakeJudgeProviderPort` (in-memory, no network) is sufficient to drive
  every scenario in the feature file: configure it to return a fixed
  `JudgeProviderResponse`, or to raise `ProviderError` or
  `MalformedResponseError`. `MissingPrerequisiteError` is never raised by the
  port itself -- it is raised by `Judge.score()` before the port is ever
  called, so the "no criteria" scenario needs no port configuration at all,
  just a `Judge` with no criteria resolvable (neither judge-level nor
  per-call).
- Assert on `isinstance(err, <Type>)` plus the required `context` keys listed
  in section 1 and `src/caliper/errors.py` -- never on message text (ADR-002,
  unchanged).
- The "different failure categories are distinguishable" scenario needs three
  independently configured `Judge`/`FakeJudgeProviderPort` pairs (or one fake
  reconfigured between calls) producing `ProviderError`,
  `MalformedResponseError`, and `MissingPrerequisiteError` respectively, then
  asserting pairwise-distinct `type()` and pairwise-distinct `recovery_hint`
  strings (distinctness of recovery guidance is assertable; its specific
  content is not, per ADR-002).
- The immutability scenario asserts on Python's `FrozenInstanceError` /
  `AttributeError` when attempting to reassign a `ScoringResult` field --
  not a `CaliperError` (ADR-002 section 7, unchanged).
