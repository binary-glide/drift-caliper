# ADR-012: Bernoulli chart design — the shift lever, the reference value, and what is exact

**Status:** ✅ **ACCEPTED — ratified by the product owner 2026-09-16**
**Date:** 2026-09-16
**Refs:** BIN-133, BIN-132, ADR-001, ADR-004, ADR-005, ADR-011

---

## Context

ADR-001's 2026-09-13 amendment rejected the p-chart and named **Bernoulli EWMA
and Bernoulli CUSUM** as the charts that serve binary pass/fail rubrics. It
deliberately left three things open: the API surface, which chart leads, and
where the in-control rate `p̂` comes from.

Work on BIN-133 established that the third question cannot be answered until a
fourth one is: **how the chart's design parameters are chosen.** Measuring how
much baseline data a binary chart needs requires designing a chart from each
simulated baseline, and every such measurement is a property of the design rule
as much as of the data. A rule invented for the measurement produces thresholds
that describe the invention.

This ADR decides the design rule so that the baseline requirement can then be
measured against something fixed.

## Decision

### 1. The shift is expressed as a failure-rate multiple, not a sigma multiple

`fit_cusum` takes `reference_value` (`k`), conventionally half the standardised
shift the chart is tuned to detect: `Δ = 2k` in units of σ. **That lever does
not transfer to a Bernoulli process, and the reason is structural rather than
stylistic.**

For a continuous chart the process level and its dispersion are independent
parameters — a mean can shift while σ stays put, so "detect a 1σ shift" is a
statement the engineer can make without knowing the mean. **A Bernoulli process
has one parameter.** Its variance is `p(1 − p)`, determined entirely by the
rate, so a shift in the rate *is* a shift in the dispersion. Expressing the
design point in σ would restate the rate change in units derived from the rate
change.

**Decision:** the binary charts take the shift as a multiple of the in-control
failure rate.

```
fit_bernoulli_cusum(baseline, target_arl=370, detect_rate_multiple=2.0)
```

`detect_rate_multiple = 2.0` — a doubling of the failure rate — is the default,
and it is **measured, not conventional.**

The criterion is ADR-001's own test for a default: *near-optimal across a range
of shift sizes, which is the right default when the engineer does not know what
degradation they face.* Applied here: calibrate a chart at design multiple `M`
to ARL₀ = 370, then measure ARL₁ when the **true** degradation is some other
multiple `A`. Regret is that ARL₁ divided by the best any design achieves at
that `A` — how much slower to detect than a chart tuned exactly right.

Worst-case regret over `A ∈ {1.25, 1.5, 2, 3, 5, 8}` and
`p₀ ∈ {0.02, 0.05, 0.10, 0.20}`:

| design M | worst-case regret | defined for |
|---|---|---|
| 1.25 | 1.34 | all p₀ |
| 1.50 | 1.30 | all p₀ |
| **2.00** | **1.17** | **all p₀** |
| 3.00 | 1.07 | only p₀ < 0.333 |
| 5.00 | 1.15 | only p₀ < 0.20 |

🚨 **The two multiples that beat 2.0 are not candidates, and the reason is not
their performance.** The design point `p₁ = M × p₀` must remain a probability,
so `M` is capped at `1/p₀`: a default of 3 is undefined for any baseline whose
failure rate exceeds a third, and 5 above a fifth. Their apparent advantage is
measured only on the subset of rates where they exist at all.

Regret falls monotonically with `M` up to that ceiling — 1.34, 1.30, 1.17 —
so **2.0 is the largest multiple defined across the whole legal domain**, which
makes it the best available default rather than a conventional one. A default
that raises for ordinary inputs is not a default.

⚠️ **17% is the worst case, not the typical one.** Across the grid the regret
is 1.00–1.06 for degradations between 1.25× and 3×, and only reaches 1.17 for
an 8× spike — where every design detects in single-digit observations anyway, so
the relative penalty is on an already-small number.

The engineer overrides it when they know the degradation they face; the ADR-001
argument applies precisely when they do not.

### 2. The reference value is derived, not chosen

Given the in-control rate `p₀` and the design point `p₁ = p₀ × detect_rate_multiple`,
the reference value `r` is the **Bernoulli log-likelihood-ratio increment**,
rescaled so the statistic accumulates `X − r`.

The derivation, in full, because this project does not ship constants from
recall:

For a test of `H₀: p = p₀` against `H₁: p = p₁`, one observation `X ∈ {0, 1}`
contributes a log-likelihood ratio

```
L(X) = X·ln(p₁/p₀) + (1 − X)·ln((1 − p₁)/(1 − p₀))
```

Collecting the terms in `X`:

```
L(X) = X·ln( p₁(1 − p₀) / (p₀(1 − p₁)) ) + ln((1 − p₁)/(1 − p₀))
```

Write `B = ln( p₁(1 − p₀) / (p₀(1 − p₁)) )`, which is strictly positive for
`p₁ > p₀`. Dividing by `B` leaves a statistic proportional to `X − r` with

```
        ln( (1 − p₀) / (1 − p₁) )
r  =  ─────────────────────────────
      ln( p₁(1 − p₀) / (p₀(1 − p₁)) )
```

so the CUSUM accumulating `max(0, Bₜ₋₁ + Xₜ − r)` is the sequential likelihood
ratio test, rescaled. **Verified numerically to machine precision** against
`L(X)/B` at both `X = 0` and `X = 1`, across `p₀ ∈ [0.01, 0.35]`.

`p₀ < r < p₁` holds throughout, which is the expected property — the reference
value sits between the rate the chart treats as acceptable and the rate it is
tuned to detect.

### 3. `r` is quantised, and the achieved ARL₀ is reported rather than assumed

The exact ARL computation in §4 requires `r` to be rational: the statistic then
lives on an integer lattice and the Markov chain is finite. `r` as derived is
irrational in general, so it is rounded to a lattice.

⚠️ **Refining that lattice does not monotonically improve calibration**, which
is counter-intuitive and worth stating. Measured at `target_arl = 370` with a
doubling design point, quantising to denominator `N` and taking the smallest
threshold clearing the target:

| p₀ | N=20 | N=50 | N=100 | N=200 | N=500 |
|---|---|---|---|---|---|
| 0.02 | 2.58% | 1.21% | 0.26% | 0.26% | 0.35% |
| 0.05 | 1.85% | 0.39% | 1.47% | 1.47% | 1.22% |
| 0.10 | 3.03% | 1.58% | 3.03% | 1.44% | 2.25% |
| 0.20 | 5.06% | 5.06% | 0.05% | 1.93% | 0.90% |

Refining `N` changes **two** things at once: the threshold granularity, which it
improves, and the quantised `r` itself — which is a *different chart*, whose
smallest clearing threshold overshoots by a different amount. The residual is
lattice granularity, not approximation error.

**Decision: do not chase the target by refining the lattice.** Compute the ARL₀
of the chart actually constructed, exactly, and report it. Caliper already
distinguishes `requested_arl` from `achieved_arl` on every fitted artefact
(ADR-004); this is that mechanism doing its job, and the engineer sees the
chart they have rather than the one they asked for.

### 4. 🚨 The ARL is exact for the CUSUM and is **not** exact for the EWMA

ADR-001's amendment states:

> *"A two-outcome process gives a finite reachable lattice, so the Markov chain
> is solved rather than discretised."*

**That is true of the Bernoulli CUSUM and false of the Bernoulli EWMA.**
Counted directly, as the size of each statistic's reachable support after `t`
observations:

| t | CUSUM support | EWMA support |
|---|---|---|
| 8 | 16 | 256 |
| 12 | 24 | 4 096 |
| 16 | 32 | 65 536 |
| 20 | 40 | **1 048 576** = 2²⁰ |

The CUSUM's `max(0, · )` floor and its fixed increments confine it to a lattice
bounded by `H/r`. The EWMA's `zₜ = λXₜ + (1 − λ)zₜ₋₁` has **no floor and no
recurrence**: distinct observation histories give distinct states, and the
support doubles at every step with no collapse.

**Consequence: the Bernoulli EWMA needs a discretisation scheme and its own
accuracy argument, exactly as the continuous EWMA does.** It inherits none of
the exactness the amendment attributes to binary charts.

### 5. The Bernoulli CUSUM ships first

⚠️ **This reverses BIN-133's scope item 1**, which specifies *"Bernoulli EWMA
first, as primary"*, mirroring ADR-001's choice for continuous scores.

That ordering was reasonable when both charts were believed to have exact ARLs.
They do not. The ordering now follows verification, not symmetry:

| | Bernoulli CUSUM | Bernoulli EWMA |
|---|---|---|
| ARL₀ | **exact** — finite lattice, linear solve | requires discretisation |
| Independent published cross-check | **held** | none obtained |
| Blocking work before it can ship | baseline threshold measurement | discretisation scheme, accuracy argument, oracle |

**The EWMA is deferred, not rejected.** ⚠️ **Which binary chart is ultimately
*primary* is not decided here** — an earlier version of this section asserted
that the EWMA remains the intended primary chart, carrying ADR-001's
continuous-score default forward unexamined. See the amendment below.

### 6. Degenerate rates raise

| condition | behaviour |
|---|---|
| `p̂ = 0` — no failures in the baseline | `DegenerateBaselineError`. No design exists: the likelihood ratio is undefined and there is no rate to detect a multiple of. Measured at **0.10%** of baselines across a realistic grid, and **0.6%** at `p₀ = 0.05` with 100 observations, so this is reachable in ordinary use rather than adversarial. |
| `p̂ = 1` — every observation failed | `DegenerateBaselineError`. Symmetric, and the process is not in control in any useful sense. |
| `p₁ = p₀ × multiple ≥ 1` | `InvalidParameterError`. The design point is not a probability. The error reports the largest multiple the baseline admits, which must round-trip as an accepted input (BIN-122's rule). |

## Consequences

**Positive.** The design rule is fixed, so the baseline requirement can be
measured against something stable and the resulting thresholds describe the
chart rather than the measurement harness. The reference value is derived from
first principles and verified numerically, so nothing rests on a citation
chain. The exactness claim is now accurate per chart.

**Negative.** The binary family ships in two stages rather than one, and the
chart ADR-001 designates primary is the later stage. An engineer with a binary
rubric gets a CUSUM — tuned to a design point — before they get the chart that
performs well without one.

**Neutral.** `detect_rate_multiple` is a new concept on the fitting surface, but
it replaces rather than adds: binary charts do not take `reference_value`.

**Reversibility.** High on the lattice denominator, which sits behind a
reported `achieved_arl`. Moderate on the default multiple: it is measured rather
than conventional, so moving it means re-running the regret study, but changing
it breaks no signature. Low on the shift lever itself — `detect_rate_multiple`
is public API, and swapping it for a σ-style parameter later would be breaking.

## Alternatives rejected

**Take `reference_value` directly, as the continuous CUSUM does.** Rejected:
`r` must lie strictly between `p₀` and `p₁` to define a valid likelihood ratio,
and `p₀` is estimated from the baseline the engineer has not inspected. The
parameter's legal range would depend on data they cannot see at the call site,
which is the ergonomic failure ADR-004 avoided elsewhere. Deriving `r` keeps the
engineer's input in units they own.

**Express the shift as an absolute rate difference (`p₁ = p₀ + δ`).** Rejected:
`δ = 0.05` is a catastrophe at `p₀ = 0.01` and noise at `p₀ = 0.40`. A multiple
is scale-free, which is what makes a single default defensible.

**Refine the lattice until the achieved ARL₀ matches the target.** Rejected on
the measurement in §3 — the error is not monotone in the lattice, so this is
chasing a residual that reporting already handles honestly.

**Ship both charts together.** Rejected: it would hold the chart that is
verifiable behind the chart that is not.

## 🚨 What this deliberately does not decide

- **The baseline requirement for binary charts.** This ADR exists so that
  measurement can be done against a fixed rule; the numbers are not in it.
  What is established is that ADR-005 does **not** transfer — at 100
  observations, 18–32% of binary baselines deliver under half the requested
  ARL₀, against a ratified appetite of 5%.
- **The lattice denominator.** A specific `N` is an implementation choice to be
  made with the threshold measurement, not ahead of it.
- **How a binary score is declared** — whether `ScoringResult` gains a score
  type or a separate fitting function infers it. Interacts with BIN-61.
- **When BIN-132's `bool` rejection lifts.** It lifts when a binary chart ships,
  not when this ADR is accepted.
- **Which binary chart is primary.** Added by the amendment below; it was
  previously asserted as settled in the body of this ADR and should not have
  been.

---

## Amendment 2026-09-17 — ratified by the product owner

Three decisions and two corrections, following a retrospective architecture
review of this ADR and a spike commissioned by it. The review was called
because this ADR was authored outside the architecture phase; it re-derived
the reference value, the exactness distinction and the lattice behaviour
independently and confirmed all three. What follows is what it found missing.

### 1. 🚨 Sign convention — Bernoulli observations are higher-is-better

**A Bernoulli observation follows the same convention as every other Caliper
score: `1.0` is the good outcome.** Where this ADR says "the failure rate", it
means `1 − mean(score)`.

This ADR did not state that, and the omission is more dangerous than it looks.
Every other Caliper chart is higher-is-better — the lower arm detects
degradation — while this ADR's text is written throughout in terms of a
*failure* rate rising. The two only reconcile under the mapping above.

⚠️ **The failure mode is silent.** A rubric like *"did it cite a source"*
naturally returns `True` for the good outcome; a rubric like *"was it
harmful"* naturally returns `True` for the bad one. An engineer recording the
second as `1.0` gets a chart that is internally consistent, reports a
plausible achieved ARL₀, and signals on the wrong side. Nothing about it looks
wrong.

### 2. Two-sided by default

**The Bernoulli CUSUM is two-sided by default, configurable to one-sided.**

ADR-004 already settled exactly this for the continuous CUSUM, and this ADR
neither cited it nor explained a departure from it — the omission was an
oversight, not a decision.

The upper arm's design point is `p₀ / detect_rate_multiple`, the same lever
applied symmetrically, so the common case gains **no new API surface**. It
detects a failure rate that has *fallen*, which under Caliper's convention
means the process improved and the baseline is stale — the same reasoning the
continuous charts already apply.

**Rejected:** a separate `improve_rate_multiple` for independent tuning of the
upper arm. No use case names asymmetric tuning, and splitting one parameter
into two later is additive rather than breaking.

### 3. Which binary chart is primary is OPEN

The body of this ADR asserted that the EWMA remains the intended primary
chart. **That assertion was already in question on the record before this ADR
was written, and this ADR neither cited nor addressed it.**

> Neuburger, Walker, Sherlaw-Johnson, van der Meulen & Cromwell (2017),
> *"Comparison of control charts for monitoring clinical performance using
> binary data"*, **BMJ Quality & Safety 26(11), 919–928**, open access:
> *"For small absolute increases in rates of less than 10%, the CUSUM detected
> change most quickly, followed by the EWMA and then the Shewhart p-chart."*

⚠️ **This is not a reason to flip the default either.** The paper's setting is
clinical adverse events, where small sustained increases are the signal of
interest; an abrupt judge-model swap is a *large* shift, a regime where the
gap narrows. **The honest position is that the question is open**, with
published evidence favouring CUSUM in an analogous domain and no
Caliper-specific evidence either way. It is settled by a regret comparison
between the two binary charts once the EWMA's discretisation scheme exists —
not by inheritance from the continuous case.

**Unchanged: the Bernoulli CUSUM still ships first**, on verification
readiness. That decision never depended on which chart is eventually primary.

### 4. The g-chart is rejected, not merely unconsidered

Raised as an alternative this ADR never weighed, and spiked. **It cannot hold
the library's central promise, and fails harder than the p-chart did.**

A g-chart plots successes between failures, so signalling means observing a
gap of `L` or fewer successes, with `L` a non-negative integer. **`L = 0` is a
hard floor** — there is no gap shorter than zero — so the largest attainable
ARL₀ is `1/p²` observations:

| p₀ | closest attainable ARL₀ to 370 | error |
|---|---|---|
| 0.02 | 379.1 | +2.5% |
| 0.05 | 400.0 | +8.1% |
| 0.10 | **100.0** | −73.0% |
| 0.20 | **25.0** | −93.2% |
| 0.30 | **11.1** | −97.0% |

From a 10% failure rate upward the target is not merely missed, it is **above
the maximum the chart can produce**. The p-chart at least had subgroup size as
a lever to trade cost for precision; the g-chart has none, and randomised
signalling is foreclosed on auditability.

⚠️ **It would not have helped even if it calibrated.** It estimates the same
parameter from the same data as the Bernoulli CUSUM, so it inherits the same
Phase I estimation error — the low-failure-rate baseline problem that motivated
the spike is not a property of the chart.

### 5. Two corrections to the body

- **`p₀ < r < p₁` is provable for every `0 < p₀ < p₁ < 1`**, not merely
  verified numerically over the tested range. Writing `a = ln(p₁/p₀) = ∫dx/x`
  and `b = ln((1−p₀)/(1−p₁)) = ∫dx/(1−x)` over `[p₀, p₁]`, we have
  `r = b/(a+b)`, and `a/b` is a weighted average of the strictly decreasing
  `(1−x)/x`, so it lies strictly between the endpoint values `(1−p₁)/p₁` and
  `(1−p₀)/p₀` — which is exactly the stated condition.
- **"bounded by `H/r`" in §4 is loose.** The bound is of order `H·N` for a
  lattice of granularity `1/N`; the two coincide only when `r = 1/N`. The
  load-bearing claim — bounded versus unbounded — is unaffected.

### 6. ⚠️ What this amendment does NOT fix

**The default multiple's regret study still only covers `p₀ ≤ 0.20`**, while
`detect_rate_multiple = 2.0` is legal up to `p₀ < 0.5`. The review derived a
real degeneracy in the untested region: with `M` fixed, `r → p₁` as
`p₀ → 0.5`, so the statistic barely accumulates under the alternative it is
tuned to detect. Measured relative position of `r` between `p₀` and `p₁`:
0.447 at `p₀ = 0.05`, 0.467 at 0.20, **0.781 at 0.499**.

**`2.0` remains the ratified default** — nothing in the tested range disputes
it, and it is still the largest multiple legal across the whole domain. But
"defined for all `p₀`" and "measured for all `p₀`" are different claims, and
only the first is currently true. Extending the study is outstanding work.
