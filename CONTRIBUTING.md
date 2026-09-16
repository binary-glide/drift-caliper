# Contributing

Caliper applies Statistical Process Control to LLM-as-a-judge quality scores. A
wrong control limit looks exactly like a right one — both produce confident
numbers. Most of the rules below exist because of that asymmetry.

Contributions are welcome. Open an issue before starting anything substantial,
so the design can be agreed before the code is written.

## Setting up

```bash
uv sync
uv run pre-commit install
```

`pre-commit install` installs the pre-commit and commit-message hooks together.

## The gates

All four must pass before you commit.

```bash
uv run pytest
uv run ruff check --no-cache . && uv run ruff format --check .
uv run ty check --error-on-warning
uv run mypy
```

The hooks run the last three. The test suite is not a hook: it takes about a
minute, and a gate that slow gets bypassed. CI runs it on 3.11, 3.12 and 3.13.

**Always pass `--no-cache` to ruff.** Ruff caches results per file, and its
import-sorting rules classify a module as first- or third-party by whether it
resolves. Introduce a package mid-branch and the files importing it keep their
cached classification, because those files did not change — so a local run can
report success on a tree CI rejects. Ruff takes well under a second either way.

**Both type checkers are required.** `ty` is the first gate. `mypy --strict`
stays because the package ships `py.typed`: its annotations are a public
contract that consumers check with mypy and pyright.

**Do not add `python_version` to the mypy configuration.** numpy's stubs use
syntax mypy rejects when the analysis target is below 3.12, so pinning the 3.11
floor breaks the gate on every newer interpreter. The floor is enforced by the
test matrix instead.

**Do not remove ruff's `*.md` exclusion.** Ruff formats Python inside markdown,
and the architecture decision records are fixed documents.

## Statistical correctness

Every numerical constant comes from a primary source. Cite it in the test that
pins the value — author, year, and the table or page.

If a value cannot be verified against a primary source, stop and say so rather
than approximating. An unverifiable constant is a blocker, not a detail.

This applies to the citation itself: take a reference from the work's own
reference list, not from a search result.

Any number a numerical routine returns to a caller needs a postcondition. The
type system will not tell you that a solver returned a plausible-looking wrong
answer.

## Errors

**The library raises; the caller decides.** Where Caliper cannot do its job —
invalid configuration, a provider failure, a malformed judge response, a missing
prerequisite — it raises. It does not swallow, warn and continue, or return a
default. Whether to abort, retry, degrade or log is the consuming application's
policy.

**Every exception leaving a public entry point is a `CaliperError`.** Nine typed
exceptions inherit from a flat `CaliperError` base, each declaring a `category`
and carrying a `context` mapping the caller can branch on:

```
invalid_parameter · missing_prerequisite · provider_failure
malformed_response · judge_refusal · provenance_mismatch
invalid_observation · insufficient_baseline · degenerate_baseline
```

A raw `TypeError`, `ValueError`, `KeyError` or `AttributeError` reaching a
caller is a defect. This includes exceptions raised by objects the caller
supplies: anything read off a caller-supplied value is untrusted, and a type
annotation on a parameter is a promise about the declaration, not a guarantee
about the value.

**Assert on the exception type and its `context` keys, never on message text.**
Wording is not part of the contract, and `recovery_hint` is written for a human
and deliberately untested. This is the one place Caliper departs from the
general house testing standard, which asserts on validation messages — that
standard is aimed at request schemas where the message is the response
contract, and this library has no such boundary. See ADR-008.

**Never apply beartype at a public boundary.** It raises
`BeartypeCallHintParamViolation`, which is not a `CaliperError` and carries
neither `category` nor `context`. beartype is a development-time tool here,
applied by an import hook over the numerical internals and absent from the
shipped wheel. Its value is catching numpy scalars in private helpers, where a
wrong dtype changes the answer without raising.

## Domain types

Value objects are Pydantic models with `ConfigDict(frozen=True)`. One per
module.

**Validation belongs in the value object, not in the caller.** Put it in a
field validator so no construction path can bypass it. A caller-side check is a
rule one new call site can miss.

Never mutate an argument. Return a new object.

Keep the dependency direction acyclic: a value object must not import the module
that consumes it.

Prefer plain exceptions to a `Result` type. The house standard reserves
`returns` for chains of heterogeneous failure types that would otherwise nest
try/except; a value object with one validation rule is not that.

## Truthiness

Do not give a type a truth value unless a field already carries that meaning.

- `SufficiencyResult.__bool__` returns `is_sufficient`.
- `ScoringResult` and the three fitted types raise `TypeError`, because none has
  a failed instance and inventing a truth value would move the trap rather than
  remove it.
- `Baseline` is a collection, so `__len__` makes it falsy when empty.

In tests this means `assert some_result` and `if fitted:` raise. Assert on a
field.

## The public API is the user interface

Caliper is imported into someone else's agent, so its API is what people
actually touch. Write the snippet an engineer would type before choosing a
shape.

- **Keep the common case short.** Optimise for the question asked most often,
  not the most general form.
- **What goes in should come out.** Passing a `str` and reading back a wrapper
  that needs `.value` taxes the caller for an internal decision.
- **Every public type should repr usefully.** The REPL, a log line and a
  debugger are all part of the interface.
- **Export what people need, not what modules contain.** Internal bounds and
  constants are noise on a public surface.
- **Errors are part of the interface.** `recovery_hint` says what to do next;
  `context` exists to be branched on without parsing prose.

Where ergonomics and correctness genuinely conflict, correctness wins and the
friction is recorded as a cost.

## Code style

- Type hints and a docstring on every public function. NumPy docstring style,
  88-column lines.
- Guard clauses at the top of a function; validate before doing work.
- Comments explain **why**, not what.
- No bare `except`.
- No magic numbers — name the constant.
- No mutable default arguments.
- Functions under roughly 40 lines; nesting no deeper than three levels.
- Composition over inheritance. Narrow `Protocol`s rather than broad base
  classes, and no hierarchy deeper than two levels.
- No provenance or bookkeeping markers in source comments. `git blame` records
  authorship, and these files ship to PyPI.

## Dependencies

- Runtime dependencies carry **lower bounds only**. An upper bound propagates
  into every consumer's resolution.
- Verify the current version from the package registry before pinning it. Never
  pin from memory.
- Do not add a runtime dependency speculatively. An unused dependency is a real
  cost to everyone who installs the library.

## Tests

`pytest`, `pytest-bdd` and `hypothesis`. Tests live in `tests/unit` and
`tests/bdd`.

- Arrange, Act, Assert, in three visible phases, with one act per test.
- Name tests `test_<verb>_<expected>_when_<condition>`.
- Tests must be deterministic — no reliance on wall-clock time, network, or
  execution order.
- Coverage has an enforced floor, but treat it as a signal for finding untested
  paths, not a target. Mutation testing (`mutmut`) is the stronger signal on
  numerical modules.
- Feature files describe capability, never mechanism. A scenario should survive
  a change of implementation without rewording.
- A bug fix ships with a test demonstrated to fail without the fix.

Two failure modes are worth checking for deliberately, because neither shows up
in a coverage report:

- **A test that passes for the wrong reason.** If a strategy is rejected on
  nearly every draw, or a guard clause makes an assertion unreachable, the test
  is counted and proves nothing. Confirm a test has power by breaking the code
  it covers, not by reading it.
- **Inputs that are individually legal but jointly invalid.** Widening a
  strategy outward will not find them; assert that the legal region is coherent
  — for instance, that any bound the library reports is accepted back as input.

## What is enforced for you

Some rules fail the build. The rest rely on you having read this file.

| Rule | Enforced by |
|---|---|
| Lint, format, both type checkers | The gates, and pre-commit |
| Commit message format | `commit-msg` hook |
| No `assert` in shipped code | `tests/unit/test_structural_invariants.py` |
| No bare `hasattr` | `tests/unit/test_structural_invariants.py` |
| No `statistics.mean` / `fmean` | `tests/unit/test_structural_invariants.py` |
| No provenance markers in comments | `tests/unit/test_structural_invariants.py` |
| Every `pragma: no cover` justified | `tests/unit/test_structural_invariants.py` |
| Only `CaliperError` escapes a public entry point | `tests/support/exception_contract_registry.py` |
| Published examples actually run | `tests/unit/test_documentation_examples.py` |
| Everything else here | You |

The structural checks catch only the spellings someone anticipated. They do not
replace a behavioural test.

## Commits and pull requests

Commit subjects use Conventional Commits with a leading gitmoji:

```
<gitmoji> <type>[(<scope>)]: <description>

📝 docs: lead the install instructions with uv
🐛 fix(baseline): reject a non-finite control limit
```

The `commit-msg` hook enforces this locally. Pull requests are squash-merged, so
the **pull request title becomes the commit subject on the trunk branch** — give
it the same shape.

Before tagging a release, regenerate the changelog:

```bash
uv run git-cliff -o CHANGELOG.md
```

## Reporting a security issue

See [SECURITY.md](SECURITY.md). Please do not open a public issue for a
suspected vulnerability.
