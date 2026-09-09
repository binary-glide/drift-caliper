# ADR-008: Error assertions use type and context, never message text

**Status:** Accepted
**Date:** 2026-09-09
**Deciders:** ratified by product owner (BIN-103)
**Refs:** BIN-103, BIN-57, BIN-58, BIN-59, ADR-002, `test-patterns/references/python.md`

## Context

`test-patterns/references/python.md` §"Testing Pydantic Validation" is explicit:

```python
def test_rejects_blank_name():
    with pytest.raises(ValidationError) as exc_info:
        CreateMarketRequest(name="   ", ...)
    errors = exc_info.value.errors()
    assert any("name must not be blank" in e["msg"] for e in errors)
```

> "Test validation at the boundary, not just the happy path. **Assert on the
> actual error messages users will see.**"

ADR-002 requires the opposite: assertions on `isinstance` plus required
`context` key presence, and **never** on message text. `recovery_hint` is
human-facing and deliberately untested.

Both cannot hold. This ADR records which governs and why, so the departure
reads as considered rather than as an oversight — and so nobody "fixes" 80
tests into a pattern this project has already rejected twice.

## Decision

**ADR-002 governs. Caliper's tests never assert on exception message text.**

Three reasons, in order of weight.

### 1. The standard's example is a different situation

`CreateMarketRequest` is a FastAPI request schema. Its validation error is
serialised into an HTTP 422 response body, so **the message genuinely is the
user-facing contract** — a client parses it, a frontend displays it, and
changing the wording changes what a consumer sees. Asserting on it is correct
there.

Caliper has no HTTP boundary and never will. Its user-facing contract is the
typed exception and its `context` mapping: an engineer writes
`except InvalidParameterError` and branches on `error.context["kind"]`. The
message is for a human reading a traceback. Testing it would pin something no
consumer programs against, while leaving the thing they *do* program against
no better tested.

### 2. This project already rejected message assertions, twice

`requirements-reviewer` failed the acceptance criterion *"the error message
includes an example of correct usage"* as untestable on **BIN-57**, and again
on **BIN-58** after it was reworded. BIN-59 replaced it with programmatic
classifiability — assert on error type or category, not message substrings —
and the reviewer confirmed that genuinely resolved the problem rather than
relocating it.

That finding is upstream of six merged, human-approved feature files. Reversing
it would reopen a question closed by review, not merely change a test style.

### 3. It would make wording a breaking change

With message text asserted, improving an error message breaks tests, and
improving it in a release breaks consumers who copied our assertions. ADR-002
keeps `recovery_hint` explicitly untested precisely so it can be improved
freely — it is the field most likely to be reworded as real users hit real
failures.

## Consequence for mutation testing, which is not obvious

`mutmut` reports **97–99 of 147 mutants killed** — around 66%, below the
standard's 80% target. Every surviving mutant was inspected individually, twice
and independently: **all of them mutate exception message strings or
`recovery_hint` text.** Zero survivors touch a `context[...]` key, a `kind`
discriminator, a comparison, or a branch.

So the raw score is misleading here, and predictably so: mutmut's 80% target
implicitly assumes message text is part of the tested contract, exactly as the
standard's Pydantic section does. Under this ADR it is not.

**The structurally meaningful mutation score is 100%.** Read the raw number
with that in mind, and do not "fix" it by asserting on strings — that would
raise the number by reintroducing the brittleness this ADR exists to prevent.

If a future change makes the raw score fall for any *other* reason, that is a
real signal. Check what the survivors touch before concluding anything.

## What this does not change

Everything else in `test-patterns` applies in full: factories, AAA structure,
naming, fixtures, coverage, `parametrize`, property-based testing, and mutation
testing itself. This is a narrow departure on one point, not a licence to treat
the standard as advisory.

Validation is still tested at the boundary, as the standard demands — through
type and structured context rather than through prose.

## Reversibility

**Low cost mechanically, high cost in review.** The assertions are localised
and could be rewritten. But reversing this would contradict two
`requirements-reviewer` findings and require re-approving six feature files, so
it should not be revisited without the product owner and a specific reason.

The situation that would justify revisiting: Caliper growing a surface where a
message genuinely becomes the machine-readable contract — a CLI with parsed
output, or a serialised error format for an OpenTelemetry exporter. Neither is
in scope.

## Alternatives considered

### Follow `test-patterns` and assert on message text

Rejected on all three grounds above.

### Assert on both — context keys plus one message check per error type

Considered seriously, since it appears to honour both documents. Rejected:
it reintroduces the brittleness in miniature while adding tests, and it gives
the false impression that message wording is a supported contract when the
library intends to keep improving it. Half a breaking change is still a
breaking change.

### Make `recovery_hint` a structured field instead of prose

Rejected as scope creep here, though it is not a bad idea. It would make the
guidance machine-readable and therefore assertable without brittleness. If a
consumer ever needs to render recovery guidance programmatically, that is the
story to write — and it would supersede part of this ADR rather than
contradict it.
