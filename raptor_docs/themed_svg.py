# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Every generated picture is two files with fixed colours: ``name.svg`` (light) and ``name-dark.svg`` (dark).

An SVG shown with ``<img>`` cannot see the docs theme toggle, only the operating system's setting, so a colour media query inside
it is wrong on a page whose theme differs from the system's. Instead the page shows both files and the theme picks one (the
``only-light`` / ``only-dark`` classes in ``raptor-theme.css``); a README uses ``<picture>``.

A generator passes ``write_pair`` a function ``render(palette) -> str`` and the light/dark palettes below do the rest.
"""
import pathlib
import sys

from raptor_docs.themed_figure import DARK, LIGHT  # noqa: E402  the one palette, shared with the notebook charts

PALETTES = {"light": LIGHT, "dark": DARK}


def dark_path(path) -> pathlib.Path:
    """``a/b.svg`` -> ``a/b-dark.svg``."""
    p = pathlib.Path(path)
    return p.with_name(p.stem + "-dark" + p.suffix)


def renders(path, render) -> dict:
    """``{file: text}`` of the pair: ``render(palette)`` called once per mode."""
    return {pathlib.Path(path): render(LIGHT), dark_path(path): render(DARK)}


def write_pair(path, render, check=False) -> int:
    """Write the pair (``check``: compare instead; 1 and a line on stderr for each file that differs). Returns an exit code."""
    rc = 0
    for file, text in renders(path, render).items():
        if check:
            if not file.is_file() or file.read_text(encoding="utf-8") != text:
                print(f"{file}: out of date", file=sys.stderr)
                rc = 1
        else:
            file.write_text(text, encoding="utf-8")
    return rc


def bad_svgs(docs_static) -> list:
    """``[(file, why)]`` for the committed SVGs under ``docs_static`` that break the rule: a colour media query inside, or a
    light file without its dark partner. Not covered: ``brand/`` (the logo files are fixed-colour marks that read on both
    surfaces and carry no query; the first check below still applies to them)."""
    root = pathlib.Path(docs_static)
    out = []
    for svg in sorted(root.rglob("*.svg")):
        name = svg.name
        if "prefers-color-scheme" in svg.read_text(encoding="utf-8", errors="replace"):
            out.append((svg, "contains prefers-color-scheme: write a light/dark pair with raptor_docs.themed_svg"))
        if "brand" in svg.relative_to(root).parts[:-1]:
            continue
        stem = svg.stem
        if stem.endswith(("-dark", "_dark")):
            partner = svg.with_name(stem[:-5] + ("-" if stem.endswith("-dark") else "_") + "light" + ".svg") \
                if stem.endswith("_dark") else svg.with_name(stem[:-5] + ".svg")
        elif stem.endswith("_light"):
            partner = svg.with_name(stem[:-6] + "_dark.svg")
        else:
            partner = dark_path(svg)
        if not partner.is_file():
            out.append((svg, f"has no partner {partner.name}"))
    return out
