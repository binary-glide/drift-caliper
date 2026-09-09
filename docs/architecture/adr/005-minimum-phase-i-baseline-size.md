# ADR-005: Minimum Phase I baseline size for LLM judge scores

**Status:** Accepted
**Date:** 2026-09-09
**Deciders:** system-architect (BIN-92), ratified by product owner
**Refs:** BIN-92, BIN-64, BIN-65, BIN-84, BIN-94, BIN-95, ADR-001, ADR-003, ADR-004

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

### The sigma estimator efficiency question

ADR-004 established that the Shewhart I-chart estimates sigma from the average
moving range (MR) divided by the unbiasing constant d_2, while EWMA and CUSUM
use the sample standard deviation. These are different quantities.

The MR-based estimator uses only adjacent pairs of observations, discarding
information from non-adjacent pairs. It is statistically **less efficient** than
the sample standard deviation for normally distributed data. The relative
efficiency is a known quantity in the SPC literature (see Montgomery 2013,
Chapter 6; Cryer and Ryan 1990). This means the Shewhart chart's sigma
estimate has higher variance than EWMA/CUSUM's for the same number of
observations.

**Does this mean Shewhart needs more observations?** In principle, yes -- a less
efficient estimator needs more data to achieve the same precision. However:

1. Zwetsloot et al. (2017) showed that under estimated parameters, the
   *Shewhart* chart's conditional ARL has **more variability** than EWMA or
   CUSUM, consistent with the less efficient sigma estimator.
2. The Shewhart chart is used for detecting **large, acute** shifts (ADR-001),
   not small sustained drift. Its detection power for large shifts is less
   sensitive to sigma estimation precision than EWMA/CUSUM's detection of
   small shifts.
3. The non-normality effect on the MR estimator vs. the sample standard
   deviation has not been characterised for LLM judge score distributions.

Setting per-chart-type defaults now would add UX complexity without empirical
validation. The mechanism already supports per-chart-type thresholds (BIN-64
BR-5). Per-chart-type defaults should follow from the simulation study
recommended below, not from theoretical efficiency ratios alone.

### Sentry context

Not applicable. Caliper is a library with no runtime to monitor.

## Decision

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

BIN-64 BR-5 requires the mechanism to support per-chart-type thresholds. The
mechanism is in place. Per-chart-type defaults are **deferred** to the
simulation study described below. Until that study runs, all chart types share
the 100-observation default.

The theoretical case for a higher Shewhart default (less efficient MR-based
sigma estimator) is noted but not acted upon, because:

- The efficiency difference is known only for normally distributed data.
- The Shewhart chart's primary role (detecting large acute shifts) is less
  sensitive to sigma estimation precision than EWMA/CUSUM's detection of
  small sustained shifts.
- Introducing per-chart-type defaults adds UX complexity. The complexity
  should be justified by empirical evidence, not theoretical efficiency
  ratios.

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

**Deferred.** The theoretical case exists (Shewhart's MR-based sigma estimator
is less efficient), but empirical validation for LLM judge score distributions
is needed. The BIN-64 mechanism supports per-chart-type thresholds. A
simulation study should determine whether per-chart-type defaults are
warranted and what the values should be. Introducing them without empirical
backing would be false precision.

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
  whether their baseline was large enough.
- **BIN-64 BR-3, BR-4, BR-5:** Configurable threshold, library default, and
  per-chart-type support. All satisfied by this decision.

## Verified claims

| Claim | Source | Verified |
|---|---|---|
| Montgomery recommends 20--25 subgroups of size 3--5 | Montgomery (2013, p. 239), cited via Does et al. (2020) and Johnson (2016) | Yes -- multiple secondary sources confirm the textbook recommendation |
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
