Feature: Deliver a structured signal event when Phase II monitoring detects drift
  As a Python engineer whose agent is monitored in production
  I want an out-of-control determination to identify what kind of statistical
  departure occurred, and I want a way to be told about it as it happens
  So that I can judge whether it warrants immediate attention without
  reconstructing the statistical picture by hand, and without polling the
  return value of every single recording call myself

  # -- Pending decisions --
  # The following assumptions and open questions are owned by
  # domain-modeller / system-architect and are not yet settled. These
  # scenarios are written to survive any resolution -- none of them names
  # a result-type shape, a "handler"/"receiver" interface, a registration
  # method, a constructor parameter, or a delivery-timing mechanism.
  # "Arrange to be told" is used throughout as the neutral description of
  # however an engineer ends up connecting a receiver, regardless of where
  # that capability ultimately attaches. "What they see" is used for the
  # signal's content, regardless of whether it lives on the existing
  # recording result or a new type.
  #
  # [ASSUMPTION] A1 -- HIGH: signal-specific content (direction, calibrated
  #   parameters) extends the existing recording result rather than
  #   introducing a second, near-identical type. Scenarios below assert
  #   only that this content is present on what recording returns for a
  #   signal, never that it is a specific named field or a separate type.
  #   Owner: domain-modeller
  #
  # [ASSUMPTION] A2 -- HIGH: a receiver is told about a signal only when
  #   one genuinely occurs, never for a routine in-control observation.
  #   Owner: system-architect
  #
  # [SETTLED -- product owner, 2026-09-11] OQ-1: a failing signal
  #   receiver ABSORBS, but SURFACES. The exception does not escape the
  #   recording call, and is not silently discarded either. 🚨 Still open
  #   for system-architect: WHERE it surfaces -- note the circularity that
  #   if a receiver failed, surfacing through that same kind of receiver
  #   may fail too. The scenario below says only that the engineer "can
  #   tell that delivery failed", naming no carrier, consistent with that
  #   open question.
  #
  # OQ-2: where an engineer arranges to be told about a signal -- a
  #   constructor parameter, a method call, module-level configuration, or
  #   something else. No precedent exists anywhere in this codebase.
  #   Owner: domain-modeller / system-architect
  #
  # OQ-3: whether delivery happens synchronously within the recording call
  #   or is deferred. Scenarios below describe delivery as something that
  #   has happened by the time the engineer next looks, never asserting
  #   whether it happened inside the call or after it returned.
  #   Owner: system-architect
  #
  # -- Out of scope for this file (see PRD Non-Goals) --
  # Severity classification (BIN-77, R2). Webhook handler (BIN-78, R2).
  # Exception-based signal handling / RaiseOnSignal (BIN-79, R2).
  # Composite handlers / fan-out to multiple simultaneous receivers
  # (BIN-80, R2). A formal, public custom-handler base interface (BIN-81,
  # R2). Western Electric pattern-violation detection (BIN-82, R2).
  # Redefining the in-control/out-of-control determination itself, or the
  # strict-inequality boundary convention -- settled by ADR-009, reused
  # not reopened here. What happens to a chart's accumulator immediately
  # after a signal (BIN-113, explicitly left open by ADR-009). The log
  # handler itself -- that is BIN-76, a consumer of what this file
  # establishes.

  # --- Signal content: direction and calibrated boundaries (BR-1, BR-2, BR-3) ---

  Scenario: A signal identifies the direction of the departure and the boundaries in force
    Given the engineer has fitted control limits and is recording Phase II observations against them
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then the resulting signal identifies the direction the process departed in
    And it identifies the calibrated boundaries that were in force when the departure was detected
    And it identifies the observation that triggered it

  Scenario: An observation that remains within the calibrated boundaries produces no signal
    Given the engineer has fitted control limits and is recording Phase II observations against them
    And a newly recorded observation's value falls within the calibrated boundaries
    When they record that observation
    Then no signal is produced for it

  Scenario: Signal content is delivered consistently regardless of which chart type was fitted
    Given the engineer has fitted control limits using each of the three available chart types from the same Phase I baseline
    And they have a departing observation that triggers a signal under each fitted artefact in turn
    When they record that observation against each fitted artefact
    Then each resulting signal identifies its own direction and its own chart's calibrated boundaries, in the same form regardless of which chart type produced it

  # --- Delivery: being told without polling (Story 2, Goals) ---

  Scenario: Engineer is told about a signal without separately checking the recording call's own result
    Given the engineer has arranged to be told when a signal occurs
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then they are told about the signal without needing to separately inspect the outcome of that recording call

  Scenario: An engineer who has arranged to be told about signals is not told about routine observations
    Given the engineer has arranged to be told when a signal occurs
    And a newly recorded observation's value falls within the calibrated boundaries
    When they record that observation
    Then they are not told anything for it

  Scenario: Multiple signals in the same session are each delivered, in order
    Given the engineer has arranged to be told when a signal occurs
    And they record more than one observation that each represents a genuine departure from the process
    When those observations are recorded, one after another
    Then the engineer is told about every one of them, in the order they occurred

  Scenario: An engineer who has not arranged to be told about anything still gets the determination from the recording call itself
    Given the engineer has not arranged to be told about signals through any other means
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then they can still learn the determination directly from that recording call's own result, exactly as before this story existed

  # --- Delivery must not interrupt the engineer's program (BR-4, ratified "signals are not errors") ---

  Scenario: Recording a genuine signal still completes and returns normally to the engineer
    Given the engineer has fitted control limits and is recording Phase II observations against them
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then the recording call completes and returns the signal as a normal result
    And their program continues running without an unhandled exception

  # --- Absorb, but surface: a failing receiver (settled OQ-1) ---
  #
  # This does not say where the failure surfaces -- see OQ-1 above. It
  # asserts only that the recording call still completes normally, and
  # that the engineer can determine, through the public interface, both that
  # delivery failed and why -- and that the answer does not travel through
  # the receiver that just failed. Tightened after requirements review:
  # "the engineer can tell" alone is satisfied by a bare boolean, and says
  # nothing about the information being public rather than a private
  # attribute. The second Then encodes the circularity constraint as an
  # assertion rather than leaving it in a comment.

  Scenario: A signal receiver that fails does not prevent the recording call from completing
    Given the engineer has arranged to be told about signals through a receiver that will fail when it is notified
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then the recording call still completes and returns the signal determination as normal
    And the engineer can determine, through Caliper's public interface, both that delivery to that receiver failed and why
    And that information does not depend on the receiver mechanism that just failed
