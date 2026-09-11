"""The Judge -- an immutable configured adapter pinned to a model version.

See ``docs/domain-model.md`` (Judge -- immutable configured adapter),
ADR-002 for the error contract enforced at creation, and
``docs/architecture/adr/006-scoring-api-surface-and-judge-provider-port.md``
for ``provider``, ``criteria`` and ``score()``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from caliper.errors import InvalidParameterError, MissingPrerequisiteError
from caliper.measurement.domain.criteria import ScoringCriteria
from caliper.measurement.domain.model_version import (
    MODEL_VERSION_CONSTRAINT,
    ModelVersion,
)
from caliper.measurement.domain.provenance import Provenance
from caliper.measurement.domain.result import ScoringResult
from caliper.measurement.ports.judge_provider import JudgeProviderPort

# Mirrors MODEL_VERSION_CONSTRAINT's shape for the one caller-facing string
# constant this module owns outright.
AGENT_OUTPUT_CONSTRAINT = "must be a non-empty string that is not entirely whitespace"


class Judge(BaseModel):
    """An immutable configured adapter that scores agent outputs.

    A ``Judge`` wraps an LLM provider and holds a model version pinned at
    creation time. The model version cannot change after creation --
    attempting to assign to it raises Pydantic's ``ValidationError``
    (ADR-002 section 7: immutability violations are not part of the
    ``CaliperError`` taxonomy).

    ``provider`` and ``criteria`` are optional additions (ADR-006 section 2)
    -- both default to ``None`` and are purely additive over BIN-57's
    original single-field ``Judge``. Neither is validated at creation
    beyond what ``ScoringCriteria's validator`` already enforces; their
    absence at ``score()`` time is what raises ``MissingPrerequisiteError``.

    ``arbitrary_types_allowed`` is required because ``JudgeProviderPort`` is
    a ``Protocol``, which Pydantic cannot build a validation schema for. It
    is ``@runtime_checkable``, so Pydantic still isinstance-checks a supplied
    provider against the protocol's method set rather than accepting anything.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    model_version: ModelVersion
    provider: JudgeProviderPort | None = None
    criteria: ScoringCriteria | None = None

    @classmethod
    def create(
        cls,
        model_version: str | None = None,
        provider: JudgeProviderPort | None = None,
        criteria: str | None = None,
    ) -> Judge:
        """Create a judge with a required, pinned model version.

        ``model_version`` is optional in the Python signature but required
        by Caliper's validation -- omitting it raises
        ``InvalidParameterError`` with ``context["kind"] == "missing"``
        rather than a Python ``TypeError``, following the same
        optional-with-required-semantics pattern ADR-004 established for
        the fitting API's ``target_arl``.

        ``provider`` and ``criteria`` are both optional (ADR-006 section 2).
        A missing ``provider`` or missing (judge-level and per-call)
        ``criteria`` is not an error here -- it only becomes
        ``MissingPrerequisiteError`` when ``score()`` actually needs it.

        Parameters
        ----------
        model_version
            The model version string to pin. Must be non-empty and not
            whitespace-only. Preserved exactly as provided, including
            surrounding whitespace.
        provider
            The judge provider port used by ``score()``. Optional at
            creation; required by the time ``score()`` runs.
        criteria
            The judge-level scoring criteria text. Optional at creation;
            may also be supplied (or overridden) per call to ``score()``.
            Must be non-empty and not whitespace-only if supplied --
            validated by ``ScoringCriteria``.

        Returns
        -------
        Judge
            A new, immutable ``Judge`` pinned to ``model_version``.

        Raises
        ------
        InvalidParameterError
            ``model_version`` was omitted (``context["kind"] ==
            "missing"``), or was supplied but is empty or whitespace-only
            (``context["kind"] == "invalid"``, raised from
            ``ModelVersion``'s field validator); or ``criteria`` was
            supplied but is empty or whitespace-only (raised from
            ``ScoringCriteria``'s field validator).
        """
        if model_version is None:
            raise InvalidParameterError(
                "model_version is required to pin measurement stability",
                context={
                    "parameter": "model_version",
                    "constraint": MODEL_VERSION_CONSTRAINT,
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
        return cls(
            model_version=ModelVersion(value=model_version),
            provider=provider,
            criteria=ScoringCriteria(value=criteria) if criteria is not None else None,
        )

    def score(
        self,
        agent_output: str,
        *,
        agent_input: str | None = None,
        criteria: str | None = None,
    ) -> ScoringResult:
        """Score an agent output and return a structured, provenanced result.

        Orchestration, per ADR-006 section 2:

        1. Raise ``MissingPrerequisiteError`` (``context["prerequisite"] ==
           "judge_provider"``, ``context["operation"] == "score"``) if
           ``self.provider`` is ``None``, before doing anything else.
        2. Resolve effective criteria: ``criteria`` (this call) if given,
           else ``self.criteria`` (judge-level) if set, else raise
           ``MissingPrerequisiteError`` (``context["prerequisite"] ==
           "scoring_criteria"``, ``context["operation"] == "score"``) --
           in both cases before the provider is ever called.
        3. Reject an empty or whitespace-only ``agent_output`` with
           ``InvalidParameterError`` (``context["parameter"] ==
           "agent_output"``, ``context["kind"] == "invalid"``) -- ADR-006
           section 6.
        4. Call ``self.provider.score(...)``, letting ``ProviderError``,
           ``MalformedResponseError`` and ``JudgeRefusalError`` propagate
           unchanged.
        5. Assemble and return a ``ScoringResult`` whose ``provenance`` is
           built from ``self.model_version`` and the resolved
           ``ScoringCriteria`` (ADR-006 section 7).

        Parameters
        ----------
        agent_output
            The agent output to score. Required; must be non-empty and not
            whitespace-only.
        agent_input
            The agent input that produced ``agent_output``, when
            available. Not validated for emptiness, not carried onto
            ``Provenance`` or ``ScoringResult`` (ADR-006 section 3).
        criteria
            Criteria to use for this call only, overriding
            ``self.criteria`` without mutating it (ADR-006 section 2,
            resolving BIN-58 OQ-3).

        Returns
        -------
        ScoringResult
            The structured, immutable scoring result.

        Raises
        ------
        MissingPrerequisiteError
            No provider is configured, or no criteria are resolvable from
            either this call or the judge.
        InvalidParameterError
            ``agent_output`` is empty or whitespace-only.
        ProviderError
            The provider's call failed.
        MalformedResponseError
            The provider's response could not be interpreted.
        JudgeRefusalError
            The provider declined to score.
        """
        if self.provider is None:
            raise MissingPrerequisiteError(
                "scoring requires a configured judge provider",
                context={"prerequisite": "judge_provider", "operation": "score"},
                recovery_hint="Pass provider=... to Judge.create().",
            )

        effective_criteria = self._resolve_effective_criteria(criteria)
        _require_non_blank_agent_output(agent_output)

        response = self.provider.score(
            model_version=self.model_version.value,
            criteria=effective_criteria.value,
            agent_output=agent_output,
            agent_input=agent_input,
        )

        return ScoringResult(
            score=response.score,
            reasoning=response.reasoning,
            provenance=Provenance(
                model_version=self.model_version,
                scoring_criteria=effective_criteria,
            ),
        )

    def _resolve_effective_criteria(self, criteria: str | None) -> ScoringCriteria:
        """Resolve per-call criteria over judge-level criteria, or raise.

        Extracted from ``score()`` to keep that method under the house
        style's ~40-line guideline (`coding-standards/references/python.md`
        Pre-Submit Checklist) -- pure refactor, no behaviour change.

        Parameters
        ----------
        criteria
            Per-call criteria text, or ``None`` to fall back to
            ``self.criteria``.

        Returns
        -------
        ScoringCriteria
            The resolved, validated criteria.

        Raises
        ------
        MissingPrerequisiteError
            Neither per-call nor judge-level criteria are available.
        """
        effective_criteria_raw = (
            criteria
            if criteria is not None
            else (self.criteria.value if self.criteria is not None else None)
        )
        if effective_criteria_raw is None:
            raise MissingPrerequisiteError(
                "scoring requires criteria",
                context={"prerequisite": "scoring_criteria", "operation": "score"},
                recovery_hint="Pass criteria=... to Judge.create() or to score().",
            )
        return ScoringCriteria(value=effective_criteria_raw)


def _require_non_blank_agent_output(agent_output: str) -> None:
    """Reject an empty or whitespace-only ``agent_output`` (ADR-006 section 6).

    Extracted from ``Judge.score()`` to keep that method under the house
    style's ~40-line guideline -- pure refactor, no behaviour change. A
    module-level function, not a method: it does not touch ``self``.

    Raises
    ------
    InvalidParameterError
        ``agent_output`` is empty or whitespace-only.
    """
    if agent_output.strip() == "":
        raise InvalidParameterError(
            "agent_output must be a non-empty, non-whitespace string",
            context={
                "parameter": "agent_output",
                "constraint": AGENT_OUTPUT_CONSTRAINT,
                "kind": "invalid",
                "provided": agent_output,
            },
            recovery_hint=(
                "Pass the agent's actual output text. If the agent "
                "genuinely produced no response, pass a caller-defined "
                "sentinel string (e.g. '[no response]') instead of an "
                "empty string."
            ),
        )
