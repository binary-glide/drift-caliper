# ADR-005: Minimum Phase I baseline size for LLM judge scores

**Status:** Accepted, amended twice
**Date:** 2026-09-09
**Amended:** 2026-09-09 (sigma estimator correction — see amendment below),
2026-09-11 (target-dependent adequacy tiers — see amendment below; **this is
the amendment that changes the Decision engineers act on today**)
**Deciders:** system-architect (BIN-92), ratified by product owner. The
2026-09-11 amendment's risk-appetite parameter (**≤5% under half**) was
**ratified by the product owner on 2026-09-11** — see that amendment's own
header for what it means and what it costs.
**Refs:** BIN-92, BIN-64, BIN-65, BIN-84, BIN-94, BIN-95, BIN-114, ADR-001,
ADR-003, ADR-004

## Context

BIN-92 (spike SP-2) asks: what is the minimum viable Phase I baseline size for
reliable control limits on LLM judge scores? BIN-64 (baseline sufficiency check)
needs a defensible default threshold. BIN-65, BIN-94, and BIN-95 (EWMA, CUSUM,
and Shewhart fitting) enforce that threshold at fit time.

`context.md` states "Minimum 20--25 observations for reliable limits." This is
inherited manufacturing SPC guidance. It is the thing to be tested, not the
answer.

### Why this is not a simple lookup

The standard textbook recommendation -- Montgomery (2013, p. 239): "20 to 25
samples of size *n*" where *n* is typically 3 to 5 -- is for **subgroups**, not
individual observations. That recommendation amounts to 100--125 total data
points, not 20--25.

Caliper monitors **individual** scalar judge scores (*n* = 1). Every observation
is a single float. This is the setting where parameter estimation error has the
greatest impact on Phase II chart performance, because no within-subgroup
averaging reduces the variance of each plotted point.

### What the literature says about individual observations

The following findings are from published, peer-reviewed studies on the effect of
Phase I sample size on control chart performance when parameters are estimated
from individual observations (*n* = 1).

**Quesenberry (1993).** "The Effect of Sample Size on Estimated Limits for X-bar
and X Control Charts," *Journal of Quality Technology* 25(4):237--247. Found
that approximately **m = 300** individual observations are required for the
unconditional run-length distribution to behave on average as if parameters are
known. For subgroups of size *n* > 1, approximately m = 400/(*n* - 1) subgroups.
This was the first paper to demonstrate that the standard 20--25 subgroup
recommendation is insufficient.

**Jones, Champ, and Rigdon (2001).** "The Performance of Exponentially Weighted
Moving Average Charts With Estimated Parameters," *Technometrics* 43(2):156--167.
Derived the run-length distribution of the EWMA chart with estimated parameters.
Showed that estimation "can lead to substantially more frequent false alarms and
yet reduce the sensitivity of the chart to detecting process changes." Found that
EWMA performance deteriorates substantially with small Phase I samples.

**Borror, Montgomery, and Runger (1999).** "Robustness of the EWMA Control Chart
to Non-normality," *Journal of Quality Technology* 31(3):309--316. Showed that
the EWMA chart is "quite robust towards non-normal distributions when either the
smoothing parameter or the shift size is large." The in-control and out-of-control
run lengths show minimal differences between normal and non-normal distributions
under those conditions. **However, this study assumed known parameters.** The
combined effect of non-normality *and* parameter estimation is less studied.

**Does, Goedhart, and Woodall (2020).** "On the design of control charts with
guaranteed conditional performance under estimated parameters," *Quality and
Reliability Engineering International* 36(4):1088--1108. Comprehensive review
finding that: (a) the standard 20--40 subgroup recommendation is insufficient;
(b) Quesenberry's m = 300 for *n* = 1 does not account for practitioner-to-
practitioner variability in estimates; (c) "studies invariably show that
impractically large amounts of Phase I data are needed for a practitioner to have
confidence that her/his in-control ARL is near the desired value"; (d) for S^2
charts, Epprecht et al. found requirements "often closer to several thousands
instead of several hundreds." The paper recommends adjusted (wider) control
limits to guarantee minimum performance with smaller samples.

**Huberts, Goedhart, and Does (2022).** "Improved control chart performance using
cautious parameter learning," *Computers & Industrial Engineering* 167:108185.
Found that "at least m = 300 samples are needed to sufficiently reduce
variability in control chart performance" (citing Quesenberry 1993). Recommended
that "when a sufficient number of observations (m >= 500) are available, we
recommend using the EWMA chart ... and not updating the Phase I parameter
estimates."

**Zwetsloot et al. (2017).** "A head-to-head comparative study of the conditional
performance of control charts based on estimated parameters," *Quality
Engineering* 29(2):244--258. Showed that under estimated parameters, the CUSUM
chart generally has higher (more variable) conditional in-control ARL than the
EWMA chart for the same Phase I data -- a difference invisible under the
known-parameter assumption. The sample size *n* in Phase I "influences
considerably the effect of estimation error on the relative Phase II
performance."

### The non-normality complication

ADR-003 established that LLM judge scores violate the normality assumption in
three ways simultaneously:

1. **Bounded** to a fixed range (typically [0, 1]) -- no tails beyond the endpoints.
2. **Left-skewed** in practice -- a working agent scores well most of the time.
3. **Effectively discretised** -- judges return values from a small repeated set.

The minimum sample size is **not distribution-independent**. All of the
Phase I sample-size literature cited above assumes normally distributed
observations. Classical ARL tables (Lucas & Saccucci 1990, Siegmund 1985) also
assume normality. Borror et al. (1999) showed that the EWMA chart's in-control
ARL is reasonably robust to non-normality *when parameters are known*, but the
combined effect of non-normality and parameter estimation from a finite sample
is an open research question.

This means the classical sample-size guidance provides a **lower bound** on
what is needed. Non-normality can only make things worse for parameter
estimation, not better -- bounded, skewed distributions compress the
information available in each observation relative to a normal distribution
with the same variance.

### The sigma estimator and per-chart-type sensitivity

~~ADR-004 established that the Shewhart I-chart estimates sigma from the average
moving range while EWMA and CUSUM use the sample standard deviation.~~ **Corrected
(2026-09-09):** ADR-004 amendment (2026-09-09) established that **all three chart
types** use the MR-based sigma estimate (MR-bar / d_2) on individual observations.
The prior inference that EWMA and CUSUM use the sample standard deviation was not
established by ADR-004 and is contradicted by standard SPC practice. See ADR-004
amendment note for the full reasoning and citation status.

With all three chart types sharing the same sigma estimator, the **estimator
efficiency asymmetry** described in the original text no longer applies: the MR
estimator's reduced efficiency (relative to the sample standard deviation) affects
all chart types equally, not Shewhart alone.

**Zwetsloot et al. (2017) remains relevant, but the explanation changes.** Their
finding -- that the Shewhart chart's conditional ARL has more variability than
EWMA or CUSUM under estimated parameters -- is not explained by a less efficient
sigma estimator (all three now use the same estimator). The variability difference
must arise from other structural properties of the Shewhart chart: EWMA and CUSUM
smooth or accumulate observations, which dampens the effect of sigma estimation
error on individual chart decisions; the Shewhart chart compares each raw
observation against limits directly, with no smoothing buffer. The greater
conditional ARL variability for Shewhart is consistent with its unsmoothed
comparison, not with a different estimator.

**Does the per-chart-type deferral still hold?** Yes, and it is strengthened.
The original case rested partly on the MR estimator being less efficient than the
sample standard deviation for Shewhart alone. That asymmetry is gone. What remains
is the Zwetsloot finding (greater conditional ARL variability for Shewhart) and
the structural argument (unsmoothed comparison amplifies estimation error). These
are still reasons a per-chart-type default *might* be warranted, but they are
weaker than the original case because the estimator efficiency difference is no
longer a factor. The case for per-chart-type defaults now rests entirely on
empirical evidence from the simulation study, not on a theoretical efficiency
gap. The BIN-64 mechanism already supports per-chart-type thresholds (BR-5).

**Does the default of 100 still stand?** Yes. The 100-observation default was
justified from the Phase I estimation literature (Quesenberry 1993; Jones,
Champ & Rigdon 2001) which addresses the sample size needed for reliable
parameter estimates. That literature concerns Phase I sample size, not the choice
of estimator. The MR estimator's lower efficiency means each observation
contributes slightly less information to the sigma estimate than the sample
standard deviation would, but this effect is shared equally across all chart types
and does not change the order-of-magnitude guidance from the literature. The
default of 100 remains the minimum defensible threshold for all chart types.

### Sentry context

Not applicable. Caliper is a library with no runtime to monitor.

## Decision

⚠️ **Amended 2026-09-11 — read this before applying the section below.** The
100-observation figure in this section remains correct as a **hard floor**
(unchanged: below 100, `InsufficientBaselineError`). But the section's premise
— that a single global constant fully answers "how much baseline is enough"
— is **superseded**. A measured study (BIN-114) found the required baseline
size scales with the requested `target_arl`, which this original Decision
treated as independent of size. See "Amendment (2026-09-11): target-dependent
adequacy tiers" at the end of this document for the corrected model. The
subsections immediately below are preserved for their reasoning (why 100 and
not 25, why not 300 as a *hard floor*) — that reasoning is **still valid for
the floor**. It no longer describes the whole policy.

### Default minimum: 100 observations (uniform across chart types)

The library default for the sufficiency check (BIN-64) is **100** individual
observations, applied uniformly to all chart types.

This is documented as a **pragmatic interim default**, not a theoretically
optimal threshold. The library's documentation must state the caveat: this
default is informed by the Phase I estimation literature but has not been
validated specifically for the distributional characteristics of LLM judge
scores. Engineers with domain-specific knowledge should configure a threshold
appropriate to their use case.

### Why 100

The sample-size spectrum for individual observations, from the literature:

| Phase I size | What the literature says |
|---|---|
| 20--25 | Montgomery's textbook minimum -- but for *subgroups of 5*, not individual observations. For *n* = 1, this is dangerously small. Quesenberry (1993) and all subsequent studies agree. |
| ~100 | Jones et al. (2001): EWMA performance with estimated parameters becomes "reasonable" at this scale. This corresponds to the total observation count behind Montgomery's subgroup recommendation (20--25 subgroups * 5 observations). |
| ~300 | Quesenberry (1993): unconditional ARL matches the known-parameter case. Cited by Huberts et al. (2022) as the threshold for "sufficient" reduction in variability. |
| >= 500 | Huberts et al. (2022): "we recommend using the EWMA chart and not updating the Phase I parameter estimates" -- i.e., estimation error is negligible. |
| thousands | Epprecht et al. (per Does et al. 2020): required for *guaranteed* conditional performance of S^2 charts. |

**100 is the minimum defensible default for a library, not the recommendation
for a high-stakes deployment.**

The rationale for 100 over the alternatives:

- **Why not 20--25.** The entire Phase I estimation literature post-Quesenberry
  (1993) agrees this is insufficient for individual observations. Shipping 25
  as the default would make the library complicit in the exact failure mode it
  exists to prevent.

- **Why not 300.** This is Quesenberry's threshold for unconditional ARL
  matching under normality. It does not account for non-normality (which makes
  things worse) or practitioner variability (which Does et al. 2020 showed
  requires still more). 300 is defensible but risks deterring adoption: an
  engineer asked to collect 300 judge-scored observations before any monitoring
  can begin faces a significant onboarding burden at the hardest step in the
  user journey (context.md: "baseline fitting UX is the hardest part").

- **Why not 500.** Per Huberts et al. (2022), this is where estimation error
  becomes negligible for EWMA. But the sufficiency check is *advisory* (BIN-64
  BR-6); fitting enforces it (BIN-65 BR-1). The 500-observation bar, while
  statistically ideal, would make the library impractical for the common case
  of an engineer prototyping quality monitoring.

- **Why 100.** It is the total observation count behind Montgomery's subgroup
  recommendation. It aligns with the scale at which Jones et al. (2001) found
  EWMA performance to be reasonable. It is 5x the dangerously-small 20--25
  range. It is feasible to collect in a reasonable baseline period for most LLM
  agent deployments. And crucially, it is a *default* -- the configurable
  threshold (BIN-64 BR-3) allows engineers to raise it.

### Caveats on the default

The default carries two explicit caveats that must appear in the library's
documentation and in the sufficiency check output:

1. **The normality assumption.** Classical ARL calibration assumes normally
   distributed observations. LLM judge scores violate this. The default of 100
   was derived from normal-theory Phase I estimation studies; the actual minimum
   for comparable ARL accuracy on bounded, skewed, discretised data may be
   higher. Engineers monitoring high-stakes processes should collect more than
   the minimum and review the fitted artefact's achieved vs. requested ARL_0
   (ADR-004) for evidence of calibration degradation.

2. **The estimation error.** At 100 observations, the in-control ARL will not
   match the known-parameter ARL exactly. Does et al. (2020) characterise the
   degradation: "these quantities will vary across practitioners due to the
   use of different reference samples in Phase I. This variation is small only
   for very large amounts of Phase I data." At 100, the variation is moderate.
   At 300, it is reduced. At 500+, it is small.

### Per-chart-type defaults: not yet, but the mechanism is ready

⚠️ **The simulation study this section defers to has now run (BIN-114,
amendment 2026-09-11).** Its answer: **no per-chart-type default is
warranted.** All three chart types need the same order-of-magnitude baseline
size for a given target — maximum spread across charts in any measured cell
is 8 percentage points, mean 2.7pp. See the amendment for the full grid. The
open question this subsection posed is now closed; what replaced it is
target-dependence, not chart-dependence.

BIN-64 BR-5 requires the mechanism to support per-chart-type thresholds. The
mechanism is in place. Per-chart-type defaults are **deferred** to the
simulation study described below. Until that study runs, all chart types share
the 100-observation default.

~~The theoretical case for a higher Shewhart default (less efficient MR-based
sigma estimator) is noted but not acted upon.~~ **Corrected (2026-09-09):** All
three chart types now use the same MR-based sigma estimator (ADR-004 amendment,
2026-09-09), so the estimator efficiency asymmetry no longer applies. Zwetsloot
et al. (2017) still showed greater conditional ARL variability for Shewhart under
estimated parameters, which may justify a per-chart-type default, but this is
now attributed to the Shewhart chart's unsmoothed comparison rather than to a
different estimator. The case for per-chart-type defaults rests on empirical
evidence from the simulation study, not on a theoretical efficiency gap.

## Alternatives considered

### Default of 25 (the `context.md` figure)

**Rejected.** The 20--25 figure in `context.md` is inherited from manufacturing
SPC guidance for subgroups, not individual observations. The entire Phase I
estimation literature since Quesenberry (1993) demonstrates that 20--25
individual observations produce unreliable parameter estimates. Shipping this
as the default would undermine the library's central claim of statistically
defensible control limits.

### Default of 300 (Quesenberry's unconditional ARL threshold)

**Rejected as default; recommended for high-stakes deployments.** 300 is
defensible from the normal-theory Phase I literature, but the adoption cost
is high. An engineer collecting 300 judge-scored observations at the start of
a monitoring programme faces a multi-week baseline collection period before
any monitoring can begin. The sufficiency check is advisory (BIN-64 BR-6),
so the risk of a too-low default is mitigable: fitting enforces sufficiency
(BIN-65 BR-1), and the fitted artefact reports achieved vs. requested ARL_0
(ADR-004), making calibration degradation visible. The documentation should
recommend 300 for regulated or high-stakes environments.

### Default of 50 (a compromise)

**Rejected.** While 50 is better than 25, the Jones et al. (2001) results and
the Quesenberry threshold both suggest that 50 individual observations produce
estimates with substantial residual variability. The Does et al. (2020) review
makes clear that the practitioner-to-practitioner variability at 50 is
significant. The marginal adoption benefit of 50 over 100 (collecting 50
fewer observations) does not justify the increased risk of unreliable limits.

### Per-chart-type defaults from the start

**Deferred.** ~~The theoretical case exists (Shewhart's MR-based sigma estimator
is less efficient).~~ **Corrected (2026-09-09):** all three chart types use the
same MR-based sigma estimator, so the estimator efficiency asymmetry is gone. The
remaining case rests on Zwetsloot et al. (2017) showing greater conditional ARL
variability for Shewhart (attributed to unsmoothed comparison, not estimator
choice). Empirical validation for LLM judge score distributions is still needed.
The BIN-64 mechanism supports per-chart-type thresholds. A simulation study should
determine whether per-chart-type defaults are warranted and what the values should
be. Introducing them without empirical backing would be false precision.

### No default (require the engineer to specify)

**Rejected.** BIN-64 BR-4 requires a library default. An engineer who does not
configure a custom threshold must still receive a meaningful sufficiency
determination. Requiring specification produces a "configure what?" UX problem
for engineers unfamiliar with SPC sample-size considerations.

## Consequences

### BIN-64 (baseline sufficiency check)

The default threshold for the sufficiency check is 100. This plugs into the
configurable mechanism without changing any Gherkin scenario -- no scenario
names a specific threshold number. The library documentation must include the
two caveats (normality assumption, estimation error).

### BIN-65, BIN-94, BIN-95 (EWMA, CUSUM, Shewhart fitting)

All three fitting stories enforce sufficiency at fit time using the threshold
configured via BIN-64. With the default of 100, all three chart types share
the same threshold. If the simulation study later produces per-chart-type
recommendations, the fitting stories already consume per-chart-type thresholds
via BIN-64 BR-5.

No change to any fitting story's PRD or feature file is required.

### BIN-84 (property-based tests for SPC maths)

The test strategy should include a **sensitivity characterisation**: at the
default of 100, at 2x (200), and at 5x (500), measure the achieved in-control
ARL against the nominal ARL_0 across a range of baseline distributions
(normal, beta(8,2), beta(20,2), discretised 5-level). This is not a pass/fail
test but a characterisation that the documentation can cite.

This extends BIN-84's existing mandate (verify computed ARLs against published
tables) with an empirical sensitivity curve specific to Caliper's domain.

### ADR-003 (distributional robustness investigation)

ADR-003 deferred two investigations: (1) an empirical ARL sensitivity study for
non-normal distributions, and (2) nonparametric bootstrap control limits. This
ADR's simulation study recommendation is investigation (1) applied to the
sample-size question. The two should be combined into a single simulation study.

### Documentation

The library's baseline fitting documentation must include:

- The default (100) and its provenance (Phase I estimation literature for
  individual observations)
- The two caveats (normality assumption, estimation error)
- A recommendation for high-stakes deployments (300+ observations)
- Guidance that the achieved-vs-requested ARL_0 on the fitted artefact
  (ADR-004) is the engineer's tool for assessing whether their specific
  baseline was large enough
- A note that per-chart-type defaults may be introduced in a future version
  once the simulation study completes

### What would settle this properly

⚠️ **Partially done (BIN-114, amendment 2026-09-11) — the sample-size axis,
not the distribution axis.** The study specified below ran for **normal
data only**, across all three chart types, five baseline sizes, and four
target ARL₀ values (a superset of the single-target scope this subsection
originally asked for). It produced the target-dependent adequacy tiers in
the amendment. The **Beta / discretised / mixture distribution** legs of the
study below remain **not done** — non-normal robustness is still deferred by
ADR-003, unchanged by this amendment. Treat the numbers below as the
completed normal-data slice of this original plan, not the whole plan.

A **Monte Carlo simulation study** over judge-score-like distributions:

1. **Distributions:** Normal (baseline), Beta(8, 2) (moderate left skew in
   [0,1]), Beta(20, 2) (heavy left skew), discretised 5-level and 10-level
   rubric scores, and a mixture (80% near-ceiling + 20% spread) representing
   a well-functioning agent.
2. **Phase I sizes:** 25, 50, 100, 200, 300, 500.
3. **Chart types:** EWMA (lambda = 0.2), CUSUM (k = 0.5), Shewhart I-chart.
4. **Metric:** For each (distribution, size, chart type) triple, estimate the
   in-control ARL from 10,000 replications and report the median, 10th
   percentile, and 90th percentile of the conditional ARL distribution.
5. **Output:** Degradation curves showing how far the achieved ARL_0 departs
   from nominal at each Phase I size, for each distribution and chart type.

This study would either confirm the 100-observation default, tighten it to a
specific number with empirical backing, or produce per-chart-type defaults.
It would also quantify the non-normality effect that ADR-003 flagged.

**This study is not a v0.1 blocker.** The default of 100 is defensible from the
published literature and is documented with caveats. The simulation study is
post-v0.1 work that strengthens the library's claims rather than unblocking
the walking skeleton.

### Reversibility

**Low cost to change.** The default is a single constant. Changing it in a
future version requires updating the constant, its documentation, and the
BIN-84 sensitivity characterisation. No API or behaviour change. No migration.
Per-chart-type defaults, if introduced, plug into the existing BIN-64
mechanism.

## Related decisions

- **ADR-001 (SPC engine in-house with scipy):** Established the calibration
  methods whose sample-size requirements this ADR addresses. Unmodified.
- **ADR-003 (reject bootstrapped MEWMA):** Flagged the distributional
  robustness concern. The simulation study recommended here is investigation
  (1) from ADR-003's Consequences section, applied to sample size.
- **ADR-004 (fitted artefact protocol):** Established that the artefact reports
  both requested and achieved ARL_0. This is the engineer's tool for assessing
  whether their baseline was large enough. ADR-004 amendment (2026-09-09)
  established that all three chart types use MR-based sigma estimation --
  correcting this ADR's inference that EWMA and CUSUM use the sample standard
  deviation.
- **BIN-64 BR-3, BR-4, BR-5:** Configurable threshold, library default, and
  per-chart-type support. All satisfied by this decision.

## Verified claims

| Claim | Source | Verified |
|---|---|---|
| Montgomery recommends 20--25 subgroups of size 3--5 | Montgomery (2013), 7th ed., **p. 239 read directly 2026-09-11** | **Yes -- primary source.** Verbatim: *"It is highly desirable to have 20--25 samples or subgroups of size n (typically n is between 3 and 5) to compute the trial control limits."* p. 236 adds *"at least 20 to 25 samples"* with *"n will be small, often either 4, 5, or 6"*. **This confirms the correction this ADR rests on: the 20--25 are subgroups, not individual observations.** |
| Quesenberry (1993): m = 300 for n = 1 | *Journal of Quality Technology* 25(4):237--247, confirmed via Does et al. (2020) and Huberts et al. (2022) | Yes -- cited independently by multiple subsequent papers |
| Jones et al. (2001): EWMA deteriorates with small Phase I | *Technometrics* 43(2):156--167 | Yes -- paper abstract confirmed via DOI 10.1198/004017001750386279 |
| Borror et al. (1999): EWMA robust to non-normality | *Journal of Quality Technology* 31(3):309--316 | Yes -- ASU publication record and JQT archive confirm |
| Does et al. (2020): studies invariably show impractically large amounts needed | *QREI* 36(4):1088--1108, DOI 10.1002/qre.2658 | Yes -- full text accessed |
| Huberts et al. (2022): m >= 500 for no updating | *Computers & Industrial Engineering* 167:108185 | Yes -- full text accessed |
| Zwetsloot et al. (2017): CUSUM more variable than EWMA under estimation | *Quality Engineering* 29(2):244--258 | Yes -- full text accessed via DOI |

| Claim | Could not verify from available sources |
|---|---|
| Exact Jones et al. (2001) table entries for m = 100 | Full-text paywalled; finding confirmed via secondary citations |
| Relative efficiency of MR/d2 vs sample std dev (specific number) | Not pinned; stated qualitatively as "less efficient" per standard SPC literature |

---

## Amendment (2026-09-09): correct sigma estimator inference

**Trigger:** ADR-004 amendment (2026-09-09) established that all three chart types
use MR-based sigma estimation on individual observations. This ADR's "sigma
estimator efficiency question" section had inferred that "EWMA and CUSUM use the
sample standard deviation" -- an inference ADR-004 never established and which is
contradicted by standard SPC practice.

### What changed

1. **Section "The sigma estimator efficiency question"** rewritten as "The sigma
   estimator and per-chart-type sensitivity." The incorrect premise (different
   estimators per chart type) is struck. The analysis is reframed around the
   corrected premise (all chart types share the MR estimator).

2. **Zwetsloot et al. (2017) re-attributed.** Their finding of greater conditional
   ARL variability for Shewhart is no longer explained by a less efficient sigma
   estimator. It is attributed to the Shewhart chart's unsmoothed comparison --
   EWMA and CUSUM smooth or accumulate observations, dampening the effect of sigma
   estimation error on individual chart decisions.

3. **Per-chart-type deferral stands, strengthened.** The original case for per-
   chart-type defaults rested partly on the estimator efficiency asymmetry, which
   is gone. The remaining case (Zwetsloot's conditional ARL variability) is weaker
   and rests entirely on empirical evidence from the simulation study.

4. **Default of 100 stands unchanged.** The default was justified from Phase I
   estimation literature (Quesenberry; Jones et al.), which concerns sample size
   for reliable parameter estimates regardless of estimator choice. The MR
   estimator's lower efficiency affects all chart types equally and does not change
   the order-of-magnitude guidance.

### What did not change

- The default of 100 observations.
- The per-chart-type deferral to the simulation study.
- The normality and estimation error caveats.
- The BIN-84 sensitivity characterisation recommendation.
- The simulation study specification.
- All verified claims remain valid.

### Feature file impact

**No feature files change.** No feature file names a sigma estimator or a per-
chart-type baseline size. Zero re-review cost.

---

## Amendment (2026-09-11): target-dependent adequacy tiers

**Trigger:** `BIN-84`'s property-based verification surfaced (`BIN-114`) that
`achieved_arl` is exact only *conditional on the Phase I baseline being the
true process* — with a finite baseline it is a random variable, and at the
library's default (*n* = 100) roughly one engineer in seven to one in five
(depending on target) sees a realised false-alarm interval under half of what
they were shown. Two exploratory measurements on `BIN-114` narrowed this to a
single question for ADR-005: **is the required baseline size independent of
the requested `target_arl`, as the original Decision above assumed?** A third,
properly powered study (300 baseline draws x 200 Phase II runs per cell, all
three chart types, five baseline sizes, four target ARL₀ values — the full
dataset is `Projects/caliper/references/adr005_grid.json` in the vault,
scripts `adr005_study.py` / `adr005_grid.py` alongside it) answers: **no.**
Required baseline size scales with `target_arl`. This amendment corrects the
model, not just the number.

⚠️ **THRESHOLDS UNDER REVIEW — added 2026-09-11, hours after this amendment
merged.** An OCR'd extract of **Jones, Champ & Rigdon (2001)** — this
amendment's own stated exit condition — was obtained the same day, and it
suggests `adequate()`'s figures below are **too low**:

- JCR require **300 subgroups of size 5 (= 1500 observations)** at *r* = 0.2,
  Caliper's `DEFAULT_SMOOTHING_PARAM`, versus the **500 individual
  observations** this amendment adopts.
- 🚨 They state their figures are a **best case**: they use the *most*
  efficient unbiased σ estimator (`S_p/c₄ₘ`), note
  `var[S_p/c₄ₘ] ≤ var[S/c₄] ≤ var[R/d₂]`, and warn that *"using a less
  efficient estimator will result in charts that perform worse … a larger
  sample size may be required."* **Caliper uses moving-range estimation —
  the `R/d₂` family, the least efficient of the three.**

**What is NOT in doubt:** the *model* — target-dependent adequacy, three tiers,
the hard floor at 100. That structure is unaffected and remains correct.

**Why this is not corrected here and now.** Three things are unresolved, and
guessing any of them would repeat the error this ADR already fixed once:

1. JCR's figures are **subgroups of size 5**; Caliper monitors **individuals**
   (*n* = 1). The comparable quantity is degrees of freedom in the σ estimate,
   and that conversion has not been done. **This is the exact trap of
   Montgomery's 20–25.**
2. The **criteria differ** — JCR bound the false-alarm rate at *t* = 20 to a
   10% rise; this amendment bounds the share of baselines delivering under half
   the requested ARL₀. Neither subsumes the other.
3. The source is an **OCR'd extract with a known transcription error**, not the
   paper.

**Do not adjust the numbers below until a clean copy is held and the *n* = 1
conversion is done.** Recorded on `BIN-114`. Treat `adequate()` as a
provisional floor that is more likely to rise than fall.

### The risk-appetite parameter — RATIFIED 2026-09-11

🚨 **Caliper's stated risk appetite: at most 5% of Phase I baselines may
deliver under half the requested ARL₀.** Ratified by the product owner,
2026-09-11.

**This is a product decision, not a statistical result.** No analysis produces
it; it is a statement of how much of the tail the project is willing to accept
before it tells an engineer their baseline is too small. It was first chosen
by the person who ran the study, who had no authority to set an organisational
risk tolerance — that gap is now closed by explicit ratification.

**Every threshold in this amendment derives from it.** `adequate(target_arl)`
is *defined* as the smallest measured baseline size holding the under-half
rate at or below 5%. Change the appetite and every number moves:

| risk appetite | t=100 | t=200 | t=370 | t=500 |
|---|---|---|---|---|
| 10% (looser) | 200 | 300 | 300 | 300 |
| **5% — ratified** | **300** | **300** | **500** | **500** |
| 2% (tighter) | 500 | 500 | 1000 | 1000 |

**Why 5% and not the alternatives:**

- **10%** would let `adequate()` collapse to roughly "300 everywhere" — a
  simpler rule and a lower adoption barrier, at roughly **double** the tail
  risk. One engineer in ten receiving under half the ARL₀ they were shown is
  too many for a library whose central claim is a calibrated false alarm rate.
- **2%** would push high-target adequacy to **1000** — ten times the current
  default, approaching the "thousands" regime Does et al. (2020) report for
  S² charts. That is statistically safer and, against an OMTM of Phase I→II
  conversion, not a library anyone would adopt.
- **5%** sits between them without forcing `adequate()` into four figures at
  any target this library realistically serves.

⚠️ **What ratifying 5% does *not* settle.** It fixes the acceptance line, not
the measurement behind it. The 300/500 figures remain **measured, not
derived** — simulation on normal data with moving-range σ, 300 draws, ±3pp,
and a step function over four targets rather than a curve. Jones, Champ &
Rigdon (2001) would replace them with a closed form (see Exit condition).
**Ratification makes the threshold authoritative; it does not make the
numbers exact.**

**To revisit:** changing the appetite requires re-deriving `adequate()` from
the grid (or from JCR's formula once held) and re-ratifying. It must not be
adjusted informally to make a given baseline size look sufficient — that
would invert the whole point of having a stated appetite.

Everything else in this amendment — the existence of target-dependence, the
measured grid, the case against the PRD's provisional trigger — stands
independently of this figure.

### The study, briefly

Charts fitted by Caliper's real `fit_ewma`/`fit_cusum`/`fit_shewhart` from a
finite Phase I baseline drawn from a known N(8.0, 0.5) process. Phase II
simulated from the **true** process — what an engineer actually experiences,
not what the fitted artefact assumes. The Phase II simulator is a vectorised
recursion rather than `Monitor.record()`, purely for the ~10⁹-observation
scale the grid needs; it was validated against the shipped `Monitor.record()`
before being trusted (EWMA 157.8 vs 148.6, CUSUM 151.2 vs 158.1, Shewhart
145.9 vs 140.2 — all within the ~5% sampling error of 400 runs at that
validation scale).

**Extended validation, 2026-09-11**, closing a weakness the first draft of
this amendment flagged honestly — the simulator had been checked at only one
mid-grid configuration, and the grid's conclusion is driven by its *extremes*.
Re-validated there, 500 runs per point:

| cell | `Monitor.record()` | vectorised | difference |
|---|---|---|---|
| EWMA *n*=100, t=500 *(worst case, drives the headline)* | 1015.6 | 1052.3 | +3.6% (0.8 SE) |
| EWMA *n*=1000, t=100 *(best case)* | 93.2 | 105.6 | +13.3% (3.0 SE) |
| CUSUM *n*=100, t=500 | 1069.6 | 1158.3 | +8.3% (1.9 SE) |
| Shewhart *n*=100, t=500 | 1191.0 | 1159.5 | −2.6% (0.6 SE) |

All within 3 SE. ⚠️ **Note the direction**: the vectorised path reads
*slightly high* in three of four comparisons. If it carries any systematic
bias it over-estimates run length, which would make the true "under half"
percentages **higher** than this grid reports. The bias therefore runs
*against* this amendment's conclusion rather than toward it — the safe
direction for a finding that says the current default is inadequate.

*n* < 100 could not be studied: `fit_*` already raises
`InsufficientBaselineError` below the hard floor, so that region is
unreachable for any real user and there was nothing to measure.

**Percentage of baselines delivering under half the requested ARL₀** (range
across the three chart types; the amendment's adopted numbers below use the
mean of the three):

| *n* | target=100 | target=200 | target=370 | target=500 |
|---|---|---|---|---|
| **100** *(current default)* | 13-15% | 21-22% | 23-29% | 26-32% |
| 200 | 5-6% | 9-12% | 13-17% | 13-21% |
| 300 | 1-3% | 2-7% | 7-9% | 8-10% |
| 500 | 0-1% | 1-2% | 3-7% | 2-5% |
| 1000 | 0% | 0% | 0-1% | 0-2% |

### Three findings

**1. All three chart types behave the same.** Maximum spread across chart
types in any single cell is 8 percentage points; mean spread 2.7pp. This is a
property of *parameter estimation from a finite sample*, not of chart choice.
It resolves the "per-chart-type defaults: not yet" question left open above:
**no per-chart-type default is warranted.** One policy serves EWMA, CUSUM,
and Shewhart alike.

**2. The median is biased low at the default, not merely noisy.** At *n* =
100, median delivered ARL₀ as a fraction of the target ranges roughly 72-83%
across the four measured targets (EWMA: 83% at target=100, falling to 72% at
target=500). This is worse than an earlier same-day exploratory measurement
at a single target had suggested, and it means the *typical* engineer at the
default configuration — not only an unlucky one — gets meaningfully less
than what `achieved_arl` reports.

**3. Quesenberry was right; ADR-005's compromise went further than the
evidence now supports.** Smallest measured *n* holding "under half" at or
below 5% (mean across the three chart types):

| target ARL₀ | *n* needed |
|---|---|
| 100 | 300 |
| 200 | 300 |
| 370 | 500 |
| 500 | 500 |

The original Decision above cited Quesenberry (1993) for ~300 individual
observations and then chose 100 as a deliberate adoption compromise. This
study, run against Caliper's own implementation rather than against the
literature in the abstract, lands the "adequate" figure at 300-500 depending
on target — closer to Quesenberry's figure than to the compromise. The
literature was right; the compromise is where the gap opened.

### Why the PRD's provisional trigger (`requested_arl > observation_count`) is superseded, not merely refined

`BIN-114`'s PRD (BR-3, labelled explicitly provisional pending this exact
amendment) proposed advising whenever `target_arl > observation_count`,
reasoning that this was the only boundary sourceable without inventing a
ratio. The grid now shows that boundary is **measurably too lax** — it
fails to fire in exactly the cases where the risk is highest:

- At *n* = 100, target = 100 (equal — the PRD trigger does **not** fire,
  since it requires strict inequality): **14.1%** of baselines deliver under
  half the requested ARL₀ anyway.
- At *n* = 200, target = 200 (also equal, also does not fire): **10.4%**
  still deliver under half.

Both are double-digit-percent risk of a ≥2x false-alarm-rate miss, silently
passed through by a trigger keyed on `target_arl` exceeding `n`, because the
real requirement is not "target exceeds sample size" but "sample size is a
small multiple of target" — the ratio needs to be roughly 3-5x, not 1x, before
risk falls to the low single digits. **The measured thresholds in this
amendment replace BR-3's trigger outright, not adjust it.** BR-5's caveat
(label the mechanism as provisional, not precision-dressed) still applies to
the replacement — see "Precision of the adequate() function" below — but the
replacement itself is now evidence-based rather than a structural guess.

### The amended decision: three tiers

The original single-constant model (`DEFAULT_SUFFICIENCY_THRESHOLD = 100`,
sufficient or not, nothing else) is replaced with three tiers. The hard floor
is unchanged; what is new is the middle tier.

| tier | condition | behaviour |
|---|---|---|
| **below floor** | `observation_count < 100` | `InsufficientBaselineError` — unchanged. Fitting is refused. |
| **fits, flagged** | `100 <= observation_count < adequate(target_arl)` | Fitting succeeds and returns usable, correctly-calibrated control limits (the maths is not in question — see `BIN-84`). A structured, non-raising advisory is attached, naming `observation_count`, `target_arl`, and the `adequate()` figure it falls short of. |
| **fits, clean** | `observation_count >= adequate(target_arl)` | Fitting succeeds. No advisory. |

`DEFAULT_SUFFICIENCY_THRESHOLD` (100) remains the **only** hard floor and is
**unchanged** — this amendment does not raise it, for the OMTM reasons argued
below. `adequate(target_arl)` is a **second, new concept**: a non-blocking
adequacy line that depends on what the engineer is asking the chart to
achieve, not a replacement for the floor.

### `adequate(target_arl)`, and its precision

From the grid, at the ratified 5%-under-half risk line, mean
across chart types:

```
adequate(target_arl):
    target_arl <= 200   -> 300
    target_arl  > 200   -> 500   (measured range tops out at target_arl = 500;
                                   see caveats below for values beyond that)
```

This is a **coarse two-step function over four measured target values**, not
a fitted curve. Fitting a continuous function to 20 measured cells (4 targets
x 5 baseline sizes) would be false precision the data does not support — the
grid resolves "which side of ~300-500 are you on," not "what is the exact
number for `target_arl` = 250." `target_arl` values between the measured
points (e.g. 250, 300) should round up to the next tier rather than
interpolate, consistent with this project's rule that no numerical constant
ships beyond what its source supports. `target_arl` above 500 is
**unmeasured**; treat `adequate() = 500` as a floor, not a validated answer,
for that range, and have the advisory say so explicitly when it fires there.

**This is the same discipline BR-5 already asked for, applied to a better-
sourced number.** The original PRD trigger was "provisional… pending Jones,
Champ & Rigdon (2001)"; so is this one. It is a materially better-evidenced
provisional answer — measured on Caliper's own fitting code rather than
inferred from a structural inequality — but it is still simulation, not the
closed-form result JCR (2001) would provide. See "Exit condition" below.

### Decision-support: what the alternatives would have meant

Retained after ratification so the reasoning stays visible — this is *why* 5%
was chosen, not an open question:

| risk appetite ("under half" ceiling) | target=100 | target=200 | target=370 | target=500 |
|---|---|---|---|---|
| 10% (looser) | 200 | 300 | 300 | 300 |
| **5% (used above)** | **300** | **300** | **500** | **500** |
| 2% (tighter) | 500 | 500 | 1000 | 1000 |

A looser appetite (10%) would let `adequate()` collapse to roughly "300
everywhere," simplifying the function at the cost of accepting roughly twice
today's tail risk. A tighter appetite (2%) would push high-target adequacy to
1000 — ten times the current default — which starts to look like the
"thousands" regime Does et al. (2020) reported for S² charts, cited in the
original Decision above. **5% was chosen because it sits between these
without requiring the function to jump to four figures. It is a ratified
product decision (2026-09-11), not a derived quantity.**

### Engaging with the OMTM this reopens

ADR-005's original compromise (100, not 300) was explicit that Phase I->Phase
II conversion is the project's One Metric That Matters, and that asking an
engineer to collect 300+ scored observations before any monitoring begins is
a real adoption cost at the hardest step in onboarding. This amendment does
**not** raise that cost at the floor — an engineer can still fit, and still
get a working chart, at 100 observations, exactly as before. What changes:

- **The advisory will fire for most realistic default configurations, not a
  minority.** `target_arl` = 370 and 500 are the two classical ARL₀ figures
  used throughout the SPC literature and already used as test-oracle targets
  in `BIN-84` (Lucas & Saccucci 1990, Siegmund 1985). An engineer who follows
  the library's own default (`n` = 100) and picks a classical target will see
  the advisory almost every time, because `adequate(370)` and `adequate(500)`
  are both 500 — five times the floor. This was flagged as the central design
  risk in `BIN-114`'s PRD (OQ-4, warning fatigue) before this amendment
  existed, and the amendment confirms the concern was correctly weighted: the
  naive PRD trigger under-fired; the measured one will fire often.
- **This is treated as the correct outcome, not a defect to design around.**
  The alternative — staying silent because the advisory would fire "too
  often" — is exactly the overclaim this investigation exists to correct. A
  library whose central pitch is calibrated, citable false-alarm rates cannot
  suppress the one signal that tells an engineer their specific number is
  less trustworthy than it looks, merely because that signal is common. What
  protects the OMTM is that **the advisory does not block fitting** — the
  metric Phase I->II conversion actually measures (does the engineer
  successfully get a working chart at all) is untouched. What the advisory
  costs is a quieter, different thing: an engineer can no longer fit at the
  default and see silence read as "you're fully covered." That silence was
  false; removing it is the fix `BIN-114` was opened to make.
- **The alternative that would have genuinely damaged the OMTM — raising
  `DEFAULT_SUFFICIENCY_THRESHOLD` itself to 300 or 500 — is explicitly
  rejected**, for the same reason the original Decision rejected it: it
  would turn "collect 100 observations" into "collect 300-500 observations"
  *before any chart exists at all*, for every engineer, regardless of their
  target. The tiered model confines the cost to disclosure, which is cheap,
  rather than to access, which is expensive. This is the load-bearing
  difference between this amendment and simply moving the old constant.
- **Net honest framing:** this amendment does not make Caliper's default
  configuration more capable. It makes Caliper stop implying, by silence,
  that the default configuration is more capable than the study shows it to
  be. That is a real cost to the story the library can currently tell about
  itself with a bare `achieved_arl` number, and it is the right trade — the
  project's own foremost rule (every statistical claim cited or derived, never
  overclaimed) does not have a carve-out for claims that are inconvenient to
  disclose.

### Methodological caveats — read before treating any number above as exact

- **Normal data, one process, one sigma.** All 60 cells are N(8.0, 0.5).
  Judge scores are not normal (ADR-003); this amendment does not close that
  gap, and non-normality can only widen the true requirement, not narrow it,
  per the original Decision's own reasoning above.
- **Moving-range sigma estimation only** — Caliper's method (ADR-004
  amendment). The specific numbers are tied to this estimator.
- **300 draws per cell -> roughly +/-3 percentage points of sampling noise**
  on every percentage in the tables above. The 300-vs-500 boundary is soft;
  do not read either number as exact.
- **The adopted `adequate()` figures use the *mean* under-half rate across
  the three chart types, not the worst case.** At the chosen 5% line, some
  individual chart/target cells exceed 5% even where the mean is at or below
  it — e.g. CUSUM at *n* = 300/target = 200 measures 7.0% (mean across charts:
  4.9%, which is why 300 was selected as adequate for that target). Using
  worst-case-per-chart instead of mean-per-target would push some `adequate()`
  entries higher. This is a real methodological choice, not an oversight, and
  it is made here explicitly: **averaging across chart types was chosen
  because finding 1 above shows chart type is not the source of the
  variation** — but a reader who wants a worst-case rather than an
  expected-case guarantee should treat the table in "Decision-support" above
  as a starting point for a stricter recomputation, not as already covering
  that case.
- **Run-length cap at 12x target** truncates the extreme upper tail of the
  achieved-ARL distribution in each cell, which the raw grid records as
  `over_double` alongside `under_half`; this does not affect the under-half
  figures this amendment relies on, but it means the p90-style upper-tail
  statistics elsewhere in `BIN-114`'s discussion are conservative
  underestimates of spread.
- **This is simulation, not the closed-form result.** See "Exit condition"
  immediately below.

### Exit condition: Jones, Champ & Rigdon (2001)

**Jones, L. A., Champ, C. W. & Rigdon, S. E. (2001). "Performance Analysis of
Exponentially Weighted Moving Average Charts When Parameters Are Estimated."
*Technometrics* 43(2), 156-167. DOI 10.1198/004017001750386279.** Already
cited in this ADR's original Decision section, and already known (via its
abstract) to derive the run-length distribution of the EWMA chart with
estimated parameters **analytically** — a formula, not a Monte Carlo
simulation. It is **not currently held**; full text is paywalled behind
Taylor & Francis and needs institutional access (tracked alongside `BIN-82`'s
reference-acquisition list).

**When obtained, JCR (2001) replaces the simulated `adequate()` step function
in this amendment with a closed-form threshold**, the same pattern ADR-004
and ADR-009 use for other deferred primary-source verifications. It would
also let Caliper report an interval around `achieved_arl` rather than a bare
point estimate — the deeper fix `BIN-114`'s PRD names as its preferred
post-v0.1 direction (Non-Goals) and defers for exactly this reason. Until
then, `adequate()` as specified above is this project's best evidenced
answer, clearly labelled as simulation-derived and provisional.

### Consequences

**`BIN-64` (baseline sufficiency check).** `DEFAULT_SUFFICIENCY_THRESHOLD`
(100) is unchanged and remains the sole hard floor enforced by
`check_sufficiency()` / fitting-time `InsufficientBaselineError`. This
amendment adds a second, independent concept — target-dependent adequacy —
that `BIN-64`'s existing signature (`threshold?`, `chart_type?`) does not yet
carry a parameter for. **Exact carrier is out of scope for this amendment**
(`BIN-114`'s own OQ-3, still open) — candidates remain what `BIN-114`'s PRD
already proposed: an optional `target_arl` parameter on `check_sufficiency()`,
or a field populated by `fit_ewma`/`fit_cusum`/`fit_shewhart` at fit time.
What this amendment settles is the **policy** (the tiers and the numbers);
the API shape is a separate, smaller decision for whoever implements
`BIN-114`.

**`BIN-65`, `BIN-94`, `BIN-95` (EWMA, CUSUM, Shewhart fitting).** No change to
any fitted output, formula, or default (BR-4, unchanged, still holds). The
advisory this amendment specifies is additive metadata attached at or after
fit time, mirroring `SufficiencyResult.data_quality_concerns`
(`DataQualityConcern`-shaped: `kind`, `description`). Applies uniformly to all
three chart types (finding 1 above; BR-6 in `BIN-114`'s PRD already assumed
this and is now confirmed rather than merely inferred from Zwetsloot et al.).

**`BIN-84` (property-based verification).** The sensitivity characterisation
this ADR originally recommended (§ "What would settle this properly") is now
substantially complete for normal data across all three chart types — the
`adr005_grid.json` dataset (vault, `Projects/caliper/references/`) is that
characterisation's output and should be treated as `BIN-84`'s reference
artefact for this question going forward, superseding the need to re-derive
it. The Beta / discretised / mixture distribution legs remain undone.

**`BIN-114` (this ADR's direct trigger).** BR-3 and BR-5 of `BIN-114`'s PRD,
and Open Question OQ-1, are **settled by this amendment**: the trigger is no
longer "requested_arl > observation_count" but "observation_count <
adequate(target_arl)" per the table above, and the numeric basis is now the
measured grid rather than the two-point structural inference the PRD flagged
as provisional. OQ-3 (exact field/carrier shape) remains open, per
Consequences/`BIN-64` above. OQ-2 (whether CUSUM/Shewhart deserve the same
confidence as EWMA) is also settled: yes, with the same evidence weight as
EWMA, since this amendment's grid measured all three directly rather than
inferring from EWMA alone.

**Documentation.** The library's baseline-fitting documentation, and
`FittedControlLimits.achieved_arl`'s own docstring, must state: `achieved_arl`
is calibrated against the Phase I baseline's *estimate* of the process, not
the true process; a finite baseline makes the realised false-alarm rate a
random variable around that figure, citing Quesenberry (1993) and Jones,
Champ & Rigdon (2001); and that Caliper surfaces a structured advisory when
`observation_count` falls short of the measured adequacy line for the
requested target. No unqualified numeric spread (e.g. "+/-2x") belongs in the
docstring — the existence and direction of the effect, plus the citations,
per `BIN-114` PRD's Story 1 acceptance criteria.

### Alternatives considered

**Raise `DEFAULT_SUFFICIENCY_THRESHOLD` to 300 or 500 uniformly.** Rejected.
Quintuples (500) or triples (300) the Phase I barrier for *every* engineer
regardless of their target, including engineers whose target is modest enough
that 100 is already adequate (e.g. target=100 needs only 300, not 500; many
engineers may want a much smaller target than the classical 370/500 figures).
Directly damages the OMTM for no benefit to the engineers whose configuration
was never at risk.

**Keep the PRD's provisional `requested_arl > observation_count` trigger
unchanged.** Rejected — see "Why the PRD's provisional trigger is superseded"
above. Measurably under-warns at exactly the equal-value boundary case, where
double-digit-percent risk exists but the trigger is silent.

**Per-chart-type adequacy thresholds.** Considered, following the mechanism
`BIN-64` BR-5 already supports and the original Decision above already
flagged as a live possibility. Rejected on the evidence: finding 1 shows
chart-type spread (2.7pp mean, 8pp max) is small relative to
target-dependence (tens of percentage points across the target range). One
policy, keyed on target rather than chart type, is both simpler and better
supported by the data.

**Continuous/interpolated function of `target_arl` rather than a two-step
function.** Considered. Rejected as false precision: only four target values
and five baseline sizes were measured. A fitted curve through 20 sparse,
noisy (+/-3pp) cells would imply a resolution the data does not have. A coarse
step function, explicitly labelled provisional, better represents what is
actually known.

**Report an interval instead of any threshold-based advisory.** This is the
long-run correct fix (see Exit condition) and is explicitly **not** rejected
— it is deferred, blocked on obtaining Jones, Champ & Rigdon (2001). The
tiered advisory in this amendment is the interim, honestly-labelled
mitigation `BIN-114`'s PRD already scoped as v0.1's Non-Goal boundary.

**Do nothing — leave the original single-constant Decision as the final
word.** Rejected. The original Decision was reasoned correctly from the
literature available at the time but rested on an unstated assumption
(baseline size requirement is independent of target) that this study shows to
be false. Leaving it uncorrected would mean the ADR continues to certify a
model contradicted by measurement on the library's own code.

### What did not change

- `DEFAULT_SUFFICIENCY_THRESHOLD` (100) as the hard floor and
  `InsufficientBaselineError` below it.
- No change to `fit_ewma`, `fit_cusum`, `fit_shewhart`, or `Monitor`.
- The normality caveat (ADR-003 still deferred; this amendment's grid is
  normal-data-only).
- The recommendation that high-stakes deployments collect well above the
  floor (this amendment sharpens "well above" into a number that depends on
  target, rather than leaving it as an unqualified "300+").
- BIN-64 BR-1 through BR-4 (configurable threshold, library default,
  advisory-not-raising semantics, no maths change).

### Feature file impact

No existing feature file names a specific baseline-size number, per the
established convention (`ADR-005`'s original Decision, `BIN-64`, `BIN-65`,
`BIN-94`, `BIN-95` all use qualitative Gherkin). `BIN-114`'s own new feature
file (drafted in its PRD, Story 2) already avoids a numeric literal for the
trigger and is unaffected by this amendment replacing the trigger's
*definition* — the scenarios assert on the advisory's presence/absence and
structure, not on the number that decides it.
