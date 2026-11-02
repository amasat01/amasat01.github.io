#!/usr/bin/env python3
# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0

"""Check that two notebooks teach the same thing: the same cell types and the same cell sources.

hawk and eagle each carry a copy of the first-kernel notebook. They differ in one place on purpose: the Colab setup
cell, which ``colab_setup`` generates per repo. That cell (by its id) is the only difference allowed; outputs, ids and
metadata are not compared. Any other edit to one copy is reported with the cell number.

    python -m raptor_docs.nb same <a.ipynb> <b.ipynb>    # exit 1 on a difference
"""
import json
import pathlib
import sys

from raptor_docs.nb.colab_setup import CELL_ID


def cells(path) -> list[tuple[str, str]]:
    """``(cell type, source)`` of every cell except the generated Colab setup cell."""
    nb = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return [(c["cell_type"], "".join(c["source"])) for c in nb["cells"] if c.get("id") != CELL_ID]


def differences(a, b) -> list[str]:
    ca, cb = cells(a), cells(b)
    out = [f"cell count: {len(ca)} against {len(cb)}"] if len(ca) != len(cb) else []
    out += [f"cell {i}: {x[0]} against {y[0]}" if x[0] != y[0] else f"cell {i}: the source differs"
            for i, (x, y) in enumerate(zip(ca, cb)) if x != y]
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m raptor_docs.nb same <a.ipynb> <b.ipynb>", file=sys.stderr)
        return 2
    found = differences(argv[1], argv[2])
    for line in found:
        print(f"DIFFERENT {line}")
    if not found:
        print(f"[nb_same] {argv[1]} and {argv[2]} match (cell types and sources, Colab setup cell aside)")
    return 1 if found else 0
