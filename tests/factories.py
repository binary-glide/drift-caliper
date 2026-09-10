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

First imported by BIN-63 (``tests/unit/baseline/test_baseline.py``), the
adoption point this module's original docstring predicted -- Phase I
baseline tests accumulate many value-object instances where the specific
value genuinely does not matter.

**Why every factory below declares a ``TYPE_CHECKING``-only ``__new__``:**
``factory.Factory``'s real ``__new__``/``_create`` builds and returns an
instance of ``Meta.model`` at runtime, but neither mypy nor ty can see that
-- statically, ``SomeFactory()`` types as ``SomeFactory`` (the factory
class itself), not the model it builds. That is invisible until a caller
outside this module chains an attribute off the result (e.g.
``ScoringResultFactory().provenance.model_version``), which resolves
against the factory's own class-level attribute declarations (a
``SubFactory``/``Faker`` descriptor) instead of the model's field --
first hit by BIN-63, the first story to call these factories from another
module. The ``if TYPE_CHECKING: def __new__(...)`` stub below is inert at
runtime (real construction still goes through factory_boy's metaclass) and
tells both checkers the true return type in the one place it should live,
rather than scattering ``# type: ignore`` / ``# ty: ignore`` across every
call site. Verified against this project's exact toolchain (mypy strict,
ty 0.0.79) before adopting -- see the BIN-63 backend-test-writer session
summary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

    if TYPE_CHECKING:

        def __new__(cls, *args: Any, **kwargs: Any) -> ModelVersion: ...


class ScoringCriteriaFactory(factory.Factory):
    """Builds a valid ``ScoringCriteria`` with a plausible rubric sentence."""

    class Meta:
        """factory_boy configuration."""

        model = ScoringCriteria

    value = factory.Faker("sentence", nb_words=8)

    if TYPE_CHECKING:

        def __new__(cls, *args: Any, **kwargs: Any) -> ScoringCriteria: ...


class ProvenanceFactory(factory.Factory):
    """Builds a valid ``Provenance`` from a fresh model version and criteria."""

    class Meta:
        """factory_boy configuration."""

        model = Provenance

    model_version = factory.SubFactory(ModelVersionFactory)
    scoring_criteria = factory.SubFactory(ScoringCriteriaFactory)

    if TYPE_CHECKING:

        def __new__(cls, *args: Any, **kwargs: Any) -> Provenance: ...


class ScoringResultFactory(factory.Factory):
    """Builds a valid ``ScoringResult`` with a finite score in ``[0, 1]``."""

    class Meta:
        """factory_boy configuration."""

        model = ScoringResult

    score = factory.Faker("pyfloat", min_value=0.0, max_value=1.0)
    reasoning = factory.Faker("sentence")
    provenance = factory.SubFactory(ProvenanceFactory)

    if TYPE_CHECKING:

        def __new__(cls, *args: Any, **kwargs: Any) -> ScoringResult: ...


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

    if TYPE_CHECKING:

        def __new__(cls, *args: Any, **kwargs: Any) -> Judge: ...
