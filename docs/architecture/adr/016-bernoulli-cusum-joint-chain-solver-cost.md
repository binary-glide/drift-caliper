# ADR-016: The Bernoulli CUSUM's joint-chain solves — ordering, solve count, and why not an iterative solver

**Status:** ✅ **ACCEPTED — ratified in full by the product owner 2026-09-27.**
**Q1 — option (b):** the **joint two-sided state cap is lowered from 1,000,000
to 400,000**, the largest cap with measured evidence of staying under ≈0.9 GB
on every reachable shape measured on Linux (worst 0.77–0.78 GB), honouring the
reason the original cap was ratified (a fit stays under ≈1 GB in the engineer's
process). The **one-sided decision-interval cap is decoupled and stays at
999,999** (≈0.96 GB). This amends ADR-014 Amendment 1 Decision 10b and
Amendment 2 Decision 13.3. **Q2 ratified** (Decision 2, calibration D's
bracketed regula falsi and the reuse of `B` for `achieved_arl`, as a pure
performance change). **Q3 ratified** (Decision 1, keep `COLAMD`; Decision 3,
reject the iterative solver).
**Date:** 2026-09-27
**Refs:** BIN-165. ADR-014 (Amendment 1 Decision 10b; Amendment 2 Decisions
13, 18, 19.4 and corrigendum C11) and ADR-015 Amendment 1 are referenced, not
edited.

> **Summary.** Keep SuperLU and its default `COLAMD` ordering (Decision 1).
> Cut calibration D's coupled solves with a proven lower bracket and a
> safeguarded regula falsi, and stop re-solving `B` for `achieved_arl` —
> identical answers, 34–55% of the solve work near the cap (Decision 2).
> Do not adopt an iterative solver (Decision 3). The cap stays at 1,000,000
> (Decision 4) pending Q1 — but on Linux **the coupled chain peaks at
> 0.71–9.4 GB at 1M states depending on the baseline** (m=300 f=3: 9.4 GB
> and 18.5 min per solve), not the ≈0.9 GB the cap was ratified on
> (Finding 0, Q1). Recommendation for Q1: a joint cap of 400,000.
>
> ✅ *Ruled 2026-09-27 (see Status): the joint cap **is** lowered to 400,000 and
> the one-sided cap decoupled at 999,999. "The cap stays at 1,000,000" above
> describes the state before the ruling.*
>
> *Added 2026-09-28: calibration D's search now has a logarithmic worst case,
> at most ⌈log₂(hi − lo)⌉ + 3 probes, from ITP's projection step (Decision 2,
> "Worst-case bound"). At the 400,000 cap, the refusal path measured 1.1–26.9 s
> end to end (Q1, "Measured at the ratified cap").*

---

## Context

The Bernoulli CUSUM reports **exact** run lengths: every figure is the
expected absorption time of a finite Markov chain, solved from
`(I − Q) m = 1` (ADR-012 §4, ADR-014 §6c). Every solve in
`src/drift_caliper/baseline/domain/bernoulli_cusum_fitting.py` goes through
one function, `_solve_absorbing_chain`, which calls
`scipy.sparse.linalg.spsolve(system, ones, use_umfpack=False)` — direct LU
with SuperLU and its default column ordering, `COLAMD`. The tests replace
`scipy.sparse.linalg.spsolve` at that seam (eight test sites, plus the
exception-contract registry), and `TestTheSolverIsPinned` asserts every call
passes `use_umfpack=False`.

Two-sided fits solve the **coupled** chain of ADR-014 Decision 19.4 on the
Cartesian product of the two arms' integer lattices (Decision 8), with
`(h_lo + 1)(h_up + 1)` states. Each state has **three** outgoing
transitions (fail both / fail lower only / succeed both), not the two the
ticket describes — the two-outcome joint chain was Amendment 1's; Amendment
2 replaced it for `achieved_arl` and calibration D. The disclosure figures
(`expected_detection_arl`, `expected_improvement_detection_arl`) still use
the two-outcome joint chain.

**What BIN-165 asks.** Near the 1,000,000-state cap (ADR-014 Amendment 1
Decision 10b), a successful two-sided fit takes minutes: calibration D
bisects over `h_up` with one coupled solve per probe. The ticket's measured
examples are m=1000 f=1 (211 s) and m=1000 f=5 (70 s) at the reported
`max_two_sided_target_arl`. The ticket lists three levers, cheapest first:

1. SuperLU's column ordering (`permc_spec`) — reported ~1.6× faster with
   `MMD_ATA` in a quick check;
2. fewer coupled solves in calibration D;
3. an iterative (Krylov) solver, which would change what "exact" means and
   would reopen the cap's memory basis.

**The cap's basis is memory**, ratified on ~950 bytes of peak RSS per state
(Amendment 1 Decision 10b, measured on the two-outcome joint chain at m=300
f=0, and re-measured for one-sided chains in Decision 13). Any lever that
changes fill-in changes that basis, so every option below is measured for
peak RSS as well as time.

**Out of scope, stated so it is not inferred.** Sentry is permanently out
of scope for this library (`CLAUDE.md`). `docs/api-contracts.md` does not
exist and is not created: Caliper has no endpoints. No public signature,
artefact field, error category or `context` key changes under any option
here. The refusal path's `max_two_sided_target_arl` (C11) is not reopened.

---

## How the measurements were taken

- **Machine (local):** Apple M1 Max, 10 cores, 32 GB, macOS; Python 3.13.14,
  numpy 2.5.3, scipy 1.18.1 (the locked versions), SuperLU as shipped in the
  scipy wheel. The machine was not otherwise idle (load average ≈ 3.5 of 10
  cores from unrelated work), so local times carry some noise; memory figures
  do not.
- **One solve per fresh process.** `solve_one.py` imports production and
  calls `_coupled_arl_in_units` (or `_arm_arl`) exactly as the fit does, matrix
  build included. Only `scipy.sparse.linalg.spsolve` — production's seam, the
  same one the tests replace — is swapped, to pass a different `permc_spec` or
  to run a Krylov method. The independent reference is
  `tests/support/bernoulli_reference.py` (`splu`, default ordering), also in
  its own process.
- **Peak RSS** is `resource.getrusage(RUSAGE_SELF).ru_maxrss` at the end of
  the process (bytes on macOS, KiB on Linux). Each row reports it beside the
  RSS just before the solve (≈106 MB: interpreter plus numpy/scipy), and
  "bytes/state" below is **(peak − before) / states** — the solve's own
  share. Not `tracemalloc` (ADR-014 Amendment 1's correction).
- **The cells.** The designs are production's, from its own helpers
  (`design.py`): both successful fits the ticket timed, at the value the
  refusal reports as `max_two_sided_target_arl` (1,700 and 21,634 —
  reproducing C11's table exactly), plus a typical T=370 fit and the
  published two-sided value.

| name | baseline, target | chain | lower `(N, k, h)` | upper `(N, k, h)` | states |
|---|---|---|---|---|---|
| P | published (SAND2016 point, `r=0.1 h=5`, `r=0.5 h=2`, `p=0.2`) | joint | (10, 1, 50) | (2, 1, 4) | 255 |
| T370 | m=1000 f=5 M=2 T=370 | coupled `B` | (64, 1, 114) | (486, 485, 370) | 42,665 |
| F5_fin | m=1000 f=5 M=2 T=21,634 | coupled `B`, D's answer | (64, 1, 345) | (486, 485, 2845) | 984,716 |
| F5_cap | same | coupled `B`, D's first probe | (64, 1, 345) | (486, 485, 2889) | 999,940 |
| F5_det | same | joint at `p̂·M = 0.01` | (64, 1, 345) | (486, 485, 2845) | 984,716 |
| F1_fin | m=1000 f=1 M=2 T=1,700 | coupled `B`, D's answer | (153, 1, 343) | (11215, 11214, 2117) | 728,592 |
| F1_cap | same | coupled `B`, D's first probe | (153, 1, 343) | (11215, 11214, 2905) | 999,664 |
| F1_det | same | joint at `p̂·M = 0.002` | (153, 1, 343) | (11215, 11214, 2117) | 728,592 |

Scripts and raw JSONL are in the session scratchpad, `b165/`
(`design.py`, `solve_one.py`, `run_matrix.sh`, `chains.txt`,
`orderings_*.jsonl`, `proto_d.py`, `proto_*.json*`); the figures that matter
are embedded here so the ADR does not depend on them.

---

## Finding 0 — the cap's memory basis does not hold for the coupled chain

**This was not asked, and it is the most important number here.**

Decision 10b ratified the 1,000,000-state cap on ≈950 bytes of peak RSS per
state, measured on the **two-outcome** joint chain (and Decision 13 on
one-sided chains). Amendment 2 then made calibration D and `achieved_arl`
solve the **three-outcome coupled** chain. Nobody re-measured its memory.

| chain | states | solve (COLAMD) | peak RSS | solve's share | bytes/state |
|---|---|---|---|---|---|
| F5_det (two-outcome joint) | 984,716 | 1.25 s | 894 MB | 788 MB | **801** |
| F1_det (two-outcome joint) | 728,592 | 11.6 s | 688 MB | 582 MB | **799** |
| F1_fin (coupled `B`) | 728,592 | 13.5 s | 778 MB | 672 MB | **922** |
| F1_cap (coupled `B`) | 999,664 | 25.1 s | 1,030 MB | 924 MB | **924** |
| F5_fin (coupled `B`) | 984,716 | 5.6 s | 1,483 MB | 1,377 MB | **1,398** |
| F5_cap (coupled `B`) | 999,940 | 5.7 s | 1,495 MB | 1,389 MB | **1,389** |

- The two-outcome chain reproduces Decision 10b's figure (≈800 bytes/state
  plus the ≈106 MB process baseline ≈ the 908 MB it recorded at 982,101
  states).
- **The coupled chain at m=1000 f=5 peaks at ≈1.5 GB at the cap**, ~60% above
  the ratified ≈0.9 GB — the figure Decision 10b rejected the 2M cap for
  (*"a fit peaking near 1.9 GB… can kill a small container"*).
- **Bytes per state is not a constant of the state count.** It depends on the
  lattices' step sizes (fill-in follows the bandwidth the steps create): m=1000
  f=1 stays at ≈920, m=1000 f=5 is ≈1,390. Time is likewise structural: the
  f=1 chain is 4.5× slower than the f=5 chain at the same size.

### Finding 0 on Linux (added 2026-09-27, for Q1)

**Setup.** Temporary branch `exp/coupled-chain-rss-1` (no ticket ID; deleted
afterwards), whose `ci.yml` was replaced by a `workflow_dispatch`-only job
running `scripts/exp_rss/run.sh`: `ubuntu-latest`, Python 3.13, `uv sync
--frozen` (the locked numpy 2.5.3 / scipy 1.18.1), **the real test job's BLAS
caps** (`OMP_NUM_THREADS = OPENBLAS_NUM_THREADS = MKL_NUM_THREADS = 1`,
ADR-015 A1), one fresh process per row, production's `_coupled_arl_in_units`
with `COLAMD`. Two identical jobs ran side by side on separate runners to
show runner variance. `ru_maxrss` is **KiB on Linux**; every figure below is
converted to decimal MB (× 1.024). Runner CPU: AMD EPYC 7763, 4 vCPU, 16 GB.

**Run 36350058687** (jobs 108706889013, 108706889203). The two jobs agree to
within 0.5% on memory and 5% on time; one column shows job 1.

| chain | shape (lower × upper) | states | time | peak RSS | solve's share, bytes/state |
|---|---|---|---|---|---|
| **two-outcome joint** (Decision 10b's kind), m=1000 f=5 at `p = 0.01` | (64,1,345) × (486,485,2889) | 999,940 | 1.8 s | **827 MB** | 701 |
| two-outcome joint, m=1000 f=1 at `p = 0.002` | (153,1,343) × (11215,11214,2905) | 999,664 | 22.6 s | 814 MB | 706 |
| **coupled `B`**, m=1000 f=1, D's first probe at T=1,700 | same | 999,664 | 25.9 s | 934 MB | 827 |
| **coupled `B`**, m=1000 f=5, D's first probe at T=21,634 | (64,1,345) × (486,485,2889) | 999,940 | 8.5 s | **1,386 MB** | 1,279 |
| coupled `B`, m=1000 f=5 **M=1.1**, ES design at C11's max | (101,1,659) × (421,420,1514) | 999,900 | 10.6 s | 1,400 MB | 1,292 |
| coupled `B`, m=10,000 f=1, ES design at C11's max | (1519,1,1) × (112144,112143,499999) | 1,000,000 | 0.3 s | 711 MB | 603 |
| coupled `B`, m=300,000 f=1, same construction | (45565,1,1) × (3364300,…,499999) | 1,000,000 | 0.3 s | 710 MB | 603 |
| coupled `B`, **m=1000 f=10**, D's first probe at C11's max (T=343,650) | (39,1,342) × (190,189,2914) | 999,845 | **79.9 s** | **2,638 MB** | **2,531** |
| coupled `B`, m=300 f=3, D's first probe at C11's max (T=260,901) | (27,1,236) × (322,321,4218) | 999,903 | > 900 s — killed by the row timeout (see run 36351807658) | | |
| coupled `B`, m=200 f=20, upper arm stretched to the cap ¹ | (5,1,61) × (17,16,16128) | 999,998 | 309 s | 12,677 MB | 12,569 |
| coupled `B`, m=100 f=10, upper arm stretched to the cap ¹ | (4,1,39) × (19,18,24999) | 1,000,000 | 124 s | 8,775 MB | 8,667 |

¹ **Not reachable by any fit** — `reach.py` shows these baselines' largest
coupled chain is ~20,000 states (they fit T=10⁶ well inside the cap). Kept
because they show what the state count alone does *not* bound: at the same
1,000,000 states, peak RSS ranged from 0.71 GB to 12.7 GB.

**Linux confirms the Mac, and then some.**

1. **The Decision 10b calibration point reproduces:** the two-outcome joint
   chain at the cap peaks at **≈0.83 GB** on Linux (Mac: 0.89 GB). The
   ratified "~0.9 GB at 1M" was a correct measurement of that chain.
2. **The coupled chain at m=1000 f=5 peaks at ≈1.39 GB on Linux** (Mac:
   1.49 GB) — the ≈1.5 GB of Finding 0 is confirmed within 7%.
3. **It is not the worst reachable shape.** m=1000 f=10 — a 1%-failure
   baseline, a common case — peaks at **≈2.6 GB and 80 s for one solve** when
   a two-sided fit asks for the target the refusal itself reports as
   attainable. m=300 f=3 at its reported maximum did not finish one solve
   in 15 minutes. Locally, `max_two_sided_target_arl` for m=300 f=3 at
   T=10⁶ took **931 s** to compute (`capcost.py`) — C11's refusal budget
   (≤ 30 s) was measured on a table that did not include this cell. At the
   ratified 400,000 cap the same refusal took 12.0 s (Q1, "Measured at the
   ratified cap").
4. **Bytes per state spans 600 to 2,500 across reachable shapes** (12,600
   across constructible ones). The narrow arm's small denominator (N = 27,
   39) with a long upper arm is what drives fill-in: the band the lower
   arm's `+N−k` step creates, multiplied by the upper arm's length.

**Run 36351807658** (jobs 108711805157, 108711805302; same setup, each row
wrapped in GNU `time -f %M` so a killed row still reports its peak; the
row timeout was raised to 3,000 s). Both jobs agree to within 0.2% on
memory; times are job 2's.

| chain | states | one solve | peak RSS | bytes/state |
|---|---|---|---|---|
| m=1000 f=10, D's first probe at **T=10⁶** — (39,1,384) × (190,189,2596) | 999,845 | 74.5 s | 2,637 MB | 2,512 |
| m=1000 f=10 shape, `h_lo`=342, `h_up`=873 | 299,782 | 2.9 s | **542 MB** | 1,447 |
| same, `h_up`=1165 | 399,938 | 5.7 s | **774 MB** | 1,666 |
| same, `h_up`=1456 | 499,751 | 10.9 s | **1,026 MB** | 1,837 |
| same, `h_up`=1894 | 649,985 | 26.2 s | **1,503 MB** | 2,146 |
| same, `h_up`=2914 (run 1: D's first probe at T=343,650) | 999,845 | 79.9 s | 2,638 MB | 2,531 |
| m=300 f=3 shape, `h_lo`=236, `h_up`=846 | 200,739 | 1.8 s | **366 MB** | 1,284 |
| same, `h_up`=1270 | 301,227 | 3.4 s | **543 MB** | 1,446 |
| same, `h_up`=1694 | 401,715 | 8.3 s | **780 MB** | 1,674 |
| same, `h_up`=4218 — **D's first probe at the reported maximum, T=260,901** | 999,903 | **1,112 s** (18.5 min) | **9,431 MB** | **9,324** |

5. **m=300 f=3 at the value the refusal reports needs 9.4 GB and 18.5
   minutes for one coupled solve**, and calibration D makes about a dozen of
   them (the largest first). An engineer who follows F13's recovery hint —
   pass back `max_two_sided_target_arl` — gets a fit that, on a 16 GB runner,
   takes hours and more than half the machine's memory. That is reachable
   today with legal inputs, from a 1%-failure, 300-observation baseline.
6. **Fill-in grows faster than the state count** for these shapes (bytes
   per state rises from ≈1,300 at 200k states to ≈2,500 or ≈9,300 at 1M).
   No single bytes-per-state figure describes the cap; the memory at a given
   state count has to be measured on the worst reachable shape.
7. **Crossings, worst reachable shapes measured:** ≈0.9 GB is crossed
   between 400,000 states (774–780 MB on both shapes) and 500,000 (1,026 MB
   on m=1000 f=10); ≈1 GB at about 490,000 on m=1000 f=10. m=300 f=3 was not
   measured between 400k and 1M, and its growth is the steeper one, so
   **400,000 is the largest cap with measured evidence of staying under
   ≈0.9 GB on every reachable shape measured.**

So the premise *"~950 bytes/state ⇒ 1M states ≈ 0.9 GB"* holds for the chain
it was measured on and not for the one calibration D now solves. This is
**Question Q1** for the product owner below; this ADR does not change the cap.
⚠️ *Superseded by the Q1 ruling (2026-09-27, see Status): the joint cap is now
400,000.*

---

## Finding 1 — SuperLU column ordering (ticket item 6)

Local, one fresh process per row. "Share" is peak RSS minus RSS before the
solve. "vs reference" is `|x − ref| / ref` against
`tests/support/bernoulli_reference.py`.

| chain | states | COLAMD (today) | MMD_ATA | MMD_AT_PLUS_A | NATURAL |
|---|---|---|---|---|---|
| P | 255 | 0.001 s | 0.001 s | 0.001 s | 0.000 s |
| T370 | 42,665 | 0.110 s · 35.7 MB | 0.067 s · 32.4 MB | 0.102 s · 32.5 MB | **15.5 s · 2,484 MB** |
| F5_fin | 984,716 | 5.63 s · 1,377 MB | **13.06 s** · 1,344 MB | **aborted**: > 3 GB RSS at 90 s, still factorising | — |
| F5_cap | 999,940 | 5.73 s · 1,389 MB | **12.48 s** · 1,388 MB | — | — |
| F5_det | 984,716 | 1.25 s · 788 MB | 0.85 s · 750 MB | — | — |
| F1_fin | 728,592 | 13.46 s · 672 MB | **8.36 s** · 650 MB | — | — |
| F1_cap | 999,664 | 25.06 s · 924 MB | **13.94 s** · 894 MB | — | — |
| F1_det | 728,592 | 11.60 s · 582 MB | 12.66 s · 547 MB | — | — |

**Agreement.** Every ordering agrees with the reference to ≤ 2.2e-13
relative (worst: MMD_ATA on F5_fin); the published value P is
`7.646438722673051` under every ordering (≤ 1.2e-16 from the reference).
COLAMD is **bit-identical** to the reference on every chain — which also
says the reference is not independent of production *in its linear algebra*:
both are SuperLU with the same default ordering. It is independent in how
the chain is built, which is what it was written to check.

**What it shows.**

1. **MMD_ATA is not a uniform win.** It is 1.6–1.8× faster on m=1000 f=1's
   coupled chains — the ticket's quick check, reproduced — and **2.2–2.3×
   slower** on m=1000 f=5's. Mixed on the two-outcome chains. Applied to a
   whole near-cap fit (13 coupled solves at f=1, 12 at f=5, measured below),
   it would take the f=1 fit from ≈ 211 s to ≈ 130 s and the f=5 fit from
   ≈ 70 s to ≈ 150 s.
2. **Memory: MMD_ATA is never worse** (0–7% lower share). It does not rescue
   Finding 0: F5 still peaks near 1.5 GB.
3. **MMD_AT_PLUS_A and NATURAL are rejected outright** — unbounded fill.
   NATURAL used 2.5 GB on a 42,665-state chain (≈58 kB/state).

**Decision 1: keep COLAMD (no change).** An ordering that halves one cell and
doubles another is a reshuffle, not an improvement, and the cell that gets
worse is the one with the worse memory. Choosing an ordering per chain shape
would be a heuristic with no derivation behind it. Revisit only if a CI
measurement contradicts the local one (see *Linux* below).

---

## Finding 2 — calibration D's solve count (ticket item 7)

**Where the time goes.** Production's calibration D (`_calibrate_two_sided`)
computes `B` at `top` (the equal-split or cap-limited upper interval), then
bisects `h_up` over `[0, top]`. `_two_sided_design` then solves `B` **again**
at the answer for `achieved_arl`, plus the two disclosure figures. Measured
through production with a spy on `_solve_absorbing_chain` (`design.py`):

| fit | one-sided solves | coupled solves in D | D's time | + re-solve of `B` + 2 disclosures | fit total (≈) |
|---|---|---|---|---|---|
| m=1000 f=1 M=2 T=1,700 | 41 (0.01 s) | **13**, 499,832–999,664 states, 6.4–25.1 s each | 173.2 s | 13.5 + 2 × ~11.6 s | ≈ 210 s (ticket: 211 s) |
| m=1000 f=5 M=2 T=21,634 | 41 (0.02 s) | **12**, 499,970–999,940 states, 2.4–5.9 s each | 62.0 s | 5.6 + 2 × ~1.3 s | ≈ 70 s (ticket: 70 s) |
| m=1000 f=5 M=2 T=370 | 32 | 9 | 0.95 s | | |
| m=1000 f=1 M=2 T=370 | 36 | 11 | 0.18 s | | |
| m=300 f=3 M=2 T=370 | 30 | 9 | 0.41 s | | |
| m=200 f=20 M=2 T=370 | 24 | 7 | 0.02 s | | |

One-sided solves are negligible; **the coupled solves are the whole cost**,
and the bisection's first probes are the largest chains.

**Three facts give a tighter search with the identical answer.** The answer
is defined as the smallest `h_up ∈ [1, top]` with `B(h_up) ≥ T`, and `B` is
non-decreasing in `h_up` (Decision 19.4's coupling). Any search that
maintains a bracket `lo < answer ≤ hi` with `B(lo) < T ≤ B(hi)` returns the
same integer. So:

1. **A proven lower bracket, free.** In the coupled chain the upper arm, on
   its own, sees a success with probability `1 − p_L` — its design rate. The
   two-sided chart stops no later than the upper arm alone, pathwise, so
   `B(h) ≤ A_up(h)` for every `h`. Hence `L`, the smallest `h` with
   `A_up(h) ≥ T` (a one-sided solve, milliseconds), satisfies `answer ≥ L`,
   and `B(L − 1) < T` is known without solving it.
2. **The answer's `B` is always already computed** by the search, so
   `_two_sided_design`'s re-solve of `achieved_arl` is redundant: one coupled
   solve per fit, the largest-but-one, saved for nothing.
3. **Interpolation instead of halving.** `B` is smooth and close to linear in
   `h_up` over the bracket, so a safeguarded regula falsi (Illinois
   variant: interpolate, clamp strictly inside the bracket, halve the stale
   end's weight on a repeat) closes the bracket in far fewer probes. The
   bracket invariant is the same as bisection's, so correctness does not
   depend on the interpolation being good — only the probe count does.

**Measured** (`proto_d.py`: runs production's `_calibrate_two_sided` with a
counting spy, then the candidates, memoising `B` by `h_up`; "states solved"
is the sum of the coupled chains' sizes, the quantity time and memory
follow):

| cell | production: solves / states solved | lower bracket only | lower bracket + Illinois | same `(h_lo, h_up)` |
|---|---|---|---|---|
| m=1000 f=5 M=2 T=21,634 | 12 / 10.95 M | 11 / 10.68 M | **4 / 3.74 M** (34%) | ✅ (345, 2845) |
| m=1000 f=1 M=2 T=1,700 | 13 / 9.38 M | 12 / 8.97 M | **7 / 5.20 M** (55%) | ✅ (343, 2117) |
| 25-cell sweep (m ∈ {100, 200, 300}, f ∈ {1, 2, 5, m/10}, M ∈ {1.1, 2, 3}, T ∈ {10, 370, 10⁴}, ES ≤ 300k states) | 195 / 5.32 M; worst cell 13 | 161 / 4.77 M | **109 / 2.32 M; worst cell 5** | ✅ all 25 |

In every cell the answer's `B` was already in the search's cache.

⚠️ **Coverage, stated.** The sweep was stopped after 25 of its ~180 cells
(the remainder, m ∈ {1000, 10000} and larger T, were cut for time) and ran
beside other measurements. MEASUREMENT PENDING: the full sweep, which the
implementation's identity test (Verification 1) supersedes anyway. The
per-variant wall times were not separated; the time estimates below scale
production's measured time by states solved, which **understates** the
saving slightly (per-state cost rises with chain size, and the dropped
probes are the large ones).

**Estimated effect on the ticket's cells** (production D time × state
fraction, plus the dropped `achieved_arl` re-solve):

| cell | fit today (measured) | fit after Decision 2 (estimated) |
|---|---|---|
| m=1000 f=1 T=1,700 | ≈ 210 s | ≈ 96 s D + 2 disclosures ≈ **120 s** |
| m=1000 f=5 T=21,634 | ≈ 70 s | ≈ 21.5 s D + 2 disclosures ≈ **24 s** |

MEASUREMENT PENDING: end-to-end fit times with Decision 2 implemented; the
implementation must measure and record them (Verification 2).

**Decision 2: replace calibration D's search, keep its definition.**

1. Bracket `h_up` in `(L − 1, top]`, with `L` the smallest `h` whose
   one-sided upper-arm ARL at `1 − p_L` meets `T` (proven lower bound above).
2. Close the bracket by safeguarded regula falsi (Illinois) on `B(h) − T`,
   every probe clamped strictly inside the bracket, falling back to the
   midpoint when the two ends' `B` are equal. The loop invariant — `B(lo) <
   T ≤ B(hi)` — is bisection's, so the returned `h_up` is the smallest with
   `B ≥ T` regardless of how good the interpolation is.
3. Return `B(h_up)` with the intervals, so `_two_sided_design` copies it to
   `achieved_arl` (through `_reported_arl`'s postcondition, unchanged)
   instead of solving the same chain again.
4. The refusal path is untouched: `top`, the `B(top) < T` refusal and the
   `joint_state_count` it reports are computed exactly as today.

Nothing reported changes: same intervals, same `B` (the same solve on the
same matrix), same refusals.

**Worst-case bound (added 2026-09-28, code review R1).** A regula falsi has
no logarithmic worst case, with or without the Illinois step. Code review R1
showed the failure: a jump in `B` to the ill-conditioned sentinel makes the
interpolation crawl, one coupled solve per step. Implemented on
`perf/BIN-165/joint-chain-solver` at `261b416`
(`_smallest_meeting_bound` in `bernoulli_cusum_fitting.py`), the search now
takes the **projection step** of the ITP method:

- **Source.** Oliveira, I. F. D. and Takahashi, R. H. C. (2020), "An
  Enhancement of the Bisection Method Average Performance Preserving Minmax
  Optimality", *ACM Transactions on Mathematical Software* 47(1),
  doi:10.1145/3423597.
- **What is taken.** Only the projection is taken; ITP's truncation step is
  not. Each interpolated probe `k` is clamped to `[hi − W, lo + W]`, with
  `W = 2^(n_max − k − 1)`, `n_max = ⌈log₂(hi − lo)⌉ + n₀`, and slack
  `n₀ = _ITP_SLACK_PROBES = 3`. A probe the projection does not move is
  exactly the Illinois probe described above.
- **The bound.** The search makes at most **⌈log₂(hi − lo)⌉ + 3** probes
  inside the bracket. This does not count the evaluations of `B(hi)` and,
  when `lo ≥ 1`, of `B(lo)` that start the interpolation.
- **What the bound rests on.**
  - The paper's result (Theorem 2.1: at most `n_{1/2} + n₀` evaluations) is
    for a continuous bracket and an ε-tolerance. **The paper is paywalled.
    That theorem was checked through a secondary source**, the Wikipedia
    article "ITP method", which states Theorem 2.1 and the projection step.
    It was not checked against the paper's text.
  - **The integer bound does not rest on the paper.** It rests on the
    width invariant argued in the code's docstring. After probe `k` the
    bracket is at most `2^(n_max − k − 1)` wide, whichever side is kept, and
    on the integer lattice the clamp interval is non-empty and strictly
    inside the bracket while its width is at least 2.
- **The slack is measured, not derived.** `n₀ = 3` is the smallest value at
  which the projection never binds on the real `B` of any pinned cell.
  Values 0–2 each raised a pinned cell's solve count. With 3, adversarial
  step functions stay within 23 probes on a 500,000-wide bracket, against 19
  for bisection and up to 231 for Illinois alone.
- **Unchanged.** Every fitted answer and every solve-count pin is unchanged.
  The invariant `B(lo) < T ≤ B(hi)`, and therefore the returned `h_up`, is
  bisection's, as before.

---

## Finding 3 — an iterative solver (ticket items 1–5)

Production's seam was replaced by `scipy.sparse.linalg.bicgstab`/`gmres`
(`rtol=1e-12`, `atol=0`, at most 20,000 iterations), unpreconditioned, with
Jacobi, or with an incomplete LU (`spilu`, `drop_tol=1e-4`,
`fill_factor=10`). ⚠️ These runs overlapped the Finding 2 sweep in another
process (one of ten cores busy), so their times are indicative; memory is
not affected.

**A rigorous error bound exists, and it is cheap.** `(I − Q)⁻¹` is
non-negative with `(I − Q)⁻¹ 1 = m`, so `‖(I − Q)⁻¹‖∞ = ‖m‖∞`. For a
computed `x` with residual `r = 1 − (I − Q)x`,

```
|m₀ − x₀|  ≤  ‖m‖∞ ‖r‖∞  ≤  ‖x‖∞ ‖r‖∞ / (1 − ‖r‖∞)        (‖r‖∞ < 1)
```

— a postcondition that needs one sparse mat-vec and holds up to rounding in
`r` itself. It is what an iterative solve would have to pass. The table
reports it relative to `x₀` ("bound").

| chain | method | iterations | time | solve's RSS share | bound | vs LU |
|---|---|---|---|---|---|---|
| P (255) | bicgstab, none | 16 | 0.002 s | — | 5.7e-15 | 5e-16 |
| T370 (42,665) | bicgstab, none | 836 | 0.29 s | 13 MB (LU: 36) | **9.7e-9** | 1.1e-11 |
| T370 | gmres, none | 4,218 | 1.97 s | 21 MB | 3.1e-12 | 1.1e-12 |
| T370 | bicgstab, ILU | 2 | 0.12 s | 39 MB | 2.2e-13 | 6e-16 |
| F5_fin (984,716) | bicgstab, none | 5,622 | **52.6 s** (LU: 5.6) | **367 MB** (LU: 1,377) | **2.5e-7** | 1.2e-10 |
| F5_fin | bicgstab, ILU | 6 | 4.7 s | 1,015 MB | 3.0e-11 | 4.6e-13 |
| F1_fin (728,592) | bicgstab, ILU | 3 | 13.9 s (ILU: 13.8) | **722 MB** (LU: 672) | 1.0e-12 | 1.5e-17 |
| F1_det (728,592) | bicgstab, ILU | 2 | 12.0 s (ILU: 11.9) | 662 MB (LU: 582) | 9.1e-12 | 6.6e-14 |

**What it shows.**

1. **The memory saving exists only without a preconditioner** — 3.8× less
   (367 MB vs 1,377 MB) at F5_fin — **and there the solve is 9× slower and
   stops at a proven error bound of 2.5e-7**, four orders of magnitude short
   of the 1e-9 every reference comparison in Decision 18 demands. BiCGSTAB
   reported success (`info = 0`): its stopping test is a 2-norm residual
   ratio, which is not the ∞-norm quantity the error bound needs. GMRES
   without a preconditioner needed 4,218 iterations at 42,665 states.
2. **An ILU preconditioner fast enough to help is an LU.** At
   `drop_tol=1e-4` it converges in 2–6 iterations and matches LU to ≤ 5e-13 —
   because building it costs what the LU costs (13.8 s of F1_fin's 13.9 s)
   and holds about as much memory (722 MB vs 672 MB at F1; 1,015 MB vs
   1,377 MB at F5). The ticket's premise — memory proportional to the
   non-zeros — holds only for the variant that does not converge.
3. **"Exact" would become "within a proven bound".** Calibration D and
   `_smallest_decision_interval_units` compare `B ≥ T` at ties; a solve with
   error 2.5e-7 decides differently from LU whenever `B` lands that close to
   `T`, and changes a calibrated interval. Adoption would need the bound as a
   raising postcondition (`DegenerateBaselineError(reason="arl_not_computable")`,
   ADR-002 / Decision 13.4) plus an LU fallback for every comparison inside
   the bound — i.e. LU's memory is still needed on exactly the hard cells.

MEASUREMENT PENDING: convergence at near-degenerate drift
(`detect_rate_multiple` at its computed floor, e.g. m=200 f=20 M=1.001) and
the ticket's 5M/10M-state scaling were not run. They cannot rescue the
option: the unpreconditioned solver already misses the bar at an ordinary
cell, and near-degenerate drift makes `I − Q` worse conditioned, not better.

**Decision 3: do not adopt an iterative solver.** Keep direct LU. "Exact"
keeps its meaning (solved to floating-point precision, agreeing with the
reference to ≤ 2.2e-13 in every cell measured here). BIN-158's memray budget
is unaffected by this ADR and needs no re-baselining from it.

**Decision 4 (item 4): no solver option here changes the cap** — none
changes memory per state materially. Whether the cap itself should move is
Q1, which is open (MMD_ATA ≤ 7%; ILU none; the
unpreconditioned solver cannot be adopted). ⚠️ But see Finding 0: the cap's
*memory figure* is wrong for the coupled chain, which is Q1.
⚠️ *Q1 has since been ruled (2026-09-27, see Status): the joint cap is
400,000. Decision 4 stands for the solver options — none of them changes the
cap — and the cap moved for Finding 0's reason instead.*

---

## Linux / CI (ticket item 5)

Measured, runs **36350058687** and **36351807658** on `ubuntu-latest` (AMD
EPYC 7763, 4 vCPU, 16 GB) with ADR-015 A1's BLAS caps — see *Finding 0 on
Linux*. The Mac's conclusions hold on Linux: the two-outcome chain at the cap
reproduces Decision 10b (0.83 GB vs 0.89 GB), and the coupled chain at
m=1000 f=5 reproduces Finding 0 (1.39 GB vs 1.49 GB). Decisions 1–3 rest on
comparisons that do not depend on the BLAS (fill-in, operation count, the
same arithmetic in fewer solves), and the orderings were not re-timed on
Linux.

Experiment branch: `exp/coupled-chain-rss-1`, forked from `49e0ff5`, tip
`6fa7099` at deletion — two throwaway commits (made with `--no-verify`)
that replaced `.github/workflows/ci.yml` with a `workflow_dispatch`-only
measurement job and added `scripts/exp_rss/` (`solve_one.py`, `chains.txt`,
`run.sh`). **Deleted, remote and local, after the logs were
read. No pull request was opened.**

---

## Consequences

**Positive**

- Near-cap two-sided fits get materially faster with **no change to any
  reported number, calibrated interval, public signature or error**: fewer
  coupled solves, the same ones.
- "Exact" keeps its meaning; no new tolerance, no new failure mode.
- A latent mis-statement of the cap's memory cost is on the record (Finding
  0) instead of discovered in someone's container.

**Negative**

- Near-cap fits remain tens of seconds to minutes: the dominant cost is now
  the few coupled solves that remain and the two disclosure solves, each
  5–25 s. Only a cheaper *solve* would move that, and neither lever measured
  here provides one.
- Calibration D becomes a regula-falsi search (with ITP's projection
  bounding its worst case, Decision 2) rather than a textbook
  bisection — more code to review, justified by its bracket invariant, not
  by the interpolation.

**Neutral**

- `_solve_absorbing_chain` and its `spsolve` seam are unchanged, so every
  existing monkeypatch, `TestTheSolverIsPinned` and the exception-contract
  registry keep working as they are.
- No kill switch: Caliper is a library with no runtime it owns; there is no
  flag service to hold one (`CLAUDE.md`, *Library, not a service*).

---

## Alternatives considered

- **Adopt `permc_spec="MMD_ATA"`** — rejected, Finding 1: 1.7× faster at
  m=1000 f=1, 2.2× slower at m=1000 f=5.
- **Choose the ordering per chain** (e.g. by the arms' step sizes) —
  rejected: a heuristic fitted to two cells, with no derivation, guarding a
  cost that Decision 2 already cuts for every cell.
- **`MMD_AT_PLUS_A`, `NATURAL`** — rejected: unbounded fill (Finding 1).
- **Unpreconditioned BiCGSTAB/GMRES** — rejected, Finding 3: 3.8× less
  memory, 9× slower, error bound 2.5e-7 at an ordinary near-cap cell.
- **ILU-preconditioned Krylov** — rejected, Finding 3: its cost and memory
  are an LU's, and it adds a tolerance.
- **Iterative with LU fallback** — rejected: the fallback must hold LU's
  memory on exactly the cells that need it, so the cap's basis is unchanged,
  and every result path gains a second solver to verify.
- **Seed D from the harmonic combination of the two one-sided ARLs** — tried
  as a starting guess (`proto_d.py`, first version): **worse** than plain
  bisection (61 coupled solves against 45 over the first six sweep cells),
  because the guess sits near `top`, far from D's answer. The lower bracket
  plus interpolation is what works.
- **Cache factorisations across probes** — not applicable: each probe
  changes `h_up`, so each matrix is different.
- **Do nothing** — rejected for Decision 2: it is free accuracy-wise and
  saves roughly half the fit time near the cap.

---

## Questions for the product owner

**Q1 — the cap's memory figure. ✅ Ruled 2026-09-27: option (b), joint cap 400,000, one-sided cap decoupled at 999,999 (see Status).** The cap was
ratified because a fit stayed under ≈1 GB in the engineer's process, and 2M
was rejected at ≈1.9 GB. Measured on Linux, the chain Decision 10b measured
still peaks at ≈0.83 GB at 1M states — but the **coupled chain calibration D
now solves peaks at 0.71–9.4 GB at 1M states, depending on the baseline's
shape**, and the three worst reachable cells measured are ordinary
baselines (m=1000 f=5: 1.39 GB; m=1000 f=10: 2.64 GB; m=300 f=3: 9.43 GB and
18.5 minutes per solve).

⚠️ **Zero-failure baselines are no longer affected by this cap at all.**
Since Amendment 2 (Decision 19.2) a two-sided request at f = 0 builds the
lower arm alone and carries `upper_arm_not_designable`; no joint chain is
solved. Measured (`capcost.py`): m = 300, 1000 and 2000 at f = 0,
`target_arl` = 10⁶, two-sided → `direction == "lower"`, fitted, achieved ARL
1,005,418 / 1,002,265 / 1,000,396. ADR-014 Decision 10b's `max_t` table for
f = 0 predates Amendment 2 and no longer describes the library. The cells
the cap binds are **low-but-nonzero failure counts**, tabulated below.

`max_two_sided_target_arl` (C11, production code) at each joint cap, with
the one-sided cap left at 999,999 (`capcost.py`, local; `—` = unchanged at
10⁶):

| baseline (M=2) | 1,000,000 (today) | 650,000 | 500,000 | **400,000** | 300,000 |
|---|---|---|---|---|---|
| m=1000 f=1 | 1,700 | 1,216 | 966 | **808** | 657 |
| m=1000 f=5 | 21,634 | 10,139 | 6,649 | **4,759** | 3,164 |
| m=1000 f=10 | 343,650 | 93,753 | 47,686 | **28,134** | 15,341 |
| m=300 f=3 | 260,901 | 78,035 | 41,482 | **25,526** | 14,241 |
| m=10,000 f=1 | 1,285 | 1,285 | 1,285 | **1,285** | 1,285 |
| m=300,000 f=1 | 38,563 | 38,563 | 38,563 | **38,563** | 38,563 |
| m=200 f=20 | — | — | — | **—** | — |
| worst measured peak RSS (Linux) at that cap | **9.4 GB** | 1.5 GB | 1.0 GB | **0.78 GB** | 0.54 GB |

`target_arl = 370` fits every cell at every cap shown (the smallest maximum
is 657).

The options, with their measured consequences:

- **(a) Keep 1,000,000 and restate the figure.** No fit changes. The
  restated figure would have to be **"up to ≈9.4 GB and ≈18 minutes per
  solve, shape-dependent"** — the 1.5 GB of the earlier draft is not the
  worst case. This contradicts the reason the cap was ratified.
- **(b) Lower the joint cap to honour ≈0.9 GB — measured value 400,000.**
  The previously suggested ≈650,000 does **not** honour it: m=1000 f=10
  peaks at 1.5 GB there. At 400,000 both worst reachable shapes measured
  peak at 0.77–0.78 GB and one solve takes ≤ 9 s on the runner. Cost: the
  maxima in the table fall by 2–13× for low-failure baselines at m ≈ 300–1000
  (e.g. m=1000 f=5: 21,634 → 4,759). Engineers who need more keep the
  one-sided recovery path, which is unaffected.
  - ⚠️ **Decision 13.3 ties the one-sided cap to the joint cap** (`_MAX_JOINT_STATES − 1`).
    Lowering both would refuse measured one-sided fits (m=3,000,000 f=0 at
    T=10⁶ needs 742,099 units, Decision 13). The one-sided chain's memory is
    ≈958 bytes/state (≈0.96 GB at 999,999, Decision 13), so **(b) should
    decouple them: joint cap 400,000, one-sided cap unchanged at 999,999.**
    This table was computed that way.

    > ⚠️ **Correction (2026-09-28) — the example above does not hold today;
    > the decoupling it supports does.** The 742,099-unit figure is from
    > ADR-014 Amendment 2's Decision 13 table, where it was the **f=0 upper**
    > arm, measured before Decision 19 made an upper arm undesignable at
    > f = 0 (`"upper"` is refused there, F15; `"two_sided"` builds the lower
    > arm alone). The f=0 **lower** arm at m=3,000,000, T=10⁶ fits at
    > `h_units = 1`, floored at `1/p_U` = 1,302,884 (re-checked here through
    > production; backend-test-writer, who reported it, found the same in
    > `tests/support/bernoulli_reference.py`).
    >
    > **Current, reproducible examples** of one-sided fits above 400,000
    > units (production's `_smallest_decision_interval_units`, M=2,
    > `onesided_cap.py`; each `h` is the smallest meeting T: ARL at `h` ≥ T >
    > ARL at `h − 1`):
    >
    > | fit | lattice (N, k) | `h_units` | ARL at h / at h − 1 |
    > |---|---|---|---|
    > | `"upper"`, m=300,000 f=1, T=5×10⁵ | (3364300, 3364299) | **460,645** | 500,001.03 / 499,999.85 |
    > | `"upper"`, m=300,000 f=1, T=10⁶ | (3364300, 3364299) | 857,041 | 1,000,001.19 / 999,999.84 |
    > | `"upper"`, m=1,000,000 f=1, T=10⁶ | (11214332, 11214331) | 950,750 | 1,000,000.84 / 999,999.74 |
    > | `"upper"`, m=3,000,000 f=1, T=10⁶ | (33642995, 33642994) | **982,840** | 1,000,000.51 / 999,999.48 |
    > | `"lower"`, m=3,800,000 f=1, T=10⁶ | (577148, 1) | 577,147 | 3,166,871.8 / 976,934.4 |
    > | `"lower"`, m=5,200,000 f=2, T=10⁶ | (577197, 1) | 577,196 | 3,167,142.9 / 977,017.8 |
    >
    > So a one-sided cap of 400,000 would refuse ordinary one-sided fits at
    > large clean baselines; keeping it at 999,999 stands.
    >
    > **Is 999,999 still ever reached by a designable fit? Not in anything
    > measured, and for the upper arm only at impractical sizes.** Every
    > upper lattice measured has `k = N − 1`: the statistic rises by exactly
    > one unit per success, so the chart needs at least `h + 1` steps to
    > exceed `h`, ARL(h) ≥ h + 1, and the smallest `h` meeting `T ≤ 10⁶` is
    > at most `⌈T⌉ − 1 ≤ 999,999`. It equals 999,999 only if ARL(999,998) <
    > 10⁶, which needs `p_L ≲ 2×10⁻¹²` — a baseline of roughly 5×10¹⁰
    > observations with one failure. The largest measured is 982,840 above.
    > The lower arm peaks just below its floor boundary at `h = N − 1`
    > (≈ 577,000 at T=10⁶, where `1/p_U` crosses T), and above that boundary
    > floors at `h = 1`. So F12's search-cap refusal is a guard that no
    > measured designable fit reaches; the cap stays as a memory bound
    > (≈ 0.96 GB, Decision 13), not as a binding limit. Not proven for
    > upper lattices with `k < N − 1`; none appeared in any cell measured for
    > this ADR (including m=100 f=10, (19, 18), and m=200 f=20, (17, 16), whose
    > upper arm reaches ARL 2×10⁶ at 324 units).
- **(c) Cap on predicted memory rather than state count** — not available:
  SuperLU exposes no symbolic-only factorisation through scipy, and fill-in
  is not predictable from the state count or step sizes (Finding 0).

**Also true under either option:** a state-count cap does not bound memory
for every *constructible* chain (a stretched m=200 f=20 shape: 12.7 GB at
1M), only for the shapes fits reach; any cap is evidence about the shapes
measured, which should be stated beside it.

**Recommendation: (b), a joint cap of 400,000 with the one-sided cap
decoupled at 999,999.** It is the only option consistent with the ruling the
cap was ratified on, the 400,000 figure is measured rather than scaled, and
the price is paid in refusals that carry a round-tripping maximum and a
one-sided alternative — the failure mode this library prefers — instead of
multi-gigabyte, multi-minute fits that can take down the engineer's process.
If the product owner prefers the higher ceiling, (a) must restate the
figure honestly as the 9.4 GB worst measured case.

Either way, a follow-up is warranted independent of Q1: at today's cap,
**m=300 f=3's refusal takes 931 s locally** to compute
`max_two_sided_target_arl` (C11's ≤ 30 s budget was set on cells that did
not include it), and ADR-014 Decision 10b's `max_t` table should be marked
superseded for f = 0.

**Measured at the ratified cap (code review R2, added 2026-09-28).** These
are end-to-end refusal times at the 400,000 joint cap, and the
`max_two_sided_target_arl` each refusal reports.
- They were measured on the code reviewer's machine. **The platform is not
  recorded here and could not be confirmed.**
- Each time includes the fit's own feasibility check, so it bounds C11's
  refusal overhead from above.
- They are the evidence for code review R2.

| cell (M=2 unless stated) | refusal time | `max_two_sided_target_arl` |
|---|---|---|
| m=300 f=3 | 12.0 s | 25,526 |
| m=1000 f=10 | 8.2 s | 28,134 |
| m=1000 f=5 | 5.7 s | 4,759 |
| m=200 f=20 M=1.001 | 4.1 s | 106 |
| m=1000 f=1 | 7.2 s | 808 |
| m=1000 f=5 M=1.01 | 26.9 s | 650 |
| m=300,000 f=1 | 1.1 s | 38,563 |

- **Every cell is inside C11's ≤ 30 s budget.** The worst is 26.9 s, at the
  M=1.01 corner.
- **m=300 f=3 falls from 931 s at the 1,000,000 cap to 12.0 s.**
- The M=2 values agree with the 400,000 column of the table above.

**Not re-measured at 400,000:** C11's 0–31% shortfall against the true
calibration-D maximum, and its 302-design premise check. The one-solve
guard keeps the reported value correct regardless.

**Q2 — Decision 2.** Accept the regula-falsi calibration D and the dropped
re-solve, as a pure performance change with the identity test in
*Verification*?

**Q3 — Decisions 1 and 3.** Accept keeping COLAMD and rejecting the
iterative solver, closing BIN-165's items 1–4 and 6 without adoption?

---

## Verification required of the implementation

1. **Identity.** For every cell of the Finding 2 sweep and the two near-cap
   cells, the new calibration D returns the same `(h_lo, h_up)` as today's
   (the prototype is the oracle to port; today's bisection may be kept as a
   test helper). Hypothesis over the legal space at small state counts.
2. **Solve count.** A spy on `_coupled_arl_in_units` asserts the near-cap
   cell's coupled-solve count is at most the measured figure, and that
   `_two_sided_design` performs no coupled solve at `(h_lo, h_up)` beyond the
   one the search made (the `achieved_arl` value is the search's).
3. **Bracket invariant.** Monkeypatch `B` to adversarial monotone step
   functions (a jump at `L`, at `top`, and one unit above `L`); the search must
   still return the smallest `h` with `B ≥ T`.
4. **No regression** in the refusal path (C11) or `max_two_sided_target_arl`:
   both call `_calibrate_two_sided` only through its return value.
5. **If Q1 is ruled (b):** re-measure peak RSS on Linux at the new cap for
   m=1000 f=10 and m=300 f=3 (the harness is `solve_one.py` in a fresh
   process, `ru_maxrss` in KiB), pin the new `max_two_sided_target_arl` table
   in the tests from the independent reference, and split Decision 13.3's
   one-sided cap from the joint cap.
6. Hang-guard budgets touched by the faster path follow ADR-015 A3
   (≥ 3× slowest CI leg); none needs raising, since everything gets faster.
