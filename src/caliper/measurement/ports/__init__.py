"""Measurement ports -- the seam between the domain and external providers.

``JudgeProviderPort`` is the only tenant so far: the boundary through which
a ``Judge`` obtains a score without the domain layer ever seeing a provider
SDK, an HTTP client, or a raw response payload.

# added by domain-implementer BIN-103
"""
