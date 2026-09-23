"""Every committed ``.feature`` file must be valid Gherkin.

**pytest-bdd parses a feature file only when a test module binds to it.** A
feature file committed ahead of its step definitions is therefore never
parsed, and can sit in the repository invalid until the first test tries to
bind -- at which point the defect surfaces in someone else's work.

That happened. A reviewed, approved feature file of 17 scenarios wrapped each
long step across several physical lines. The Gherkin parser rejects every
continuation line; nothing bound to the file, so nothing parsed it. It passed
the scenario writer's gates, two requirements reviews and three independent
content checks, and was found only when step definitions were written.
Reading could not have caught it -- the wrapping looks like ordinary prose
formatting -- which is why this is a test and not a rule someone remembers.

The parser is the one pytest-bdd itself uses, so a file this test accepts is
one pytest-bdd can load.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gherkin.errors import CompositeParserException, ParserException
from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner

_FEATURES = Path(__file__).resolve().parents[1] / "bdd" / "features"


def _feature_files() -> list[Path]:
    return sorted(_FEATURES.rglob("*.feature"))


def _parse_error(text: str) -> str | None:
    """Return the parser's error for ``text``, or None if it is valid Gherkin."""
    try:
        # gherkin is unannotated; this is the only call into it.
        Parser().parse(TokenScanner(text))  # type: ignore[no-untyped-call]
    except (CompositeParserException, ParserException) as error:
        return str(error)
    return None


def test_every_feature_file_is_valid_gherkin() -> None:
    failures = {
        str(path.relative_to(_FEATURES)): error
        for path in _feature_files()
        if (error := _parse_error(path.read_text(encoding="utf-8"))) is not None
    }

    assert not failures, "unparseable feature files -- " + "; ".join(
        f"{name}: {error.splitlines()[0]}" for name, error in failures.items()
    )


def test_the_scan_reaches_the_feature_files() -> None:
    """The rule above scans a populated tree, so a green run means something.

    Without this, a wrong ``_FEATURES`` path would make the rule pass forever
    -- the vacuity shape this project keeps hitting.
    """
    files = _feature_files()

    assert len(files) > 5, (
        f"only {len(files)} feature files found under {_FEATURES} -- the scan "
        "is looking in the wrong place"
    )


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "Feature: f\n  Scenario: s\n    Given a step that wraps\n"
            "      onto a second physical line\n",
            id="step wrapped across two lines",
        ),
        pytest.param(
            "Feature: f\n  Scenario: s\n    Given a step\n    Whereupon nonsense\n",
            id="line with no step keyword",
        ),
    ],
)
def test_the_parser_rejects_the_defects_this_guards_against(text: str) -> None:
    """The guard has power: the exact shape that slipped through is refused.

    Pinned here rather than demonstrated once, so the guard cannot silently
    stop detecting it -- for instance if a parser upgrade began accepting
    continuation lines.
    """
    assert _parse_error(text) is not None


def test_the_parser_accepts_a_valid_feature() -> None:
    """Counterpart to the above, so a parser that rejects everything cannot pass."""
    text = "Feature: f\n  Scenario: s\n    Given a step\n    Then a result\n"

    assert _parse_error(text) is None
