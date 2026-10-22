#!/usr/bin/env python3
# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0

"""Gate: every notebook under the given directories must be EXECUTED - each
code cell with non-blank source carries an execution count and no `error` output. The docs publish
runs this on the notebooks `make nbexec` filled, before rendering them with
Sphinx execution switched off, so an unfilled notebook can never reach the
published pages silently (nor trigger a second, hidden execution).

Also refuses a notebook whose OUTPUT (stream text, `text/plain`,
`text/html`, or an error traceback) contains an absolute local-machine
path. The docs publish to a public site; a committed output with
`/local/...`, `/home/<user>/...` etc. leaks the machine that built
them. Only rendered OUTPUT is scanned, not cell source. A stored Python
warning (``UserWarning:`` and the like) is refused too: it is noise from the
machine that ran the notebook, and it usually carries such a path.

Refuses a picture that is not a light/dark pair (``raptor_docs.themed_figure``: an html output of two data images, only-light and
only-dark; a bare image output has no dark partner). Finally, refuses a stored image larger than the repo's image budget: the docs show the
stored plots (nothing re-executes at build), so a runaway figure would bloat
the repository.
"""
import pathlib
import re
import sys

import nbformat

from raptor_docs import config

# Deliberately narrow: absolute local-filesystem roots a committed output
# should never contain, not a general "looks like a path" heuristic.
# Bytes of base64 per stored image output: ``image_budget`` in the repo's docs/raptor_docs.toml.

_LEAK_PATTERNS = [re.compile(p) for p in (r"/local/", r"/home/", r"/tmp/", r"/dev/shm/", r"/root/", r"/Users/",
                                          r"C:\\Users")]
_WARNING = re.compile(r"\b\w*Warning: ")


def _text_of(value) -> str:
    return "".join(value) if isinstance(value, list) else str(value)


def _leaked_path(text: str) -> str | None:
    for pat in _LEAK_PATTERNS:
        if pat.search(text):
            return pat.pattern
    return None


def _output_leaks(cell) -> list[str]:
    leaks = []
    for out in cell.get("outputs", []):
        texts = []
        if out.get("output_type") == "stream":
            texts.append(_text_of(out.get("text", "")))
        elif out.get("output_type") in ("display_data", "execute_result"):
            data = out.get("data", {})
            texts.extend(_text_of(data[mime]) for mime in ("text/plain", "text/html") if mime in data)
        elif out.get("output_type") == "error":
            texts.append(_text_of(out.get("traceback", [])))
        for text in texts:
            pattern = _leaked_path(text)
            if pattern:
                leaks.append(pattern)
            if _WARNING.search(text):
                leaks.append("a Python warning")
    return leaks


_DATA_IMG = re.compile(r'<img\b[^>]*\bsrc="data:image/[^"]*"[^>]*>')


def _image_sizes(cell) -> list[int]:
    """Bytes of every stored image of a code cell: an image output, or a ``data:`` image inside an html output."""
    sizes = []
    for out in cell.get("outputs", []):
        data = out.get("data", {})
        sizes += [len(_text_of(data[mime])) for mime in ("image/png", "image/jpeg") if mime in data]
        if "text/html" in data:
            sizes += [len(m.group(0)) for m in _DATA_IMG.finditer(_text_of(data["text/html"]))]
    return sizes


def _oversized_images(cell, budget) -> list[int]:
    return [size for size in _image_sizes(cell) if size > budget]


def _unpaired_images(cell) -> list[str]:
    """A picture a page shows in both themes is two images, ``only-light`` and ``only-dark`` (``raptor_docs.themed_figure``).
    Names each image output that is not: a bare image output, or an html output whose data images are not in matching pairs."""
    bad = []
    for out in cell.get("outputs", []):
        data = out.get("data", {})
        if any(mime in data for mime in ("image/png", "image/jpeg")):
            bad.append("a bare image output (use themed_figure.show)")
        if "text/html" in data:
            tags = _DATA_IMG.findall(_text_of(data["text/html"]))
            light = sum('only-light' in t for t in tags)
            dark = sum('only-dark' in t for t in tags)
            if tags and (light != dark or light + dark != len(tags)):
                bad.append(f"{light} only-light and {dark} only-dark images among {len(tags)}")
    return bad


def main(argv: list[str]) -> int:
    cfg = config()
    budget = cfg["image_budget"]
    roots = [pathlib.Path(a) for a in argv[1:]] or [cfg["root"] / r for r in cfg["nb_roots"]]
    notebooks = sorted(
        p for r in roots
        for p in ([r] if r.suffix == ".ipynb" else r.rglob("*.ipynb"))
        if ".ipynb_checkpoints" not in p.parts
    )
    if not notebooks:
        print("nb_check_filled: no notebooks found under", [str(r) for r in roots])
        return 2
    bad = []
    errored = []
    leaked = []
    heavy = []
    unpaired = []
    for p in notebooks:
        nb = nbformat.read(p, as_version=4)
        unexecuted = [
            i for i, c in enumerate(nb.cells)
            if c.cell_type == "code" and c.source.strip() and c.get("execution_count") is None
            and "colab-setup" not in c.get("metadata", {}).get("tags", [])  # generated, no output
        ]
        if unexecuted:
            bad.append((p, unexecuted))
        failed = [i for i, c in enumerate(nb.cells) if c.cell_type == "code"
                  and any(out.get("output_type") == "error" for out in c.get("outputs", []))]
        if failed:
            errored.append((p, failed))
        for i, c in enumerate(nb.cells):
            if c.cell_type != "code":
                continue
            for pattern in _output_leaks(c):
                leaked.append((p, i, pattern))
            heavy.extend((p, i, size) for size in _oversized_images(c, budget))
            unpaired.extend((p, i, why) for why in _unpaired_images(c))
    for p, cells in bad:
        print(f"[nb_check_filled] UNEXECUTED {p}: code cells {cells[:6]}"
              f"{'...' if len(cells) > 6 else ''}")
    for p, cells in errored:
        print(f"[nb_check_filled] ERROR OUTPUT {p}: code cells {cells[:6]}{'...' if len(cells) > 6 else ''}")
    for p, i, pattern in leaked:
        print(f"[nb_check_filled] LEAKED OUTPUT {p}: code cell {i} output matched {pattern!r}")
    for p, i, size in heavy:
        print(f"[nb_check_filled] IMAGE OVER BUDGET {p}: code cell {i} image is {size} bytes "
              f"(budget {budget})")
    for p, i, why in unpaired:
        print(f"[nb_check_filled] NO DARK PARTNER {p}: code cell {i} has {why}")
    filled = len(notebooks) - len({p for p, _ in bad} | {p for p, _ in errored})
    print(f"[nb_check_filled] {filled}/{len(notebooks)} notebooks fully executed, no errors")
    return 1 if (bad or errored or leaked or heavy or unpaired) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
