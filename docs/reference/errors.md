# Exceptions

Every exception Caliper raises inherits from `CaliperError` and carries a
`category`, a machine-readable `context`, and a human-facing `recovery_hint`.

Branch on the type or on `context`, never on the message text. Message wording
is not part of the contract and will change; `category` and the required
`context` keys are.

::: drift_caliper.CaliperError

::: drift_caliper.InvalidParameterError

::: drift_caliper.MissingPrerequisiteError

::: drift_caliper.ProviderError

::: drift_caliper.MalformedResponseError

::: drift_caliper.JudgeRefusalError

::: drift_caliper.ProvenanceMismatchError

::: drift_caliper.InvalidObservationError

::: drift_caliper.InsufficientBaselineError

::: drift_caliper.DegenerateBaselineError
