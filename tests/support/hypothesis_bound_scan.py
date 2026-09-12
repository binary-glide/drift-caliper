"""AST scanner enumerating every numeric Hypothesis strategy bound in ``tests/``.

**BIN-124, round 2.** Round 1 built a guard for one dimension (baseline
scores) that a new ``src/`` rejection could silently turn illegal. Round 2
(this ticket's reopening comment, 2026-09-12) found that guard's own
docstring had *already* named its blind spot -- ``target_arl`` and its
siblings, which were duplicated across eight files, not triplicated the way
scores were, so they were never brought under Part A's consolidation. ADR-011
then narrowed ``target_arl`` and none of those eight strategies noticed by
themselves; it happened, in this instance, only because every site already
imported the shared ``MIN_TARGET_ARL`` constant rather than a stale literal.

**The completeness problem, stated rather than solved away.** Round 1's own
meta-test is a curated, hand-written check over a strategy the author knew
about. A hand-curated registry of "the parameters we currently know are
library-validated" has the identical weakness: it catches today's known
bounds and silently misses a ninth file added tomorrow. `BIN-121`'s
exception-contract audit solved the equivalent problem for *exported
names* by enumerating ``caliper.__all__`` -- a real, mechanically
enumerable surface that cannot be forgotten about, because forgetting to
export a name does not make it stop being exported.

There is no equivalent *behavioural* surface for "every Hypothesis
strategy bound in the test suite" -- nothing in ``src/`` enumerates the
test suite's own strategies. What **is** mechanically enumerable is the
*source text* of the test suite itself: every ``min_value=``/``max_value=``
keyword passed to ``st.floats``/``st.integers``/``st.decimals`` is a
syntactic fact about a ``.py`` file, discoverable by parsing it, with no
need to run anything and no need to already know the file exists. This
module does exactly that: a plain AST walk, so a new file, a new
``@given`` parameter, or a new strategy factory function is *found*
automatically the next time this scanner runs -- it need not be
separately registered anywhere for its *existence* to be noticed.

**What this scanner deliberately does not decide.** Finding a bound is not
the same as knowing whether it feeds a parameter the library validates
(``target_arl``) or a pure simulation knob (``scale``, ``shift``) -- that
classification is a domain judgement this module has no way to make from
syntax alone, and ``tests/support/parameter_bound_registry.py`` is where it
is made, deliberately, by a human, once per distinct name. The scanner's
job stops at *making every site impossible to silently miss*; the registry
and the meta-test in
``tests/unit/baseline/test_parameter_strategy_contract.py`` are what force
each discovered site into a classification before the suite passes.

**Two tiers of site, matching the two shapes this suite actually uses:**

1. **Direct** -- a keyword argument of a ``@given(...)`` decorator whose
   strategy subtree contains a ``min_value=``/``max_value=`` bound, e.g.
   ``@given(target_arl=st.floats(min_value=MIN_TARGET_ARL, ...))``. Tagged
   with ``given_parameter`` -- the ``@given`` keyword name (``"target_arl"``
   above). This is every real site in this suite today except one.
2. **Factory** -- a ``min_value=``/``max_value=`` bound inside a plain
   function's body, not directly inside any ``@given(...)`` (e.g.
   ``baseline_scores_strategy()`` in ``tests/support/baseline_strategies.py``,
   called as ``@given(scores=baseline_scores_strategy())`` -- the bound
   itself lives one level of indirection away from the decorator). Tagged
   with ``factory_function`` instead of ``given_parameter``.

**Scope, stated rather than assumed.** This scanner only looks at
module-level (non-nested, non-class-method) function definitions --
verified directly, not assumed: this codebase has zero ``class Test...``
suites and zero nested ``def`` inside a Hypothesis-decorated test anywhere
under ``tests/`` (grepped before writing this module). A future test class
or a strategy factory nested inside another function would not be found.
Extending to genuinely arbitrary nesting is possible (walk every
``FunctionDef` regardless of ancestry, deduplicating by node identity) but
was not needed for the pattern this suite actually uses, and the added
complexity was judged not worth carrying for a hypothetical shape that does
not exist here today.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_NUMERIC_STRATEGY_FUNCS = frozenset({"floats", "integers", "decimals"})
_BOUND_KEYWORDS = frozenset({"min_value", "max_value"})
_GIVEN_NAMES = frozenset({"given"})


@dataclass(frozen=True)
class BoundSite:
    """One ``min_value=``/``max_value=`` keyword on a numeric Hypothesis strategy.

    ``given_parameter`` is set when the bound sits directly inside a
    ``@given(...)`` decorator's keyword subtree (Tier 1 -- see module
    docstring); ``factory_function`` is set instead when it was found in a
    plain function body (Tier 2). Exactly one of the two is ever set.
    """

    file: str
    lineno: int
    bound_kind: str
    bound_source: str
    given_parameter: str | None
    factory_function: str | None


def _numeric_strategy_func_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _NUMERIC_STRATEGY_FUNCS:
        return func.attr
    if isinstance(func, ast.Name) and func.id in _NUMERIC_STRATEGY_FUNCS:
        return func.id
    return None


def _given_call(node: ast.AST) -> ast.Call | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = (
        func.attr
        if isinstance(func, ast.Attribute)
        else func.id
        if isinstance(func, ast.Name)
        else None
    )
    return node if name in _GIVEN_NAMES else None


def _sites_from_strategy_call(
    call: ast.Call,
    *,
    file: str,
    given_parameter: str | None,
    factory_function: str | None,
) -> list[BoundSite]:
    return [
        BoundSite(
            file=file,
            lineno=kw.value.lineno,
            bound_kind=kw.arg,  # narrowed non-None by the `if` filter below
            bound_source=ast.unparse(kw.value),
            given_parameter=given_parameter,
            factory_function=factory_function,
        )
        for kw in call.keywords
        if kw.arg in _BOUND_KEYWORDS
    ]


def _scan_function(node: ast.FunctionDef, *, file: str) -> list[BoundSite]:
    sites: list[BoundSite] = []

    # Tier 1: bounds nested inside a `@given(...)` decorator's keywords.
    for decorator in node.decorator_list:
        given = _given_call(decorator)
        if given is None:
            continue
        for kw in given.keywords:
            if kw.arg is None:  # `@given(**something)` -- not used in this suite
                continue
            for inner in ast.walk(kw.value):
                if isinstance(inner, ast.Call) and _numeric_strategy_func_name(inner):
                    sites.extend(
                        _sites_from_strategy_call(
                            inner,
                            file=file,
                            given_parameter=kw.arg,
                            factory_function=None,
                        )
                    )

    # Tier 2: bounds inside the function's own body -- a strategy factory.
    for stmt in node.body:
        for inner in ast.walk(stmt):
            if isinstance(inner, ast.Call) and _numeric_strategy_func_name(inner):
                sites.extend(
                    _sites_from_strategy_call(
                        inner,
                        file=file,
                        given_parameter=None,
                        factory_function=node.name,
                    )
                )

    return sites


def scan_module(path: Path, *, label: str) -> list[BoundSite]:
    """Scan one ``.py`` file's top-level function definitions for bound sites."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: list[BoundSite] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            sites.extend(_scan_function(node, file=label))
    return sites


def scan_tests_tree(root: Path) -> list[BoundSite]:
    """Scan every ``.py`` file under ``root`` (expected: the repo's ``tests/`` dir).

    ``label`` on each returned :class:`BoundSite` is the path relative to
    ``root``'s parent (e.g. ``tests/unit/baseline/test_ewma_fitting.py``) --
    stable, readable, and usable as a dotted module path with ``.py``
    stripped and ``/`` replaced by ``.``.
    """
    sites: list[BoundSite] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        label = str(path.relative_to(root.parent)).replace("\\", "/")
        sites.extend(scan_module(path, label=label))
    return sites


def module_dotted_name(label: str) -> str:
    """Convert a scanned file's relative label to an importable dotted module name."""
    return label[: -len(".py")].replace("/", ".")
