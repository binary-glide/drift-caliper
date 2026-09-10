"""``caliper.baseline``'s public export surface (BIN-110 P2).

Before BIN-110, `caliper.baseline.__all__` listed 6 internal validation
bounds (`MIN_*`/`MAX_*`) alongside the useful domain types and `fit_*`
functions -- noise on autocomplete that an engineer never needs to type.
`DEFAULT_*` constants are ruled to belong (see below); `MIN_*`/`MAX_*` are
removed from the module entirely, not just from `__all__` -- `__all__`
only governs `from module import *`, not attribute access or REPL
tab-completion, so the actual DX fix is dropping the re-export itself, not
just the list entry.

**Ruling on `DEFAULT_*` (delegated by the ticket):** kept, exported. An
engineer overriding `fit_ewma(smoothing_param=...)` benefits from seeing
what the un-overridden value is (`DEFAULT_SMOOTHING_PARAM`) before they
decide to override it -- the same reasoning ADR-005 already establishes
for `DEFAULT_SUFFICIENCY_THRESHOLD`. `MIN_*`/`MAX_*` have no equivalent
case: they are validation floors and ceilings an engineer supplies a value
*within*, never a value they assign, so knowing the exact number buys them
nothing an `InvalidParameterError`'s `constraint` message does not already
say at the moment they actually need it.
"""

from __future__ import annotations

import caliper.baseline as baseline_pkg

# The 6 internal validation bounds BIN-110 removes from the public surface
# entirely (not just from __all__ -- see module docstring).
_REMOVED_VALIDATION_BOUNDS = (
    "MAX_MEANINGFUL_ARL",
    "MAX_REFERENCE_VALUE",
    "MAX_SMOOTHING_PARAM",
    "MIN_MEANINGFUL_ARL",
    "MIN_REFERENCE_VALUE",
    "MIN_SMOOTHING_PARAM",
)

# The 4 DEFAULT_* constants BIN-110 keeps -- see the module docstring's
# ruling.
_RETAINED_DEFAULT_CONSTANTS = (
    "DEFAULT_DIRECTION",
    "DEFAULT_REFERENCE_VALUE",
    "DEFAULT_SMOOTHING_PARAM",
    "DEFAULT_SUFFICIENCY_THRESHOLD",
)

# The domain types and fit_* functions that were already useful exports --
# BIN-110 does not touch these; pinned here so a future accidental removal
# is a visible, deliberate test failure rather than a silent regression.
_RETAINED_DOMAIN_EXPORTS = (
    "Baseline",
    "DataQualityConcern",
    "FittedControlLimits",
    "FittedCUSUM",
    "FittedEWMA",
    "FittedShewhart",
    "SufficiencyResult",
    "fit_cusum",
    "fit_ewma",
    "fit_shewhart",
)


def test_internal_validation_bounds_are_removed_from_the_module_entirely() -> None:
    """MIN_*/MAX_* must not be reachable at all -- not just absent from __all__.

    `__all__` only changes `from caliper.baseline import *`; REPL
    tab-completion and `hasattr` see every module attribute regardless of
    `__all__`. The DX complaint was about autocomplete noise, so the
    re-export itself must go, not just the list entry.
    """
    for name in _REMOVED_VALIDATION_BOUNDS:
        assert not hasattr(baseline_pkg, name), (
            f"{name} is internal validation noise; it must not be an "
            "attribute of caliper.baseline at all"
        )
        assert name not in baseline_pkg.__all__


def test_default_constants_remain_exported() -> None:
    """DEFAULT_* stays -- an engineer may want to know a default before overriding."""
    for name in _RETAINED_DEFAULT_CONSTANTS:
        assert hasattr(baseline_pkg, name)
        assert name in baseline_pkg.__all__


def test_domain_types_and_fit_functions_remain_exported() -> None:
    """BIN-110 does not touch the already-useful exports."""
    for name in _RETAINED_DOMAIN_EXPORTS:
        assert hasattr(baseline_pkg, name)
        assert name in baseline_pkg.__all__


def test_every_exported_name_resolves() -> None:
    """Mirrors `tests/unit/test_package.py`'s top-level check, for this subpackage."""
    for name in baseline_pkg.__all__:
        assert hasattr(baseline_pkg, name), f"__all__ exports {name!r}, which is absent"
