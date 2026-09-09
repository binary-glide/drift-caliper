"""Measurement domain -- entities and value objects, no infrastructure.

One value object per module (ADR-006 section 7). Nothing in this package
imports a port, an adapter, or any infrastructure library -- the seam to
the outside world is ``caliper.measurement.ports``.

# added by domain-implementer BIN-103
"""
