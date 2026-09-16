"""Pin the commit-message format gate installed by BIN-89.

The checker is the only thing standing between the project's stated commit
convention and prose, so a defect here is either a broken gate or -- worse --
a rejected commit someone has to fight. Both directions are tested.

⚠️ **The historical corpus is pinned as literals rather than read from
``git log``.** ``actions/checkout`` clones to depth 1, so a test that walked
real history would pass vacuously in CI while appearing to assert something
substantial. That is the vacuity shape recorded in ``CLAUDE.md`` -- a test
that passes for the wrong reason is worse than no test, because it is counted.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_commit_message.py"


def _load() -> ModuleType:
    """Import the checker from ``scripts/``, which is not an installed package."""
    spec = importlib.util.spec_from_file_location("check_commit_message", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_commit_message = _load()


# Real subjects from this repository's history. Every one of these was written
# before the gate existed, so they are evidence about the convention rather
# than examples invented to match the regex.
HISTORICAL_SUBJECTS = [
    "📝 docs: lead the install instructions with uv",
    "👷 ci: run CodeQL's security-extended suite, not security-and-quality",
    "♻️ refactor(baseline): hoist _has_zero_variance into the numerical layer",
    "🐛 fix(baseline,monitoring): stop four non-CaliperError leaks from the API",
    "✅ test: BIN-128 — enforce five project invariants structurally",
    "✨ feat(measurement): add ScoringCriteria",
    "🔖 chore: release 0.1.0a1",
    ":arrow_up: chore(deps): Bump mutmut in the dev-toolchain group",
]


@pytest.mark.parametrize("subject", HISTORICAL_SUBJECTS)
def test_accepts_subjects_this_project_has_actually_written(subject: str) -> None:
    """The gate must not reject the convention it was derived from."""
    assert check_commit_message.is_valid(subject)


def test_accepts_a_comma_separated_scope() -> None:
    """Multi-scope commits are real here -- ``fix(baseline,monitoring):`` x3.

    A regex allowing only a single ``[a-z-]+`` scope is the tempting simpler
    form, and it would reject commits already on ``trunk``. This test fails
    that fix.
    """
    assert check_commit_message.is_valid("🐛 fix(baseline,monitoring): guard access")


def test_accepts_a_subject_longer_than_seventy_two_characters() -> None:
    """Subject length is deliberately unconstrained.

    The longest subject in this history is 126 characters. Conventional
    Commits suggests ~72; adding that limit is the tempting wrong fix, and it
    would reject the project's own prevailing style.
    """
    subject = "📝 docs: " + "a" * 200
    assert check_commit_message.is_valid(subject)


def test_accepts_a_breaking_change_marker() -> None:
    """``!`` before the colon is Conventional Commits' breaking-change marker."""
    assert check_commit_message.is_valid("💥 feat(api)!: drop the acknowledge flag")


def test_accepts_a_composed_emoji_carrying_a_variation_selector() -> None:
    """``♻️`` is U+267B *followed by* U+FE0F, and appears nine times in history.

    A character class covering only the pictographic planes (U+1F300+) misses
    it, because U+267B sits in the much older Miscellaneous Symbols block.
    """
    assert "️" in "♻️"
    assert check_commit_message.is_valid("♻️ refactor: extract the value object")


def test_accepts_the_gitmoji_shortcode_form_dependabot_writes() -> None:
    """Dependabot's messages are not ours to format, and it writes shortcodes."""
    assert check_commit_message.is_valid(":arrow_up: chore(deps): Bump ruff")


@pytest.mark.parametrize(
    ("subject", "why"),
    [
        ("fix: drop the flag", "no gitmoji"),
        ("🐛 Normalise scores before hashing", "gitmoji but no conventional type"),
        ("🐛 fixed(baseline): a typo'd type", "unknown type"),
        ("🐛 fix(baseline) missing the colon", "no colon"),
        ("🐛 fix:", "no description"),
        ("🐛 fix: ", "whitespace-only description"),
        ("", "empty subject"),
    ],
)
def test_rejects_malformed_subjects(subject: str, why: str) -> None:
    """Each rejected shape is a distinct way the convention can be missed."""
    assert not check_commit_message.is_valid(subject), why


@pytest.mark.parametrize(
    "subject",
    [
        "Merge pull request #33 from binary-glide/feat/BIN-68/provenance",
        "Merge branch 'trunk' into feat/BIN-89/pre-commit",
        'Revert "🐛 fix(baseline): guard duck-typed attribute access"',
        "fixup! 📝 docs: lead the install instructions with uv",
        "squash! ✅ test: pin the exception contract",
    ],
)
def test_exempts_subjects_git_generates_rather_than_ones_we_write(
    subject: str,
) -> None:
    """Rejecting these would break ``git merge``, ``revert`` and rebase."""
    assert check_commit_message.check(subject) is None


def test_ignores_the_comment_block_git_appends_to_the_template() -> None:
    """The subject is the first non-comment line, not the first line."""
    message = (
        "# Please enter the commit message for your changes.\n"
        "# On branch trunk\n"
        "\n"
        "📝 docs: explain the hook\n"
        "\n"
        "Body text.\n"
    )
    assert check_commit_message.subject_of(message) == "📝 docs: explain the hook"
    assert check_commit_message.check(message) is None


def test_an_entirely_empty_message_is_not_a_format_error() -> None:
    """git aborts an empty commit itself; a format error here would mislead."""
    assert check_commit_message.check("\n# only comments\n") is None


def test_failure_message_names_the_offending_subject_and_the_legal_types() -> None:
    """Errors are UX -- the message must say what to do, not merely refuse."""
    error = check_commit_message.check("🐛 Normalise scores before hashing")
    assert error is not None
    assert "🐛 Normalise scores before hashing" in error
    for conventional_type in check_commit_message.TYPES:
        assert conventional_type in error
