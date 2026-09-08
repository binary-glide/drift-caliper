# Caliper

> Statistical Process Control for LLM agent quality scores.

Dashboards tell you a score went down. Caliper tells you whether that shift is
statistically significant — or just noise.

Caliper is a Python library that treats **LLM-as-a-judge as a measurement
instrument** and applies **Statistical Process Control** as the signal detection
layer on top of it. An 80-year-old manufacturing methodology, pointed at AI
agent quality.

**Status:** in design. Not yet released.

---

## Why

Existing observability platforms (LangSmith, Langfuse, Arize, Helicone) want to
be your trace store, and they show you a score chart. None of them apply formal
SPC with calibrated false alarm rates.

Caliper makes a claim no platform makes: **statistically defensible drift
detection with auditable control limits.**

It is a library, not a platform. It emits into wherever you already log
(OpenTelemetry compatible).

## Design

- **Charts** — EWMA (primary; gradual drift), CUSUM (sustained shifts),
  Shewhart I-chart (acute failures), p-chart (pass/fail judges)
- **API** — `@monitor.watch` decorator as the happy path,
  `async with monitor.trace()` for multi-step agents, `.record()` for framework
  callbacks (LangGraph, PydanticAI)
- **Alerting** — callback/handler chain, not exceptions; `RaiseOnSignal` is
  opt-in
- **Judge model pinning** — a required parameter, not an optional one. This is
  the single biggest threat to statistical integrity
- **Severity** — `warning` on first signal, `critical` on 3+ consecutive or a
  score below a hard floor

## Install

Not yet published.

```bash
pip install caliper-ai   # planned
```

```python
import caliper
```

## Licence

Apache 2.0 — see [LICENSE](LICENSE).
