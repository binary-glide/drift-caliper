# What the numbers mean

No Statistical Process Control background is assumed. This page explains the
four ideas Caliper's API is built on, and is honest about what each number does
and does not promise.

---

## The problem, before any statistics

You are judging your agent's outputs and getting scores. Today's average is 7.6;
last week's was 8.1.

**Has quality dropped, or is this a normal wobble?**

You cannot answer that from the two averages, because you do not know how much
this measurement bounces around on its own. If scores routinely swing between
7.4 and 8.6 when nothing is wrong, 7.6 is unremarkable. If they normally sit
between 7.9 and 8.3, it is alarming.

A threshold — *"alert me below 7.5"* — does not answer it either. It encodes a
guess about that variation without stating what the guess is or how often it
will be wrong.

**Statistical Process Control answers it by measuring the variation first, then
deciding what counts as unusual relative to it.** That is the whole idea; the
rest is arithmetic.

## 1. ARL₀ — the number you actually choose

**ARL₀ is how long you go between false alarms while nothing is wrong.**

`target_arl=370` means: while the process is behaving normally, expect the chart
to cry wolf about **once every 370 observations**.

That is the one parameter you have to pick, and it is a *business* decision, not
a statistical one. It is the answer to "how much noise can my on-call rotation
absorb?"

| `target_arl` | A false alarm roughly every | Suits |
|---|---|---|
| 200 | 200 observations | You would rather investigate than miss something |
| **370** | **370 observations** | The field's conventional default |
| 500 | 500 observations | Alert fatigue is the bigger risk |
| 1000 | 1000 observations | Only large, unambiguous changes are worth waking someone |

!!! warning "Why 370 rather than a round number"

    370 is not arbitrary and it is not chosen for tidiness. A classical Shewhart
    chart with limits at ±3 standard deviations has a false alarm probability of
    0.0027 per observation under normality, and `1 / 0.0027 ≈ 370`.

    So 370 is what the textbook "3-sigma rule" has *always* meant, stated as the
    quantity you actually care about. Caliper takes it as the input rather than
    the by-product, which is the only real difference.

**Say it as a rate, not a percentage.** "About one false alarm every 370
observations" is both easier and more accurate than "a 0.27% false alarm rate" —
the latter invites the reading that any individual observation has a 0.27%
chance of *being wrong*, which is not what it means.

### What `achieved_arl` is telling you

Every fitted artefact reports both numbers:

```python
fitted = fit_ewma(baseline, target_arl=370.0)
print(fitted.requested_arl)   # 370.0 -- what you asked for
print(fitted.achieved_arl)    # 370.0 -- what the calibration delivered
```

They differ when a chart cannot hit your request exactly. CUSUM in particular
has a floor: at some reference values no decision interval achieves a low ARL₀,
and Caliper refuses rather than silently returning something unattainable.

!!! danger "`achieved_arl` is a zero-state figure, and that is a real caveat"

    It describes **the first run** — how long until the first false alarm,
    starting from a freshly reset chart. `Monitor.record()` runs continuously,
    and the *steady-state* ARL of a continuously-running chart is generally
    **lower** than its zero-state value.

    So `achieved_arl` most likely **overstates** how quiet your chart will be.

    Zero-state is the convention every published table Caliper verifies against
    uses — Lucas & Saccucci state theirs are "based on zero-state in-control
    ARL = 500" — so reporting it is what makes the numbers checkable. **The
    direction of the discrepancy is known; its size has not been computed for
    this library, and will not be guessed at here.**

## 2. Phase I and Phase II

SPC splits monitoring into two jobs that are easy to conflate and must not be.

```text
  Phase I  -- learning        Phase II -- watching
  ────────────────────        ────────────────────
  What does normal            Is THIS observation
  look like?                  consistent with normal?

  Baseline.record()           Monitor.record()
  fit_ewma / fit_cusum /      returns MonitoringResult
  fit_shewhart                every time
        │                            │
        └──── fitted artefact ───────┘
```

**Phase I** is retrospective. You collect scores from a period when the agent
was behaving acceptably, and estimate two things from them: the centre, and the
spread. That is what `fit_*` does, and it returns a **fitted artefact** carrying
those estimates plus the limits derived from them.

**Phase II** is prospective. Each new observation is tested against those fixed
limits.

!!! warning "The limits must not move as new data arrives"

    It is tempting to recompute limits continuously so they stay current. That
    destroys the method: a chart whose limits follow the data will quietly
    re-centre on a degraded process and report that everything is fine.

    Gradual degradation is precisely the failure this library exists to catch,
    and it is exactly the one a self-updating limit cannot see.

## 3. How much baseline do I actually need?

**The library refuses below 100 observations** and fits above it.

```python
fit_ewma(baseline, target_arl=370.0)
# InsufficientBaselineError: context {"have": 50, "need": 100}
```

**100 is a compromise, and it is worth knowing which way it leans.** Estimating
the centre and the spread from a finite sample introduces error, and that error
makes the delivered false alarm rate worse than the one you requested. More
baseline means less error.

| Baseline size | What to expect |
|---|---|
| under 100 | Refused |
| 100–300 | Fits. Delivers a **worse** ARL₀ than requested; how much worse is not currently reported |
| 300+ | Approaching the point where estimation error stops dominating |
| 500+ | Estimation error small, but never zero |

Quesenberry (1993) found around **300 individual observations** are needed
before the run-length distribution behaves as though the parameters were
known.[^q] The default of 100 is set deliberately below that: requiring 300
judged outputs before an engineer can fit anything is a materially larger
adoption barrier, and a chart fitted from 100 is far better than no chart.

??? note "Why the familiar '20-25 observations' figure does not apply"

    Standard SPC texts recommend 20–25 for establishing limits. That figure refers
    to **subgroups of size 3–5**, so it is 100–125 individual data points — and
    more importantly it describes a setting where each plotted point is the *average*
    of a subgroup, which shrinks its variance.

    Caliper monitors **individual** scores. There is no within-subgroup averaging,
    which is the setting where estimation error hurts most. Carrying the 20–25
    figure across is a factual error, and it appeared in this project's own early
    notes before being corrected.

!!! danger "Open work, stated rather than hidden"

    The middle tier of the table above is **a decision that is not yet
    implemented**. A fit from 120 observations currently emits no advisory at
    all — it simply succeeds and says nothing.

    The thresholds themselves were established by simulation over a 60-cell
    grid rather than derived, against a ratified risk criterion (at most 5% of
    baselines may deliver under half the requested ARL₀). Confirming them
    against Jones, Champ & Rigdon (2001) is outstanding, and there is a known
    reason to expect the current numbers are **too low**: that paper's figures
    are for subgroups of five using the most efficient estimator of spread,
    while Caliper uses individuals and the least efficient one.

    Do not read the absence of an advisory at 120 observations as a statement
    that 120 is fine.

## 4. Provenance — why the judge is pinned

A control limit is a statement about **one specific judge applying one specific
rubric**. Change either, and the limits describe an instrument you are no longer
using.

Every `ScoringResult` carries a `Provenance` recording both, and every fitted
artefact carries the provenance of the baseline it came from. If they disagree,
Caliper raises:

```python
from drift_caliper import ProvenanceMismatchError, compare_provenance

try:
    compare_provenance(result, fitted)
except ProvenanceMismatchError as e:
    print(e.mismatches)
    # {"model_version": {"expected": "claude-sonnet-5-20260115",
    #                    "received": "claude-sonnet-5-20260420"}}
```

Comparison is **exact string equality** — no whitespace stripping, no case
folding, no Unicode normalisation. Any normalisation rule would be a guess about
what does not matter semantically in *your* rubric, and Caliper cannot know
that. If you want insensitivity, normalise before you pass the value in.

!!! danger "A reflowed rubric invalidates a baseline, and there is no override"

    This is a real cost and it compounds: recovering means collecting a new
    Phase I baseline at the full 100-observation minimum.

    There is deliberately no `force=` or `acknowledge=` parameter. Knowing the
    instrument changed does not make old-instrument measurements comparable to
    new ones — an override would preserve a chart that looks authoritative and
    reports nothing.

    It is accepted because a one-off cost you can see beats a silent, permanent
    invalidation you cannot.

---

## Terms, in one place

| Term | Meaning |
|---|---|
| **ARL₀** | Average Run Length while in control — observations between false alarms |
| **ARL₁** | Average Run Length once a real shift has occurred — how fast you detect it |
| **Phase I** | Retrospective: estimate the centre and spread from known-good data |
| **Phase II** | Prospective: test each new observation against the fixed limits |
| **In control** | Consistent with normal variation. Not the same as "good" |
| **Out of control** | Not explainable by normal variation. Not the same as "bad" |
| **UCL / LCL** | Upper and lower control limits |
| **Sigma estimate** | Caliper's estimate of the process's normal spread |

!!! note "\"In control\" is not a quality judgement"

    A consistently mediocre agent is perfectly in control. SPC detects
    **change**, not badness — an agent that has always scored 6.2 and still
    scores 6.2 is doing exactly what it has always done.

    Whether 6.2 is acceptable is your call, and it is not a question a control
    chart can answer.

[^q]:
    Quesenberry, C.P. (1993). "The effect of sample size on estimated limits
    for $\bar{X}$ and $X$ control charts." *Journal of Quality Technology*
    25(4):237–247.
