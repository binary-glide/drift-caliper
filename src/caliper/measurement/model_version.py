"""The pinned model version a Judge measures with.

A value object in its own module rather than a member of ``judge.py``,
following the one-value-object-per-module convention (ADR-006 section 7).
That placement is load-bearing, not cosmetic: ``Provenance`` also carries a
``ModelVersion``, so while this type lived in ``judge.py`` the import graph
ran ``judge -> result -> provenance -> judge`` and ``Judge.score()`` had to
defer its imports into the function body to break the cycle. With the type
here, nothing imports ``judge.py`` and every import sits at module level.

See ADR-002 for the error contract enforced at creation.
"""

from __future__ import annotations

from dataclasses import dataclass

from caliper.errors import InvalidParameterError

# Shared with judge.py, which reports the same constraint for the "missing"
# case before a ModelVersion is ever constructed. Not part of the public API
# -- `caliper.measurement` does not re-export it.
MODEL_VERSION_CONSTRAINT = "must be a non-empty string that is not entirely whitespace"


@dataclass(frozen=True, slots=True)
class ModelVersion:
    """A pinned, non-empty model version string.

    Preserved exactly as provided, including any surrounding whitespace.
    Equality follows the wrapped ``value`` (dataclass value equality).

    Validation lives here, in ``__post_init__``, rather than in any caller
    (e.g. ``Judge.create``) so the invariant holds for every construction
    path -- there is no way to build a ``ModelVersion`` that wraps an empty
    or whitespace-only string.

    Raises:
        InvalidParameterError: ``value`` is empty or contains only
            whitespace. ``context["kind"]`` is always ``"invalid"`` here --
            a value was supplied, just not one that satisfies the
            constraint. The ``"missing"`` case (no value supplied at all)
            is a distinct condition handled by callers such as
            ``Judge.create`` before a ``ModelVersion`` is ever constructed.
    """

    value: str

    def __post_init__(self) -> None:
        """Reject empty or whitespace-only model version strings."""
        if self.value.strip() == "":
            raise InvalidParameterError(
                "model_version must be a non-empty, non-whitespace string",
                context={
                    "parameter": "model_version",
                    "constraint": MODEL_VERSION_CONSTRAINT,
                    "kind": "invalid",
                    "provided": self.value,
                },
                recovery_hint=(
                    "Pass the exact model version string your provider "
                    "returns for the model you are pinning to, e.g. "
                    "'claude-sonnet-4-5-20250929'. Whitespace-only strings "
                    "do not identify a model."
                ),
            )
