"""Caliper's typed exception taxonomy.

Nine leaf exception types under a single :class:`CaliperError` base
(ADR-002). Each carries a stable ``category`` string and a structured
``context`` mapping -- the testable contract -- plus a human-readable
``recovery_hint`` that is deliberately excluded from any test assertion.

Immutability violations (e.g. attempting to reassign a frozen dataclass
field) are NOT part of this taxonomy -- they raise Python's built-in
``AttributeError`` / ``dataclasses.FrozenInstanceError`` instead (ADR-002
section 7).

See ``docs/architecture/adr/002-error-contract-exception-taxonomy.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class CaliperError(Exception):
    """Base of Caliper's exception taxonomy.

    Consumers can catch every Caliper failure with ``except CaliperError``,
    or a specific leaf type below for finer-grained handling.

    Attributes:
        category: Stable, machine-readable category identifier (e.g.
            ``"invalid_parameter"``). Part of the tested contract.
        context: Structured fields describing the failure. Required keys
            per category are documented on each leaf type and in ADR-002.
            Part of the tested contract.
        recovery_hint: Human-readable suggested next step, for engineers
            reading logs or a REPL. Not part of the tested contract --
            tests must never assert on its content.
    """

    category: str

    def __init__(
        self,
        message: str,
        *,
        category: str,
        context: Mapping[str, Any],
        recovery_hint: str,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.context: Mapping[str, Any] = context
        self.recovery_hint = recovery_hint


class InvalidParameterError(CaliperError):
    """A parameter was missing, or a supplied value violates a constraint.

    Required ``context`` keys:
        parameter: Name of the offending parameter.
        constraint: What the parameter must satisfy.
        kind: ``"missing"`` when the parameter was not supplied at all,
            ``"invalid"`` when a value was supplied but violates the
            constraint. A closed discriminator.
        provided: The supplied value. Present only when ``kind ==
            "invalid"`` -- absent when ``kind == "missing"``, but nothing
            asserts on that absence (ADR-002 section 3).
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="invalid_parameter",
            context=context,
            recovery_hint=recovery_hint,
        )


class MissingPrerequisiteError(CaliperError):
    """An operation was attempted before its required configuration was in place.

    Required ``context`` keys:
        prerequisite: What is missing.
        operation: What operation it blocks.
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="missing_prerequisite",
            context=context,
            recovery_hint=recovery_hint,
        )


class ProviderError(CaliperError):
    """A judge's LLM provider returned an error or was unreachable.

    Required ``context`` keys:
        provider: Which provider failed.
        operation: What operation was attempted.
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="provider_failure",
            context=context,
            recovery_hint=recovery_hint,
        )


class MalformedResponseError(CaliperError):
    """A judge produced a response that cannot be parsed.

    Required ``context`` keys:
        operation: What operation produced the response.
        expected_shape: What shape was expected.
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="malformed_response",
            context=context,
            recovery_hint=recovery_hint,
        )


class JudgeRefusalError(CaliperError):
    """A judge declined to score due to a content or safety policy.

    Required ``context`` keys:
        provider: Which provider refused.
        operation: What was being scored.
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="judge_refusal",
            context=context,
            recovery_hint=recovery_hint,
        )


class ProvenanceMismatchError(CaliperError):
    """An observation's provenance differs from an established signature.

    Required ``context`` keys:
        dimension: Which provenance field differs (model version or
            criteria).
        expected: The established value.
        received: The differing value.
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="provenance_mismatch",
            context=context,
            recovery_hint=recovery_hint,
        )


class InvalidObservationError(CaliperError):
    """An input to baseline recording is not a complete scoring result.

    Required ``context`` keys:
        reason: Why the observation is invalid.
        missing_fields: Which fields are missing.
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="invalid_observation",
            context=context,
            recovery_hint=recovery_hint,
        )


class InsufficientBaselineError(CaliperError):
    """A baseline is below the minimum observation count required for fitting.

    Required ``context`` keys:
        have: Current observation count.
        need: Required minimum.
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="insufficient_baseline",
            context=context,
            recovery_hint=recovery_hint,
        )


class DegenerateBaselineError(CaliperError):
    """A baseline meets the count threshold but is statistically unusable.

    Required ``context`` keys:
        reason: What makes the baseline degenerate (e.g.
            ``"zero_variance"``).
    """

    def __init__(
        self, message: str, *, context: Mapping[str, Any], recovery_hint: str
    ) -> None:
        super().__init__(
            message,
            category="degenerate_baseline",
            context=context,
            recovery_hint=recovery_hint,
        )
