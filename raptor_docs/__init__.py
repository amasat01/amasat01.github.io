# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Shared docs tooling for the RAPTOR family: a Sphinx skin, the notebook gates, the freshness check, the capability map.

Each repo keeps one data file, ``docs/raptor_docs.toml``; ``config()`` reads it. Nothing here is imported by a shipped package.
"""
import pathlib
import tomllib

DEFAULTS = {"repo": "", "helper_dirs": [], "helper_needs": {}, "preinstalled": ["numpy", "IPython"], "image_budget": 500_000,
            "nb_roots": ["docs/content"], "jax_floor": "", "fresh": []}


def find_root(start=None) -> pathlib.Path:
    """The repo root: the nearest directory, from ``start`` (default: the working directory) up, with ``docs/raptor_docs.toml``."""
    here = pathlib.Path(start or ".").resolve()
    for d in (here, *here.parents):
        if (d / "docs" / "raptor_docs.toml").is_file():
            return d
    raise SystemExit(f"raptor_docs: no docs/raptor_docs.toml found from {here} upwards")


def config(root=None) -> dict:
    """The repo's settings (``DEFAULTS`` overridden by its toml), plus ``root`` as a path."""
    root = pathlib.Path(root).resolve() if root else find_root()
    data = tomllib.loads((root / "docs" / "raptor_docs.toml").read_text(encoding="utf-8"))
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        raise SystemExit(f"{root}/docs/raptor_docs.toml: unknown keys {unknown}")
    return {**DEFAULTS, **data, "root": root}
