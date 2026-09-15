# Choosing a chart

Three charts are implemented. They differ in **what kind of change they are good
at noticing**, and the choice matters more than any parameter you will tune
afterwards.

**If you do not want to think about it, use EWMA.** It is the right default for
LLM quality monitoring and the rest of this page explains why.

---

## The short answer

| Chart | Notices | Misses | Fit with |
|---|---|---|---|
| **EWMA** | small, gradual drift | nothing important for this use case | `fit_ewma` |
| **CUSUM** | a sustained shift of a size you name in advance | shifts much larger or smaller than the one you tuned for | `fit_cusum` |
| **Shewhart I** | one large, obvious outlier | slow drift, almost entirely | `fit_shewhart` |

All three take the same first two arguments and all three are calibrated to the
ARL₀ you request:

```python
fit_ewma(baseline, target_arl=370.0)
fit_cusum(baseline, target_arl=370.0)
fit_shewhart(baseline, target_arl=370.0)
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

## Binary pass/fail rubrics are not supported

If your judge returns pass/fail rather than a score, none of these three charts
is appropriate, and Caliper does not offer one.

A p-chart was evaluated and **rejected**. The reason is worth stating because it
is the kind of thing a library could easily have got wrong quietly: for binary
data the control limits are integer counts, so the achievable ARL₀ values are
**discrete**. You cannot calibrate one to 370 — you get whichever value the
nearest integer limit happens to give, which might be 250 or 800.

A randomised signalling rule *can* hit 370 exactly, and was considered. It was
rejected because it makes the chart non-deterministic: the same data could
signal on one run and not the next, which is unacceptable for a library whose
claim is auditability.

The honest answer for pass/fail data is to aggregate into **non-overlapping
batches** and monitor the batch pass rate as a continuous score. Watch the
independence assumption above, and note that the normal approximation needs both
`n·p > 5` and `n·(1−p) > 5` — with a batch of 20, the second condition excludes
pass rates above 0.75, which is to say it excludes the well-behaved agent.

See [ADR-001](architecture/adr/001-spc-engine-in-house-with-scipy.md) for the
full evaluation and what a Bernoulli CUSUM would offer instead.

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
