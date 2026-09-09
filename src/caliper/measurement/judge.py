"""The Judge -- an immutable configured adapter pinned to a model version.

See ``docs/domain-model.md`` (Judge -- immutable configured adapter) and
ADR-002 for the error contract enforced at creation.

Implementation note (BIN-57 domain-implementer): this module currently
scaffolds the public shape only, so that
``tests/unit/measurement/test_judge.py`` and
``tests/bdd/test_judge_adapter_pinned_model_version.py`` can import and run.
``Judge.create`` raises ``NotImplementedError`` until validation and
construction land.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelVersion:
    """A pinned, non-empty model version string.

    Preserved exactly as provided, including any surrounding whitespace.
    Equality follows the wrapped ``value`` (dataclass value equality).
    """

    value: str


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
            InvalidParameterError: ``model_version`` was omitted, empty,
                or whitespace-only.
        """
        raise NotImplementedError
