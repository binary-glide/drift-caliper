# ADR-007: Run both `ty` and `mypy --strict`, deliberately

**Status:** Accepted
**Date:** 2026-09-09
**Deciders:** ratified by product owner (BIN-103)
**Refs:** BIN-103, BIN-85, `coding-standards/references/python.md`

## Context

`coding-standards/references/python.md` names one type checker in its Tooling
table:

| Purpose | Tool |
|---|---|
| Type checking | `ty` |

Caliper runs two — `ty check --error-on-warning` first, then `mypy --strict`.
Both are CI gates. That is a departure from the house standard and needs to be
on the record as a decision rather than left to look like drift, because the
obvious tidy-up for any future agent is to delete the one the standard does not
name.

The standard was written for internal FastAPI services. Caliper is different in
one respect that bears directly on type checking: **it is published to PyPI and
ships `py.typed`.** BIN-85 states the library ships with strict type
annotations. Once `py.typed` is in the wheel, those annotations stop being an
internal development aid and become part of the public contract — consumers
type-check *their* code against *our* annotations, using whatever checker they
run, which in practice is mypy or pyright far more often than `ty`.

## Decision

**Both run. `ty` is the first gate; `mypy --strict` is the second.**

`ty` is the house Astral toolchain, sits alongside `uv` and `ruff`, and is fast
enough to run on every save.

`mypy --strict` stays for a specific, narrow reason: **`ty` 0.0.x has no strict
mode.** At the time of writing it is version 0.0.79, `Development Status :: 4 -
Beta` (verified live on PyPI, 2026-09-09), and its CLI has no `--strict` and no
equivalent of `disallow_untyped_defs` or `disallow_any_generics`. Those are the
precise checks that make BIN-85's "ships with strict type annotations"
enforceable rather than aspirational. Without them, an untyped function or an
implicit `Any` reaches a consumer's type checker as a hole in our public
contract, and nothing in our own CI would have objected.

Running both costs roughly 16 seconds combined in CI. That is not a meaningful
price for the guarantee.

### Do not add `python_version` to the mypy config

Recorded here because it is a trap that has already cost a red CI run.

numpy's bundled stubs use PEP 695 `type` statements. mypy rejects those as a
**syntax error** whenever the analysis target is below 3.12 — so pinning
`python_version = "3.11"` to match Caliper's floor fails on any 3.12+
interpreter with numpy installed, which is CI and every developer machine.
Reproduced on 3.12 and 3.13. It passes only on a 3.11 venv, the least likely
setup anyone actually runs.

The 3.11 floor is enforced where it can be enforced honestly: the pytest matrix
runs the full suite on 3.11, 3.12 and 3.13, so 3.12-only syntax in `src` fails
the 3.11 job at import. The reasoning is duplicated in `pyproject.toml` next to
the config it governs.

## Consequences

- Two checkers must both stay green. A disagreement between them is a signal
  worth investigating, not a nuisance to suppress.
- Suppression comments come in pairs where the two disagree — e.g.
  `# type: ignore[assignment]  # ty: ignore[invalid-assignment]`. Slightly
  noisy, and the honest cost of the decision.
- One capability was lost in the Pydantic migration and is worth knowing about:
  mypy used to catch frozen-**dataclass** assignment statically. It cannot see
  that a Pydantic model is frozen, so that guarantee is now runtime-only,
  asserted by tests rather than by the type checker.

## Reversibility

**Low cost, and the exit condition is concrete.** Drop `mypy` the moment `ty`
gains a strict mode with an equivalent of `disallow_untyped_defs` — remove the
dependency, the `[tool.mypy]` block, the CI step, and this ADR's justification
in one commit. Nothing in `src/` depends on which checker runs.

Revisit when `ty` reaches 1.0, or sooner if it ships strictness.

## Alternatives considered

### `ty` only, per the standard as written

The straightforward reading of the house rule. Rejected because it would make
BIN-85's strict-annotations claim unverifiable by any gate — it would rest on
`ty`'s defaults plus reviewer attention, and reviewer attention is exactly what
failed on this project already (see BIN-103).

Worth restating: this is not a judgement that the standard is wrong. For an
internal service whose annotations no external consumer ever checks, `ty` alone
is the right call and the standard is correct as written.

### `mypy` only

Rejected. `ty` is the house toolchain, is materially faster, and being the
first gate means most type errors surface in the fast check.

### `mypy` as a release-only gate, not on every PR

Rejected as worse than either alternative: a check that runs only at release
finds problems when they are most expensive to fix, and a contributor gets no
signal while the code is still in their head.
