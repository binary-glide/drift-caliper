# Choosing a chart

Four charts are implemented: three for continuous scores, and one for pass/fail
rubrics. The continuous ones differ in **what kind of change they are good at
noticing**, and the choice matters more than any parameter you will tune
afterwards.

**If you do not want to think about it, use EWMA.** It is the right default for
LLM quality monitoring and the rest of this page explains why. If your judge
returns pass/fail, see [Binary pass/fail rubrics](#binary-passfail-rubrics).

---

## The short answer

| Chart | Notices | Misses | Fit with |
|---|---|---|---|
| **EWMA** | small, gradual drift | nothing important for this use case | `fit_ewma` |
| **CUSUM** | a sustained shift of a size you name in advance | shifts much larger or smaller than the one you tuned for | `fit_cusum` |
| **Shewhart I** | one large, obvious outlier | slow drift, almost entirely | `fit_shewhart` |
| **Bernoulli CUSUM** | a change in a pass/fail failure rate | nothing, if the baseline has enough failures — see below | `fit_bernoulli_cusum` |

All four take the same first two arguments and all four are calibrated to the
ARL₀ you request:

```python
fit_ewma(baseline, target_arl=370.0)
fit_cusum(baseline, target_arl=370.0)
fit_shewhart(baseline, target_arl=370.0)
fit_bernoulli_cusum(baseline, target_arl=370.0)  # scores exactly 0.0 or 1.0
```

## Why EWMA is the default

Agent quality degrades **gradually**. A model is deprecated and silently
substituted, a prompt is edited, the population of user requests shifts, a
retrieval index goes stale. Scores slide by a fraction of their normal spread
over weeks.

EWMA carries memory: each point is a weighted average of the current observation
and everything before it. A small persistent shift accumulates across many
observations until it becomes visible, even though no single observation was
unusual enough to notice.

```python
fitted = fit_ewma(baseline, target_arl=370.0)

print(fitted.smoothing_param)      # 0.2
print(fitted.calibration_method)   # markov_chain
```

`smoothing_param` (λ) is how much weight the newest observation gets. Smaller
values remember further back and detect smaller shifts more slowly; larger
values react faster and notice only bigger ones. **0.2 is the field's
conventional choice** and the default here.

!!! warning "A fixed λ is tuned for one shift size, and you choose it before you know"

    An EWMA at λ = 0.2 is efficient over roughly a 0.75σ–1.25σ shift. Outside
    that band it is noticeably worse than a chart tuned for the shift you
    actually got — and you must pick λ before knowing whether you face an abrupt
    model swap or a slow slide.

    This is a genuine limitation of the method rather than of this
    implementation. Adaptive EWMA variants address it by varying λ with the
    observed deviation; none is implemented here.

## When CUSUM instead

CUSUM accumulates deviations from the target and signals when the running total
exceeds a decision interval. It is **optimal for detecting a shift of a
particular size** — and you have to name that size up front.

```python
fitted = fit_cusum(baseline, target_arl=370.0)

print(fitted.reference_value)     # 0.5  -- k, in sigma units
print(fitted.decision_interval)   # 4.766 -- h, solved for your target_arl
print(fitted.direction)           # two_sided
print(fitted.calibration_method)  # siegmund_approximation
```

`reference_value` (k) is **half the shift you want to detect, in standard
deviations**. The default of 0.5 targets a 1σ shift, which is the standard
choice.

Reach for CUSUM when you can state the shift that matters: *"a drop of half a
point on a 10-point scale is what I care about, anything smaller is not worth
paging anyone."* Then set `k` to half that, expressed in sigma.

### One-sided monitoring

Scores are **higher-is-better**, so degradation is the lower side. If a rise in
scores is not interesting — or not plausible — you can watch one direction only:

```python
fit_cusum(baseline, target_arl=370.0, direction="lower")
```

Valid values are `"two_sided"` (the default), `"lower"` and `"upper"`. A
one-sided chart spends its whole false alarm budget on the direction you care
about, so it detects a fall faster at the same ARL₀.

!!! warning "Not every ARL₀ is attainable at every reference value"

    At large `k`, no decision interval produces a low ARL₀ — the lowest
    attainable at `k = 5.0` two-sided is above 1158. Ask for less and Caliper
    raises `InvalidParameterError` reporting `min_attainable_arl`, rather than
    returning a chart that cannot deliver what its own artefact claims.

    The reported value round-trips: passing it straight back is accepted.

## When Shewhart instead

The Shewhart individuals chart tests **each observation on its own**, with no
memory. It signals when a single point falls outside the limits.

```python
fitted = fit_shewhart(baseline, target_arl=370.0)

print(fitted.sigma_multiplier)          # 2.9997
print(fitted.sigma_estimation_method)   # moving_range
print(fitted.calibration_method)        # tail_probability
```

Note the multiplier: calibrating to ARL₀ = 370 recovers **almost exactly 3
sigma**, which is the classical rule arrived at from the other direction.

Shewhart is the right choice for catching an agent that has broken outright —
started returning empty output, hit a safety filter, lost its retrieval context.
It is a poor choice for drift: a memoryless chart cannot accumulate evidence, so
a half-sigma slide can continue indefinitely without any single point ever
crossing a limit.

??? note "Why sigma comes from the moving range, not the standard deviation"

    For individual observations, Caliper estimates spread from the **average moving
    range** — the mean absolute difference between consecutive observations —
    divided by `d₂ = 1.128`.[^d2]

    The ordinary sample standard deviation would be wrong here, and in a specific
    direction. It measures *total* variation, which includes any drift already
    present in the baseline. Using it would inflate the spread estimate, widen the
    limits, and make the chart less able to detect the very thing it is for.

    The moving range only sees **consecutive** differences, so a slow trend across
    the baseline barely affects it. This is short-term variation, which is what
    control limits should be built from.

    ⚠️ It assumes consecutive observations are independent. If you feed Caliper a
    *rolling* average, that assumption is badly violated — use non-overlapping
    batches instead.

## Binary pass/fail rubrics

If your judge returns pass/fail rather than a score, use the **Bernoulli CUSUM**:
`fit_bernoulli_cusum`. None of the three continuous charts is appropriate for
binary data, and you do not need to batch judgements to use it.

**Record each judgement as a score of exactly `1.0` (pass) or `0.0` (fail).**
There is no separate "binary" setting: a baseline whose every score is `0.0` or
`1.0` is the binary case. A `bool` score is refused with `InvalidParameterError`
rather than guessed at, and a baseline containing any other value — even a legal
continuous one — is refused by `fit_bernoulli_cusum`. In Phase II, `Monitor`
refuses a score that is not exactly `0.0` or `1.0` with
`InvalidObservationError` (`context["reason"] == "score_not_binary"`).

Each judgement is one observation, so the 100-observation Phase I minimum means
100 judgements, not 100 batches.

### What you get

- **Two-sided by default.** The lower arm watches for a rising failure rate —
  degradation. The upper arm watches for a falling one, which usually means the
  baseline no longer describes the agent. Pass `direction="lower"` or
  `direction="upper"` to check one arm only; the fitted artefact carries only the
  arms it checks.
- **An exact ARL₀.** A pass/fail statistic moves in fixed steps, so the chart is a
  finite Markov chain and its in-control ARL₀ is solved exactly, not
  approximated. `achieved_arl` is that exact figure, never below the
  `target_arl` you requested.
- **Designed at a confidence bound, not the observed rate.** A small baseline's
  observed failure rate can be low by chance, and a chart designed on it would
  alarm more often than it promises. Each arm is designed at the one-sided
  Clopper–Pearson bound on the side that is conservative for it (`p_u` for the
  lower arm, `p_l` for the upper, each at 90% confidence). For a one-sided
  chart, the true ARL₀ is then at least `achieved_arl` with at least 90%
  confidence. For the two-sided chart, `achieved_arl` is a floor on the true
  ARL₀ at every failure rate between the two bounds.
- **`detect_rate_multiple`, default `2.0`,** is the shift the chart is tuned for:
  a multiple of the failure rate, not of a standard deviation. It must be finite
  and greater than 1.

!!! note "Why `achieved_arl` can sit well above your target"

    A pass/fail chart cannot hit every ARL₀: its decision interval moves in whole
    lattice steps, so you get the smallest one that meets your target. On a
    baseline with very few failures there is also a floor. When one failure is
    enough to signal, the in-control ARL₀ is just the mean wait for one failure,
    `1/p_u`, whatever you asked for. Caliper fits that chart rather than
    refusing it, and says so with a `lower_arm_signals_on_first_failure`
    advisory whose `boundary` is that floor.

### The advisories you may see

The fitted artefact's `advisories` are disclosures, not errors — the chart is
valid in every case. Each has a `kind`, a `description` and a `boundary`.

| `kind` | means | `boundary` |
|---|---|---|
| `lower_arm_signals_on_first_failure` | every single failure signals, so `achieved_arl` is `1/p_u` | that ARL₀ |
| `detection_shift_within_design_rate` | `expected_detection_arl` is `None`: see below | the multiple above which it is reported |
| `improvement_shift_within_design_rate` | the improvement figure is `None`: see below | the multiple above which it is reported |
| `upper_arm_not_designable` | a two-sided request met a baseline with no failures, so only the lower arm was built and `direction` is reported as `"lower"` | `1.0` |

⚠️ **With few failures in the baseline, the detection figures are `None`.**
`expected_detection_arl` says how quickly the chart would catch the failure rate
multiplied by `detect_rate_multiple`; `expected_improvement_detection_arl` does
the same for an improvement. When the baseline has few failures, the confidence
bound sits far above the observed rate. A doubled rate is then still one the chart
is designed to tolerate, and it would take at least as long to signal as a false
alarm. So the figure is reported as `None` rather than as a large number that
describes no detection at all.

The ratio depends on the **number** of failures, not on the size of the baseline.
At the default multiple of 2:

- three or fewer failures leaves both figures `None`;
- four or five leaves only the improvement figure `None`;
- six or more reports both.

The advisory's `boundary` is the multiple strictly above which the figure would
be reported. The remedy is more failures in the baseline, or a larger
`detect_rate_multiple`. A larger multiple also changes the shift the chart is
tuned for, so it is a design choice, not a fix.

`direction="upper"` is refused on a baseline with no failures: there is no
failure rate for an improvement to fall from.

### What is not built, and what was rejected

**The Bernoulli EWMA is not built.** The Bernoulli CUSUM is the only chart for
pass/fail data today.

A **p-chart** was evaluated and **rejected**. For binary data its control limits
are integer counts, so the achievable ARL₀ values are **discrete**. You cannot
calibrate one to 370: you get whichever value the nearest integer limit happens
to give, which might be 250 or 800. A randomised signalling rule *can* hit 370
exactly, and was considered. It was rejected because it makes the chart
non-deterministic: the same data could signal on one run and not the next, which
is unacceptable for a library whose claim is auditability.

The Bernoulli CUSUM avoids this because its lever, `detect_rate_multiple`, is
the library's to design around, whereas the p-chart's lever is the batch size,
which is your data rate.

⚠️ **Do not batch pass/fail judgements into a pass rate** and monitor it on a
continuous chart. It is no longer needed, and a *rolling* pass rate would also
break the independence the continuous charts' spread estimate assumes.

See [ADR-001](architecture/adr/001-spc-engine-in-house-with-scipy.md) for the
p-chart evaluation, and
[ADR-014](architecture/adr/014-bernoulli-cusum-api-surface-and-fitted-artefact-shape.md)
for the Bernoulli CUSUM's design.

## Can I run more than one?

Yes. The charts are independent — a fitted artefact is an immutable value, and
`Monitor` holds one.

```python
ewma_monitor = Monitor(fit_ewma(baseline, target_arl=370.0), receivers=[alert])
shewhart_monitor = Monitor(fit_shewhart(baseline, target_arl=370.0), receivers=[alert])

for output in live_outputs:
    result = judge.score(output)
    ewma_monitor.record(result)
    shewhart_monitor.record(result)
```

!!! warning "Two charts at ARL₀ = 370 do not give you ARL₀ = 370"

    Running both roughly **halves** the combined time between false alarms,
    because either chart can raise one. If you want an overall ARL₀ of 370
    across two charts, each needs a target closer to 740.

    Caliper does not manage this for you — it has no view of how many charts you
    have running, and inventing one would mean the artefacts stopped being
    independent values.

[^d2]:
    Montgomery, D.C. *Introduction to Statistical Quality Control*, 7th ed.,
    Wiley 2013, §6.4 and Appendix VI. The exact value is $d_2 = 2/\sqrt{\pi}
    \approx 1.1284$ for subgroups of size two, which is what a moving range of
    consecutive individual observations is.
