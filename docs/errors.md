# Errors

**Where Caliper cannot do its job, it raises. It does not warn, swallow, or
return a default.**

Choosing whether to abort, retry, degrade or log is your application's policy,
not the library's. A library that decides for you has made a guess about a
system it cannot see.

---

## The shape of every error

Every exception inherits from `CaliperError` and carries three things:

```python
from drift_caliper import CaliperError, fit_ewma

try:
    fit_ewma(baseline, target_arl=50.0)
except CaliperError as e:
    print(e.category)        # "invalid_parameter"  -- a stable, closed string
    print(e.context)         # {"parameter": "target_arl", "kind": "invalid", ...}
    print(e.recovery_hint)   # human-facing prose: what to do next
```

| | | |
|---|---|---|
| `category` | machine-readable | Stable. Safe to branch on |
| `context` | machine-readable | The specific values involved. Keys are stable per category |
| `recovery_hint` | human-facing | For a person to read. **Not** part of the contract |

!!! danger "Branch on the type or on `context` — never on the message"

    Message wording is not part of the API and will change without notice.
    `category` and the required `context` keys are.

    ```python
    # Do this
    except InvalidParameterError as e:
        if e.context["kind"] == "missing":
            ...

    # Never this
    except CaliperError as e:
        if "target_arl" in str(e):   # breaks silently on any rewording
            ...
    ```

## The nine categories

| Exception | `category` | Raised when |
|---|---|---|
| `InvalidParameterError` | `invalid_parameter` | A parameter is missing, the wrong type, or out of range |
| `MissingPrerequisiteError` | `missing_prerequisite` | An operation needs something that has not happened yet |
| `ProviderError` | `provider_failure` | Your judge provider failed or was unreachable |
| `MalformedResponseError` | `malformed_response` | The provider responded, but not with a usable score |
| `JudgeRefusalError` | `judge_refusal` | The provider declined to score, on content or safety grounds |
| `ProvenanceMismatchError` | `provenance_mismatch` | A result came from a different judge or rubric than the artefact |
| `InvalidObservationError` | `invalid_observation` | An observation cannot be recorded — not finite, wrong type |
| `InsufficientBaselineError` | `insufficient_baseline` | Fewer than 100 observations in the baseline |
| `DegenerateBaselineError` | `degenerate_baseline` | The baseline has no variation to estimate spread from |

The list is **semi-open**: a future version may add a category. Code that
branches on the ones it knows and lets the rest propagate stays correct.

## Two discriminators that look alike and are not

`InvalidParameterError` carries `context["kind"]`, which is a **closed** set:

| `kind` | Meaning |
|---|---|
| `"missing"` | The parameter was not supplied at all |
| `"invalid"` | It was supplied, but is the wrong type or out of range |

`InvalidObservationError` and `DegenerateBaselineError` carry
`context["reason"]`, which is **descriptive** and open-ended.

They are deliberately different keys. `kind` can be exhaustively matched;
`reason` cannot. Do not unify them.

## Why some parameters are optional in the signature but required in practice

```python
fit_ewma(baseline)
# InvalidParameterError, context["kind"] == "missing"
```

`target_arl` has a default of `None` even though you must supply it. That looks
odd until you see what the alternative does: a genuinely required argument makes
**Python** raise `TypeError` before Caliper runs, and a `TypeError` has no
`category`, no `context`, and no `recovery_hint`.

Optional-in-signature, required-by-validation means every failure — including
the one where you forgot an argument entirely — arrives in the same shape and
can be handled by the same `except` block.

## Errors worth handling specifically

### The judge changed

```python
from drift_caliper import ProvenanceMismatchError

try:
    monitor.record(result)
except ProvenanceMismatchError as e:
    for dimension, values in e.mismatches.items():
        print(f"{dimension}: expected {values['expected']}, got {values['received']}")
```

`mismatches` is keyed by dimension (`"model_version"`, `"scoring_criteria"`),
each value a `{"expected": ..., "received": ...}` pair. **Both dimensions are
reported when both differ** — it does not stop at the first.

The only correct recovery is a new baseline. There is no override; see
[provenance](concepts.md#4-provenance-why-the-judge-is-pinned) for why.

### The provider failed

```python
from drift_caliper import ProviderError, MalformedResponseError, JudgeRefusalError

try:
    result = judge.score(agent_output)
except ProviderError:
    ...      # transient -- your retry policy goes here
except MalformedResponseError:
    ...      # the provider replied with something unusable
except JudgeRefusalError:
    ...      # the provider declined on content grounds -- do not retry
```

!!! note "Caliper does not retry, and will not start without saying so"

    There is no retry inside the library. `ProviderError` is raised on the first
    failed attempt.

    Retry policy belongs to the caller: how many attempts, what backoff, which
    failures are worth repeating, and whether a retry storm is acceptable are
    all properties of your system, not of a statistics library. Wrap
    `judge.score()` in whatever your codebase already uses.

    The three exceptions above are deliberately distinct so a retry policy can
    tell them apart — retrying a `JudgeRefusalError` will fail the same way
    every time.

### The baseline is unusable

```python
from drift_caliper import DegenerateBaselineError, InsufficientBaselineError

try:
    fitted = fit_ewma(baseline, target_arl=370.0)
except InsufficientBaselineError as e:
    print(e.context)    # {"have": 50, "need": 100} -- collect more
except DegenerateBaselineError:
    ...                 # every observation identical: no spread to estimate
```

`DegenerateBaselineError` usually means a stub judge that has been left wired in,
or a rubric so coarse that every output receives the same score. A chart cannot
be fitted from data with no variation — there is nothing to measure "unusual"
against.

## Signals are not errors

A drift signal is the **successful** output of a measurement. The library did
its job; the answer is "the process moved".

```python
result = monitor.record(judge.score(output))

if not result.is_in_control:
    print(result.direction)     # "lower" or "upper"
```

It is delivered to your receivers and returned on the result. It is never
raised. Raising on a signal would be like `re.match` throwing when there is no
match.

### A failing receiver does not become an error either

If one of your receivers raises, the exception does not escape `record()`. The
measurement had already succeeded before any receiver ran, and a broken pager
should not take down monitoring.

It is not discarded either — a signal nobody received, with nobody told, is the
precise failure this library exists to prevent:

```python
result = monitor.record(observation)

for failure in result.delivery_failures:
    print(failure.receiver, failure.error_type, failure.error_message)
```

!!! note "Why the failure comes back on the result rather than through a log"

    If the receiver that failed *was* the log sink, surfacing the failure
    through logging would fail the same way. An in-band carrier on the returned
    value is the one channel known to still work.
