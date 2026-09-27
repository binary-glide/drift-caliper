# ADR-015: Parallel, shuffled test execution, and sorted dependency lists

**Status:** ✅ **ACCEPTED — ratified by the product owner 2026-09-27.** Q1–Q4
were answered as recommended: the serial `wall_clock` step replaces
`loadgroup` (Q1); a hang guard running above 40 s of its 60 s on CI may be
raised to 3× the CI-measured duration, the measurement cited beside it (Q2);
the nightly full run goes parallel too, after the pre-merge full-suite
`workflow_dispatch` run in Verification item 7 (Q3); the ticket text is
corrected (Q4).
> ⚠️ **Amendment 1 (2026-09-27, ACCEPTED) is at the end of this ADR.** The
> pre-merge full-suite run failed on all three legs. Amendment 1 re-measures on
> CI and **supersedes** Decisions 2 and 6 and the Q2 and Q3 answers above: the
> nightly/dispatch run is serial, the test job caps BLAS threads, and hang-guard
> budgets follow the "≥ 3× slowest CI leg" rule. Read it before relying on any
> of those.

**Date:** 2026-09-25
**Deciders:** system-architect (proposal); product owner (ratification pending)
**Refs:** BIN-155, BIN-133, BIN-124, BIN-89, BIN-154, ADR-007, ADR-014 (C11)

## Context

BIN-155 asks for three things:

1. Run the suite in parallel with `pytest-xdist`.
2. Shuffle test order on every run with `pytest-randomly`.
3. Sort `pyproject.toml`'s dependency lists and keep them sorted.

The ticket fixes three parts of the scope. The local default stays serial.
Nothing becomes a pre-commit hook. tox and nox are out of scope (BIN-154).

Why this is an ADR rather than a CI tweak:

- The shuffle and the parallelism are **the suite's isolation check**. If the
  suite passes only in one order, or only in one process, it is not
  deterministic, and `CONTRIBUTING.md` says it must be.
- The Bernoulli CUSUM tests from BIN-133 / ADR-014 depend on the machine. 196
  tests carry `@pytest.mark.timeout`. Two assert on elapsed wall-clock time.
  Several spawn child processes (`tests/support/isolated_bernoulli_fit.py`),
  and some fits peak near 0.9 GB RSS (ADR-014 Decision 10b). Under `-n auto`
  they compete for CPU and memory with every other worker, so their budgets
  depend on load.
- Codecov's patch check gates pull requests. A change to how coverage is
  collected changes what the gate means.
- `pytest-randomly` also reseeds `random`, numpy's global generator,
  factory-boy and Faker before every test. What it does to Hypothesis has to
  be recorded, not assumed.

### Environment the measurements were taken on

- **Local:** Apple Silicon Mac, 10 cores (8 performance + 2 efficiency),
  32 GB RAM. Python 3.13 from the repo's `.venv`, `uv sync --frozen` at
  `trunk` `6cf0ac6`.
- **CI:** GitHub's standard Linux runner for public repositories has
  **4 CPUs, 16 GB RAM** (verified 2026-09-25 against
  `github/docs` `data/reusables/actions/supported-github-runners.md`).

### Versions, verified live on PyPI 2026-09-25

| package | latest | released | requires |
|---|---|---|---|
| `pytest-xdist` | 3.8.0 | 2025-07-01 | `execnet>=2.1`, `pytest>=7.0.0`, Python >=3.9 |
| `pytest-randomly` | 5.0.0 | 2026-09-01 | `pytest>=8`, Python >=3.10 |
| `pytest-repeat` (diagnostic only, never a dependency) | 0.9.4 | 2025-04-07 | `pytest` |
| `pytest-rerunfailures` (rejected, see Decision 5) | 16.7 | 2026-09-17 | — |

Source: `curl -s https://pypi.org/pypi/<name>/json`, reading `info.version`,
`info.requires_python`, `info.requires_dist` and the upload time.

## Decision 1: CI runs `-n auto --dist worksteal`. Local default stays serial.

**Dependency.** Add `pytest-xdist>=3.8` to the `dev` group, in sorted
position (Decision 4). Lower bound only. Source: PyPI JSON, 2026-09-25.

**Where it runs.** Only the `test` job in `.github/workflows/ci.yml`. Both
test steps change: the pull-request/push step and the nightly/dispatch step.

```yaml
- if: github.event_name == 'pull_request' || github.event_name == 'push'
  run: uv run pytest -n auto --dist worksteal -m "not slow" --cov-report=xml
- if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
  run: uv run pytest -n auto --dist worksteal --cov-report=xml
```

- **`addopts` does not change.** `-n` must not go there. The ticket wants
  `pdb`, `-x` and readable tracebacks to keep working single-process.
- **`-n auto` is correct on CI without `psutil`.** xdist's
  `pytest_xdist_auto_num_workers` uses `psutil` only if it is importable.
  Otherwise it uses `os.sched_getaffinity(0)`. `psutil` is not in `uv.lock`.
  On the 4-CPU runner both give 4. Do not add `psutil` for this.
- **`mutmut` is unaffected.** It drives its own pytest invocation with
  `pytest_add_cli_args = ["--no-cov"]` and never passes `-n`.

### Distribution mode: `worksteal`

`load` was measured against `worksteal`. `loadscope`, `loadfile` and
`loadgroup` were not measured for the whole suite. Here is why:

- `loadscope` and `loadfile` pin a whole module or class to one worker. The
  cost is dominated by a few Bernoulli CUSUM modules (see the durations
  under Measurements), so those modes would serialise exactly the
  expensive part.
- `loadgroup` is evaluated as an isolation mechanism in Decision 2, not as
  a speed option.

| mode, workers | wall (s) | pytest-reported (s) | result |
|---|---|---|---|
| serial (today) | 439 | 436 | 1558 passed, 8 skipped |
| `load`, 10 | 139 | 133 | 1558 passed, 8 skipped |
| `worksteal`, 10 | 110 | 109 | 1558 passed, 8 skipped |
| `load`, 4 | 231 | 229 | 1558 passed, 8 skipped |
| `worksteal`, 4 | 131 | 129 | 1558 passed, 8 skipped |

`worksteal` wins because the suite's cost is very uneven. 1566 tests take
431 s of test time serially. One test alone is 48.7 s, and the ten slowest
are 212 s, about half the total. `load` hands out tests in fixed chunks up
front, so a worker that draws two 20 s tests becomes the critical path.
`worksteal` rebalances as it goes.

### Coverage is identical, line for line and branch for branch

Codecov's patch check gates pull requests, so "about the same percentage" is
not enough. The Cobertura XML from the serial run was compared with the XML
from each parallel run: every `(file, line)` hit/miss and every branch's
`condition-coverage` string.

| run | line-rate | branch-rate | lines covered/valid | branches covered/valid | differing lines | differing branches |
|---|---|---|---|---|---|---|
| serial | 0.9962 | 0.99 | 1556/1562 | 297/300 | — | — |
| `load`, 10 | 0.9962 | 0.99 | 1556/1562 | 297/300 | 0 | 0 |
| `worksteal`, 10 | 0.9962 | 0.99 | 1556/1562 | 297/300 | 0 | 0 |
| `load`, 4 | 0.9962 | 0.99 | 1556/1562 | 297/300 | 0 | 0 |
| `worksteal`, 4 | 0.9962 | 0.99 | 1556/1562 | 297/300 | 0 | 0 |

pytest-cov combines the worker data files in the controller. The terminal
report and the `fail_under = 80` check see the combined figure too. Nothing
in `[tool.coverage.*]` needs to change. Reporting from one matrix leg (3.13)
stays correct.

## Decision 2: tests that assert elapsed time run in a separate serial step. Timeout-guarded tests stay in the parallel run.

### `xdist_group` + `--dist loadgroup` does not do what the ticket needs

The ticket proposes putting the wall-clock tests in one `xdist_group` and
running with `--dist loadgroup`. That mechanism does not isolate them:

- `LoadGroupScheduling` subclasses `LoadScopeScheduling` (see
  `xdist/scheduler/loadgroup.py`, 3.8.0). It guarantees only that every test
  in a group runs **on the same worker, one after another**.
- The other workers keep running their own tests at the same time.
- So a grouped timing test still shares the CPU and memory with *N − 1*
  busy workers. That is exactly the contention the ticket wants to remove.
- It also forces the whole suite onto `loadscope`-style scheduling. That
  gives up `worksteal`'s balancing (Decision 1) and gains no isolation.

The only way to give a test the machine is to run it when nothing else is
running.

### Two kinds of time-sensitive test, and they need different things

| kind | what it claims | count | examples | under load |
|---|---|---|---|---|
| **Elapsed-time assertion** | the library is *fast enough* | 2 | `TestEqualSplitBound::test_refusal_completes_within_the_measured_budget` (asserts `elapsed <= 15.0`); `TestBoundedTimeWorstCorner::test_worst_corner_completes_or_raises_within_budget` (asserts `< 30.0`) | the measurement is load-dependent, so parallel load can **falsify** it |
| **`@pytest.mark.timeout` hang guard** | the library *terminates* | 196 not-slow tests (51 marker sites in 9 files) | ADR-014 bounded-time tests, child-process fits | load uses up headroom, but a hang guard exists to catch runaway, not to measure speed |

**Elapsed-time assertions: new `wall_clock` marker, separate serial CI step.**

1. Declare `wall_clock` in `[tool.pytest.ini_options].markers`.
   `--strict-markers` is already on, so a misspelling fails collection.
2. Mark the two tests above. `grep -rn "time.monotonic\|perf_counter" tests`
   finds exactly these two today.
3. CI runs them after the parallel step, with the machine to themselves:

```yaml
- if: github.event_name == 'pull_request' || github.event_name == 'push'
  run: uv run pytest -n auto --dist worksteal -m "not slow and not wall_clock" --cov-report=
- if: github.event_name == 'pull_request' || github.event_name == 'push'
  run: uv run pytest -m "wall_clock and not slow" --cov-append --cov-report=xml
# nightly/dispatch: the same pair, without "not slow"
```

- `--cov-append` makes the second step add to the first step's `.coverage`
  instead of erasing it. So `coverage.xml`, which Codecov reads, covers both
  steps.
- `--cov-report=` (empty) on the first step stops a half report from being
  written.
- ⚠️ `fail_under = 80` is checked **in each step, on the data accumulated so
  far**. The first step alone is at about 99.5%, so this does not bite
  today. The implementer must confirm the second step's total equals a
  single serial run's (Verification item 1).
- **The recipe was run end to end.** The two tests were selected with `-k`,
  because the marker does not exist yet:
  - Step 1: `-n auto --dist worksteal -m "not slow" -k "not (…)" --cov-report=`.
    1556 passed, 8 skipped, 121 s.
  - Step 2: `-m "not slow" -k "…" --cov-append --cov-report=xml`. 2 passed,
    11 s wall (8.6 s pytest-reported). Most of that is collection.
  - Step 2's report says `Total coverage: 99.52%`, the same as the serial
    baseline. Its `coverage.xml` matches the serial one with **0 differing
    lines and 0 differing branches**.
  - So the second step costs about 11 s, and `fail_under` evaluated in step 2
    sees the combined data.

**Hang guards: stay in the parallel run. Their headroom is checked, not
isolated.** A `timeout` that trips because four workers share four CPUs was
set too tight for a hang guard. The fix is the budget, not a quarantine.
Isolating all 196 would serialise roughly 312 s of the 431 s suite, which
defeats the ticket.

Headroom measured locally (timeout ÷ duration). The worst five are shown:

| test | timeout | serial | `worksteal` ×10 | headroom ×10 | `worksteal` ×4 |
|---|---|---|---|---|---|
| `TestJointStateCountCap::test_raises_with_joint_state_count_exceeded_context` | 60 | 23.4 s | 28.4 s | 2.1× | 24.2 s (2.5×) |
| `TestJointStateCountCap::test_max_two_sided_target_arl_round_trips` | 60 | 24.0 s | 26.6 s | 2.3× | 24.5 s (2.4×) |
| `test_one_sided_simulated_mean_run_length_matches_achieved_arl[floored_lower_m1000_f0]` | 180 | 48.7 s | 47.2 s | 3.8× | 43.7 s (4.1×) |
| `TestUnconstructibleUpperArm…::test_pinned_regression_at_m_3_million` | 60 | 12.7 s | 15.1 s | 4.0× | 13.1 s (4.6×) |
| `TestLatticeFinderAtTheEdgeOfDoublePrecision::test_an_unrealisable_design…` | 60 | 12.8 s | 14.3 s | 4.2× | 13.4 s (4.5×) |

⚠️ **The two `TestJointStateCountCap` tests are the risk on CI.**

- Their headroom is 2.5× serially on this Mac.
- The existing budget notes assume CI runners are about 1.9× slower (see
  `test_bernoulli_cusum_two_sided_refusal.py`). On that basis they already
  run at about 45 s of their 60 s serially on CI.
- The measured parallel penalty for them is +11% to +22%. That would put
  them at about 50–55 s.
- CI does not upload per-test durations today, so this cannot be confirmed
  without a CI run, and this ADR does not push.
- **Proposed:** the implementer reads their duration from the first CI run
  of the PR (`--durations=20` is cheap to add). If either is above 40 s on
  CI, raise its timeout to 3× the CI-measured duration and cite the
  measurement in the comment, as the existing budget notes already do.
  This is a question for the product owner (Q2), because these budgets came
  out of ADR-014 work.

### Child-process tests are hit hardest, and it does not matter

The tests that spawn `tests.support.isolated_bernoulli_fit` show the largest
relative slowdown under load. Example:
`TestLargeBaselines::test_fits_and_matches_the_independent_solver[m300k_f1_lower_370]`

- serial: 1.5 s
- `load` ×10: 35.6 s
- `worksteal` ×10: 17.1 s

Each child starts a fresh interpreter and imports numpy/scipy cold. That
extra process competes with every worker, and at `-n auto` there is already
one worker per core. The absolute times stay far inside their budgets
(`timeout(240)`, child `timeout=120.0`). None of them asserts on elapsed
time. They stay in the parallel run.

### Memory

ADR-014 Decision 10b measured about 908 MB peak RSS at the 1M-state cap.
Four CI workers, each running one such fit plus possibly one child, stay
well under the runner's 16 GB. Locally, 10 workers stay under 32 GB. No
isolation is needed for memory. This is an estimate from ADR-014's per-fit
figure, not a measurement of concurrent peak. No run hit memory pressure
(no `Killed`, no worker crash).

## Decision 3: add `pytest-randomly`. Shuffle every run. Reproduce a failure by its seed.

**Dependency.** Add `pytest-randomly>=5.0` to the `dev` group, in sorted
position. Lower bound only. Source: PyPI JSON, 2026-09-25.

- Installing it is enough to enable it. No `addopts` change.
- `-p randomly` appears in commands below only to pin the plugin explicitly
  in reproductions.

### What it does, read from the 5.0.0 source (`pytest_randomly/__init__.py`)

- **Order.** Modules are shuffled, then classes within a module, then tests
  within a class. The seed is a 32-bit integer printed in the header:
  `Using --randomly-seed=<n>`.
- **Order is decided first.** 5.0.0 moved the shuffle into a
  `pytest_collection_modifyitems` hook wrapper, so it runs before every other
  plugin's implementation of that hook. Caliper's own
  `tests/conftest.py::pytest_collection_modifyitems` only adds the `unit`
  marker and does not reorder, so there is no interaction.
- **Reseeding.** Before each test's setup, call and teardown it calls
  `random.seed(seed + crc32(nodeid) ± 1)`, then
  `numpy.random.seed(... % 2**32)`, and resets factory-boy's and Faker's
  random state. The seed is per test and independent of order, so a test
  that depends only on those generators behaves the same wherever it lands.
- **With xdist.** The controller generates the seed and passes it to each
  worker through `workerinput`. Every worker collects the same shuffled
  order, which xdist requires.

### Hypothesis: randomly does *not* reseed it, and a randomly seed does *not* reproduce a Hypothesis failure

The ticket says *"it reseeds Hypothesis per run"*. For 5.0.0 that is not
correct:

- **The source has no Hypothesis code at all.** The project changelog, read
  in full on 2026-09-25, never mentions Hypothesis.
- **Hypothesis takes each test's seed from its own generator.**
  `hypothesis.core.get_random_for_wrapped_test` resolves in this order:
  1. `@seed`
  2. `derandomize=True`, which uses a digest of the test function
  3. `--hypothesis-seed`
  4. otherwise `threadlocal._hypothesis_global_random`, a separate
     `random.Random()` seeded from OS entropy

  Reseeding the stdlib `random` module does not touch that fourth source.
- **Probed empirically.** A throwaway Hypothesis test was run twice with the
  same `--randomly-seed=7`:
  - the stdlib `random.random()` was identical both times (0.623598);
  - Hypothesis's first three draws differed: `[0, 222, 3125205]` vs
    `[0, 10041, 2602821927]`.

Consequences:

1. **`.hypothesis/examples` is unaffected.** Database keys come from the test
   function's digest, not from order or seed. A saved failing example
   replays first, whatever order the test runs in.
2. **Several workers share one database directory under xdist.**
   `DirectoryBasedExampleDatabase` writes each example to a temporary file
   and `rename`s it into place, so concurrent writers do not tear files. CI
   starts with no database either way, because `.hypothesis/` is gitignored
   and not cached. That is unchanged.
3. **The BIN-124 strategy-drift guard is unaffected.**
   `test_baseline_scores_strategy_contract.py` draws with Hypothesis's own
   seed and replays from the database exactly as before. Order cannot change
   what it checks, because it asks the library about each draw
   independently.
4. **The 9 `derandomize=True` tests in `test_extreme_value_fitting.py` stay
   fixed.** They are seeded from the function digest.
5. **Reproducing a failure takes two seeds, not one**, when the failing test
   is a Hypothesis test. `--randomly-seed` restores the order. Hypothesis
   prints its own reproduction (a `@reproduce_failure` blob, or the falsifying
   example, which it also saves to the local database). CONTRIBUTING must say
   so (Decision 5).

### numpy's global generator is reseeded, and nothing in `src/` uses it

randomly calls `numpy.random.seed` before every test.

- `grep` for `np.random.` finds only `default_rng(seed)`, in
  `tests/support/spc_simulation.py` and
  `test_bernoulli_cusum_arl_simulated_properties.py`.
- Those are explicitly seeded `Generator`s, not the legacy global generator,
  so they are unaffected.
- `test_documentation_examples.py` seeds `random` itself, so it is
  unaffected too.

### The beartype import hook

`tests/conftest.py` calls `beartype_package(...)` at import time for two
numerics modules. The hook is installed when conftest is imported, before
any test module is collected, so order cannot move it. Under xdist, each
worker imports conftest and installs its own hook, and all 1558 tests
passed with the hook active in every worker (Decision 1 runs).

The known numpy *"cannot load module more than once per process"* failure
is caused by `--cov=<dotted module>`, not by order. `--cov=src` stays as it
is.

### `-p no:randomly`

The ticket warns that command lines passing `-p no:randomly` become real
once the plugin is installed. Searched on 2026-09-25:

- the repo, including `.github/workflows/`, `.pre-commit-config.yaml`,
  `CONTRIBUTING.md` and `CLAUDE.md`;
- the vault's `Projects/caliper/`;
- `~/.claude/agents`, `~/.claude/commands` and `~/.claude/skills`.

**There are no occurrences.** The only uses found are ad-hoc diagnostic
commands in one past session transcript. Those were no-ops then and are
harmless now. Nothing in CI or a hook disables shuffling.

⚠️ The ticket's reproduction syntax, `-p randomly -p "randomly_seed=<n>"`,
is not valid. `-p` loads a plugin by name. The seed option is
`--randomly-seed=<n>`. See Decision 5 for the exact command.

## Decision 4: every dependency list is alphabetical by normalised name, enforced by a unit test

### The rule

- **Scope.** `[project].dependencies`, and every list under
  `[dependency-groups]` (`dev`, `docs`, and any group added later). Each list
  is sorted on its own. Grouping by purpose is dropped: it decayed within a
  day (`pytest-timeout` landed at the end of `dev`), and alphabetical order
  can be applied by anyone without knowing the author's intent.
- **Sort key.** The distribution name, normalised per PEP 503 (the
  "Normalized names" rule of the packaging specification): lowercase, and
  every run of `-`, `_` or `.` collapsed to `-`. The name is the leading
  `[A-Za-z0-9][A-Za-z0-9._-]*` of the requirement string, before any extra,
  specifier, marker or URL. The key then compares as a plain string.
  - This puts `pytest` before `pytest-bdd`, and `mkdocs` before
    `mkdocs-material` before `mkdocstrings`, because `-` (0x2D) sorts below
    letters.
  - That makes the `docs` group already correct.
- **Ties.** Two entries with the same normalised name in one list are a
  failure in their own right (a duplicate), not a sort question.
- **Other entries.** A PEP 735 `{include-group = "…"}` table entry is not a
  requirement string. None exist today. The test must fail loudly on a
  non-string entry rather than skip it, so whoever adds the first one
  decides where it sorts.

Resulting order. This is what the implementer produces, including the two
new entries:

```
[project].dependencies   numpy, pydantic, scipy
dev                      beartype, dirty-equals, factory-boy, freezegun,
                         git-cliff, hypothesis, mutmut, mypy, pre-commit,
                         pytest, pytest-bdd, pytest-cov, pytest-mock,
                         pytest-randomly, pytest-timeout, pytest-xdist,
                         ruff, ty, zizmor
docs                     mkdocs, mkdocs-material, mkdocstrings,
                         mkdocstrings-python        (unchanged)
```

### Comments move with their entry

A comment block directly above an entry, with no blank line between, belongs
to that entry and moves with it. A comment above the list's opening line
(`dependencies = [`, `dev = [`) belongs to the list and stays where it is.
Applied to today's file:

| comment | currently above | after sorting |
|---|---|---|
| "Domain types are Pydantic BaseModel…" | `pydantic` | still above `pydantic`, now second of three |
| "Dev-only runtime type enforcement… (BIN-109)" | `beartype` | above `beartype`, now first in `dev` |
| "Commit-time gates (BIN-89)… `zizmor` audits the workflow files…" | `pre-commit` **and** `zizmor` | **split in two**: one comment above `pre-commit` (drives the commit-time hooks, BIN-89), one above `zizmor` (audits workflow files; pinned by `uv.lock` rather than `uvx` because an unpinned security auditor is the one tool whose result must be reproducible) |
| "Changelog generation (BIN-90)…" | `git-cliff` | above `git-cliff` |
| "mkdocstrings 1.x moved the Python handler…" | `mkdocstrings-python` | unchanged |
| test-stack preamble above `dev = [` | the list | unchanged |

The new `pytest-xdist` and `pytest-randomly` entries each get a one-line
comment citing BIN-155 and this ADR. `uv.lock` is regenerated with
`uv lock`. That is the only lock change: adding two dev dependencies must not
move any existing pin, and the implementer checks this with
`git diff uv.lock`.

### Enforcement: a unit test, not a formatter

The test is `tests/unit/test_pyproject_dependency_order.py`. It is
stdlib-only: `tomllib` plus the regex above. It does not import `packaging`,
which is only a transitive dependency of pytest, and a test must not lean on
an undeclared import.

- It parses `pyproject.toml` from the repo root. For each list in scope, it
  asserts that the normalised names equal their sorted copy and contain no
  duplicates.
- On failure it reports **the list name and the first out-of-place entry**,
  because the fix is to move that line.
- **Power check** (the house rule on vacuity):
  - Move one entry out of order and confirm the test fails, naming that
    list.
  - Add a duplicate and confirm it fails.
  - Add a non-string entry and confirm it fails.

  The test writer records each of those runs.
- **Structural invariant table.** Add a row to CONTRIBUTING's "What is
  enforced for you" table: *Dependency lists are alphabetical →
  `tests/unit/test_pyproject_dependency_order.py`*.

`pyproject-fmt` is rejected (see Alternatives): it reformats the whole file,
and preserving the long explanatory comment blocks is unverified.

## Decision 5: what `CONTRIBUTING.md` must say

It goes in the existing **"The gates"** and **"Tests"** sections. Do not add
a new top-level section. Five points:

1. **Correct the stale claim.** "It takes about a minute" is wrong today. The
   not-slow suite takes about 7 minutes serially on a 10-core Mac, and the
   full suite much longer. State that `uv run pytest` runs everything,
   including `slow`, and give the fast path:

   ```bash
   uv run pytest -n auto --dist worksteal -m "not slow"   # about 2 minutes on 10 cores
   ```

   Serial stays the default, because `pdb`, `-x` and tracebacks are easier
   in one process. `-n auto` is the fast path, not the gate.

2. **Order is shuffled on every run.** The header prints
   `Using --randomly-seed=<n>`. To reproduce a failure, rerun with that seed:

   ```bash
   uv run pytest -p randomly --randomly-seed=<n>              # same order, serially
   uv run pytest -p randomly --randomly-seed=last             # the previous run's seed (needs the pytest cache)
   uv run pytest -p no:randomly                               # file order, for bisecting a suspected order dependency
   ```

   A failure seen only under `-n auto` may depend on which tests shared a
   worker. `worksteal` does not assign tests to workers the same way on every
   run, so reproduce with the seed **serially first**. An order-dependent
   failure is a defect to fix, never a seed to pin.

3. **Hypothesis failures reproduce by Hypothesis's own seed, not
   randomly's.** Use the `@reproduce_failure` line or the falsifying example
   Hypothesis prints, or its local database in `.hypothesis/`. The randomly
   seed restores only the order (Decision 3).

4. **Never `pytest-rerunfailures` on the gate.** A retry turns a test that
   fails for a real reason on some runs into a green check. That is the
   "passes for the wrong reason" failure this file already warns about. To
   check whether a test is flaky, repeat it diagnostically, without adding a
   dependency:

   ```bash
   uv run --with pytest-repeat pytest <nodeid> --count 50 -x
   ```

   `pytest-repeat` gives each repetition a distinct node id (`[1-50]`), so
   randomly reseeds each one differently.

5. **Tests that measure elapsed time carry `@pytest.mark.wall_clock`.** CI
   runs them serially after the parallel run (Decision 2). A new test that
   asserts on `time.monotonic()` or `perf_counter()` must carry the marker. A
   test that only needs to *terminate* uses `@pytest.mark.timeout` with a
   budget note, and stays in the parallel run.

Also add the dependency-order row to the enforcement table (Decision 4).

## Decision 6: CI time, and the nightly run

**The nightly full run uses xdist too.** Both CI steps change. The nightly
run is the one that most needs the time. The concurrency group already keeps
it from being cancelled by trunk pushes.

Measured, not-slow set:

| where | serial | parallel | speed-up |
|---|---|---|---|
| local, 10 cores, `worksteal` | 439 s | 110 s | 4.0× |
| local, `-n 4`, `load` (CI's worker count) | 439 s | 231 s | 1.9× |
| local, `-n 4`, `worksteal` | 439 s | 131 s | 3.4× |
| CI, 4 CPUs, per matrix leg | 635–704 s (the three legs of the trunk push run, 2026-09-25 12:54) | **estimate: ~300–360 s** | **~2×** (estimate) |

⚠️ **`-n 4` on a 10-core Mac does not model contention on a 4-CPU runner.**
Locally, the six spare cores absorb child processes and OS work. On CI,
workers equal CPUs, as with `-n auto` locally, where the median slowdown of
tests over 1 s was 1.21× (`worksteal` ×10).

How the CI estimate was built. It is an estimate, not a measurement:

1. Start from the local `worksteal` ×4 time: 131 s.
2. Multiply by 1.2 for workers-equal-cores contention.
3. Multiply by the ~1.9× CI-vs-local speed ratio the existing budget notes
   use.
4. Add the 30–60 s of job overhead.

That gives about 300–360 s against today's 635–704 s. This is the low end
of the ticket's "2–3×" expectation. The floor is the single 48.7 s test
(about 90 s on CI), which no amount of parallelism shortens.

The CI serial figures come from `gh run list --workflow ci.yml` and
`gh run view <id> --json jobs`, taking the `test (pyX)` job's
`completedAt − startedAt`. That includes checkout, `uv sync` and the upload,
roughly 30–60 s that parallelism does not shorten.

**Actual CI before/after must be recorded from the implementing PR's own
run.** This ADR cannot measure it without pushing. The implementer adds the
three legs' job durations to the PR description, and the code-reviewer
checks they are there.

## Alternatives considered

### Parallelism

- **`-n auto` in `addopts`.** Rejected by the ticket, and correctly so. It
  breaks `pdb` and `-x`, and makes local tracebacks interleave.
- **`--dist load`.** Measured. It is 26% slower than `worksteal` at 10
  workers (139 s vs 110 s). Its up-front chunking lets two long tests land
  on one worker.
- **`--dist loadscope` / `loadfile`.** Not measured for the whole suite.
  They pin a module to one worker, and the cost is concentrated in a few
  Bernoulli CUSUM modules, so they would serialise the expensive part.
- **Splitting the suite across more matrix jobs (sharding).** Rejected. It
  multiplies checkout and `uv sync` overhead by the shard count, and needs
  a coverage-merge job before Codecov. xdist gets the same effect inside one
  job.
- **`psutil` so `-n auto` counts CPUs better.** Rejected. xdist falls back
  to `os.sched_getaffinity(0)`, which is correct on the Linux runner. It
  would be a dependency with no effect.

### Isolating wall-clock tests

- **`xdist_group` + `--dist loadgroup`**, as the ticket suggests. Rejected:
  it serialises the grouped tests with each other but not with the rest of
  the machine (Decision 2), and it costs `worksteal`.
- **Keeping the elapsed-time assertions in the parallel run.** Rejected.
  `test_refusal_completes_within_the_measured_budget` went from 3.9 s to
  8.2 s under `worksteal` ×10 locally, against a 15 s assertion. Apply the
  test's own ~1.9× CI factor and it lands at the limit.
- **Loosening the elapsed-time assertions instead.** Rejected. The 15 s
  figure is a deliberately tight measurement of the library (ADR-014 C11).
  Loosening it to survive load would stop it detecting a real regression.
- **Isolating every `timeout`-marked test.** Rejected. That is 196 tests and
  about 312 s of the 431 s, so most of the gain disappears. A hang guard
  that trips under legitimate load was mis-set.
- **A `pytest-xdist` `--maxprocesses` / worker-restart knob.** Not
  applicable. No worker crashed or exhausted memory.

### Shuffling

- **`pytest-random-order`.** Same idea, with bucket options. Rejected for
  randomly, which the ticket names. randomly also reseeds factory-boy and
  Faker, which this suite uses, and 5.0.0 made its ordering independent of
  plugin registration order.
- **No shuffling, relying on xdist's scattering alone.** Rejected. xdist
  changes *which process* a test runs in, but each worker still runs its
  share in file order. A dependency between two tests in the same module
  would survive indefinitely.
- **Pinning a seed in CI.** Rejected. A fixed order is exactly what the
  ticket exists to remove. Reproducibility comes from the printed seed.

### Retries

- **`pytest-rerunfailures` on the gate.** Rejected (Decision 5). It hides
  exactly the class of defect this project keeps finding: tests that pass
  for the wrong reason.

### Dependency order

- **`pyproject-fmt`.** Rejected. It rewrites the whole file, not just the
  lists. Whether it preserves this file's long comment blocks and their
  attachment to entries is unverified, and a wrong move would quietly
  detach a rationale from its dependency.
- **Keeping purpose-grouping, documented.** Rejected. It depends on every
  author knowing and applying the grouping, and it decayed the same day it
  was relied on.
- **A pre-commit hook instead of a test.** Rejected. It needs a script
  either way, and the test also runs in CI's test job for a contributor who
  never ran `pre-commit install`.

## Consequences

**Positive**

- PR feedback gets roughly 2× faster per matrix leg (estimate; the real
  figure comes from the implementing PR). The nightly run gets the same
  gain.
- Every run is an isolation check: a new process layout and a new order.
- Coverage and Codecov gating are unchanged, verified line by line.
- Dependency order is mechanical and enforced.

**Negative**

- CI failure output from parallel runs is interleaved per worker. Reproduce
  serially with the seed.
- One more marker (`wall_clock`), one more CI step per event, and one more
  rule for authors of timing tests.
- A Hypothesis failure needs two seeds to reproduce: order from randomly,
  data from Hypothesis. That is documented, not removed.
- Two `TestJointStateCountCap` hang guards may need their budgets raised
  after the first CI measurement (Q2).

**Neutral**

- `uv.lock` gains `pytest-xdist`, `execnet` and `pytest-randomly`.
- `mutmut` is unaffected (`--no-cov`, no `-n`).

## Reversibility

**Low cost throughout.**

- Parallelism is two CI flags.
- Shuffling is one dev dependency, and can be switched off for a run with
  `-p no:randomly`.
- The dependency-order rule is one test.
- Nothing in `src/` changes, and nothing ships in the wheel: both plugins
  are dev-only.

## Verification required of the implementation

1. `uv run pytest -n auto --dist worksteal -m "not slow and not wall_clock"`
   followed by `uv run pytest -m "wall_clock and not slow" --cov-append
   --cov-report=xml` produces a `coverage.xml` whose line-rate, branch-rate
   and per-line hits equal a serial `uv run pytest -m "not slow"`. Compare
   the XML, as this ADR's measurements did, not just the percentage.
2. `uv run pytest -m wall_clock --collect-only -q` collects exactly the two
   elapsed-time tests, and `-m "not wall_clock"` collects everything else.
3. The not-slow suite passes under at least five distinct randomly seeds in
   parallel and two serially. Record the seeds in the PR.
4. The dependency-order test fails on a moved entry, a duplicate and a
   non-string entry, each shown by a recorded run (Decision 4).
5. The implementing PR records the three CI test legs' before/after job
   durations (Decision 6), and `TestJointStateCountCap`'s CI durations (Q2).
6. `grep -rn "no:randomly" .github .pre-commit-config.yaml` stays empty.
7. A `workflow_dispatch` run of the PR branch runs the full suite, including
   `slow`, under `-n auto --dist worksteal` on all three legs and passes. The
   slow set has not yet been run in parallel anywhere.

## Questions for the product owner — ✅ all answered 2026-09-27 (see Status)

**Q1.** Accept the separate serial `wall_clock` CI step (Decision 2)
instead of the ticket's `xdist_group` + `loadgroup`? The ticket's mechanism
does not isolate. The cost is one extra step of about 11 s (measured), and a marker
authors must remember.

**Q2.** If CI shows either `TestJointStateCountCap` hang guard above 40 s of
its 60 s, may the implementer raise it to 3× the CI-measured duration, with
the measurement cited in the comment? The alternative is to move them into
the serial step. That works, but it treats a hang guard as a speed
assertion, and those two tests alone would make the serial step about 50 s.

**Q3.** The nightly full run also goes parallel (Decision 6). Any reason to
keep it serial, for instance as a check that nothing depends on parallel
execution? This ADR says no: the serial path is exercised by every local
`uv run pytest`.

**Q4.** The ticket's text says randomly "reseeds Hypothesis per run" and
gives `-p "randomly_seed=<n>"` as the reproduction. Both are incorrect for
5.0.0 (Decision 3). Should the ticket be corrected so the wrong command is
not copied from it?

## Measurements, and the commands that produced them

All runs were on `trunk` `6cf0ac6` with the lock file untouched. The plugins
were added ephemerally with `uv run --with`. Each run was sequential, with
nothing else running, so wall times are comparable.
`-p no:cacheprovider` was used on every run so no run could inherit a
previous run's state.

```bash
# serial baseline
uv run pytest -m "not slow" -p no:cacheprovider \
  --cov-report=xml:cov-serial.xml --junitxml=junit-serial.xml --durations=60

# distribution modes (no shuffling)
uv run --with 'pytest-xdist>=3.8' pytest -n auto --dist load      -m "not slow" -p no:cacheprovider --cov-report=xml:... --junitxml=...
uv run --with 'pytest-xdist>=3.8' pytest -n auto --dist worksteal -m "not slow" ...
uv run --with 'pytest-xdist>=3.8' pytest -n 4    --dist load      -m "not slow" ...
uv run --with 'pytest-xdist>=3.8' pytest -n 4    --dist worksteal -m "not slow" ...

# shuffled, parallel and serial
uv run --with 'pytest-xdist>=3.8' --with 'pytest-randomly>=5.0' \
  pytest -n auto --dist worksteal -p randomly --randomly-seed=<n> -m "not slow" ...
uv run --with 'pytest-xdist>=3.8' --with 'pytest-randomly>=5.0' \
  pytest -p randomly --randomly-seed=<n> -m "not slow" ...
```

- **Coverage comparison.** A script parsed both Cobertura files and compared:
  - the root `line-rate`, `branch-rate` and covered/valid counts;
  - every `<line>`'s hit/miss, keyed by `(filename, number)`;
  - every branch line's `condition-coverage`.
- **Per-test slowdown.** Computed from the `--junitxml` `time` attributes,
  matched by `(classname, name)`.
- **Timeout values.** Read at collection by a throwaway plugin calling
  `item.get_closest_marker("timeout")`.
- **Hypothesis probe (Decision 3).** A throwaway
  `@given(st.integers(0, 10**12))` test with `database=None`, run twice with
  `--randomly-seed=7`, recording its draws and `random.random()`.

### The shuffled runs

Every run: 1558 passed, 8 skipped, exit 0.

| run | seed | wall (s) |
|---|---|---|
| `worksteal` ×10 | 1 | 122 |
| `worksteal` ×10 | 20260925 | 90 |
| `worksteal` ×10 | 3141592653 | 87 |
| `worksteal` ×10 | 7 | 126 |
| `worksteal` ×10 | 99 | 120 |
| `worksteal` ×10 | unpinned; printed `734915703` | 122 |
| `worksteal` ×4 | 42 | 149 |
| `worksteal` ×4 | 2718281828 | 129 |
| serial | 5 | 410 |
| serial | 123456789 | 429 |

**No order-dependent failure was found.** That is 10 shuffled runs:

- 8 parallel: six at ×10 across six seeds, two at ×4;
- 2 serial;
- all at `-m "not slow"`.

It also means 196 `timeout`-guarded tests passed ten times each under the
contention described in Decision 2, with no timeout tripped. The unshuffled
parallel runs are four more passes under different process layouts: `load`
and `worksteal`, at ×10 and ×4. Every run's summary line is identical to the
serial baseline's (1558 passed, 8 skipped), so no test was silently
deselected or skipped differently.

Wall time varies with the seed, from 87 s to 126 s at ×10. The order
decides when the few 20–50 s tests start, and a long test started late
extends the tail. `worksteal` cannot split a single test.

A reporting difference, so nobody mistakes it for lost tests. The serial
summary line says `18 deselected` and the xdist summary lines do not. Under
xdist, deselection happens in the workers and the controller does not
report it. The passed and skipped counts are identical.

**Not covered: the `slow` set (18 tests) under xdist.** It was not run, to
keep the machine free for the comparable timings above. The slow set is
where the largest fits live (m = 3,000,000 cells, ADR-014 Decision 13).
**The first nightly run after merge is its first parallel run.** The
implementer should trigger one by `workflow_dispatch` on the PR branch
before merge, and record its result (Verification item 7).

---

## Amendment 1 (2026-09-27): measured on CI

**Status:** ✅ **ACCEPTED — ratified by the product owner 2026-09-27.**
QA1: the job-level BLAS caps are a permanent part of the CI contract. QA2: the
seven new budgets and the "≥ 3× slowest CI leg" rule replace Q2. QA3: the
nightly/dispatch run is serial. QA4: 3× stands for now, **to be re-checked
against the `--durations=30` CI logs once about two weeks of runs exist** — the
runner hardware is heterogeneous, and the margin was sized on one observed
part.
**Why:** the pre-merge full-suite `workflow_dispatch` run failed on all three
legs (Verification item 7).

### What ADR-015 got wrong

**1. The slow set was never run under xdist.** The original ADR said so itself
("Not covered: the `slow` set… under xdist"). It then recommended the parallel
nightly anyway (Q3), treating the gap as something to confirm rather than as
missing evidence. The confirmation run is what failed.

**2. A 10-core Mac is not a 4-vCPU runner.** Every contention figure in
Decisions 2 and 6 was measured locally:

- the ~1.2× median slowdown;
- the 2.1× worst headroom;
- the ~300–360 s CI estimate.

`-n 4` on 10 cores leaves six cores idle to absorb child processes and OS
work. The runner has none spare. The "workers-equal-cores" ×1.2 factor used
in the CI estimate was taken from the Mac's ×10 run, and CI contradicts it
(below).

**3. The CI speed factor was borrowed, not measured.** The ~1.9× CI-vs-local
factor came from a test's budget note. CI did not publish per-test durations
at the time, so no CI duration backed any headroom figure.

### The failing run: 36330900057 (branch `ci/BIN-155/parallel-shuffled-tests` at `0828937`)

The run used `-n auto --dist worksteal -m "not wall_clock"` on 4 workers,
with the full suite including `slow`. Compared with the last green serial
full-suite run, 36326491650 (dispatch at `c16949f`):

| leg (job) | tests that hit their timeout | parallel session | serial session (36326491650) | change |
|---|---|---|---|---|
| 3.11 (108652492543) | both `TestJointStateCountCap` (60 s); `test_pinned_regression_at_m_3_million` (60 s); `test_one_sided_simulated_mean_run_length_matches_achieved_arl[floored_lower_m1000_f0]` (180 s); `TestLatticeFinderAtTheEdgeOfDoublePrecision::test_an_unrealisable_design_at_an_ordinary_multiple_is_f16_with_a_minimum` (60 s) | 1496.1 s | 1570.5 s | −5% |
| 3.12 (108652492364) | both `TestJointStateCountCap` (60 s) | 1118.7 s | 1201.5 s | −7% |
| 3.13 (108652492423) | both `TestJointStateCountCap` (60 s) | 1926.8 s | 1427.7 s | **+35%** |

Four workers on four vCPUs made the full suite **no faster**, and on 3.13
slower. According to code-reviewer's reading of the logs, unmarked
Hypothesis tests reached 430–440 s on 3.13, and `test_slow_refusal_cells[m1000_f1]`
reached 546 s on 3.12 (timeout 900). ADR-015's local model predicted about
1.2× slowdown. That model is wrong for this runner.

### Experiment 1: run 36333444223 (branch `exp/ci-parallel-measure-1`)

**Setup.** The experiment branch forked `0828937` and changed two things:

- **The CI `test` job.** It became a matrix of Python version (3.11, 3.12,
  3.13) × five configurations, each on its own fresh 4-vCPU runner:

  | config | command | BLAS/OpenMP thread caps |
  |---|---|---|
  | `ns-serial` | `pytest -m "not slow"` | none |
  | `ns-serial-capped` | the same | `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1` |
  | `ns-par` | the PR pair: `-n auto --dist worksteal -m "not slow and not wall_clock" --cov-report=`, then `-m "wall_clock and not slow" --cov-append --cov-report=xml` | none |
  | `ns-par-capped` | the same pair | caps as above |
  | `full-par-capped` | the nightly pair, without `not slow` | caps as above |

  Every command added `--durations=0 --durations-min=2`.
- **A `tests/conftest.py` shim.** It multiplied every `timeout` marker by 10,
  so a test that would trip its hang guard runs to completion and reports
  its real duration.

Each job also recorded:

- `nproc`, `free -m` and the CPU model;
- `threadpoolctl.threadpool_info()`, taken after importing numpy, scipy and
  `scipy.sparse.linalg`;
- a `free -m` sample every 20 s;
- its `coverage.xml`, printed into the log so it could be compared line by
  line.

**Which BLAS, and whether the cap takes effect.** `threadpoolctl` finds two
OpenBLAS pools, both using the `pthreads` threading layer, not OpenMP:

- numpy's bundled `libscipy_openblas64_` (0.3.34.106.0);
- scipy's bundled `libscipy_openblas` (0.3.31.dev).

Uncapped, each pool starts `num_threads = 4`, one per vCPU. So four xdist
workers can each run two 4-thread pools on four vCPUs. With the caps set,
both pools report `num_threads = 1`. `OPENBLAS_NUM_THREADS` is the variable
that governs pthreads OpenBLAS. `OMP_NUM_THREADS` is its fallback, and MKL is
not present. Setting all three costs nothing and stays correct if a future
wheel changes its BLAS.

**The runners are not uniform hardware, and this matters more than the
Python version.** Each job printed its CPU:

- most were `AMD EPYC 7763`;
- some were `INTEL(R) XEON(R) PLATINUM 8573C`, and those were markedly
  faster.

`ns-serial` 3.13 ran on the Intel part, which likely explains why "3.13" was
the fastest serial leg. The failing run's 3.13 leg (+35%) may equally be a
hardware draw; that run's CPU model was not logged. Every duration below is
tagged with its CPU.

#### Results, experiment 1

Every job passed. "pytest session" is the time pytest reports for each
step; parallel configurations add the serial `wall_clock` step.

| config | py | job | CPU | pytest session(s) | max mem MB | coverage (lines/branches) | coverage diff vs `ns-serial`, same Python |
|---|---|---|---|---|---|---|---|
| full-par-capped | py3.11 | 108659677101 | AMD EPYC 7763 | 826 + 11 | 4111 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| full-par-capped | py3.12 | 108659677084 | AMD EPYC 7763 | 871 + 11 | 4995 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| full-par-capped | py3.13 | 108659677093 | AMD EPYC 7763 | 675 + 10 | 4710 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-par | py3.11 | 108659677120 | Intel(R) Xeon(R) 6973P-C | 1495 + 7 | 3059 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-par | py3.12 | 108659677114 | AMD EPYC 7763 | 966 + 11 | 2531 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-par | py3.13 | 108659677045 | AMD EPYC 7763 | 1006 + 10 | 2494 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-par-capped | py3.11 | 108659677067 | AMD EPYC 7763 | 313 + 11 | 2822 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-par-capped | py3.12 | 108659677053 | AMD EPYC 7763 | 294 + 11 | 2675 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-par-capped | py3.13 | 108659677089 | AMD EPYC 7763 | 262 + 10 | 2504 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-serial | py3.11 | 108659677018 | AMD EPYC 7763 | 643 | 1716 | 1556/297 (0.9962/0.99) | — |
| ns-serial | py3.12 | 108659677033 | AMD EPYC 7763 | 607 | 2001 | 1556/297 (0.9962/0.99) | — |
| ns-serial | py3.13 | 108659677079 | INTEL(R) XEON(R) PLATINUM 8573C | 440 | 2354 | 1556/297 (0.9962/0.99) | — |
| ns-serial-capped | py3.11 | 108659677007 | AMD EPYC 7763 | 625 | 1888 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-serial-capped | py3.12 | 108659677024 | AMD EPYC 7763 | 576 | 2178 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |
| ns-serial-capped | py3.13 | 108659677147 | INTEL(R) XEON(R) PLATINUM 8573C | 481 | 1990 | 1556/297 (0.9962/0.99) | 0 lines/branches differ |

Every parallel configuration's `coverage.xml` matched its serial counterpart
exactly. "0 differ" means every line's hit/miss and every branch's
`condition-coverage` matched `ns-serial` on the same Python. The totals are
1556/1562 lines and 297/300 branches everywhere, so Codecov's figures are
unchanged.

**What experiment 1 shows:**

1. **Uncapped threads are the cause of the failure. Capping fixes the
   suite-level problem.**
   - Uncapped `ns-par` took 966–1495 s, *slower* than serial at 440–643 s.
   - Capped `ns-par-capped` took 262–313 s, about **2.1× faster than
     serial** on the same AMD hardware.
   - The victims of oversubscription are the dense-linear-algebra Hypothesis
     tests, which do many small `np.linalg.solve` calls through
     `ewma_numerics`. Uncapped in parallel, the BIN-124 guard
     (`test_baseline_scores_strategy_never_draws_a_baseline_the_library_rejects`,
     6.6 s serially on the Mac) took **742 s** on 3.11 and 459 s on 3.13.
     `test_affine_transform_…`, `test_fit_ewma_handles_structured_large_magnitudes`
     and `test_ewma_delivers_the_requested_arl0_…` took 146–463 s each.
   - `ns-par` 3.11 drew an `Intel Xeon 6973P-C` runner and was still the
     slowest job of all (1495 s). So this is not a hardware artefact.
   - This confirms code-reviewer's hypothesis.
2. **Capping costs nothing serially.** `ns-serial-capped` vs `ns-serial` on
   the same hardware: 625 vs 643 s (3.11) and 576 vs 607 s (3.12). The
   suite's BLAS work is too small for four threads to help. So the caps can
   be set for every test step, not only the parallel one.
3. **Even capped, four workers on four vCPUs slow each heavy test by
   1.6–2.6×.** This is far more than the ~1.2× measured on the 10-core Mac.
   The sparse solves (SuperLU, single-threaded) and memory bandwidth are
   shared, and a 4-vCPU runner is likely 2 cores with SMT; the CPU topology
   was not captured. **This is why the hang guards trip even with the cap.**
   See the next table.
4. **Memory is not a constraint.**
   - Peak `used` was 2.5–2.8 GB for the not-slow parallel runs and 4.1–5.0 GB
   for the full suite, on a 16 GB runner.
   - Serial runs peaked at 1.7–2.4 GB.
5. **The full suite, capped and parallel, took 675–871 s**, against 1201–1570 s
   for the last green serial run (36326491650). That is about 1.8× faster,
   and every test passed, but only with timeouts stretched ×10. See Decision
   A2 for what it would take at real budgets.

#### Hang guards within 3× of their timeout: CI durations, experiment 1

Durations are the `setup` + `call` + `teardown` totals from `--durations=0`,
with timeouts stretched ×10 so every test finished. `serial` is `ns-serial`
(3.11 AMD, 3.12 AMD, 3.13 Intel).

| test | timeout | `ns-serial` 3.11 / 3.12 / 3.13 | `ns-par-capped` 3.11 / 3.12 / 3.13 | `full-par-capped` 3.11 / 3.12 / 3.13 | worst headroom |
|---|---|---|---|---|---|
| `TestJointStateCountCap::test_raises_with_joint_state_count_exceeded_context` | 60 | 42.5 / 39.7 / 28.0 | **73.5** / 68.5 / 61.3 | 67.2 / 69.0 / 62.8 | **0.82×** |
| `TestJointStateCountCap::test_max_two_sided_target_arl_round_trips` | 60 | 42.6 / 40.5 / 28.4 | 67.7 / 49.3 / 66.2 | 67.7 / **71.2** / 67.6 | **0.84×** |
| `TestUnconstructibleUpperArmAtOrdinaryMultiples::test_pinned_regression_at_m_3_million` | 60 | 21.9 / 19.1 / 10.6 | **39.2** / 36.9 / 28.0 | 38.9 / 36.9 / 27.2 | 1.53× |
| `TestLatticeFinderAtTheEdgeOfDoublePrecision::test_an_unrealisable_design_at_an_ordinary_multiple_is_f16_with_a_minimum` | 60 | 22.3 / 19.1 / 10.7 | 37.4 / **38.5** / 27.5 | 38.7 / 34.7 / 26.6 | 1.55× |
| `test_one_sided_simulated_mean_run_length_matches_achieved_arl[floored_lower_m1000_f0]` | 180 | 73.7 / 56.5 / 41.2 | 99.8 / 111.8 / 107.5 | 128.8 / **153.7** / 95.4 | 1.17× |
| `TestLatticeFinderAtTheEdgeOfDoublePrecision::test_the_forward_walk_finds_the_ratified_lattice` | 60 | 13.7 / 12.7 / 7.4 | 15.4 / 25.5 / 19.9 | **26.1** / 22.8 / 17.9 | 2.30× |
| `TestEqualSplitBound::test_slow_refusal_cells[m1000_f5_M1.01]` (`slow`) | 900 | not in `ns-serial` | — | 329.7 / **424.1** / 274.3 | 2.12× |

⚠️ **The two `TestJointStateCountCap` tests are over the ratified Q2
threshold even serially on CI.** They take 42.5 s on AMD 3.11, and Q2's
threshold is 40 s of 60. Their budget was always too tight for CI. The
parallel run only made that visible.

### Experiment 2: run 36335148663 (branch `exp/ci-parallel-measure-2`)

Experiment 2 answered three questions with the same shim, caps and
`--durations`:

- Does the capped parallel result replicate? Two more `ns-par-capped` runs,
  `-a` and `-b`.
- Would three workers relieve the per-test contention? `ns-par3-capped`,
  using `-n 3`.
- What does a second capped serial run give? `ns-serial-capped`.

Every job passed. Coverage is again identical to the capped serial run on
the same Python, with 0 differing lines or branches.

| config | py | job | CPU | pytest session (s) | max mem MB |
|---|---|---|---|---|---|
| `ns-par-capped-a` | 3.11 | 108664475821 | AMD EPYC 7763 | 303 + 10 | 2818 |
| `ns-par-capped-a` | 3.12 | 108664475777 | AMD EPYC 7763 | 304 + 11 | 2644 |
| `ns-par-capped-a` | 3.13 | 108664475829 | AMD EPYC 7763 | 285 + 10 | 2875 |
| `ns-par-capped-b` | 3.11 | 108664475771 | AMD EPYC 7763 | 293 + 10 | 2101 |
| `ns-par-capped-b` | 3.12 | 108664475790 | AMD EPYC 7763 | 308 + 11 | 2622 |
| `ns-par-capped-b` | 3.13 | 108664475745 | AMD EPYC 9V45 | 131 + 5 | 2403 |
| `ns-par3-capped` | 3.11 | 108664475886 | Intel Xeon Platinum 8573C | 289 + 10 | 2224 |
| `ns-par3-capped` | 3.12 | 108664475721 | AMD EPYC 9V74 | 297 + 10 | 2628 |
| `ns-par3-capped` | 3.13 | 108664475825 | AMD EPYC 7763 | 277 + 10 | 2549 |
| `ns-serial-capped` | 3.11 | 108664475722 | AMD EPYC 9V74 | 588 | 1737 |
| `ns-serial-capped` | 3.12 | 108664475871 | AMD EPYC 9V74 | 431 | 1562 |
| `ns-serial-capped` | 3.13 | 108664475834 | AMD EPYC 7763 | 546 | 1766 |

**Replication.** On the common `AMD EPYC 7763` runner, the capped parallel
not-slow session was 262–313 s across all eight such legs in experiments 1
and 2. Capped or uncapped serial on the same CPU was 546–643 s. That is a
**steady ~2× gain**. The one `AMD EPYC 9V45` draw finished in 131 s, which
shows how much runner hardware alone moves these numbers.

**`-n 3` is not better.** It took 277–297 s against 285–313 s for `-n auto`
(4), within the hardware noise. The `TestJointStateCountCap` tests still
reached 68.4 s on a 7763 under `-n 3`. A spare vCPU does not rescue the
tightest guards, so `-n auto` stays.

**The `wall_clock` step on CI.**
`test_refusal_completes_within_the_measured_budget` took 4.6–5.5 s across
every CI job in both experiments, serial or not, against its `<= 15.0`
assertion. That is about 3× headroom, as ADR-015 intended. The separate
serial step works.

**Why the Mac did not show any of this.** Locally, numpy and scipy link
Apple's **Accelerate**, confirmed with `np.show_config()`.
`threadpoolctl` does not see Accelerate, and Accelerate did not
oversubscribe in the local runs. The Linux wheels bundle **pthreads
OpenBLAS**, which starts one thread per vCPU per library. The local
measurements could not have revealed the failure mode, so it had to be
measured on CI.

### Decisions (Amendment 1)

**A1. PR/push stays parallel, with BLAS threads capped.**

- The `test` job sets these at **job level**, so every test step, parallel
  or serial, runs capped:

  ```yaml
  env:
    OMP_NUM_THREADS: "1"
    OPENBLAS_NUM_THREADS: "1"
    MKL_NUM_THREADS: "1"
  ```

- `OPENBLAS_NUM_THREADS` is the one that matters for today's wheels:
  pthreads OpenBLAS in both numpy and scipy, per `threadpoolctl`.
  `OMP_NUM_THREADS` is OpenBLAS's fallback and covers an OpenMP build.
  `MKL_NUM_THREADS` covers an MKL build. All three are inert when unused.
- Measured cost of capping serially: none (experiment 1, finding 2).
- Measured gain of capping in parallel: 966–1495 s → 262–313 s.
- The PR step pair from ADR-015 Decision 2 is unchanged:
  `-n auto --dist worksteal -m "not slow and not wall_clock" --cov-report=`,
  then `-m "wall_clock and not slow" --cov-append --cov-report=xml`.
- Expected not-slow session: ~290 s on the common runner, against ~600 s
  serial. With job overhead that is ~6 min, against today's ~11 min.

**A2. Nightly/dispatch goes back to serial. The evidence agrees with the
product owner's direction.**

- It is one step: `uv run pytest --cov-report=xml --durations=30`, capped by
  the job-level env like everything else. The `wall_clock` split is not
  needed when nothing runs in parallel.
- There is a measured case *for* parallel: `full-par-capped` passed in
  675–871 s against 1201–1570 s serial, about 1.8× faster. It is outweighed
  on three counts:
  1. The nightly run is on nobody's critical path. Twelve minutes saved
     overnight buys nothing.
  2. Under four workers, each heavy slow test runs 1.6–2.6× longer than it
     would serially. `test_slow_refusal_cells[m1000_f5_M1.01]` reached
     424 s of its 900 s. The slow tests' budgets (ADR-014) were set from
     serial measurements. Running them in parallel would mean re-deriving
     them from a single CI run each.
  3. The nightly run is the only place the `slow` tests run. Running them
     the way they were measured keeps a timeout there meaning "the library
     got slower", not "the runner was busy".
- Reversal Q3 is therefore confirmed on evidence. This is not a guess, and
  it can be reopened with the numbers above if nightly time ever matters.

**A3. New hang-guard budgets: at least 3× the slowest CI duration under the
configuration that runs the test.**

- Each figure is the maximum over **18 CI measurements**: nine capped
  parallel legs (experiment 1, 2a and 2b) and nine serial legs (experiments
  1 and 2, capped and uncapped).
- The new value is 3× that maximum, rounded up to a multiple of 30 s.
- The comment beside each marker must cite this amendment, the run id and
  the slowest leg, as the existing budget notes do.

| test (file) | old | slowest CI duration (run, job, CPU) | new |
|---|---|---|---|
| `TestJointStateCountCap::test_raises_with_joint_state_count_exceeded_context` (`test_bernoulli_cusum_lattice_fix.py`) | 60 | 73.5 s (36333444223, 108659677067, EPYC 7763, parallel) | **240** |
| `TestJointStateCountCap::test_max_two_sided_target_arl_round_trips` (same) | 60 | 70.3 s (36335148663, 108664475771, EPYC 7763, parallel) | **240** |
| `test_one_sided_simulated_mean_run_length_matches_achieved_arl` (`test_bernoulli_cusum_arl_simulated_properties.py`; the marker covers every parameter, and `floored_lower_m1000_f0` sets it) | 180 | 134.9 s (36335148663, 108664475821, EPYC 7763, parallel) | **420** |
| `TestUnconstructibleUpperArmAtOrdinaryMultiples::test_pinned_regression_at_m_3_million` (`test_bernoulli_cusum_detect_rate_multiple.py`) | 60 | 39.2 s (36333444223, 108659677067, EPYC 7763, parallel) | **120** |
| `TestLatticeFinderAtTheEdgeOfDoublePrecision::test_an_unrealisable_design_at_an_ordinary_multiple_is_f16_with_a_minimum` (`test_bernoulli_cusum_defensive_paths.py`) | 60 | 39.0 s (36335148663, 108664475821, EPYC 7763, parallel) | **120** |
| `TestLatticeFinderAtTheEdgeOfDoublePrecision::test_the_forward_walk_finds_the_ratified_lattice` (same file) | 60 | 25.5 s (36333444223, 108659677053, EPYC 7763, parallel) | **90** |
| `test_two_sided_simulated_mean_run_length_is_at_least_the_coupled_bound` (`test_bernoulli_cusum_arl_simulated_properties.py`; `[p_hat]` sets it) | 180 | 62.7 s (36335148663, 108664475777, EPYC 7763, parallel) | **210** |

- No other not-slow test with a `timeout` marker came within 3× of its
  budget in any of the 18 measurements.
- **The ratified Q2 rule is superseded.** The "raise if above 40 s of 60"
  trigger assumed the tests were comfortably inside their budget on CI.
  They were not: 42.5 s serially, uncapped, on the 7763.
- The replacement rule is general: **a hang guard's budget is at least 3×
  its slowest measured CI duration under the configuration that runs it.**
  New guards follow the same rule.
- **`slow` tests are not re-budgeted here.** Under A2 they run serially, as
  before, where the last full serial run (36326491650) was green. Their
  serial CI durations were never logged. The nightly run's `--durations=30`
  now records them, and any within 3× gets the same treatment in a
  follow-up.

**A4. What else changes.**

- **`CONTRIBUTING.md`.** On Linux, a local `-n auto` run should set
  `OPENBLAS_NUM_THREADS=1`, or it will oversubscribe the same way CI did:

  ```bash
  OPENBLAS_NUM_THREADS=1 uv run pytest -n auto --dist worksteal -m "not slow"
  ```

  macOS (Accelerate) did not need it in any measurement.
- **The `ci.yml` comment** must record why the caps exist, citing this
  amendment and the 966–1495 s vs 262–313 s figures, so nobody removes them
  as unexplained.
- **Verification before merge:**
  1. A CI run of the PR pair on the implementing branch shows no timeout
     tripped and coverage matching serial.
  2. A `workflow_dispatch` run of the (now serial) full suite passes on all
     three legs.

  Both run ids go in the PR description.

### Experiment branches

`exp/ci-parallel-measure-1` (`6dea470`) and `exp/ci-parallel-measure-2`
(`57bf8ec`) were created from `0828937` and carry no ticket ID. They
changed only `.github/workflows/ci.yml` and `tests/conftest.py` (the ×10
timeout shim), plus `scripts/exp_cov_dump.sh`, and none of those changes is
merged. Both branches were deleted once the measurements were read. No
pull request was opened from either.

### Questions for the product owner (Amendment 1) — ✅ all answered 2026-09-27 (see its Status)

**QA1.** Accept the job-level BLAS caps (A1) as a permanent part of the CI
contract, documented in `ci.yml` and `CONTRIBUTING.md`?

**QA2.** Accept the seven new budgets (A3) and the general
"≥ 3× slowest CI leg" rule in place of Q2's 40-of-60 trigger?

**QA3.** Nightly serial (A2) accepted with the evidence above, or run it
capped and parallel at ~1.8× (which would then require re-budgeting the
slow set from parallel measurements)?

**QA4.** The runners are heterogeneous. Across these two experiments alone
they included `EPYC 7763`, `EPYC 9V45`, `EPYC 9V74`, `Xeon Platinum 8573C`
and `Xeon 6973P-C`. The 3× margin was sized on the common, slowest part
(7763). Is 3× enough, given that an unlucky draw of a slower part has not
been observed but cannot be ruled out?
