"""Meta-test (BIN-124, round 2): parameter-dimension strategy bounds stay legal.

**Why this file exists, and why it is not a bigger version of
``test_baseline_scores_strategy_contract.py``.** Round 1 built a guard for
exactly one dimension -- the ``scores`` a baseline is built from -- and its
own docstring said, in writing, two days before it mattered: *"target_arl,
smoothing_param, reference_value and direction are held fixed ... those
parameters ... were never triplicated across files the way the scores
strategy was, so BIN-124's Part A scope -- and this meta-test's scope --
does not extend to them. A future rejection tied to one of those parameters
needs its own guard, not this one."*

ADR-011 then added exactly that: a new floor on ``target_arl``
(``MIN_TARGET_ARL = 100.0``, replacing the purely-arithmetic
``MIN_COHERENT_ARL = 1.0``). Eight files across this suite drew
``target_arl`` from a Hypothesis strategy bounded at the old floor. **None
of them broke**, because every one of them was updated in the same PR to
import ``MIN_TARGET_ARL`` rather than the old name -- but nothing *forced*
that; it happened because whoever wrote ADR-011's implementation had read
the docstring above. This file is what makes that no longer optional.

**Design chosen: paralleled, not generalised, against round 1's guard --
stated as a deliberate choice, not an oversight.** The two guards have
structurally different shapes, and forcing them into one mechanism would
paper over that rather than remove it:

* Round 1 (**scores**) is *generative*: draw many baselines via Hypothesis,
  ask the real ``fit_*`` entry points whether each one is accepted, and
  read a failure in either direction (a strategy that has drifted into
  illegal territory, or the library over-rejecting legal data -- the
  BIN-123 class). It needs Hypothesis because "a baseline the library
  should accept" is not something you can enumerate as a short list of
  boundary values -- the space of legal score lists is what is being
  explored.
* Round 2 (**parameters** -- this file) is *static*: every
  ``target_arl``/``reference_value``/``smoothing_param``/``threshold``
  bound in this suite is a single, already-known number (a named constant
  or a literal) sitting at one of two ends of a range. There is nothing to
  *generate* -- the fix the brief explicitly rules out is widening
  ``_CONTRACT_TARGET_ARL`` (round 1's own fixed value) into a strategy,
  which would only make the guard's own draws subject to the identical
  drift it exists to catch. What this dimension actually needs is the
  **inverse** of round 1's shape: enumerate the bounds the suite *already
  uses* and ask whether the library still accepts *them*, today, as
  literal boundary probes -- no Hypothesis, no random search, no `max_examples`
  budget.

Sharing one file across two different assertion shapes (draw-and-ask vs.
enumerate-and-probe) would have produced exactly the kind of inconsistency
``CLAUDE.md`` already lists nine instances of. Paralleling instead --
same directory, same ``*_strategy_contract.py`` naming, cross-referenced
docstrings, same completeness-registry pattern as
``tests/support/exception_contract_registry.py`` -- keeps each guard doing
one clean job while making the sibling relationship between them obvious to
whoever reads either one next.

**The completeness problem, and the honest answer to it.** A hand-curated
list of "the parameters we know are library-validated" has the identical
weakness round 1's own docstring already named: it catches today's known
bounds and silently misses tomorrow's ninth file. There is no equivalent of
``BIN-121``'s ``drift_caliper.__all__`` enumeration here -- nothing in ``src/``
lists "every Hypothesis strategy bound in the test suite". What **is**
mechanically enumerable is the test suite's own source text:
``tests/support/hypothesis_bound_scan.py`` AST-walks every ``.py`` file
under ``tests/`` and returns every ``min_value=``/``max_value=`` keyword
passed to a numeric Hypothesis strategy, with no need to already know a
file exists. ``tests/support/parameter_bound_registry.py`` then classifies
every distinct name the scanner can attach to a site -- a ``@given(...)``
keyword, or a strategy-factory function name -- as either
:class:`~tests.support.parameter_bound_registry.GovernedParameter` (feeds a
library-validated parameter; carries a probe) or
:class:`~tests.support.parameter_bound_registry.ExcludedParameter` (a
simulation/geometry knob; carries a stated reason). This file's
``test_every_bound_site_is_classified`` asserts every site the scanner
found is one or the other -- so a new file, or an existing file's new
``@given`` parameter, cannot silently go unclassified: the completeness
test fails, by name, at the exact site, until a human decision is recorded
in the registry.

**This is a real distinction, not a rhetorical one, and it is worth being
precise about which half is mechanical and which half is judgement:**
finding *that* a bound exists is now automatic; deciding *what it means* is
not, and this file does not claim otherwise.

**Not everything with ``min_value=``/``max_value=`` qualifies, and here is
the line drawn.** ``scale``, ``shift`` (both ARL-simulated-property files'
affine-invariance tests) and ``arl_gap``/``count`` are bounds on
*simulation or fixture-construction* inputs -- they are never themselves
passed to a keyword argument any ``fit_*``/``check_sufficiency`` call
validates. ``arl_gap`` is added to ``arl_low`` to derive a second
``target_arl`` for a monotonicity comparison, but the sum's legality is
already guaranteed by ``arl_low``'s own floor; ``scale``/``shift`` multiply
and offset raw scores before any chart sees them; ``count`` picks how many
observations a fixture baseline holds, never a validated keyword itself.
Each is registered in ``EXCLUDED_GIVEN_PARAMETERS`` with that reasoning
stated, not silently swept in -- see
``tests/support/parameter_bound_registry.py``.

**What this guard cannot catch, stated rather than left implicit.**

* **Only ``target_arl``, ``arl_low`` (which is a ``target_arl`` under a
  different local name), ``smoothing_param``, ``reference_value`` and
  ``threshold``.** Nothing about ``direction`` (a string enum, not a
  numeric bound) or any future validated parameter is covered until it is
  both discovered by the scanner *and* classified in the registry --
  discovery is automatic; classification is not, by design (see above).
* **A bound expression the scanner cannot resolve to a plain numeric
  literal or a module-level name** is reported as an explicit resolution
  failure (see ``_resolve_bound_value`` below), not silently skipped --
  but every real site in this suite today is one of those two forms, so
  this path is unexercised in practice, not proven robust against a
  more exotic expression.
* **A probe only asserts the library *accepts* the exact value used as a
  bound today.** It says nothing about whether the library *should*
  reject some other value nearby (that is round 1's BIN-123-direction
  concern, over-rejection, and is a different guard's job) -- this file is
  specifically about under-rejection drift, the ADR-011 pattern: a
  strategy quietly generating inputs the library has started refusing.
* **Not an exception-contract audit** (``BIN-121``'s job) and **not a
  Hypothesis-scale property test** -- these are deterministic boundary
  probes, one call per discovered bound, not a generative search.

**Round 3 (BIN-124, 2026-09-12).** A reopening comment found a bound this
file's completeness check had no way to see: a ``@given`` keyword whose
value is a bare module-level constant (``_SHARED = st.floats(...)``) rather
than an inline call. ``hypothesis_bound_scan.py`` now resolves that case
(Part A) and reports, as an explicit named failure rather than a silent
zero-site result, any ``@given`` keyword it still cannot resolve -- a helper
function call, an import from elsewhere, a ``.map()``/``.filter()`` chain
(Part B). ``test_no_given_argument_is_left_unresolved`` below is Part B's
half of the guard; everything above this note is unchanged from round 2 and
now also benefits from Part A's resolution before reaching the same
classification and probing logic. See ``hypothesis_bound_scan.py``'s own
module docstring for the full design and its stated remaining scope
boundaries.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from _pytest.outcomes import Failed

from drift_caliper.errors import CaliperError
from tests.support.hypothesis_bound_scan import (
    BoundSite,
    UnresolvedGivenSite,
    module_dotted_name,
    scan_tests_tree,
)
from tests.support.parameter_bound_registry import (
    EXCLUDED_FACTORY_FUNCTIONS,
    EXCLUDED_GIVEN_PARAMETERS,
    GOVERNED_GIVEN_PARAMETERS,
    governed_probe_for,
)

# tests/unit/baseline/test_parameter_strategy_contract.py -> tests/
_TESTS_ROOT = Path(__file__).resolve().parents[2]
assert _TESTS_ROOT.name == "tests", f"unexpected root resolved: {_TESTS_ROOT}"

# Scanned once at collection time so every test below parametrizes over the
# identical, already-computed site list -- re-scanning per test would just
# repeat the same AST walk for no benefit.
_SCAN_RESULT = scan_tests_tree(_TESTS_ROOT)
_ALL_SITES: tuple[BoundSite, ...] = _SCAN_RESULT.sites
_UNRESOLVED_SITES: tuple[UnresolvedGivenSite, ...] = _SCAN_RESULT.unresolved

_GOVERNED_GIVEN_NAMES = frozenset(p.name for p in GOVERNED_GIVEN_PARAMETERS)
_EXCLUDED_GIVEN_NAMES = frozenset(p.name for p in EXCLUDED_GIVEN_PARAMETERS)
_EXCLUDED_FACTORY_NAMES = frozenset(p.name for p in EXCLUDED_FACTORY_FUNCTIONS)

_GOVERNED_SITES = tuple(
    site
    for site in _ALL_SITES
    if site.given_parameter is not None
    and site.given_parameter in _GOVERNED_GIVEN_NAMES
)


# Resolved by name in test_resolve_bound_value_handles_both_supported_forms.
_MODULE_LEVEL_PROBE_VALUE = 123.0


def _site_id(site: BoundSite) -> str:
    parameter = site.given_parameter or f"factory:{site.factory_function}"
    return f"{site.file}:{site.lineno}:{parameter}:{site.bound_kind}"


def test_resolve_bound_value_reports_an_unresolvable_expression() -> None:
    """The resolution-failure branch fires, rather than merely being described.

    ``_resolve_bound_value`` deliberately supports only a numeric literal
    or a bare module-level name, and reports anything else instead of
    ``eval``-ing test source. **No real site in this suite has that shape**,
    so without this test that branch would be engineering nobody has ever
    seen run -- the "documented-but-not-executing verification" pattern this
    project has now named three times (``fail_under`` with no ``--cov``,
    ``mutmut`` on a 2.x schema, BIN-66's uncollected scenarios).

    Raised by ``code-reviewer`` on BIN-124: an unexercised error path is a
    claim, not a guard.
    """
    unresolvable = BoundSite(
        file="tests/unit/baseline/test_parameter_strategy_contract.py",
        lineno=1,
        bound_kind="min_value",
        bound_source="MIN_TARGET_ARL * 2",  # an expression, not a bare name
        given_parameter="target_arl",
        factory_function=None,
    )
    with pytest.raises(Failed, match="cannot resolve bound expression"):
        _resolve_bound_value(unresolvable)


def test_resolve_bound_value_handles_both_supported_forms() -> None:
    """The two shapes it *does* support, pinned alongside the one it rejects."""
    literal = BoundSite(
        file="tests/unit/baseline/test_parameter_strategy_contract.py",
        lineno=1,
        bound_kind="min_value",
        bound_source="30",
        given_parameter="threshold",
        factory_function=None,
    )
    assert _resolve_bound_value(literal) == 30.0

    named = BoundSite(
        file="tests/unit/baseline/test_parameter_strategy_contract.py",
        lineno=1,
        bound_kind="min_value",
        bound_source="_MODULE_LEVEL_PROBE_VALUE",
        given_parameter="target_arl",
        factory_function=None,
    )
    assert _resolve_bound_value(named) == _MODULE_LEVEL_PROBE_VALUE


def _resolve_bound_value(site: BoundSite) -> float:
    """Resolve a bound site's source expression to today's actual numeric value.

    Only a bare identifier (``MIN_TARGET_ARL``) or a numeric literal
    (``30``, ``-50.0``) is supported -- every real site in this suite is
    one of the two (checked directly while writing this guard, see the
    module docstring). A more general expression is a deliberate,
    reported resolution failure rather than an ``eval`` over test source
    -- that safety trade has not been needed yet and is not taken
    speculatively.
    """
    module = importlib.import_module(module_dotted_name(site.file))
    source = site.bound_source
    try:
        return float(ast.literal_eval(source))
    except (ValueError, SyntaxError):
        pass
    if source.isidentifier() and hasattr(module, source):
        return float(getattr(module, source))
    pytest.fail(
        f"{site.file}:{site.lineno} -- cannot resolve bound expression "
        f"{source!r} to a plain numeric literal or a module-level name in "
        f"{module.__name__!r}. This guard only resolves those two forms "
        "(see this file's module docstring, 'What this guard cannot "
        "catch') -- extend _resolve_bound_value deliberately if a new "
        "site genuinely needs a general expression."
    )
    raise AssertionError("unreachable")  # pytest.fail always raises


def test_scanner_found_the_expected_dimensions() -> None:
    """Sanity check on the scanner itself, not on any classification.

    If this starts failing because the count drops to zero, the AST walk
    itself has broken (a path or package-layout change) -- every other
    test in this file would otherwise pass vacuously over an empty list,
    which is a worse failure mode than a loud one here.
    """
    assert len(_ALL_SITES) >= 15
    found_given_parameters = {
        s.given_parameter for s in _ALL_SITES if s.given_parameter
    }
    # The five names this ticket's reopening comment named explicitly, plus
    # arl_low (target_arl's local name in the monotonicity properties) --
    # confirms the scanner is actually walking the eight files, not an
    # empty or wrong directory.
    expected = {
        "target_arl",
        "arl_low",
        "reference_value",
        "threshold",
        "smoothing_param",
    }
    assert expected <= found_given_parameters


def _unresolved_id(site: UnresolvedGivenSite) -> str:
    return f"{site.file}:{site.lineno}:{site.given_parameter}"


def test_no_given_argument_is_left_unresolved() -> None:
    """Part B (BIN-124 round 3): every ``@given`` keyword resolves to a
    strategy this scanner can walk for bounds, or the suite fails by name.

    Deliberately a single assertion over the whole list, not a
    parametrization over ``_UNRESOLVED_SITES`` -- ``pytest.mark.parametrize``
    over an empty list collects zero test items, which would make this
    check invisible (collected as nothing, indistinguishable from "not
    written") on every green run rather than a check that actively passed.
    See ``test_scanner_found_the_expected_dimensions`` immediately above for
    the identical reasoning applied to the sites list itself.

    A ``@given`` argument reaches ``_UNRESOLVED_SITES`` when
    ``tests/support/hypothesis_bound_scan.py`` could not resolve it to an
    inline strategy call or a same-file module-level name (Part A) --
    built by a helper function, imported from another module, chained via
    ``.map()``/``.filter()``, or otherwise composed. See that module's
    docstring, "Part B", for the full reasoning.
    """
    assert not _UNRESOLVED_SITES, "\n".join(
        [
            f"{len(_UNRESOLVED_SITES)} @given argument(s) could not be resolved "
            "to a strategy this scanner can verify -- rewrite each into an "
            "inline `st.floats(...)`/`st.integers(...)`/`st.decimals(...)` "
            "call (optionally behind a module-level constant referenced by "
            "name), or a zero-argument call to a strategy-factory function "
            "defined at module level under tests/:",
            *(
                f"  {_unresolved_id(site)} -- {site.detail}"
                for site in _UNRESOLVED_SITES
            ),
        ]
    )


@pytest.mark.parametrize("site", _ALL_SITES, ids=[_site_id(s) for s in _ALL_SITES])
def test_every_bound_site_is_classified(site: BoundSite) -> None:
    """Every bound the scanner finds is registered as GOVERNED or EXCLUDED.

    See ``tests/support/parameter_bound_registry.py``. This is the
    completeness half of the guard: it does not know whether a newly
    discovered bound is dangerous, only that a decision about it has not
    yet been recorded -- and it fails, loudly and by name, until one is.
    """
    if site.given_parameter is not None:
        assert (
            site.given_parameter in _GOVERNED_GIVEN_NAMES
            or site.given_parameter in _EXCLUDED_GIVEN_NAMES
        ), (
            f"{site.file}:{site.lineno} -- @given parameter "
            f"{site.given_parameter!r} is classified in neither "
            "GOVERNED_GIVEN_PARAMETERS nor EXCLUDED_GIVEN_PARAMETERS in "
            "tests/support/parameter_bound_registry.py. A new Hypothesis "
            "strategy bound was added without a classification decision -- "
            "add one there (with a probe if it feeds a library-validated "
            "parameter, or a reason if it does not) before this can pass."
        )
    else:
        assert site.factory_function is not None  # exactly one is ever set
        assert site.factory_function in _EXCLUDED_FACTORY_NAMES, (
            f"{site.file}:{site.lineno} -- strategy-factory function "
            f"{site.factory_function!r} is not classified in "
            "EXCLUDED_FACTORY_FUNCTIONS (nor any governed-factory registry) "
            "in tests/support/parameter_bound_registry.py. A new strategy "
            "factory was added without a classification decision."
        )


@pytest.mark.parametrize(
    "site", _GOVERNED_SITES, ids=[_site_id(s) for s in _GOVERNED_SITES]
)
def test_every_governed_bound_is_accepted_by_the_library_today(site: BoundSite) -> None:
    """The exact numeric bound used at this site is legal today, per the live library.

    This is the direction round 1's own docstring predicted and named
    before it happened: a ``src/`` rejection narrows a parameter's legal
    range, and a Hypothesis strategy already bounded at the old range
    becomes a generator of illegal inputs. Resolving the bound's *current*
    value from the file it actually lives in (rather than re-deriving an
    expected value here) is what lets this test fail the moment a bound
    stops matching what the library enforces, without this file needing to
    duplicate ADR-011's constants.
    """
    assert site.given_parameter is not None  # only classified-governed sites reach here
    value = _resolve_bound_value(site)
    probe = governed_probe_for(site.given_parameter)
    try:
        probe(value)
    except CaliperError as exc:
        pytest.fail(
            f"{site.file}:{site.lineno} -- @given parameter "
            f"{site.given_parameter!r}'s {site.bound_kind}={site.bound_source!r} "
            f"(resolves today to {value!r}) is REJECTED by the library: "
            f"{type(exc).__name__}(category={exc.category!r}, "
            f"context={dict(exc.context)!r}).\n"
            "A src/ rejection has narrowed the legal range for this "
            "parameter and this strategy bound was not updated to match -- "
            "the exact BIN-124 pattern. Update the bound at the file/line "
            "named above to the current legal floor/ceiling (see "
            "tests/support/parameter_bound_registry.py's probe/note for "
            "which constant governs it)."
        )
