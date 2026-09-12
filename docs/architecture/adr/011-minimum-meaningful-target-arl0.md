# ADR-011: Minimum meaningful target ARL₀

**Status:** ✅ **ACCEPTED — ratified by the product owner 2026-09-12**
**Date:** 2026-09-12
**Refs:** BIN-131, BIN-117, BIN-122, ADR-001, ADR-004, ADR-005

---

## Context

`fit_ewma` and `fit_shewhart` accept `target_arl=1.0` and return a fitted
artefact. Monitoring a **perfectly healthy in-control process** with it:

```
in-control observations signalling out-of-control: 20/20
```

Every observation alarms. Nothing raises. The artefact reports
`achieved_arl ≈ 1.0` and is, by its own stated contract, delivering exactly
what was requested.

`fit_cusum` refuses — **but only by accident.** BIN-117's attainability check
happens to reject `1 < 1.0431` at the default reference value. A guard that
exists for one chart as a side effect of an unrelated fix is not a guard.

### The constant is correctly derived and wrongly named

`ewma_fitting.py` justifies `MIN_MEANINGFUL_ARL = 1.0` rigorously:

> ARL₀ is defined as the expectation of a stopping time … that count is a
> positive integer … `E[N] >= 1` for any `N` supported on `{1, 2, 3, …}`
> follows directly from the definition of expectation.

**That derivation is sound and is preserved.** It establishes the
**coherence** floor — the smallest arithmetically meaningful value — while the
name promises the smallest **useful** one. Those are different numbers, and the
gap between them is where BIN-131 lives.

---

## The governing principle

> **It is the engineer's choice, provided they have been properly informed.**

Ratified by the product owner, 2026-09-12, and it settles the shape of this
decision before any number is chosen. Caliper's job at a low `target_arl` is
**not** to protect the engineer from an unusual configuration. It is to
guarantee they cannot adopt one *without knowing what they are giving up*.

⚠️ **This is the same principle ADR-005 already applies to baseline size**,
which is why this ADR adopts the same three-tier shape rather than inventing
one. Two thresholds on two different axes, one philosophy.

---

## Four candidate floors, and what each actually claims

| floor | value | claim | source |
|---|---|---|---|
| **Coherence** | `1.0` | below this, ARL₀ is not a number | derived, `E[N] ≥ 1` |
| **Attainability** | per-chart | below this, no parameterisation reaches it | computed; BIN-117 |
| **Literature** | **`100`** | below this, the field does not tabulate it | Lucas & Saccucci |
| **Verification** | **`370`** | below this, Caliper has no test oracle | this repo |

They are **not competing answers to one question.** They answer four different
questions — and the tiering below uses two of them for what each is actually
good for, rather than forcing one to do both jobs.

### Attainability — computed, not cited

```
CUSUM @ k=0.5 (default), two-sided : 1.0431
CUSUM @ k=5.0, two-sided           : 1158.3
EWMA, Shewhart                     : ≈ 1.0 regardless of parameters
```

⚠️ **Per-chart and per-parameter, not a library constant**, and it can sit far
*above* the policy floor. BIN-117 already enforces it for CUSUM. A *necessary*
bound, never a sufficient one — `target_arl=2.0` is attainable on all three
charts and still useless.

### Literature — the hard floor

Lucas & Saccucci (1990), *Technometrics* 32(1):1–12, held at
`Projects/caliper/references/papers/`, §"Tables", **read directly**:

> "Lucas and Saccucci (1987) also provided tables for in-control ARL's of
> **100**, 300, 1,000, 2,000, and 5,000."

Their **Table 4** ("Optimal EWMA Control Schemes") covers **300, 500, 1,000,
2,000, 5,000** — so *optimal design* begins at 300, and **100 is the lowest
in-control ARL the canonical EWMA reference tabulates at all.**

Same paper Caliper already verifies `fit_ewma` against
(`test_ewma_arl_published_values.py` pins all ten of its Table 3 `L` values), so
it requires no acquisition and introduces no new authority.

### Verification — the advisory line

Every published-table oracle in this repository sits at **ARL₀ = 370–500**.
Below 370 there is **no oracle at all**.

ADR-001 makes published ARL tables *the* test strategy. A chart fitted at
`target_arl = 150` is calibrated by the same code and the same method as one at
500 — **but Caliper has never checked that code against a published value in
that region.** That is a real and disclosable difference, and it is exactly what
the engineer deserves to be told.

---

## Decision

**1. Rename the existing constant to what it derives.**
`MIN_MEANINGFUL_ARL` → `MIN_COHERENT_ARL = 1.0`, keeping its derivation comment
verbatim.

✅ **Internal-only, verified**: absent from `caliper.__all__` *and*
`caliper.baseline.__all__`, not reachable via `hasattr`. BIN-110 removed the six
validation bounds from the public surface entirely and
`test_baseline_package_exports.py` pins that absence. **No consumer can be
importing it** — no deprecation burden.

**2. Three tiers, mirroring ADR-005.**

| tier | condition | behaviour |
|---|---|---|
| **refused** | `target_arl < 100` | `InvalidParameterError`. **No source supports a design here** — the literature does not tabulate it, so Caliper has nothing to calibrate *against* and no basis to claim the number it would report. |
| **fits, flagged** | `100 <= target_arl < 370` | Fits, returns correctly-computed limits, and **attaches a non-raising advisory**: this target is outside the range any published table in Caliper's test suite covers. The maths is the same; the *verification* is not. |
| **fits, clean** | `target_arl >= 370` | Fits. No advisory. Within the oracle-verified range. |

**3. Keep BIN-117's per-chart attainability check**, applied on all three charts
rather than CUSUM alone. It is a different bound and both are needed.

### Why not 370 as a hard floor

It was considered and rejected **on the governing principle**: 370 is Caliper's
*verification* range, not the field's *design* range, and refusing there
substitutes the library's caution for the engineer's judgement about their own
process.

⚠️ **It also has a concrete cost that only surfaced on inspection.** ADR-005
defines:

```
adequate(target_arl):  <= 200 -> 300      > 200 -> 500
```

**A hard floor of 370 makes the first branch unreachable**, collapsing
`adequate()` to a constant and discarding a distinction the 60-cell study
measured at four targets starting at 100. Two ADRs that compose cleanly at 100
stop composing at 370.

### 🚨 What this deliberately does not decide

**It does not claim 100 is statistically adequate for any process.** It claims
the field does not tabulate below it, so Caliper has no basis to *calibrate*
there. Nor does the advisory tier claim 150 is wrong — only that Caliper has not
checked itself in that region and will say so.

---

## Consequences

**A shared advisory vehicle is now needed, and does not exist.**
`DataQualityConcern` is bound to `SufficiencyResult` from `check_sufficiency()`;
there is **no non-raising advisory on a fitted artefact**. ⚠️ ADR-005's
middle tier needs the identical mechanism and is also unimplemented. **One
vehicle, two users** — build it once, and do not let the second caller invent a
parallel shape.

**Breaking for `[1.0, 100.0)` only** — a far narrower band than 370 would cut.

⚠️ **The in-repo blast radius is not zero.** `test_shewhart_fitting.py` runs
Hypothesis strategies over `[MIN_MEANINGFUL_ARL, MAX_MEANINGFUL_ARL]`, which
would draw now-illegal values on nearly every example and must be rebounded.
**That is precisely BIN-124's pattern** — a new rejection turning an existing
strategy into a generator of illegal inputs — and **BIN-124's meta-test should
catch it. This will be the first real-world exercise of that guard.**

No production code and no `.feature` scenario requests a target below 370.
Tightening later is breaking; loosening later is not — so the hard floor is
better placed before PyPI than after.

**Closes BIN-131** and removes the asymmetry where CUSUM alone rejected the
pathological case.

**Does not close BIN-132.** A `bool` *score* is a separate question from a low
*target*.

**BIN-122 gains a worked example** — every individual value legal, the
combination meaningless, nothing raised. The exception-contract audit is
structurally blind to it, as its own docstring states.

---

## ⚠️ A correction, recorded because the error was in guidance

`BIN-132`'s `recovery_hint` — the redirect an engineer reads at the exact
moment Caliper refuses their `bool` score — shipped with **two statistical
errors**, caught by `code-reviewer` and corrected before merge. Recorded here
rather than only in a commit message, because both are easy to make again:

**1. A one-sided condition for a two-sided requirement.** It stated the normal
approximation to the binomial holds once `n*p > 5`, omitting the symmetric
`n*(1-p) > 5`. At the hint's own worked example (batch of 20) that silently
excludes pass rates above **0.75** — which is to say, **it excluded the
well-functioning agent**, the most likely reader.

```
n=20, p=0.90  ->  n*p = 18.0  OK      n*(1-p) = 2.0   FAILS
```

**2. Rolling language priced with batch arithmetic.** It recommended a
*rolling* pass-rate and then costed it as *non-overlapping* batches
(`100 * 20 = 2000`). A rolling window needs only **119** raw judgements for
100 values — but consecutive values then share **19 of 20** observations.

🚨 **That overlap is the serious half.** Caliper fits sigma from the **moving
range**, which assumes consecutive observations are independent. A rolling
pass-rate violates that badly — so the hint would have walked an engineer out
of one silently-wrong chart and into another. The corrected text specifies
**non-overlapping batches** and says why.

**The general lesson, which is not about statistics:** this hint was reviewed
approvingly by the coordinator on the strength of it being detailed, honest
about cost, and pointing at a real alternative. **It was all three, and still
wrong.** Confident, well-structured guidance reads as correct — worked
arithmetic is what distinguishes it, and a `recovery_hint` that redirects to a
statistical method deserves the same citation discipline as a constant.

---

## Alternatives rejected

**Document it as legal-but-useless.** ❌ The failure is silent, and
documentation does not reach someone who never reads it. The advisory tier is
the disciplined version of this: informing at the point of use, in the return
value, not in prose someone may never open.

**Extend BIN-117's attainability check and stop there.** ❌ EWMA's and
Shewhart's floors are ≈1.0 regardless of parameters, so this rejects nothing —
it would look like a fix and change no behaviour.

**Pick a round number.** ❌ ADR-001 deliberately pinned no numerical constants.
`100` names Lucas & Saccucci (1987); `370` names this repository's own oracle
coverage. Both are sourced; neither is taste.

---

## Ratified 2026-09-12

- [x] **100** as the hard floor, cited to Lucas & Saccucci (1987)
- [x] **370** as the advisory line, cited to Caliper's own oracle coverage
- [x] The breaking change for `[1.0, 100.0)`, pre-PyPI
- [x] The shared fitted-artefact advisory vehicle is built once and serves
      ADR-005's middle tier too

**The governing principle came from the product owner and reshaped the
decision.** Two earlier drafts treated `100` and `370` as rival answers to one
question and asked which to pick. *"It is the developer's choice as long as we
have informed them properly"* made clear they answer **different** questions —
what the field designs for, and what this repository has verified — and that a
library's job at an unusual-but-sourced setting is disclosure, not refusal.

⚠️ Recorded because the reasoning is reusable: **when two sourced numbers seem
to compete, check whether they are answering the same question before choosing
between them.**
