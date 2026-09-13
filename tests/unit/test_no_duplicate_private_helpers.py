"""No module-level private helper is defined in more than one module (BIN-141).

**This project has consolidated the same duplication twelve times**, and
every instance was found *by accident* -- a human or an agent happening to
notice while doing something else. `BIN-124` (a triplicated Hypothesis
strategy), `BIN-125` (`_has_zero_variance`), and `BIN-141`'s own
`_require_target_arl` were each discovered that way. The check is a dozen
lines of `ast`; leaving it to attention is the part that keeps failing.

**Why duplication is consequential here rather than merely untidy.**
`BIN-119` added a second baseline rejection and put it in the *shared*
``_moving_range_sigma``, so all three charts inherited it automatically.
Had it landed in per-chart copies it would have needed writing three
times, and a miss in one produces a chart that **silently accepts what the
other two refuse** -- an authoritative-looking control limit derived from
data another chart rejects.

**Follows `BIN-124`'s precedent**: do not write a rule telling people to
keep copies in sync -- ask the codebase, and fail the build.

⚠️ **What this does NOT catch, stated so a green run is not over-read.**

* **It is a *name* check, not a similarity check.** A copy that was
  *renamed* passes cleanly. Every instance so far kept its name, which is
  why the check is worth having -- not evidence that it is sufficient.
* **Module-level definitions only.** Nested functions and methods
  legitimately share names across classes, and scanning them would produce
  noise that gets the test muted -- the failure mode `BIN-136` records.
* **It says nothing about *public* names**, which are deliberately
  re-exported across `__init__` modules.

**There is deliberately no allow-list.** If a genuine case ever needs the
same private name in two modules, add one *then* -- with a specific,
falsifiable reason per entry, the standard `BIN-136`'s grid set
(*"these are unrelated helpers that happen to share a name, because X"*,
never *"intentional"*). An allow-list nobody can evaluate is worse than no
test, because it reads as a decision when it is an exemption.
"""

from __future__ import annotations

import ast
import collections
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "caliper"


def _module_level_private_functions() -> dict[str, list[str]]:
    """Map each module-level private function name to the modules defining it."""
    definitions: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level only -- see the module docstring
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name.startswith("_")
                and not node.name.startswith("__")
            ):
                definitions[node.name].append(str(path.relative_to(_SRC.parent)))
    return definitions


def test_no_private_helper_is_defined_in_two_modules() -> None:
    """A private helper defined twice is a copy waiting to diverge."""
    duplicated = {
        name: modules
        for name, modules in _module_level_private_functions().items()
        if len(modules) > 1
    }

    assert not duplicated, (
        "private helpers defined in more than one module:\n"
        + "\n".join(
            f"  {name}\n" + "".join(f"      {m}\n" for m in modules)
            for name, modules in sorted(duplicated.items())
        )
        + "\nHoist the shared definition into the module that owns the "
        "concern -- spc_numerics.py for numerical predicates, "
        "parameter_guards.py for validation -- and import it. If the copies "
        "differ deliberately, parameterise the difference rather than "
        "keeping two bodies (BIN-141 did exactly that for the chart name in "
        "_require_target_arl's message)."
    )


def test_the_scan_actually_finds_functions() -> None:
    """The scan sees a healthy number of helpers, so a green run means something.

    🚨 **Without this, a scan that silently walked zero files would pass the
    test above forever** -- the vacuity shape this project has hit five
    times in two days, and exactly what a wrong ``_SRC`` path or an
    ``rglob`` typo would produce.
    """
    found = _module_level_private_functions()

    # 27 as of BIN-141 (2026-09-13). The floor sits well below that on
    # purpose: it exists to catch a scan finding *nothing*, not to track the
    # count, which would make this fail on ordinary refactoring.
    assert len(found) > 20, (
        f"only {len(found)} module-level private helpers found under {_SRC} -- "
        "the scan is probably looking in the wrong place, which would make "
        "the duplication test above pass vacuously"
    )
