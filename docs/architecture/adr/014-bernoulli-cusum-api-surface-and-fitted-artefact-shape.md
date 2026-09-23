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
produce without refitting).

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
`"gicp_markov_chain_harmonic_combination"` rather than
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
