"""Caliper's typed exception taxonomy.

Nine leaf exception types under a single :class:`CaliperError` base
(ADR-002). Each carries a stable ``category`` string and a structured
``context`` mapping -- the testable contract -- plus a human-readable
``recovery_hint`` that is deliberately excluded from any test assertion.

Immutability violations (e.g. attempting to reassign a field on a frozen
Pydantic ``BaseModel``) are NOT part of this taxonomy -- they raise
Pydantic's ``ValidationError`` instead (ADR-002 section 7, amended
2026-09-09 under BIN-103 -- verified empirically against pydantic 2.13.5;
value objects were stdlib frozen dataclasses when section 7 was
originally written).

See ``docs/architecture/adr/002-error-contract-exception-taxonomy.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class CaliperError(Exception):
    """Base of Caliper's exception taxonomy.

    Consumers can catch every Caliper failure with ``except CaliperError``,
    or a specific leaf type below for finer-grained handling.

    The taxonomy is semi-open (ADR-002 section 6): third-party code may
    extend it by subclassing with a new ``category`` string. Library
    categories are a stable contract -- removing one is a breaking change,
    adding one is a minor-version change.

    Attributes:
        category: Stable, machine-readable category identifier (e.g.
            ``"invalid_parameter"``), declared once per concrete subclass.
            Part of the tested contract.
        context: Structured fields describing the failure. Required keys
            per category are documented on each leaf type and in ADR-002.
            Part of the tested contract.
        recovery_hint: Human-readable suggested next step, for engineers
            reading logs or a REPL. Not part of the tested contract --
            tests must never assert on its content.
    """

    category: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Require every concrete subclass to declare a ``category``.

        The constructor no longer takes ``category`` as an argument, so
        nothing else would catch a subclass that forgets to set it -- the
        omission would surface much later, as an ``AttributeError`` raised
        while a caller was trying to classify an error it had just caught.
        Failing at class-definition time instead makes it a typo the author
        sees immediately, and it holds for third-party extensions too.
        """
        super().__init_subclass__(**kwargs)
        if "category" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must declare a class-level `category` string; "
                "see ADR-002 section 6 on extending the taxonomy"
            )

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any],
        recovery_hint: str,
    ) -> None:
        super().__init__(message)
        self.context: Mapping[str, Any] = context
        self.recovery_hint = recovery_hint


class InvalidParameterError(CaliperError):
    """A parameter was missing, or a supplied value violates a constraint.

    Required ``context`` keys:
        parameter: Name of the offending parameter.
        constraint: What the parameter must satisfy.
        kind: ``"missing"`` when the parameter was not supplied at all,
            ``"invalid"`` when a value was supplied but violates the
            constraint. A closed discriminator -- distinct from the
            descriptive ``reason`` key used by other categories, and
            deliberately not unified with it.
        provided: The supplied value. Present only when ``kind ==
            "invalid"`` -- absent when ``kind == "missing"``, but nothing
            asserts on that absence (ADR-002 section 3).
    """

    category = "invalid_parameter"


class MissingPrerequisiteError(CaliperError):
    """An operation was attempted before its required configuration was in place.

    Required ``context`` keys:
        prerequisite: What is missing.
        operation: What operation it blocks.
    """

    category = "missing_prerequisite"


class ProviderError(CaliperError):
    """A judge's LLM provider returned an error or was unreachable.

    Required ``context`` keys:
        provider: Which provider failed.
        operation: What operation was attempted.
    """

    category = "provider_failure"


class MalformedResponseError(CaliperError):
    """A judge produced a response that cannot be parsed.

    Required ``context`` keys:
        operation: What operation produced the response.
        expected_shape: What shape was expected.
    """

    category = "malformed_response"


class JudgeRefusalError(CaliperError):
    """A judge declined to score due to a content or safety policy.

    Required ``context`` keys:
        provider: Which provider refused.
        operation: What was being scored.
    """

    category = "judge_refusal"


class ProvenanceMismatchError(CaliperError):
    """An observation's provenance differs from an established signature.

    Required ``context`` keys:
        dimension: Which provenance field differs (model version or
            criteria).
        expected: The established value.
        received: The differing value.
    """

    category = "provenance_mismatch"


class InvalidObservationError(CaliperError):
    """An input to baseline recording is not a complete scoring result.

    Required ``context`` keys:
        reason: Why the observation is invalid. Descriptive, not a closed
            discriminator -- see ``InvalidParameterError.kind``.
        missing_fields: Which fields are missing.
    """

    category = "invalid_observation"


class InsufficientBaselineError(CaliperError):
    """A baseline is below the minimum observation count required for fitting.

    Required ``context`` keys:
        have: Current observation count.
        need: Required minimum.
    """

    category = "insufficient_baseline"


class DegenerateBaselineError(CaliperError):
    """A baseline meets the count threshold but is statistically unusable.

    Required ``context`` keys:
        reason: What makes the baseline degenerate (e.g.
            ``"zero_variance"``). Descriptive, not a closed discriminator
            -- see ``InvalidParameterError.kind``.
    """

    category = "degenerate_baseline"
