"""Smoke test: the package installs and imports under the configured toolchain."""

import caliper


def test_package_imports() -> None:
    assert caliper.__doc__


def test_every_exported_name_resolves() -> None:
    # Deliberately does not pin the CONTENTS of __all__. The top-level public
    # surface is still being decided as bounded contexts land; freezing it here
    # would turn a design decision into a test failure. What must always hold
    # is that anything __all__ claims to export actually exists.
    for name in caliper.__all__:
        assert hasattr(caliper, name), f"__all__ exports {name!r}, which is absent"
