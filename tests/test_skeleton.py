"""The top-level packages exist and import, so later missions have a home."""

import importlib

import pytest


@pytest.mark.parametrize("package", ["core", "packs", "evals"])
def test_package_imports(package: str) -> None:
    module = importlib.import_module(package)
    assert module.__doc__, f"{package} has no docstring stating its responsibility"
