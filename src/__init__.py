"""VAOS: an AI-first project analysis and continuation platform.

This package root exists because the frozen VAOS architecture nests every
layer (`core`, `domain`, `application`, ...) under `src` as a single
top-level package rather than as independent top-level packages. Every
layer is imported by its full path, e.g. `from src.core.config import
load_config`.
"""
