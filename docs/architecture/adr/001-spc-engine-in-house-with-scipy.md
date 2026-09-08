# ADR-001: SPC engine implemented in-house with scipy as numerical foundation

**Status:** Accepted
**Date:** 2026-09-08
**Deciders:** system-architect (BIN-91), ratified by product owner
**Refs:** BIN-91, BIN-65, BIN-84, BIN-59

## Context

Caliper's core value proposition is "statistically defensible drift detection with
auditable control limits." The library applies Statistical Process Control (SPC)
to LLM-as-a-judge quality scores, using EWMA, CUSUM, and Shewhart I-chart
control charts with Phase I baseline fitting and Phase II monitoring.

The SPC engine is the computational layer that:

1. Fits control limits from Phase I baseline data with a specified in-control
   Average Run Length (ARL_0) -- i.e. a known false alarm rate.
2. Updates chart statistics for each Phase II observation and signals when the
   process goes out of control.
3. Provides the ARL calibration that distinguishes Caliper from every existing
   tool (verified: no competitor applies formal SPC with calibrated ARL to
   LLM-judge scores -- see `Projects/caliper/market-analysis.md`).

The decomposition (BIN-51) established the SPC engine as a swappable adapter
behind a port, deferring the build-vs-adopt decision to this spike. Three options
were framed:

- **(a) In-house** -- implement EWMA, CUSUM, and Shewhart charts with ARL
  calibration from first principles, using scipy for numerical computation.
- **(b) Layer over Frouros** -- wrap Frouros's drift detection algorithms behind
  Caliper's API, adding LLM-aware Phase I/II methodology on top.
- **(c) Hybrid** -- own ARL calibration, borrow detection primitives from Frouros.

This spike also resolves the score type question (BIN-59 OQ-1), which is
load-bearing for control limit mathematics.

### Sentry context

Not applicable. Caliper is a library with no runtime to monitor.

## Decision

**(a) In-house implementation, with scipy as the numerical foundation.**

The SPC engine is implemented from first principles behind the `SPCPort`
interface. The numerical substrate is `scipy` (for distributions, numerical
integration) and `numpy` (for array operations). Published ARL tables from the
SPC literature serve as test oracle fixtures for property-based tests (BIN-84).

### Score type resolution (BIN-59 OQ-1)

The canonical score type is **`float`**. EWMA, CUSUM, and Shewhart I-chart all
operate on continuous numeric values natively. Integer scores would reduce
statistical power (fewer distinct values). Binary (pass/fail) scores require a
fundamentally different chart type (p-chart, deferred to R2). Float scores in a
bounded range (the range itself is BIN-59 OQ-2, still open) are the natural
representation for LLM-as-a-judge rubric scores.

## Rationale

### Frouros does not provide what Caliper needs

Verified against Frouros source code on `main` branch at
`IFCA-Advanced-Computing/frouros` (GitHub, 2026-09-08):

**1. CUSUM has no ARL calibration.**
The CUSUM detector (`change_detection/cusum.py`) uses a hand-set threshold
`lambda_ = 50.0` with no stated statistical meaning. The `_update_sum` method
implements the one-sided upper CUSUM recursion:

```python
self.sum_ = np.maximum(0, self.sum_ + error_rate - self.mean_error_rate.mean - self.config.delta)
```

There is no ARL parameter, no false alarm rate, and no procedure for deriving
the threshold from a target run length. Drift is declared when `sum_ > lambda_`.
This is the CUSUM *recursion*, not CUSUM *design*.

**2. ECDD has limited ARL-aware calibration, but only for binary error streams.**
The ECDD detector (`statistical_process_control/ecdd.py`) does accept an
`average_run_length` parameter, but it is constrained to exactly three discrete
values (100, 400, or 1000) mapped to pre-fitted polynomial approximations from
Ross et al. (2012). These polynomials take the error rate `p` as input --
designed for binary classification error streams (0 if correct, 1 if error), not
continuous judge scores in [0, 1]. The control limit is computed as:

```python
average_run_length_map = {
    100: lambda p: 2.76 - 6.23*p + 18.12*p**3 - 312.45*p**5 + 1002.18*p**7,
    400: lambda p: 3.97 - 6.56*p + 48.73*p**3 - 330.13*p**5 + 848.18*p**7,
    1000: lambda p: 1.17 + 7.56*p - 21.24*p**3 + 112.12*p**5 - 987.23*p**7,
}
```

This is a different statistical framework from what Caliper requires (continuous-
score EWMA/CUSUM with arbitrary ARL_0 specification).

**3. DDM/EDDM/HDDM/RDDM use hand-set sigma multipliers.**
DDM defaults to `warning_level=2.0`, `drift_level=3.0` -- standard-deviation
multipliers with no ARL calibration. These are conceptually similar to a
Shewhart chart with 2-sigma warning and 3-sigma control limits, but applied to
error-rate standard deviations without formal Phase I/Phase II methodology.

**4. Detectors are framed around classifier error streams.**
All Frouros streaming detectors expect a sequence of error indicators or error
rates from a classifier. The API (`update(value)`) and internal naming
(`error_rate`, `mean_error_rate`) reflect this framing. Caliper's inputs are
continuous quality scores from LLM judges, not classification errors.

**5. The CUSUM is one-sided upper only.**
Quality monitoring needs to detect both upward drift (degradation on a
higher-is-better score) and downward drift (degradation on a lower-is-better
score, or improvement that invalidates control limits). The standard approach
is two one-sided CUSUMs. Frouros provides only the upper CUSUM.

**6. Practical adoption barriers.**
- Latest PyPI release: 0.9.0 (2024-10-05) -- nearly two years stale.
- Released Python support: `<3.13` -- conflicts with BIN-83 (test on 3.13).
- Dependency upper bounds: `numpy<2.2`, `scipy<1.15` -- current releases are
  numpy 2.5.3 and scipy 1.18.1, so Frouros 0.9.0 is incompatible with current
  scipy. These caps propagate to Caliper's consumers.
- Python 3.13 support exists on `main` but is unreleased. Adopting means
  depending on an unreleased git ref.

### The hybrid option collapses into in-house

Option (c) was defined as "own the calibration, borrow the detection
primitives." But the detection primitives -- the EWMA recursion, the CUSUM
recursion, the Shewhart limit comparison -- are each 3-5 lines of arithmetic.
The hard part is ARL calibration, which is exactly what Frouros does not
provide (except in the limited ECDD case for binary streams). Borrowing the
trivial part while building the hard part yields no meaningful reduction in
implementation effort and adds a dependency with the adoption barriers listed
above.

### What is actually adopted: scipy + published ARL tables

The real "adopt" axis is not Frouros but the numerical and statistical
infrastructure the implementation rests on:

- **numpy** -- array operations, the EWMA/CUSUM recursions.
- **scipy.stats** -- normal distribution functions for Shewhart chart limits,
  numerical integration for ARL computation where closed-form approximations
  are insufficient.
- **Published ARL tables** -- test oracle fixtures from the SPC literature,
  enabling BIN-84 to verify that Caliper's ARL computations match decades of
  published results.

### ARL calibration approach (per chart type)

The following calibration methods are standard in the SPC literature. Specific
constants and formulas must be verified from primary sources at implementation
time -- they are not pinned from recall here.

**CUSUM:** Siegmund (1985), *Sequential Analysis: Tests and Confidence Intervals*,
provides corrected diffusion approximations for one-sided CUSUM ARL under the
exponential family (Theorem 10.16). Given a target in-control ARL_0, this
approximation yields the decision interval *h*. For two-sided monitoring, two
one-sided CUSUMs are run simultaneously (upper for degradation, lower for
improvement); the two-sided ARL is approximated from the one-sided ARLs.

**EWMA:** Lucas & Saccucci (1990), "Exponentially weighted moving average
control schemes: Properties and enhancements," *Technometrics* 32(1):1-12,
developed a Markov-chain approximation for EWMA ARL. The EWMA statistic region
between control limits is discretized into states; the expected number of steps
to absorption is computed as a matrix operation. The companion paper Saccucci &
Lucas (1990), "Average run lengths for EWMA control schemes using the Markov
chain approach," *Journal of Quality Technology* 22(2):154-162, provides the
computational procedure and published ARL tables. Given a smoothing parameter
lambda and a target ARL_0, the control limit factor *L* (number of sigma-
equivalents for the EWMA control limits) is determined from these tables or
computed via the Markov-chain method.

**Shewhart I-chart:** Control limits are mean +/- k * sigma_hat, where sigma_hat
is estimated from the moving range (MR) divided by the unbiasing constant d_2.
For individual observations with a moving range of span 2, d_2 is a tabulated
constant from the SPC literature (available in Montgomery, *Introduction to
Statistical Quality Control*, and every quality engineering reference). The
relationship between k and ARL_0 is direct for normally-distributed observations
(ARL_0 = 1 / alpha where alpha is the tail probability beyond +/- k sigma). The
standard choice is k=3, yielding ARL_0 ~= 370. The exact d_2 value must be
taken from a primary source at implementation time.

### Verification note

The named methods (Siegmund's approximation, Lucas & Saccucci's Markov-chain
method) and every constant (d_2, specific h values for target ARLs, ARL table
entries) must be verified from primary sources during implementation of BIN-65
and BIN-84. This ADR establishes the approach and cites the methods; it does
not pin specific numerical values. Statistical correctness is the product -- an
incorrect constant silently invalidates every claim the library makes.

## Alternatives considered

### (b) Layer Caliper's API over Frouros

**Rejected.** Would buy approximately 5 lines of CUSUM recursion arithmetic
while inheriting: no ARL calibration on CUSUM, ARL calibration limited to three
fixed values on binary streams for ECDD, a two-year-old release, Python <3.13
cap, numpy/scipy upper bounds incompatible with current releases, and a
dependency whose framing (classifier error streams) does not match Caliper's
domain (continuous judge scores). Caliper's central claim -- "calibrated false
alarm rates, auditable control limits" -- would rest on a library that does not
make that claim.

### (c) Hybrid: own calibration, borrow detection primitives from Frouros

**Rejected -- collapses into (a).** The detection primitives (EWMA recursion,
CUSUM recursion) are 3-5 lines each and trivial to implement correctly. The
hard part -- ARL calibration -- is what Frouros does not provide for continuous
scores. Borrowing only the trivial part adds a dependency with significant
adoption barriers for no meaningful reduction in implementation effort.

### (d) Use statprocon, pyspc, or spc-lib

**Evaluated and rejected.** `statprocon` 2.0.0 implements XmR (individuals and
moving range) charts -- Shewhart-style only, no EWMA or CUSUM, no ARL
calibration. `pyspc` 0.4 and `spc-lib` 1.1.2 are basic charting libraries
without ARL calibration. None provide the statistical design capability Caliper
requires.

### (e) Use statsmodels CUSUM

**Evaluated and rejected.** `statsmodels` 0.15.0 includes a CUSUM test in
`recursive_ls` for structural breaks in regression residuals -- a different
statistical procedure from the CUSUM control chart. It does not implement EWMA
charts or provide ARL calibration for process control.

### (f) Vendor Frouros code

**Rejected.** Vendoring would copy the CUSUM recursion (the only potentially
relevant code) into Caliper's codebase. Since the recursion is trivial and the
ARL calibration must be written from scratch regardless, vendoring provides no
advantage over implementing from first principles and adds licence-tracking
overhead.

## Consequences

### Positive

- **Full control over ARL calibration** -- the differentiating capability is
  implemented and tested entirely within the project.
- **No dependency adoption barriers** -- no Python version caps, no numpy/scipy
  upper bounds beyond what Caliper's own code requires.
- **Published ARL tables as test fixtures** -- BIN-84's property-based tests
  can verify computed ARLs against decades of published tabulated values,
  providing a verification standard that no wrapper around Frouros could match
  (Frouros has no ARL to verify against on CUSUM).
- **Continuous-score native** -- charts are designed for float scores from the
  start, not adapted from binary error-stream detectors.
- **Two-sided CUSUM** -- both upward and downward drift detection, standard for
  quality monitoring.

### Negative

- **Implementation effort** -- the ARL calibration methods (Siegmund's
  approximation for CUSUM, Lucas & Saccucci's Markov-chain for EWMA) must be
  implemented and tested. This is genuine complexity -- estimated as the
  majority of BIN-65's size-L effort.
- **Statistical verification burden** -- every formula must be verified against
  primary sources. No shortcut exists; this is intrinsic to the product's claim.

### Neutral

- **scipy and numpy become runtime dependencies.** These are already expected
  for any numerical Python library. Current versions: scipy 1.18.1
  (requires Python >=3.12), numpy 2.5.3 (requires Python >=3.12). Caliper
  targets Python 3.11/3.12/3.13 (BIN-83), so dependency lower bounds must
  accommodate 3.11-compatible scipy/numpy releases. Exact version pins to be
  determined at implementation time from live registry data.

### Reversibility

**Low cost to reverse.** The SPC engine sits behind a port interface. Adding a
Frouros-backed adapter later would require one adapter class per chart type,
mapping Caliper's `fit()` / `update()` / `check()` interface to Frouros's
`update(value)` API. The in-house implementation is the first adapter, not the
only possible one. The port contract is established in the domain model (the
domain-modeller agent's next output); this ADR does not remove or weaken it.

## Related decisions

- **BIN-59 OQ-1 (score type):** Resolved as `float`. Recorded here; BIN-59
  updated with the outcome.
- **BIN-59 OQ-2 (score range):** Still open. The maths works on any bounded
  continuous range; [0, 1] is the natural choice for normalized rubric scores
  but the range constraint is separable from the score type.
- **BIN-84 (property-based tests):** Test strategy updated -- published ARL
  tables become primary test oracle fixtures. Tests verify that Caliper's
  computed ARL values match published tables within a stated tolerance.
- **Error-contract inconsistency across E1 feature files:** Not addressed here.
  Queued for a separate ADR.
- **Judge-refusal taxonomy (BIN-59 m2):** Not addressed here.
