# ADR-013: Guaranteed In-Control Performance supersedes the provisional Bernoulli baseline floor

**Status:** ✅ **ACCEPTED — ratified by the product owner 2026-09-23**
`α = 0.10` is already ratified (2026-09-23), as the outcome of the derivation
in §3. The ADR as a whole — adopting GICP, governing its cost by disclosure
rather than a second floor, and lifting `DegenerateBaselineError` for
`p̂ = 0` — has not been ruled on.
**Date:** 2026-09-23
**Refs:** `BIN-133`, ADR-005, ADR-011, ADR-012 (referenced, not edited)

---

## Context

ADR-012 fixed the Bernoulli CUSUM's design rule — `detect_rate_multiple`, the
derived reference value `r` — but explicitly declined to set the Phase I
baseline-size requirement, on the grounds that a threshold needed the design
rule to exist first.

A `system-architect` retrospective review of ADR-012 (`BIN-133`, 2026-09-16)
then measured that ADR-005's baseline adequacy does **not** transfer to
binary data: at ADR-005's 100-observation floor, 18–32% of Bernoulli
baselines delivered under half their requested `ARL₀`, against the ratified
≤5% appetite. The review's central finding was that **the obvious fix
doesn't work**: the natural rule is stated in the true rate `p₀`, which the
library never observes — only `m` (observations) and `f` (observed
failures) are available at fit time. The one attempt to restate the rule in
those observable terms, bucketing by raw `f`, was shown to be confounded
(it pools baselines with different `p₀` and different resulting chart
designs under one bucket).

Pending that gap closing, the product owner ruled (2026-09-17): ship with a
**provisional, uniform floor** — the largest `m` in the measured grid
(1,500 observations), applied regardless of observed rate, explicitly
marked provisional. Two related questions — whether Bernoulli-chart
primacy should be reopened, and whether the Bernoulli CUSUM should be
two-sided by default — were deliberately **not actioned**, sequenced behind
a commissioned spike: if an alternative chart changed the binary picture,
both questions would look different, so they were not to be decided twice.

That spike (`BIN-133`, 2026-09-17) investigated the g-chart and returned a
**clean negative result**. A g-chart fails the identical test that
disqualified the p-chart — its achievable `ARL₀` set is discrete and, for
most of Caliper's realistic operating range, does not come close to 370 —
and, independently of that, a g-chart estimates the same `p₀` from the same
`m` Bernoulli trials as the CUSUM does; the observed failure count is a
sufficient statistic, so no reparameterisation of the same data can reduce
the estimation-error problem the baseline floor exists to address. The
g-chart does not change the binary picture. This ADR does not reopen
primacy or two-sidedness — see §8.

**What does close the gap is a published method, found after that spike.**

## Decision

### 1. Guaranteed In-Control Performance (GICP), via Clopper–Pearson

> **Heidema et al. (2026)**, *"The Poisson CUSUM Chart for Monitoring Small
> Counts: Addressing the Estimation Uncertainty,"* **Biometrical Journal**,
> open access — PMC13051258.

The paper's method, **Guaranteed In-Control Performance (GICP)**, sets a
chart's control limit from an **upper confidence bound** on the in-control
parameter rather than from its point estimate, constructed so that

```
inf_{λ₀>0}  P[ conditional ARL₀ ≥ target ]  =  1 − α
```

holds at the least favourable true parameter value — not merely on
average. For the Poisson case the paper uses Garwood's exact upper limit;
**the paper states directly, and independently of anything measured on
this ticket, that the construction generalises to "any distribution where
an ordering of parameters implies stochastic dominance," explicitly
naming one-parameter exponential-family distributions, and its own
supplementary material demonstrates a binomial application.** Bernoulli's
exact analogue of Garwood is **Clopper–Pearson**.

**Decision: the Bernoulli CUSUM is designed at `p_U`, the one-sided
Clopper–Pearson upper confidence bound on the baseline's failure rate,
rather than at `p̂ = f/m`.**

```
p_U(f, m, α) = quantile function of Beta(f+1, m−f) at 1−α     (f < m)
p_U(0, m, α) = 1 − α^(1/m)                                     (closed form, f = 0)
```

Every other part of ADR-012's design rule is unchanged: `detect_rate_multiple`
still sets `p₁ = M · p_U`, `r` is still derived from the log-likelihood
ratio at `(p_U, p₁)`, and the reference value is still quantised to a
finite lattice for the exact Markov-chain `ARL₀` solve. **Only the
substitution of `p_U` for `p̂` as the design's "in-control rate" is new.**

**Verified, not merely adopted.** Both the mechanism and a sample of the
measured grid were independently checked (`BIN-133`, 2026-09-17): the
Clopper–Pearson formula against `scipy.stats.beta` and the closed form for
`f=0`; a from-scratch Markov-chain solver — different code, different
RNG — reproduced two of the six original `(p₀, m)` cells, one to within
noise on every figure including `ARL₁` to one decimal place. **One caveat
carried forward from that check, not resolved by it:** the headline
figures are lattice-dependent. At `p₀=0.02, m=100`, `N=50` gives a median
`ARL₀` of 38,299 against `N=100/200/400`'s converged 26,110 — a 47% swing
at the coarsest lattice tested, stable from `N=100` up. Treat any specific
`ARL₀`/`ARL₁` figure in this document as an illustrative, converged
measurement at `N=100`, not a precision constant — exactly the discipline
ADR-012 §3 already applies to plug-in designs.

### 2. This supersedes the provisional uniform floor. ADR-005's `m < 100` floor does not move.

The provisional floor was named provisional for a specific, stated reason:
*"until an observable-conditioned rule exists."* GICP is that rule —
`p_U` is a function of `m` and `f` alone, the two quantities the library
actually holds at fit time. It does not sidestep the implementability gap
the way the uniform floor did (by refusing to depend on the observed rate
at all); it dissolves it, because the design no longer needs to know the
true `p₀`.

It is also the statistically stronger property, not merely the more
convenient one. A floor is a *population-level* control — it makes an
aggregate exceedance rate acceptable across baselines it never inspects
individually, measured once and then trusted. GICP is a *per-baseline*
guarantee, constructed fresh at the moment of fitting from the data
actually in hand. ADR-005's ratified population appetite (≤5% of baselines
under half the target) becomes a **consequence** of GICP holding for every
individual baseline (verified in §3), not a separate statistic that could
silently drift as the mix of `p₀` values in the wild changes.

**Superseded:** the 2026-09-17 provisional uniform floor of 1,500
observations, for binary baselines specifically.

**Not touched:** ADR-005's absolute hard floor — `m < 100` still raises
`InsufficientBaselineError`, for every chart type, binary included. That
guard answers a different question ("is there enough data to trust any
estimate at all") from the one GICP answers ("does this specific chart's
false-alarm rate hold"), and nothing here argues for removing it.

### 3. `α = 0.10`, derived from the ratified appetite — not cited, not defaulted

**`α` is not a statistical constant, and no primary source could settle
it.** It is a risk-appetite parameter — *guarantee the `ARL₀` meets target
with probability `≥ 1−α`* — the same kind of quantity as ADR-005's own
*"at most 5% of baselines may deliver under half the requested `ARL₀`,"*
which that ADR already records as *"a product decision, not a statistical
result."* Inheriting Clopper–Pearson's textbook `α = 0.05` by convention
would have been exactly the kind of unsourced default this project
otherwise refuses to ship.

🚨 **`α` and ADR-005's ratified appetite bound different events, and
conflating them is the obvious future mistake.** `α` bounds
`P(true ARL₀ < target)`. ADR-005's appetite bounds
`P(true ARL₀ < target/2)`. Setting `α = 0.05` *because* the appetite is 5%
is a category error: at `α = 0.05`, the appetite metric — measured
independently — comes out at 0.0–1.0%, nowhere near its own 5% budget.
**The two numbers are allowed to differ, and here they do.**

**So `α` was derived, not chosen, by finding where it lands relative to the
appetite that is already ratified.** `α` sits on a continuum: `α → 1`
collapses `p_U` onto `p̂` and recovers plug-in design (no guarantee);
`α → 0` drives `p_U → 1` and the chart never signals. The decision is
**the largest `α` that still holds ADR-005's ≤5% appetite across the
legal operating range** — the least conservative design that still keeps
the ratified promise.

**Grid:** `p₀ ∈ {0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30} ×
m ∈ {100, 200, 300, 500, 1000}` — 40 cells, 4,000 replications each,
`N=100`, `detect_rate_multiple=2.0`. **Judged on the upper 95% confidence
bound of the measured exceedance rate, not the point estimate** — this
number governs public API behaviour, and a cell that merely *looks*
compliant on a point estimate is not sufficient evidence.

```
alpha    breaching cells    worst cell     worst pt   worst ub    verdict
0.075                  0    (0.02, 200)       1.77%      2.16%    defensible
0.100                  0    (0.10, 100)       2.15%      2.57%    defensible
0.125                  0    (0.03, 100)       4.40%      4.97%    defensible
0.150                  1    (0.03, 100)       4.58%      5.16%    no
0.200                  6    (0.15, 100)       6.00%      6.65%    no
```

Every breaching cell across the grid sits at `m = 100` — small baselines
are where the appetite binds.

**`α = 0.125` is the largest defensible value in this grid, and it was
not chosen.** It clears the 5% bar, but at 4.97% on its own upper bound —
genuinely marginal, close enough that a different simulation seed could
plausibly tip it over. `α = 0.10` clears with real headroom (2.57%), for
a measured, moderate cost in detection power (below). **Ratified
2026-09-23: `α = 0.10`, for the headroom, over
the more aggressive but marginal `α = 0.125`.** Recording the rejected
option and why it was rejected is part of this decision, not incidental
to it — `α = 0.125` remains available to revisit if the detection-power
cost of `0.10` proves material in practice.

**The detection-power cost this buys back, now measured directly for the
ratified `α = 0.10`** (true `ARL₁` at a doubled failure rate, 2,000
replications, `N=100`, `M=2.0`):

```
p0     m      a=0.05    a=0.10   a=0.125    0.05 -> 0.10
0.02   100    1709.6     864.9     725.6           1.98x
0.05   100     404.7     261.3     225.8           1.55x
0.10   100     153.8     111.1      99.8           1.38x
0.20   100      59.5      48.2      44.3           1.23x
0.02   500     250.9     198.9     187.8           1.26x
0.05   500     122.6     103.4      98.9           1.19x
0.10   500      67.3      60.4      58.5           1.11x
```

**`α = 0.10` roughly halves detection time against the earlier arbitrary
`α = 0.05`, and gives up relatively little to the rejected `α = 0.125`** —
at `p₀=0.02, m=100`, `0.10` recovers 1.98× of `0.125`'s 2.36×, and the gap
between them narrows further as `p₀` or `m` grows. **This is the trade
that justifies choosing headroom over the maximum**: most of the
available detection-power recovery, for a design that clears the ratified
appetite with room to spare (2.57%) rather than by 0.03 percentage
points (4.97%).

**One methodological finding worth recording on its own, because it
independently corroborates the whole Bernoulli transfer.** The guarantee's
own breach rate was checked against the Clopper–Pearson undercoverage rate
directly:

```
α      worst P(true ARL₀ < target)    P(p_U < p₀) at that cell
0.05                       4.95%                        4.95%
0.15                      14.65%                       14.65%
```

Equal to two decimal places. **The guarantee fails exactly when, and only
when, the confidence bound itself undercovers** — precisely what the
theory predicts, and stronger evidence the mechanism transfers correctly
to Bernoulli than the pass/fail verdict alone would have been.

### 4. Governing the over-conservatism: a disclosed detection-power figure, not a second floor

**The false-alarm problem does not disappear under GICP — it changes
type.** At `p₀=0.02, m=100`, the *true* `ARL₀` (evaluated at the real,
simulated rate) has a measured median of 26,110 against a request of 370,
and the *true* `ARL₁` at a doubled rate has a measured median of 1,710
observations (at the earlier `α=0.05`; smaller under the ratified `0.10`,
per §3). The chart is safe and, in practice, close to inert.

**Recommendation: disclose, do not add a second floor.** A hard
detection-power floor would need its own product-owner-ratified appetite
(a new business judgement, the same shape as ADR-005's, not one this ADR
can supply), and it is not a property of `m` alone — the same baseline is
"fine" at `detect_rate_multiple=5` and "hopeless" at `1.25`, so any floor
computed after the engineer's own choice of sensitivity is functionally
already a disclosure, not a refusal. ADR-011 already settled this shape of
argument once — *informed choice over refusal* — for a low-but-sourced
`target_arl`. This is the same argument applied to a low-but-guaranteed
`m`.

**What the disclosed figure actually is, precisely, because "report
power" is a direction and not a definition:**

The reported figures need to answer a question the engineer can act on,
using only what Caliper actually knows at fit time — which is `m`, `f`
(hence `p̂ = f/m`), `p_U`, and the chosen design (`r`, `H`). **The
simulation study's "true `ARL₀`/`ARL₁`" figures above cannot be computed
by the library itself** — they required knowing the ground-truth `p₀`,
which only a Monte Carlo study has access to. This matters, because it
means `achieved_arl` computed the honest way — at the chart's own design
point, `p_U` — will **already read close to the requested target by
construction** (that is what the design step solves for). It will not,
on its own, show anything resembling "26,110". **The disclosure gap is
not that `achieved_arl` looks like good news; it is that nothing today
tells the engineer what `p_U`'s conservatism costs them in practice.**

**Confirmed by direct measurement, not only by the argument above.**
Median `achieved_arl` at the design point, `α = 0.10`:

```
p₀=0.02, m=100   median achieved_arl at p_U = 375.9   (request 370)
p₀=0.20, m=100   median achieved_arl at p_U = 387.9   (request 370)
```

Both read within a few percent of the request, exactly as designed, and
give no hint of the underlying rate's true weakness. **This is a missing
number, not a misleading one**: `achieved_arl` is not lying, it is
honestly answering a narrower question than the one the engineer needs
answered.

**Decision: add a second reported figure to the fitted artefact,
`expected_detection_arl`, defined as the exact `ARL₁` — computed by the
same Markov-chain machinery that already produces `achieved_arl` — of the
constructed chart (`r`, `H`, fixed by the design step), evaluated at**

```
p = p̂ × detect_rate_multiple          (the ordinary case)
p = p_U × detect_rate_multiple        (only when f = 0, since p̂ = 0 makes
                                        "a rise from zero" undefined as a
                                        target rate — falls back to the
                                        one positive rate already computed)
```

**Why `p̂`, not `p_U`, for the ordinary case.** `p_U` is *deliberately*
pessimistic — using it again on the detection side would produce an even
more extreme, needlessly alarming number, doubly conservative in a way
that answers "what is the worst defensible case" rather than "what should
I actually expect." `p̂` is the best single-point description of the
baseline actually observed, already computed, and reusing it costs no new
statistical machinery — only a second call to the exact-`ARL` solver
already built for `achieved_arl`, at a different input rate. This is a
genuinely different question from `achieved_arl`'s: *"is my false-alarm
promise safe"* (answered conservatively, at `p_U`) versus *"how fast will
this plausibly catch a real doubling"* (answered at the best estimate,
`p̂`) — and an engineer needs both to read the artefact correctly.

**Naming and exact field shape are not ratified by this ADR** — `expected_detection_arl`
is this document's proposal, not a settled API surface; `system-architect`'s
implementation pass may reasonably rename it, provided the *definition*
(evaluated at `p̂ × M`, falling back to `p_U × M` at `f=0`, via the shared
`ARL` machinery) survives review unchanged.

**Considered and deliberately not adopted here: a symmetric, conservative
companion figure** — an `ARL₁` evaluated at a *lower* confidence bound on
`p₀` (mirroring `p_U`'s role on the false-alarm side), giving a genuine
worst-case detection number rather than an expected one. This is a
principled idea — same Clopper–Pearson machinery, same `α`, symmetric
treatment of the two failure directions — but it is a new figure that
would need its own measurement and verification before shipping, exactly
like `α` itself did. Recorded as a real option for a future amendment, not
adopted now. See §8.

**Routing.** `expected_detection_arl` is delivered through
**`FittingAdvisory`**, the non-raising disclosure vehicle ADR-011 specified
for the fitting side. This is a second caller for an existing type, not a
reason to invent a new shape.

> 🚨 **Corrected 2026-09-23, before implementation.** An earlier version of
> this paragraph routed the figure through **`DataQualityConcern`** and
> described that mechanism as *"unbuilt"*. **Both halves were wrong**, and
> the correction is recorded rather than silently applied because the error
> is instructive.
>
> **The vehicle is built and wired.**
> `src/drift_caliper/baseline/domain/fitting_advisory.py` defines
> `FittingAdvisory` (`kind`, `description`, `boundary: float`); all three
> fitted artefacts already carry `advisories: tuple[FittingAdvisory, ...]`,
> and the `FittedControlLimits` protocol exposes it. One producer is live —
> `parameter_guards.py` emits `target_arl_below_verified_range` for
> ADR-011's flagged tier.
>
> ⚠️ **And it named the wrong one of two types that exist precisely to be
> distinguished.** `FittingAdvisory` is the fitting-side carrier;
> `DataQualityConcern` (`kind`, `description`) belongs to
> `SufficiencyResult`. `fitting_advisory.py`'s own module docstring records
> why: a data-quality-named type *"would misdescribe both of this type's
> intended uses."* Routing a fitting-time disclosure through the
> sufficiency-time type would have undone a distinction the codebase makes
> deliberately.
>
> **What remains genuinely unimplemented is ADR-005's middle tier** — an
> advisory from `check_sufficiency()` for a baseline above the hard floor
> but below `adequate(target_arl)`. `fitting_advisory.py` records that as
> its second intended caller and notes `adequate()` itself is still
> unratified. That is one unbuilt caller, not a missing mechanism.
>
> ⚠️ **The error came from reading the decision record instead of the
> source.** This project's own note — *"`CLAUDE.md` is a record of
> decisions, not of what shipped"* — applies to ADRs with equal force. A
> claim that something is unbuilt is a claim about the repository, and
> claims about the repository get checked against it.

⚠️ **One API question is left to implementation, not settled here.**
`FittingAdvisory.boundary` is already a `float` and could carry the figure,
or `expected_detection_arl` could be a first-class field on the fitted
artefact as this section's definition implies. Those are different public
surfaces. The *definition* above — the exact `ARL₁` of the constructed
chart, evaluated at `p̂ × detect_rate_multiple`, falling back to
`p_U × M` at `f = 0` — is what must survive either choice.

### 5. `p̂ = 0`: `DegenerateBaselineError` is lifted, contingent on §4 shipping in the same release

ADR-012 §6 raises `DegenerateBaselineError` when `p̂ = 0`, reasoning that
*"the likelihood ratio is undefined and there is no rate to detect a
multiple of."* **That reasoning no longer holds once the design uses
`p_U` in place of `p̂`.** `p_U(0, m, α)` is well-defined and strictly
positive for any `m ≥ 1` and any `α ∈ (0, 1)` — the closed form,
`1 − α^(1/m)`, was independently checked against `scipy.stats.beta` and
matches to five decimal places (`p_U(f=0, m=100, α=0.05) = 0.02951`).
Heidema et al. state this design property directly for the Poisson case
and it carries over unchanged: the procedure "does not suffer from
calibration issues whenever all Phase I observations are zero."

**Decision: `p̂ = 0` no longer raises `DegenerateBaselineError`. The chart
is designed at `p_U(0, m, α)`, exactly as any other `f`.**

**This is coherent only together with §4, not on its own.** `f=0` is the
*most* extreme instance of the over-conservatism problem this ADR exists
to manage — a design calibrated against a `p_U` of roughly 3% (at
`m=100`) when the true rate could be far lower still produces a
weaker chart than any of the `p₀=0.02` measurements above. Lifting the
error without also shipping `expected_detection_arl` would hand back a
"successful" fit that is practically inert, with nothing telling the
engineer so — a worse outcome than today's honest refusal, not a better
one. **Do not ship this row of §5 ahead of §4.**

**`p̂ = 1` is unaffected, and this is worth stating rather than leaving
implicit.** `p_U ≥ p̂` always; pushing `p̂` toward `p_U` at `p̂` near 1
makes the design-point constraint (`p₁ = M · p_U < 1`) *harder* to
satisfy, not easier. GICP cannot rescue this case — structurally, not by
oversight. ADR-012 §6 treated `p̂=0` and `p̂=1` as a matched, symmetric
pair, each needing its own `DegenerateBaselineError` branch. Under GICP
they stop being symmetric: `p̂=0` becomes an ordinary (if extreme) design;
`p̂=1`, or more precisely any baseline whose `p_U` is too high for the
chosen `detect_rate_multiple`, falls into the **already-existing**
`p₁ ≥ 1 → InvalidParameterError` path. No bespoke all-failures branch is
needed — one special case removed, not added.

### 6. The `p₀ → 0.5` region: the regret figure was incomplete, and GICP reaches the design ceiling before plug-in does

ADR-012's amendment already flagged its own regret study as covering only
`p₀ ≤ 0.20` while `detect_rate_multiple = 2.0` stays legal to `p₀ < 0.5`,
and named extending it as outstanding work. That work is now done, on
both halves of the question this ADR needs answered.

**6a. `detect_rate_multiple = 2.0` survives; the published regret figure
understated its cost.** Calibrated at the exact `p₀` (not `p_U` — this
measures the chart's own behaviour, independent of GICP), worst-case
regret for `M = 2.0` across the previously-untested region:

```
p0      0.25   0.30   0.35   0.40   0.45
regret  1.18   1.25   1.28   1.31   1.49
```

🚨 **ADR-012 §1 states worst-case regret as 1.17. That figure holds only
for `p₀ ≤ 0.20`; across the full legal domain it rises to 1.49.** The
decision itself is unaffected — `2.0` remains the largest multiple legal
everywhere and still performs best at its own design point — but the
originally published number described a narrower range than its own text
claimed to cover. **This ADR discharges that outstanding item directly in
ADR-012's amendment** (the one narrow edit made to that document
alongside this one — see the note at the end of this section); nothing
about `detect_rate_multiple`'s ratified value changes here.

The underlying mechanism is confirmed but is a **gradual drift, not the
cliff** the derivation alone suggested: `r`'s position between `p₀` and
`p₁` stays near 0.49 out to `p₀ = 0.35`, then moves to 0.533 at `0.40` and
0.580 at `0.45` — degrading steadily rather than collapsing at a point.

⚠️ **A lattice artefact, not a chart property, worth recording so nobody
re-derives it as a finding:** at `p₀=0.40, M=1.5`, the derived `r` lands
on exactly `0.5000` at `N=100` (`k=50`), and the achieved `ARL₀`
overshoots to 516.7 against a request of 370 — the same non-monotone
quantisation behaviour ADR-012 §3 already documents, showing up at a
specific coordinate rather than as a new phenomenon.

**6b. 🚨 GICP hits the design ceiling before plug-in design does, and this
ADR's own `p̂=0` relief has a mirror-image cost at the high end.** A
design requires `p₁ = M · p_U < 1`, hence `p_U < 1/M`. Since `p_U > p̂`
always, this bites **earlier** under GICP than under plug-in design —
measured at `α = 0.10, M = 2.0`, 3,000 draws per cell:

```
p0     m      % undesignable GICP    % undesignable plug-in
0.35   100                    3.8%                      0.1%
0.40   100                   22.5%                      2.7%
0.40   200                    6.2%                      0.2%
0.45   100                   62.0%                     19.6%
0.45   200                   47.2%                      9.1%
0.45   500                   16.5%                      1.2%
```

**At a 45% observed failure rate with 100 observations, GICP refuses to
design a chart 62% of the time where plug-in design would have
succeeded.**

**This is a real asymmetry, and it belongs in this decision stated
plainly rather than left for someone to notice later.** §5 lifts a
refusal at the low end — `p̂ = 0` becomes designable. This section
documents one this same ADR introduces at the high end — a `p̂` that
plug-in design would have accepted now more often gets refused. Neither
is a defect; both are the correct, honest behaviour of a confidence-bound
design. But shipping the low-end relief without naming the high-end cost
would misrepresent what this ADR does to the shape of Caliper's refusal
surface.

**Decision: the largest admissible `detect_rate_multiple` reported in the
`InvalidParameterError` raised when `p₁ ≥ 1` must be computed from `p_U`,
not `p̂`.** ADR-012 §6 already requires this error to report the largest
multiple the baseline admits, so that value round-trips as an accepted
input (`BIN-122`'s rule). Under GICP, the value that actually gets
accepted on resupply is bounded by `p_U`, not `p̂` — reporting a bound
computed from `p̂` would name a multiple GICP will then refuse, breaking
that round-trip guarantee at exactly the boundary this section measures.
**This is not a new judgement call; it is what `BIN-122`'s already-ratified
contract requires once `p_U` is the design's operative rate.**
Implementers must compute the reported maximum admissible multiple from
`p_U`, not `p̂`.

**Considered and not adopted here: a `FittingAdvisory` for
high-rate baselines that remain designable but sit close to this
ceiling.** There is a plausible case for one — a baseline near the
`p₀ → 0.5` region gets a *valid* chart whose regret is measurably worse
(6a) and whose design sits closer to the point where the next observation
could tip it into outright refusal, with nothing today disclosing either.
**Judged to be scope creep for this ADR, not a decision to make here**:
unlike the round-trip fix above, it is not required by an existing
contract, and unlike `expected_detection_arl` (§4), no threshold for
"close enough to the ceiling to warrant a word" has been measured. Adding
one now would mean inventing a number this ADR's own discipline forbids.
Recorded as a candidate for a future amendment — a fourth caller for the
same still-unbuilt advisory vehicle, not a reason to build a different
one.

**Discharging ADR-012's outstanding item.** The measurement in 6a
completes the extension ADR-012's amendment §6 named as outstanding work.
That document's amendment §6 is updated accordingly, in the one narrow
edit this ADR makes outside itself — the regret figure and its scope are
corrected there; no other line of ADR-012 changes, and no decision in it
is reversed.

### 7. Verification bar for any number that gates public behaviour

🚨 **Twice on this ticket, a study produced a confident, wrong answer that
only a re-run at higher rigour caught — and neither was visible by
inspection.** First: a near-singular linear solve returned a
plausible-looking negative `ARL` (`BIN-140`) rather than failing, and
separately corrupted an early Phase I baseline grid, producing a 63.4%
exceedance cell sitting between neighbours reading 11.0% and 2.3%.
Second, on this very derivation: an 800-replication first pass at the
40-cell `α` grid flagged the GICP guarantee itself as breached at **every**
`α` tested, including 0.05 — a false alarm about a false-alarm guarantee,
resolved only by re-running at 4,000 replications, where it held, and
where the breach mechanism was confirmed to equal the Clopper–Pearson
undercoverage rate to the decimal (§3). **Both were the same shape:
confident, plausible, and wrong, at a resolution too coarse to have caught
itself.**

**Standing requirement, not a footnote: any number in this ADR family that
gates public behaviour — a default, a floor, an `α` — must, before it is
treated as ratified:**

1. **Carry a postcondition on every numerical solve it depends on**
   (finite, positive, within a sane range) — the general form of the
   `BIN-140` lesson, applied to every `ARL` computation, not only the one
   that first surfaced it.
2. **Be checked by at least two independent implementations or methods**
   where the check is affordable — as was done for `r`'s derivation, the
   CUSUM oracle cross-check, and the original 6-cell GICP-vs-plug-in grid.
   Reused code checked twice is not this; a second, independently written
   path is.
3. **Be judged on a confidence bound of the measured quantity, not its
   point estimate**, whenever that quantity is itself a probability being
   checked against a ratified threshold — as §3 does, and as the earlier
   provisional-floor grid (800 reps, ±0.8pp) did not have the resolution
   to do reliably.
4. **Run at enough replications that the decision-relevant confidence
   interval is comfortably narrower than the margin to the threshold it
   is being judged against** — 800 replications produced a false breach
   at every `α` tested; 4,000 resolved it. There is no fixed number that
   is always enough; the requirement is that the study state its own
   margin and show the interval is tight relative to it, not merely
   report a point estimate that happens to clear the bar.
5. **State its sensitivity to fixed nuisance choices explicitly** — the
   lattice denominator `N` and `detect_rate_multiple`, in this case —
   rather than silently. §1 records the `N` sensitivity found; `M`
   sensitivity for the `α` grid is not yet checked (§8).
6. **Be posted to the ticket in full** — grid, code, replication count,
   confidence intervals — not summarised. A number that only exists as a
   chat summary is not yet a number this project can cite; this happened
   once already on this ticket (the original four-band baseline table)
   and was corrected by posting the full grid.

## Consequences

**Positive.** The implementability gap the ADR-012 review found — a rule
stated in the unobservable `p₀` — is closed, not worked around. The
resulting guarantee is per-baseline and verified, not a population
statistic taken on faith. `p̂ = 0` becomes a normal, if extreme, case
rather than a dead end. The design directly reuses ADR-012's existing
machinery (`r` derivation, the exact Markov-chain solve) with one input
substituted; no new numerical method was introduced. `BIN-122`'s
round-trip contract (§6b) is preserved by an explicit decision here
rather than surfacing later as a defect once GICP made `p̂`'s bound the
wrong one to report.

**Negative.** A new public concept, `α`, joins `detect_rate_multiple` on
the design surface, and its role — a guarantee's own risk appetite,
distinct from ADR-005's baseline-adequacy appetite even though both are
"5%-ish numbers" — is a real education cost, exactly the trap §3 names.
Detection power at small `m` and low `p₀` is, and remains, genuinely
weak; disclosure does not make the chart faster, only honest about how
slow it is. `expected_detection_arl` is a new field every consumer of a
fitted Bernoulli CUSUM artefact must learn to read, on top of
`requested_arl`/`achieved_arl`. **A refusal mode is introduced at the
high end of `p₀` that is strictly more frequent than plug-in design's
own** (§6b) — up to 62% of `m=100` baselines at `p₀=0.45`, against 19.6%
under plug-in — the mirror image of §5's relief at `p̂=0`, and it must be
read together with that relief, not separately.

**Neutral.** `FittingAdvisory` (ADR-011) is **already built and wired** —
all three fitted artefacts carry `advisories`, and `parameter_guards.py`
already produces one. This ADR adds a second producer to an existing
vehicle, not an item to a backlog. ⚠️ An earlier draft of this line said the
mechanism *"remains unbuilt"*; see §4's correction. What is genuinely
unbuilt is ADR-005's middle-tier caller, which is a separate matter.

**Reversibility.** Moderate. `α = 0.10` can be revised without a breaking
change to the design rule (it is a default, not part of the public
signature commitment the way `detect_rate_multiple` is) — but revising it
means re-running §3's grid, not adjusting a constant in isolation.
Lifting `DegenerateBaselineError` for `p̂=0` is a breaking change in the
narrow sense that code catching that exception at `f=0` will stop seeing
it; low practical cost, since nothing has shipped against the current
behaviour yet. Adding `expected_detection_arl` is purely additive.

## Alternatives rejected

**Keep the plug-in design and the provisional uniform floor.** Rejected —
this is precisely the state GICP improves on; the floor was explicitly
named provisional for the reason GICP now resolves, and plug-in's
measured 18–32% exceedance at `m=100` is what motivated this whole line
of work.

**`α = 0.125`.** Rejected as too marginal to ratify as public API
behaviour — 4.97% against a 5% bar, on a single 4,000-replication study.
Not rejected on the merits; §3's measured detection payoff shows `0.10`
already recovers most of `0.125`'s advantage, which is what makes `0.125`
revisit-able rather than regretted — if `0.10`'s remaining cost proves
material in practice, the more aggressive value is still defensible and
already measured.

**A hard detection-power floor**, mirroring ADR-005's shape but for
`ARL₁`. Rejected: it needs its own ratified appetite this ADR has not
established, it is not a function of `m` alone (it depends on the
engineer's own `detect_rate_multiple`), and a floor computed after the
engineer's choice of sensitivity is functionally indistinguishable from
disclosure — so disclosure is the honest version of the same idea, not a
weaker substitute for it.

**A "knowledge-based" variant** (Heidema et al.'s own extension, using a
heuristic estimator when all Phase I observations are zero to partially
recover power). Rejected for R1: it requires the practitioner to supply
external knowledge of a minimum plausible baseline rate, which Caliper
has no principled source for across arbitrary engineers' rubrics — unlike
the chikungunya case study the paper demonstrates it on, Caliper has no
privileged domain knowledge about any given baseline. Worth revisiting
only if a future release adds an explicit, opt-in way for an engineer to
supply such a prior.

**A `FittingAdvisory` for high-rate baselines near the
`p₀ → 0.5` ceiling** (§6b). A plausible idea — the baseline is
designable but sits closer to outright refusal and carries measurably
worse regret — rejected for this ADR as scope creep: no threshold for
"close enough to warrant a word" has been measured, unlike the round-trip
fix in the same section, which is a contract requirement rather than a
new judgement call. A candidate for a future amendment.

## 🚨 What this deliberately does not decide

- **The lattice denominator `N`.** ADR-012 already deferred this; it
  remains deferred. Every figure in this ADR uses `N=100`, and §1 records
  that this specific measurement (26,110 at `p₀=0.02, m=100`) is stable
  from `N=100` upward but not at `N=50` — a fact about this measurement,
  not a resolution of the denominator question.
- **`detect_rate_multiple` sensitivity for the `α` derivation and for
  the undesignability measurement.** §3's 40-cell grid, and §6b's
  designability grid, both fix `detect_rate_multiple = 2.0`. The
  guarantee in §3 is expected to be a structural property independent of
  the chosen multiple; §6b's undesignable-rate figures are specific to
  `M=2.0` by construction (a larger `M` would push the ceiling lower and
  the refusal rate higher; a smaller `M` the reverse). Neither has been
  checked at another multiple.
- **A threshold for a high-rate `FittingAdvisory`** (§6b) —
  considered and rejected as scope creep for this ADR, not because the
  idea is wrong, but because no such threshold has been measured.
- **A conservative, lower-confidence-bound companion to
  `expected_detection_arl`** — considered in §4, not adopted. A real
  candidate for a future amendment, needing its own measurement before it
  could ship.
- **How a binary score is declared** on `Baseline`/`ScoringResult` —
  ADR-012's own open item, interacting with `BIN-61`. Untouched here.
- **Chart primacy, and whether the Bernoulli CUSUM should be two-sided by
  default.** Both were deliberately left unactioned by the product owner
  pending the g-chart spike, which has since closed with a negative
  result and therefore does not change either picture — but neither
  question has been re-raised or re-ruled on since. This ADR is scoped to
  calibration; it does not decide either, and leaves them exactly where
  the 2026-09-17 ruling put them: open, now unblocked, not yet acted on.
- **The exact field name `expected_detection_arl`.** The *definition* in
  §4 is the decision; the name is this document's proposal, open to
  revision at implementation.
