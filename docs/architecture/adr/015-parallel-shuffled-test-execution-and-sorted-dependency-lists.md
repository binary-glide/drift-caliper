# ADR-015: Parallel, shuffled test execution, and sorted dependency lists

**Status:** ✅ **ACCEPTED — ratified by the product owner 2026-09-27.** Q1–Q4
were answered as recommended: the serial `wall_clock` step replaces
`loadgroup` (Q1); a hang guard running above 40 s of its 60 s on CI may be
raised to 3× the CI-measured duration, the measurement cited beside it (Q2);
the nightly full run goes parallel too, after the pre-merge full-suite
`workflow_dispatch` run in Verification item 7 (Q3); the ticket text is
corrected (Q4).
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
