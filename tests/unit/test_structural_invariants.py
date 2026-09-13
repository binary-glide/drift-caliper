"""Project invariants enforced structurally rather than by attention (BIN-128).

**Every recurring defect on this project has one shape: a rule written in
``CLAUDE.md`` or an ADR, enforced only by attention, re-violated at the
next site that needs it.** `BIN-118` landed in PR #45; its own review found
the same hazard eight lines away in the same file, hours later, and
`BIN-121`'s audit then found three more sites. That is not carelessness --
it is what happens when a rule has no mechanical representation.

**Mechanism, decided by measurement rather than preference.** `BIN-128`
left the choice open between ripgrep, an AST test, and semgrep. Auditing
the tree settled it:

===========================  ==============  =======================
rule                         real code hits  comment/docstring hits
===========================  ==============  =======================
``statistics.fmean``                      0                       8
bare ``hasattr``                          0                       2
``assert``                                0                       1
beartype decorator                        0                      10
===========================  ==============  =======================

🚨 **A literal text rule would have false-positived on nearly every one**,
because this codebase's comments discuss precisely the things the rules
forbid -- they exist to explain *why* the forbidden thing is avoided. A
rule that fires spuriously gets suppressed and then ignored, so text
matching is disqualified wherever the language can be parsed instead.

**semgrep was rejected**: `ast` is stdlib, runs inside the existing gate,
adds no dependency, no config, no CI job and no suppression mechanism to
teach people to reach for. The cost semgrep would buy back -- more
readable rule syntax -- is small at five rules.

⚠️ **These do NOT replace behavioural tests, and must not grow to try.**
`BIN-121`'s exception-contract audit catches a leak *whatever its
syntactic form*; a structural rule catches only the spellings someone
anticipated. **Where both apply the behavioural test is strictly
stronger.** These cover what tests cannot see -- *"this call site exists"*
rather than *"this behaviour is wrong"*.

Each rule below names the ticket whose violation motivated it, and each
was demonstrated to fire by reintroducing that violation before merge.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SRC = _REPO / "src" / "caliper"


def _source_files() -> list[pathlib.Path]:
    return sorted(_SRC.rglob("*.py"))


def _locate(path: pathlib.Path, node: ast.AST) -> str:
    return f"{path.relative_to(_SRC.parent)}:{getattr(node, 'lineno', '?')}"


# ---------------------------------------------------------------------------
# Rule 1 -- no `assert` in shipped code (BIN-120)
# ---------------------------------------------------------------------------


def test_no_assert_statements_in_shipped_code() -> None:
    """``assert`` must not appear in ``src/`` (BIN-120).

    Two independent reasons, either sufficient:

    * ``AssertionError`` is **not** a ``CaliperError`` -- no ``category``,
      no ``context`` to branch on. `BIN-120` was exactly this: a structural
      ``FittedControlLimits`` was accepted by ``Monitor`` and then raised
      ``AssertionError`` from ``record()``.
    * ``python -O`` strips assertions entirely, so an invariant guarded
      only by ``assert`` silently stops being guarded in any consumer who
      runs optimised.

    An internal invariant that must not be reachable should ``raise`` a
    real exception -- the three ``fit_*`` functions raise ``RuntimeError``
    for exactly that case.
    """
    offenders = [
        _locate(path, node)
        for path in _source_files()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assert)
    ]

    assert not offenders, (
        "assert statements in shipped code:\n  "
        + "\n  ".join(offenders)
        + "\nRaise a CaliperError, or a RuntimeError for a genuine internal "
        "invariant. AssertionError carries no category or context, and -O "
        "removes it (BIN-120)."
    )


# ---------------------------------------------------------------------------
# Rule 2 -- no bare `hasattr` on caller-supplied objects (BIN-118, BIN-127)
# ---------------------------------------------------------------------------


def test_no_bare_hasattr_calls_in_shipped_code() -> None:
    """``hasattr`` must not be called in ``src/`` (BIN-118, BIN-127).

    🚨 ``hasattr`` **swallows only** ``AttributeError``. Since Python 3.2 any
    other exception from a property or ``__getattr__`` propagates -- so a
    duck-typing check written as ``hasattr(candidate, name)`` lets a
    hostile or merely broken object raise straight through a public entry
    point as a non-``CaliperError``.

    `BIN-118` found the first instance; `BIN-121`'s audit found three more
    at ``Baseline.record()``, ``Monitor.record()`` and
    ``compare_provenance()``. The replacement is
    ``attribute_probe.probe_attribute``/``probe_fields``, which catch every
    exception and report the failure as a typed error.
    """
    offenders = [
        _locate(path, node)
        for path in _source_files()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "hasattr"
    ]

    assert not offenders, (
        "bare hasattr() calls in shipped code:\n  "
        + "\n  ".join(offenders)
        + "\nUse attribute_probe.probe_attribute/probe_fields -- hasattr "
        "swallows only AttributeError, so anything else a property raises "
        "escapes as a non-CaliperError (BIN-118, BIN-127)."
    )


# ---------------------------------------------------------------------------
# Rule 3 -- no `statistics` mean helpers (BIN-123)
# ---------------------------------------------------------------------------


def test_no_statistics_mean_calls_in_shipped_code() -> None:
    """``statistics.fmean``/``mean`` must not be called in ``src/`` (BIN-123).

    ``statistics.fmean`` delegates to ``math.fsum``, which raises
    ``OverflowError`` on an intermediate overflow **even when the mean
    itself is representable** -- a baseline of alternating ``±1e308`` is
    the case `BIN-119` hit. ``spc_numerics._overflow_safe_mean`` tries the
    ordinary path and falls back to exact power-of-two scaling.

    ⚠️ Four call sites already delegate correctly; nothing stopped a fifth
    from reaching for ``statistics`` directly, which is why this is a rule
    rather than a convention.
    """
    offenders = []
    for path in _source_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"fmean", "mean"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "statistics"
            ):
                offenders.append(_locate(path, node))

    assert not offenders, (
        "statistics.fmean/mean calls in shipped code:\n  "
        + "\n  ".join(offenders)
        + "\nUse spc_numerics._overflow_safe_mean -- math.fsum raises "
        "OverflowError on an intermediate overflow even when the mean is "
        "representable (BIN-119, BIN-123)."
    )


# ---------------------------------------------------------------------------
# Rule 4 -- no agent-provenance markers (ratified 2026-09-10)
# ---------------------------------------------------------------------------

# Matches `added by <hyphenated-agent-name>` rather than enumerating
# agents. `code-reviewer` pointed out the closed list held five entries
# while the pipeline defines thirteen-plus code-writing agents -- none
# applicable to Caliper today, which is exactly how a list goes stale
# unnoticed. Requiring a hyphenated name is what keeps this from matching
# ordinary prose such as "raised by the product owner".
_PROVENANCE_MARKER = re.compile(
    r"\b(?:added|updated|written|generated)\s+by\s+[a-z]+(?:-[a-z]+)+",
    re.IGNORECASE,
)


def test_no_agent_provenance_markers_in_comments() -> None:
    """No ``# added by <agent> BIN-n`` markers anywhere (ratified 2026-09-10).

    ⚠️ **This one genuinely needs token scanning**, unlike the rules above:
    its subject *is* a comment, which `ast` discards. Scanning tokens
    rather than raw text still avoids matching the word inside a string
    literal or docstring.

    🚨 **The rule exists because an agent's own specification tells it to
    add these.** ``domain-implementer``'s Idempotency section instructs
    exactly that marker, and `CLAUDE.md` countermands it for this project --
    so the violation arrives with every run, from a source that believes
    it is doing the right thing. That is the strongest possible case for
    mechanical enforcement over attention.

    ``git blame`` already records authorship, more accurately and at no
    cost, and these files ship to PyPI -- pipeline bookkeeping published to
    every consumer.
    """
    offenders = []
    # ⚠️ Wider than the other rules, deliberately: the ratified wording is
    # "no agent-provenance markers in source **or tests**", and an agent
    # writing tests is as likely to add one as an agent writing src/.
    # Scanning COMMENT tokens rather than raw text is what keeps this
    # module's own docstrings -- which quote the forbidden marker in order
    # to describe it -- from matching themselves.
    for path in sorted(_SRC.parent.rglob("*.py")) + sorted(
        (_REPO / "tests").rglob("*.py")
    ):
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            if _PROVENANCE_MARKER.search(token.string):
                offenders.append(
                    f"{path.name}:{token.start[0]}  {token.string.strip()}"
                )

    assert not offenders, (
        "agent-provenance markers found:\n  "
        + "\n  ".join(offenders)
        + "\nStrip them. git blame records authorship already, and these "
        "files ship to PyPI (ratified 2026-09-10)."
    )


# ---------------------------------------------------------------------------
# Rule 5 -- every `# pragma: no cover` carries a justification (BIN-117)
# ---------------------------------------------------------------------------


def test_every_no_cover_pragma_is_justified() -> None:
    """Each ``# pragma: no cover`` has an explanatory comment beside it (BIN-117).

    Excluding a branch from coverage is a claim that it cannot be reached.
    `BIN-117` found one that was **live** while marked unreachable, so the
    claim needs to be written where a reviewer will see it.

    ⚠️ **This checks a reason was written, NOT that the reason is true** --
    and `BIN-117`'s own pragma *had* a comment, which was wrong. The same
    honest ceiling as `BIN-136`'s word-count floor: it makes the empty
    gesture inconvenient, and judging the claim stays a human job. Read a
    green run as "someone wrote a justification", never as "the branch is
    unreachable".
    """
    offenders = []
    for path in _source_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "pragma: no cover" not in line:
                continue
            # A justification may sit on either side: the three fit_*
            # functions put it on the lines below, monitor.py:394 puts it
            # above the `raise` it guards. Both read naturally; requiring
            # one direction would have made this rule fire on correct code,
            # which is how a rule earns a suppression and then gets ignored.
            #
            # ⚠️ **Immediately adjacent only.** A first draft allowed three
            # lines either way, and `code-reviewer` demonstrated by
            # injection that an unrelated comment in that window -- a
            # section divider, say -- satisfied the rule without being a
            # justification. All five current pragmas put their reason
            # directly against the line, so the tighter window costs
            # nothing and removes the loophole.
            adjacent = lines[max(0, index - 1) : index] + lines[index + 1 : index + 2]
            neighbours = [c.strip() for c in adjacent if c.strip()]
            has_reason = any(candidate.startswith("#") for candidate in neighbours)
            if not has_reason:
                offenders.append(
                    f"{path.relative_to(_SRC.parent)}:{index + 1}  {line.strip()}"
                )

    assert not offenders, (
        "`# pragma: no cover` without an adjacent justification:\n  "
        + "\n  ".join(offenders)
        + "\nState why the branch is unreachable, on the following line. "
        "BIN-117 found a live branch marked unreachable."
    )


# ---------------------------------------------------------------------------
# Vacuity guard
# ---------------------------------------------------------------------------


def test_the_scan_reaches_the_source_tree() -> None:
    """The rules above scan a populated tree, so a green run means something.

    🚨 **Without this, a wrong ``_SRC`` path would make all five rules pass
    forever** -- the vacuity shape this project has hit repeatedly, and
    exactly what an ``rglob`` typo produces. The floor is deliberately far
    below the real count so ordinary refactoring cannot trip it.
    """
    files = _source_files()

    assert len(files) > 20, (
        f"only {len(files)} source files found under {_SRC} -- the scan is "
        "looking in the wrong place, which would make every rule above pass "
        "vacuously"
    )
