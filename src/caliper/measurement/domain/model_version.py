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

from pydantic import BaseModel, ConfigDict, field_validator

from caliper.errors import InvalidParameterError
from caliper.measurement.domain.type_guards import require_str

# Shared with judge.py, which reports the same constraint for the "missing"
# case before a ModelVersion is ever constructed. Not part of the public API
# -- `caliper.measurement` does not re-export it.
MODEL_VERSION_CONSTRAINT = "must be a non-empty string that is not entirely whitespace"


class ModelVersion(BaseModel):
    """A pinned, non-empty model version string.

    Preserved exactly as provided, including any surrounding whitespace.
    Equality follows the wrapped ``value``.

    Validation lives here, in a ``field_validator``, rather than in any caller
    (e.g. ``Judge.create``) so the invariant holds for every construction
    path -- there is no way to build a ``ModelVersion`` that wraps an empty
    or whitespace-only ``str``.

    A wrong-*typed* argument (``ModelVersion(value=123)``) is rejected by
    ``reject_wrong_type`` below, a ``mode="before"`` validator that runs
    ahead of Pydantic's own core coercion (BIN-104) -- so both a blank
    value and a wrong-typed one raise the same ``InvalidParameterError``,
    never a raw ``pydantic_core.ValidationError``.

    Raises
    ------
    InvalidParameterError
        ``value`` is not a ``str``, or is empty or contains only
        whitespace. ``context["kind"]`` is always ``"invalid"`` here -- a
        value was supplied, just not one that satisfies the constraint.
        The ``"missing"`` case (no value supplied at all) is a distinct
        condition handled by callers such as ``Judge.create`` before a
        ``ModelVersion`` is ever constructed.
    """

    model_config = ConfigDict(frozen=True)

    value: str

    @field_validator("value", mode="before")
    @classmethod
    def reject_wrong_type(cls, v: object) -> object:
        """Reject a non-``str`` ``value`` before Pydantic's core coercion runs.

        See ``caliper.measurement.domain.type_guards`` for why this is a
        ``mode="before"`` validator and why it raises ``InvalidParameterError``
        directly rather than ``ValueError`` (BIN-104).
        """
        return require_str(
            v, parameter="model_version", constraint=MODEL_VERSION_CONSTRAINT
        )

    @field_validator("value")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        """Reject empty or whitespace-only model version strings.

        Raises ``InvalidParameterError`` directly rather than ``ValueError``.
        Pydantic wraps ``ValueError`` and ``AssertionError`` in its own
        ``ValidationError``; any other exception propagates unwrapped, which
        is what preserves ADR-002's contract for the engineer who called us.
        ``architecture/references/ddd.md`` translates at a service boundary
        instead -- Caliper has no service layer, so there is nowhere to do
        that, and the value object is the boundary.
        """
        if v.strip() == "":
            raise InvalidParameterError(
                "model_version must be a non-empty, non-whitespace string",
                context={
                    "parameter": "model_version",
                    "constraint": MODEL_VERSION_CONSTRAINT,
                    "kind": "invalid",
                    "provided": v,
                },
                recovery_hint=(
                    "Pass the exact model version string your provider "
                    "returns for the model you are pinning to, e.g. "
                    "'claude-sonnet-4-5-20250929'. Whitespace-only strings "
                    "do not identify a model."
                ),
            )
        return v

    def __str__(self) -> str:
        """Return the wrapped string directly (BIN-110 P3).

        A ``str`` goes in at ``Judge.create(model_version=...)``; without
        this, reading it back (an f-string, a log line) produced Pydantic's
        default ``"ModelVersion(value='...')"``, needing ``.value`` to
        recover the original string. ``repr()`` is untouched -- it still
        identifies the wrapper type, which is the correct behaviour for a
        REPL echo (``CLAUDE.md``: "Every public type reprs usefully").
        """
        return self.value
