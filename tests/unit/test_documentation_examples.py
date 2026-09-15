"""The documented examples must actually run (BIN-86).

``brand.md`` § Writing for Two Readers makes this a rule rather than an
aspiration: *"Every example is complete and runnable. No ``...``, no 'assume
you have a baseline', no fragments. A human tolerates elision; an agent copies
it, or invents what fills it."*

Prose cannot enforce that. This module extracts the complete programmes from
``README.md`` and ``docs/quickstart.md`` and executes them, so an API change
that silently invalidates the first code a prospective user reads fails the
build instead of shipping.

⚠️ This is not hypothetical. Writing these pages, a draft printed
``fitted.target_arl``; the real attribute is ``requested_arl``. It was caught
by running the example, and would not have been caught by reading it -- the
wrong name is entirely plausible, which is exactly what makes it the failure
mode worth guarding.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The full programmes are identified by the class they define rather than by
# position, so reordering a page or adding a snippet above them does not
# silently start testing a different block.
_SENTINEL = "class StubProvider"

_DOCUMENTS = (
    _REPO_ROOT / "README.md",
    _REPO_ROOT / "docs" / "quickstart.md",
)


def _extract_runnable_programme(document: Path) -> str:
    """Return the one self-contained Python programme in ``document``."""
    blocks: list[str] = re.findall(
        r"```python\n(.*?)```", document.read_text(), re.DOTALL
    )
    programmes = [block for block in blocks if _SENTINEL in block]
    assert len(programmes) == 1, (
        f"{document.name} should contain exactly one complete programme "
        f"(identified by {_SENTINEL!r}), found {len(programmes)}"
    )
    return programmes[0]


@pytest.mark.parametrize("document", _DOCUMENTS, ids=lambda p: p.name)
def test_documented_programme_runs(document: Path) -> None:
    """The programme published in ``document`` executes without raising."""
    programme = _extract_runnable_programme(document)

    # Seeded here rather than in the published example: a reader running it
    # should see their own draw, but a test that sometimes detects the shift
    # and sometimes does not is worse than no test. The shift the examples
    # apply is 3 sigma, so detection is near-certain either way -- the seed
    # removes the remaining "near".
    random.seed(20260915)

    namespace: dict[str, object] = {"__name__": "__doc_example__"}
    exec(compile(programme, str(document), "exec"), namespace)  # noqa: S102


@pytest.mark.parametrize("document", _DOCUMENTS, ids=lambda p: p.name)
def test_documented_programme_imports_only_public_names(document: Path) -> None:
    """Examples import from ``drift_caliper`` directly, never a deep path.

    A deep import in published documentation teaches every reader -- and every
    agent trained on it -- a path this project treats as private and reserves
    the right to move.
    """
    programme = _extract_runnable_programme(document)
    deep_imports = re.findall(r"^from\s+(drift_caliper\.\S+)\s+import", programme, re.M)
    assert not deep_imports, (
        f"{document.name} imports from private paths: {deep_imports}. "
        f"Import from `drift_caliper` itself."
    )
