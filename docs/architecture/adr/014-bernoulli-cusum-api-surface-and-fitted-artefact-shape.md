# ADR-014: Bernoulli CUSUM — API surface, Phase II input contract, and the fitted artefact's shape

**Status:** ✅ **ACCEPTED — ratified in full by the product owner 2026-09-23**
**Date:** 2026-09-23
**Refs:** BIN-133, ADR-004, ADR-006, ADR-011, ADR-012 (referenced, not edited), ADR-013 (referenced, not edited)

---

## Context

ADR-012 and ADR-013 (both ACCEPTED) settle the Bernoulli CUSUM's statistical
design in full: the shift lever (`detect_rate_multiple`, default 2.0), the
derived reference value, the sign convention (higher-is-better, "failure
rate" means `1 − score`), two-sided-by-default, and Guaranteed In-Control
Performance (GICP) — designing at `p_U`, the Clopper–Pearson upper confidence
bound on the observed failure rate, with `α = 0.10`.

Neither ADR settles the concrete Python API surface, the fitted artefact's
field shape, or the Phase II recording contract. Both explicitly defer these
to this pass (ADR-012 "what this deliberately does not decide"; ADR-013
"what this deliberately does not decide"). The PRD's requirements review
(`requirements-review.md`, second pass, 2026-09-23) confirms: 0 of 17
scenarios in `tests/bdd/features/baseline/bernoulli-cusum-control-limit-fitting.feature`
are bindable today, because every `When` step reduces to an entry point that
does not exist in any form in `src/`.

This ADR answers the six questions the PRD and the prior architecture review
left for this pass: whether ADR-011's `target_arl` tiering transfers (OQ-2);
whether a binary score is declared or inferred (OQ-4); the Phase II input
contract (OQ-5, contested at review); the detection-disclosure's name and
shape; whether `α` is ever engineer-facing; and the two-sided artefact's
concrete shape, including whether it satisfies `FittedControlLimits`.

**Every one of the 17 scenarios remains bindable, without rewording, against
the design below.** No scenario is named a field, a formula, or a numeric
literal — see the feature file's own header comments, which confirm this
deliberately.

**Codebase state, verified directly (not inherited):** `src/drift_caliper/`
contains no `bernoulli` or `clopper_pearson` module, and no `gicp` reference
anywhere. `fitted_control_limits.py`'s `sigma_estimate` docstring reads,
verbatim: *"The OPERATIONAL sigma used by ALL chart types for control limit
computation."* This claim is load-bearing for Decision 6 below.

---

## Decision 1 (OQ-4): the binary score is inferred at fit time, not declared

**`Baseline`/`ScoringResult` gain no new field.** A "binary baseline" is
simply a `Baseline` whose recorded `ScoringResult.score` values happen to be
exactly `0.0` or `1.0`. `fit_bernoulli_cusum` validates this itself, at fit
time, against the baseline it is handed.

```python
def fit_bernoulli_cusum(
    baseline: Baseline,
    *,
    target_arl: float | None = None,
    detect_rate_multiple: float | None = None,
    direction: str | None = None,
) -> FittedBernoulliCUSUM: ...
```

Mirrors ADR-012 §1's worked example and ADR-004 §5's optional-with-required
signature shape exactly — no new parameter-semantics pattern.

**Validation order** (baseline-related checks precede request-parameter
checks, mirroring `fit_cusum`'s existing order):

1. `require_type(baseline, Baseline, ...)` — existing helper, unchanged.
2. **New:** every `baseline.observations[i].score` is exactly `0.0` or
   `1.0`. A baseline containing any other value (including a legal,
   finite, in-range continuous score) raises
   `InvalidParameterError(parameter="baseline", kind="invalid")` —
   `context["reason"] = "score_not_binary"`, and the offending value plus
   its position are reported so the engineer can find it.
3. `target_arl`, `detect_rate_multiple`, `direction` — parameter-level
   validation (Decisions 5, 6).
4. `baseline.check_sufficiency()` — ADR-005's unchanged 100-floor (ADR-013 §2).
5. GICP design (`p̂`, `p_U`), degenerate-rate handling (ADR-013 §5),
   calibration.

**Why infer, not declare.** Three reasons, in order of weight:

1. **The PRD's own Non-Goals rule this out for this release**: *"Declaring
   a binary score 'type' on `ScoringResult`... Not now."* A declared kind
   is explicitly out of scope, and would be a much larger, riskier change
   — `ScoringResult` is a public type every existing chart already
   constructs against, and ADR-006's `Provenance`-typing note records that
   this exact class of value-object decision has already proven expensive
   to reverse once (`Provenance` holding `ModelVersion`/`ScoringCriteria`
   rather than `str`).
2. **`BIN-61` (multiple scoring dimensions) is explicitly still open** and
   interacts with any declared-kind design. Deciding a kind now risks
   designing against a scoring-dimension shape that BIN-61 later changes.
3. **Inference costs nothing extra Caliper doesn't already pay.** Every
   `fit_*` function already validates its baseline's content (zero-variance
   check, sufficiency check). Checking "is every score in `{0.0, 1.0}`" is
   the same shape of check, on the same data, at the same point in the
   call.

**Alternatives considered:**

- **Declare a `kind: Literal["continuous", "binary"]` on `ScoringResult` or
  `Baseline`.** Rejected — out of PRD scope (Non-Goals, explicit), and
  premature ahead of BIN-61.
- **A separate `BinaryBaseline` wrapper type**, constructed explicitly by
  the engineer from a `Baseline`. Rejected: it adds a second collection
  type on a public surface for zero behavioural gain over inference (the
  content check has to happen either way — wrapping it earlier only moves
  *when* the check runs, not whether it's needed), and CLAUDE.md's DX
  principle flags exactly this shape of cost ("two overlapping collection
  types on a public surface is the failure mode").
- **Silently coerce out-of-set values** (round to nearest of `{0.0, 1.0}`,
  or treat any value `≥ 0.5` as a pass). Rejected outright — this is
  precisely the silent-miscalibration failure class the project's error
  taxonomy exists to prevent (ADR-002; the `bool`-rejection precedent,
  `BIN-132`). A rounding rule is also an invented threshold with no
  citation.

---

## Decision 2 (OQ-5): the Phase II input contract — reject anything not exactly `0.0` or `1.0`

**Decided on the merits, with the contest in front of me** (the PRD's OQ-5
addendum records `requirements-reviewer`'s partial disagreement with
`bdd-scenario-writer`'s type-boundary exemption).

**I agree with the contest, not with the exemption it was raised against.**
`bdd-scenario-writer`'s reasoning — *"a language with a real two-valued type
... could not construct the malformed input at all"* — is true only if you
grant its premise, that today's situation is equivalent to a missing type.
It is not. `requirements-reviewer`'s counter-argument is the sharper read
of the codebase as it actually stands: Caliper's `float` score type is not
an accident of Python's dynamic typing (the shape `BIN-126`/`BIN-104`
exempted) — it is ADR-006's own **deliberate, ratified** decision ("Score is
unconstrained but must be finite"), applied uniformly, on purpose, to every
chart including this one. `0.73` reaching a Bernoulli-fitted `Monitor` is
not Python letting a wrong type through a gap nobody designed; it is
Caliper's own chosen design offering a value this chart's statistics cannot
interpret. Applying the project's own test — *"would the question still
exist in a language with a different type system?"* — the honest answer is
**yes**: even a hypothetical Caliper with a real `Pass | Fail` sum type
would still have had to *choose* whether every chart shares one score type
or each chart declares its own, and Decision 1 above just chose the former,
deliberately, for this release. The question is about Caliper's design, not
about Python's type system, so it does not qualify for the exemption.

**Decision: a Phase II observation checked against a `FittedBernoulliCUSUM`
whose `.score` is not exactly `0.0` or `1.0` is rejected, no tolerance
band, via `InvalidObservationError`.**

```python
monitor = Monitor(fitted_bernoulli_chart)

result = monitor.record(judge.score(agent_output))   # score is 0.0 or 1.0 -- succeeds

try:
    monitor.record(judge.score(other_agent_output))  # score is 0.42
except InvalidObservationError as e:
    assert e.category == "invalid_observation"
    assert e.context["reason"] == "score_not_binary"
```

**Category choice: `InvalidObservationError`, not `InvalidParameterError` or
a new category.** `InvalidObservationError`'s existing scope ("An input to
baseline recording is not a complete scoring result") is narrower in its
current docstring than the concept it names. Both `Baseline.record()` and
`Monitor.record()` already raise it for the same underlying situation —
*this thing you are trying to record cannot be accepted for the recording
operation you are attempting* — and today's only instance of that
(incompleteness) is one case of it, not the definition of it. Broadening
the docstring to cover *"...either because it is not a complete
`ScoringResult`, or because its score is not a value the specific fitted
chart can interpret"* is a natural extension of what the category already
means, not a redefinition.

`missing_fields` (an existing required context key) is `()` for this case —
nothing is missing; the value present is simply outside the domain this
chart can interpret. This is the same shape of conditional-presence
precedent `InvalidParameterError.provided` already establishes (present
only when relevant, absent otherwise, per ADR-002 §3) — no ADR-002 change
needed, only a docstring broadening implementers should make in
`errors.py`.

**No tolerance band, deliberately.** An epsilon (e.g., accept `0.999` as
"close enough" to `1.0`) would itself be an invented, uncited constant —
exactly what CLAUDE.md's "invent no numbers" discipline forbids. A
continuous-valued score reaching a binary-fitted `Monitor` is far more
likely to indicate the wrong chart was called, or the wrong dimension of a
multi-dimension `ScoringResult` was passed (once BIN-61 exists), than
floating-point noise from a boolean-derived value — silently accepting it
would hide exactly that mistake.

**Where the check runs.** `Monitor.record()` gains a third precondition,
gated on the artefact's concrete type, inserted after the existing
provenance check and before the existing chart-specific `_check` dispatch:

```
1. isinstance(observation, ScoringResult)          -- existing, unchanged
2. compare_provenance(observation, self._artefact)  -- existing, unchanged
3. NEW: if isinstance(self._artefact, FittedBernoulliCUSUM):
             observation.score must be exactly 0.0 or 1.0
4. self._check(observation.score)                   -- existing dispatch,
                                                         gains a fourth branch
```

This mirrors the method's existing "validate every precondition before any
state mutates" discipline (docstring: *"Only once both checks pass does the
chart-specific comparison run"*) — this is a third check of the same kind,
not a new mechanism.

**Alternatives considered:**

- **No scenario, no explicit contract — inherit the type-boundary
  exemption as `bdd-scenario-writer` applied it.** Rejected for the reasons
  above; this is the position being overturned.
- **Reuse `InvalidParameterError`** (`parameter="observation.score"`).
  Rejected: `InvalidParameterError` is documented and used throughout this
  codebase for a *function's own* parameters (`target_arl`,
  `reference_value`, `direction`, `baseline`) — a case can be made that
  `observation` is `Monitor.record`'s parameter, but its *field* failing a
  chart-specific interpretability constraint is a different shape of
  failure from a parameter itself being out of range, and
  `InvalidObservationError` already exists, at the same call site, for
  exactly "this recorded thing is not acceptable here."
  `InvalidObservationError` is the closer, and already-established, fit.
- **A new tenth category** (e.g. `invalid_score_domain`). Rejected: the
  taxonomy is semi-open for genuinely new failure *kinds*, but this is not
  one — it is the same kind of failure (`InvalidObservationError`'s "this
  thing cannot be recorded here") as the existing incompleteness case,
  just with a different `reason`. Adding a category for every distinguishable
  `reason` would defeat the purpose of `reason` being descriptive rather
  than a second closed discriminator (ADR-002's `kind`-vs-`reason`
  distinction, which this project has already been warned once not to
  conflate).
- **A tolerance band around `{0.0, 1.0}`.** Rejected — see above.

---

## Decision 3 (OQ-2): ADR-011's `target_arl` tiering does not transfer as numbers; two narrower things do

**ADR-011's hard floor (100) and advisory band (`[100, 370)`) are not
applied to `fit_bernoulli_cusum`.**

**What transfers, and why:**

1. **The coherence floor (`ARL₀ ≥ 1`) transfers unchanged.** It is a
   definitional fact about any stopping time's expectation (`E[N] ≥ 1`),
   independent of chart type. No measurement needed.
2. **A computed attainability floor transfers *in kind*, not as a number.**
   Exactly as `BIN-117` established for the continuous CUSUM,
   `fit_bernoulli_cusum` must compute the smallest `ARL₀` actually
   reachable by its own design (given the lattice-quantised reference
   value(s) and the search bracket's floor) and refuse a `target_arl`
   below it, reporting the true floor in `context` so it round-trips as an
   accepted input (`BIN-122`'s rule) — mirroring
   `_min_attainable_arl0`/`_require_attainable_target_arl` exactly, not a
   new mechanism.

   ⚠️ **Superseded 2026-09-24 by Amendment 2, Decision 12** — the item above
   was never implemented, and on measurement the Bernoulli lower arm's floor
   is exactly `1/p_U` whatever the lattice, with a 2.8–3.3× gap to the next
   attainable value. Refusing below it would leave large zero-failure
   baselines unfittable two-sided at any target. The ratified replacement:
   **fit, report `achieved_arl` honestly, and disclose** via
   `FittingAdvisory(kind="lower_arm_signals_on_first_failure")`. The text
   above is kept as the original decision.

**What does not transfer, and why — stated precisely, not just asserted:**

ADR-011's hard floor and advisory band exist for one specific reason: *"the
field does not tabulate it"* (hard floor) and *"Caliper has never checked
its own calibration against a published value in that region"* (advisory).
Both claims are about a gap between an **approximation** (Markov-chain for
EWMA, Siegmund's diffusion approximation for continuous CUSUM) and the
**published table** that verifies it at a handful of points.

**The Bernoulli CUSUM has no approximation to verify this way.** ADR-012
§4/§5 is explicit that this chart ships *because* its `ARL₀` is **exact** —
a finite Markov chain, linear solve, no discretisation error beyond the
reference value's own lattice quantisation (ADR-012 §3, "report, don't
chase"). There is no approximation-vs-table gap for a literature floor to
be gatekeeping against, at any `target_arl`. The gap ADR-011 discloses does
not exist here to disclose.

**What ADR-012 §3's existing mechanism already does instead, at every
`target_arl`, low or high:** the artefact reports `achieved_arl` next to
`requested_arl`, exactly computed for the chart actually constructed. Any
lattice-quantisation gap between what was requested and what was achieved
is *already* fully disclosed by comparing the two fields — this is a
stronger, chart-native disclosure than a borrowed literature-coverage tier
would add, because it is exact and specific to the fit in hand rather than
a coarse "you're in a flagged band" flag.

**What this ADR does not decide, and does not invent a number for:**
whether lattice-quantisation error (ADR-012 §3's measured 0.05%–5.06% at
`target_arl = 370`) grows large enough at *low* `target_arl` to warrant its
own advisory is unmeasured. The prior architecture review recommended
extending ADR-012 §3's own study to lower `target_arl` values as the
correct way to settle this, and that study has not been run. No advisory
of this shape ships in this release; a future amendment may add one once
that study exists.

**Alternatives considered:**

- **Copy ADR-011's `100`/`370` verbatim.** Rejected — see above; the
  rationale underlying both numbers is specific to approximation-vs-table
  verification, which does not apply.
- **Set new, chart-specific literature-style thresholds.** Rejected —
  there is no literature table for this exact construction (GICP-designed
  Bernoulli CUSUM) to set a threshold against; inventing one would violate
  "invent no numbers."
- **No floor at all, not even the computed attainability one.** Rejected
  — `BIN-117`'s finding (a silent bottom-out at the search bracket's floor,
  reporting a far-higher achieved ARL as if it were the requested one) is
  chart-agnostic; nothing about GICP or exactness makes the Bernoulli
  CUSUM immune to the same root-finding failure mode.

---

## Decision 4: the detection-disclosure figure is a first-class field, not routed through `FittingAdvisory`

ADR-013 §4 defines `expected_detection_arl` precisely (the exact `ARL₁` of
the constructed chart, evaluated at `p̂ × detect_rate_multiple`, falling
back to `p_U × detect_rate_multiple` at `f = 0`) but leaves its **routing**
open between two candidates: `FittingAdvisory.boundary` (already a `float`)
or a first-class artefact field.

**Decision: first-class field, `expected_detection_arl: float`.**

**Reasoning.** `FittingAdvisory` (ADR-011) is built for **optional,
conditional** disclosures — the type's own module docstring and every
current producer (`parameter_guards.classify_target_arl`, firing only
inside the `[100, 370)` band) agree: `advisories` is `()` "when there is
nothing to disclose." `expected_detection_arl` is not conditional. Every
one of Story 1 and Story 2's happy-path scenarios asserts it on the
**main** fitting path, unconditionally — "the fitted chart reports how
quickly it is expected to catch the degradation it is tuned to detect" is
not a corner-case assertion. A quantity every fit reports belongs beside
`requested_arl`/`achieved_arl` as a first-class field, in the same shape
every other always-present figure already takes — not folded into a
`kind`/`description`/`boundary` triple built for the different, genuinely
optional case. Routing it through `FittingAdvisory.boundary` would also
force the actual number to be re-derived from `description`'s prose to be
machine-readable in the way DX demands ("context exists to be branched on
without parsing prose") — `boundary` alone, decoupled from a `kind`
discriminator distinguishing "this is the detection figure" from some
future, genuinely-optional advisory that also happens to carry a `float`,
is a worse machine-readable contract than a named field.

`advisories: tuple[FittingAdvisory, ...] = ()` is still carried on
`FittedBernoulliCUSUM`, for forward compatibility with ADR-005's still-
unbuilt middle-tier baseline-adequacy advisory (which does apply to binary
baselines — ADR-013 §2 leaves ADR-005's floor, and by extension its
still-unbuilt middle tier, unchanged for binary charts) — empty today,
since no producer for *this* chart exists yet.

**Alternatives considered:**

- **`FittingAdvisory.boundary`, as ADR-013 §4 proposed.** Rejected for the
  unconditional-vs-conditional reason above. ADR-013 explicitly left this
  open for this pass ("system-architect's implementation pass may
  reasonably rename it, provided the *definition* survives") — this ADR
  exercises exactly that latitude.
- **A different name than `expected_detection_arl`.** Considered and kept
  — it is accurate, and nothing found during this pass improves on it.

---

## Decision 5: `α` stays a fixed internal library constant, not engineer-facing, in this release

**Decision: `α = 0.10` (ADR-013's ratified value) is not a parameter on
`fit_bernoulli_cusum`.** It is reported on the fitted artefact
(`alpha: float`), for auditability, but cannot be supplied by the caller.

**Reasoning.** ADR-013 §3's own grid is precise about how narrow the
verified range is: of five `α` values tested (`0.05, 0.075, 0.10, 0.125,
0.15, 0.20`), only three (`0.075, 0.10, 0.125`) cleared ADR-005's ratified
5% appetite on their *upper confidence bound*, and `0.125` did so only
marginally (4.97% against the 5% bar — the ADR's own words: "genuinely
marginal, close enough that a different simulation seed could plausibly
tip it over"). Exposing `α` as a caller-settable parameter would let an
engineer choose a value **outside that five-point grid entirely** — with
no verification behind it at all — and silently break the guarantee GICP
exists to provide, the opposite of informed choice: the engineer would
have no way to know which values are safe without re-deriving ADR-013 §3's
own study themselves.

This is not the same shape of decision as `detect_rate_multiple` (which
*is* engineer-facing). `detect_rate_multiple`'s legal range is checked
mechanically at every call (`p_U · M < 1`), and any value inside it
produces a chart whose reported `achieved_arl`/`expected_detection_arl`
are exactly, honestly computed — there is no way to pick an *unsafe*
`detect_rate_multiple` that the library would silently mis-verify. `α`, by
contrast, governs a **probabilistic coverage guarantee** — "does the
false-alarm promise actually hold" — that was only checked at five
specific values. A parameter whose safe range cannot be checked
mechanically, only by a study Caliper does not re-run per call, is exactly
what BR-5's reasoning (an engineer should not be asked to validate a
statistical parameter's legal range themselves) already argues against for
a different parameter in this same chart family.

**Reversibility: low cost.** Exposing `α` later is additive (a new optional
parameter, defaulting to the current fixed value) and does not break
anything constructed under the fixed value. This is deliberately the
direction of least regret — the same asymmetry principle ADR-011 and
ADR-006 both already apply (loosen later, don't tighten later).

**Alternatives considered:**

- **Expose `α` as an optional parameter, defaulting to `0.10`.** Rejected
  for the reason above — nothing stops an engineer supplying an
  unverified value.
- **Expose `α` but restrict it to the five values ADR-013 §3 actually
  measured.** Considered more seriously — it would at least keep every
  reachable value verified. Rejected for this release on cost-vs-benefit:
  it adds real API surface (a second tuning axis, with its own validation
  and its own place in every worked example) for a benefit — choosing
  among three defensible values (`0.075`/`0.10`/`0.125`) that ADR-013 §3
  itself already weighed and ratified one of. Revisit if a concrete need
  for `α = 0.125`'s detection-power recovery (ADR-013 §3's own trade-off
  table) materialises in practice — ADR-013 already names this as a live,
  revisitable option.

---

## Decision 6: the two-sided artefact's shape, and it does not satisfy `FittedControlLimits`

### 6a. `FittedBernoulliCUSUM` does not conform to `FittedControlLimits`

**Checked against the actual contract in `src/`, not assumed.**
`fitted_control_limits.py`'s `sigma_estimate` property is documented,
verbatim: *"The OPERATIONAL sigma used by ALL chart types for control
limit computation on individual observations."* This is true today because
every chart that satisfies the protocol — EWMA, continuous CUSUM, Shewhart
— genuinely standardises its statistic by the moving-range sigma before
comparing it to a limit.

**The Bernoulli CUSUM does not.** Its statistic accumulates the raw
pass/fail value directly against a probability-space reference value
(`r`), derived from a log-likelihood ratio over `(p_U, p₁)` — nowhere does
`sigma_estimate` enter its calibration. Populating a `sigma_estimate` field
on `FittedBernoulliCUSUM` (even a mechanically well-defined moving-range
sigma of the raw `0`/`1` sequence — which is computable, just unused) would
make the protocol's own documented claim, *"used by ALL chart types,"*
false the moment this chart ships, while giving a reader the false
impression that the number does something. This is exactly the class of
misrepresentation ADR-004 §3 already refused once, at the detection-
boundary level (declining to collapse CUSUM's decision interval into an
observation-scale limit pair because it would misrepresent the mechanism)
— the same argument, one level up, at the artefact-protocol level.

**Decision: `FittedBernoulliCUSUM` satisfies `HasProvenance`** (ADR-004's
2026-09-12 amendment — the two-attribute protocol `compare_provenance`
already accepts) **and is otherwise its own type**, reporting its own,
honestly-scoped field set (below). It does not satisfy the twelve-attribute
`FittedControlLimits`.

**Consequence, stated rather than left implicit:** `Monitor.__init__`'s
parameter is currently typed `artefact: FittedControlLimits`. Accepting a
`FittedBernoulliCUSUM` (which `Monitor` must, to construct a monitor for
this chart) needs that signature widened — e.g. to
`FittedControlLimits | FittedBernoulliCUSUM`, or an explicit union alias.
`Monitor.__init__`'s runtime check is already a concrete-type `isinstance`
tuple, not a protocol check (BIN-120), so this changes only the static
type hint, not the runtime behaviour shape — but it is real follow-up work
for `domain-modeller`/`domain-implementer`, not zero-cost. `Monitor.record()`
also gains a fourth `_check` dispatch branch (`_check_bernoulli_cusum`) and
the Decision 2 precondition.

This narrows a claim ADR-004's amendment made ("all artefacts carry two
spread measures... applies to all three chart types") to "all *continuous*
chart types" as a practical matter, without editing ADR-004 or ADR-012/013.
A future ADR-004 amendment could formalise this narrowing explicitly if
useful; recorded here since it is the direct cause of this decision.

**Alternatives considered:**

- **Force conformance, reporting a mechanically-computed but operationally
  unused `sigma_estimate`.** Rejected — see above; it would make the
  protocol's own documented contract false and mislead a reader into
  thinking the figure is used.
- **Redefine `sigma_estimate`'s contract to mean "a reported spread
  statistic, operational or not, per chart."** Rejected — this quietly
  weakens an existing, working contract for every *other* chart to
  accommodate one new one, trading a true claim for a vaguer one across
  the whole protocol rather than scoping the change to where it is
  actually needed.
- **A second protocol, `FittedControlLimits2` or similar, with a smaller
  shared surface covering all four chart types.** Considered. Rejected for
  now on the same cost-vs-benefit ADR-004 §3 already applied to
  `DetectionBoundary`: worth revisiting if a *third* chart type also fails
  to fit `FittedControlLimits`, at which point a genuine common subset
  might justify a new protocol. One new chart type is not yet that
  signal.

### 6b. Field shape

```python
class FittedBernoulliCUSUM(FittedArtefactBase):
    # -- reporting core (HasProvenance + Bernoulli-specific) --
    chart_type: str                    # "bernoulli_cusum"
    observed_failure_rate: float       # p-hat = f / m
    observation_count: int             # m
    provenance_model_version: str
    provenance_criteria: str
    requested_arl: float
    achieved_arl: float
    expected_detection_arl: float      # ADR-013 section 4's definition; Decision 4
    calibration_method: str            # see 6c
    advisories: tuple[FittingAdvisory, ...] = ()   # empty today; Decision 4

    # -- Bernoulli-specific design surface --
    detect_rate_multiple: float        # M
    alpha: float                       # 0.10, fixed; reported not settable -- Decision 5
    p_u: float                         # the Clopper-Pearson upper bound actually used
    direction: str                     # "two_sided" (default), "lower", "upper"
    reference_value_lower: float       # r for the degradation-detecting arm
    decision_interval_lower: float     # h for the degradation-detecting arm
    reference_value_upper: float       # r for the improvement-detecting arm
    decision_interval_upper: float     # h for the improvement-detecting arm
```

`reference_value_upper`/`decision_interval_upper` are present regardless of
`direction` (mirroring how `FittedCUSUM.direction` is reported even though
only some arms are *checked* at Phase II — `Monitor._check_cusum` already
establishes "both sums always updated regardless of `direction`" as the
existing convention; the equivalent here is "both arms always designed and
reported regardless of `direction`," for the same auditability reason: an
engineer inspecting the artefact can see what a direction change *would*
produce without refitting). ⚠️ *Corrected by Amendment 2's corrigendum, below (C3), ratified 2026-09-24: an artefact carries only the arms its `direction` checks.*

No `target_value`/`sigma_estimate`/`sigma_estimation_method`/
`baseline_spread` fields — deliberately absent (6a); there is no raw-scale
target or operational sigma for this chart to report. No `baseline_mean` —
`observed_failure_rate` is the one summary statistic ADR-012/013's own
vocabulary uses throughout and Story 1's scenario asks for by name
("reports the observed failure rate"); reporting its complement too would
be redundant, not informative.

`FittedArtefactBase` is still the base class (for the "every float field
finite" postcondition, BIN-142) — its `sigma_estimate` field-validator is
declared with `check_fields=False` and simply does not fire on a type that
declares no field by that name, verified against `fitted_artefact_base.py`
directly. No change needed there.

`__bool__` forbidden, `ConfigDict(frozen=True)`, `audit_summary()` — same
conventions as every other `Fitted*` type (BIN-110, BIN-108).

### 6c. Both arms' calibration is exact, via a joint Markov-chain solve — not the continuous chart's harmonic-combination approximation

**Do not copy `_combine_two_sided_arl0` from the continuous CUSUM.**
`cusum_fitting.py` combines two one-sided `ARL₀`s via Montgomery's Eq. 9.7,
which is itself an **approximation** — acceptable there because the
continuous CUSUM's whole `ARL₀` computation (Siegmund's diffusion
approximation) is already approximate; combining two approximations
approximately costs nothing additional in kind.

**That reasoning does not transfer.** ADR-012 §4/§5's entire justification
for shipping the Bernoulli CUSUM *before* the EWMA is that its `ARL₀` is
**exact** — a finite Markov chain, independently cross-checked. Reusing an
approximate combination formula for the two-sided case would silently
reintroduce approximation into the one property that justified shipping
this chart first, undermining exactly the claim ADR-012 §4/§5 makes about
it.

**Decision: the two-sided `achieved_arl` and `expected_detection_arl` are
computed via an exact joint two-armed Markov-chain solve** — state space
the Cartesian product of both arms' bounded lattices (each individually
finite per ADR-012 §4's own argument), a single Bernoulli(`p`) draw
updating both accumulators each step, solved once for the combined
in-control (`p = p_U`) and once for the alternative (`p = p̂ × M` or the
`f = 0` fallback, per ADR-013 §4) hypothesis. One-sided configurations
(`direction = "lower"`/`"upper"`) are unaffected — ADR-012's existing
single-arm exact solve already covers them fully; only the `"two_sided"`
combination needs new work.

**This is unmeasured, unverified numerical work, and this ADR does not
supply it.** The joint construction described above is a real, new
Markov-chain derivation — the same order of work ADR-012 §1 did for the
single-arm reference value, and ADR-013 §7 sets the verification bar any
such derivation must clear before it gates public behaviour (a
postcondition on every solve, at least two independent implementations,
judged on a confidence bound where applicable, posted to the ticket in
full). Neither exists yet. This ADR decides **which method must be used**
(the exact joint solve), not the formula itself, which is
`domain-modeller`/`schema-designer`/`domain-implementer`'s work, to the
same rigour ADR-012/013 already demonstrated.

**A named, honest fallback, in case the joint solve proves intractable
within this release's timeline.** If it does, `fit_bernoulli_cusum` may
fall back to the harmonic-combination approximation (identical to the
continuous chart's method) **only if** the fitted artefact's
`calibration_method` says so explicitly —
`"gicp_markov_chain_harmonic_combination"` rather than ⚠️ *corrected by the corrigendum, below (C5).*
`"gicp_markov_chain"` — so the artefact never silently claims an exactness
property it does not have. This is not a decision to ship the fallback; it
is a decision that *if* it ships, it must be named honestly. Preferred:
`"gicp_markov_chain"`, the exact joint solve, ship-blocking if not ready.

**Alternatives considered:**

- **Reuse `_combine_two_sided_arl0` verbatim.** Rejected — see above;
  silently reintroduces approximation into the chart shipped specifically
  *because* it avoids approximation.
- **Ship one-sided only in this release, defer two-sided.** Considered.
  Rejected: ADR-012's amendment already ratified two-sided-by-default
  (not reopened here), and two of Story 2's six scenarios directly assert
  two-sidedness as the default behaviour — deferring it would reopen a
  settled decision and fail two ratified scenarios. The exact joint solve
  is real work but is implementation effort, not a reason to reopen a
  design decision.
- **Ship the harmonic-combination approximation silently, without a
  distinguishing `calibration_method` string.** Rejected outright — this
  is precisely the silent-miscalibration-under-a-plausible-label failure
  class ADR-013 §7 exists to guard against, generalised from "a wrong
  number" to "an honest-looking but wrong claim about which method
  produced it."

### 6d. `p_U` substitutes for `p₀` in both arms' design-point formulas, consistently — with an unverified-coverage caveat, stated rather than hidden

ADR-013 §1 states the substitution rule generally: `p_U` replaces `p̂`
"as the design's 'in-control rate'" wherever ADR-012's design rule
references it. ADR-012's amendment §2 states the upper (improvement-
detecting) arm's design point as `p₀ / detect_rate_multiple` — using the
same symbol, `p₀`, that the primary arm's formula uses and that ADR-013
substitutes `p_U` for.

**Decision: `p_U` substitutes for `p₀` in both arms**, consistently —
lower arm: `p₁ = M · p_U`; upper arm: design point `= p_U / M` — both
against the same shared reference point `p_U`. This is the literal,
minimal application of ADR-013 §1's stated rule to every place ADR-012's
formula used the symbol it substitutes, inventing no new formula.

**Flagged, not resolved, because it needs its own verification ADR-013 did
not do:** Heidema et al.'s GICP proof establishes its coverage guarantee
(`P[conditional ARL₀ ≥ target] ≥ 1 − α`) for detecting a parameter
**increase** — the direction where an *upper* confidence bound is the
conservative choice. The upper arm here detects a **decrease** (an
improvement event). Whether an upper bound (`p_U`) is still the
conservative, coverage-preserving choice for *that* direction's own
false-alarm guarantee, or whether it should instead use a *lower*
confidence bound (mirroring `p_U`'s role but on the opposite tail), has
not been derived or measured on this ticket. ADR-013 §4 itself considered
and declined to adopt a lower-confidence-bound companion figure for a
different purpose (a conservative detection-speed disclosure) — the
question here is related but distinct (the upper arm's own **false-alarm**
coverage, not its detection speed).

**Practical consequence, stated plainly:** the `α = 0.10` GICP coverage
guarantee ADR-013 §3 proved is proven for the **lower (degradation-
detecting) arm only**. The upper arm's `achieved_arl` is exactly computed
for whatever `p_U`-derived design it gets (6c's exactness argument still
holds — the *number* is trustworthy for the parameters used) but whether
that design's *own* false-alarm probability meets the 1 − α standard is
**unverified**, not merely unmeasured-and-probably-fine. This is not
invented away; it is recorded here as the honest state of the two-sided
mode at ship time, and flagged as the next natural extension of ADR-013 §3's
grid (a mirrored study, at the upper arm's own design point) for a future
amendment.

**Alternatives considered:**

- **Use `p̂` (the plain estimate) for the upper arm, `p_U` only for the
  lower.** Considered. Rejected for now on consistency grounds (one
  substitution rule, uniformly applied, is simpler to implement, test, and
  explain) and because it would not actually resolve the open coverage
  question either — `p̂` has no proven coverage property for this arm any
  more than `p_U` does; it would just be a different unverified choice.
- **Derive and verify a proper lower-confidence-bound construction for the
  upper arm now.** The statistically correct next step, and explicitly
  not ruled out — but it is unmeasured, real numerical work of ADR-013 §7's
  calibre, out of place to improvise inside this API-surface ADR. Named as
  follow-up work, not performed here.
- **Disable the upper arm entirely pending that verification** (ship
  `direction="two_sided"` as documented but silently only checking the
  lower arm). Rejected outright — this would make the artefact's own
  `direction` field lie about what it does, precisely the kind of silent
  mismatch this project's error-taxonomy discipline exists to prevent.

---

## Worked example (the code an engineer actually types)

```python
from drift_caliper.baseline import fit_bernoulli_cusum, Baseline
from drift_caliper.monitoring import Monitor
from drift_caliper.errors import (
    InsufficientBaselineError,
    InvalidObservationError,
    InvalidParameterError,
)

# ... baseline populated via baseline.record(judge.score(...)) as usual,
# scores happening to be 0.0/1.0 -- no separate declaration.

chart = fit_bernoulli_cusum(baseline, target_arl=370)

chart.observed_failure_rate     # p-hat -- what "normal" looks like here
chart.p_u                       # the conservative bound the design used
chart.requested_arl             # 370.0
chart.achieved_arl              # the exact false-alarm ARL0 this chart delivers
chart.expected_detection_arl    # how fast it's expected to catch a real doubling
chart.detect_rate_multiple      # 2.0 -- the documented default
chart.direction                 # "two_sided"
chart.alpha                     # 0.10 -- reported, not settable

# Tune to a known degradation, one-sided:
chart = fit_bernoulli_cusum(
    baseline, target_arl=370, detect_rate_multiple=3.0, direction="lower"
)

# The round-trip guarantee (BIN-122 / ADR-013 section 6b):
try:
    fit_bernoulli_cusum(baseline, target_arl=370, detect_rate_multiple=50.0)
except InvalidParameterError as e:
    max_m = e.context["max_detect_rate_multiple"]      # computed from p_u
    fit_bernoulli_cusum(baseline, target_arl=370, detect_rate_multiple=max_m)  # succeeds

# All-failed baseline -- same category, distinguishable reason, no round-trip value:
try:
    fit_bernoulli_cusum(all_failed_baseline, target_arl=370)
except InvalidParameterError as e:
    assert "max_detect_rate_multiple" not in e.context   # no value would work
    assert e.context.get("reason") == "all_baseline_judgements_failed"

# Phase II:
monitor = Monitor(chart)
monitor.record(judge.score(agent_output))          # score 0.0/1.0 -- succeeds

try:
    monitor.record(judge.score(other_output))       # score 0.42
except InvalidObservationError as e:
    assert e.context["reason"] == "score_not_binary"
```

---

## Consequences

**Positive.** All 17 feature-file scenarios become bindable against this
design without rewording. OQ-2, OQ-4, OQ-5, the detection-disclosure
routing, `α`'s exposure, and the artefact's protocol conformance are all
settled, closing every item the PRD and the prior architecture review left
open for this pass. `Monitor`'s existing "validate, then dispatch"
discipline extends by one precondition and one branch, not a new
mechanism. The exactness property that justified shipping this chart
before the EWMA (ADR-012 §4/§5) is preserved rather than quietly
undermined by an approximate two-sided combination.

**Negative.** `FittedBernoulliCUSUM` not conforming to `FittedControlLimits`
is a real, if narrow, precedent break — the first chart type whose fitted
artefact does not satisfy the shared reporting protocol, and it costs a
`Monitor.__init__` signature widening plus a `_check` branch that a fully-
conforming type would not have needed. The two-sided mode ships with an
explicitly unverified coverage property on its upper arm (Decision 6d) —
disclosed, not hidden, but a genuine gap a future amendment must close.
The exact joint two-armed Markov-chain solve (6c) is new, real, unverified
numerical work this ADR does not supply — a ship-blocking dependency for
the two-sided mode specifically, named honestly via `calibration_method`
if a fallback is used instead.

**Neutral.** `α` staying internal is additive to expose later. The
`InvalidObservationError` docstring broadening (Decision 2) is a
documentation change with no behavioural impact on existing callers — the
category, required keys, and every existing raise site are unchanged.

**Reversibility.** High on `calibration_method`'s exact string and the
`p_u`/`alpha` field names — cosmetic, behind a reported value. Moderate on
not conforming to `FittedControlLimits` — reversible by adding the missing
fields later (additive), but doing so honestly would require either
computing a genuinely-unused `sigma_estimate` (the thing this decision
specifically avoids) or a documented exception carved into the protocol's
own contract. Low on the two-sided calibration method (6c) — the *method*
decision (exact joint solve vs. approximation) is effectively permanent
once `calibration_method` values are public and consumers may branch on
them; a later switch from the approximate fallback to the exact solve is
safe (values converge, string changes), the reverse is not.

---

## What `domain-model.md` will need — not changed here

- A new **"FittedBernoulliCUSUM"** entry under **Chart-Specific
  Artefacts**, per Decision 6b's field table — explicitly noting it is
  **not** a `FittedControlLimits` conformer (Decision 6a), the first such
  case, alongside the existing `FittedEWMA`/`FittedCUSUM`/`FittedShewhart`
  entries which remain conformers.
- A new **Library Operations** entry for `fit_bernoulli_cusum`, mirroring
  the existing `fit_cusum` entry's shape.
- **The Dual-Spread Distinction** section's "all charts" framing needs a
  narrowing note: the moving-range sigma discussion applies to the three
  *continuous* chart types; `FittedBernoulliCUSUM` has no sigma-based
  quantity at all (Decision 6a).
- **`Monitor`**'s Object Map entry needs its accepted-artefact-types list
  extended, and a note on the new Decision 2 precondition.
- **Error Contract Reference**: `InvalidObservationError`'s entry gains
  the `reason == "score_not_binary"` case; `InvalidParameterError` gains
  the `parameter == "baseline"` / `reason == "score_not_binary"` and
  `parameter == "detect_rate_multiple"` /
  `reason == "all_baseline_judgements_failed"` cases.
- **Open Questions**: OQ-2, OQ-4, OQ-5 (as inherited from the PRD/prior
  review) should be marked settled by this ADR, with a note that Decision
  6d's upper-arm coverage gap is a **new**, narrower open question this
  ADR introduces rather than one it closes.

This is `domain-modeller`'s step, not performed here.

---

## Amendment 2026-09-23 — lattice correctness defect and cost-bounding

**Status:** ✅ **ACCEPTED — ratified by the product owner 2026-09-23**, with the joint state cap set at 1,000,000 (Decision 10b).

⚠️ **Partly corrected and extended by Amendment 2 (2026-09-24), below.** Its §0 records three claims in this amendment that measurement disproved — one-sided fits "never exceed ~40,000 states", the refusal bisection "completes in under 1 s", and "`target_arl = 370` fits every baseline" — and Decisions 13–14 replace this amendment's float lattice handling with integers carried end to end. Read Amendment 2 before relying on any figure here.

**Refs:** BIN-133 PR #29 code review, ADR-011, ADR-012 §3, ADR-013 §1/§7.

### 0. The defect — stated in full, because the tests missed it

**Found:** verification of the implementation on branch `feat/BIN-133/bernoulli-cusum`
(PR #29, not merged) *after* `code-reviewer` had approved it — Codecov's
failing patch check prompted a look at the uncovered lines. Measured independently, reproduced from first
principles, and confirmed against the running code.

**`_quantise_reference_value` rounds each arm's log-LR reference value `r` to
a fixed lattice with denominator `N = 100` (`_LATTICE_DENOMINATOR`).** When
`p₁ − p₀` is narrower than one lattice step (`1/100`), the rounded `r_q`
leaves the open interval `(p₀, p₁)` ADR-012's derivation requires:

```
arm     m     f   p₀          p₁          r_real      r_q     status
lower   300   0   0.007646    0.015292    0.011036    0.0100   OK
upper   300   0   0.992354    0.996177    0.994483    0.9900   VIOLATED: r_q < p₀
lower   500   0   0.004595    0.009189    0.006630    0.0100   VIOLATED: r_q > p₁
upper   500   0   0.995405    0.997703    0.996685    0.9900   VIOLATED
lower  1000   0   0.002300    0.004600    0.003319    0.0100   VIOLATED
upper  1000   0   0.997700    0.998850    0.998341    0.9900   VIOLATED
upper  1000   5   0.990745    0.995373    0.993322    0.9900   VIOLATED
```

**Every existing test sat at `p₀ ∈ [0.02, 0.30]`; failure rates under 1% —
the common case for a healthy agent on a binary rubric — were never exercised.
The test strategies used "realistic" ranges that systematically excluded the
defect region.**

**Consequence.** The chart's `achieved_arl` is exactly computed **for the
rounded chart**, so the reported number is not wrong on its own terms — but the
rounded chart is not the designed CUSUM:

- **Lower arm:** when `r_q > p₁` (e.g. m=500, f=0), the in-control drift
  `E[X − r_q] = p₀ − r_q` is **deeply negative** and the out-of-control
  drift `p₁ − r_q` is **also negative**. The chart never signals on either
  hypothesis — detection is destroyed.
- **Upper arm:** when `r_q < p₀` (e.g. m=300, f=0: `r_q = 0.99, p₀ = 0.992`),
  the in-control drift is **positive**, so the accumulator drifts toward the
  boundary even under the null hypothesis. The calibration search compensates
  by pushing the decision interval ever higher. Measured at the upper arm
  of m=1000, f=0, per-arm target 2×10⁶:
  `_calibrate_one_sided_decision_interval_units` returns 2,097,152 (= 2²¹),
  exceeding `_MAX_DECISION_INTERVAL_UNITS` (2,000,000) — **silently**.

- **Joint two-sided state count** at m=1000, f=0, `target_arl = 10⁶`:
  `(h_lower + 1) × (h_upper + 1)` reached **826 million** states. A
  two-sided fit at that configuration did not finish in 2 minutes. Even at
  configurations where the invariant holds (e.g. m=200, f=20, target=10⁹
  two-sided), the fit took 26 seconds — all within the fixed `N = 100`
  lattice.

**Root cause.** `_LATTICE_DENOMINATOR = 100` was chosen as the smallest
denominator ADR-013's measurements were stable at (§1: "stable from `N=100`
upward but not at `N=50`"). But that measurement was a statement about
*ARL convergence* at specific grid points, not a claim that `N = 100`
satisfies the `(p₀, p₁)` interval invariant across the whole legal space.
The two properties are unrelated: a denominator can produce converged ARLs
for the chart it constructs while placing `r_q` outside the interval the
design requires — which is exactly what it does here. ADR-012 §3 and
ADR-013's "what this deliberately does not decide" both deferred the
denominator choice, and neither noticed it carried a correctness invariant.

**Why the test suite missed it.** The BDD scenarios contain no numeric
literals (deliberately). The unit tests' Hypothesis strategies bounded
`failure_count` to `[2, max_failures]` — realistic ranges that never reached
`f = 0` at large `m`. The published-oracle tests (`sand2016-7395c`) cover
`r ∈ {0.01, 0.02, 0.03, 0.04}` and `p ≤ 0.10`, which are all well within
`N = 100`'s safe region. **No test checked the invariant `p₀ < r_q < p₁`
directly.**

---

### Decision 7: per-arm adaptive lattice denominator with centring tolerance

**Each arm computes its own lattice denominator `N`, independently**, as the
smallest integer such that `round(r × N) / N` lies strictly inside
`(p₀, p₁)` **and** within `ε × (p₁ − p₀)` of the unquantised `r`.

**Why the interval invariant alone is not enough.** A denominator that
merely places `r_q` inside `(p₀, p₁)` can place it at the *edge* of the
interval, which reintroduces the defect in milder form. Measured with the
smallest-safe-N rule (the original draft's proposal), the normalised
position `(r_q − p₀) / (p₁ − p₀)`:

```
m=300  f=0:  lower arm position 0.98  upper arm position 0.00
m=1000 f=0:  lower arm position 0.99  upper arm position 0.00
m=1000 f=5:  lower arm position 0.96  upper arm position 0.02
```

A lower-arm `r_q` at position 0.99 (nearly touching `p₁`) means the
out-of-control drift `p₁ − r_q` is near zero — detection is not destroyed
(the invariant holds) but is severely degraded. An upper-arm `r_q` at
position 0.00 (on `p₀`) means the in-control drift is near zero — the
calibration compensates by inflating the decision interval, and the joint
state count explodes at high targets:

```
                             min-safe rule       centred (ε=0.25)
m=300  f=0 target=1e6:       7,478,688 states    2,090,772 states
m=1000 f=0 target=1e6:      41,511,879 states   16,377,848 states
m=1000 f=5 target=1e6:       4,483,750 states    1,472,526 states
```

**The `ε`-centring rule keeps `r_q` near `r` rather than at the edge.**
With `ε = 0.25`, positions are consistently 0.40–0.60 and joint state
counts at high targets are 2.5–3.5x smaller.

**Why per-arm, not per-fit.** The two arms need very different granularities.
At m=1000, f=0, the lower arm needs N=257 and the upper needs N=514 (at
`ε = 0.25`). A single denominator serving both would be `max(257, 514)` or,
if the reference values must be co-representable on a shared grid, their LCM
— which, at coprime per-arm Ns (e.g. `N_lower = 218, N_upper = 435`,
LCM = 94,830), inflates the joint state count catastrophically (Decision 8).

**The closed-form bound is sufficient.** `|round(r × N) / N − r| ≤ 1/(2N)`
always holds (the rounding error is at most half a lattice step). So any `N`
satisfying `1/(2N) < ε × (p₁ − p₀)`, i.e. `N > 1 / (2ε(p₁ − p₀))`, is
guaranteed to produce `|r_q − r| < ε × (p₁ − p₀)`. Since
`ε × (p₁ − p₀) < min(r − p₀, p₁ − r)` holds for `ε < 0.5` (because `r`
sits near the midpoint of `(p₀, p₁)` — measured at position 0.44–0.54 across
the legal space), this also guarantees `r_q ∈ (p₀, p₁)` strictly. No scan
is needed for the mathematical guarantee.

**The implementation uses a scan, starting from `N = 2`, because the
closed form overshoots.** The bound assumes worst-case rounding; actual
rounding at a given `N` is often better. Measured at `ε = 0.25`:

```
m      f   arm     scan N   closed N   ratio
300    0   lower   78       262        3.4x
300    0   upper   155      524        3.4x
1000   0   lower   257      870        3.4x
1000   0   upper   514      1740       3.4x
100    10  lower   4        14         3.5x
```

The scan produces consistently ~3.4x smaller `N`, which translates to ~12x
fewer joint states. The scan terminates because the closed form guarantees
a safe `N` exists — ADR-012 amendment §5 proves `p₀ < r < p₁`, and the bound
above proves any sufficiently large `N` clears the tolerance. The scan's
worst measured depth is ~1400 iterations (m=5000, f=0, upper arm) — trivial.

**Choice of `ε = 0.25` — measured, not picked.** Detection-ARL penalty
(per-arm `ARL₁` ratio against a near-continuous reference at `N = 10000`)
across the legal space, at `target_arl = 370`:

```
ε        worst detection penalty   states at m=1000 f=0 t=1e6
0.10     14.7%                     16,275,330
0.15     14.7%                     16,065,215
0.20     14.7%                     16,091,712
0.25     14.7%                     16,377,848
0.30     57.9%                     17,058,824
0.40     57.9%                     19,669,120
```

The 14.7% worst-case penalty is a single lattice-granularity artefact (ADR-012
§3's documented non-monotone residual): at one specific `(m, f, arm)` the
quantised `r_q` happens to land on a lattice point that shifts the chart
design. It is **not cumulative with `ε`** — it is the same 14.7% at
`ε = 0.10` through `ε = 0.25`, because the same lattice point is hit. The
jump at `ε ≥ 0.30` is a second, different lattice-point crossing.

State counts at `m = 1000, f = 0, target = 10⁶` are essentially flat from
`ε = 0.10` to `ε = 0.25` (~16M). **The gain from centring vs edge-placement
is large (41.5M → 16.4M); the gain from varying `ε` within the centred range
is small.** `ε = 0.25` is chosen because it produces the smallest per-arm
`N` without crossing the detection-penalty threshold — lower `N` means fewer
lattice points per unit of `h`, which reduces state count at low targets
where the centring effect is less dominant.

**Alternatives considered:**

- **A finer fixed denominator** (e.g. `N = 10,000` everywhere). Rejected:
  it is wasteful at common configurations (m=100, f=10 needs only `N = 4`)
  and still eventually fails at extreme corners (very large `m`, `f = 0`,
  where even `N = 10,000` may not clear the gap). A fixed denominator is
  the wrong abstraction when the gap width varies over four orders of
  magnitude.
- **The smallest-safe-N rule** (smallest `N` satisfying only
  `r_q ∈ (p₀, p₁)`, without a centring tolerance). Rejected — this is the
  original draft's proposal, and it places `r_q` at the interval edge
  (positions 0.96–1.00 / 0.00–0.02), inflating state counts by 2.5–3.5x
  at high targets. Measured and demonstrated above.
- **The closed-form `N` directly** (`ceil(1 / (2ε(p₁ − p₀)))`). Rejected
  for implementation: it overshoots the minimum by ~3.4x consistently,
  producing ~12x more joint states than necessary. It is used as a
  termination guarantee for the scan, not as the answer itself.
- **The Reynolds & Stoumbos scaling** (formulate the statistic so `r ≈ 1/k`
  for integer `k`, and use `k` as the denominator). Not held: Reynolds &
  Stoumbos (1999) is not in the vault (only Mousavi & Reynolds 2009, which
  is about autocorrelation, not this). Named as a candidate for a future
  simplification once the paper is obtained; the scan with `ε`-tolerance
  is correct without it.

---

### Decision 8: the joint two-sided solve must use independent per-arm lattices

ADR-014 §6c specifies the joint two-armed Markov-chain solve: state space is
the Cartesian product of both arms' bounded lattices, a single Bernoulli(p)
draw updating both accumulators each step.

**The current implementation (`_joint_two_sided_bernoulli_arl0`) converts all
four values (both reference values, both decision intervals) to a single
shared denominator via `_lattice_denominator` (LCM).** With per-arm
denominators that share no common factor, the LCM is their product:

```
N_lower    N_upper    LCM         blowup
22         44         44          1×
66         131        8,646       66×
109        218        218         1×
218        435        94,830      218×
```

At m=1000, f=0, target=370: the LCM-shared lattice turns what should be
94,176 states into approximately **8.87 billion** — which is why the earlier
benchmark timed out even on small configurations when passed through the
current joint solver.

**Decision: the joint solver accepts independent per-arm lattice parameters.**
Each arm's CUSUM accumulator lives on its own lattice. State `(i, j)` means
the lower arm is at `i` units of `1/N_lower` and the upper arm is at `j`
units of `1/N_upper`. A single Bernoulli draw transitions both:

- `X = 1` (failure, probability `p`): lower arm `i → i + (N_lower − r_lower_units)`,
  upper arm `j → max(0, j − r_upper_units)`.
- `X = 0` (success, probability `1 − p`): lower arm `i → max(0, i − r_lower_units)`,
  upper arm `j → j + (N_upper − r_upper_units)`.

Absorption when either accumulator exceeds its own decision interval.
**State count: `(h_lower_units + 1) × (h_upper_units + 1)`.** Measured with
this construction, using Decision 7's centred `ε = 0.25` rule:

```
m      f    target     N_lower  N_upper  h_lower  h_upper  joint states  solve time
100    0    370        26       52       62       146      9,261          0.01s
300    0    370        78       155      130      257      33,798         0.03s
1000   0    370        257      514      256      431      111,024        0.06s
100    0    10,000     26       52       141      478      68,018         0.11s
1000   0    10,000     257      514      856      2,246    1,925,679      refused (> 1M cap; ≈ 1.8 GB)
1000   0    1,000,000  257      514      2,032    8,055    16,377,848     refused (> 1M cap; ≈ 15.5 GB)
```

Note: the m=1000 f=0 target=10⁶ case gives 16.4M states — above the
ratified 1M cap (Decision 10b), which refuses it before the solve runs.
Memory figures in this table's last two rows are extrapolated from Decision
10b's measured ≈ 950 bytes/state peak RSS, not run. Compare to the edge-positioned min-safe rule's 41.5M at the same
corner.

**The exact property ADR-012 §4/§5 and ADR-014 §6c require is preserved:**
each arm's accumulator is on an integer lattice with rational increments, and
the chain is finite and absorbing, so `(I − Q)m = 1` gives the exact expected
absorption time. The two arms sharing a single draw is what makes the joint
solve exact (§6c's stated construction) — they do not need to share a lattice
denominator for that property to hold, only a single source of randomness,
which they do.

**This replaces both `_joint_two_sided_bernoulli_arl0`'s shared-N call to
`_lattice_denominator`, and the current `_one_sided_bernoulli_arl0`'s own
call to `_lattice_denominator`** (which was only needed because reference
values and decision intervals were passed as floats and the denominator had
to be reconstructed; with per-arm integer parameters, reconstruction is
unnecessary).

**Alternatives considered:**

- **Force related denominators** (e.g. `N_upper = 2 × N_lower`). Rejected:
  there is no mathematical reason the upper arm's minimum safe denominator
  should be a multiple of the lower arm's, and forcing the relationship
  would either over-refine one arm or under-refine the other.
- **Keep the shared LCM approach but cap it.** Rejected: a shared denominator
  whose LCM is capped would silently round one arm's reference value to a
  coarser lattice than it needs, potentially reintroducing the interval
  violation the per-arm fix exists to prevent.

---

### Decision 9: `target_arl` ceiling at `MAX_MEANINGFUL_ARL = 1,000,000`

**The Bernoulli CUSUM gets the same `target_arl` upper bound the three
continuous charts already enforce.** `fit_bernoulli_cusum` will reject
`target_arl > MAX_MEANINGFUL_ARL` with `InvalidParameterError`, mirroring
`parameter_guards._validate_target_arl_range`'s existing check.

**The ceiling alone does not fix the defect** — confirmed by measurement:
at `target_arl = 370` (well below 10⁶), the fixed `N = 100` lattice
already violates the `(p₀, p₁)` invariant at `m ≥ 300, f = 0`. The defect
is in the lattice denominator (Decision 7), not in the target range. The
ceiling exists to **bound cost** (Decision 10), not to fix the interval
violation.

**Rationale for reusing `MAX_MEANINGFUL_ARL` rather than a Bernoulli-specific
number.** ADR-014 Decision 3 already established that ADR-011's three-tier
structure (hard floor, advisory, verified range) does not transfer to the
Bernoulli chart, because the Bernoulli CUSUM's ARL₀ is exact — there is no
approximation gap for the tiers to gatekeep against. That reasoning holds:
the ceiling is a **cost bound**, not a verification boundary. An engineer who
requests `target_arl = 10⁶` on a binary chart gets an exact, honestly-
computed ARL₀ if the solve can be completed (same as at 370, same Markov
chain, same linear algebra). The only question is whether the solve *can* be
completed within the resource budget this library is willing to spend.
`MAX_MEANINGFUL_ARL = 10⁶` is the value the continuous charts already use for
a different reason (ADR-011's verification boundary), but it is also a
reasonable cost boundary: with the per-arm lattice (Decision 7) and
independent-lattice joint solve (Decision 8), every tested configuration at
`target_arl = 10⁶` completes in bounded time *except* the extreme corner
(m ≥ 1000, f = 0), which is caught by the joint state count cap (Decision 10).

**The rejection is `InvalidParameterError`** with
`context["parameter"] = "target_arl"`, `context["kind"] = "invalid"`,
`context["max_value"] = MAX_MEANINGFUL_ARL`, `context["max_inclusive"] = True`.
The value `MAX_MEANINGFUL_ARL` round-trips as an accepted input (BIN-122's
rule).

**Alternatives considered:**

- **A lower, Bernoulli-specific ceiling** (e.g. 100,000). Rejected: it is
  not needed at most configurations (m=100, f=10 at target=10⁶ gives only
  18,160 joint states), and a ceiling that refuses a configuration the
  library could serve in under 0.01s substitutes the library's caution for
  the engineer's judgement. The joint state count cap (Decision 10) is the
  precise control; the target ceiling is a coarse, user-facing one.
- **No ceiling.** Rejected: the product owner has ruled that a ceiling is
  needed, and without one there is no upper bound on the per-arm decision
  interval search.

---

### Decision 10: joint state count cap and search-bound enforcement

Two resource bounds, each with an enforced limit and a clear error path:

**10a. The one-sided calibration search must not return past its bound.**

`_calibrate_one_sided_decision_interval_units` currently returns past
`_MAX_DECISION_INTERVAL_UNITS` silently — measured at the upper arm of
m=1000, f=0, per-arm target 2×10⁶: the search returned 2,097,152 (2²¹)
against a cap of 2,000,000 and the caller never checked.

**Decision: when the exponential search reaches `_MAX_DECISION_INTERVAL_UNITS`
without finding a solution, the calibration raises `InvalidParameterError`.**
`context` reports the achievable ARL₀ at the cap: the ARL is monotonically
non-decreasing in `h`, so the value at `_MAX_DECISION_INTERVAL_UNITS` is the
largest ARL₀ this arm can deliver. That value round-trips: if the engineer
reduces `target_arl` to at most that value, the search succeeds (BIN-122's
rule).

⚠️ **This is not the same as ADR-014 Decision 3's computed attainability
floor** (which BIN-117 established for the continuous CUSUM). The attainability
floor is computed at the search bracket's *minimum* `h`; this cap is the
search bracket's *maximum*. Both are needed: the floor catches targets that
are too *low*, the cap catches targets that are too *high* (or, more
precisely, that require a decision interval too large for the search to
reach). In practice, the cap fires only when the interval invariant is
violated and the search compensates by inflating `h` without bound — with
Decision 7 in place, the invariant holds and the cap is a safety net.

**10b. Joint two-sided state count cap.**

**Measurement method and a correction.** The original draft measured memory
with Python's `tracemalloc`. **Those figures were wrong** for two reasons:
(1) tracing overhead inflated solve time by roughly 3x, and (2)
`tracemalloc` tracks only Python-side allocations — `scipy.sparse.linalg.spsolve`
delegates to SuperLU, which allocates most of its working memory through
`malloc` outside Python's allocator, so `tracemalloc` undercounted peak
memory by roughly 4x. The corrected table uses **peak RSS** via
`resource.getrusage(RUSAGE_SELF).ru_maxrss`, measured in a fresh process
per row (so each row's RSS is not cumulative), on this machine (macOS,
Apple Silicon, 16 GB). The independent-lattice joint solver (Decision 8)
with m=300 f=0 lattice N=(85, 170):

```
joint states    solve time    peak RSS
4,141           0.0s          55 MB      (process baseline)
542,101         0.5s          507 MB
982,101         1.3s          908 MB
1,962,801       3.4s          1,923 MB
2,003,001       2.9s          1,905 MB
4,504,501       7.5s          4,351 MB
```

Approximately **950 bytes per state** in peak RSS, consistent across aspect
ratios. Two rows independently reproduced on the same machine:
- 974,341 states: 1.2s, 903 MB
- 1,956,071 states: 2.8s, 1,854 MB

**Decision: `_MAX_JOINT_STATES = 1,000,000`. Ratified by the product
owner.** The fit raises `InvalidParameterError` when the joint state count
`(h_lower_units + 1) × (h_upper_units + 1)` exceeds this cap.

**Rationale.** Memory, not time, is the binding constraint. Caliper runs
inside the engineer's own agent process — a fit peaking near 1.9 GB (the
2M-state case) can kill a small container or crowd out the agent's own
working memory. At 1M states, peak RSS is ~908 MB (~1.3s) — under 1 GB,
safe for a typical CI runner or agent container.

**Cost accepted:** zero-failure baselines at large `m` get lower two-sided
maxima than the 2M alternative would have allowed. The maximum two-sided
`target_arl` per baseline at the ratified 1M cap, computed via bisection
and round-trip verified:

```
                  cap=1M
                  ~1.3s / ~908 MB
m=200  f=0        max_t=975,430
m=300  f=0        max_t=93,422
m=500  f=0        max_t=16,642
m=1000 f=0        max_t=4,035
m=2000 f=0        max_t=1,768
m=5000 f=0        max_t=1,085
m=1000 f=5        max_t=252,368
m=1000 f=10       max_t=1,000,000
```

`target_arl = 370` still fits **every** baseline. All baselines with
`f ≥ 1%` of `m` fit at all targets up to 10⁶. The refusal reports
`max_two_sided_target_arl` which round-trips as an accepted input (verified
at five baselines, each within 1 unit of the cap).

Joint state count is monotone in `target_arl` for a fixed baseline
(verified by measurement across four representative baselines).

**`context` reports the `max_two_sided_target_arl` for this baseline.**
Because joint state count is monotone in `target_arl` (verified), a
bisection over `target_arl` in `[1, MAX_MEANINGFUL_ARL]` gives the largest
two-sided target this baseline supports under the cap. That value is
reported in `context["max_two_sided_target_arl"]` and **round-trips as an
accepted input** (BIN-122's rule) — verified at five baselines, each within
1 unit of the cap.

Additionally, `context` carries `reason = "joint_state_count_exceeded"`,
the computed state count, and the cap. `recovery_hint` directs the engineer
to: (a) reduce `target_arl` to at most `max_two_sided_target_arl`, (b)
increase `detect_rate_multiple` (which widens `p₁ − p₀` and reduces per-arm
decision intervals), or (c) use `direction = "lower"` or `"upper"`, which
avoids the joint solve entirely and always succeeds (see below).

**One-sided fits always succeed up to `MAX_MEANINGFUL_ARL`.** Verified: at
every tested `(m, f)` including the worst corner (m=10,000, f=0), the
one-sided state count at `target_arl = 10⁶` is at most ~40,000, and no
arm's calibration search exceeds `_MAX_DECISION_INTERVAL_UNITS`. A
one-sided solve at 40K states takes < 0.01s. **The recovery path from a
joint-state-count refusal to a one-sided fit is always available**, not
contingent on the baseline.

**Interaction with Decision 9's ceiling.** The ceiling (`MAX_MEANINGFUL_ARL`)
is checked first, before calibration. The joint state cap is checked after
per-arm calibration, before the joint solve. Both are needed: the ceiling
prevents the search from running unboundedly long; the joint cap prevents
the final solve from exceeding the resource budget.

**Alternatives considered:**

- **A time-based cap** (abort after N seconds). Rejected: execution time is
  hardware-dependent, non-deterministic, and not checkable before starting
  the solve. A state count cap is a static, measurable property of the
  configuration that can be checked with no computation.
- **No cap — rely on the target ceiling alone.** Rejected: `target_arl = 10⁶`
  at m=1000, f=0 produces 16.4M states under Decision 7's centred lattice;
  the ceiling passes it, and the solve would peak at ~15.6 GB — far beyond
  any reasonable process budget.
- **Cap at 2,000,000** (2M states: ~3.4s, ~1.9 GB peak RSS). Considered
  and recommended by the original draft. Rejected: Caliper runs inside the
  engineer's own agent process, so a fit peaking at ~1.9 GB can kill a
  small container; the additional coverage (m=1000 f=0 two-sided up to
  ~10,582 instead of ~4,035) does not justify the memory risk.
- **Cap at 500,000** (~0.5s, ~507 MB — comfortable on any machine).
  Considered. Rejected: it caps m=5000 f=0 at `max_t = 1,085`, leaving
  near-zero headroom above `target_arl = 370`, and it refuses m=1000 f=0
  at `max_t = 1,753`. The 1M cap gives meaningful room at every corner that
  the 500K cap does not.

---

### Decision 11: verification bar for the fix

**At minimum, the following tests must exist before this amendment is
considered implemented:**

1. **Property: `r_q ∈ (p₀, p₁)` AND `|r_q − r| ≤ ε × (p₁ − p₀)` for
   both arms, over the full legal space.** A Hypothesis strategy drawing
   `(m, f)` from the full legal range — including `f = 0` at `m` up to at
   least 10,000, and `f = m − 1` at large `m` — must verify that the
   per-arm adaptive denominator produces a quantised `r_q` satisfying both
   the interval invariant and the centring tolerance. **The strategy must
   NOT be bounded to "realistic" ranges** — restricting `f` to `[2, max]`
   or `m` to `[100, 1000]` is the exact coverage gap that caused this
   defect. Assert on both conditions explicitly: inside the interval, and
   within `ε × (p₁ − p₀)` of `r`.

2. **Property: the per-arm denominator finder always terminates.** The
   closed-form bound `N = ceil(1 / (2ε(p₁ − p₀)))` guarantees a safe `N`
   exists (§7's derivation). The implementation's scan must have a safety
   cap (the closed-form value, or a generous constant) to prevent an
   unbounded loop in the event of a floating-point edge case. The test
   need only verify the invariant holds at the returned `N`.

3. **Bounded-time test at the worst legal corner.** `fit_bernoulli_cusum`
   called with `m = 10,000`, `f = 0`, `target_arl = MAX_MEANINGFUL_ARL`,
   `direction = "two_sided"` must either complete in bounded time or raise
   `InvalidParameterError` with the joint-state-count context — never hang.
   This is the single test that would have caught the defect if it had
   existed.

4. **Regression: the fixed-N=100 violation cases.** Each of the six
   violated configurations in the table above (m=300/500/1000 f=0 and
   m=1000 f=5, both arms) must be covered by an explicit test verifying
   the invariant holds under the fix — not just by the property test, which
   may not hit those exact coordinates.

5. **The search cap fires.** A test that verifies
   `_calibrate_one_sided_decision_interval_units` raises (not returns
   silently) when the target exceeds what the search bracket can deliver.

6. **`max_two_sided_target_arl` round-trips.** When the joint state count
   cap triggers, the `context["max_two_sided_target_arl"]` value reported
   in the error must round-trip: calling `fit_bernoulli_cusum` with that
   value as `target_arl` (same baseline, same `direction = "two_sided"`)
   must succeed. Test at the baselines in §10b's table where the cap fires.

7. **One-sided fits succeed at `MAX_MEANINGFUL_ARL` for f=0 baselines.**
   For `m ∈ {100, 500, 1000, 5000, 10000}`, `f = 0`, verify that
   `fit_bernoulli_cusum(baseline, target_arl=MAX_MEANINGFUL_ARL,
   direction="lower")` succeeds — confirming the recovery path the error's
   `recovery_hint` directs the engineer toward.

8. **The bisection for `max_two_sided_target_arl` completes in bounded
   time.** At the worst corner (m=10,000, f=0, `target_arl =
   MAX_MEANINGFUL_ARL`, `direction = "two_sided"`), the refusal path —
   which must compute `max_two_sided_target_arl` via bisection over
   per-arm calibrations — must itself finish in bounded time, not hang.
   The bisection performs O(50) iterations of per-arm calibration (each
   fast — one-sided solves at < 40K states), not a joint solve, so it
   should complete in under 1 second; the test asserts this.

---

### Consequence for ADR-013's GICP grid

ADR-013 §3's 40-cell measurement grid covers `p₀ ∈ {0.02, 0.03, 0.05,
0.075, 0.10, 0.15, 0.20, 0.30}`. The defect region starts at
`p₀ < 0.01` (approximately — the gap `p₁ − p₀ ≈ p₀` falls below `1/N`
when `p₀ < 0.005` at `N = 100`). **ADR-013's GICP coverage guarantee is a
property of the Clopper-Pearson construction itself** — it holds for any
`p₀ ∈ (0, 1)`, not only at the grid points, because the proof is analytic
(the guarantee fails exactly when the confidence bound undercovers, §3's
measured correspondence confirms the mechanism). **The grid does not need
extending below `p₀ = 0.02` for the guarantee to hold there.**

What does need extending is **lattice-quantisation error measurement** at
low `p₀` — ADR-012 §3's table, which measured the `achieved_arl` vs
`requested_arl` gap, only covers `p₀ ∈ {0.02, 0.05, 0.10, 0.20}` at
`N = 100`. With the per-arm adaptive denominator, the quantisation residual
at low `p₀` is a property of the *adaptively chosen* `N`, not of a fixed
`N = 100`. The existing "report, don't chase" mechanism
(`achieved_arl` ≠ `requested_arl`) handles this honestly regardless of
the denominator, so no new measurement gates this fix — but extending the
table to the adaptive-N regime is noted as follow-up verification work.

---

### Summary of changes to the ADR body

| ADR-014 decision | status |
|---|---|
| Decision 1 (binary score inferred) | **unchanged** |
| Decision 2 (Phase II input contract) | **unchanged** |
| Decision 3 (target_arl tiering) | **amended**: gains `MAX_MEANINGFUL_ARL` ceiling (Decision 9) |
| Decision 4 (detection-disclosure field) | **unchanged** |
| Decision 5 (α not engineer-facing) | **unchanged** |
| Decision 6a (not FittedControlLimits) | **unchanged** |
| Decision 6b (field shape) | **unchanged** |
| Decision 6c (exact joint solve) | **amended**: gains independent-lattice requirement (Decision 8) |
| Decision 6d (p_U substitution) | **unchanged** |
| **NEW Decision 7** | per-arm adaptive lattice denominator |
| **NEW Decision 8** | independent per-arm lattices in the joint solve |
| **NEW Decision 9** | `target_arl` ceiling at `MAX_MEANINGFUL_ARL` |
| **NEW Decision 10** | search-bound enforcement + joint state count cap |
| **NEW Decision 11** | verification bar |

---

### 🚨 What this amendment deliberately does not decide
- **Whether the `_LATTICE_DENOMINATOR` constant should have a floor**
  (e.g. `max(scan_result, 100)` to preserve ADR-013's convergence
  property). The ARL convergence finding at `N = 100` was for specific
  `(p₀, m)` cells; whether a floor is needed for the per-arm adaptive
  denominator's own convergence is an implementation measurement, not an
  architecture decision.
- **A `FittingAdvisory` for configurations near the joint state cap.**
  Considered; same shape as ADR-013 §6b's deferred high-rate advisory. No
  threshold for "close enough to the cap to warrant a word" has been
  measured.

---

## Amendment 2 (2026-09-24): the reported numbers and the running chart must be the same chain

**Status:** ✅ **ACCEPTED — Decisions 12–19 ratified in full by the product owner
2026-09-24.**

Rulings:
- **Q1:** Decision 12 accepted.
- **Q2:** settled with Q8; calibration D.
- **Q3:** Decision 13.3's 999,999-unit one-sided cap accepted.
- **Q4:** `DegenerateBaselineError(reason="arl_not_computable")` accepted.
- **Q5:** the public `BernoulliArmLattice` shape accepted, with the floats as
  computed properties.
- **Q6:** the upper-only `expected_detection_arl` at `p̂/M` accepted. Its f=0
  fallback is withdrawn by Decision 19.
- **Q7:** the recommendation to defer was overruled; the upper arm is fixed now,
  inside BIN-133.
- **Q8:** Decision 19's numbers ratified. These are `p_L` at α = 0.10, the
  two-sided `achieved_arl` as the guaranteed floor `B`, and calibration D, on
  the evidence of 19.3 and the independent check in 19.4.
- **Q9:** the improvement-detection figure is a number, not a warning (19.6).
- **Q10:** the f = 0 two-sided artefact shape accepted.

Open Question 23 is **settled by Decision 19**.

**Refs:** BIN-133 PR #29 re-review (head `5b7e3a1`), ADR-002 §3/§4, ADR-009 §5,
ADR-011, ADR-012 §3/§4, ADR-013 §4/§7, BIN-112, BIN-117, BIN-122, BIN-134,
BIN-140.

### 0. What shipped, what was missed, and why

The re-review of PR #29 found six blockers. Every measurement below was
**reproduced independently for this amendment** against the implementation at
`5b7e3a1`, using scripts kept in the session scratchpad under `amend2/`
(`a1`–`a10`, named where used). None of these numbers comes from the review
text alone.

| # | defect, as shipped | reproduced? |
|---|---|---|
| 1 | Decision 3 item 2's attainability floor was **ratified but never built**. `_calibrate_one_sided_decision_interval_units` returns `h_units = 1` whenever that already meets the target. The docstring cites `_require_attainable_target_arl` "below", and no such function exists. | **Yes.** m=1000 f=0: lower at 100 and at 370 both give 434.8; two-sided at 370 gives 485.8; m=2000 lower at 370 gives 869.1; m=5000 two-sided at 370 gives 552.2; m=300 f=3 lower at 50 gives 147.6 (`probe_floor.py`) |
| 2 | Achieved ARLs are computed by **rebuilding each lattice from floats** (`Fraction.limit_denominator(100_000)`). This breaks once the upper arm's N passes 100,000. | **Yes, including the segfault.** At m=200,000 f=0: `upper` returns `achieved_arl = expected_detection_arl = 1e15` (the sentinel) after 24.2 s. `two_sided` dies with `Fatal Python error: Segmentation fault` in `scipy.sparse.linalg.spsolve`, reached from `_joint_two_sided_bernoulli_arl0` via `_solve_absorbing_chain`. The process exits with code 139 (`probe_e2e.py` run under `-X faulthandler`, in a subprocess). **Cause** (`a3_segfault_cause.py`): the true upper lattice is N=102,629 with h=736 units, and the rebuilt one is N=2,297,300,000 with h=16,475,000 units. So a 1,474-state problem was handed to SuperLU as a 16.5-million-state one, **without passing the 1,000,000 joint cap**, because the cap is checked on the true integers and the solve runs on the rebuilt ones. At m=300,000 the rebuilt N is 9,065,300,000. |
| 3 | `Monitor` accumulates `max(0, S + x − r)` in binary floating point, so it does **not run the integer chain whose ARL₀ was calibrated**. | **Yes.** On the reviewer's sequence at m=105 f=10 (upper lattice N=9, r=8, h=40 units), Monitor signals `upper` at observation 139 with `S = 4.444444444444446`, while the exact statistic is 40 units = h, which is in control (`a4_monitor_float.py`). |
| 4 | Nothing ties Monitor's Bernoulli branch to the fitted chart. The reviewer's four mutations survive, and one of them survives the whole suite. | Taken from the review; not re-run. It is consistent with #3 going unnoticed. |
| 5 | `expected_detection_arl` is **meaningless for `direction="upper"`**. The code matches `docs/domain-model.md`, so this is a gap in the spec. | **Yes.** At m=150 f=40 it reads 357,451.6 against an achieved 406.2 (`a6_upper_detection.py`). |
| 6 | Some refusals lack required ADR-002 keys: the ceiling and joint-cap refusals have no `constraint`, and the search-cap refusal has no `provided`. | **Yes**, by reading `bernoulli_cusum_fitting.py:860-875, 655-672, 987-997`. **One more, not in the review:** the `score_not_binary` refusal has `kind="invalid"` and no `provided`. |

**How big defect 3 is, measured rather than asserted** (`a4`, `a5`). Over 400
in-control runs per configuration, Monitor signalled earlier than the exact
chain in these runs:

- m=105 f=10: 2 runs
- m=300 f=3: **211 runs**. That is every run in which the upper statistic reached h exactly. The upper lattice there is N=54 and r=53, and its float r is `53/54`.
- m=200 f=20, m=150 f=40, m=1000 f=5, m=120 f=30: 0 runs

No run signalled late. Over 4,000 paired runs at m=300 f=3 `direction="upper"`:

| | mean run length |
|---|---|
| reported `achieved_arl` | 375.6 |
| exact chain | 378.1 ± 9.0 |
| Monitor's float arithmetic | 370.7 ± 8.7 |

The float path signalled at or before the exact chain in **4,000 of 4,000** runs.
The bias is small next to the Monte Carlo noise, but it only ever runs one way.
It is a different chart from the one whose ARL₀ is reported, and at some
configurations it hits every run that touches the boundary.

**Why the first review and the coordinator's verification missed these.**

- **Defect 1 was treated as built.** Amendment 1's §10a and its "What this
  deliberately does not decide" section both discuss the floor as if it existed.
  The implementation's docstring names a function that does not exist, and
  nobody grepped for it. This project has made the same error before: ADR-013
  §4's correction and `CLAUDE.md`'s *"a record of decisions, not of what
  shipped"* both warn about it.
- **Every check stayed on the existing grid.** Targets were 370 or higher and
  baselines were small. Nobody compared `achieved_arl` against `requested_arl`
  at f=0, and no test built a baseline beyond m=10,000, although `Baseline` has
  no maximum size. Both reviews missed things for the same reason Amendment 1's
  own defect was missed: they sampled "realistic" inputs instead of the edges of
  the legal space.
- **Amendment 1 itself carries three measurements that were wrong at the edges
  (§1 below).** They are corrected here, not silently. §10b says one-sided fits
  never exceed about 40,000 states: measured 300,924 at m=300,000 and 742,099
  at m=3,000,000. §11 item 8 says the refusal bisection takes under 1 s:
  measured 0.7 s at m=300 and **44.8 s at m=300,000** (`a8_maxt.py`). §10b's
  line "`target_arl = 370` still fits every baseline" holds only because the
  floor it would have collided with was never built (Decision 12).
- **The Monitor check was vacuous.** It asserted only that some signal arrives
  within 10,000 identical observations. Any chart that accumulates in the right
  direction passes that. It is the same shape as the vacuity findings recorded
  under `BIN-121`.

---

### Decision 12 (item 1): the lower arm's floor is exactly `1/p_U`, a property of the chart and not of the lattice. Fit, report and disclose; do not refuse.

**✅ Ratified 2026-09-24.**

**The measurement that decides it** (`a1_floor_structure.py`). The ARL₀ at the
smallest decision interval the search uses (`h_units = 1`) equals
**`1/p_U` to relative precision 1e-9 in every row**, from m=100 to m=300,000,
with f=0 and f>0. Re-quantising the same `r` on lattices 2, 4 and 16 times
finer **leaves it unchanged**:

```
m       f   1/p_U       N x1..x16             floor (every N)   next attainable value (N x1 / x4 / x16)
300     0   130.79      78 .. 1,248           130.79            423.89 / 370.15 / 395.04
852     0   370.52      219 .. 3,504          370.52            1,202.76 / 1,050.95 / 1,124.88
1000    0   434.79      257 .. 4,112          434.79            1,411.04 / 1,232.57 / 1,320.92
1000    5   108.05      64 .. 1,024           108.05            351.78 / 305.84 / 327.33
5000    0   2,171.97    1,284 .. 20,544       2,171.97          7,040.34 / 6,155.62 / 6,594.30
300000  0   130,288.84  76,972 .. 1,231,552   130,288.84        422,349.67 / 369,301.30 / 395,680.21
```

**Why this holds, so that it does not rest on the table alone.** For any
`h < 1 − r`, one failure lifts the lower statistic from 0 to `1 − r > h` and
the chart signals. A success leaves it at 0. So the run length is the waiting
time to the first failure, which is geometric with mean exactly `1/p`. Nothing
in that argument involves `N`. It holds for any lower-arm Bernoulli CUSUM, on
any lattice, **and for the continuous-`r` chart too**: no chart that raises its
statistic only on a failure can have an in-control ARL below the mean waiting
time for one. **The hypothesis that the floor is an artefact of Decision 7's
smallest `N` is refuted.**

**It is a gap, not only a floor.** The next attainable value is roughly **2.8
to 3.3 times** the floor at every baseline measured. That is the first `h` at
which a single failure no longer signals. Refining `N` moves it by a few
percent, not by a multiple. A target inside that gap gets the next value up:

- m=1000 f=0 two-sided at 370: the lower arm's per-arm target of 740 lies in
  (434.8, 1,411.0), and the result is 485.8.
- m=300 f=0 lower at 370: 423.9.

**Refusing only below the floor, as Decision 3 item 2 prescribes, would
therefore not deliver `achieved ≈ requested` even when it fired.**

**The interaction with the 1,000,000 joint-state cap is decisive against
refusal** (`a8_maxt.py`, f=0, two-sided):

```
m        two-sided target at which the lower arm leaves its floor   max_two_sided_target_arl (1M cap)
2,000    434.5                                                        1,768
3,000    651.7                                                        1,112
5,000    1,086.0                                                      1,085
10,000   2,171.7                                                      2,171
100,000  21,715.0                                                     21,714
300,000  65,144.4                                                     65,143
```

From about m=5,000 upward, the joint-state cap binds **one unit below** the
point where the lower arm leaves `h_units = 1`. The reason is that the second
lower-arm regime needs `h_lower_units ≥ N_lower − r_units ≈ N_lower`, and
`N_lower` grows linearly with m. So with a floor refusal, each such baseline
would refuse every two-sided target below the floor, and the cap would refuse
every target at or above it. **A healthy f=0 baseline of 5,000 or more
observations could not be fitted two-sided at any `target_arl`.** Two-sided is
the ratified default, and this is the most common production case: a reliable
agent with a long clean history.

**Decision (ratified 2026-09-24): replace Decision 3 item 2's refusal with
fit-and-disclose for the Bernoulli CUSUM.**

1. `fit_bernoulli_cusum` never refuses a `target_arl` for being below what is
   attainable. The calibration keeps returning the smallest `h` that meets the
   target. ARL₀ is non-decreasing in `h`, so a one-sided `achieved_arl` is
   always `≥ requested_arl`, which is the conservative direction: fewer false
   alarms than the engineer tolerated, never more.
2. When the lower arm is at its floor, the artefact carries a structured
   disclosure:
   ```python
   FittingAdvisory(
       kind="lower_arm_signals_on_first_failure",
       description=...,  # prose, not part of the contract
       boundary=<exact one-sided lower-arm ARL at h_units = 1>,  # == 1/p_U
   )
   ```
   - **Condition:** `direction` checks the lower arm (`"lower"` or
     `"two_sided"`) **and** `h_lower_units < N_lower − r_lower_units`, which is
     an integer test.
   - **No threshold is invented.** The condition is a structural fact about the
     constructed chart ("every single failure pages you"), not a judgement about
     how far `achieved` may stray from `requested`.
   - `boundary` is the smallest in-control ARL₀ **any** lower-arm Bernoulli
     CUSUM can have on this baseline. That tells the engineer why the number is
     what it is, and that no parameter they control changes it.
3. The remaining general case, a target that falls in a gap above the floor,
   stays ADR-012 §3's ratified "report, don't chase". `achieved_arl` sits next
   to `requested_arl`, computed exactly.

**Why refusal is wrong here, although it is right for the continuous CUSUM
(BIN-117).**

- **BIN-117's refusal has a lever.** Its recovery hint is *"lower
  `reference_value`"*. Here there is none. The floor is `1/p_U`, which does not
  depend on `detect_rate_multiple`, on `N` or on `direction`. The only thing
  that lowers it is a *smaller* baseline, which is perverse.
- **The refused call and its round-trip produce the same chart.**
  `fit(target_arl=370)` and `fit(target_arl=434.79...)` at m=1000 f=0 both
  construct `h_units = 1`, with identical fields apart from `requested_arl`. A
  refusal whose only recovery rebuilds the chart it refused is ceremony.
- **The failure BIN-117 guarded against is absent.** There, root-finding
  bottomed out and the fit *"reported the achieved ARL0 as if it were a
  successful fit"*. Here the exact `achieved_arl` is always reported beside the
  request, and the new advisory names the regime.
- **The governing principle is already ratified twice:** ADR-011's
  *"informed choice over refusal"* and ADR-013 §4's rejection of a
  detection-power floor.

**Options rejected.**

- **(a) Refuse per Decision 3 item 2, with a round-tripping `min_value`.**
  This is the ratified text. Rejected for four reasons:
  - it leaves f=0 baselines of 5,000 or more observations unfittable two-sided
    at every target (table above);
  - it refuses `target_arl = 370` for every f=0 baseline with m ≥ 851 one-sided
    (the smallest m whose `1/p_U` reaches 370 is 851) and m ≥ 1,703 two-sided;
  - its recovery reproduces an identical chart;
  - it leaves the gap above the floor unguarded anyway.

  For the product owner's comparison, this is its exact shape if ratified
  instead:
  - condition: `target_arl < floor`;
  - floor: for one-sided `"lower"`, `1/p_U` via the solver at `h_units = 1`;
    for `"two_sided"`, the value at which the equal split leaves the floor,
    which is `floor_lower / 2` with a per-arm target of `2T`; for `"upper"`,
    `1/(1 − p_U)` ≈ 1, which never binds in practice;
  - context: `parameter`, `constraint`, `kind`, `provided`, `min_value`, and
    `min_inclusive=True`;
  - round-trip: passing `min_value` back is accepted, because the calibration
    accepts `ARL(1) ≥ target` at equality.
- **(b) Choose `N` so the target becomes attainable.** Rejected as impossible:
  the floor and the gap do not depend on `N` (measured above, and proved).
- **(d) Two-sided: keep the equal-split lower arm, then calibrate the upper arm
  against the exact joint solve so the two-sided ARL₀ meets `T`.**
  `a9_twosided_options.py` measured it:

  | baseline | option (d) | shipped equal split |
  |---|---|---|
  | m=5000 f=0 | 370.4, 812 states | 552.2 |
  | m=100,000 f=0 | 370.4, 744 states | 727.8 |
  | m=1000 f=0 | 371.0, 85,838 states | 485.8 |

  It is attractive, and it removes most of the two-sided gap. *As first
  drafted*, this amendment held it back for two reasons:
  - it moves most of the false-alarm budget onto the upper (improvement) arm.
    At m=5000 f=0 the lower arm contributes about 1/2,172 per observation of
    the 1/370 total;
  - that arm's GICP coverage is Open Question 23, and the measurement below
    points the wrong way for it.

  It is listed as a product-owner option. It would also need a monotonicity
  proof for the joint ARL in `h_up` before it could gate behaviour (ADR-013
  §7).

  > **Superseded 2026-09-24 by Decision 19.4.** Once the upper arm is designed
  > at `p_L`, both objections fall away. The monotonicity proof is supplied
  > there, by coupling, and option (d) is re-measured and adopted as
  > calibration D.
- **(e) Randomised signalling to hit the target exactly.** Rejected. ADR-012's
  amendment §4 already foreclosed it on auditability.
- **The literal "joint floor at `(1, 1)`" for two-sided.** Rejected as
  meaningless. It is about 2.0 at every baseline measured, because the upper
  arm then signals on the first success, so it never binds and discloses
  nothing (`a9`).

**Measured context for Open Question 23, not a decision.** At the observed rate
`p̂ < p_U`, the upper arm alarms **more** often than its reported `achieved_arl`
(`a10_upper_at_phat.py`, `direction="upper"`, T=370):

| baseline | at `p_U` | at `p̂` |
|---|---|---|
| m=1000 f=0 | 371.1 | 268.0 |
| m=300 f=3 | 375.6 | 172.3 |
| m=200 f=20 | 385.6 | 148.8 |
| m=100 f=10 | 391.5 | 108.9 |

That is the direction Decision 6d feared: designing at an *upper* bound is
anti-conservative for the arm that detects a *decrease*. It does not change any
decision here. It is why this amendment first held option (d) back, and it
raised Open Question 23 from "unverified" to "**measured evidence of a coverage
problem**". *Resolution:* the product owner ruled to fix it inside BIN-133. It is
settled by Decision 19, and option (d) was adopted there as calibration D.

---

### Decision 13 (item 2): integer lattice parameters end to end; no size bound on the baseline; a one-sided state cap; a raising postcondition

**✅ Ratified 2026-09-24.**

**What the measurements show** (`a2_integer_fit.py`, `a2_large.out`). I re-ran
`fit_bernoulli_cusum`'s own design and calibration helpers, but computed every
reported ARL straight from the integers `(N, r_units, h_units)` with nothing
rebuilt.

- **Agreement with the float path.** Wherever the float path works (m ≤ 150,000),
  the two agree to every printed digit: m=1,000, 10,000 and 100,000 at T=370,
  all three directions (`--with-float`).
- **Correct results where the float path fails.** At m=200,000 upper T=370 the
  integer path gives 370.79, where the float path gave the sentinel `1e15`. At
  m=300,000 it gives 370.53, where the float path gave 369.52.
- **Two-sided at T=370 is small at every baseline size.** It needs only
  1,474–1,480 joint states from m=200,000 to m=3,000,000, and the solve takes
  under 1 ms.
- **Without the rebuild there is no segfault to reach.** The segfault needed
  the rebuilt 16.5-million-state chain.

f=0 figures at the extremes of the legal space:

```
m          N_lower    N_upper     scan    one-sided T=1e6: worst arm states / calibrate time
10,000     2,566      5,132       0.001s  39,638 / 0.7s
100,000    25,658     51,315      0.012s  168,337 / 3.3s
300,000    76,972     153,943     0.037s  300,924 / 6.2s
1,000,000  256,571    513,141     0.13s   518,866 / 8.7s
3,000,000  769,710    1,539,420   0.37s   742,099 / 10.3s
```

With failures present (m=300,000, f ∈ {1, 30, 3000}) everything is smaller.
Nothing fails numerically anywhere up to m=3,000,000.

For peak memory of a single one-sided solve (`a7_onesided_rss.py`, a fresh
process for each row):

| states | time | peak RSS |
|---|---|---|
| 100,000 | 0.07 s | 182 MB |
| 500,000 | 0.34 s | 507 MB |
| 1,000,000 | 0.70 s | 958 MB |
| 2,000,000 | 1.61 s | 2,012 MB |

This matches Decision 10b's ≈950 bytes per state.

**Decisions.**

1. **The integers are the chart.** `fit_bernoulli_cusum` passes
   `(N, r_units, h_units)` for each arm straight into the one-sided and joint
   solvers.
   - `_lattice_denominator`, `_DENOMINATOR_RECONSTRUCTION_CAP` and every
     `limit_denominator` call are **removed from production code**.
   - The float-accepting wrappers survive only as test helpers. The
     published-value oracles (`sand2016-7395c`) state `r` and `h` as exact
     decimals, so the test builds its integers from exact `Fraction`s.
   - This is what Amendment 1's Decision 8 already said ("with per-arm integer
     parameters, reconstruction is unnecessary"). It was never carried out.
2. **No bound on baseline size and no bound on `N`.** None is needed. Every
   legal f=0 configuration up to m=3,000,000 fits one-sided at
   `MAX_MEANINGFUL_ARL` and two-sided at 370, and the adaptive-`N` scan costs
   0.37 s at its largest. A bound on `m` would refuse the healthiest agents
   precisely because they are healthy. Integer width is not a concern, since
   Python `int` is unbounded and N stays under 2×10⁶ in this range. ⚠️ *corrected by the corrigendum, below (C9).*
3. **The one-sided chain gets the same memory budget as the joint chain.**
   - `_MAX_DECISION_INTERVAL_UNITS` becomes `_MAX_JOINT_STATES − 1`
     (999,999), so no single solve, one-sided or joint, exceeds 1,000,000
     transient states (about 958 MB).
   - Today's value of 2,000,000 allows a one-sided solve peaking at about
     2 GB. That contradicts the reasoning behind the ratified 1M joint cap
     (Decision 10b: *"a fit peaking near 1.9 GB... can kill a small
     container"*).
   - **Nothing measured is refused by this change.** The worst case measured
     is 742,099 states at m=3,000,000 T=10⁶. Past that, the existing
     search-cap refusal fires with its round-tripping `max_attainable_arl`.
4. **Postcondition, raising.** Every ARL copied onto the artefact
   (`achieved_arl`, `expected_detection_arl`) must satisfy all of:
   - it is finite;
   - it is ≥ 1.0;
   - it is **not** `_ILL_CONDITIONED_ARL_SENTINEL`;
   - the solved chain's state count equals `h_units + 1` (one-sided) or
     `(h_lower_units + 1) × (h_upper_units + 1)` (joint).

   A violation raises. **The sentinel may steer the calibration search and
   must never be copied into a field.**
   - The error is `DegenerateBaselineError` with
     `context["reason"] = "arl_not_computable"`, plus `chart_type` and
     `figure` (`"achieved_arl"` or `"expected_detection_arl"`). This follows
     the one existing precedent for "these inputs are legal but the resulting
     number is not representable": `spc_numerics.require_representable_limits`,
     BIN-142.
   - After decisions 1–3 no measured input reaches this path, so it is a
     guard, not an expected outcome. This **reverses the "never raises
     `DegenerateBaselineError`" line** in `fit_bernoulli_cusum`'s docstring,
     for this one reason only. The alternative, a bare `RuntimeError`, would
     leak a non-`CaliperError` through a public entry point, the defect class
     BIN-121 exists to prevent.
5. **The refusal-path bisection must be cheap.**
   - `_find_max_two_sided_target_arl` recalibrates both arms from scratch
     about 20 times. That took 44.8 s at m=300,000 and 18.8 s at m=100,000
     (`a8`).
   - The value is correct: every row agrees with the floor analysis to one
     unit.
   - The cost is not acceptable for a refusal. It must reuse per-arm results,
     for example by bisecting on per-arm `h_units` and evaluating each arm's
     ARL once for each `h`, or by caching `achieved_at(h)` across iterations.
   - The verification bar below sets the budget.

**Options rejected.**

- **Raise the reconstruction cap** (to 10⁷, say). Rejected. It moves the cliff
  rather than removing it, and the reconstruction can mis-identify a
  denominator at any cap (`a3`: the rebuilt N was a multiple, and neither the
  true N nor a divisor of it).
- **Bound the baseline size** (for example m ≤ 150,000). Rejected: nothing
  above it fails once the integers are carried through, and refusing a
  larger, cleaner baseline inverts the product's incentive.
- **Keep the sentinel on the reporting path and document it.** Rejected. That
  is BIN-140's defect class, and the module docstring's promise ("never
  reported back") was the only guard, which is how it shipped.

---

### Decision 14 (item 3): the artefact carries each arm's integer lattice, and `Monitor` steps it in integers

**✅ Ratified 2026-09-24.**

**Decision.**

1. **A new frozen value object, one for each arm:**

   ```python
   class BernoulliArmLattice(BaseModel):   # ConfigDict(frozen=True)
       denominator: int               # N  >= 2
       reference_units: int           # r_units, 0 < r_units < N
       decision_interval_units: int   # h_units, 1 <= h_units <= _MAX_DECISION_INTERVAL_UNITS

       @property
       def reference_value(self) -> float: return self.reference_units / self.denominator
       @property
       def decision_interval(self) -> float: return self.decision_interval_units / self.denominator
   ```

   - Validators enforce each bound in the comments, and reject `bool` and any
     non-exact `int`.
   - `repr` shows the three integers. A `Fraction`-style "r=8/9, h=40/9" is
     also fine; the choice is the implementer's.
   - `__bool__` raises, as it does on every other domain type (BIN-110).
2. **`FittedBernoulliCUSUM` gains `lattice_lower: BernoulliArmLattice` and
   `lattice_upper: BernoulliArmLattice`.** These amend §6b's field table. They ⚠️ *corrected by the corrigendum (C3): each is `BernoulliArmLattice | None`, `None` exactly when that arm is not checked.*
   are **the stored, authoritative definition of the chart.**
3. **The four public float fields stay, and so does their meaning, but they
   become derived.** `reference_value_lower`, `decision_interval_lower`,
   `reference_value_upper` and `decision_interval_upper` are read-only computed
   properties that delegate to the lattices (Pydantic `@computed_field`, so
   they still appear in `repr`, `model_dump` and `audit_summary()`). **There is
   one source of truth, and two independently stored copies can never
   disagree.** Engineers read exactly what they read today.
4. **`Monitor` accumulates in integer units.** The per-arm state is an `int`.
   - On a failure: `s_lo += N_lo − r_lo`; `s_up = max(0, s_up − r_up)`.
   - On a success: `s_lo = max(0, s_lo − r_lo)`; `s_up += N_up − r_up`.
   - It signals on `s_lo > h_lo_units` or `s_up > h_up_units`, strictly
     (ADR-009 §5 / BIN-112).
   - This is exactly the transition structure the solver inverts, so the
     reported `achieved_arl` belongs to the chart that `Monitor` runs.
5. **`Monitor` re-validates the lattices at use** (exact `int`, the bounds
   above).
   - The artefact is caller-supplied, and `model_copy(update=...)` and
     `model_construct()` skip validation.
   - The same reasoning, and the same placement, as `_check_bernoulli_cusum`'s
     existing `require_exact_str` on `direction` (BIN-143).
   - A violation raises `InvalidParameterError` with
     `parameter="artefact"`, a `constraint`, `kind="invalid"`, `provided`, and
     `field` naming the offending attribute.

**Why public fields, not private attributes.** A fitted artefact is the thing
an engineer persists: fit once, then monitor in another process. With private
attributes, `model_dump()` → `model_validate()` would drop the only exact
description of the chart. The rebuilt artefact could then not drive `Monitor`
exactly, or it would silently fall back to floats, which is defect 3 again.
**What goes in comes out:** the artefact serialises to the chart that was
fitted, and nothing is lost.

**Why nested, not six flat fields.** Six more flat fields on an 18-field type
bury the fields engineers actually read, which runs against "export what
engineers need". One named object for each arm says what it is: *"the exact
lattice of the lower arm"*. It groups three numbers that are meaningless apart,
and the class can enforce `0 < r < N` itself. `BernoulliArmLattice` is exported
from `drift_caliper.baseline`, because it appears in a public field's type, but
**not** from the top-level `drift_caliper` namespace. Engineers read it; they do
not construct it.

**Options rejected.**

- **Six flat integer fields beside the four floats.** Rejected: it creates two
  stored records of the same number (this project's recurring failure), and it
  adds namespace noise.
- **`PrivateAttr` integers.** Rejected: they are lost on serialisation (above),
  and they are invisible to `repr` and to auditing.
- **`fractions.Fraction` accumulators in `Monitor`, rebuilt from the floats.**
  Rejected: the rebuild uses `limit_denominator` and inherits defect 2's
  cliff. The reviewer made the same point.
- **Keep float accumulation with an epsilon at the boundary.** Rejected: it is
  an invented constant, and it still leaves the running chart different from
  the solved one.

**Cost.** §6b's field table changes. `docs/domain-model.md` needs the new value
object (domain-modeller's step, not done here). `audit_summary()` gains two
lines. Pre-release, so no consumer migration is needed.

---

### Decision 15 (item 4): `expected_detection_arl` means *"at the shift this chart is tuned to detect"*, so the upper-only chart uses the improvement

**✅ Ratified 2026-09-24.**

**The defect** (`a6_upper_detection.py`, T=370, M=2). For `direction="upper"`,
the shipped code evaluates an improvement-only chart at a **degradation**
(`p̂ × M`), a shift it is built never to signal on. The resulting figure means
nothing:

```
m     f    achieved   shipped (p̂·M)   ratified (p̂/M)   f=0 fallback (p_U/M)*
150   40   406.2      357,451.6        32.8             39.6
200   20   385.6      6,478.7          61.3             77.4
105   10   392.5      2,209.6          52.5             73.0
300   3    375.6      322.4            133.3            182.8
1000  5    372.3      401.8            198.4            238.9
1000  0    371.1      530.6            (undefined)      314.1
100   30   406.9      173,301.6        27.0             34.5
```

\* The f = 0 column is historical. Decision 19 refuses `"upper"` at f = 0, so
this fallback is withdrawn.

**Decision.** `expected_detection_arl` is the exact ARL₁ of the constructed
chart, evaluated at **the shift that the checked arm(s) are designed for**. It
remains unconditional and first-class (Decision 4).

| `direction` | evaluated at failure rate | f = 0 fallback |
|---|---|---|
| `"lower"` | `p̂ × M` (unchanged) | `p_U × M` (unchanged) |
| `"two_sided"` | `p̂ × M` via the joint chain (unchanged; a doubling is the headline question for the default chart) | `p_U × M` (unchanged) ⚠️ *corrected by the corrigendum, below (C8)* |
| `"upper"` | **`p̂ / M`**, the mirror of ADR-013 §4 and the upper arm's own design direction (ADR-012 amendment §2) | **`p_U / M`**, mirroring ADR-013 §4's fallback: at f=0, "an improvement from zero" is undefined, as "a rise from zero" is for the lower arm |

**Why this and not the alternatives.**

- ADR-013 §4 defines the figure as answering *"how fast will this plausibly
  catch the degradation it is tuned to detect"*. For an upper-only chart the
  tuned shift is an improvement, so evaluating it anywhere else answers a
  question the chart was built not to answer.
- **`None` for upper.** Rejected. It would make the field conditional, which
  Decision 4 rejected, and it would force `float | None` on every consumer
  branch for the default direction too.
- **Keep the degradation for every direction.** Rejected: that is the defect.
- **Report both figures for two-sided.** Plausible, but it adds a field no
  scenario asks for. Deferred, not rejected.
- **`p̂ / M` exactly as defined.** It uses the same "`p̂` for the expectation,
  `p_U` only when `p̂` is degenerate" rule as ADR-013 §4, and needs no new
  machinery.

**The feature file does not change.** Its scenarios assert that the detection
figure is reported, not what it is evaluated at. The glossary entry
(`docs/domain-model.md` line ~1000) and the field row (line ~512) need a
direction-aware definition. That is domain-modeller's step.

---

### Decision 16 (item 5): two-sided fits never surface the per-arm `max_attainable_arl`; a per-arm search-cap hit is reported as the joint-state refusal

**✅ Ratified 2026-09-24.**

**Reachability, measured, not assumed.** Under today's cap of 2,000,000 units ⚠️ *corrected by the corrigendum, below (C1).*
no two-sided configuration measured reaches the per-arm search cap. The
largest per-arm `h` is 1,211,962 units, at m=3,000,000 f=0 T=10⁶
(`a2_large.out`). **Under Decision 13's cap of 999,999 units that same
configuration does reach it.** The search-cap refusal would then fire before
the joint-cap check, reporting a per-arm figure that does not round-trip as a
two-sided `target_arl` (the per-arm target is `2T`). So the defect becomes
reachable the moment Decision 13 lands, and it is decided here rather than
left latent.

**Decision.** In `"two_sided"` mode, a per-arm search-cap hit is caught and
turned into the joint-state refusal (`reason = "joint_state_count_exceeded"`,
with `max_two_sided_target_arl`).

**Proof that this is correct, not merely convenient.** If either arm's
`h_units` exceeds 999,999, then
`(h_lower_units + 1)(h_upper_units + 1) ≥ 1,000,001 > _MAX_JOINT_STATES`. So
the configuration is over the joint cap whatever the other arm is.
`_find_max_two_sided_target_arl` already treats a search-cap hit inside its
bisection as "over the cap", so its reported value round-trips unchanged. In
`"lower"`/`"upper"` mode, `max_attainable_arl` is a one-sided figure and
round-trips as a one-sided target, as it does now.

**Rejected: halve `max_attainable_arl` for two-sided.** Half the per-arm
maximum is not the two-sided maximum, because the joint ARL is not the
harmonic combination (§6c). The value would not round-trip.

---

### Decision 17 (item 6): the complete `context` for every Bernoulli refusal, in one table

**✅ Ratified 2026-09-24.**

**ADR-002, as it applies here.**

- §4's table requires `parameter`, `constraint` and `kind` on every
  `invalid_parameter`.
- §3 requires `provided` whenever `kind == "invalid"`.
- BIN-134 adds `min_value`/`max_value` with `min_inclusive`/`max_inclusive`
  wherever a numeric range bound is reported. A reported bound must
  round-trip, which is BIN-122's rule.
- `invalid_observation` requires `reason` and `missing_fields`;
  `insufficient_baseline` requires `have` and `need`; `degenerate_baseline`
  requires `reason`.

The shipped code missed three of these and this amendment found a fourth. The
rows below are **the whole contract**. Every row is an emission site, and every
key listed is required. "New" marks a row this amendment adds or changes.

**`fit_bernoulli_cusum`**

| # | condition | type | required `context` |
|---|---|---|---|
| F1 | `baseline` is not a `Baseline` | `InvalidParameterError` | `parameter="baseline"`, `constraint`, `kind="invalid"`, `provided` (existing `require_type`) |
| F2 | a score is not exactly 0.0/1.0 | `InvalidParameterError` | `parameter="baseline"`, `constraint`, `kind="invalid"`, **`provided`** (new: the `Baseline` passed, the same meaning `require_type` gives this parameter in F1), `reason="score_not_binary"`, `invalid_score`, `position` |
| F3 | `target_arl` omitted | `InvalidParameterError` | `parameter="target_arl"`, `constraint`, `kind="missing"` (no `provided`) |
| F4 | `target_arl` not a real number, or a `bool` | `InvalidParameterError` | `parameter`, `constraint`, `kind="invalid"`, `provided` (existing `require_real_number`) |
| F5 | **new, merged:** `target_arl` non-finite, `< 1.0` or `> MAX_MEANINGFUL_ARL` | `InvalidParameterError` | `parameter="target_arl"`, `constraint` (e.g. `"must be a finite float in [1.0, 1000000.0]"`), `kind="invalid"`, `provided`, `min_value=1.0`, `max_value=MAX_MEANINGFUL_ARL`, `min_inclusive=True`, `max_inclusive=True`. Replaces today's two separate raises, one of which had no `constraint`. This is the key set `parameter_guards.classify_target_arl` already emits, so it should come from a shared, bounds-parameterised helper and not be hand-rolled (the reviewer's point: hand-rolling is how `constraint` was lost). |
| F6 | `detect_rate_multiple` not a real number | `InvalidParameterError` | `parameter`, `constraint`, `kind="invalid"`, `provided` |
| F7 | `detect_rate_multiple` non-finite or ≤ 0 | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`, `min_value=0.0`, `min_inclusive=False` (existing) ⚠️ *corrected by the corrigendum, below (C2)* |
| F8 | `direction` not recognised, or not an exact `str` | `InvalidParameterError` | `parameter="direction"`, `constraint`, `kind="invalid"`, `provided` (existing `_validate_direction`/`require_exact_str`) ⚠️ *corrected by the corrigendum, below (C6)* |
| F9 | fewer than 100 observations | `InsufficientBaselineError` | `have`, `need` |
| F10 | every judgement failed | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`, `reason="all_baseline_judgements_failed"`; **no** `max_detect_rate_multiple` |
| F11 | `p_U × M ≥ 1` | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`, `max_detect_rate_multiple` (round-trips; key name ratified, unchanged) |
| F12 | one-sided search reaches `_MAX_DECISION_INTERVAL_UNITS` (`"lower"`/`"upper"` only, Decision 16) | `InvalidParameterError` | `parameter="target_arl"`, `constraint`, `kind="invalid"`, **`provided`** (new: the caller's `target_arl`, not the per-arm figure), `max_attainable_arl` (round-trips as a one-sided target), `direction` |
| F13 | two-sided joint states over `_MAX_JOINT_STATES`, **or** a per-arm search-cap hit in two-sided mode (Decision 16) | `InvalidParameterError` | `parameter="target_arl"`, **`constraint`** (new: e.g. `"the two-sided joint state count must not exceed max_joint_states"`), `kind="invalid"`, `provided`, `reason="joint_state_count_exceeded"`, `joint_state_count`, `max_joint_states`, `max_two_sided_target_arl` (round-trips). When a per-arm hit triggered it, `joint_state_count` is the lower bound `(h_lo+1)(h_up+1)` at the capped arm, still over the cap. |
| F14 | **new:** a reported ARL fails its postcondition (Decision 13.4) | `DegenerateBaselineError` | `reason="arl_not_computable"`, `chart_type="bernoulli_cusum"`, `figure` (`"achieved_arl"` or `"expected_detection_arl"`) ⚠️ *corrected by the corrigendum, below (C10)* |

**Not a refusal: the disclosure (Decision 12).** It is
`FittingAdvisory(kind="lower_arm_signals_on_first_failure", description, boundary)`,
carried on `advisories`, with `boundary` equal to the exact one-sided lower-arm
ARL₀ at `h_units = 1`.

**`Monitor`**

| # | condition | type | required `context` |
|---|---|---|---|
| M1 | Phase II score not exactly 0.0/1.0 | `InvalidObservationError` | `reason="score_not_binary"`, `missing_fields=()` (existing, Decision 2) |
| M2 | **new:** a lattice on a caller-supplied `FittedBernoulliCUSUM` has an integer that is not exact, or is out of bounds (Decision 14.5) | `InvalidParameterError` | `parameter="artefact"`, `constraint`, `kind="invalid"`, `provided`, `field` (e.g. `"lattice_upper.reference_units"`) ⚠️ *corrected by the corrigendum, below (C4, C6)* |
| M3 | artefact `direction` not an exact `str` | `InvalidParameterError` | existing `require_exact_str` keys (BIN-143) |

**Enforcement, so this cannot be missed a third time.**

- Every row above is registered in `tests/support/exception_contract_registry.py`.
- One parametrised test drives each site through the public API and asserts
  the **full** key set in the table: presence, and for bounds, the
  round-trip.
- A site added later without a registry row must fail the existing
  exception-contract audit. That is the BIN-121 mechanism, extended to this
  module.

---

### Decision 18: the verification bar for Amendment 2

**✅ Ratified 2026-09-24.**

This is in addition to Decision 11, which stands, except where corrected in §0.
**Every item must exist before Amendment 2 counts as implemented.** Items
marked 🚨 are the ones that would each have caught a shipped defect.

1. 🚨 **Differential test: `Monitor` against an independent exact stepper.**
   - The stepper is written in the test itself, is ≤ 20 lines, and imports
     nothing from `monitor.py` or `bernoulli_cusum_fitting.py`.
   - It reads only `artefact.lattice_lower`/`lattice_upper` and applies the
     integer transitions from Decision 14.4.
   - Hypothesis generates the pass/fail sequences. At **every** step, for all
     three `direction` values, `Monitor.record(...).is_in_control` and
     `.direction` must equal the stepper's result.
   - Required configurations:
     - m=105 f=10 and m=300 f=3, where float drift was measured;
     - one f=0 baseline with m ≥ 1,000;
     - one baseline with p̂ ≥ 0.25.
   - It must include **constructed sequences that land each arm's statistic
     exactly on `h_units`**, which is in control, followed by the one step that
     exceeds it, which signals.
   - The reviewer's sequence at m=105 f=10 is pinned as a named regression. It
     must stay in control through observation 139.
   - This kills the reviewer's mutations M3a–M3d.
2. **Simulated ARL₀ through `Monitor`**, in
   `test_bernoulli_cusum_arl_simulated_properties.py`, following the three
   continuous charts' convention exactly:
   - `_N_RUNS = 1_500`, `_CONFIDENCE_Z = 4.0`, `derived_relative_tolerance`;
   - no formula imported from production;
   - in-control streams drawn at `p_U`, the rate `achieved_arl` is defined at.

   Cover `"two_sided"` at m=300 f=3, `"upper"` at m=300 f=3, `"lower"` at
   m=200 f=20, and one floored lower arm (m=1,000 f=0 `"lower"`, where
   `achieved_arl = 1/p_U`).

   ⚠️ **This test alone would not have caught defect 3.** At m=300 f=3
   `"upper"` the float bias was 375.6 against 370.7 ± 8.7, inside any honest
   tolerance. Item 1 is the precise check; this one guards the calibration
   end to end.
3. 🚨 **Large baselines, every direction.** ⚠️ *corrected by the corrigendum, below (C1).*
   - Scope: m ∈ {300,000; 1,000,000}, f=0, with T ∈ {370, `MAX_MEANINGFUL_ARL`}.
     Build each baseline with one shared `ScoringResult`, which takes about
     0.05 s at 200,000.
   - Every fit must either succeed or raise F12/F13 with a round-tripping
     bound.
   - Every reported ARL must be finite, ≥ 1, and not the sentinel.
   - Every reported ARL must equal an **independent** integer reference solver
     in the test to rel 1e-9. The existing
     `TestJointTwoSidedBernoulliARL0MatchesTheReferenceSolver` solver,
     extended, qualifies.
   - Expected (from `a2_large.out`), each case must match:
     - m=300,000: upper at 370 gives 370.5273;
     - m=300,000: two-sided at 370 gives 735.9166, with 1,476 joint states;
     - m=300,000: lower at 10⁶ gives 1,000,020.0999;
     - m=300,000: two-sided at 10⁶ refuses with F13.
   - m=3,000,000 at T=370, all directions, is marked `slow`.
4. 🚨 **Decision 8 enforced by value, not by a timeout.** At a baseline whose
   per-arm denominators are coprime (the test asserts `gcd(N_lo, N_up) == 1`
   before anything else), spy on the solver's `n_states`, and assert it equals
   `(h_lower_units + 1) × (h_upper_units + 1)`. This kills mutation M2, which
   today is caught only by pytest-timeout.
5. 🚨 **Decision 12, the floor and the disclosure.** ⚠️ *corrected by the corrigendum, below (C1).*
   - For m ∈ {852, 1,000, 5,000, 300,000}, f=0, `"lower"` at T=370, and for
     m=300 f=3 `"lower"` at T=50: `achieved_arl == 1/p_U` to rel 1e-9. The
     advisory `lower_arm_signals_on_first_failure` is present, with
     `boundary == achieved_arl`.
   - For m=5,000 f=0 `"two_sided"` at T=370: the fit **succeeds** (552.2) and
     carries the advisory.
   - The advisory is **absent** when the arm is not floored (m=300 f=0
     `"lower"` at T=370, where `h_units = 77`), and for `"upper"`.
   - Property: a one-sided `achieved_arl ≥ requested_arl` for every legal
     input, with Hypothesis drawing from the full legal space (f=0 at large m
     included) as Decision 11 item 1 requires.
6. **The postcondition raises (Decision 13.4).** Monkeypatch the solver to
   return the sentinel, `NaN`, `0.5`, and a vector of the wrong length. Each
   must raise F14 for `achieved_arl` and for `expected_detection_arl`, and
   none may produce an artefact.
7. **No float reconstruction in production.** A structural test (AST or grep)
   asserts that `bernoulli_cusum_fitting.py` contains no `limit_denominator`
   and no `Fraction` reconstruction.
8. **Decision 15.** `"upper"`'s `expected_detection_arl` equals the reference ⚠️ *corrected by the corrigendum, below (C1).*
   solver at failure rate `p̂/M`: 32.8 at m=150 f=40, and 61.3 at m=200 f=20.
   At f=0 it uses `p_U/M`: 314.1 at m=1,000. `"lower"` and `"two_sided"` are
   unchanged.
9. **Decision 16.** Monkeypatch `_MAX_DECISION_INTERVAL_UNITS` small enough ⚠️ *corrected by the corrigendum, below (C1).*
   that one arm hits it in `"two_sided"`. The fit must raise F13, not F12, and
   `max_two_sided_target_arl` must round-trip.
10. **Decision 17.** The registry-driven test asserts every row's full key set,
    as described there.
11. **Serialisation round-trip.**
    `FittedBernoulliCUSUM.model_validate(chart.model_dump())` equals `chart`,
    and drives `Monitor` identically under item 1's stepper. Each float field
    equals `units / denominator` exactly.
12. **Refusal-path budget.** The F13 refusal at m=300,000 f=0 `"two_sided"` at ⚠️ *corrected by the corrigendum, below (C1; budget replaced in C11).*
    T=`MAX_MEANINGFUL_ARL` completes in **≤ 5 s locally**; today it takes
    44.8 s. This is an engineering budget, not a statistical constant.
    Decision 11 item 8's "under 1 second" is withdrawn as unmeasured. Tests
    must not drive a zero-drift chain to a real cap: monkeypatch the cap, as
    `TestCapBisectionPath` already does. That is the reviewer's
    Recommendation 1, and today the suite spends 101 s in one test.

---

### Decision 19: each arm is designed on the side that is conservative for the shift it detects. The upper arm uses the Clopper–Pearson lower bound `p_L`, and the two-sided budget is calibrated on an exact guaranteed bound.

✅ **ACCEPTED — ratified by the product owner 2026-09-24.** The direction (Q7,
fix now) and the numbers (Q8: `p_L` at α = 0.10, `B` as the two-sided
`achieved_arl`, calibration D), on the evidence of 19.3 and 19.4. Q9 is 19.6, and
Q10 is 19.2's f = 0 shape. **Open Question 23 is settled by this decision.**

#### 19.0 The defect: the shipped upper arm is systematically anti-conservative

The criterion is ADR-013 §3's. A baseline is counted if its **true** in-control
ARL₀, evaluated at the true `p₀`, falls below `T/2`. The ratified appetite is at
most 5%. `T = 370`, `M = 2.0`. Figures are exact, by enumeration over
`f ~ Binomial(m, p₀)` (`g1b_upper_at_pu.py`), for the upper arm **as shipped,
designed at `p_U`**:

```
p0      m=100            m=300            m=1000
        <T/2    <T       <T/2    <T       <T/2    <T
0.002   100.0%  100.0%   45.2%   100.0%   1.7%    100.0%
0.01    100.0%  100.0%   57.8%   95.1%    8.2%    93.4%
0.02    86.7%   100.0%   55.6%   94.0%    11.0%   93.6%
0.05    74.2%   96.3%    53.7%   93.5%    13.9%   89.4%
0.10    79.4%   94.2%    52.8%   93.0%    13.5%   90.8%
0.30    62.3%   88.6%    32.7%   85.8%    3.0%    80.6%
```

This is not marginal: the appetite is breached by up to 20 times. The cause is
the one Decision 6d suspected. The upper arm signals on *successes*, so its
ARL₀ **falls** as the true failure rate falls. Designing it at an *upper* bound
on the failure rate therefore calibrates it at the rate where it alarms least,
and every true rate below that makes it alarm more.

#### 19.1 The design

| arm | detects | designed at | `r` from | calibrated at |
|---|---|---|---|---|
| lower | a rise in failure rate | `p_U` = Clopper–Pearson **upper** bound, α = 0.10 (unchanged, ADR-013) | `(p_U, M·p_U)` | `p_U` |
| upper | a fall in failure rate | **`p_L` = Clopper–Pearson lower bound, α = 0.10**, the `α` quantile of `Beta(f, m − f + 1)` | `(1 − p_L, 1 − p_L/M)` on the success indicator | `1 − p_L` |

`α` is ADR-013's ratified value and is not re-derived here. `p_L` has a closed
form at f=1: `1 − (1 − α)^(1/m)`.

**What Heidema et al. (2026) covers, and what it does not.** The paper's GICP
proof covers detecting a parameter **increase**, using an upper confidence bound.
Nothing in this decision cites it for decreases. **The mirrored argument is
derived here instead**, and then measured (19.3).

**Derivation: GICP for the upper arm, by coupling.**

1. Drive every chart from one stream of uniforms `U_t`. At true rate `p`, a
   failure is `U_t < p`, and a success is `U_t ≥ p`.
2. The upper statistic's recursion `S ← max(0, S + (Y − r))` is non-decreasing
   in each increment `Y`.
3. For `p' ≤ p`, the success indicators satisfy `1[U ≥ p'] ≥ 1[U ≥ p]` on every
   path. So the statistic at `p'` is pathwise at least the statistic at `p`, and
   its stopping time is pathwise at most. **ARL₀ of the upper arm is
   non-decreasing in the true failure rate.**
4. Hence on the event `p_L ≤ p₀`: `ARL₀(p₀) ≥ ARL₀(p_L) = achieved_arl ≥ T`.
5. The Clopper–Pearson lower bound satisfies `P(p_L ≤ p₀) ≥ 1 − α` (exact
   binomial coverage).
6. So `P(true ARL₀ ≥ T) ≥ 1 − α`. This is the same guarantee ADR-013 §1 states
   for the lower arm, with the sign of the monotonicity reversed.

The same coupling proves the lower arm's case: step 3 with the inequality
flipped. It also predicts that **a breach of `ARL₀ ≥ T` happens only when `p_L`
over-covers** (`p_L > p₀`), which 19.3 confirms numerically.

**Alternatives considered for the upper arm.**

- **Keep `p_U` (as shipped).** Rejected. It is measured at up to 100% breach
  (19.0).
- **Design at `p̂` (plug-in).** Rejected. It has no guarantee, and at f=0 it is
  undefined, as `p_L` is. ADR-013 rejected plug-in design for the lower arm on
  the same evidence (18–32% breach).
- **One two-sided Clopper–Pearson interval at `α/2` each side.** Rejected. It
  changes the lower arm's ratified design (a `p_U` at `α = 0.05`), which is a
  ratified value and outside this decision's scope. Each one-sided arm meets the
  appetite at α = 0.10 as it is (19.3).
- **`p_L` at a different α.** Not considered. α is ratified, and the grid passed
  at 0.10.

#### 19.2 The f = 0 and small-f edges

**f = 0.** `p_L = 0`. The upper arm's in-control success rate would be exactly
1, and there is no improvement left to detect. The reference-value formula is
undefined there.

- **`direction="two_sided"` at f = 0:** the fit **builds the lower arm only**,
  calibrated to the full `T` (not `2T`), since it is the only arm.
  - The artefact reports **`direction = "lower"`**. That is the chart that
    actually runs, and Decision 6d's rejected option ("silently only checking
    the lower arm") is avoided by saying so.
  - It carries `FittingAdvisory(kind="upper_arm_not_designable", boundary=1.0)`.
    The boundary is the smallest baseline failure count at which the
    improvement arm can be designed.
  - `lattice_upper` is `None` for this artefact. `reference_value_upper` and
    `decision_interval_upper` are therefore `float | None`, which changes the
    ratified shape of 6b/14 **only at f = 0**. ⚠️ *corrected by the corrigendum (C3): `lattice_X` is `None` exactly when arm X is not checked, for any f and any requested direction.*
  - Why fit rather than refuse: the ratified default must not refuse the
    healthiest baselines. Decision 12 established that reasoning for this same
    population.
- **`direction="upper"` at f = 0:** **refused.** It is new row F15 in
  Decision 17. There is no value the engineer can pass instead, so no
  round-trip key exists. This mirrors F10's all-failed case.
- **Decision 15's f = 0 fallback (`p_U/M`) is withdrawn.** It is unreachable,
  because `"upper"` refuses at f = 0 and `"two_sided"` becomes `"lower"`.
  `expected_detection_arl` for `"upper"` is always at `p̂/M` with `f ≥ 1`.

**f = 1, 2** (`g3_small_f.py`, T=370): the design is valid at every `m` measured.

```
m        f  p_L        upper N    up  h    achieved  ARL at p̂/M   two-sided (ES) states
100      1  1.05e-3    1,122      1   312  371.0     760.3        25,162
1000     1  1.05e-4    11,215     1   362  370.1     398.1        109,089
10000    2  5.32e-5    22,217     1   366  370.6     373.8        1,452
300000   1  3.51e-7    3,364,300  1   369  370.0     370.1        1,480
```

Two facts follow, and both are recorded rather than hidden.

- **Cost is benign.** `up = 1`, so the statistic counts consecutive successes,
  and `h ≈ T`. `N_upper` reaches 3.4 million at m=300,000, f=1, which takes a
  0.58 s scan. The integer-exact path of Decision 13 is required here: a float
  rebuild would fail far earlier.
- 🚨 **Detection power is essentially nil when `p̂·T ≪ 1`.**
  - The upper arm's ARL at its own target improvement (`p̂/M`) is about equal to
    its in-control ARL₀, or **higher**: 398.1 against 370.1 at m=1000, f=1, and
    760.3 against 371.0 at m=100, f=1.
  - It fires about every T observations whether or not anything improved. That
    is a property of the process, not of this design: with fewer than one
    expected failure per T observations, a halving of the failure rate barely
    changes the waiting time for a long run of successes.
  - **No refusal or drop rule is adopted.** Any threshold on "too little power"
    would be an invented number. ADR-013 §4 already ruled for disclosure over a
    detection-power floor. The number is disclosed by `expected_detection_arl`
    for `"upper"`.
  - For `"two_sided"` there is no improvement-detection figure (Decision 15
    deferred one). Whether to add one is question 9 below.

#### 19.3 Verification: ADR-013 §3's grid for the upper arm at `p_L`, extended below p₀ = 0.02

**Grid:**
- `p₀ ∈ {0.002, 0.005, 0.01}`, below the ratified range, as requested; plus
  ADR-013's `{0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30}`;
- `m ∈ {100, 200, 300, 500, 1000}`;
- 55 cells, `M = 2.0`, `T = 370`;
- the lattice is Decision 7's adaptive `N` with ε = 0.25 (the shipped design),
  not ADR-013's fixed `N = 100`.
- **`T = 370` is ADR-013's own request:** every §3/§4 measurement there is stated
  at "request 370".

**Two independent methods, per ADR-013 §7 item 2** (`g1_upper_grid.py`):
- **A. Exact enumeration** over `f ~ Binomial(m, p₀)` with the production
  helpers. There is no sampling noise, so this is the exact exceedance
  probability.
- **B. 4,000-baseline Monte Carlo** with a from-scratch implementation: its own
  reference value, lattice scan, calibration and sparse solve. It is judged on
  the Clopper–Pearson upper 95% bound, as ADR-013 §3 requires.
- A and B returned **identical** ARLs (relative difference 0.0) on every design
  compared.
- f = 0 has no upper arm (19.2), so it cannot false-alarm. Its share is the
  `P(f=0)` column.

Result for `appetite = P(true ARL₀ < T/2)`, with ratified bar ≤ 5%:

```
                exact A (%)                              MC B upper-95% bound (%)
p0      m=100  m=200  m=300  m=500  m=1000     m=100  m=200  m=300  m=500  m=1000
0.002   0.112  0.006  0.004  0.000  0.000      0.33   0.09   0.09   0.09   0.09
0.005   0.167  0.056  0.016  0.006  0.000      0.39   0.14   0.09   0.09   0.09
0.01    0.343  0.101  0.102  0.021  0.001      0.74   0.36   0.36   0.14   0.09
0.02    0.406  0.253  0.123  0.025  0.002      0.65   0.43   0.33   0.14   0.09
0.03    1.062  0.310  0.205  0.070  0.004      1.19   0.52   0.39   0.26   0.09
0.05    1.147  0.582  0.257  0.086  0.006      1.62   0.98   0.52   0.26   0.09
0.075   1.727  0.444  0.376  0.118  0.007      2.32   0.77   0.74   0.29   0.18
0.10    1.001  0.535  0.242  0.114  0.008      1.56   1.04   0.49   0.22   0.09
0.15    1.189  0.529  0.329  0.104  0.007      1.59   0.83   0.65   0.29   0.09
0.20    1.125  0.410  0.210  0.047  0.003      1.24   0.49   0.46   0.22   0.09
0.30    0.717  0.261  0.083  0.017  0.000      0.95   0.39   0.22   0.14   0.09
```

✅ **Passes in every cell.**
- The worst cell is `(0.075, 100)`: 1.727% exact, 2.32% on the Monte Carlo upper
  bound. That is 2.7 points of headroom, against the lower arm's own 2.57% in
  ADR-013 §3.
- No noise can fake a pass or a breach here. Method A is exact, and method B
  (4,000 reps) agrees with it cell by cell.
- **The mechanism check:** `P(true ARL₀ < T)`, the guarantee, is ≤ 9.74% in
  every cell, under α = 10%. In **44 of 55 cells** it equals `P(p_L > p₀)`, the
  bound's own over-coverage, to the printed precision. In the other 11 it is
  *smaller*: (0.30, 100), (0.20 and 0.30 at m = 200, 300 and 1000), and (0.05,
  0.15, 0.20 and 0.30 at m = 500). Lattice overshoot there turns some
  over-covering baselines into non-breaches. That is
  exactly what the coupling proof in 19.1 predicts: a breach needs over-coverage.
- Full per-cell output, including `P(ARL₀ < T)` and `P(p_L > p₀)`, is in
  `g1_m{100,200,300,500,1000}.out`.

#### 19.4 Two-sided (Q2): equal split, or reallocate on an exact guaranteed bound

**What a two-sided `achieved_arl` means now.** The two arms have different
design rates, so no single rate evaluates the pair. **Decision: the two-sided
`achieved_arl` is `B`, the exact expected run length of the coupled
three-outcome chain.** Using one uniform per step:

| `U` falls in | lower arm | upper arm |
|---|---|---|
| `U < p_L` | failure | failure |
| `p_L ≤ U < p_U` | failure | success |
| `U ≥ p_U` | success | success |

Why `B` is the right number:
- By 19.1's coupling, **`B ≤ true joint ARL₀(p)` for every `p ∈ [p_L, p_U]`**.
  It is a guaranteed floor, not a plug-in estimate.
- It is exactly the conservative "false-alarm promise" `achieved_arl` exists to
  state (ADR-013 §4).
- It is solved exactly on the Decision 8 state space, with the same state count
  as the ordinary joint chain.
- One-sided `achieved_arl` is unchanged in kind: the lower arm is evaluated at
  `p_U`, the upper at `p_L`.

**Two calibrations, measured on the same 55 cells** (`g2_twosided_grid.py`,
exact enumeration):

- **ES (equal split):** each arm is calibrated one-sided to `2T` at its own
  design rate.
- **D (reallocation):** the lower arm is as ES. The upper arm's `h` is the
  smallest with `B ≥ T`. This bisection is valid because `B` is non-decreasing
  in `h_up`: a larger interval delays the upper stopping time pathwise, the same
  coupling.

```
                  worst appetite (bar 5%)   worst P(ARL0<T)   P(B < T)   median B/T      mean true ARL1 at 2·p0 (examples)
ES  equal split   1.781% (0.02, m=200)      6.53%             0 cells    1.01 – 1.27     m=500,p0=0.002: 1,251   m=300,p0=0.002: 1,678
D   reallocation  1.781% (0.02, m=200)      7.88%             0 cells    1.001 – 1.08    m=500,p0=0.002:   908   m=300,p0=0.002: 1,166
```

**Both pass the appetite in every cell.** The worst cell and its value are the
same for both; the full per-cell tables are in `g2_m*.out`.
- **ES over-delivers.** The reported `B` sits 1–27% above the request, and
  `P(B < T)` is 0 in every cell.
- **D delivers what was asked:** a median `B/T` of 1.001–1.08.
- **D detects degradation faster in the low-`p₀` cells:** 27–31% faster at
  `p₀ ≤ 0.005` with `m ≥ 200`, and 56% faster at (0.005, 100). It is within 3%
  of ES at `p₀ ≥ 0.05`.
- **D never increased the upper interval in any cell** (`P(B<T) = 0` under ES),
  so its joint state count is at most ES's. It costs no memory.

**Decision (ratified 2026-09-24): D.** Calibrate the two-sided chart so its guaranteed
bound `B` meets `T`, keeping the lower arm at its equal-split design and giving
the upper arm the remaining budget.
- This is Amendment 2's former option (d). The reason it was held back, an
  upper arm with unverified coverage, is removed by 19.1 and 19.3.
- For comparison with a10, the same cells before and after (`g4_a10_after.py`),
  showing the true joint ARL₀ at `p̂`:

```
m      f    before (upper at p_U, ES): reported / true at p̂    after, D: reported B / true at p̂
300    3    372.0 / 248.8                                        370.4 / 1,809.8
200    20   388.7 / 206.8                                        371.1 / 2,018.0
100    10   382.7 / 147.0                                        373.5 / 4,485.4
1000   5    374.0 / 352.7                                        370.3 / 766.9
1000   0    485.8 / 432.0                                        434.8 (lower arm only, Decision 12's floor) / —
10000  0    632.9 / 684.0                                        4,343.4 (lower arm only, floored) / —
```

**Before:** the reported figure overstated the in-control spacing at `p̂` by up
to 2.6 times. **After:** it is a floor that holds. The price is ADR-013 §4's
known one, conservatism: at the observed rate the chart alarms much *less* often
than requested. That is the direction the ratified appetite permits, and
`expected_detection_arl` discloses what it costs.

**The two-sided grid, checked by a fully independent implementation (Decision
18 item 18, closed 2026-09-24)** (`g5_twosided_independent.py`, output in
`g5.out`):
- It was written from scratch and **imports nothing from `drift_caliper`**:
  its own Clopper–Pearson bounds, reference value, adaptive-`N` scan, one-sided
  calibration, coupled-chain solver (via `splu`) and calibration D.
- It runs 4,000 baselines per cell, is judged on the Clopper–Pearson upper 95%
  bound, and uses the same appetite criterion.

```
cell                       exact (g2, D)   independent MC: point   upper-95%   f=0 draws   designs differing   max rel |B| diff
p0=0.02,  m=200  (2-sided worst)   1.781%   1.55%     1.98%    61/4000     0 of 14 f values    4.1e-15
p0=0.075, m=100  (upper-arm worst) 0.689%   0.75%     1.07%    2/4000      0 of 19             3.6e-14
p0=0.005, m=200                    0.001%   0.00%     0.09%    1,465/4000  0 of 7              9.2e-16
p0=0.002, m=1000                   0.000%   0.00%     0.09%    577/4000    0 of 9              1.5e-16
p0=0.002, m=100  (designable)      0.005%   0.00%     0.09%    3,316/4000  0 of 4              2.6e-15
```

✅ **Every cell passes on its upper bound, the worst being 1.98% against the 5%
bar.**

For every distinct failure count drawn, the independent implementation produced
**the identical design**: the same `(N, r_units, h_units)` for both arms,
including D's `h_up`. Its `B` matched to within floating-point rounding
(≤ 3.6e-14 relative).

⚠️ **What "production's `B`" means here:**
- The comparison pipeline is `g2_twosided_grid.py`, which uses the production
  *design* helpers (reference value, adaptive-`N` finder, one-sided
  calibration) with `g2`'s own coupled-chain solver.
- **Production has no `B` yet**, since it is this decision's proposal. So the
  agreement shown is independent-versus-production on the design, and
  independent-versus-`g2` on `B`.
- The implemented `B` must re-pass this comparison. Decision 18 items 14 and 16
  require that.

**Rejected for two-sided.**
- **ES:** it passes, but it reports and delivers more conservatism than
  requested, and detects more slowly, for no gain in the appetite.
- **Report the joint ARL at `p̂`:** it has no guarantee, and it is the number
  that misled before.
- **Report the minimum of the joint ARL over a grid of `p ∈ [p_L, p_U]`:** it is
  not exact between grid points. `B` is exact and provably at or below that
  minimum.

#### 19.5 Consequences for the artefact, the refusals, Open Question 23 and the verification bar

- **§6b/Decision 14 shape:**
  - add **`p_l: float`**, reported beside `p_u`;
  - `lattice_upper` is `None` only when f = 0 forced `direction = "lower"` ⚠️ *corrected by the corrigendum (C3): `None` exactly when the upper arm is not checked; see also C4.*
    (19.2).
- **Decision 15:** the `"upper"` row keeps `p̂/M`. Its f = 0 fallback is
  withdrawn (19.2).
- **Decision 16:** unchanged. A per-arm cap hit in two-sided mode, including
  inside D's bisection, still routes to F13, with the bisection over `T`
  applying the D calibration.
- **Decision 17**, new rows:

  | # | condition | type | required `context` |
  |---|---|---|---|
  | F15 | `direction="upper"` and the baseline has zero failures | `InvalidParameterError` | `parameter="direction"`, `constraint` (e.g. `"'upper' requires at least one failed judgement in the baseline"`), `kind="invalid"`, `provided="upper"`, `reason="no_baseline_failures"`; no round-trip key |

  Disclosure (not a refusal):
  `FittingAdvisory(kind="upper_arm_not_designable", boundary=1.0)` on a
  two-sided fit at f = 0.
- **Open Question 23** (`docs/domain-model.md`) is **SETTLED by Decision 19**,
  ratified 2026-09-24: the upper arm is designed at
  `p_L`, derived in 19.1 and measured in 19.3. Updating the domain model is
  domain-modeller's step, not done here.
- **Decision 18, extended:**

  13. **Upper-arm GICP grid.** A slow-marked test re-runs 19.3 by exact
      enumeration at (at least) the worst cell `(0.075, 100)` and the three
      sub-0.02 rows at `m = 100`. It asserts appetite ≤ 5% and
      `P(ARL₀ < T) ≤ α`, and pins the exact values to rel 1e-6.
  14. **The coupling bound.** For three baselines, `B ≤` the exact joint ARL at
      `p ∈ {p_L, p̂, p_U}` and at 5 interior points. `B` must also be
      monotone in `h_up`.
  15. **f = 0.**
      - `"two_sided"` returns `direction == "lower"`, the
        `upper_arm_not_designable` advisory, `lattice_upper is None`, and
        `achieved_arl` equal to the one-sided lower fit at `T`.
      - `"upper"` raises F15 with its full key set.
      - f = 1 at m = 300,000 fits all three directions, within the time budget
        of item 12.
  16. **Calibration D.** `B ≥ T`, and `B` at `h_up − 1` is `< T` (minimality),
      on the a10 cells above.
  17. **Differential and simulated-ARL tests (items 1–2) cover a `p_L`-designed
      upper arm.** Item 2's simulated two-sided run must be driven at `p̂` *and*
      at both bounds, and assert the simulated mean `≥ B` within tolerance at
      each.
  18. ✅ **Done 2026-09-24; see 19.4's independent table.** *Original
      requirement:* **Second method for the two-sided grid.** The 19.4 grid rests on exact
      enumeration plus a from-scratch joint solver (`joint3`) that is
      independent of production's joint solver. The production *design*
      helpers are shared, however. A 4,000-rep Monte Carlo of the two-sided
      appetite at the worst ES/D cell `(0.02, 200)` is required before
      ratification is treated as closed, to meet ADR-013 §7 item 2 fully for
      two-sided.
  19. **`expected_improvement_detection_arl`:** as specified in 19.6.

#### 19.6 `expected_improvement_detection_arl` (Q9, ratified 2026-09-24)

**Field:** `expected_improvement_detection_arl: float | None` on
`FittedBernoulliCUSUM`. It amends §6b and Decision 14.

**Definition.** The exact ARL of the constructed two-sided chart, meaning the
joint chain of Decision 8 with Decision 13's integer lattices and calibration
D's intervals, evaluated at the single true failure rate **`p̂ / M`**. That is
the improvement the upper arm is tuned to detect, the mirror of
`expected_detection_arl`'s `p̂ · M` and the same rate Decision 15 uses for
`"upper"`.
- It is a number, not a warning. There is no threshold and no advisory tied to
  it.
- **`p̂ = 0` never reaches it.** At f = 0 a two-sided request becomes
  `direction="lower"` (19.2), so the field is `None`. For every f ≥ 1,
  `p̂/M > 0` and the rate is well-defined, so **no fallback exists or is needed**.

**Which directions carry it. Rule: it is non-`None` exactly when the chart
checks both arms.**

| artefact `direction` | `expected_detection_arl` | `expected_improvement_detection_arl` |
|---|---|---|
| `"two_sided"` (f ≥ 1) | joint chain at `p̂·M` (degradation) | **joint chain at `p̂/M`** |
| `"lower"`, requested or forced by f = 0 | lower arm at `p̂·M` (`p_U·M` at f = 0) | `None`: no upper arm is checked |
| `"upper"` | upper arm at `p̂/M` (Decision 15, the improvement) | `None`: `expected_detection_arl` already is the improvement figure |

**Why `"upper"` does not repeat it.** For an upper-only chart the improvement
*is* the shift it is tuned to detect, so Decision 15 already puts that number in
`expected_detection_arl`. Carrying it twice would give two fields meaning the
same thing. The rule stays a single sentence: `expected_detection_arl` is the
headline tuned shift; `expected_improvement_detection_arl` is the second arm's
figure, present only on a two-armed chart.

**Measured, calibration D, T = 370** (`g6_improvement_field.py`):

```
m     f    B (achieved)   expected_detection_arl (p̂·M)   expected_improvement_detection_arl (p̂/M)
100   1    370.4          8,239.9                          1,416.5
1000  1    370.1          570.8                            504.7
1000  5    370.3          558.1                            580.9
300   3    370.4          953.2                            780.3
200   20   371.1          115.8                            220.1
100   10   373.5          188.1                            334.5
150   40   382.6          41.2                             85.5
```

It makes 19.2's finding visible without a warning. At m=1000 f=5 the figure
(580.9) is **above** `B` (370.3): at the design improvement, the chart signals no
sooner than it would false-alarm.

**Verification (Decision 18 item 19).**
- For the cells above, the field equals an independent reference joint solver
  at `p̂/M` to rel 1e-9.
- It is `None` for `"lower"`, for `"upper"`, and for an f = 0 two-sided request.
- It is finite and ≥ 1 whenever present, under Decision 13.4's postcondition,
  which extends to this field with `figure="expected_improvement_detection_arl"`
  in F14.
- It survives the serialisation round-trip of item 11.
- The registry test of item 10 covers the extended F14.

---

### Summary of changes to the ADR body (Amendment 2)

| decision | status |
|---|---|
| Decision 3 item 2 (computed attainability floor, refuse below it) | **superseded, if ratified**, by Decision 12: fit, report and disclose |
| Decision 4 (`expected_detection_arl` first-class) | **amended** by Decision 15: evaluated at the checked arm's own tuned shift |
| Decision 6b (field shape) | **amended** by Decision 14: `lattice_lower`/`lattice_upper` stored; the four floats become derived |
| Decision 8 (independent lattices) | **completed** by Decision 13.1: integers end to end, no reconstruction |
| Decision 10a (search cap) | **amended** by Decisions 13.3 and 16: cap is 999,999 units; two-sided hits are routed to F13 |
| Decision 10b (joint cap) | **unchanged** (1,000,000). The one-sided "≤ ~40,000 states" claim is **corrected** (§0) |
| Decision 11 (verification bar) | **extended** by Decision 18; item 8's "< 1 s" is withdrawn |
| **NEW Decisions 12–18** | as above, **ratified 2026-09-24** |
| Decision 6d (`p_U` for both arms) | **superseded** by Decision 19: the upper arm is designed at `p_L`. Open Question 23 is **settled** |
| Decision 6b / 14 (shape) | **amended** by Decision 19: adds `p_l` and `expected_improvement_detection_arl` (19.6). At f = 0 two-sided, `lattice_upper` is `None` and the three upper-arm fields are optional ⚠️ *corrected by the corrigendum (C3): `None` whenever the arm is not checked* |
| Decision 6c (two-sided `achieved_arl`) | **amended** by Decision 19: the coupled bound `B`, calibrated per option D |
| Decision 15 | f = 0 upper fallback **withdrawn** by Decision 19 |
| **NEW Decision 19** | **ratified 2026-09-24**: upper arm at `p_L`, f = 0 rules, two-sided `B` with calibration D, and `expected_improvement_detection_arl` |

### Questions for the product owner — ruled 2026-09-24

All ten questions were ruled on 2026-09-24; the full list is in the status
header. The questions are kept below **as they were asked**, for the record. Each
now carries its ruling, and any pre-ruling drafting advice inside them is
superseded by that ruling.


1. *(Accepted.)* **Decision 12: replace Decision 3 item 2's ratified refusal
   with fit-and-disclose?** If you keep the refusal (option (a)), f=0 baselines
   of 5,000 or more observations become unfittable two-sided at every
   `target_arl`, and one-sided `target_arl = 370` is refused for every f=0
   baseline with m ≥ 851.
2. **Option (d), two-sided budget reallocation: now, later, or never?** It
   delivers about 370 where the equal split gives 552–728 at large clean
   baselines. The cost is that the unverified upper arm carries most of the
   false-alarm budget. *(Ruled with Q8: adopted as calibration D once the upper
   arm was redesigned at `p_L`.)*
3. *(Accepted.)* **Decision 13.3: lower the one-sided search cap from 2,000,000 to 999,999
   units**, matching the ratified 1M joint-state memory budget? Nothing
   measured up to m=3,000,000 is refused by the change.
4. *(Accepted.)* **Decision 13.4: raise `DegenerateBaselineError(reason="arl_not_computable")`
   for the postcondition**, reversing the documented "never raises
   `DegenerateBaselineError`"? The alternative is a new `reason` on
   `InvalidParameterError` naming `baseline`.
5. *(Accepted.)* **Decision 14: the nested `BernoulliArmLattice` shape and its name**, and
   public fields rather than private ones (they must survive serialisation).
6. *(Accepted; f=0 fallback withdrawn by Decision 19.)* **Decision 15: the upper-only `expected_detection_arl` evaluated at
   `p̂/M`**, falling back to `p_U/M` at f=0.
7. *(Overruled "later": fix now; see Decision 19.)* **Open Question 23 priority.** The measured evidence (Decision 12's
   context table) shows the upper arm alarming 1.4–3.6 times more often at
   `p̂` than its reported `achieved_arl`. Should that study be scheduled before
   the Bernoulli CUSUM ships two-sided by default?

### Questions for the product owner — Decision 19 (ruled 2026-09-24)

8. *(Ratified.)* **Ratify Decision 19's numbers:**
   - the upper arm at `p_L` (α = 0.10);
   - the 55-cell grid (worst appetite 1.727% exact, 2.32% MC upper bound);
   - two-sided `achieved_arl` defined as the coupled bound `B`;
   - calibration **D**, which keeps the equal split for the lower arm and gives
     the upper arm the remaining budget (chosen over ES; both pass).
9. *(Accepted as a number, not a warning; see 19.6.)* **Two-sided improvement detection.** When `p̂·T ≪ 1`, the upper arm has
   essentially no power (19.2), and for `"two_sided"` nothing discloses this.
   Should a second detection figure (the upper arm's ARL at `p̂/M`) be added,
   or is this left undisclosed for two-sided? No drop rule is adopted, because
   any power threshold would be an invented number.
10. *(Accepted.)* **The f = 0 two-sided artefact reports `direction = "lower"`**, with the
    `upper_arm_not_designable` advisory and `lattice_upper = None`. Is that
    shape acceptable, given it makes three upper-arm fields optional?

### 🚨 What Amendment 2 deliberately does not decide

- ~~The upper arm's GICP coverage (Open Question 23)~~,
  ~~whether the equal `2T` split should change~~ and
  ~~a detection figure for the upper arm of a two-sided chart~~: **all settled by
  Decision 19**, ratified 2026-09-24. They were addressed in 19.1–19.3, 19.4 and
  19.6 respectively.
- **A power threshold, or any refusal or drop rule, for an upper arm with no
  detection power.** Deliberately not decided: any threshold would be invented.
  The number is disclosed (19.6) instead.
- **α for `p_L`.** It is taken as ADR-013's ratified 0.10, and is not re-derived.
  The grid passed at it, so no adjustment was needed.
- **Test runtime and Codecov patch coverage** (the reviewer's Blocker 6 and
  Recommendations 1–2, 6). These are implementation, not architecture. Item 12
  above sets the one budget that belongs here.
- **`docs/domain-model.md`.** Domain-modeller's step, not performed here.
- **An iterative solver** (bicgstab or gmres) in place of the direct sparse
  solves, to cut per-solve time and memory. Raised separately as its own ticket
  (see the corrigendum's C11).

---

### Amendment 2 corrigendum (2026-09-24)

**Why this exists.** domain-modeller, modelling the committed Amendment 2
(`e828a06`), found that it contradicts itself in places. It recorded these as
Open Questions 29–36 in `docs/domain-model.md`. The coordinator also
reproduced three failures of `detect_rate_multiple` on PR #29. Ratified text
above is **not** edited. Each line that is now wrong carries a visible
"⚠️ corrected by the corrigendum, below (Cn)" pointer.

**Status:** ✅ **ACCEPTED 2026-09-24.** C12 corrects it within the ratified
decisions, and reports one new defect (C12.4).
- **C1, C4–C10** are specification corrections. They follow from decisions
  already ratified.
- **C2's lower bound:** ruled by the product owner as C-Q1, option (A).
- **C3:** ruled as C-Q2.
- **C11:** ruled as C-Q3. The direction is an equal-split conservative bound.
  Its premise was measured to hold in all 302 designs checked, and a one-solve
  guard makes correctness independent of that premise.

All measurements use the scripts in `scratchpad/amend2/`: `h1`–`h6`, and for
C11 `k1b_premise.py`, `k2_es_bound.py` and `k3_refusal_time.py`. Every
figure is **re-measured under the ratified behaviour**:
- upper arm at `p_L`;
- f = 0 two-sided becomes lower-only; `"upper"` at f = 0 raises F15;
- calibration D, with `B` as the two-sided `achieved_arl`;
- caps of 999,999 units per arm and 1,000,000 joint states.

The implementation is the fully independent one from `g5`, extended with the
caps. It imports nothing from `drift_caliper`. **No figure computed under
superseded behaviour is reused.**

#### C1. Decision 18's f = 0 cells, re-based (Open Question 36)

`h1_d18_cells.py`, output `h1.out`.

| item | cell | required outcome, re-measured |
|---|---|---|
| 5 | m ∈ {852, 1000, 5000, 300000}, f=0, `"lower"`, T=370 | `h_units = 1`, `achieved_arl = 1/p_U` = 370.5191, 434.7947, 2171.9724, 130288.8446. `lower_arm_signals_on_first_failure` present, with `boundary == achieved_arl` |
| 5 | m=300 f=3 `"lower"` **T=40** | floored: 45.1815, advisory present. ⚠️ **The original cell, T=50, was wrong even before Decision 19.** 50 falls in the *gap* above the floor, giving `h_units = 26`, `achieved_arl` 147.5931, and **no** advisory. T=50 is kept as the gap case, asserting the advisory is **absent** |
| 5 | m=5000 f=0 **`"two_sided"`** T=370 | returns **`direction = "lower"`**, `achieved_arl` 2171.9724, with **both** advisories (`lower_arm_signals_on_first_failure`, `upper_arm_not_designable`) and `lattice_upper is None`. It replaces "fits at 552.2" |
| 5 | advisory absent | m=300 f=0 `"lower"` T=370: `h_units = 77`, 423.8900 |
| 5 | F15 | m=1000 f=0 `"upper"` → F15 with its full key set |
| 3 | m=300,000 **f=1**, `"lower"` | T=370: floored, 77126.7422. T=10⁶: `h = 101,595`, 1000018.2953 |
| 3 | m=300,000 f=1, `"upper"` | T=370: `N = 3,364,300`, `h = 369`, 370.0241. T=10⁶: `h = 857,041`, 1000001.1949 (fits; **not** F12) |
| 3 | m=300,000 f=1, `"two_sided"` | T=370: `h = (1, 370)`, 742 states, `B` 370.1115, `expected_detection_arl` 370.5428, `expected_improvement_detection_arl` 370.8856. T=10⁶: **F13**, because the upper arm's per-arm target of 2·10⁶ exceeds the 999,999-unit cap (Decision 16's route) |
| 3 | m=300,000 **f=30** | `"upper"` T=370: 370.2214. `"upper"` T=10⁶: `h = 81,621`, 1000026.7807. `"two_sided"` T=370: `h = (1, 379)`, 760 states, `B` 370.9495 |
| 8 | `"upper"` `expected_detection_arl` at `p̂/M`, upper arm at `p_L` | m=150 f=40: 72.1128. m=200 f=20: 157.6429. m=1000 f=1: 398.1379. ⚠️ **The original 32.8 and 61.3 were computed with the upper arm at `p_U`**, and 314.1 is the withdrawn f = 0 fallback. All three are withdrawn |
| 12 | F13 refusal-path budget | re-based to f ≥ 1. m=300,000 f=1 `"two_sided"` T=10⁶ refuses. Under the D bisection, `max_two_sided_target_arl` was 38,562, took 17.8 s, and was over the 5 s budget. **Resolved by C11:** the equal-split bound reports 38,563 in 2.2 s end to end, and the budget is replaced |

**Decision 16's reachability, re-measured at f ≥ 1.** The per-arm search cap is
reached in two-sided mode at m=300,000 f=1 T=10⁶ (the upper arm at 2·10⁶ hits
the cap) and routes to F13, as Decision 16 decides. Its original measurement
cell (m=3,000,000 **f=0**) no longer describes a two-sided fit. The route is
still reachable, at f ≥ 1.

#### C2. `detect_rate_multiple`: a legal range, and an O(log N) lattice finder

**Reproduced on PR #29 by the coordinator** (m=200 f=20 T=370):
- `M=1.0` leaks `ZeroDivisionError`;
- `M=0.5` leaks `ValueError`;
- `M=1.0000001` **hangs**.

**The hang is Decision 7's linear scan, not the chain.** The scan walks `N`
upward and is bounded only by `⌈1/(2ε·gap)⌉`. As M → 1⁺ the gap shrinks to 0.
Closed-form bounds, `h2_m_range.py`:

| baseline | M | lower-arm bound | upper-arm bound |
|---|---|---|---|
| m=10,000 f=1 | 1.05 | 102,851 | 3,986,335 |
| m=10,000 f=1 | 1.0001 | 51,425,011 | 1,898,444,142 |
| m=200 f=20 | 1.0000001 | ≈1.5×10⁸ | ≈3.4×10⁸ |

**C2 part 1: specification correction, not a PO item.** Replace the scan with
the **smallest-denominator rational in the closed interval
`[r − ε·gap, r + ε·gap]`**. That is the classic continued-fraction
(Stern–Brocot) construction, done in exact `Fraction` arithmetic. Then take
`k = round(r·N)` at that `N` and verify both Decision 7 invariants exactly.
- It is the same decision rule as the scan, with the same output.
- **Measured identical to the scan on 797 of 797 real design points** ⚠️ *corrected by the corrigendum (C12.4): M ≤ 3 only, and the finder was wrong at large M. It is replaced by the exact finder, identical on 6,994 points including M > 3.*
  (`h3_m_near_one.py`, both arms, M ∈ [1.01, 3], m ≤ 3,000, all 1 ≤ f ≤ m/4).
- It takes 0.1–0.2 ms per design **even at M − 1 = 10⁻⁷**, where the scan would
  walk hundreds of millions of steps.
- Once the finder is logarithmic, Decision 13.3's caps bound everything else.

  | m=200 f=20, M | lower | upper | two-sided | time |
  |---|---|---|---|---|
  | 1.1 | fits, `h` 127 | fits, `h` 61 | fits | 0.07 s |
  | 1.001 | fits, `h` 879 | fits, `h` 825 | F13 | 8.7 s |
  | 1.0000001 | fits, `h` 54,736 | fits, `h` 66,483 | F13 | 3.1 s |

  The times exclude `max_two_sided_target_arl`, which C11 resolves (16.4 s
  end to end at M = 1.001).

**The legal range.**
- **M ≤ 1 is refused (specification correction).** `M = 1` detects no shift,
  since `p₁ = p₀`. `M < 1` would design the "degradation" arm to detect an
  *improvement*, mislabelled, and would put the upper arm's design point
  `p_L/M` above `p_L`. ADR-012's reference value needs `p₀ < p₁`, so no
  design exists for either.
- **Just above 1, double precision runs out.** `h4_resolution.py` swept
  M − 1 = 10⁻¹ … 10⁻¹⁵ over 11 baselines (m from 100 to 300,000, f from 0 to
  60). Every baseline is constructible down to M − 1 = 10⁻⁷, and every one
  fails at 10⁻⁸ or 10⁻⁹. None succeeds below its first failure, so the failure
  is monotone. This matches the error analysis:
  - the float error in `r` is about `p₀·ε_mach/(M − 1)`;
  - the tolerance it must sit inside is `ε·p₀·(M − 1)`;
  - so the design becomes unverifiable when `(M − 1)² ~ ε_mach`, that is at
    M − 1 ≈ 1.5×10⁻⁸.

✅ **Ratified 2026-09-24 (C-Q1): option (A).** The lower bound is computed per
fit. Every option refused through one new row, F16, and they differed only in
`min_value`; (B) and (C) are recorded as rejected.

- **(A) Ratified: computed per fit.** `min_value` is the smallest M, found
  by bisection on `log(M − 1)` over (0, 1] with ≤ 64 probes of the finder, for
  which both arms' design is constructible and verified in double precision. ⚠️ *corrected by the corrigendum (C12.1): "every arm the fit designs"; `min_value` is the nearest constructible multiple at or above the request.*
  - It **round-trips by construction**, because the bisection returns a
    verified value.
  - No constant is invented.
  - It admits any M the maths can represent, which is ADR-011's principle of
    *informed choice over refusal*. Such an M may still be refused later by
    F12/F13, each with its own round-tripping bound.
- **(B) Rejected: fixed `MIN_DETECT_RATE_MULTIPLE = 1.25`.** This is the smallest multiple
  ADR-012 §1's regret study measured, so it is sourced. But it refuses designs
  that are exact and cheap: M = 1.1 and 1.01 fit in under 0.3 s at m=200 f=20.
  That substitutes the library's caution for the engineer's judgement, which
  ADR-011 rejects.
- **(C) A fixed "safe margin" such as 1 + 10⁻⁶.** Rejected as an invented
  number.

**F16**, which applies whichever option is ruled:

| # | condition | type | required `context` |
|---|---|---|---|
| F16 | `detect_rate_multiple` ≤ 1, or below the smallest multiple the design can resolve | `InvalidParameterError` | `parameter="detect_rate_multiple"`, `constraint`, `kind="invalid"`, `provided`, `reason` (`"no_shift_to_detect"` for M ≤ 1; `"shift_below_numerical_resolution"` for 1 < M < `min_value`), `min_value` (the computed bound under (A)), `min_inclusive=True` |

**F7 narrows** to a non-finite `detect_rate_multiple`, with `parameter`,
`constraint`, `kind="invalid"` and `provided`. Its `min_value=0.0` and
`min_inclusive=False` are withdrawn, because F16 now owns every lower bound.
F11's upper bound is unchanged.

**If `min_value` exceeds F11's `max_detect_rate_multiple`, no M works.** That
happens only when `p_U` is close to 1/2. F16 then raises with
`reason="no_valid_multiple"` and **no** `min_value`, mirroring F10. Measuring
where it fires is verification item 20.

#### C3. ✅ Ratified 2026-09-24 (C-Q2): which arms a fit carries (Open Questions 29 and 31)

**Measured first** (`h6_unchecked_arm.py`). In a one-sided `"lower"` fit, the
unchecked upper arm's calibration **never hit the cap**, up to m=3,000,000 f=1
at T=10⁶ (`h` 857,041, 950,750 and 982,840).

There is a proof for the f ≥ 1 upper arm, whose `up = 1`. It needs at least
`h + 1` consecutive successes to signal, so `ARL(h) ≥ h + 1`, and hence the
smallest adequate `h` is at most `T − 1 ≤ 999,999`. So Open Question 31's feared
spurious F12 is **not reachable** on this arm. It still costs most of the
fit's time at large T: 4.4–6.0 s.

**Rule (ratified):** `lattice_X is None` **exactly when the artefact's
`direction` does not check arm X**. This answers Open Question 29 for a
directly requested `"lower"` at f = 0 (`lattice_upper is None`), and it
replaces 19.5's "only when f = 0 forced lower" with one rule that can always
hold.
- A one-sided fit designs and calibrates **only** the arm it checks.
- F12's `direction` key names that arm.
- `Monitor` accumulates only the checked arms.
- **It reverses 6b's** "both arms always designed and reported regardless of
  `direction`". What is lost: an engineer can no longer read off what a
  direction change would produce without refitting. A refit is cheap, and the
  artefact's `direction` is frozen anyway.
- **Rejected alternative:** keep 6b. Then OQ-29 is answered as "the upper lattice is
  `None` at f = 0 whatever was requested". The `upper_arm_not_designable`
  advisory attaches to a requested `"lower"` at f = 0 as well, and the
  unchecked arm keeps costing time.

#### C4. `Monitor` with an upper-checking artefact that has no upper lattice (Open Question 30)

Specification correction. It extends M2. If `direction` checks an arm whose
lattice is `None`, the result is `InvalidParameterError` with:
- `parameter="artefact"`;
- `constraint` (e.g. `"must be a BernoulliArmLattice when direction checks this arm"`);
- `kind="invalid"`;
- `field="lattice_upper"` or `"lattice_lower"`;
- `provided_type="NoneType"` (see C6).

The check runs in `Monitor.record()` before any state changes, beside
Decision 14.5's integer checks. It must never leak `AttributeError` or
`TypeError` (BIN-121).

#### C5. `calibration_method` (Open Question 33)

Specification correction.
- `"gicp_markov_chain"` for one-sided fits: exact, at the arm's own
  conservative bound. Unchanged in meaning.
- **`"gicp_markov_chain_coupled_bound"`** for two-sided fits: `achieved_arl`
  is the coupled floor `B` under calibration D.
- The string changes, so an auditor can tell a pre-Amendment-2 two-sided
  figure from a post-Amendment-2 one.
- **§6c's `"gicp_markov_chain_harmonic_combination"` fallback is withdrawn.**
  The exact coupled solve is ratified and implemented in both independent
  checks, so no approximate path may ship.

#### C6. `provided` vs `provided_type` (Open Question 35)

Specification correction, following the existing guard (BIN-143). The rule
applies to every row in Decision 17: ⚠️ *corrected by the corrigendum (C12.2): only the `require_exact_str` family (F8, M2, C4, M3); F1, F4 and F6 keep `provided`.*
- **A type failure reports `provided_type`, never the value.** A hostile
  object's `repr` can raise inside the error path, so the value is not touched.
- **A value failure on an already exact-typed value reports `provided`,**
  which is safe to carry.

So:
- F8's not-a-`str` path emits `provided_type`, and its unknown-string path
  emits `provided`.
- M2 and C4 emit `provided_type` for a non-exact `int` or a `None` lattice,
  and `provided` for an exact `int` that is out of bounds.
- M3 emits `provided_type`, as it already does.

This is the documented exception to ADR-002 §3's "`provided` whenever `kind ==
"invalid"`" that BIN-143 already practises. **The registry test (Decision 17)
asserts exactly one of `provided` / `provided_type` per invalid-kind row, as
this rule assigns.**

#### C7. BIN-142's finite-float backstop (Open Question 34)

Specification correction.
- The validator must cover fields annotated `float` **and** `float | None`,
  skipping `None`.
- The computed float properties (Decision 14.3) need no check. Each is `units
  / denominator` over validated `int`s with `denominator ≥ 2`, so it is always
  finite.
- Test (verification item 21): direct construction with a `NaN` or `inf`
  `expected_improvement_detection_arl` raises the existing BIN-142
  `InvalidParameterError`.

#### C8. Decision 15's table

Specification correction. The `"two_sided"` row's f = 0 fallback (`p_U × M`)
is **unreachable**, because at f = 0 a two-sided request becomes `"lower"`
(19.2) and takes the `"lower"` row. The `"lower"` row's f = 0 fallback
(`p_U × M`) stands.

#### C9. Decision 13.2's "N stays under 2×10⁶"

Specification correction. **The claim is false:** `N_upper` = 3,364,300 at
m=300,000 f=1 (C1), and `N` is unbounded in principle as M → 1⁺ (C2).
**Nothing depends on it.** Python `int` is unbounded; state counts depend on
`h_units`, not on `N`; and C2's finder is logarithmic in `N`. The sentence is
withdrawn, and Decision 13.2's conclusion (no bound on `N`) stands.

#### C10. F14's `figure` values

Specification correction. F14's `figure` is one of **`"achieved_arl"`,
`"expected_detection_arl"`, `"expected_improvement_detection_arl"`**, the third
added by 19.6. The registry test enumerates all three.

#### C11. ✅ Ratified 2026-09-24 (C-Q3): `max_two_sided_target_arl` comes from the equal-split state count, in lattice space, with a one-solve guard

**The ruling.** The product owner rejected the 17.8–137 s refusal and ruled to
build the cheaper conservative bound first, with its premise verified. This
section is that bound, and the evidence behind it.

**Definition.** When F13 fires, the reported `max_two_sided_target_arl` is
`floor(T_ES)`, capped at `MAX_MEANINGFUL_ARL`, where

```
T_ES = max over a >= 1 of  min( A_lo(a), A_up(H(a)) ) / 2,     H(a) = floor(1,000,000 / (a + 1)) - 1
```

- `A_lo(a)` is the one-sided in-control ARL of the lower arm at `h_units = a`,
  at `p_U`.
- `A_up(b)` is the same for the upper arm at `h_units = b`, at `1 − p_L`.
- `T_ES` is the largest two-sided target whose **equal-split** design fits the
  joint cap.

**Why this is the equal-split maximum, and why a bisection finds it**
(derived, not measured):

1. **ES state count is non-decreasing in T.** The calibrated interval
   `h_arm(2T)` is the smallest `h` with `A_arm(h) ≥ 2T`. `A_arm` is
   non-decreasing in `h`: by coupling, a wider interval delays the stopping
   time on every path. So each `h_arm(2T)` is non-decreasing in T, and so is
   the product `(h_lo + 1)(h_up + 1)`. The coordinator's monotonicity question
   is answered by proof.
2. **The ES design fits at T exactly when the formula above allows it.** It
   fits iff some `a` satisfies both `A_lo(a) ≥ 2T` and `A_up(H(a)) ≥ 2T`.
   That is because `(x + 1)(y + 1) ≤ 1,000,000` iff `y ≤ H(x)`, and
   `h_arm(2T) ≤ c` iff `A_arm(c) ≥ 2T`. Hence `2·T_ES` is the maximum over `a`
   of the minimum.
3. **So a bisection on `a` finds the maximum.** `A_lo(a)` is non-decreasing
   in `a`, and `A_up(H(a))` is non-increasing. The maximum of their minimum
   sits at the crossing. The bisection makes about 19 probes, each two
   one-sided solves, **with no joint solve**.
4. **Ill-conditioned solves.** A one-sided solve whose postcondition fails
   (its ARL is beyond double resolution) steers the search as "+∞" under
   BIN-140's rule, and is never reported. The reported value is the minimum
   over two finite sides. Without this rule, three of the measured cells
   crashed during the search.

**The premise: calibration D never needs more states than ES.** D keeps
`h_lo = h_lo_ES` and takes the smallest `h_up` with `B ≥ T`, and `B` is
non-decreasing in `h_up`. So

```
states_D(T) <= states_ES(T)   <=>   B(h_lo_ES, h_up_ES) >= T.
```

- **It is not provable from the construction.** It amounts to "the expected
  minimum of two *dependent* stopping times, each with mean ≥ 2T, is ≥ T".
  That does not hold for arbitrary dependence. I could not derive it for
  this coupling, and I do not claim it.
- **Measured** (`k1b_premise.py`, fully independent code), across:
  - m ∈ {100, 200, 300, 1000, 10000, 300000};
  - f ∈ {1, 2, 5, m/10, 3m/10};
  - M ∈ {3, 2, 1.1, 1.001, and 1 + 2·(M_min − 1)}, where M_min is C2's
    computed floor;
  - T ∈ {10, 370, 10⁴, 10⁶};
  - every ES design under the cap: **302 designs**.
- **Result: zero failures. The smallest margin is `B_ES/T = 1.0025`**
  (m=100 f=30 M=1.1 T=10⁴). The margin is thin, at a quarter of a percent.
- **Coverage gap, stated.** Some of the T=10⁶, M=1.1, large-f cells at
  m ∈ {1000, 10000, 300000} did not complete: each single cell ran over 20
  minutes under 14-way contention, and I stopped them. Those cells are
  unmeasured, not passed.

**Because the premise is empirical and its margin thin, correctness does not
rest on it.** At the reported value, the refusal path computes the ES design
and **one** coupled solve. If `B_ES ≥ T` and the ES states are ≤ 1,000,000,
then D provably fits at that value, so the value round-trips by construction.
If the guard ever fails, the refusal falls back to the exact D maximum (h5's
bisection): slow but correct, and **never observed**. The report is never an
unverified number.

**Measured end-to-end refusal times, one process, no contention**
(`k3_refusal_time.py`):

| cell | D feasibility check at the request* | ES bound | guard | total | reported | guard `B_ES/T` |
|---|---|---|---|---|---|---|
| m=300,000 f=1 M=2 T=10⁶ (was 17.8 s) | 1.5 s | 0.4 s | 0.3 s | **2.2 s** | 38,563 | 1.2544 |
| m=1000 f=5 M=2 T=10⁶ (was 137.3 s) | 10.2 s | 4.0 s | 5.7 s | **19.9 s** | 21,634 | 1.0230 |
| m=200 f=20 M=1.001 T=370 (was 70.9 s) | 8.6 s | 1.5 s | 6.3 s | **16.4 s** | 249 | 1.0435 |
| m=3,000,000 f=1 M=2 T=10⁶ | 2.3 s | 0.2 s | 2.3 s | 4.8 s | 252,207 | 1.4589 |
| m=1000 f=1 M=2 T=10⁶ | 18.4 s | 0.9 s | 24.9 s | 44.3 s | 1,700 | 1.2429 |
| m=300,000 f=30 M=2 T=10⁶ | 2.6 s | 0.7 s | 0.0 s | 3.3 s | 3,914 | 1.0850 |
| m=1000 f=5 **M=1.01** T=10⁵ (worst corner found) | 95.5 s | 3.0 s | 5.7 s | 104.2 s | 1,471 | 1.1005 |

\* The first column is the same two per-arm calibrations and capped coupled
check that **any** two-sided fit at that T performs to decide whether it
fits. It is the fit's own cost, not the refusal's. What the refusal adds is
the ES bound plus the guard: **0.7–25.8 s**, against 17.8–137.3 s for the D
bisection it replaces. The guard's remaining cost is its own two
calibrations. Bracketing them by `a*` and `H(a*)` from the ES search is a
cheaper implementation, and it is not measured here.

**How conservative it is, and whether it round-trips** (`k2_es_bound.py`
`--dmax`, run against the true D maximum from h5's bisection, which is exact
to ±1):

| cell | ES bound | true D max | ratio | round-trips under ES and D |
|---|---|---|---|---|
| m=300,000 f=1 M=2 T=10⁶ | 38,563 | 38,562 | 1.0000† | yes |
| m=300,000 f=30 M=2 T=10⁶ | 3,914 | 3,914 | 1.0000 | yes |
| m=10,000 f=1 M=2 T=10⁶ | 1,285 | 1,285 | 1.0000 | yes |
| m=1000 f=5 M=2 T=10⁶ | 21,634 | 22,196 | 0.9747 | yes |
| m=200 f=20 M=1.001 T=370 | 249 | 259 | 0.9614 | yes |
| m=1000 f=5 M=1.01 T=10⁵ | 1,471 | 1,614 | 0.9114 | yes |
| m=1000 f=1 M=2 T=10⁶ | 1,700 | 2,168 | 0.7841 | yes |
| m=3,000,000 f=1 M=2 T=10⁶ | 252,207 | 367,937 | **0.6855** | yes |

† One above the ±1 bisection's floor, which is within its tolerance.

**Summary: it is conservative by 0–31%, and it round-trips in every measured
cell.** The largest shortfall is where the lower arm is floored
(`a* = 1`, m=3,000,000 f=1). There, D's upper arm gains most over equal split.

**Decision (ratified 2026-09-24):**
- `max_two_sided_target_arl` is `floor(T_ES)` (capped at
  `MAX_MEANINGFUL_ARL`), with the guard and the fallback described above.
- F13's other keys are unchanged.
- The lattice-space *D* search (one joint solve per `a` probe) is **not
  adopted**. D's feasible region is not shown to be unimodal in `a`, so a
  bisection there would be unjustified. The ES search is fast enough without
  it.

**Decision 18 item 12 is replaced** (the 5 s figure was never met). The
refusal path's overhead, meaning the ES bound plus the guard, beyond the fit's
own feasibility check, must be **≤ 30 s locally** at every refusal cell in the
table above. The measured maximum is 25.8 s.
- This is an engineering budget set from measurement, not a statistical
  constant.
- The fit's own feasibility check is **not** budgeted here. Its cost is the
  per-solve cost of one-sided chains near the 999,999-unit cap (95.5 s at the
  M=1.01 corner). That belongs to the iterative-solver question, which is out
  of scope below.

**What this corrigendum does not decide.** Whether the direct sparse solves
(`spsolve`/`splu`) should give way to an iterative solver (bicgstab, gmres) to
cut per-solve time and memory. That is raised separately as its own ticket.

#### Verification bar additions (Decision 18, continued)

20. **C2.**
    - The finder equals the linear scan on every design point where the scan
      is feasible: Hypothesis over the full legal space, both arms.
    - `M=1.0` and `M=0.5` raise F16 (`"no_shift_to_detect"`), with no
      `ZeroDivisionError` or `ValueError`.
    - `M=1.0000001` at m=200 f=20 completes within the F12/F13 caps.
    - Under (A): `min_value` round-trips, and `min_value` minus one float step
      raises F16 (`"shift_below_numerical_resolution"`).
    - Measure whether the `"no_valid_multiple"` case is reachable, and pin it
      if it is.
21. **C7.** The finite-float backstop covers `float | None`.
22. **C3/C4.** The `lattice_*` presence rule holds for every direction and f.
    `Monitor` raises C4's row for an upper-checking artefact with no upper
    lattice.
23. **C5/C6/C10.** The `calibration_method` strings are correct. The registry
    test asserts the `provided`/`provided_type` assignment and all three F14
    `figure` values.
24. **C11.**
    - `max_two_sided_target_arl` equals `floor(T_ES)` computed by an
      independent reference on the refusal cells in C11's table (38,563;
      21,634; 249; 1,471; 1,700; 3,914).
    - Passing it back fits, under both ES and D.
    - The ES state count is monotone in T (Hypothesis).
    - The guard's fallback path is exercised by monkeypatching `B` below T.
    - The overhead budget of item 12, as replaced, holds.

#### C12. Corrections found while folding the corrigendum into the domain model (2026-09-24)

These are specification corrections within ratified decisions, so the
corrigendum keeps its ACCEPTED status. C12.4 also reports a **new defect** in
the shipped code, found while measuring C12.1, and a correction to this
corrigendum's own C2 evidence.

##### C12.1 `min_value` is computed over the arms the fit designs (Open Question 37)

**Correction.** C2's "both arms' design" becomes **"every arm the fit
designs" (C3)**:
- `"lower"` designs the lower arm only;
- `"upper"` designs the upper arm only;
- `"two_sided"` designs both arms at f ≥ 1, and the lower arm only at f = 0,
  because 19.2 turns it into `"lower"`.

**Measured** (`k4_min_value.py`, the exact finder of C12.4, bisection on
`log(M − 1)`, nothing from `drift_caliper`). Each cell gives M_min − 1:

```
baseline          "lower"       "upper"       "two_sided"
m=200    f=20     1.8210e-08    1.6616e-08    1.8228e-08
m=100    f=60     3.5337e-09    3.5423e-09    7.3520e-09
m=1000   f=5      2.2723e-08    3.1459e-08    2.3211e-08
m=300000 f=1      3.6177e-08    3.9954e-08    3.7746e-08
m=1000   f=0      2.2956e-08    F15           2.2956e-08 (→ "lower")
m=300000 f=0      3.3664e-08    F15           3.3664e-08 (→ "lower")
```

- **Every value round-trips.** The design is constructible at it, and not at
  the next float below it.
- **`min_value` differs by direction on the same baseline.**
- **The two-sided value is its own computation, not the larger of the two
  per-arm values.** At m=100 f=60 it is 7.35e-9, against 3.53e-9 and 3.54e-9.
- **At f = 0, a two-sided request's `min_value` equals `"lower"`'s exactly**,
  because it designs the same single arm.

**Constructibility is not monotone just above 1, so C2's "smallest M" needs a
precise meaning.** `k5_monotone.py` swept a dense 4,000-point log grid of M − 1
from 10⁻⁹ to 0.999·(M_max − 1), per baseline and per arm set, with the exact
finder. The findings:
- Non-constructible multiples lie **above** the first constructible one.
- **All of them fall below M − 1 = 5.41×10⁻⁸** (worst: m=300,000 f=1).
- **None falls anywhere else**, up to 0.999·M_max.

A bisection therefore returns *a* boundary inside that band. A caller's M
above it could still be refused.

**Definition, corrected.**
- **F16 fires exactly when** M ≤ 1, **or** the designed arms are not
  constructible at the M the caller passed. This is checked directly, not
  inferred from a threshold.
- **`min_value` is the nearest constructible multiple at or above the one
  requested.** It is found by the same bisection on `log(M − 1)`, bracketed
  between the requested M (or 1, when M ≤ 1) and a constructible anchor
  (M = 2, or halfway to F11's `max_detect_rate_multiple` when that is below 2;
  the anchor is itself verified).
  - It round-trips by construction.
  - Taking it changes the engineer's request by the least amount the
    arithmetic allows.
- **Unchanged:** `min_inclusive=True`. If no anchor is constructible, F16
  raises with `reason="no_valid_multiple"` and no `min_value`, as C2 already
  specifies.
- **The ratified intent of C-Q1's option (A)** (computed per fit,
  round-tripping, no invented constant) is kept. What changes is that the key
  no longer claims every larger M works, because that claim is false inside
  the band.

##### C12.2 C6's `provided_type` rule covers only the `require_exact_str` family (Open Question 38)

**Correction.** C6's "applies to every row" is wrong. The rule, *a type
failure reports `provided_type`*, applies **only** to these rows:
- **F8's not-a-`str` path, and M3.** Both use `require_exact_str` (BIN-143).
- **M2 and C4's extension.** Both are new `Monitor` lattice guards, written in
  the same style.

**F1, F4 and F6 keep `provided`, carrying the value.**
- They are type failures, but they use the **shared** guards `require_type`
  and `require_real_number`.
- Those guards emit `provided` for every chart in the library.
- The BIN-121 exception-contract registry already audits them.
- This ticket does not change shared-guard behaviour.

The registry test (Decision 17, C6) asserts `provided_type` on the
`require_exact_str` rows and `provided` on F1/F4/F6.

**Follow-up, recommended and not done here.** The hazard that motivated
BIN-143 applies equally to the shared guards: a hostile object's `repr` can
raise inside the error path, and `provided` holds the object itself. Whether
`require_type` and `require_real_number` should move to `provided_type`
library-wide belongs in a ticket of its own. It would change every chart's
`context`.

##### C12.3 Stale `lattice_upper` lines

Visible "⚠️ corrected by the corrigendum (C3)" pointers are now beside:
- 19.2's f = 0 bullet;
- 19.5's shape bullet;
- Decision 14's field declaration;
- the Amendment 2 summary-table row.

Each says `lattice_X` is `None` **exactly when arm X is not checked**, for any
f and any requested direction.

##### C12.4 🚨 New defect found while measuring: the lattice finder's centring guarantee fails at large `detect_rate_multiple`

**What Amendment 1 assumed.** Decision 7's closed-form termination bound
assumed `ε·(p₁ − p₀) < min(r − p₀, p₁ − r)`. That holds if `r` sits near the
middle of `(p₀, p₁)`, which was measured at 0.44–0.54 **at M = 2**.

**At large M it does not hold.** `r` drifts toward one end, measured at
0.14–0.23 of the way along `(p₀, p₁)` for M = 55–1000 on the lower arm. Two
consequences follow:

1. **The shipped scan (`feat` at `5b7e3a1`) returns lattices that violate
   Decision 7's own invariants.**
   - Its range stops at the closed-form bound, and then it returns that bound
     unchecked (the `# pragma: no cover` "unreachable" line).
   - **Measured** (random legal lower-arm designs, M from 1.001 to M_max, m
     from 100 to 300,000): **761 of 4,000 returned a lattice outside the
     centring tolerance.** The worst was m=300,000 f=0 M≈26,556: `r_q = 1/11`
     against `r ≈ 0.022`, with a tolerance of 0.051.
   - **Where it starts** (`k9_threshold.py`, `k8_shipped_finder.py`): the
     upper arm's premise fails above M* ≈ 36–40, and its first observed
     violation is at M ≈ 56–102 (m=100 f=10, m=200 f=20, m=1000 f=5). The
     lower arm's first violation is at M ≈ 55–63 on large, clean baselines
     (m=10,000 f=1; m=300,000 f=1).
   - **No test reached it**, because every test used M ≤ 5. It is the same
     "realistic grid" blind spot as Amendment 1's original defect.
2. **This corrigendum's own C2 finder was wrong in the same region.** Its
   "797 of 797 identical to the scan" check sampled M ≤ 3 only. At large M it
   searched the interval `[r − ε·gap, r + ε·gap]`, which there reaches past
   `p₀`, and returned `N = 2`, which fails verification.

**Correction: the exact, fast finder** (`fast_finder3.py`).
1. Let `J = [r − ε·gap, r + ε·gap] ∩ (p₀, p₁)`, closed at the tolerance ends
   and open at `p₀` and `p₁`.
2. `N_any` is the denominator of the simplest rational in `J`, found by
   continued fractions in exact `Fraction` arithmetic. No smaller `N` has any
   `k/N` in `J`.
3. From `N_any`, walk forward applying Decision 7's ratified test exactly:
   `k = round(r·N)`, strictly inside `(p₀, p₁)`, within `ε·gap`.
4. The walk is bounded by `N_sym`, the simplest denominator in the symmetric
   interval of radius `min(ε·gap, r − p₀, p₁ − r)`. There the nearest
   numerator always passes, so an answer exists in exact arithmetic.
5. If floating point cannot realise one, which happens only in C12.1's band
   near M = 1, the design is non-constructible and F16 fires.

**Measured** (`k7_equivalence.py`): identical to the ratified linear rule on
**6,994 of 6,994** design points. These span both arms, f from 0 to m − 1, M
across (1, M_max), m from 100 to 3,000,000, and **2,642 of them have M > 3**.
The forward walk from `N_any` was at most **1** step over 10,846 designs.

**Decision 7's rule itself is unchanged.** Only the claim that `N ≤
⌈1/(2ε·gap)⌉` always suffices is withdrawn, together with the unchecked
`return max_n`. A ⚠️ pointer is added at C2's evidence line. Amendment 1's
Decision 7 text is left as ratified and corrected here.

**Verification additions (Decision 18, continued).**

25. **C12.4.**
    - A Hypothesis property over the **full** legal M range, both arms,
      f = 0 … m − 1, asserts the finder returns a lattice satisfying both
      Decision 7 invariants.
    - It equals the unbounded linear rule wherever that is feasible.
    - Pinned regressions: m=300,000 f=0 M≈26,556, and m=300,000 f=1 M=55,
      lower arm.
26. **C12.1.**
    - F16 fires iff the designed arms are not constructible at the requested M
      (or M ≤ 1).
    - `min_value` is ≥ the request, round-trips, and differs by direction on
      the table's baselines.
    - At f = 0, a two-sided request's `min_value` equals `"lower"`'s.
27. **C12.2.** The registry asserts `provided` on F1/F4/F6, and
    `provided_type` on the type-failure paths of F8, M2, M3 and C4.

#### Product-owner rulings on the corrigendum (2026-09-24)

- **C-Q1 (C2): ✅ ratified, option (A).** `detect_rate_multiple ≤ 1` is
  refused by F16. The lower bound is computed per fit and round-trips by
  construction. (B), fixed at 1.25, and (C), a fixed margin, are rejected.
- **C-Q2 (C3): ✅ ratified.** An artefact carries only the arms its
  `direction` checks. This reverses 6b's "both arms always reported".
- **C-Q3 (C11): ✅ ratified.** The product owner rejected both the 20-probe
  structural bound and dropping the key. `max_two_sided_target_arl` is the
  equal-split conservative bound `floor(T_ES)`, computed in lattice space,
  with a one-solve guard that falls back to the exact D maximum. Decision 18
  item 12's budget is replaced by C11's measured ≤ 30 s overhead budget.
