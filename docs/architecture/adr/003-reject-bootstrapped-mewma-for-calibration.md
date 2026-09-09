# ADR-003: Reject bootstrapped MEWMA (arXiv:2507.16749) for control-limit calibration

**Status:** Accepted
**Date:** 2026-09-09
**Deciders:** system-architect (BIN-93), ratified by product owner
**Refs:** BIN-93, BIN-65, BIN-84, BIN-92, BIN-95, ADR-001

## Context

BIN-93 (spike SP-3) asked whether Caliper should adopt the bootstrapped MEWMA
approach from Wu & Apley (2026) for more data-efficient control-limit
calibration, instead of or alongside the classical Phase I fitting that ADR-001
already established.

**Paper under evaluation:**

- Wu, J. and Apley, D.W. (2026). "Bootstrapped Control Limits for Score-Based
  Concept Drift Control Charts." *Technometrics* (2026).
  DOI: 10.1080/00401706.2026.2676855. arXiv: 2507.16749v3 (21 March 2026).

The paper builds on Zhang, K., Bui, A.T., and Apley, D.W. (2023). "Concept
drift monitoring and diagnostics of supervised learning models via score
vectors." *Technometrics* 65(2):137-149.

**Caliper's current calibration approach (ADR-001):**

- EWMA: Lucas & Saccucci (1990) Markov-chain approximation targeting a
  specified ARL_0.
- CUSUM: Siegmund (1985) corrected diffusion approximation targeting ARL_0.
- Shewhart I-chart: direct tail-probability relationship between k and ARL_0.
- Verification: published ARL tables as test-oracle fixtures (BIN-84).

**The spike framed three outcomes:** (a) adopt, (b) defer, (c) reject.

### What the paper actually does

The paper makes two contributions:

1. **Score-based drift monitoring via MEWMA.** The method monitors Fisher score
   vectors -- gradients of the log-likelihood from a parametric supervised
   learning model fitted via maximum likelihood estimation (MLE). Changes in
   the score vector's mean are detected using a multivariate EWMA (MEWMA) with
   a Hotelling T-squared statistic. This follows Zhang et al. (2023).

2. **A nested bootstrap procedure for calibrating the control limit.** The
   prior method (Zhang et al. 2023) splits initial data into a training subset
   (for model fitting) and a holdout subset (for control-limit computation).
   The bootstrap eliminates this split, allowing the entire initial sample to
   be used for model fitting. A novel 0.632-like correction accounts for
   bootstrap samples containing only ~63.2% unique observations, which causes a
   naive bootstrap to underestimate score-vector variability.

### Why this was investigated

The ticket framed the spike around data efficiency: "The bootstrapped MEWMA
approach claims to produce reliable control limits with fewer observations."
This matters because Phase I to Phase II conversion (the OMTM) depends on the
baseline collection burden. A secondary angle -- distributional robustness --
was raised at epic level (BIN-53, BIN-95): LLM judge scores fit normality
poorly (bounded, left-skewed, effectively discretised), and bootstrap methods
are generally attractive because they do not assume normality.

## Decision

**(c) Reject. The method is not applicable to Caliper's problem.**

The paper's bootstrapped MEWMA addresses a fundamentally different statistical
problem from the one Caliper solves. The two contributions do not transfer --
neither together nor independently -- to univariate control-chart calibration
on scalar quality scores.

## Rationale

### Contribution 1 does not apply: Caliper does not monitor Fisher score vectors

The paper monitors Fisher score vectors from a parametric supervised learning
model. These are gradients of the log-likelihood with respect to model
parameters -- a multivariate quantity inherent to the model's parametric
structure.

Caliper monitors a scalar float quality score produced by an LLM judge. There
is no parametric model, no likelihood function, no Fisher information matrix,
and no score vector. The "scores" in Caliper and the "scores" in the paper are
entirely different objects:

| Dimension | Wu & Apley (2026) | Caliper |
|-----------|-------------------|---------|
| What is monitored | Fisher score vectors (gradient of log-likelihood) | Scalar quality scores from an LLM judge |
| Dimensionality | Multivariate (dimension = number of model parameters) | Univariate (single float) |
| Source | Parametric supervised learning model fitted via MLE | LLM-as-a-judge rubric evaluation |
| Chart type | MEWMA with Hotelling T-squared | Univariate EWMA (Lucas & Saccucci 1990) |
| What "drift" means | Change in the predictive relationship of a fitted model | Change in the quality of agent outputs |

### Contribution 2 does not transfer independently: the bootstrap solves a problem Caliper does not have

The nested bootstrap eliminates the need to split training data between model
fitting and control-limit estimation. This is valuable when fitting a
parametric model consumes data that would otherwise determine the control limit.

Caliper's Phase I baseline serves a different role. The baseline observations
ARE the reference data, and control limits are derived analytically from
baseline statistics (mean, variance) via the Markov-chain approximation
(EWMA) or Siegmund's approximation (CUSUM). There is no model-fitting step
that competes for data with control-limit estimation. The "data efficiency"
claim solves a data-splitting problem that does not exist in Caliper's
architecture.

The nested bootstrap fundamentally requires:

1. **A parametric model to refit on each bootstrap sample.** Caliper has no
   parametric model.
2. **Fisher score vectors computed from the refit model.** Caliper has scalar
   scores, not model gradients.
3. **The 0.632 correction** accounting for overlap between bootstrap training
   data and out-of-bag data used for score computation. This correction is
   specific to model-refitting bootstraps and has no analogue in Caliper's
   setting.
4. **A covariance matrix** of the score vectors for the T-squared statistic.
   Caliper's univariate EWMA uses scalar variance.

### The paper's own assumptions exclude Caliper's setting

The paper requires (Assumptions A.1-A.4): correct or near-correct parametric
model specification, parameter identifiability, twice-continuous
differentiability of the likelihood, and finite Fisher information matrix. It
explicitly states the method is "not directly applicable to non-parametric or
tree-based methods like Random Forests or XGBoost, which do not admit a
differentiable likelihood function with respect to fixed parameters."

Caliper's observation sequence -- scalar float scores from an LLM judge -- is
not the output of any parametric model. There is no likelihood to
differentiate.

### The calibration target differs

The paper calibrates against a **pointwise false alarm rate** (marginal Type I
error at each observation). The authors explicitly state: "calculating ARLs via
Monte Carlo simulation for our approach is computationally prohibitive due to
the nested bootstrap required at each time step."

ADR-001 established **ARL_0** (in-control average run length) as Caliper's
calibration target, with published ARL tables as verification fixtures. ARL is
the standard metric in the SPC literature for process monitoring and is what
BIN-84's property-based tests verify against. Switching to a pointwise false
alarm rate would abandon the published-table verification story that backs the
library's "auditable, statistically defensible" claim.

### The distributional robustness angle is real but this paper does not address it

LLM judge scores violate the normality assumption underlying classical ARL
tables (bounded [0,1], left-skewed, effectively discretised by rubric levels).
This is a genuine concern flagged at epic level (BIN-53, BIN-95).

However, this paper does not help. Its bootstrap operates within a parametric
framework -- Assumption A.1 requires correct model specification. The method
assumes the parametric model is right; it does not relax distributional
assumptions about the monitored data.

Bootstrap-based control charts for non-normal data exist in the SPC literature
(e.g., nonparametric bootstrap applied directly to baseline observations to
empirically determine control limits). This is a different research direction
from what Wu & Apley (2026) provide, and it warrants a separate investigation
if the normality violation proves practically significant. See Consequences.

## Alternatives considered

### (a) Adopt: replace classical fitting with the bootstrapped approach

**Rejected.** The method requires a parametric model fitted via MLE, Fisher
score vectors, and a multivariate monitoring statistic. None of these exist in
Caliper's setting. Adoption is not a design choice -- it is a category error.
The paper solves a different problem.

### (b) Defer: implement classical Phase I first, add bootstrapped MEWMA later

**Rejected in favour of (c).** Deferral implies the method might apply once
Caliper matures. It does not. The mismatch is structural (no parametric model,
no Fisher scores, univariate not multivariate), not a matter of implementation
readiness. Framing the outcome as "defer" would leave a misleading open item
on the backlog suggesting future applicability that does not exist.

The one genuine deferral candidate -- bootstrap-based control limits for
non-normal univariate data, a different method from a different literature --
is recorded as a future investigation (see Consequences) but is distinct from
this spike's question.

### (d) Adopt the bootstrap calibration only, without the MEWMA monitoring

**Rejected.** This was the most carefully considered alternative. The nested
bootstrap's contribution is eliminating the training-data split required by
model refitting. Since Caliper does not refit a model (it computes limits
analytically from baseline statistics), the data-split problem does not exist,
and the bootstrap provides no benefit. The 0.632 correction, which is the
paper's main technical novelty, addresses a specific artefact of bootstrap
model-refitting overlap that has no analogue in Caliper's analytical
calibration.

## Consequences

### What does not change (all tickets confirmed unaffected)

- **BIN-65 (EWMA fitting):** Lucas & Saccucci Markov-chain approximation
  stands as specified in ADR-001. No change to the calibration method.
- **BIN-94 (CUSUM fitting):** Siegmund's corrected diffusion approximation
  stands. This spike was EWMA-focused; CUSUM is unaffected regardless.
- **BIN-63 (baseline collection):** Collection requirements unchanged. The
  data-efficiency claim from the paper does not transfer.
- **BIN-84 (property-based tests):** Published ARL tables remain the
  verification backstop. No alternative oracle is introduced.
- **BIN-66 OQ-5 (artefact protocol):** No impact from this spike. The
  artefact's shared core does not gain bootstrap-specific fields (no
  resampling parameters, iteration count, or seed to carry).

### What this implies for BIN-92 (minimum baseline size)

BIN-92 (SP-2, still open) investigates the minimum viable baseline size for
LLM judge scores. This spike was partly motivated by the hope that bootstrapped
calibration would reduce the minimum. **It does not.** The minimum baseline
size must be determined from classical Phase I sample-size considerations in
the SPC literature (e.g., Quesenberry's guidelines, Jones et al. 2001, or
simulation studies specific to EWMA charts with non-normal data). BIN-92 must
resolve independently without relying on this paper's data-efficiency claim.

### New concern surfaced: distributional robustness of ARL tables

This spike surfaced a genuine concern that warrants separate investigation.
Classical EWMA ARL tables (Lucas & Saccucci 1990) assume normally distributed
observations. LLM judge scores are bounded [0,1], left-skewed, and
effectively discretised by rubric levels. The practical impact on ARL accuracy
is unknown.

Two paths forward (neither is in scope for v0.1, but both should be tracked):

1. **Empirical ARL sensitivity study.** Simulate EWMA charts with non-normal
   distributions matching typical LLM judge score profiles. Measure how far
   the achieved in-control ARL deviates from the nominal ARL_0 under the
   normality assumption. If the deviation is within a practical tolerance
   (e.g., +/- 15% of ARL_0), the classical tables are adequate. If not, a
   correction or alternative calibration is needed.

2. **Nonparametric bootstrap control limits.** A different method from Wu &
   Apley -- apply a bootstrap directly to baseline observations to empirically
   determine EWMA control limits without assuming normality. This is
   established in the SPC literature (e.g., Phanyaem et al. 2014; Jones &
   Steiner 2008 on bootstrap-based Shewhart limits). Unlike the paper under
   evaluation, this approach does not require a parametric model. It would
   trade the published-ARL-table verification story for distributional
   robustness -- the same fundamental tradeoff the spike identified, but with
   a method that actually applies.

Both are recorded as potential future work. Neither blocks v0.1, because the
classical methods are the established baseline and the library's initial claim
is correctly scoped: "control limits calibrated to a specified false alarm
rate, verified against published ARL tables." The distributional robustness
question is an enhancement, not a prerequisite.

### Reversibility

**Zero cost to reverse.** This ADR rejects adding a new calibration method;
it does not remove one. The SPCPort interface (ADR-001) remains the extension
point. If a future investigation (path 1 or 2 above) produces a
non-normality-robust calibration method, it would be added as a new adapter
behind SPCPort alongside the classical methods. Nothing in this decision
forecloses that.

### ADR-001 is not amended

ADR-001's calibration section (Lucas & Saccucci for EWMA, Siegmund for CUSUM,
direct tail probability for Shewhart) stands unchanged. This ADR adds context
(a rejected alternative) but does not modify any existing decision.

## Related decisions

- **ADR-001 (SPC engine in-house with scipy):** Established the calibration
  methods this spike evaluated alternatives to. Confirmed unchanged.
- **BIN-92 (SP-2, minimum baseline size):** Must resolve independently. This
  spike does not deliver a data-efficiency improvement.
- **BIN-95 (Shewhart I-chart fitting):** Flagged the normality concern at
  epic level. The distributional robustness investigation noted above applies
  to Shewhart limits as well.
- **BIN-53 (epic: Establish a Trusted Baseline):** The distributional
  robustness concern was raised here. This ADR surfaces it explicitly and
  records the two investigation paths.

## Verified claims about the paper

| Claim | Status |
|-------|--------|
| Title: "Bootstrapped Control Limits for Score-Based Concept Drift Control Charts" | Verified at arxiv.org |
| Authors: Jiezhong Wu and Daniel W. Apley | Verified |
| Dates: v1 22 July 2025; v3 21 March 2026 | Verified |
| Published in *Technometrics* 2026 | Verified (DOI: 10.1080/00401706.2026.2676855) |
| Monitors Fisher score vectors via MEWMA | Verified |
| Novel nested bootstrap for control-limit calibration | Verified |
| Requires parametric model fitted via MLE | Verified -- paper states it explicitly |
| Calibrates against pointwise false alarm rate, not ARL | Verified -- paper states ARL computation is "prohibitive" |
| Not applicable to non-parametric methods | Verified -- paper states this explicitly |
| No univariate special case discussed | Verified -- paper is entirely multivariate |

| Claim | Could not verify from abstract/HTML |
|-------|--------------------------------------|
| Exact Assumptions A.2 and A.3 text | Deferred to appendix, not fully rendered in HTML |
| Simulation sample sizes beyond the n=2000 example | Appendix D not fully accessible |
