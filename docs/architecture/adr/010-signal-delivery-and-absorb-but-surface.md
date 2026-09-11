# ADR-010: Signal delivery, `MonitoringResult` extension, and absorb-but-surface

**Status:** Accepted
**Date:** 2026-09-11
**Deciders:** system-architect (combined pass, BIN-75 + BIN-76), ratified by product owner (OQ-1, "absorb, but surface", 2026-09-11)
**Refs:** BIN-75, BIN-76, ADR-001, ADR-002, ADR-004, ADR-008, ADR-009

## Context

Both `requirements-reviewer` runs (BIN-75, BIN-76, 2026-09-11) independently recommended
resolving these two stories together — BIN-76 consumes what BIN-75 defines (the signal
content and the receiver-attachment mechanism), and both share the same settled-but-not-fully-
shaped policy ("absorb, but surface", OQ-1). Treating them as two separate architecture passes
would risk designing the receiver surface once for BIN-75 and finding it does not fit BIN-76's
own failure case. ADR-009 resolved BIN-69/BIN-72 the same way, for the same reason; this ADR
follows that precedent.

E4 ("Detect and Respond to Drift" delivery chain) is the last unmodelled half of "Signal"
(`docs/domain-model.md`, Glossary — Signal: *"The determination itself is now modelled
(ADR-009, BIN-69); its delivery ... is E4 ... which still has no written requirements and
remains unmodelled."*). This ADR is where that becomes specified, for R1's two walking-skeleton
stories only (BIN-77 through BIN-82 are Release 2 and are not designed here).

### What already exists and must not be contradicted

- **`MonitoringResult`** (ADR-009 §4) currently carries `is_in_control: bool`,
  `observation: ScoringResult`, `chart_type: str` — nothing else. `__bool__` raises `TypeError`
  (ADR-009 §4, domain-modeller's delegated decision).
- **`Monitor.record()`** (ADR-009 §§1–3) is a synchronous call-and-return. It checks provenance
  internally, raises `InvalidObservationError`/`ProvenanceMismatchError` for the two precondition
  violations, and otherwise never raises — a signal is a normal return value (BR-7, "signals are
  not errors", ratified project-wide).
- **No receiver/callback/handler concept exists anywhere in this codebase.** Confirmed
  independently by both `requirements-reviewer` runs against `src/caliper/monitoring/domain/
  monitor.py`'s actual `__init__`/`record()` signatures.
- **`FittedControlLimits`** (ADR-004) is a `@runtime_checkable Protocol`. Detection boundaries
  are deliberately chart-specific, not shared (ADR-004 §3) — EWMA/Shewhart use `ucl`/`lcl`/`cl`
  on the observation scale; CUSUM uses `decision_interval` (*h*) against an accumulating
  statistic, explicitly *not* on the observation scale. Any new field this ADR adds must not
  re-flatten that distinction.
- **ADR-009 §8 precedent, cited by both PRDs directly:** *"concrete-only in R1, but the public
  surface names no internal type, so a port stays additive."* Both PRDs recommend this pattern
  apply to the receiver surface — evaluated below, in Decision §3.
- **BIN-110's truthiness rule:** any new yes/no-shaped field needs an explicit field, not
  reliance on Python's default object truthiness. `delivery_failures` below is a container
  (naturally falsy when empty via `__len__`, not a custom `__bool__`), which is the same
  pattern `Baseline` already uses safely — not a truthiness trap.
- **ADR-002/ADR-008:** typed errors, structured `context`, `isinstance` + key-presence
  assertions, never message text. A receiver's own exception is arbitrary third-party code, not
  necessarily a `CaliperError` — this ADR does not require it to be one (see Decision §2).
- **Sentry context:** not applicable — Caliper is a library with no runtime to monitor.

## Decision

### 1. WHERE a delivery failure surfaces: an in-band field on the returned `MonitoringResult`

**`MonitoringResult` gains `delivery_failures: tuple[DeliveryFailure, ...] = ()`.** Empty when
every receiver succeeded (or none were configured); one entry per receiver that raised during
this `record()` call.

```python
class DeliveryFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    receiver: str        # identifies which receiver failed (repr/qualname)
    error_type: str      # type(exc).__name__ -- the "why", machine-branchable
    error_message: str   # str(exc) -- human-readable detail
```

⚠️ **Amended 2026-09-11 (`BIN-118`): `repr()` and `str()` are themselves
hazardous and must be guarded.** A receiver whose `__repr__` raises (a closed
file, a detached ORM session), or a custom exception with a broken `__str__`,
would let that *second* exception escape `record()` — absorbing the receiver's
failure and then propagating its description defeats the whole decision. The
two fields above are therefore populated by `_describe_receiver()` and
`_describe_exception()`, each wrapping exactly one hazardous call with a
fallback: `repr(receiver)` falls back to `type(receiver).__name__` then to a
constant; `str(exc)` falls back to `type(exc).__name__`.

`error_type` needs no guard — `type(exc).__name__` reads a class attribute and
never executes caller code. **Only `repr()` and `str()` are hazardous.** The
fallbacks must never become a route to receiver-supplied content; section 1's
rule that failure content comes from the `Monitor`, never from the receiver,
is unchanged and pinned by
`test_delivery_failure_content_comes_from_monitor_not_the_receiver`.

**Why this satisfies the scenario's binding assertion.** Both feature files require: *"the
engineer can determine, through Caliper's public interface, both that delivery ... failed and
why"* and *"that information does not depend on the [receiver/logging] mechanism that just
failed."* A field on the object `Monitor.record()` already returns is:

- **Public** — an ordinary attribute, not a private implementation detail (closes
  `requirements-reviewer`'s M1 finding on both tickets: a bare boolean or a private attribute
  would not have satisfied the revised scenario wording).
- **Diagnosable, not just detectable** — `error_type`/`error_message` carry the "why", not only
  the "that" (same finding).
- **Independent of the failed mechanism, by construction** — `Monitor` populates this field
  itself, from its own `try`/`except` around each receiver call. It is never asked of the
  receiver, and never routed back through the receiver's own channel (crucial for BIN-76: if the
  log receiver is what failed, the failure is *not* reported by trying to log again — see §4).
- **Not raised.** Consistent with "signals are not errors" and "absorb, but surface" — a delivery
  failure does not interrupt the caller's program (BR-4/SC8-9), it is data on the result they
  already hold.

**Why a field on `MonitoringResult`, not a separate accessor (e.g. `Monitor.last_delivery_
error`).** `Monitor.record()`'s return value is already the one place every scenario in both
files inspects. A separate accessor would require the engineer to know a second place to look,
and — worse — a method on `Monitor` (not the result) would not appear in `Monitor.history`,
losing the audit trail this design gets for free (§5). It also directly matches OQ-1's own
framing in both PRDs: *"That argues for an in-band carrier on the returned result rather than
another sink call, but the shape is undecided"* — this ADR adopts that leaning, having evaluated
the alternative (below) and found no advantage to it.

**Why `str`, not the live exception object.** `DeliveryFailure` could instead hold `error:
Exception` (the raised exception itself), preserving full type/traceback access. Rejected for
R1: `Monitor.history` retains `MonitoringResult`s by default and without bound (ADR-009 §7's
already-accepted risk); holding live exception objects — which can reference tracebacks, frames,
and arbitrarily large closures — compounds that accepted memory-growth risk for no scenario-
required benefit. `error_type` + `error_message` is the same shape ADR-002's taxonomy already
uses for structured, non-prose failure content, applied here to an exception that is not
necessarily a `CaliperError` (a receiver is arbitrary code, most concretely an engineer's own
callable or the built-in log receiver, not a Caliper-authored type).

### 2. `MonitoringResult` is extended, not replaced with a second type (settles BIN-75 A1)

**`MonitoringResult` gains three fields; no new result type is introduced.**

```python
class MonitoringResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_in_control: bool
    observation: ScoringResult
    chart_type: str
    direction: str | None = None                        # NEW
    fitted_artefact: FittedControlLimits                 # NEW
    delivery_failures: tuple[DeliveryFailure, ...] = ()  # NEW
```

- **`direction: str | None`** — `"upper"` or `"lower"`, matching `FittedCUSUM.direction`'s
  existing vocabulary (`"two_sided"`/`"lower"`/`"upper"`) rather than inventing new terms.
  `None` when `is_in_control` is `True` — there is no departure to have a direction. `"upper"` =
  the process departed above the calibrated upper boundary (EWMA/Shewhart: `score > ucl`;
  CUSUM: `S_hi > h`). `"lower"` = departed below the lower boundary (`score < lcl`; `S_lo > h`).
  Reused as a plain `str`, not a `Literal`, matching `FittedCUSUM.direction`'s own existing type
  (no ADR-004 precedent for `Literal` on this vocabulary).
- **`fitted_artefact: FittedControlLimits`** — the same immutable artefact `Monitor` was
  constructed from, referenced (never copied). Always present, on every result, signal or not —
  not gated on `is_in_control`, because an engineer inspecting `Monitor.history` benefits from
  knowing what artefact every entry was checked against, and gating it would be an arbitrary
  asymmetry with no scenario requiring it.
- **`delivery_failures`** — see Decision §1.

**Why extend, not a second type (BIN-75 Assumption A1, both PRDs' own recommendation).**
`MonitoringResult` already carries the observation and chart type a signal needs; direction and
calibrated parameters are additions to the same concept — a richer description of the same
`record()` outcome — not a different concept requiring a different type. CLAUDE.md's own settled
DX principle: *"two near-identical result types on a public surface is a real cost"*
(BIN-110's findings on `caliper.baseline`'s namespace noise are the concrete precedent for
taking this seriously, not a hypothetical). Extending is also strictly additive to every
existing consumer of `MonitoringResult` — no field is removed or renamed.

**Why `fitted_artefact` closes the "calibrated parameters" requirement without duplicating
fields.** Business Rule 2 (BIN-75) requires the calibrated parameters *in force at detection
time*, and SC3 requires this be delivered "in the same form regardless of which chart type
produced it." ADR-004 §3 already rejected flattening chart-specific detection boundaries into a
shared representation — a common `ucl`/`lcl` pair would misrepresent CUSUM's `decision_interval`.
Reusing the existing `FittedControlLimits`-satisfying artefact object achieves "same form"
(always a `FittedControlLimits`, narrowed via `isinstance` exactly as `Monitor._check` already
does internally) without re-deriving or duplicating any field `FittedEWMA`/`FittedCUSUM`/
`FittedShewhart` already carries — `ucl`/`lcl`, `decision_interval`/`target_value`/
`reference_value`, `achieved_arl`, `calibration_method`, everything. This closes the Problem
Statement's own complaint more completely than a narrower field would: the engineer no longer
needs to have kept a separate reference to the fitted artefact at all — every signal already
carries it.

**Alternative considered and rejected: chart-specific boundary fields directly on
`MonitoringResult`** (e.g. `boundary_crossed: float`, `threshold: float`). Rejected: this is
exactly the flattening ADR-004 §3 already ruled out for the artefact itself, now one level
removed — a `threshold: float` field would misrepresent CUSUM's *h* the same way a shared
`ucl`/`lcl` would, and would give the engineer a single number instead of the full parameter set
Business Rule 2 asks for ("parameters", plural — `achieved_arl`, `calibration_method`, etc. all
matter for "independently audit the statistical basis of the determination").

### 3. Receiver attachment: `Monitor(artefact, receivers=...)` — a plain sequence, not a protocol

**`Monitor.__init__` gains a keyword-only `receivers` parameter accepting a sequence of plain
callables:**

```python
SignalReceiver: TypeAlias = Callable[[MonitoringResult], None]

def __init__(
    self,
    artefact: FittedControlLimits,
    *,
    retain_history: bool = True,
    receivers: Sequence[SignalReceiver] = (),
) -> None: ...
```

```python
monitor = caliper.Monitor(fitted_artefact, receivers=[caliper.monitoring.log_receiver])
```

**No `Protocol`, no base class, no registration method.** A receiver is any callable taking a
`MonitoringResult` and returning `None`. `SignalReceiver` is a plain `TypeAlias`, offered for
engineers' own type hints — not a formal interface, and not `@runtime_checkable` (there is
nothing to structurally check; any callable satisfies it by definition). Receivers are supplied
once, at construction, and are immutable for the `Monitor`'s lifetime in R1 — no `add_receiver()`
method, matching the scope both PRDs set ("this story needs to support exactly one receiver ...
in R1", "do not build a plugin system").

**Does the ADR-009 §8 / BIN-72 A1 precedent apply here? Yes, in shape, not in literal choice.**
Both PRDs cite it directly: *"concrete-only in R1, but the public surface names no internal
type, so a port stays additive."* ADR-009 §8 chose a concrete-only store with no `Protocol`
because a single implementation does not justify an abstraction shaped by guessing at a second
implementation's needs. The receiver surface follows the same discipline for the same reason —
no `Protocol`/ABC is introduced for a single R1 consumer (the log receiver) — but the concrete
shape chosen is *"accept a sequence of callables"* rather than *"accept exactly one callable"*,
for a reason ADR-009 §8 did not need to weigh: this brief explicitly warns *"do not leave a
surface so minimal that BIN-80/BIN-81 must rewrite a published API."* A singular `receiver:
Callable | None` parameter would force BIN-80 (composite/fan-out, R2) into exactly that rewrite —
either renaming the parameter or widening its type in a way existing single-receiver callers
would need to know is still valid. A `Sequence[SignalReceiver]` parameter is already fan-out-
ready mechanically (§4's per-receiver absorb-but-surface loop costs the same whether the sequence
has zero, one, or many entries) while remaining, in this ADR, tested and documented against
exactly one element — R1 ships one built-in receiver (BIN-76's `log_receiver`) and no composite/
ordering/partial-failure semantics beyond what §4 already gives for free. **BIN-81's eventual
formal interface** (the `on_signal`-method sketch in `context.md`) is compatible with this
choice without a breaking change: an engineer can already pass a bound method
(`my_handler.on_signal`) as a `SignalReceiver` today, since a bound method is a plain callable.

**Alternative considered: `receiver: Callable[[MonitoringResult], None] | None = None`
(singular).** Rejected. Closest literal reading of *"this story needs to support exactly one
receiver ... in R1"*, and it would have been the more conservative choice. But it reads that
sentence as constraining the *parameter arity*, when the more consistent reading — given the
same PRD's adjacent instruction not to force a rewrite later — is that R1 constrains what is
*tested and documented* (one built-in receiver), not what the constructor can structurally
accept. A plain `Sequence` parameter with no registration ceremony is not "a plugin system" by
any definition either PRD uses elsewhere (no base class, no discovery, no lifecycle) — it is the
same category of decision as `retain_history: bool` already being a plain constructor keyword.

**Alternative considered: a store-like standalone `SignalReceivers` object the engineer
constructs and passes in.** Rejected for the same reason ADR-009 §7 rejected an opt-in store
object for `Monitor.history` — it reintroduces a configuration step neither PRD asks for, for a
capability (registering callables) that a plain sequence already expresses with zero ceremony.

**Alternative considered: module-level configuration** (e.g. `caliper.monitoring.register_
receiver(fn)`, global to the process). Rejected outright: global mutable registration state is
incompatible with `Monitor`'s own design — two `Monitor`s constructed from the same artefact
already hold independent accumulator state (ADR-009 §1); a global receiver registry would let
one `Monitor`'s configuration leak into another's, breaking that isolation for no benefit, and
introduces a process-wide side effect a library should not own (the same reasoning CLAUDE.md
already applies to rejecting `structlog`'s process-wide formatting).

### 4. Delivery is synchronous, inside `record()`, after the chart check, before history append (settles BIN-75 OQ-3)

**Sequence inside `Monitor.record()`, after the existing provenance/observation checks (ADR-009
§§2–3, unchanged):**

1. Run the chart-specific comparison (`_check`), producing `is_in_control` and `direction`.
2. Build a provisional `MonitoringResult` with `delivery_failures=()` — everything else already
   known.
3. **Only if `is_in_control is False`** (settles BIN-75 Assumption A2 — a receiver is told about
   a signal only when one genuinely occurs, never for a routine observation): for each receiver
   in `self._receivers`, call `receiver(provisional_result)` inside its own `try`/`except
   Exception`. On success, continue. On failure, append a `DeliveryFailure(receiver=_describe_
   receiver(receiver), error_type=type(exc).__name__, error_message=_describe_exception(exc))`
   to a local list — the two helpers guard `repr()`/`str()`, which can raise in turn (see the
   `BIN-118` amendment in section 1) — one receiver's failure
   never prevents the next receiver from being attempted (per-receiver isolation, not one
   `try` around the whole loop).
4. If any failures were collected, produce the final result via `provisional_result.model_copy
   (update={"delivery_failures": tuple(failures)})` — the same "mutations return new instances"
   pattern `references/ddd.md` and `references/hexagonal.md` already establish for this
   codebase, applied here because `MonitoringResult` is frozen and `delivery_failures` cannot be
   known until every receiver has been attempted.
5. Append the final result to `self._history` (if `retain_history`), then return it.

**Why synchronous, not deferred.** Three reasons, all scenario-grounded:

- **SC6 (BIN-75), SC5 (BIN-76): ordering.** *"Multiple signals ... are each delivered, in
  order"* / *"each signal produces its own log entry, in the order the signals occurred."*
  Synchronous, in-call delivery trivially guarantees this — each `record()` call fully completes
  (chart check, all receivers, history append) before the next one begins. A deferred/queued
  design would need its own explicit ordering guarantee that does not otherwise exist anywhere
  in this synchronous, single-threaded library.
- **SC4 (BIN-75): "told about the signal without needing to separately inspect the outcome of
  that recording call."** This is satisfied by the receiver having already run by the time
  `record()` returns — a deferred design could not guarantee the receiver has fired yet at that
  point, undermining the very guarantee the scenario asserts.
- **Consistency with the rest of the library.** `Judge.score()`, `Baseline.record()`, and
  `Monitor.record()` itself (ADR-009) are all synchronous call-and-return. Caliper has no
  `asyncio` dependency anywhere (`CLAUDE.md`'s "Stack Members Not Yet Used" note does not list an
  async runtime as a future trigger for this project). Introducing deferred/background delivery
  for R1's one built-in receiver would be new infrastructure this ADR has no scenario-driven
  reason to build.

**Why after the chart check but reflected in the result returned to the engineer.** The
provisional result already carries `is_in_control`/`direction`/`fitted_artefact`/`observation`
before any receiver runs — a receiver never influences the determination itself (consistent with
"signals are not errors": delivery is a side effect of a signal, never a cause of one).

### 5. History captures delivery outcome, for free

Because the final `MonitoringResult` (with `delivery_failures` populated) is what gets appended
to `Monitor.history` (ADR-009 §6, unchanged — still a plain `tuple[MonitoringResult, ...]`), an
engineer reviewing history after the fact can see, per historical entry, whether delivery to its
configured receiver(s) succeeded — no new mechanism, no second store, purely a consequence of
extending the one result type these consecutive ADRs already share.

### 6. The built-in log receiver (BIN-76)

```python
def log_receiver(signal: MonitoringResult) -> None:
    logger = logging.getLogger("caliper.monitoring")
    logger.warning(
        "caliper detected a drift signal: chart_type=%s direction=%s",
        signal.chart_type,
        signal.direction,
        extra={
            "caliper_chart_type": signal.chart_type,
            "caliper_direction": signal.direction,
            "caliper_observation_score": signal.observation.score,
            "caliper_fitted_artefact": signal.fitted_artefact,
        },
    )
```

Exported as `caliper.monitoring.log_receiver`, usable as
`Monitor(artefact, receivers=[caliper.monitoring.log_receiver])` — a concrete instance of §3's
plain-callable `SignalReceiver` shape, no special-casing in `Monitor` itself. Because it is an
ordinary receiver, a failure inside it (a broken handler, a full disk) is caught by the exact
same per-receiver `try`/`except` in §4 — **no separate failure-handling path for the log
receiver was built**, which is precisely what closes the shared OQ-1 circularity for BIN-76's
own case: the failure is reported via `result.delivery_failures` (populated by `Monitor`, from
outside the logging call entirely), never by attempting to log the failure through the same
logging call that just failed.

**Logger namespace: `"caliper.monitoring"` (settles BIN-76 OQ-3).** Follows CLAUDE.md's ratified
`stdlib logging.getLogger("caliper")` convention (the same pattern requests/urllib3/botocore
use), scoped to the Monitoring bounded context specifically — an engineer can filter or attach a
handler to `"caliper.monitoring"` without affecting log output from other Caliper contexts,
should any appear later. Documented on the `log_receiver` docstring, per BR-3's requirement that
the engineer can discover how to attach a handler in practice, not just in principle.

**Log level: `WARNING` (settles BIN-76 OQ-2).** Not a stylistic choice — it is required by SC4
("Engineer still sees a signal in the log without any additional logging configuration of their
own ... through Python's own default logging behaviour, without needing extra configuration").
Python's `logging` module installs `logging.lastResort` (level `WARNING`, writes to `stderr`)
when no handler is configured anywhere in the hierarchy. A call at `INFO` or `DEBUG` produces
**no visible output** without configuration — only `WARNING` and above satisfy SC4 as written.
`WARNING`, not `ERROR`: a drift signal is not an error in Caliper's own operation (BR-7,
"signals are not errors" — the same rule this ADR's whole delivery design exists to preserve);
`ERROR` would misrepresent a successful, correct measurement as a failure. This is a single
interim level for every signal, in the explicit absence of severity classification (BIN-77, R2)
— not a considered choice among severities, the same "no mechanism yet" posture ADR-009 already
took for the accumulator-reset question (BIN-113).

**Structured content, not `structlog` (BR-1, unchanged from the PRD's own resolution).** The
`extra=` mapping attaches machine-inspectable fields to the stdlib `LogRecord` without requiring
any third-party formatting library — an engineer's own `logging.Formatter` or a `structlog`
processor they already run can pick these fields up if they choose to; Caliper does not require
it. Ruff's `LOG`/`G` rule families (already enabled in this project's config) are satisfied by
this call: a `Logger` instance is used (never the `logging.warning()` module-level shortcut), and
arguments are passed positionally for lazy `%`-formatting rather than an f-string.

## Alternatives considered

### Raising an exception on delivery failure

Rejected outright by the ratified policy (OQ-1, "absorb, but surface", product owner, 2026-09-11)
before this ADR began: `record()` has already computed a successful measurement by the time any
receiver runs; letting a broken receiver destroy that result would be a second, worse way of
violating "signals are not errors."

### Silently discarding a delivery failure

Also rejected by the ratified policy: a drift signal nobody receives, with nobody told even that
delivery itself failed, is the exact failure this library exists to prevent — silently worse than
the status quo before this ADR, not neutral.

### Surfacing a delivery failure through the receiver's own channel (e.g. always also try to log it)

Rejected — this is the circularity both PRDs name explicitly: if the log receiver is the one that
failed, attempting to report that failure by logging again is not guaranteed to succeed either,
and for a non-logging receiver (a future webhook, BIN-78) there may be no fallback channel at
all. An in-band field on the result (§1) has no analogous failure mode — it is populated by
`Monitor`'s own code, not by calling anything that could itself fail.

### Delivery failures as a new `CaliperError` subclass, raised then caught internally

Considered, since ADR-002's taxonomy is semi-open. Rejected: `DeliveryFailure` is not raised
anywhere in the public API (the policy is absorb-but-surface, not absorb-then-re-express-as-an-
exception-nobody-catches) — it is data attached to a successful result, and treating it as an
`CaliperError` subtype would misrepresent it as an operational failure of Caliper itself, when
the actual failure belongs to the engineer's own receiver code (or, for `log_receiver`, their own
logging configuration).

### `MonitoringResult` as two types depending on outcome (a `SignalResult` subtype)

Considered as a way to make `direction`/`fitted_artefact` required rather than optional on the
signal path. Rejected: reintroduces the two-near-identical-types cost §2 already rejects, and
none of the fifteen scenarios requires `direction`/`fitted_artefact` to be non-nullable — `is_in_
control` is already the single source of truth for whether a signal occurred, and branching on it
is one line the engineer already writes.

## Consequences

### What changes

- `MonitoringResult` gains three fields: `direction: str | None`, `fitted_artefact:
  FittedControlLimits`, `delivery_failures: tuple[DeliveryFailure, ...]`. All additive — no
  existing field removed or renamed.
- A new value object, `DeliveryFailure` (`receiver: str`, `error_type: str`, `error_message:
  str`), frozen, equality by value.
- `Monitor.__init__` gains a keyword-only `receivers: Sequence[SignalReceiver] = ()` parameter.
  A new public type alias, `SignalReceiver = Callable[[MonitoringResult], None]`.
- `Monitor.record()` gains a delivery step between the chart-specific check and the history
  append: invoke each configured receiver only on a genuine signal, absorb any exception into
  `DeliveryFailure`, never let one propagate out of `record()`.
- A new public function, `caliper.monitoring.log_receiver`, the R1 built-in log-based
  `SignalReceiver`, logging to `"caliper.monitoring"` at `WARNING`.
- No new `CaliperError` category. No new bounded context — this extends Monitoring (E3, ADR-009)
  as its delivery mechanism, per `docs/domain-model.md`'s own note that E4 is "the natural
  location" for this once specified.
- `docs/domain-model.md` gains: updated Monitor/MonitoringResult Object Map and Value Object
  Inventory entries, a new `DeliveryFailure` entry, updated Library Operations rows, updated
  Glossary entries (Signal, and new entries for Signal receiver / Delivery failure), and closes
  the Domain Event Catalogue's outstanding "E4 unspecified" note for R1's two stories specifically
  (BIN-77 onward remains unspecified).

### What does not change

- **ADR-009** is not amended. `Monitor`'s constructor validation, provenance-check ordering,
  boundary convention (strict inequality), and `Monitor.history`'s plain-`tuple` shape all stand
  exactly as decided. This ADR adds a delivery step and three result fields; it does not alter
  how recording, provenance-checking, or history retention work.
- **ADR-004** is not amended. `FittedControlLimits` and the three concrete artefact types are
  unchanged; `MonitoringResult.fitted_artefact` is a new *consumer* reference, not a new field on
  the protocol.
- **ADR-002/ADR-008** are not amended. No new exception category; `DeliveryFailure` is data, not
  an exception.
- **No `.feature` file changes.** All fifteen scenarios across both files were verified bindable
  against this design (below) — both were written mechanism-neutrally, specifically to survive
  whichever resolution this ADR chose.

### Bindability — verified scenario-by-scenario

**`out-of-control-signal-event.feature` (BIN-75), 9/9 bindable:**

| Scenario | Binds against |
|---|---|
| SC1 (direction + boundaries + observation) | `result.direction`, `result.fitted_artefact`, `result.observation` |
| SC2 (no signal → nothing produced) | `result.is_in_control is True` and `result.direction is None`; no receiver invoked (§4 step 3 gate) |
| SC3 (consistent form across chart types) | `direction` always `str \| None`; `fitted_artefact` always `FittedControlLimits`-satisfying, narrowed via `isinstance` |
| SC4 (told without polling) | `receivers=[my_receiver]`; `my_receiver` invoked synchronously inside `record()` |
| SC5 (not told for routine observations) | §4 step 3 — receivers invoked only when `is_in_control is False` |
| SC6 (multiple signals, in order) | §4's synchronous, in-call delivery — no ordering mechanism needed beyond call order |
| SC7 (no receivers → still get determination from the call) | `receivers=()` default; return value unchanged in shape |
| SC8 (signal completes/returns normally) | §4's `try`/`except` around each receiver — a genuine signal never raises |
| SC9 (failing receiver — absorb but surface, via public interface, mechanism-independent) | `result.delivery_failures` — populated by `Monitor`, not the receiver; `error_type`/`error_message` carry "why" |

**`drift-signal-log-handler.feature` (BIN-76), 6/6 bindable:**

| Scenario | Binds against |
|---|---|
| SC1 (log entry with direction/boundaries/observation) | `log_receiver`'s `extra=` mapping, sourced from `MonitoringResult`'s new fields |
| SC2 (routine observations → no log entry) | Same gate as BIN-75 SC5 — `log_receiver` is a receiver, only invoked on signal |
| SC3 (respects engineer's own logging config) | stdlib `logging.getLogger("caliper.monitoring")` — destination/format always the engineer's own handler/formatter config |
| SC4 (visible with zero extra config) | `WARNING` level — satisfies `logging.lastResort`'s default `WARNING` threshold |
| SC5 (multiple signals logged independently, in order) | Same synchronous, in-call ordering as BIN-75 SC6 |
| SC6 (logging failure — absorb but surface, mechanism-independent) | `result.delivery_failures`, populated by `Monitor`'s own `try`/`except` around the `log_receiver` call — never by attempting to log the failure itself |

### Reversibility

- **`MonitoringResult` extension (§2):** medium cost, the same class ADR-009 already assigned to
  this type — adding fields is additive and safe; removing or renaming `direction`,
  `fitted_artefact`, or `delivery_failures` later would break every consumer, including
  `Monitor.history`'s entries. Low cost *now* — no released consumer exists yet.
- **`DeliveryFailure` shape (§1):** low-medium cost. Adding fields (e.g. a future `traceback:
  str | None`) is additive. Switching `error_type`/`error_message` to hold the live exception
  object later is also additive (a new optional field, not a replacement) if a genuine need for
  traceback access appears — the string-only choice here is a starting default, not a permanent
  ceiling, chosen for the memory-growth reason in §1.
- **`receivers: Sequence[SignalReceiver]` (§3):** low cost to *use* at more than one element later
  (BIN-80) — the parameter shape and the per-receiver delivery loop (§4) already support N
  receivers mechanically; R1 only tests and documents one. Genuinely low cost specifically
  *because* the plural shape was chosen now — the alternative (singular `receiver`) would have
  made this a medium-to-high cost breaking change instead, which is the reasoning §3's alternative
  discussion is explicit about.
- **Synchronous delivery (§4):** medium-high cost to reverse into deferred/async delivery later —
  would change the ordering and "told before the call returns" guarantees several scenarios rely
  on, and would need a new mechanism (queue, background thread/task) this library has no
  precedent for. Not expected to be revisited without a specific async-delivery requirement
  appearing, which nothing currently does.
- **Log receiver namespace/level (§6):** low cost. Changing the namespace or level later is a
  behaviour change for anyone who configured a handler against `"caliper.monitoring"` at
  `WARNING` specifically, but is mechanically a one-line change with no structural consequence
  elsewhere — the same low-reversibility-cost class as any other single-purpose default.

## Related decisions

- **BIN-75 A1** (extend `MonitoringResult` vs. new type): resolved above, §2.
- **BIN-75 A2** (receiver told only on genuine signal): resolved above, §4 step 3.
- **BIN-75 OQ-1** (absorb-but-surface, WHERE): resolved above, §1. WHAT (absorb, but surface) was
  already ratified by the product owner before this ADR; this ADR resolves WHERE only.
- **BIN-75 OQ-2** (where an engineer arranges to be told): resolved above, §3 — `Monitor`
  constructor, `receivers` keyword parameter.
- **BIN-75 OQ-3** (synchronous vs. deferred delivery): resolved above, §4 — synchronous.
- **BIN-76 OQ-1** (absorb-but-surface, shared with BIN-75): resolved above, §6 — the log receiver
  uses the same general mechanism, no special-casing.
- **BIN-76 OQ-2** (logging level): resolved above, §6 — `WARNING`.
- **BIN-76 OQ-3** (logger namespace): resolved above, §6 — `"caliper.monitoring"`.
- **ADR-009 §8** (no store port in R1, concrete-only, additive public surface): the precedent both
  PRDs cite; applied to the receiver surface in §3, with the specific shape (sequence, not
  singular) chosen for a reason ADR-009 §8 itself did not need to weigh (see §3's discussion).
- **BIN-77** (severity classification, R2): not designed here. The single interim `WARNING` level
  (§6) and the absence of any severity field on `MonitoringResult` are both explicitly provisional
  — BIN-77 is expected to add a severity dimension additively, not to replace this ADR's decisions.
- **BIN-78** (webhook handler, R2): not designed here. `SignalReceiver`'s plain-callable shape
  (§3) already accommodates a webhook receiver as an ordinary function with no interface change.
- **BIN-79** (`RaiseOnSignal`, R2): not designed here, and explicitly out of scope — `record()`
  never raises for a genuine signal under this ADR either, consistent with BR-7.
- **BIN-80** (composite/fan-out to multiple receivers, R2): shaped, not designed, by §3 and §4 —
  the `Sequence[SignalReceiver]` parameter and per-receiver `try`/`except` loop already support
  multiple receivers mechanically; BIN-80's own scope is to test, document, and potentially add
  convenience/ordering guarantees on top, not to change the parameter shape.
- **BIN-81** (formal public custom-handler base interface, R2): shaped, not designed, by §3 — any
  future `Protocol`/ABC with an `on_signal` method is satisfiable today via a bound method passed
  as a plain `SignalReceiver`, so introducing one later is additive.
- **BIN-82** (Western Electric pattern-violation detection, R2): not designed here; depends on
  this ADR's basic signal delivery existing first, which it now does.
