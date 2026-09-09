"""Domain factories for the Measurement bounded context.

``factory_boy`` factories for the value objects in ``caliper.measurement``,
per ``test-patterns/references/python.md`` ("Fixtures and Factories"). Each
factory builds a *valid* instance by default -- these are for tests that
need "a Judge" or "some ScoringCriteria" as supporting setup, not for tests
that exercise a specific boundary or invalid-input case.

Do NOT use these factories for boundary-value or equivalence-partition
tests (empty string, whitespace-only, non-finite score, missing
prerequisite, and so on). Those tests must construct the value object
directly with the exact literal under test -- ``ModelVersion(value="")``,
not ``ModelVersionFactory(value="")`` -- so the assertion traces back to a
value the reader can see at the call site, not one buried in a factory
default. Factories exist to remove *incidental* setup noise, never to
obscure the value that makes a test meaningful.

``FakeJudgeProviderPort`` (``tests/support/fakes.py``) is deliberately not
wrapped in a factory here: it is test infrastructure, not a domain value
object, and its two meaningful configurations (a fixed response, or an
error to raise) are exactly what each test needs to state explicitly.

Not yet imported by any test (BIN-103). Every current unit test pins one
numbered acceptance scenario (``SC1``, ``SC2``, ...) from a merged feature
file and therefore intentionally uses a literal, reader-visible value even
in its "happy path" case -- there is no current test that needs "a Judge"
without caring which one. The natural adoption point is BIN-63 (Phase I
baseline collection), which will accumulate many value-object instances
where the specific value genuinely does not matter. This module exists now
so that story does not repeat the "no tests/factories.py" gap this ticket
fixed.
"""

from __future__ import annotations

import factory

from caliper.measurement import (
    Judge,
    ModelVersion,
    Provenance,
    ScoringCriteria,
    ScoringResult,
)
from tests.support.fakes import FakeJudgeProviderPort


class ModelVersionFactory(factory.Factory):
    """Builds a valid, unique ``ModelVersion``."""

    class Meta:
        """factory_boy configuration."""

        model = ModelVersion

    value = factory.Sequence(lambda n: f"claude-sonnet-4-5-factory-{n}")


class ScoringCriteriaFactory(factory.Factory):
    """Builds a valid ``ScoringCriteria`` with a plausible rubric sentence."""

    class Meta:
        """factory_boy configuration."""

        model = ScoringCriteria

    value = factory.Faker("sentence", nb_words=8)


class ProvenanceFactory(factory.Factory):
    """Builds a valid ``Provenance`` from a fresh model version and criteria."""

    class Meta:
        """factory_boy configuration."""

        model = Provenance

    model_version = factory.SubFactory(ModelVersionFactory)
    scoring_criteria = factory.SubFactory(ScoringCriteriaFactory)


class ScoringResultFactory(factory.Factory):
    """Builds a valid ``ScoringResult`` with a finite score in ``[0, 1]``."""

    class Meta:
        """factory_boy configuration."""

        model = ScoringResult

    score = factory.Faker("pyfloat", min_value=0.0, max_value=1.0)
    reasoning = factory.Faker("sentence")
    provenance = factory.SubFactory(ProvenanceFactory)


class JudgeFactory(factory.Factory):
    """Builds a fully configured, ready-to-score ``Judge``.

    ``provider`` defaults to a fresh ``FakeJudgeProviderPort`` with no
    response or error configured -- callers that intend to call
    ``.score()`` must still set ``judge.provider.response`` (or
    ``error_to_raise``) before doing so, since a Judge factory cannot know
    what a given test wants the provider to return.
    """

    class Meta:
        """factory_boy configuration."""

        model = Judge

    model_version = factory.SubFactory(ModelVersionFactory)
    provider = factory.LazyFunction(FakeJudgeProviderPort)
    criteria = factory.SubFactory(ScoringCriteriaFactory)
