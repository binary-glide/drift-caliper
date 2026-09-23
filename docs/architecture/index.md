# Why these decisions exist

Every architectural decision in Caliper is written down, including the ones that
were rejected and why. This is not documentation ceremony — it is the mechanism
behind the claim that the library's numbers can be checked rather than trusted.

A rejected option with its reasoning is often more useful than an accepted one.
It tells you the question was asked.

---

## The decisions

| | Settles |
|---|---|
| [001](adr/001-spc-engine-in-house-with-scipy.md) | SPC engine built in-house behind a port, with published ARL tables as the test oracle. Also: **why the p-chart was rejected** |
| [002](adr/002-error-contract-exception-taxonomy.md) | Nine typed exceptions under one base; assert on type and `context`, never message text |
| [003](adr/003-reject-bootstrapped-mewma-for-calibration.md) | **Rejects** a bootstrapped multivariate approach — it calibrates against pointwise false alarm rate rather than ARL₀ |
| [004](adr/004-fitted-artefact-protocol-and-fitting-api-surface.md) | The fitted artefact protocol, and why detection boundaries are chart-specific rather than shared |
| [005](adr/005-minimum-phase-i-baseline-size.md) | Minimum Phase I baseline size, and the correction of a factual error carried from discovery |
| [006](adr/006-scoring-api-surface-and-judge-provider-port.md) | The scoring API and the judge provider port. No retry inside the library |
| [007](adr/007-two-type-checkers-ty-and-mypy.md) | Why **both** `ty` and `mypy --strict` run, against the house single-checker rule |
| [008](adr/008-error-assertions-over-message-text.md) | Why error tests assert on structure rather than message text |
| [009](adr/009-phase-ii-monitor-and-observation-store.md) | Where Phase II chart state lives between calls |
| [010](adr/010-signal-delivery-and-absorb-but-surface.md) | Signal delivery, and what happens when a receiver raises |
| [011](adr/011-minimum-meaningful-target-arl0.md) | The minimum meaningful `target_arl`, and why two sourced numbers were not rivals |
| [012](adr/012-bernoulli-chart-design-and-reference-value.md) | How binary charts are designed, and which of them has an exact ARL |
| [013](adr/013-gicp-supersedes-the-provisional-baseline-floor.md) | ✅ *Accepted.* Guaranteed In-Control Performance (Clopper–Pearson) replaces plug-in calibration for the Bernoulli CUSUM baseline, and a derived `α` |
| [014](adr/014-bernoulli-cusum-api-surface-and-fitted-artefact-shape.md) | ✅ *Accepted.* The Bernoulli CUSUM's API surface, Phase II input contract, and why its fitted artefact does not conform to `FittedControlLimits` |

## Three that are worth reading even if you never touch the code

**[ADR-001](adr/001-spc-engine-in-house-with-scipy.md) — why not use an existing
library.** Six alternatives were evaluated. The shortest version: the closest
candidate's CUSUM threshold is a hand-set constant with no ARL meaning, and its
calibrated alternative offers three discrete false alarm rates rather than a
continuous one. Neither could support the claim this library exists to make.

**[ADR-005](adr/005-minimum-phase-i-baseline-size.md) — a correction, published
rather than quietly fixed.** This project's own discovery notes recorded
"minimum 20–25 observations for reliable limits". That is wrong: the figure
refers to *subgroups of 3–5*, not individuals, and the individuals case is where
estimation error hurts most. The ADR records the error, the correction, and the
fact that the resulting threshold is **measured rather than derived** — with the
exit condition for replacing measurement with a citation.

**[ADR-011](adr/011-minimum-meaningful-target-arl0.md) — how a decision was
reshaped by asking a better question.** Two sourced numbers, 100 and 370, looked
like rival answers to "what is the lowest ARL₀ we should allow?". They were
answering **different** questions — what the field designs for, and what this
repository has verified. Once that was clear, both could be used, for what each
was actually good for.

!!! note "The reasoning is reusable, which is why it is recorded"

    When two sourced numbers seem to compete, check whether they are answering
    the same question before choosing between them.

## What you will not find

No ADR pins a numerical constant.

That is deliberate, and it is the single highest-stakes rule in this codebase. A
wrong `d₂`, a wrong decision interval for a target ARL₀, a wrong table entry —
each produces control limits that look authoritative and are silently wrong,
which is exactly the failure Caliper exists to prevent.

Constants live in the source, beside the primary source they came from, with the
test that checks them. Where a value could not be verified against a primary
source, the work stopped and reported rather than approximating.
