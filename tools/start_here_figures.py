# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The three charts of ``start_here.md`` as light/dark PNG pairs (``_static/figures/start_here/NAME.png`` and ``NAME-dark.png``).

Runs ``notebooks/raptor_start_here.ipynb`` (CPU, a temporary copy in which each ``plt.show()`` becomes
``raptor_docs.themed_figure.show()``) and writes the two images of each chart. The notebook itself stays standalone.
Needs eagle, hawk, torch, matplotlib, nbclient and ipykernel.

    python tools/start_here_figures.py
"""
import base64
import pathlib
import re
import sys

import nbformat
from nbclient import NotebookClient

SITE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE))
#: the notebook's charts in order of appearance
NAMES = ("arc", "landings", "fit")
#: the page shows them at 560 and 380 px wide; 160 dpi gives about twice that many pixels (2x)
DPI = 160


def main() -> int:
    nb = nbformat.read(SITE / "notebooks" / "raptor_start_here.ipynb", as_version=4)
    shown = [c for c in nb.cells if c.cell_type == "code" and "plt.show()" in c.source]
    if len(shown) != len(NAMES):
        sys.exit(f"expected {len(NAMES)} charts, found {len(shown)}")
    for c in shown:
        c.source = f"import raptor_docs.themed_figure as _tf; _tf.DPI = {DPI}\nfrom raptor_docs.themed_figure import show\n" + c.source.replace("plt.show()", "show()")
    NotebookClient(nb, timeout=900, kernel_name=nb.metadata.get("kernelspec", {}).get("name", "python3"),
                   resources={"metadata": {"path": str(SITE / "notebooks")}}).execute()
    out = SITE / "_static" / "figures" / "start_here"
    for name, cell in zip(NAMES, shown):
        html = "".join(o["data"]["text/html"] for o in cell.outputs if "text/html" in o.get("data", {}))
        light, dark = (base64.b64decode(b) for b in re.findall(r'src="data:image/png;base64,([^"]*)"', html))
        (out / f"{name}.png").write_bytes(light)
        (out / f"{name}-dark.png").write_bytes(dark)
        print("wrote", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
