Feature: Configure a log handler for drift signals
  As a Python engineer running Phase II monitoring in production
  I want a drift signal to appear in my application's own logs automatically
  when it fires
  So that I see drift events alongside every other operational concern I
  already monitor through logging, without writing custom code at each call
  site that records an observation

  # -- Pending decisions --
  # The following assumptions and open questions are owned by
  # system-architect and are not yet settled. These scenarios are written
  # to survive any resolution -- none of them names a logger name, a
  # logging level, a handler class, or a registration method. "Arranged
  # for drift signals to be logged" is used throughout as the neutral
  # description of however an engineer connects this built-in receiver,
  # regardless of where BIN-75's attachment mechanism (its own OQ-2)
  # ultimately lives.
  #
  # This story is a consumer of BIN-75's signal-delivery mechanism and
  # signal content. It does not redefine either. It cannot be built until
  # BIN-75's receiver-attachment shape (BIN-75 OQ-2) exists -- see
  # out-of-control-signal-event.feature for that story's own scenarios.
  #
  # [SETTLED -- product owner, 2026-09-11] OQ-1: a failing signal
  #   receiver ABSORBS, but SURFACES -- shared with BIN-75. Applied here
  #   to the specific case of the log handler itself failing to write.
  #   🚨 Still open for system-architect: WHERE it surfaces. Note the
  #   circularity named in both PRDs: if the log handler failed,
  #   surfacing through logging may fail too. The scenario below does
  #   not assert that the failure appears in the log -- that would
  #   presuppose the very mechanism that failed. It says only that the
  #   engineer "can tell" delivery failed, naming no carrier.
  #
  # OQ-2: what standard-library logging level a drift signal uses, given
  #   no severity classification exists yet (BIN-77, R2). Not fixed by
  #   the PRD -- no scenario below names a level.
  #   Owner: system-architect
  #
  # OQ-3: what logger name or namespace Caliper logs under, and how an
  #   engineer attaches or filters their own handler to it. Not fixed by
  #   the PRD -- no scenario below names a logger name. Scenarios assert
  #   only that the engineer's own logging configuration governs where
  #   and how a logged signal appears (BR-3).
  #   Owner: system-architect
  #
  # -- Out of scope for this file (see PRD Non-Goals) --
  # Adopting the `structlog` third-party library -- never for this
  # project; this story uses the standard library's own logging facility
  # (BR-1). Severity classification (BIN-77, R2). Webhook handler
  # (BIN-78, R2). Exception-based signal handling / RaiseOnSignal
  # (BIN-79, R2). Composite handlers / fan-out to multiple simultaneous
  # destinations (BIN-80, R2). A formal, public custom-handler base
  # interface (BIN-81, R2). Western Electric pattern-violation detection
  # (BIN-82, R2). Redefining the signal content BIN-75 defines -- this
  # story logs what BIN-75 delivers; it does not select, summarise, or
  # redefine it.

  # --- Happy path: a signal appears in the engineer's own logs (BR-1, BR-4) ---

  Scenario: Engineer sees a log entry when a drift signal fires
    Given the engineer has arranged for drift signals to be logged
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then they see a log entry that identifies the direction of the departure, the calibrated boundaries that were in force, and the observation that triggered it

  # --- Sad path: routine observations produce no log noise (BR-2) ---

  Scenario: Routine observations do not appear in the logs
    Given the engineer has arranged for drift signals to be logged
    And a newly recorded observation's value falls within the calibrated boundaries
    When they record that observation
    Then no log entry is produced for that observation

  # --- The engineer's own logging configuration governs (BR-3) ---

  Scenario: Logged signals respect the engineer's own logging configuration
    Given the engineer has configured their application's own logging destination and format
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When a drift signal is logged as a result of recording that observation
    Then it appears through that same destination and format, with no separate logging system to configure

  Scenario: Engineer still sees a signal in the log without any additional logging configuration of their own
    Given the engineer has arranged for drift signals to be logged but has not configured any additional destination for their application's own logs
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then they still see the log entry through Python's own default logging behaviour, without needing extra configuration

  # --- Multiple signals during a session (mirrors BIN-75's ordering guarantee) ---

  Scenario: Multiple signals during the same session are each logged independently
    Given the engineer has arranged for drift signals to be logged
    And they record more than one observation that each represents a genuine departure from the process
    When those observations are recorded, one after another
    Then each signal produces its own log entry, in the order the signals occurred

  # --- Sad path: the log handler itself fails to write (shared settled OQ-1) ---
  #
  # Does not assert the failure appears in the log -- that would
  # presuppose the very mechanism that failed. See OQ-1 above.

  Scenario: A failure while logging a signal does not prevent the recording call from completing
    Given the engineer has arranged for drift signals to be logged, and logging is not currently able to succeed
    And a newly recorded observation represents a genuine departure from the process the baseline describes
    When they record that observation
    Then the recording call still completes and returns the signal determination as normal
    And the engineer can determine, through Caliper's public interface, both that the signal could not be logged and why
    And that information does not depend on the logging mechanism that just failed
