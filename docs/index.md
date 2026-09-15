# Caliper

**Statistical Process Control for LLM-as-a-judge agent quality scores.**

Your dashboard says the average score dropped from 8.1 to 7.6. Caliper answers
the question the dashboard cannot: **is that a real change, or is it noise?**

Caliper treats LLM-as-a-judge as a *measurement instrument* and applies
Statistical Process Control as the signal detection layer on top of it. You
choose a false alarm rate. The library derives control limits that deliver it,
and tells you what it actually achieved.

---

## The claim, stated plainly

**Your monitoring should have a known false alarm rate.**

Most quality alerting uses a threshold somebody picked. If you set it tight you
drown in false alarms; if you set it loose you find out from your users. Neither
setting has a stated error rate, so neither can be defended when someone asks
why it is where it is.

Caliper takes the error rate as the *input*:

```python
fitted = fit_ewma(baseline, target_arl=370.0)
```

`target_arl=370` means: **while nothing is actually wrong, expect a false alarm
about once every 370 observations.** That is a parameter you chose, with known
statistical properties, and the fitted artefact reports what the calibration
achieved so you can check it:

```python
print(fitted.requested_arl, fitted.achieved_arl)   # 370.0 370.0
```

## What it does not do

Scope discipline is a feature, so it is worth being explicit.

Caliper does **not** capture traces, render dashboards, manage prompts, store
your data, run eval suites, or call an LLM. It has no server, no database, and
no network code — three runtime dependencies (`numpy`, `scipy`, `pydantic`) and
no I/O of any kind.

It detects drift. It plugs into what you already use.

## Where to go next

| | |
|---|---|
| [Quickstart](quickstart.md) | A complete, runnable programme — judge to signal |
| [What the numbers mean](concepts.md) | ARL₀, Phase I and Phase II, with no SPC background assumed |
| [Choosing a chart](charts.md) | EWMA, CUSUM or Shewhart, and how to decide |
| [Errors](errors.md) | What Caliper refuses to do, and why each refusal exists |
| [Reference](reference/measurement.md) | The full API, generated from the source |
| [Decisions](architecture/index.md) | Every architectural decision, including the rejected ones |

## Why the decisions are published

The brand this project writes under calls it *the authority of showing your
work*, which in practice means three commitments you can check rather than take
on trust:

**Control limits are derived, not chosen.** Nothing in this library contains a
threshold somebody felt was about right.

**Every constant cites a primary source.** `d₂ = 1.128` appears in the code with
*Montgomery, Introduction to Statistical Quality Control, Appendix VI* beside
it.[^d2] Where a value could not be verified against a primary source, the work
stopped rather than approximating.

**The test suite verifies against published tables.** The EWMA calibration is
checked against all ten multipliers in Table 3 of Lucas & Saccucci (1990);[^ls]
the CUSUM approximation reproduces Montgomery's worked example to four
significant figures.

[^d2]:
    Montgomery, D.C. *Introduction to Statistical Quality Control*, 7th ed.,
    Wiley 2013, Appendix VI. The exact value is $d_2 = 2/\sqrt{\pi}$ for
    subgroups of size two, which is what a moving range of consecutive
    individual observations is.

[^ls]:
    Lucas, J.M. and Saccucci, M.S. (1990). "Exponentially Weighted Moving
    Average Control Schemes: Properties and Enhancements." *Technometrics*
    32(1):1–12. Table 3.
