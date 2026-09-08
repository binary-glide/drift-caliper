Feature: Scoring criteria as a text rubric
  As a Python engineer wiring quality measurement into my LLM agent
  I want to define a text rubric that anchors the judge's assessment
  So that my quality scores measure what matters to my specific use case
  rather than an opaque LLM default

  # -- Pending decision (OQ-1) --
  # Whether missing or invalid scoring criteria should cause
  # configuration to FAIL or merely WARN has not been ratified.
  #
  # The PRD recommends an error (at scoring time at the latest),
  # because unanchored scores produce baselines nobody can explain.
  # However, the case is weaker than BIN-57's model-pinning
  # fail-loudly decision: missing criteria undermine interpretability,
  # not statistical integrity directly.
  #
  # The scenarios below follow the PRD recommendation (invalid criteria
  # are rejected). system-architect owns the final enforcement mechanism
  # and timing.

  # -- Pending decision (OQ-3) --
  # Whether criteria are configured at judge creation, at monitoring
  # setup, per-call, or some combination is not yet settled. These
  # scenarios are deliberately neutral on the attachment point -- they
  # describe configuring and inspecting criteria without specifying
  # where in the pipeline the configuration happens.

  # --- Happy path (BR-1 happy, BR-5) ---

  Scenario: Engineer defines a text rubric as scoring criteria
    Given the engineer has a text rubric describing what to evaluate
    When they configure scoring criteria with that rubric
    Then the criteria should be accepted
    And the engineer should be able to inspect the configured criteria

  # --- Sad paths: empty and whitespace-only criteria (BR-1 sad, BR-4) ---

  Scenario: Engineer attempts to define empty criteria
    Given the engineer provides an empty string as criteria
    When they attempt to configure scoring criteria
    Then the criteria should be rejected
    And the engineer should be told that criteria are required to anchor quality scores
    And the message should include an example of a valid rubric

  Scenario: Engineer attempts to define whitespace-only criteria
    Given the engineer provides a string containing only whitespace as criteria
    When they attempt to configure scoring criteria
    Then the criteria should be rejected
    And the engineer should be told that non-empty criteria are required to anchor quality scores
    And the message should include an example of a valid rubric

  # --- Edge cases: preservation and opacity (BR-2, BR-3) ---

  Scenario: Criteria text is preserved exactly as provided
    Given the engineer has configured scoring criteria with specific text including whitespace and punctuation
    When they inspect the configured criteria
    Then the reported criteria should match the text they originally provided character for character

  Scenario: Engineer defines a multi-line rubric with detailed instructions
    Given the engineer has a multi-line rubric including dimensions and example anchors
    When they configure scoring criteria with that rubric
    Then the criteria should be accepted
    And the full multi-line text should be preserved when inspected

  Scenario: Engineer defines a minimal single-sentence rubric
    Given the engineer has a brief single-sentence rubric
    When they configure scoring criteria with that rubric
    Then the criteria should be accepted
    And the engineer should be able to inspect the configured criteria

  # --- Boundary value: whitespace padding (BR-1 / BR-2 boundary) ---

  Scenario: Criteria with surrounding whitespace are accepted and preserved
    Given the engineer provides criteria with leading and trailing spaces around meaningful text
    When they configure scoring criteria with that text
    Then the criteria should be accepted
    And the reported criteria should include the surrounding spaces exactly as provided
