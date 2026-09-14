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
  Shewhart I-chart (acute failures). Binary pass/fail rubrics are **not yet
  supported** — see [ADR-001's 2026-09-13 amendment](docs/architecture/adr/001-spc-engine-in-house-with-scipy.md)
  for why a p-chart was rejected and what replaces it
- **API** — `@monitor.watch` decorator as the happy path,
  `async with monitor.trace()` for multi-step agents, `.record()` for framework
  callbacks (LangGraph, PydanticAI)
- **Alerting** — callback/handler chain, not exceptions; `RaiseOnSignal` is
  opt-in
- **Judge model pinning** — a required parameter, not an optional one. This is
  the single biggest threat to statistical integrity
- **Severity** — `warning` on first signal, `critical` on 3+ consecutive or a
  score below a hard floor

## Reading the source

Comments, tests and ADRs cite internal tracker IDs (`BIN-123`). **No tracker
access is needed** — each is explained where it appears, and the ID is a
citation rather than a lookup.

They are kept deliberately. A note reading *"`str.__str__(value)`, not
`str(value)` — the latter dispatches to the subclass's `__str__`, which is
hijackable exactly like `__eq__`"* is a decision someone made once, for a
reason, after something went wrong. The ID marks it as a defect that was
found and fixed rather than a hypothetical someone thought of.

Design decisions live in [`docs/architecture/adr/`](docs/architecture/adr/),
including the ones that were rejected and why.

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
