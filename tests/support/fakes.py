"""Test doubles for the Measurement bounded context.

``FakeJudgeProviderPort`` is an in-memory, no-network implementation of
``caliper.measurement.JudgeProviderPort`` (ADR-006 section 1). It is the
seam that makes "the judge's provider returns an error" and "the judge
produces an uninterpretable response" testable without a real LLM provider
call: configure it to return a fixed ``JudgeProviderResponse``, or to raise
``ProviderError``, ``MalformedResponseError`` or ``JudgeRefusalError``.

Test code only -- never imported from ``src/caliper``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from caliper.errors import CaliperError
from caliper.measurement import JudgeProviderResponse


@dataclass
class FakeJudgeProviderPort:
    """Configurable in-memory stand-in for a real ``JudgeProviderPort``.

    Configure exactly one of ``response`` or ``error_to_raise`` before
    calling ``score()``. Both may be reassigned between calls (e.g. to
    reuse one fake across the happy-path and error branches of a
    scenario). Every call is recorded in ``calls``, in order, so a test can
    assert the provider was (or was not) reached, and with what arguments.
    """

    response: JudgeProviderResponse | None = None
    error_to_raise: CaliperError | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def score(
        self,
        *,
        model_version: str,
        criteria: str,
        agent_output: str,
        agent_input: str | None = None,
    ) -> JudgeProviderResponse:
        """Record the call, then return ``response`` or raise ``error_to_raise``.

        Raises:
            CaliperError: whatever ``error_to_raise`` was configured to be.
            AssertionError: neither ``response`` nor ``error_to_raise`` was
                configured -- a test setup bug, not a scenario under test.
        """
        self.calls.append(
            {
                "model_version": model_version,
                "criteria": criteria,
                "agent_output": agent_output,
                "agent_input": agent_input,
            }
        )
        if self.error_to_raise is not None:
            raise self.error_to_raise
        if self.response is not None:
            return self.response
        raise AssertionError(
            "FakeJudgeProviderPort must be configured with either "
            "`response` or `error_to_raise` before use"
        )
