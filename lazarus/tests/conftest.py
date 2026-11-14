"""Never point the automated suite at a user's configured cloud project."""

import pytest


@pytest.fixture(autouse=True)
def isolate_persistence(monkeypatch):
    # Cloud tests explicitly install their protocol double after this default.
    monkeypatch.setenv("LAZARUS_STORAGE_BACKEND", "local")
