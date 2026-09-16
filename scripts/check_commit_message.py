"""Validate a commit message subject against this project's format (BIN-89).

The format is **Gitmoji + Conventional Commits**, a global standard in
``~/.claude/CLAUDE.md`` that until now existed only as prose. This script is
what turns it into a gate.

    <gitmoji> <type>[(<scope>)][!]: <description>

    📝 docs: lead the install instructions with uv
    ♻️ refactor(baseline): hoist _has_zero_variance into the numerical layer
    🐛 fix(baseline,monitoring): stop four non-CaliperError leaks

⚠️ **The accepted set was derived from this repository's own history, not from
the Gitmoji specification.** Every emoji and every type below appears in
``git log``; the type list is the Conventional Commits standard set, which is a
superset of the seven actually in use (``test``, ``docs``, ``feat``, ``chore``,
``fix``, ``refactor``, ``ci``). Two findings from that survey shaped the rules:

* **Scopes are comma-separated in practice** -- ``fix(baseline,monitoring):``
  appears three times. A regex allowing a single ``[a-z-]+`` scope would have
  rejected commits already on ``trunk``.
* **Subject length is not constrained.** The longest subject in history is 126
  characters. Conventional Commits suggests ~72; this project clearly prefers a
  descriptive subject, and no standard it follows mandates a limit. Enforcing
  one would reject the project's own style, so this script does not.

🚨 **What this cannot reach.** ``trunk``'s history is built from GitHub
squash merges, whose subject is the *pull request title* -- typed on the web,
never passing through a local ``commit-msg`` hook. Six such subjects carry a
gitmoji but no conventional type. This script governs local commits only; the
gap is real and is recorded on BIN-89 rather than papered over.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Conventional Commits' standard type set. A superset of the seven this
# repository uses -- the unused four are accepted rather than reserved, so
# that the first legitimate `perf:` commit is not rejected by an oversight.
TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)

# Emoji codepoint ranges, broad rather than an enumerated Gitmoji list: an
# enumeration needs maintenance every time Gitmoji adds an entry, and the
# failure mode is rejecting a valid commit. U+FE0F (variation selector) and
# U+200D (zero-width joiner) are included because composed emoji need them --
# `♻️` is U+267B followed by U+FE0F, and appears nine times in this history.
_EMOJI_RANGES = (
    "←-⇿"  # arrows
    "⌀-⏿"  # miscellaneous technical
    "■-➿"  # geometric shapes, misc symbols, dingbats (✅ ✨ ♻)
    "⤴-⤵"
    "⬀-⯿"  # misc symbols and arrows (⬆)
    "〰〽㊗㊙"
    "️‍"  # variation selector, zero-width joiner
    "\U0001f000-\U0001faff"  # the main pictographic planes
)

# Either a literal emoji or a `:shortcode:`. Dependabot writes the shortcode
# form (`:arrow_up: chore(deps): ...`) and we do not control its messages.
_GITMOJI = f"(?:[{_EMOJI_RANGES}]+|:[a-z0-9_+-]+:)"

_SCOPE = r"(?:\([a-z0-9][a-z0-9,._ /-]*\))?"

SUBJECT_PATTERN = re.compile(f"^{_GITMOJI} (?:{'|'.join(TYPES)}){_SCOPE}!?: \\S.*$")

# Subjects git itself generates, or that mark a message as provisional. None
# of these is ours to format, and rejecting them would break `git merge`,
# `git revert` and interactive rebase.
EXEMPT_PREFIXES = (
    "Merge ",
    "Revert ",
    "fixup!",
    "squash!",
    "amend!",
)

_FAILURE_MESSAGE = """
✖ Commit message rejected -- subject does not match the project format.

  your subject: {subject}

  expected:     <gitmoji> <type>[(<scope>)]: <description>

  examples:     📝 docs: lead the install instructions with uv
                🐛 fix(baseline): reject a non-finite control limit
                ✅ test(monitoring): pin absorb-but-surface delivery

  types:        {types}

The gitmoji comes first and a conventional type is required -- a bare
"🐛 Fixed the thing" is rejected. Scopes may be comma-separated.

Gitmoji reference: https://gitmoji.dev
"""


def subject_of(message: str) -> str | None:
    """Return the subject line of a raw commit message, or None if empty.

    Skips the comment lines git appends to the message template, including
    everything after a ``--verbose`` scissors line, since those are stripped
    before the message is stored and must not be mistaken for the subject.
    """
    for line in message.splitlines():
        if line.startswith("#"):
            continue
        if line.strip():
            return line.rstrip()
    return None


def is_exempt(subject: str) -> bool:
    """Return whether the subject is one git generates rather than one we write."""
    return subject.startswith(EXEMPT_PREFIXES)


def is_valid(subject: str) -> bool:
    """Return whether the subject satisfies the project's commit format."""
    return SUBJECT_PATTERN.match(subject) is not None


def check(message: str) -> str | None:
    """Return an error message for a bad commit message, or None if it passes.

    An empty message returns None: git aborts an empty commit itself, and
    duplicating that here would report a confusing format error instead.
    """
    subject = subject_of(message)
    if subject is None:
        return None
    if is_exempt(subject) or is_valid(subject):
        return None
    return _FAILURE_MESSAGE.format(subject=subject, types=", ".join(TYPES))


def main(argv: list[str]) -> int:
    """Check the commit message file named by ``argv[1]``; return an exit code."""
    if len(argv) < 2:
        print("usage: check_commit_message.py <commit-msg-file>", file=sys.stderr)
        return 2
    error = check(Path(argv[1]).read_text(encoding="utf-8"))
    if error is None:
        return 0
    print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
