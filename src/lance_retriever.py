#!/usr/bin/env python3
"""Compatibility wrapper for the modular LanceDB retrieval package.

Existing workflow contracts call this file directly, and tests import
``lance_retriever`` for helper access. Keep this surface stable while the
implementation lives under ``retrieval``.
"""

from __future__ import annotations

from retrieval import pipeline as _pipeline

globals().update({
    name: getattr(_pipeline, name)
    for name in dir(_pipeline)
    if not name.startswith("__")
})


if __name__ == "__main__":
    from _env_guard import check_environment
    from retrieval.cli import main

    check_environment("lance_retriever.py")
    raise SystemExit(main())
