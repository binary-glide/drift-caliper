"""The judge provider port -- the seam between ``Judge`` and an LLM provider.

See ``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
section 1. A conforming implementation owns everything infrastructure
specific: the call to an LLM provider (or any other scoring backend), and
interpreting its raw response into a score and reasoning. Caliper's domain
layer never sees a provider SDK, an HTTP client, or a raw response payload.

A concrete implementation (wrapping a real LLM provider SDK) is out of
scope for this story -- ``FakeJudgeProviderPort`` (``tests/support/fakes.py``)
is the only implementation that exists so far, and is test code, not part
of this package.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class JudgeProviderResponse(BaseModel):
    """Raw ``(score, reasoning)`` pair returned by a provider.

    Internal to ``Judge.score()``'s orchestration -- not exposed to the
    engineer. Provenance is attached by ``Judge.score()`` after this is
    returned; a ``JudgeProviderResponse`` carries no provenance itself.
    """

    model_config = ConfigDict(frozen=True)

    score: float
    reasoning: str


@runtime_checkable
class JudgeProviderPort(Protocol):
    """Port through which a ``Judge`` obtains a score and reasoning.

    A structural contract (``@runtime_checkable`` ``Protocol``) that a fake
    or a real adapter can satisfy without inheriting from anything --
    following the same pattern ADR-004 established for ``FittedControlLimits``.
    This is what makes ``Judge.score()`` testable without a network call.

    Exception contract (part of this Protocol -- cannot be expressed in
    Python's type system, so it is normative here):

    Raises:
        ProviderError: the call to the provider failed or the provider was
            unreachable. Required context: ``provider``, ``operation``.
        MalformedResponseError: the provider responded, but the response
            cannot be interpreted as a ``(score, reasoning)`` pair.
            Required context: ``operation``, ``expected_shape``.
        JudgeRefusalError: the provider declined to score due to a content
            or safety policy. Required context: ``provider``, ``operation``.
    """

    def score(
        self,
        *,
        model_version: str,
        criteria: str,
        agent_output: str,
        agent_input: str | None = None,
    ) -> JudgeProviderResponse:
        """Call the provider and return its parsed ``(score, reasoning)``.

        Args:
            model_version: The judge's pinned model version.
            criteria: The effective scoring criteria text for this call.
            agent_output: The agent output being scored.
            agent_input: The agent input that produced ``agent_output``,
                when available.

        Returns:
            The provider's parsed score and reasoning.
        """
        ...
