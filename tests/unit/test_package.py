"""Smoke test: the package installs and imports under the configured toolchain."""

import caliper


def test_exposes_module_docstring_when_imported() -> None:
    # Arrange/Act: importing the module (above) is the only action under
    # test -- there is nothing else to set up or call.
    # Assert
    assert caliper.__doc__


def test_every_exported_name_resolves() -> None:
    # Arrange: __all__ as declared by the package. Deliberately does not pin
    # the CONTENTS of __all__. The top-level public surface is still being
    # decided as bounded contexts land; freezing it here would turn a design
    # decision into a test failure. What must always hold is that anything
    # __all__ claims to export actually exists.
    exported_names = caliper.__all__

    # Act/Assert: resolving each declared name on the module is itself the
    # check -- there is no separate result to inspect afterwards.
    for name in exported_names:
        assert hasattr(caliper, name), f"__all__ exports {name!r}, which is absent"
