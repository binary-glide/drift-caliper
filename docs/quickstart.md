# Quickstart

Five steps, then the whole thing as one script.

The five steps show the shape against **your** data — your LLM client, your
agent outputs — so they name those as placeholders. [The whole
thing](#the-whole-thing) at the bottom substitutes a stub provider and **runs
unattended, exactly as printed**, including the output shown beneath it.

```bash
uv add drift-caliper
```

<!-- uv leads because it is what this project builds with and what most new
     Python projects reach for. pip stays because this page's sibling, the
     README, is also the PyPI long description -- read by people on poetry,
     pdm, conda and plain pip, none of whom should have to translate. -->

```bash
pip install drift-caliper
```

---

## 1. Write a judge provider

**Caliper does not call an LLM.** It has no network code and no provider SDKs.
You supply the call; Caliper supplies everything downstream of the score.

A provider is any object with a `score` method matching this shape:

```python
from drift_caliper import JudgeProviderResponse

class MyJudgeProvider:
    def score(self, *, model_version, criteria, agent_output, agent_input=None):
        # Your LLM call goes here. Return the score and the reasoning.
        response = my_llm_client.complete(
            model=model_version,
            prompt=f"{criteria}\n\nOutput to judge:\n{agent_output}",
        )
        return JudgeProviderResponse(
            score=response.score,
            reasoning=response.reasoning,
        )
```

!!! note "Why you write this and Caliper does not"

    A concrete provider would tie the library to one vendor's SDK and its
    release cadence, and Caliper's statistical claims do not depend on where a
    score came from. The seam is a `Protocol`, so your class needs no base
    class and no registration — it just needs the method.

## 2. Pin the judge

```python
from drift_caliper import Judge

judge = Judge.create(
    model_version="claude-sonnet-5-20260115",
    provider=MyJudgeProvider(),
    criteria="Rate the helpfulness of this response from 0 to 10.",
)
```

!!! danger "The model version is required, and a blank one is refused"

    Caliper raises `InvalidParameterError` rather than defaulting or warning.

    This is the library's single biggest integrity concern. Every control limit
    you fit is a statement about *one specific judge applying one specific
    rubric*. If the judge silently changes underneath you, the limits still look
    authoritative and no longer mean anything — which is the exact failure this
    library exists to prevent.

    A warning would be suppressible by logging configuration. This is not.

Scoring returns a `ScoringResult` carrying the score, the judge's reasoning, and
a `Provenance` recording which judge and which rubric produced it:

```python
result = judge.score("The capital of France is Paris.")

print(result.score)                             # 8.4
print(result.provenance.model_version.value)    # claude-sonnet-5-20260115
```

## 3. Collect a Phase I baseline

Phase I answers *"what does normal look like?"*. You need a sample of outputs
from a period when the agent was behaving acceptably.

```python
from drift_caliper import Baseline

baseline = Baseline()
for output in historical_agent_outputs:      # your own outputs
    baseline.record(judge.score(output))

print(len(baseline))                         # 150
```

Check it is big enough before fitting anything:

```python
sufficiency = baseline.check_sufficiency()

print(sufficiency.is_sufficient)             # True
print(sufficiency.observation_count)         # 150
print(sufficiency.threshold)                 # 100
```

!!! warning "100 is the floor the library enforces, not the size you want"

    Below 100 observations, `fit_*` raises `InsufficientBaselineError` with
    `context = {"have": 50, "need": 100}`. At 100 or above it fits, and says
    nothing further.

    **That silence is not an endorsement.** 100 is a deliberate compromise
    between statistical adequacy and adoption cost. Quesenberry (1993) found
    around **300 individual observations** are needed before the run-length
    distribution behaves as if the parameters were known.[^q] With 120, your
    chart works — it just delivers a false alarm rate somewhat worse than the
    one you asked for, and nothing currently tells you by how much.

    The widely-quoted "20–25 observations" figure is worth unlearning: it refers
    to *subgroups of 3–5*, so it is 100–125 data points, and it describes a
    setting with within-subgroup averaging that this one does not have.

    [What the numbers mean](concepts.md#3-how-much-baseline-do-i-actually-need)
    has the numbers and the open work.

## 4. Fit control limits

```python
from drift_caliper import fit_ewma

fitted = fit_ewma(baseline, target_arl=370.0)

print(fitted.chart_type)      # ewma
print(fitted.requested_arl)   # 370.0
print(fitted.achieved_arl)    # 370.0
print(fitted.baseline_mean)   # 8.012  -- your baseline's mean
print(fitted.ucl, fitted.lcl) # 8.437 7.586
```

The mean and the limits come from *your* baseline, so yours will differ. The
two ARL figures are the ones to check: `requested_arl` is what you asked for,
`achieved_arl` is what the calibration delivered.

`target_arl=370` means **about one false alarm per 370 observations while
nothing is wrong**. See [choosing a chart](charts.md) for EWMA versus CUSUM
versus Shewhart, and [what the numbers mean](concepts.md) for what `achieved_arl`
is and is not promising.

## 5. Monitor

```python
from drift_caliper import Monitor, MonitoringResult

def alert_me(signal: MonitoringResult) -> None:
    print(f"drift detected: {signal.direction} on {signal.chart_type}")

monitor = Monitor(fitted, receivers=[alert_me])

for output in live_agent_outputs:
    monitor.record(judge.score(output))
```

`Monitor.record()` returns a `MonitoringResult` every time, whether or not
anything is wrong. A drift signal is a *successful measurement*, not an error —
so it is delivered to your receivers, never raised.

```python
result = monitor.record(judge.score(output))

if not result.is_in_control:
    print(result.direction)     # "lower" -- scores have fallen
```

!!! note "If your receiver raises, `record()` still returns"

    A receiver that raises — a full disk, a misconfigured logger, a pager that
    is down — does not propagate out of `record()`. The measurement already
    succeeded before any receiver ran, and a broken log sink should not take
    down your monitoring.

    It is not swallowed either. The failure comes back on the result, so a
    signal nobody received is never silently lost:

    ```python
    for failure in result.delivery_failures:
        print(failure.receiver, failure.error_type, failure.error_message)
    ```

---

## The whole thing

Runnable as-is. The provider is a stand-in that generates scores from a normal
distribution, so you can watch the machinery work before wiring in a real LLM.

```python
import random

from drift_caliper import (
    Baseline,
    Judge,
    JudgeProviderResponse,
    Monitor,
    MonitoringResult,
    fit_ewma,
)


class StubProvider:
    """Stands in for a real LLM call so this example runs unattended."""

    def __init__(self) -> None:
        self.mean = 8.0

    def score(self, *, model_version, criteria, agent_output, agent_input=None):
        return JudgeProviderResponse(
            score=random.gauss(self.mean, 0.5),
            reasoning="stub reasoning",
        )


provider = StubProvider()
judge = Judge.create(
    model_version="claude-sonnet-5-20260115",
    provider=provider,
    criteria="Rate the helpfulness of this response from 0 to 10.",
)

# Phase I -- what normal looks like.
baseline = Baseline()
for _ in range(150):
    baseline.record(judge.score("a representative agent output"))

sufficiency = baseline.check_sufficiency()
print(f"baseline: {len(baseline)} observations, sufficient: {sufficiency.is_sufficient}")

# Fit limits that deliver the false alarm rate we asked for.
fitted = fit_ewma(baseline, target_arl=370.0)
print(f"requested ARL0 {fitted.requested_arl}, achieved {fitted.achieved_arl:.1f}")

# Phase II -- watch for drift.
signals: list[MonitoringResult] = []
monitor = Monitor(fitted, receivers=[signals.append])

for _ in range(20):
    monitor.record(judge.score("a healthy agent output"))
print(f"signals while healthy: {len(signals)}")

# The judge's model is quietly swapped for a worse one.
provider.mean = 6.5
for _ in range(30):
    result = monitor.record(judge.score("a degraded agent output"))
    if not result.is_in_control:
        print(f"signal: direction={result.direction} chart={result.chart_type}")
        break

print(f"signals delivered: {len(signals)}")
```

Output:

```text
baseline: 150 observations, sufficient: True
requested ARL0 370.0, achieved 370.0
signals while healthy: 0
signal: direction=lower chart=ewma
signals delivered: 1
```

## What happens when the judge changes

Every fitted artefact carries the provenance of the baseline it was fitted from.
If a Phase II result was produced by a different judge model or a different
rubric, Caliper raises `ProvenanceMismatchError` rather than scoring it against
limits that no longer describe it.

```python
from drift_caliper import ProvenanceMismatchError, compare_provenance

try:
    compare_provenance(result, fitted)
except ProvenanceMismatchError as e:
    print(e.mismatches)
    # {"model_version": {"expected": "claude-sonnet-5-20260115",
    #                    "received": "claude-sonnet-5-20260420"}}
```

!!! danger "There is no acknowledgement flag, and that is deliberate"

    `compare_provenance()` takes no `force=` or `acknowledge=` parameter, and a
    test exists specifically to fail if one is ever added.

    Knowing the instrument changed does not make old-instrument measurements
    comparable to new ones. An override would preserve a chart that looks
    authoritative and reports nothing — so the answer to a mismatch is to
    collect a new baseline.

    **This is a real cost, not a hidden one:** a judge change resets the
    100-observation Phase I minimum in full. It is accepted because a one-off
    cost you can see beats a silent, permanent invalidation you cannot.

[^q]:
    Quesenberry, C.P. (1993). "The effect of sample size on estimated limits
    for $\bar{X}$ and $X$ control charts." *Journal of Quality Technology*
    25(4):237–247.
