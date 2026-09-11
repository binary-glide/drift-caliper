"""Smoke test: the package installs and imports under the configured toolchain."""

import caliper
from caliper.baseline import Baseline as BaselineFromSubpackage
from caliper.measurement import Judge as JudgeFromSubpackage


def test_exposes_module_docstring_when_imported() -> None:
    # Arrange/Act: importing the module (above) is the only action under
    # test -- there is nothing else to set up or call.
    # Assert
    assert caliper.__doc__


def test_every_exported_name_resolves() -> None:
    # Arrange: __all__ as declared by the package. Deliberately does not pin
    # the CONTENTS of __all__. The top-level public surface is still being
    # decided as bounded contexts land; freezing it here would turn a design
    # decision into a test failure. What must always hold is that anything
    # __all__ claims to export actually exists.
    exported_names = caliper.__all__

    # Act/Assert: resolving each declared name on the module is itself the
    # check -- there is no separate result to inspect afterwards.
    for name in exported_names:
        assert hasattr(caliper, name), f"__all__ exports {name!r}, which is absent"


# --- Import surface (BIN-110 P2) -----------------------------------------
#
# Before BIN-110, `caliper.__all__` was `[]` -- an accident carried since
# BIN-57 (a smoke test once asserted `__all__ == []`; that assertion was
# later removed as wrong, but the empty list itself was never revisited).
# `import caliper` gave an engineer nothing; they had to already know to
# reach into `caliper.measurement` and `caliper.baseline`. These tests pin
# a front door: everything an engineer types in their own code -- `Judge`,
# `ScoringCriteria`, `Baseline`, the three `fit_*` functions, the result
# and artefact types they annotate with, and the error taxonomy -- must be
# reachable from the top level. Subpackage imports keep working
# unconditionally (nothing here removes them, and
# `test_subpackage_imports_still_work_alongside_the_top_level_promotion`
# below pins that directly); this only adds a shorter path alongside them.

# Every name BIN-110 requires promoted to `caliper.__all__` -- the set an
# engineer names in their own code, per the ticket's own list. Deliberately
# a *subset* requirement (`<=`), not an exact-equality pin: a future story
# may reasonably promote more names, and this test should not have to
# change every time that happens. Internal validation constants
# (`MIN_*`/`MAX_*`/`DEFAULT_*`) are deliberately absent from this set --
# see `tests/unit/baseline/test_baseline_package_exports.py` for that
# separate, `caliper.baseline`-scoped ruling.
_REQUIRED_TOP_LEVEL_NAMES = frozenset(
    {
        # Measurement
        "Judge",
        "ModelVersion",
        "Provenance",
        "ScoringCriteria",
        "ScoringResult",
        # The port an adapter implements. ADR-006 names writing a
        # concrete provider as the natural first-hour task, so the
        # protocol and its response type belong on the front door.
        "JudgeProviderPort",
        "JudgeProviderResponse",
        # Baseline
        "Baseline",
        "SufficiencyResult",
        "DataQualityConcern",
        "FittedControlLimits",
        "FittedEWMA",
        "FittedCUSUM",
        "FittedShewhart",
        "fit_ewma",
        "fit_cusum",
        "fit_shewhart",
        "compare_provenance",
        # Monitoring (BIN-69, BIN-72, ADR-009)
        "Monitor",
        "MonitoringResult",
        # Error taxonomy (ADR-002) -- an engineer catches these, so they
        # must be reachable without knowing `caliper.errors` exists.
        "CaliperError",
        "InvalidParameterError",
        "MissingPrerequisiteError",
        "ProviderError",
        "MalformedResponseError",
        "JudgeRefusalError",
        "ProvenanceMismatchError",
        "InvalidObservationError",
        "InsufficientBaselineError",
        "DegenerateBaselineError",
    }
)


def test_dunder_all_is_not_empty() -> None:
    """`import caliper` must expose something.

    BIN-57 deliberately deferred promotion rather than churning the top
    level one story at a time; BIN-110 discharges that deferral now the
    walking skeleton's shape is settled. The empty list was a decision
    with a stated exit condition, not an oversight -- but leaving it
    empty past that condition would be.
    """
    assert caliper.__all__ != []


def test_dunder_all_includes_every_name_an_engineer_types() -> None:
    """The front door promotes Judge, Baseline, fit_*, results, and errors."""
    # Arrange
    exported = set(caliper.__all__)

    # Act
    missing = _REQUIRED_TOP_LEVEL_NAMES - exported

    # Assert
    assert missing == set(), f"not promoted to caliper.__all__: {sorted(missing)}"


def test_promoted_names_are_usable_directly_from_the_top_level() -> None:
    """The promoted names are not just listed -- they resolve and work.

    `test_every_exported_name_resolves` above would already catch a name
    that doesn't `hasattr`; this goes one step further for the first thing
    an engineer's own snippet does -- actually constructing through the
    top-level path rather than a subpackage import.
    """
    # Act
    judge = caliper.Judge.create(model_version="claude-sonnet-4-5-20250929")

    # Assert
    assert isinstance(judge, caliper.Judge)
    assert isinstance(judge.model_version, caliper.ModelVersion)


def test_subpackage_imports_still_work_alongside_the_top_level_promotion() -> None:
    """Promoting names to the top level must not remove the deep-path imports."""
    assert BaselineFromSubpackage is caliper.Baseline
    assert JudgeFromSubpackage is caliper.Judge
