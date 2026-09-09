"""Smoke test: the package installs and imports under the configured toolchain."""

import caliper


def test_package_imports() -> None:
    assert caliper.__all__ == []
