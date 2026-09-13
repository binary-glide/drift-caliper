"""BIN-121 (part 3) -- hostile objects at the boundary.

Tests that Caliper handles caller-supplied objects whose dunder methods
(``__eq__``, ``__ne__``, ``__repr__``, ``__str__``) raise or return
unexpected types, wherever Caliper calls ``repr``/``str``/``format`` on,
or compares, a caller-supplied value.

Two confirmed defects (reproduced against trunk ``be88f7c``):

**Defect A** -- ``compare_provenance`` leaks a non-``CaliperError``.
``probe_attribute`` (BIN-127) guards attribute *access* on a duck-typed
artefact but not what the attribute *returns*. ``build_mismatches`` then
evaluates ``expected != received`` on that value
(``provenance_comparison.py:50,55``), so a raising ``__eq__``/``__ne__``
escapes as a raw ``RuntimeError``.

**Defect B** -- the declared ``context["mismatches"]`` type contract
(``dict[str, dict[str, str]]``) is silently violated. An object that
compares unequal but is not a ``str`` lands in the mapping.
``mypy --strict`` cannot catch it: the function parameters are declared
``str`` and the probe value arrives as ``Any``.

**Audit results for other surfaces** (verified independently, not
merely assumed):

* ``monitor.py``'s ``_safe_repr`` / ``_describe_receiver`` /
  ``_describe_exception`` (BIN-118) -- already guarded. Confirmed safe
  below through the public ``Monitor.record()`` surface.
* ``CaliperError.__init__`` -- stores ``context`` unformatted;
  ``repr(error)`` / ``str(error)`` only format the message string
  (always a literal ``str``). Confirmed safe below.
* ``log_receiver`` -- only reachable through ``Monitor._deliver`` with
  validated Pydantic ``MonitoringResult`` data. Safe by construction.
* ``attribute_probe.py`` -- never formats caller-supplied values;
  ``type(exc).__name__`` is a class-attribute read. Safe.
* ``Baseline.record()`` -- calls ``build_mismatches`` on Caliper's own
  ``Provenance`` values (always ``str``). NOT affected.

Tests for defects A and B are expected to FAIL against current ``src/``.
Confirmation tests for already-guarded surfaces are expected to PASS.
Both categories serve as regression guards once the fixes land.
"""

from __future__ import annotations

import pytest

from caliper.baseline import compare_provenance
from caliper.errors import CaliperError, InvalidParameterError
from caliper.measurement import ModelVersion, Provenance, ScoringCriteria, ScoringResult

_MODEL_VERSION = "claude-sonnet-4-5-20250929"
_CRITERIA = "Evaluate the response for factual accuracy and helpfulness."


def _result(
    *,
    model_version: str = _MODEL_VERSION,
    criteria: str = _CRITERIA,
) -> ScoringResult:
    """Build a ``ScoringResult`` with known, literal provenance."""
    return ScoringResult(
        score=0.9,
        reasoning="Accurate and concise.",
        provenance=Provenance(
            model_version=ModelVersion(value=model_version),
            scoring_criteria=ScoringCriteria(value=criteria),
        ),
    )


# ---------------------------------------------------------------------------
# Hostile value fixtures
#
# Each is a non-str object that misbehaves in a specific way when
# compared or formatted. Deliberately minimal -- no extra attributes
# beyond what is needed to trigger the specific code path under test.
# ---------------------------------------------------------------------------


class _RaisingNeValue:
    """An object whose ``__ne__`` raises, exercising Defect A."""

    def __ne__(self, other: object) -> bool:
        raise RuntimeError("__ne__ exploded")

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("__eq__ exploded")


class _RaisingEqOnlyValue:
    """An object whose ``__eq__`` raises (no ``__ne__`` override).

    Python 3's default ``__ne__`` is ``not self.__eq__(other)``, so
    ``!=`` routes through ``__eq__`` and the raise propagates identically
    to an explicit ``__ne__`` raise. A separate fixture because the call
    path is different: the ``__ne__`` route is direct; this route goes
    through object's ``__ne__`` → ``__eq__`` → raise.
    """

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("__eq__ exploded")

    def __hash__(self) -> int:
        return id(self)


class _NonStrAlwaysUnequal:
    """A non-str object that compares unequal to everything without raising.

    Exercises Defect B: passes through ``build_mismatches``'s ``!=``
    comparison (returns ``True``), then lands in
    ``context["mismatches"]`` as a non-``str`` value, violating the
    ``dict[str, dict[str, str]]`` type contract.
    """

    def __ne__(self, other: object) -> bool:
        return True

    def __eq__(self, other: object) -> bool:
        return False

    def __repr__(self) -> str:
        return "<NonStrAlwaysUnequal>"

    def __hash__(self) -> int:
        return id(self)


# ---------------------------------------------------------------------------
# Hostile artefact fixtures
#
# Each satisfies FittedControlLimits structurally enough for
# probe_attribute to succeed on the provenance fields -- the defects
# live one step past that guard, in build_mismatches.
# ---------------------------------------------------------------------------


class _HostileNeModelVersionArtefact:
    """``provenance_model_version`` is an object whose ``__ne__`` raises."""

    provenance_model_version = _RaisingNeValue()
    provenance_criteria = _CRITERIA


class _HostileEqOnlyModelVersionArtefact:
    """``provenance_model_version`` is an object whose ``__eq__`` raises."""

    provenance_model_version = _RaisingEqOnlyValue()
    provenance_criteria = _CRITERIA


class _HostileNeCriteriaArtefact:
    """``provenance_criteria`` is an object whose ``__ne__`` raises."""

    provenance_model_version = _MODEL_VERSION
    provenance_criteria = _RaisingNeValue()


class _NonStrModelVersionArtefact:
    """``provenance_model_version`` is a non-``str`` that compares unequal."""

    provenance_model_version = _NonStrAlwaysUnequal()
    provenance_criteria = _CRITERIA


class _BothNonStrArtefact:
    """Both provenance attributes are non-``str`` objects."""

    provenance_model_version = _NonStrAlwaysUnequal()
    provenance_criteria = _NonStrAlwaysUnequal()


# ===================================================================
# Defect A -- hostile comparison escapes as non-CaliperError
#
# compare_provenance → build_mismatches → (expected != received) → LEAK
#
# Each test below failed against pre-fix src/: a RuntimeError (or
# equivalent) escaped where a CaliperError is required. They pass now --
# verified two-way by disabling the guard, at which point all six fail.
# ===================================================================


def test_raises_caliper_error_when_model_version_ne_raises() -> None:
    """Defect A: ``provenance_model_version.__ne__`` raises RuntimeError.

    ``probe_attribute`` (BIN-127) returns the value successfully --
    attribute access did not raise. But ``build_mismatches`` then
    evaluates ``expected != received``, and the raising ``__ne__``
    propagates as a raw ``RuntimeError``.

    Expected after fix: ``InvalidParameterError`` rejecting the
    non-``str`` provenance value at the boundary, before comparison.
    """
    result = _result()
    artefact = _HostileNeModelVersionArtefact()

    with pytest.raises(Exception) as exc_info:
        compare_provenance(result, artefact)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    assert isinstance(exc_info.value, CaliperError), (
        f"compare_provenance raised {type(exc_info.value).__name__}, "
        f"not CaliperError -- Defect A (BIN-121): hostile __ne__ escapes "
        f"through build_mismatches"
    )


def test_raises_caliper_error_when_model_version_eq_raises() -> None:
    """Defect A variant: ``__eq__`` raises via Python 3's default
    ``__ne__`` delegation.

    When ``__ne__`` is not overridden, ``object.__ne__`` calls
    ``self.__eq__(other)`` and negates. A raising ``__eq__`` escapes
    the same way as a raising ``__ne__``.
    """
    result = _result()
    artefact = _HostileEqOnlyModelVersionArtefact()

    with pytest.raises(Exception) as exc_info:
        compare_provenance(result, artefact)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    assert isinstance(exc_info.value, CaliperError), (
        f"compare_provenance raised {type(exc_info.value).__name__}, "
        f"not CaliperError -- Defect A via __eq__ delegation"
    )


def test_raises_caliper_error_when_criteria_ne_raises() -> None:
    """Defect A on the criteria dimension.

    The same ``build_mismatches`` comparison runs on both
    ``provenance_model_version`` and ``provenance_criteria``
    (``provenance_comparison.py:50,55``). A hostile ``__ne__`` on
    criteria escapes identically.
    """
    result = _result()
    artefact = _HostileNeCriteriaArtefact()

    with pytest.raises(Exception) as exc_info:
        compare_provenance(result, artefact)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    assert isinstance(exc_info.value, CaliperError), (
        f"compare_provenance raised {type(exc_info.value).__name__}, "
        f"not CaliperError -- Defect A on criteria dimension"
    )


# ===================================================================
# Defect B -- non-str value violates context["mismatches"] contract
#
# compare_provenance → build_mismatches → stores non-str in dict
#
# Each test below failed against pre-fix src/, where the non-str reached
# build_mismatches and landed in the mapping. They pass now, and assert
# the rejection rather than the mapping -- see the helper's docstring for
# why that change was forced and what it cost.
# ===================================================================


def _assert_rejected_as_invalid_artefact(artefact: object) -> InvalidParameterError:
    """``compare_provenance`` must reject a non-``str`` provenance value.

    ⚠️ **This replaced a weaker form, and the reason matters more than the
    tests.** As written for the red phase these three asserted *"if a*
    ``ProvenanceMismatchError`` *is raised, every value in* ``mismatches``
    *is a* ``str``*"*. That was right against the unfixed library, which
    did raise one. The fix rejects the artefact **before**
    ``build_mismatches`` runs, so no ``ProvenanceMismatchError`` is raised
    -- the guard went false, the inner assertions stopped executing, and
    all three passed while asserting nothing beyond "some ``CaliperError``
    occurred". **A test whose precondition the fix made unreachable is
    vacuous, not green.**

    The same shape was caught in this ticket's part 1 (see
    ``test_extreme_value_fitting.py``'s measured fit/reject split), which
    is why it was looked for here.

    So these now pin the behaviour that actually exists. The
    ``dict[str, dict[str, str]]`` contract for *genuine* mismatches is not
    orphaned by the change -- ``test_compare_provenance.py`` (lines 218-290)
    asserts exact dict equality against ``str`` literals on every
    legitimate mismatch path, which pins the value types outright.
    """
    result = _result()

    with pytest.raises(InvalidParameterError) as exc_info:
        compare_provenance(result, artefact)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    error = exc_info.value
    assert error.context["kind"] == "invalid", (
        "a non-str provenance value is a malformed artefact, not a missing "
        "one -- ADR-002 keeps `kind` a closed discriminator"
    )
    assert error.context["parameter"] == "artefact", (
        "the rejection must name the parameter the caller passed, not the "
        "internal probe -- `errors are UX` (CLAUDE.md)"
    )
    return error


def _assert_offending_fields(error: InvalidParameterError, *expected: str) -> None:
    """Assert exactly which provenance attributes were rejected.

    ``context["non_str_fields"]`` is a **structured** key -- a mapping of
    attribute name to the type name found there -- so this is the ADR-008
    assertion proper, not a grep of prose.
    """
    assert set(error.context["non_str_fields"]) == set(expected)


def test_non_str_model_version_is_rejected_before_comparison() -> None:
    """Defect B, model_version dimension: rejected, not compared.

    A ``_NonStrAlwaysUnequal`` previously reached ``build_mismatches`` and
    landed in ``context["mismatches"]["model_version"]["expected"]``,
    violating the declared ``dict[str, dict[str, str]]``. ``mypy --strict``
    cannot catch that: ``build_mismatches``' parameters are declared
    ``str`` and the probed value arrives as ``Any``, so the lie
    type-checks.
    """
    error = _assert_rejected_as_invalid_artefact(_NonStrModelVersionArtefact())
    _assert_offending_fields(error, "provenance_model_version")


def test_non_str_criteria_is_rejected_before_comparison() -> None:
    """Defect B, scoring_criteria dimension: rejected, not compared."""

    class _NonStrCriteriaArtefact:
        provenance_model_version = _MODEL_VERSION
        provenance_criteria = _NonStrAlwaysUnequal()

    error = _assert_rejected_as_invalid_artefact(_NonStrCriteriaArtefact())
    _assert_offending_fields(error, "provenance_criteria")


def test_both_non_str_dimensions_are_both_reported() -> None:
    """Both dimensions non-``str`` at once: both named, not just the first.

    ADR-002's amendment settled this shape for ``ProvenanceMismatchError``
    -- when both dimensions differ, report both, never short-circuit on
    the first checked -- and the reasoning carries over unchanged to
    rejecting a malformed artefact. A guard that returned after finding
    one bad attribute would satisfy both per-dimension tests above and
    still under-report here.

    ⚠️ **Two earlier drafts of this test got the assertion wrong in
    opposite directions, which is why the mechanism is spelled out.**

    The first grepped ``context["constraint"]`` for each attribute name.
    That is a **false signal**: ``constraint`` is a fixed module constant
    (``_ARTEFACT_PROVENANCE_CONSTRAINT``) naming both attributes whatever
    the input was, so it holds even for a guard that inspects one
    dimension. It is also the message-text assertion ADR-008 forbids.

    The second dropped the claim entirely, on the stated grounds that
    making it *"needs a structured* ``context`` *field (BIN-134)"*.
    **That was wrong** -- ``non_str_fields`` is exactly that field, and it
    was already on the error, three lines below the ``constraint`` the
    first draft was grepping. Caught by ``code-reviewer``. ADR-008's
    remedy for prose-parsing is to assert a structured key **when one
    exists**; checking whether it does comes before concluding it cannot
    be done. ``BIN-134`` remains open for the bounds that genuinely have
    no such field -- it is not a blanket excuse.
    """
    error = _assert_rejected_as_invalid_artefact(_BothNonStrArtefact())
    _assert_offending_fields(error, "provenance_model_version", "provenance_criteria")


# ===================================================================
# Confirmation -- already-guarded surfaces
#
# These tests PASS against current src/. They verify that BIN-118's
# guards in monitor.py and the error construction path remain safe.
# They are regression guards, not red-phase tests.
# ===================================================================


def test_caliper_error_repr_does_not_format_context_values() -> None:
    """``CaliperError.__init__`` passes only the message string to
    ``super().__init__()``. ``repr(error)`` and ``str(error)`` format
    only ``args[0]`` (the message), never ``context`` values.

    A hostile object stored in ``context["provided"]`` must not cause
    ``repr(error)`` or ``str(error)`` to raise.
    """

    class _HostileRepr:
        def __repr__(self) -> str:
            raise RuntimeError("repr exploded")

        def __str__(self) -> str:
            raise RuntimeError("str exploded")

    error = InvalidParameterError(
        "test message",
        context={
            "parameter": "x",
            "constraint": "y",
            "kind": "invalid",
            "provided": _HostileRepr(),
        },
        recovery_hint="test",
    )

    # Neither must raise
    result_repr = repr(error)
    result_str = str(error)

    assert "test message" in result_repr
    assert result_str == "test message"


def test_caliper_error_is_not_value_error_subclass() -> None:
    """``CaliperError`` must not subclass ``ValueError``.

    This is load-bearing for the ``mode="before"`` type guards in
    ``caliper.measurement.domain.type_guards``: Pydantic re-wraps
    ``ValueError``/``AssertionError`` raised inside any field validator
    into its own ``ValidationError``, but propagates every other exception
    type unchanged. If ``CaliperError`` ever became a ``ValueError``
    subclass, every type guard would silently stop working.

    Already pinned by ``tests/unit/test_errors.py`` (verified via the
    module's own docstring); duplicated here as part of the hostile-object
    audit's contract verification.
    """
    assert not issubclass(CaliperError, ValueError)
    assert not issubclass(CaliperError, AssertionError)
