Feature: Persist Phase II observations to an in-memory store
  As a Python engineer developing or testing Phase II monitoring
  I want the observations I record during my program's run to remain
  available for me to look back at
  So that I can review monitoring history without configuring external
  storage

  # -- Pending decisions --
  # The following assumptions and open questions are owned by
  # domain-modeller / system-architect and are not yet settled. These
  # scenarios are written to survive any resolution -- none of them
  # names a store "Protocol", a constructor an engineer must call, or
  # a specific shape for a stored entry. "Review their session's
  # monitoring history" is used throughout as the neutral description
  # of the action, regardless of where that capability ultimately
  # lives or what object (if any) the engineer holds to reach it.
  #
  # [ASSUMPTION] A1 -- HIGH: No dedicated store *port* (a Protocol
  #   abstraction) is needed in R1. This story ships a concrete
  #   in-memory store only; any abstraction is introduced later by
  #   BIN-73, once a second real implementation exists to abstract
  #   over. docs/domain-model.md already states this for the Repository
  #   pattern generally. No scenario below names an interface, and
  #   none would change if this assumption were overturned.
  #   Owner: system-architect
  #
  # [ASSUMPTION] A2 -- HIGH: Reviewing session monitoring history
  #   requires zero engineer-side configuration -- available
  #   automatically once a Phase II observation is recorded (BIN-69),
  #   not requiring the engineer to construct or attach a store object
  #   first. Scenarios below say "the engineer has recorded ... during
  #   their running program" and "they review their session's
  #   monitoring history" -- true whether that review happens through
  #   an object the engineer already holds from recording, a separate
  #   zero-argument accessor, or something else not yet named.
  #   Owner: system-architect, coupled to BIN-69 OQ-1
  #
  # OQ-1: What exact shape a stored entry takes -- BIN-69's raw result
  #   type directly, or a wrapper pairing the Phase II observation with
  #   its determination. Coupled to BIN-69's still-open OQ-2 (result
  #   shape, including whether an explicit in-control/out-of-control
  #   field exists, per BIN-110's settled truthiness convention).
  #   Scenarios below assert only that the observation and its
  #   determination are both visible together, never that a specific
  #   field or wrapper carries them.
  #   Owner: system-architect / domain-modeller, coupled to BIN-69 OQ-2
  #
  # OQ-2: Whether the store exposes a way to bound or clear its growth
  #   during a long-running session, and whether any of that is in
  #   scope for R1 at all, or only structurally un-precluded for later
  #   (BR-7). This is genuinely undecided, not merely a mechanism
  #   choice -- the PRD's own Non-Goals exclude "a specific bounding,
  #   eviction, or clearing mechanism" from R1. A scenario exercising
  #   bounded growth would have to invent whether such a thing exists
  #   at all this release, so none is written here. Add one once this
  #   resolves.
  #   Owner: system-architect
  #
  # OQ-3: Whether reviewing monitoring history needs visibility into
  #   each chart's accumulated internal state (for example, the EWMA
  #   smoothed statistic) at the time of each observation, or only the
  #   observation and its in-control/out-of-control determination.
  #   Coupled to BIN-69's still-open OQ-1/A1 (where EWMA/CUSUM chart
  #   state is carried forward between calls) -- that state may or may
  #   not end up living in this story's store. Scenarios below assert
  #   only the observation and its determination, never chart-internal
  #   state.
  #   Owner: domain-modeller, coupled to BIN-69 OQ-1/A1
  #
  # -- Out of scope for this file (see PRD Non-Goals) --
  # Durable persistence across process restarts (BIN-73, R2). Postgres
  # store adapter and dashboard/read-view UI (never -- epic-level
  # deferred scope). OpenTelemetry emission (BIN-74, R2). Signal
  # delivery -- handlers, callbacks, severity, webhooks (E4, BIN-75
  # through BIN-81, unspecified). Decorator (BIN-70) and context
  # manager (BIN-71) wiring (R2). Persisting Phase I baseline
  # observations -- already covered by `Baseline` (BIN-63); this store
  # is deliberately not a second Baseline. Recording an attempt that
  # Phase II recording itself refused (not now -- see BR-2 below).
  # Chart rendering or visualisation (BIN-107, not now). A specific
  # bounding, eviction, or clearing mechanism (see OQ-2 above).

  # --- Happy path: ordered review (BR-3) ---

  Scenario: Engineer reviews the observations recorded during their session, in order
    Given the engineer has recorded more than one Phase II observation during their running program
    When they review their session's monitoring history
    Then they see the observations in the order they were recorded

  # --- Boundary: a single recorded observation (BVA -- between empty and "more than one") ---

  Scenario: A single recorded observation appears in the session's monitoring history
    Given the engineer has recorded a single Phase II observation during their running program
    When they review their session's monitoring history
    Then they see that one observation as the entirety of their recorded history

  # --- Happy path: outcome is visible alongside the observation (BR-2, OQ-1) ---

  Scenario: Engineer sees what a reviewed observation's monitoring outcome was
    Given the engineer has recorded a Phase II observation that was checked against fitted control limits
    When they review that observation in their session's monitoring history
    Then they can see whether it was in control or out of control at the time it was recorded

  # --- Boundary: empty history (BVA -- empty case) ---

  Scenario: A session with no recorded observations has an empty monitoring history
    Given the engineer has not yet recorded any Phase II observations in their running program
    When they review their session's monitoring history
    Then they see that no observations have been recorded yet

  # --- Sad path: session lifetime (BR-5) ---
  #
  # This is the entire distinction between this story and BIN-73's
  # durable store. The scenario asserts the boundary directly rather
  # than any particular mechanism that enforces it.

  Scenario: Monitoring history does not carry over between separate runs of the engineer's program
    Given the engineer recorded Phase II observations during a previous run of their program
    When they start a new run and review their session's monitoring history
    Then they see no observations from the previous run

  # --- Edge: repeatable, non-destructive review (BR-5, "not silently durable" implies reads don't mutate) ---

  Scenario: Reviewing monitoring history is repeatable and does not change what was recorded
    Given the engineer has recorded Phase II observations during their session
    When they review their session's monitoring history more than once
    Then each review shows the same recorded observations in the same order

  # --- Sad path: immutability (BR-4) ---

  Scenario: A recorded observation in the session's monitoring history cannot be altered after the fact
    Given the engineer has recorded a Phase II observation into their session's monitoring history
    When they attempt to change that recorded observation
    Then the attempt does not succeed and the original observation is unchanged

  # --- Sad path: refused attempts are not recorded (BR-2, reuses BIN-69's refusal) ---
  #
  # This does not redefine BIN-69's refusal behaviour -- it asserts
  # only that a refused attempt leaves no trace in this store.

  Scenario: An observation that Phase II recording refused does not appear in the session's monitoring history
    Given the engineer attempted to record a Phase II observation that Phase II recording refused, for example because of a measurement provenance mismatch
    When they review their session's monitoring history
    Then the refused attempt does not appear among the recorded observations

  # --- Sad path: this store does not overlap with Phase I's Baseline (BR-1) ---
  #
  # This store is not a second Baseline. Phase I observations belong
  # to BIN-63's Baseline collection; this scenario guards against the
  # two collections' data ever mixing, regardless of how the two are
  # ultimately shaped or connected on the public surface.

  Scenario: Phase I baseline observations do not appear in the session's monitoring history
    Given the engineer has recorded observations into a Phase I baseline during their session
    And they have also recorded Phase II observations during the same session
    When they review their session's monitoring history
    Then they see only the Phase II observations, and none of the Phase I baseline observations
