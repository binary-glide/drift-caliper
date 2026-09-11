Feature: Record a Phase II observation and check for a signal
  As a Python engineer whose agent is producing live output in production
  I want to record a newly scored observation against my fitted Phase I
  control limits and find out whether it represents normal variation or a
  genuine process change
  So that I can trust my production monitoring without performing my own
  statistical comparison

  # -- Pending decisions --
  # The following assumptions and open questions are owned by
  # domain-modeller / system-architect and are not yet settled. These
  # scenarios are written to survive any resolution -- none of them
  # names a "Monitor" construct, a free function, a method on the fitted
  # artefact, or any particular shape for carried-forward chart state.
  # "Record the observation against the fitted artefact" is used
  # throughout as the neutral description of the action, regardless of
  # where the operation ultimately lives or where EWMA/CUSUM state is
  # ultimately held between calls.
  #
  # [ASSUMPTION] A1 -- HIGH: Some state distinct from both the immutable
  #   fitted artefact and BIN-72/73's durable persistence must carry
  #   EWMA/CUSUM's accumulated statistic forward between recording
  #   calls. No construct for this exists yet in docs/domain-model.md --
  #   ADR-006 explicitly declined to invent a "Monitor" for a different
  #   question. Scenarios below describe accumulation as an observable
  #   property of "recording against the same fitted artefact", not as
  #   a specific object an engineer holds.
  #   Owner: domain-modeller
  #
  # [ASSUMPTION] A2 -- HIGH: The recording operation should call the
  #   existing provenance comparison (BIN-68, merged) internally rather
  #   than requiring the engineer to call it separately first, so a
  #   forgetful engineer cannot silently record against mismatched
  #   provenance. Scenarios assert only that recording is refused on a
  #   mismatch, not whether the check happens inside recording or via a
  #   separate call the scenario doesn't show.
  #   Owner: system-architect
  #
  # OQ-1: Where the recording-and-checking operation lives -- on the
  #   fitted artefact, on a new construct not yet in the domain model,
  #   or as a free function. Scenarios use "record the observation
  #   against the fitted artefact" throughout, which is true under any
  #   of the three.
  #   Owner: domain-modeller
  #
  # OQ-2: What a non-signalling record returns, and whether it carries
  #   an explicit yes/no field. Per BIN-110, truthiness is forbidden
  #   unless an explicit field already carries the yes/no meaning.
  #   Scenarios below say "they see that the process remains in
  #   control" / "they see that the process is now out of control" --
  #   an observable outcome -- and never phrase an assertion as reading
  #   a bare truth value of the result itself.
  #   Owner: domain-modeller
  #
  # OQ-3: Whether an observation lying exactly on a control limit
  #   boundary (or exactly at CUSUM's decision interval) counts as in
  #   control or out of control. This is a genuine numerical question
  #   that must be verified against the primary sources already cited
  #   for each chart type (Lucas & Saccucci 1990; Siegmund 1985;
  #   Montgomery), not assumed here. No scenario in this file asserts
  #   an outcome for an observation exactly at a boundary -- inventing
  #   one would encode a guess as a contract. Left for system-architect
  #   to settle and for a follow-up scenario to assert once it is.
  #   Owner: system-architect
  #
  # OQ-4: What error category applies to recording an incomplete or
  #   otherwise invalid Phase II observation -- reusing
  #   `InvalidObservationError` (BIN-63's Phase I equivalent) or a new
  #   category. ADR-002's taxonomy is semi-open. The scenario below
  #   asserts only that the failure is programmatically classifiable
  #   and identifies what was missing or invalid, not which category.
  #   Owner: system-architect
  #
  # -- Out of scope for this file (see PRD Non-Goals) --
  # Signal delivery -- handlers, callbacks, severity, webhooks,
  # OpenTelemetry (E4, BIN-75-81, unspecified). This story reports the
  # fact of a signal; it does not deliver it anywhere. The decorator
  # (BIN-70) and context manager (BIN-71) wiring, and their wrapper
  # failure policy, are R2 and not presupposed here. Durable,
  # queryable observation persistence (BIN-72/73). Redefining
  # provenance-mismatch behaviour -- BIN-68/ADR-002 stand as-is; this
  # file asserts only that recording reuses that established failure.

  # --- Happy path: observation confirmed in control (BR-1 happy) ---

  Scenario: A production observation within the calibrated boundaries is confirmed in control
    Given the engineer has a fitted control limit artefact from a Phase I baseline
    And they have a newly scored Phase II observation that shares the artefact's measurement provenance
    And the observation's value falls within the calibrated boundaries
    When they record the observation against the fitted artefact
    Then they see that the process remains in control

  # --- Signal path: observation reported out of control (BR-1, BR-7) ---
  #
  # An out-of-control determination is the successful output of a
  # measurement, not a failure -- see the "signal is not raised" edge
  # case below, which asserts the non-interruption property directly.

  Scenario: A production observation that breaches the calibrated boundaries is reported as out of control
    Given the engineer has a fitted control limit artefact from a Phase I baseline
    And they have a newly scored Phase II observation that shares the artefact's measurement provenance
    And the observation represents a genuine departure from the process the baseline describes
    When they record the observation against the fitted artefact
    Then they see that the process is now out of control
    And what they see identifies the observation that triggered it

  # --- Accumulation vs memorylessness (BR-3, BR-4) ---
  #
  # EWMA and CUSUM are recursive by definition -- their entire value is
  # detecting a sustained small shift that no single observation crosses
  # a boundary on its own. The Shewhart I-chart is memoryless by design.
  # "Record one observation" genuinely means something different per
  # chart, and both properties must be observable without either
  # scenario prescribing where the accumulated state lives (A1, OQ-1).

  Scenario: A chart that accumulates evidence across observations reflects the accumulated pattern, not only the latest value
    Given the engineer has fitted an EWMA or CUSUM artefact from a Phase I baseline
    And they have already recorded one or more prior Phase II observations against this artefact, each individually within the calibrated boundaries
    When they record a further observation continuing the same small, sustained shift
    Then whether the process is now out of control reflects the pattern across the recorded sequence, not the latest observation considered alone

  Scenario: A chart that evaluates each observation independently is unaffected by a prior observation's outcome
    Given the engineer has fitted a Shewhart control limit artefact from a Phase I baseline
    And a prior Phase II observation recorded against this artefact was reported as out of control
    When they record a further observation whose own value falls within the calibrated boundaries
    Then they see that this observation is in control, regardless of the prior observation's outcome

  # --- Edge: first observation needs no prior history (feasibility risk) ---
  #
  # Whatever state EWMA/CUSUM initialise from must not require the
  # engineer to have already recorded something -- the very first
  # production call after fitting must be checkable on its own.

  Scenario: The very first Phase II observation after fitting can be checked on its own
    Given the engineer has just fitted control limits and has not yet recorded any Phase II observations
    When they record their first production observation
    Then they see whether that single observation is in control, without needing any other observation to have been recorded first

  # --- Sad path: provenance mismatch (BR-2, reuses BIN-68) ---
  #
  # This does not redefine BIN-68's provenance-mismatch behaviour --
  # it asserts only that recording a Phase II observation is one of the
  # places that established failure now applies.

  Scenario: Recording is refused when the observation's measurement provenance does not match the fitted artefact
    Given the engineer has a fitted control limit artefact from a Phase I baseline
    And they have a newly scored Phase II observation produced under a different judge model version or scoring criteria than the artefact
    When they attempt to record the observation against the fitted artefact
    Then they see the same provenance mismatch failure already established for comparing measurement systems across the Phase I to Phase II boundary
    And they do not receive an in-control or out-of-control answer for that observation

  # --- Sad path: invalid observation (BR-5) ---

  Scenario: Recording is refused for an incomplete observation
    Given the engineer has a fitted control limit artefact from a Phase I baseline
    When they attempt to record something that is not a complete scored observation
    Then the recording fails with an error that is programmatically classifiable, rather than being silently treated as in control
    And what they see identifies what was missing or invalid

  # --- Edge: signals are not errors (BR-7, ratified) ---

  Scenario: An out-of-control determination does not interrupt the engineer's program
    Given the engineer has a fitted control limit artefact from a Phase I baseline
    And they have a newly scored Phase II observation that represents a genuine departure from the process
    When they record the observation against the fitted artefact
    Then they receive the out-of-control determination as a normal result of the call
    And their program continues running without an unhandled exception

  # --- Edge: consistency across chart types (BR-6, ADR-004) ---
  #
  # The comparison logic is necessarily chart-specific (ADR-004 section
  # 3 rejected a shared detection-boundary representation) -- this
  # scenario asserts that the engineer-facing capability is nonetheless
  # uniform, not that the underlying comparison is shared.

  Scenario: Checking a production observation works the same way regardless of which chart type was fitted
    Given the engineer has fitted control limits using each of the three available chart types from the same Phase I baseline
    And they have the same newly scored Phase II observation for each
    When they record that observation against each fitted artefact in turn
    Then in every case they can determine whether the process is in control
