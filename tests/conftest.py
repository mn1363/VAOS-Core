"""Shared pytest configuration for the VAOS test suite.

No fixtures are defined yet: the `core` layer's tests are self-contained
and rely on pytest's built-in `tmp_path` and `monkeypatch` fixtures. This
file exists as the place future phases add shared fixtures as the suite
grows.
"""
