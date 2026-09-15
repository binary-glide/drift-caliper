<!-- The wordmark is lowercase monospace: it is the line the engineer types.
     brand.md specifies an SVG via <picture> with light/dark variants, which is
     the "primary vehicle" for brand on GitHub. That is not used here yet for a
     verified reason: PyPI's readme_renderer STRIPS <source>, so the dark
     variant is dropped, and a relative src does not resolve on PyPI at all --
     it needs an absolute URL, which only works once this repository is public.
     A code span is lowercase and monospace on both surfaces today, and keeps a
     real text <h1> for screen readers and scrapers. Swap at soft launch. -->

# `caliper`

[![CI](https://github.com/binary-glide/drift-caliper/actions/workflows/ci.yml/badge.svg?branch=trunk)](https://github.com/binary-glide/drift-caliper/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/binary-glide/drift-caliper/branch/trunk/graph/badge.svg)](https://codecov.io/gh/binary-glide/drift-caliper)
[![PyPI](https://img.shields.io/pypi/v/drift-caliper.svg)](https://pypi.org/project/drift-caliper/)
[![Python](https://img.shields.io/pypi/pyversions/drift-caliper.svg)](https://pypi.org/project/drift-caliper/)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-475569.svg)](https://github.com/binary-glide/drift-caliper/blob/trunk/LICENSE)
[![Documentation](https://readthedocs.org/projects/drift-caliper/badge/?version=latest)](https://drift-caliper.readthedocs.io/en/latest/)
[![CodeQL](https://github.com/binary-glide/drift-caliper/actions/workflows/codeql.yml/badge.svg?branch=trunk)](https://github.com/binary-glide/drift-caliper/security/code-scanning)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/binary-glide/drift-caliper/badge)](https://securityscorecards.dev/viewer/?uri=github.com/binary-glide/drift-caliper)

> Statistical Process Control for LLM-as-a-judge agent quality scores.

Your dashboard says the average score dropped from 8.1 to 7.6. Caliper answers
the question the dashboard cannot: **is that a real change, or is it noise?**

Caliper treats LLM-as-a-judge as a **measurement instrument** and applies
**Statistical Process Control** as the signal detection layer on top of it. You
choose a false alarm rate; the library derives control limits that deliver it,
and reports what it actually achieved.

**Status:** pre-release. The API below is implemented and tested, but nothing is
published to PyPI yet.

---

## The claim

**Your monitoring should have a known false alarm rate.**

Most quality alerting uses a threshold somebody picked. Set it tight and you
drown in false alarms; set it loose and your users tell you first. Neither
setting has a stated error rate, so neither can be defended when someone asks
why it is where it is.

Caliper takes the error rate as the **input**:

```python
fitted = fit_ewma(baseline, target_arl=370.0)
```

`target_arl=370` means: while nothing is actually wrong, expect a false alarm
about once every 370 observations. That is a parameter you chose, with known
statistical properties — and the fitted artefact reports what the calibration
achieved, so you can check it rather than trust it:

```python
print(fitted.requested_arl, fitted.achieved_arl)   # 370.0 370.0
```

## Install

Not yet published.

```bash
pip install drift-caliper   # planned
```

```python
import drift_caliper
```

## Example

Runs as printed. The provider is a stand-in for a real LLM call so you can watch
the machinery work first.

```python
import random

from drift_caliper import (
    Baseline, Judge, JudgeProviderResponse, Monitor, fit_ewma,
)


class StubProvider:
    def __init__(self) -> None:
        self.mean = 8.0

    def score(self, *, model_version, criteria, agent_output, agent_input=None):
        return JudgeProviderResponse(
            score=random.gauss(self.mean, 0.5), reasoning="stub reasoning"
        )


provider = StubProvider()
judge = Judge.create(
    model_version="claude-sonnet-5-20260115",   # required, not optional
    provider=provider,
    criteria="Rate the helpfulness of this response from 0 to 10.",
)

# Phase I -- establish what normal looks like.
baseline = Baseline()
for _ in range(150):
    baseline.record(judge.score("a representative agent output"))

# Fit limits that deliver the false alarm rate we asked for.
fitted = fit_ewma(baseline, target_arl=370.0)
print(f"requested ARL0 {fitted.requested_arl}, achieved {fitted.achieved_arl:.1f}")

# Phase II -- watch for drift.
monitor = Monitor(fitted, receivers=[lambda s: print(f"drift: {s.direction}")])

for _ in range(20):
    monitor.record(judge.score("a healthy agent output"))

provider.mean = 6.5             # the judge's model is quietly swapped
for _ in range(30):
    result = monitor.record(judge.score("a degraded agent output"))
    if not result.is_in_control:
        break
```

```text
requested ARL0 370.0, achieved 370.0
drift: lower
```

The lifecycle, in full:

```text
  score            collect            fit                 monitor
  ─────            ───────            ───                 ───────
  judge.score()  → Baseline.record  → fit_ewma      → Monitor.record()
                   (Phase I)          fit_cusum       (Phase II)
                                      fit_shewhart          │
                   ≥100 observations  calibrated to         ▼
                   required           your target_arl   receivers
```

## What it does not do

Scope discipline is a feature, so it is worth being explicit.

Caliper does **not** capture traces, render dashboards, manage prompts, store
your data, run eval suites, or call an LLM. There is no server, no database and
no network code — three runtime dependencies (`numpy`, `scipy`, `pydantic`) and
no I/O of any kind.

It detects drift. It plugs into what you already use.

## What is implemented

Three charts, all calibrated against published ARL tables:

| Chart | Detects | Fit with |
|---|---|---|
| **EWMA** | gradual drift — the default | `fit_ewma` |
| **CUSUM** | sustained shifts of a known size | `fit_cusum` |
| **Shewhart I** | large, abrupt single-point failures | `fit_shewhart` |

Binary pass/fail rubrics are **not supported yet**. A p-chart was evaluated and
**rejected** — its control limits are integer counts, so the achievable false
alarm rates are discrete and it cannot be calibrated to a target you choose.
**Bernoulli EWMA and Bernoulli CUSUM are the decided replacement**, and neither
is built. See [ADR-001's 2026-09-13 amendment](docs/architecture/adr/001-spc-engine-in-house-with-scipy.md)
for the full evaluation.

**The judge model version is a required parameter.** A missing or blank one
raises `InvalidParameterError`; it does not warn and it does not default. Every
control limit you fit is a statement about one specific judge applying one
specific rubric, so a judge that changes silently makes the limits look
authoritative while meaning nothing.

**Signals are delivered, not raised.** A drift signal is the *successful* output
of a measurement, so it goes to your receivers. Errors — invalid configuration,
a provider failure, a provenance mismatch — do raise, because Caliper cannot do
its job and only your application can decide whether to abort, retry or degrade.

<details>
<summary><b>Not yet built, and deliberately not advertised as if it were</b></summary>

A previous version of this README described a `@monitor.watch` decorator, an
`async with monitor.trace()` context manager, LangGraph and PydanticAI
integrations, and a p-chart. **None of those exist.** The decorator and the
context manager are planned for a later release; the integrations are not built;
the p-chart was rejected on statistical grounds.

They are recorded here rather than quietly deleted because the reason matters:
a reader who copies a quickstart and hits an `ImportError` has been told
something untrue by a library whose entire argument is that its claims can be
checked.

</details>

## Documentation

**<https://drift-caliper.readthedocs.io/en/latest/>**

- [Quickstart](https://drift-caliper.readthedocs.io/en/latest/quickstart/) — judge to signal, complete and runnable
- [What the numbers mean](https://drift-caliper.readthedocs.io/en/latest/concepts/) — ARL₀, Phase I and Phase II, assuming no SPC background
- [Choosing a chart](https://drift-caliper.readthedocs.io/en/latest/charts/) — EWMA, CUSUM or Shewhart
- [Decisions](https://drift-caliper.readthedocs.io/en/latest/architecture/) — every architectural decision, including the rejected ones

## Why the decisions are published

Three commitments you can check rather than take on trust.

**Control limits are derived, not chosen.** Nothing in this library contains a
threshold that somebody felt was about right.

**Every constant cites a primary source.** `d₂ = 1.128` appears in the code with
*Montgomery, Appendix VI* beside it.[^d2] Where a value could not be verified
against a primary source, the work stopped rather than approximating.

**The test suite verifies against published tables.** The EWMA calibration is
checked against all ten multipliers in Table 3 of Lucas & Saccucci (1990);[^ls]
the CUSUM approximation reproduces Montgomery's worked example to four
significant figures.

## Reading the source

Comments, tests and ADRs cite internal tracker IDs (`BIN-123`). **No tracker
access is needed** — each is explained where it appears, and the ID is a
citation rather than a lookup.

They are kept deliberately. A note reading *"`str.__str__(value)`, not
`str(value)` — the latter dispatches to the subclass's `__str__`, which is
hijackable exactly like `__eq__`"* is a decision someone made once, for a
reason, after something went wrong. The ID marks it as a defect that was found
and fixed rather than a hypothetical someone thought of.

Design decisions live in [`docs/architecture/adr/`](docs/architecture/adr/),
including the ones that were rejected and why.

## Licence

Apache 2.0 — see [LICENSE](LICENSE).

## References

<!-- Both renderers hoist footnote *definitions* to the end of the document
     regardless of where they appear in the source, so this heading has to be
     the last one for the list to land under it.

     It is not decoration. GitHub labels the block
     `<h2 class="sr-only">Footnotes</h2>` -- visually hidden, so sighted
     readers get an unlabelled list -- and PyPI's readme_renderer emits a bare
     `<section><ol>` with no heading at all. Without this, the citations render
     as though they belong to the Licence section on both surfaces. -->

[^d2]:
    Montgomery, D.C. *Introduction to Statistical Quality Control*, 7th ed.,
    Wiley 2013, Appendix VI. The exact value is `2/√π` for subgroups of size
    two, which is what a moving range of consecutive individual observations is.

[^ls]:
    Lucas, J.M. and Saccucci, M.S. (1990). "Exponentially Weighted Moving
    Average Control Schemes: Properties and Enhancements." *Technometrics*
    32(1):1–12, Table 3.
