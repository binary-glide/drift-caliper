"""AST scanner enumerating every numeric Hypothesis strategy bound in ``tests/``.

**BIN-124, round 3.** Round 2 built a curated registry over every bound the
scanner could see -- but its own reopening comment (2026-09-12) found a bound
the scanner could not see at all: a ``@given`` keyword argument that is a bare
module-level constant, e.g.::

    _SHARED = st.floats(min_value=1.0, max_value=9.0)   # 1.0 illegal as target_arl

    @given(target_arl=_SHARED)
    def test_something(target_arl: float) -> None: ...

Round 2's scanner only walked a ``@given(...)`` keyword's *own* value
subtree, or a plain function's *own* body (Tier 2). ``_SHARED`` is neither --
it is a name, resolved elsewhere, and the old scanner never followed it. That
site scored 85/85 and reported nothing: not "classified", not "excluded",
simply never visited. The refactor that produces this shape is not
hypothetical -- ``BIN-122``'s implementer reached for exactly this to avoid
repeating an identical strategy across three ``@given`` calls, then inlined it
three times instead once the scanner was found blind to it (see
``tests/unit/baseline/test_joint_parameter_validity.py``'s own comment on
this, written before round 3 existed to fix it).

**Round 3 does two things, not one.**

**Part A -- resolve a bare-Name ``@given`` argument to its module-level
assignment.** When a ``@given`` keyword's value is an ``ast.Name``, this
scanner looks for a top-level ``<name> = <expr>`` assignment earlier in the
*same file* and scans ``<expr>``'s subtree instead -- exactly as if the
strategy had been written inline. The discovered :class:`BoundSite` still
carries the ``@given`` keyword's own parameter name (so it classifies against
the same registry as every other site for that parameter), but its
``lineno`` points at the assignment, not the ``@given`` call -- so a reader
goes straight to the constant that needs updating, not to the call site
that merely used it.

A single shared constant feeding *two different* governed parameter names
(e.g. ``_SHARED`` used both as ``target_arl=_SHARED`` in one test and
``reference_value=_SHARED`` in another) is handled, not silently resolved
one way: resolution happens once per ``@given`` keyword, independently, so
the same assignment produces one :class:`BoundSite` per distinct parameter
name that references it, each classified and probed against *that
parameter's own* legal range. Nothing here ever has to decide which of two
meanings a constant "really" has -- both are checked.

**Part B -- fail loudly on anything Part A still cannot resolve.** A
``@given`` keyword's value may be built by a helper function, imported from
another module, chained through ``.map()``/``.filter()``, or otherwise
composed in a way this scanner cannot see through. Before round 3, all of
these produced the same silence Part A closes for the bare-Name case: zero
sites, nothing to classify, nothing to fail. Round 3 replaces that silence
with an explicit, named failure -- see
:class:`UnresolvedGivenSite` and
``tests/unit/baseline/test_parameter_strategy_contract.py``'s
``test_no_given_argument_is_left_unresolved``, which fails by
``file:line:parameter`` the moment such a site is found, rather than a
generative test one clean site short of a check on it.

**Why Part A must exist before Part B is not hostile.** Without Part A, a
module-level constant -- an entirely ordinary refactor -- would trip Part B's
failure, actively pushing authors back toward the triplicated-literal style
``BIN-122`` was forced into. Part A is what keeps the tidy form of the code
legal; Part B is what stops every *other* shape from vanishing silently
instead.

**A latent imprecision Part B's stricter checking forced into the open.**
``tests/bdd/steps/*.py`` decorates step functions with a same-named
``@given(...)`` from ``pytest_bdd`` -- a Gherkin step registration
(``@given("some step text", target_fixture="...")``), not a Hypothesis
strategy parametrisation. Rounds 1 and 2 matched a decorator named "given"
by name alone and got away with it, because a ``pytest_bdd`` keyword's
value (always a plain string) never contained a numeric-strategy call
either way -- silently zero sites, indistinguishable from "not applicable".
Part B's "every keyword must resolve to *something*" check does not get
that pass for free: a bare string is not a resolvable strategy under the
new rule, so every ``target_fixture=`` keyword in every BDD step file
started failing the moment Part B was added. Fixed at the root rather than
carved around: :func:`_hypothesis_given_names` resolves, per module, which
local name its *imports* bind to ``hypothesis``'s ``given`` (``from
hypothesis import given``), and only a decorator call matching one of
those names is ever treated as a Hypothesis ``@given``. ``pytest_bdd``'s
``@given`` (imported ``from pytest_bdd import given``) is never scanned at
all now, correctly, rather than being scanned and happening not to match
anything.

**Two tiers of site, matching the two shapes this suite actually uses,
unchanged from round 2:**

1. **Direct** -- a keyword argument of a ``@given(...)`` decorator whose
   (possibly Part-A-resolved) strategy subtree contains a
   ``min_value=``/``max_value=`` bound, e.g.
   ``@given(target_arl=st.floats(min_value=MIN_TARGET_ARL, ...))``. Tagged
   with ``given_parameter`` -- the ``@given`` keyword name (``"target_arl"``
   above).
2. **Factory** -- a ``min_value=``/``max_value=`` bound inside a plain
   function's own body, not directly inside any ``@given(...)`` (e.g.
   ``baseline_scores_strategy()`` in ``tests/support/baseline_strategies.py``,
   called as ``@given(scores=baseline_scores_strategy())``). Tagged with
   ``factory_function`` instead of ``given_parameter``. Round 3 does not
   change Tier 2 in any way -- see "What remains out of scope" below.

**What counts as "resolved" for a ``@given`` keyword's value, precisely --
and why this is a recursive property, not a one-hop check
(BIN-124 round 3, Blocker 1).** An initial version of this scanner trusted
any call shaped like ``st.<attr>(...)`` outright and stopped looking. That
missed a real case: a Hypothesis *combinator* -- ``st.one_of(...)``,
``st.builds(...)``, ``st.recursive(...)``, ``st.deferred(...)``, or any
future one -- takes further strategies as its own arguments, and one of
those arguments can itself be an unresolvable or illegal-bound ``Name``:

.. code-block:: python

    _ILLEGAL_NAMED = st.floats(min_value=1.0, max_value=9.0)  # illegal target_arl

    @given(
        target_arl=st.one_of(
            _ILLEGAL_NAMED, st.floats(min_value=500.0, max_value=600.0)
        )
    )

Trusting ``st.one_of(...)`` at the top level and walking only its own
subtree finds the *inline* branch's bound (500.0/600.0) but never
``_ILLEGAL_NAMED``'s -- a ``Name`` leaf has no children to walk into.
That reproduces Part B's exact failure mode, one layer deeper, through a
combinator instead of a bare ``@given`` argument.

**The general rule, not a per-combinator allowlist:** a value is resolved
only if *every* call reachable from it -- at the top level and inside any
positional argument, list/tuple/set element, or non-bound keyword argument
of a trusted call, recursively -- is itself one of:

* a direct call whose function is an attribute access on the ``hypothesis``
  strategies module (``st.floats(...)``, ``st.one_of(...)``,
  ``st.sampled_from(...)``, ...) -- the module alias this suite always
  uses, verified by grep before writing this module (``st`` and,
  defensively, the unabbreviated ``strategies``);
* a bare call to one of the numeric strategy constructors imported by name
  (``floats(...)``, matching the same set ``_numeric_strategy_func_name``
  already recognised in Tier 1); or
* a zero-argument call to a function defined at module level *somewhere*
  under ``tests/`` -- a strategy-factory reference, Tier 2's own territory
  (e.g. ``baseline_scores_strategy()``). This is deliberately permissive
  about *which* top-level function: it does not re-verify that the callee
  is Hypothesis-shaped, only that it is a real, statically-discoverable,
  argument-free, module-level ``def`` in the test suite -- the same
  standard Tier 2 already applies when it scans that function's own body
  independently. A function whose name begins with ``test_`` is excluded
  from this set (a test function is never a legitimate strategy factory);

and every ``Name`` reachable the same way (as the value itself, or as one
of a trusted call's arguments) resolves to a same-file module-level
assignment, applied recursively to what it resolves to -- with a cycle
guard, since nothing about a self-referential assignment chain is
otherwise excluded by construction. This is why the check is a walk over
the whole reachable shape, not a single dispatch on the outermost node.

``min_value=``/``max_value=`` keyword arguments are the one deliberate
exception to "every argument is recursed into" -- they hold numeric bound
*values*, not nested strategies, and are resolved by the separate
``_resolve_bound_value`` mechanism in the meta-test (which, unlike this
recursion, accepts an *imported* name, not only a same-file one -- a
genuinely different rule for a genuinely different question, so the two
must not be conflated or merged).

Anything else -- a call to a name that is not module-level anywhere in
``tests/`` (imported from elsewhere, or a nested ``def``/closure Tier 2 was
already documented not to reach), a ``.filter()``/``.map()``/``.flatmap()``
chain (its outermost call's function is an attribute of *another call*, not
of the strategies module), or any other composite expression -- is
unresolved, and reported as such rather than silently producing zero sites,
**no matter how deep inside a trusted combinator it sits.**

**What this scanner still does not decide.** Finding a bound, or finding
that a bound cannot be found, is not the same as knowing whether a *found*
bound feeds a parameter the library validates (``target_arl``) or a pure
simulation knob (``scale``, ``shift``) -- that classification is a domain
judgement made once per distinct name in
``tests/support/parameter_bound_registry.py``, by a human, exactly as in
round 2. This module's job is discovery and resolvability; classification
and library-acceptance probing are the registry's and the meta-test's.

**What remains out of scope for round 3, named rather than assumed away:**

* **Tier 2 factory function bodies are not Part-A/B resolved.** A Tier-2
  factory that itself referenced a module-level constant, or delegated to
  another helper, would not have that reference followed -- only ``@given``
  keyword arguments are. No such factory exists in this suite today
  (``baseline_scores_strategy()`` -- the only Tier-2 site -- writes its
  bound inline), so this is a stated boundary, not a known live gap.
* **A ``@given`` nested inside another function's body is still
  misattributed to Tier 2**, losing the real parameter name -- round 2's
  ``code-reviewer`` found this and it is unchanged here; no site of this
  shape exists in the suite today (verified by the same grep as round 2).
* **A ``@given`` decorating a method inside a ``class Test...:`` body is
  still invisible outright** -- ``scan_module`` only iterates a module's
  top-level statements. No such class exists in this suite today.
* **Positional (non-keyword) ``@given`` arguments are not scanned at all**,
  resolved or not -- e.g. ``@given(st.text(...).filter(...))`` in
  ``test_judge.py``/``test_criteria.py``. Verified directly: no positional
  ``@given`` argument in this suite is a numeric strategy, so this scans
  zero real sites out, but a future numeric positional argument would be
  silently invisible, not loudly rejected. This is the one honest remaining
  gap: neither "impossible to silently miss" (the module's own overclaim,
  corrected by this docstring) nor converted to a loud failure by Part B,
  because Part B is scoped to keyword arguments only, matching Part A.
* **A bound's own *value* expression** (``min_value=<this>``) that is
  neither a literal nor a bare module-level name is a separate, already-
  handled resolution failure -- see
  ``test_parameter_strategy_contract.py``'s ``_resolve_bound_value``. Round
  3 does not change that mechanism; it only changes which ``@given``
  keyword *arguments* the scanner can reach in the first place.

**The corrected claim.** Round 1 and round 2's module docstrings both said
some form of "a new file or ``@given`` parameter cannot be silently missed."
That was true only for bounds written in one of the syntactic positions this
scanner watches, which is narrower than stated. The accurate claim, after
round 3: every ``@given`` keyword argument is either (a) resolved to a
concrete strategy expression this scanner can walk for bounds, or (b)
reported as an explicit, named resolution failure -- **except** a numeric
bound reached only through a positional ``@given`` argument, which remains
genuinely invisible, as stated above, because no real site of that shape
exists to justify building the mechanism speculatively.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_NUMERIC_STRATEGY_FUNCS = frozenset({"floats", "integers", "decimals"})
_BOUND_KEYWORDS = frozenset({"min_value", "max_value"})
_STRATEGY_MODULE_ALIASES = frozenset({"st", "strategies"})


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


@dataclass(frozen=True)
class UnresolvedGivenSite:
    """A ``@given`` keyword argument Part A could not resolve (BIN-124 round 3).

    Reported instead of silently producing zero :class:`BoundSite` entries
    for that keyword -- see the module docstring's "Part B" section.
    """

    file: str
    lineno: int
    given_parameter: str
    detail: str


@dataclass(frozen=True)
class ScanResult:
    """Everything one AST walk over ``tests/`` found: resolved sites and
    ``@given`` arguments Part A/B could not resolve."""

    sites: tuple[BoundSite, ...]
    unresolved: tuple[UnresolvedGivenSite, ...]


def _numeric_strategy_func_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _NUMERIC_STRATEGY_FUNCS:
        return func.attr
    if isinstance(func, ast.Name) and func.id in _NUMERIC_STRATEGY_FUNCS:
        return func.id
    return None


def _hypothesis_given_names(tree: ast.Module) -> frozenset[str]:
    """Local names this module's imports bind to *Hypothesis's* ``given``.

    ``tests/bdd/steps/*.py`` also decorates functions with a same-named
    ``@given(...)`` from ``pytest_bdd`` -- a Gherkin step registration that
    takes a step-text string (and often ``target_fixture=<a plain string>``),
    not a Hypothesis strategy. Before round 3 this conflation was harmless:
    the old scanner only ever found numeric-strategy calls inside a
    ``@given`` keyword's value, and ``pytest_bdd``'s keywords never contain
    one, so it silently produced zero sites either way. Part B's stricter
    "every keyword value must resolve" check does not get that pass for
    free -- a plain string is not a resolvable strategy, so telling the two
    decorators apart is now required, not cosmetic. Resolved from imports
    (``from hypothesis import given`` / ``... as g``), never from the name
    "given" alone.
    """
    names: set[str] = set()
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "hypothesis":
            for alias in stmt.names:
                if alias.name == "given":
                    names.add(alias.asname or alias.name)
    return frozenset(names)


def _given_call(
    node: ast.AST, *, hypothesis_given_names: frozenset[str]
) -> ast.Call | None:
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
    return node if name in hypothesis_given_names else None


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


def _is_trusted_strategy_call(
    call: ast.Call, *, known_factory_names: frozenset[str]
) -> bool:
    """True if ``call``'s outermost shape is one round 3 can vouch for.

    See the module docstring's "What counts as 'resolved'" section for the
    full reasoning. A ``.filter()``/``.map()``/``.flatmap()`` chain fails
    this check by construction: its outermost call's function is an
    attribute of *another call* (the thing being chained from), never of
    the strategies module itself -- so it is never mistaken for a trusted
    direct strategy construction, and falls through to Part B.
    """
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id in _STRATEGY_MODULE_ALIASES
    if isinstance(func, ast.Name):
        if func.id in _NUMERIC_STRATEGY_FUNCS:
            return True
        return func.id in known_factory_names and not call.args and not call.keywords
    return False


def _resolve_given_value(
    value: ast.expr,
    *,
    module_assignments: dict[str, ast.expr],
    known_factory_names: frozenset[str],
    visited: frozenset[str],
) -> tuple[list[ast.expr] | None, int, str | None]:
    """Validate ``value`` and collect every sub-expression reachable only
    through a same-file Name assignment (Part A).

    **BIN-124 round 3, Blocker 1 fix.** A trusted top-level call is not
    enough -- a combinator (``st.one_of``, ``st.builds``, ``st.recursive``,
    ``st.deferred``, or any future one) can itself take further strategies
    as arguments, and a bare ``Name`` sitting in one of *those* positions
    must be resolved and verified exactly as the top-level ``@given`` value
    would be. Trusting any call whose function is ``st.<attr>`` without
    looking at its arguments would let ``st.one_of(_ILLEGAL_NAMED,
    st.floats(...))`` through with ``_ILLEGAL_NAMED``'s bound never
    classified *or* reported unresolved -- the exact silent gap Part B
    exists to close, reached one layer deeper. So this function recurses
    into every positional argument and every non-bound keyword argument of
    a trusted call, validating each the same way.

    ``min_value=``/``max_value=`` keyword arguments are exempt from this
    recursion -- they are numeric bound *values*, resolved by an entirely
    separate mechanism
    (``tests/unit/baseline/test_parameter_strategy_contract.py``'s
    ``_resolve_bound_value``) that deliberately supports a plain literal or
    an *imported* module-level name (not just a same-file assignment) --
    a genuinely different resolution rule, so the two must not be
    conflated. A bound keyword's own value is never itself a nested
    strategy.

    Returns ``(extra_subexprs, lineno, None)`` on success. ``extra_subexprs``
    is every sub-expression reached *only* via a same-file Name assignment
    -- these sit outside ``value``'s own AST subtree, so a plain
    ``ast.walk(value)`` would never see their bounds; the caller must walk
    each of them too, alongside ``value`` itself. An inline nested call
    (``st.floats(...)`` written directly as an argument to ``st.one_of``)
    needs no separate entry -- walking ``value`` already reaches it, and
    adding it again would report its bounds twice.

    Returns ``(None, lineno, detail)`` when anything reachable -- at the
    top level or nested inside a trusted combinator's arguments -- is
    untrusted or unresolvable (Part B). ``lineno`` is the point resolution
    got stuck, ``detail`` explains why.
    """
    if isinstance(value, ast.Constant):
        return [], value.lineno, None
    if isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant):
        return [], value.lineno, None
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        extra: list[ast.expr] = []
        for element in value.elts:
            nested, lineno, detail = _resolve_given_value(
                element,
                module_assignments=module_assignments,
                known_factory_names=known_factory_names,
                visited=visited,
            )
            if nested is None:
                return None, lineno, detail
            extra.extend(nested)
        return extra, getattr(value, "lineno", 0), None
    if isinstance(value, ast.Name):
        if value.id in visited:
            return (
                None,
                value.lineno,
                f"circular module-level assignment resolving {value.id!r}",
            )
        assigned = module_assignments.get(value.id)
        if assigned is None:
            return (
                None,
                value.lineno,
                f"{value.id!r} is not a module-level assignment in this file "
                "(imported from elsewhere, or not a plain top-level name)",
            )
        nested, lineno, detail = _resolve_given_value(
            assigned,
            module_assignments=module_assignments,
            known_factory_names=known_factory_names,
            visited=visited | {value.id},
        )
        if nested is None:
            return None, lineno, detail
        # `assigned` is not part of the caller's own AST subtree -- it (and
        # anything it in turn resolved via a further Name) must be walked
        # for bounds separately.
        return [assigned, *nested], lineno, None
    if isinstance(value, ast.Call):
        if not _is_trusted_strategy_call(
            value, known_factory_names=known_factory_names
        ):
            return (
                None,
                value.lineno,
                "not an inline `st.<name>(...)` call, a resolvable module-level "
                "name, or a recognised zero-argument tests/ strategy-factory "
                "call -- built by a helper function this scanner cannot see "
                "into, imported from another module, chained via "
                "`.map()`/`.filter()`/`.flatmap()`, or otherwise composed",
            )
        extra = []
        for arg in value.args:
            nested, lineno, detail = _resolve_given_value(
                arg,
                module_assignments=module_assignments,
                known_factory_names=known_factory_names,
                visited=visited,
            )
            if nested is None:
                return None, lineno, detail
            extra.extend(nested)
        for kw in value.keywords:
            if kw.arg in _BOUND_KEYWORDS:
                continue  # a numeric bound *value* -- _resolve_bound_value's job
            nested, lineno, detail = _resolve_given_value(
                kw.value,
                module_assignments=module_assignments,
                known_factory_names=known_factory_names,
                visited=visited,
            )
            if nested is None:
                return None, lineno, detail
            extra.extend(nested)
        return extra, value.lineno, None
    return (
        None,
        getattr(value, "lineno", 0),
        f"a {type(value).__name__} is not a strategy expression this "
        "scanner resolves (expected a call, a module-level name, a "
        "literal, or a list/tuple/set of these)",
    )


def _module_level_assignments(tree: ast.Module) -> dict[str, ast.expr]:
    """Simple ``NAME = <expr>`` assignments at module top level, last wins.

    Only single-target, single-name assignments are recognised -- tuple
    unpacking and multi-target assignments are not a pattern this suite
    uses for strategy constants (verified by grep before writing this).
    """
    assignments: dict[str, ast.expr] = {}
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            assignments[stmt.targets[0].id] = stmt.value
    return assignments


def _top_level_function_names(tree: ast.Module) -> set[str]:
    """Every module-level ``def`` name, excluding test functions themselves.

    Used only to decide whether a zero-argument call in a ``@given``
    keyword is a legitimate strategy-factory reference (Tier 2's own
    territory, e.g. ``baseline_scores_strategy()``) -- not to re-verify
    that the callee actually builds a Hypothesis strategy, which Tier 2
    already checks independently when it scans that function's own body.
    """
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_")
    }


def _scan_function(
    node: ast.FunctionDef,
    *,
    file: str,
    module_assignments: dict[str, ast.expr],
    known_factory_names: frozenset[str],
    hypothesis_given_names: frozenset[str],
) -> tuple[list[BoundSite], list[UnresolvedGivenSite]]:
    sites: list[BoundSite] = []
    unresolved: list[UnresolvedGivenSite] = []

    # Tier 1: bounds nested inside a `@given(...)` decorator's keywords.
    # `hypothesis_given_names` excludes `pytest_bdd`'s same-named decorator
    # -- see `_hypothesis_given_names`'s docstring.
    for decorator in node.decorator_list:
        given = _given_call(decorator, hypothesis_given_names=hypothesis_given_names)
        if given is None:
            continue
        for kw in given.keywords:
            if kw.arg is None:  # `@given(**something)` -- not used in this suite
                continue
            extra_subexprs, lineno, detail = _resolve_given_value(
                kw.value,
                module_assignments=module_assignments,
                known_factory_names=known_factory_names,
                visited=frozenset(),
            )
            if extra_subexprs is None:
                unresolved.append(
                    UnresolvedGivenSite(
                        file=file,
                        lineno=lineno,
                        given_parameter=kw.arg,
                        detail=detail or "unresolvable",
                    )
                )
                continue
            # `kw.value` itself, plus every sub-expression reached only
            # through a same-file Name assignment (Blocker 1: a trusted
            # combinator's own arguments can hide further such names) --
            # each walked independently so nothing nested only behind a
            # Name is missed, and nothing already inline is counted twice.
            for subexpr in (kw.value, *extra_subexprs):
                for inner in ast.walk(subexpr):
                    if isinstance(inner, ast.Call) and _numeric_strategy_func_name(
                        inner
                    ):
                        sites.extend(
                            _sites_from_strategy_call(
                                inner,
                                file=file,
                                given_parameter=kw.arg,
                                factory_function=None,
                            )
                        )

    # Tier 2: bounds inside the function's own body -- a strategy factory.
    # Unchanged from round 2 -- see module docstring's "What remains out of
    # scope" section.
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

    return sites, unresolved


def scan_module(
    path: Path, *, label: str, known_factory_names: frozenset[str] = frozenset()
) -> ScanResult:
    """Scan one ``.py`` file's top-level function definitions for bound sites.

    ``known_factory_names`` should be every module-level function name found
    across the *entire* ``tests/`` tree (see :func:`scan_tests_tree`), not
    just this file's own -- a strategy factory is typically defined in one
    file and called from another (``baseline_scores_strategy()``). Called
    with the default empty set, a zero-argument call to a factory defined
    in a different file will be reported as unresolved rather than
    recognised; that is a single-file convenience, not the entry point
    ``scan_tests_tree`` uses.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_assignments = _module_level_assignments(tree)
    hypothesis_given_names = _hypothesis_given_names(tree)
    sites: list[BoundSite] = []
    unresolved: list[UnresolvedGivenSite] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            found_sites, found_unresolved = _scan_function(
                node,
                file=label,
                module_assignments=module_assignments,
                known_factory_names=known_factory_names,
                hypothesis_given_names=hypothesis_given_names,
            )
            sites.extend(found_sites)
            unresolved.extend(found_unresolved)
    return ScanResult(sites=tuple(sites), unresolved=tuple(unresolved))


def scan_tests_tree(root: Path) -> ScanResult:
    """Scan every ``.py`` file under ``root`` (expected: the repo's ``tests/`` dir).

    ``label`` on each returned :class:`BoundSite`/:class:`UnresolvedGivenSite`
    is the path relative to ``root``'s parent (e.g.
    ``tests/unit/baseline/test_ewma_fitting.py``) -- stable, readable, and
    usable as a dotted module path with ``.py`` stripped and ``/`` replaced
    by ``.``.

    Two passes over the tree: the first only collects every module-level
    function name (Part A/B's ``known_factory_names``, needed because a
    strategy factory is typically defined in one file and called from
    another); the second does the real scan using that complete set.
    """
    paths = [
        path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts
    ]
    trees: dict[Path, ast.Module] = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in paths
    }
    known_factory_names = frozenset(
        name for tree in trees.values() for name in _top_level_function_names(tree)
    )

    sites: list[BoundSite] = []
    unresolved: list[UnresolvedGivenSite] = []
    for path in paths:
        label = str(path.relative_to(root.parent)).replace("\\", "/")
        tree = trees[path]
        module_assignments = _module_level_assignments(tree)
        hypothesis_given_names = _hypothesis_given_names(tree)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                found_sites, found_unresolved = _scan_function(
                    node,
                    file=label,
                    module_assignments=module_assignments,
                    known_factory_names=known_factory_names,
                    hypothesis_given_names=hypothesis_given_names,
                )
                sites.extend(found_sites)
                unresolved.extend(found_unresolved)
    return ScanResult(sites=tuple(sites), unresolved=tuple(unresolved))


def module_dotted_name(label: str) -> str:
    """Convert a scanned file's relative label to an importable dotted module name."""
    return label[: -len(".py")].replace("/", ".")
