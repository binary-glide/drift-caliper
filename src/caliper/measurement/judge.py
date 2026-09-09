"""The Judge -- an immutable configured adapter pinned to a model version.

See ``docs/domain-model.md`` (Judge -- immutable configured adapter) and
ADR-002 for the error contract enforced at creation.
"""

from __future__ import annotations

from dataclasses import dataclass

from caliper.errors import InvalidParameterError

_MODEL_VERSION_CONSTRAINT = "must be a non-empty string that is not entirely whitespace"


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
                    "constraint": _MODEL_VERSION_CONSTRAINT,
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


@dataclass(frozen=True, slots=True)
class Judge:
    """An immutable configured adapter that scores agent outputs.

    A ``Judge`` wraps an LLM provider and holds a model version pinned at
    creation time. The model version cannot change after creation --
    attempting to assign to it raises ``dataclasses.FrozenInstanceError``
    (ADR-002 section 7: immutability violations are not part of the
    ``CaliperError`` taxonomy).
    """

    model_version: ModelVersion

    @classmethod
    def create(cls, model_version: str | None = None) -> Judge:
        """Create a judge with a required, pinned model version.

        ``model_version`` is optional in the Python signature but required
        by Caliper's validation -- omitting it raises
        ``InvalidParameterError`` with ``context["kind"] == "missing"``
        rather than a Python ``TypeError``, following the same
        optional-with-required-semantics pattern ADR-004 established for
        the fitting API's ``target_arl``.

        Args:
            model_version: The model version string to pin. Must be
                non-empty and not whitespace-only. Preserved exactly as
                provided, including surrounding whitespace.

        Returns:
            A new, immutable ``Judge`` pinned to ``model_version``.

        Raises:
            InvalidParameterError: ``model_version`` was omitted (
                ``context["kind"] == "missing"``), or was supplied but is
                empty or whitespace-only (``context["kind"] == "invalid"``,
                raised from ``ModelVersion.__post_init__``).
        """
        if model_version is None:
            raise InvalidParameterError(
                "model_version is required to pin measurement stability",
                context={
                    "parameter": "model_version",
                    "constraint": _MODEL_VERSION_CONSTRAINT,
                    "kind": "missing",
                },
                recovery_hint=(
                    "Call Judge.create(model_version=...) with the exact "
                    "model version string your provider returns, e.g. "
                    "'claude-sonnet-4-5-20250929'. An unpinned judge "
                    "silently invalidates every statistical claim "
                    "downstream, so this is a required parameter."
                ),
            )
        return cls(model_version=ModelVersion(value=model_version))
