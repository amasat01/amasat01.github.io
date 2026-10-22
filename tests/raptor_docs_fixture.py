# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""A throwaway repo for the raptor_docs tests: a docs/raptor_docs.toml, a helper module, one notebook, one generator."""
import json
import pathlib
import sys

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(SITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SITE_ROOT))

TOML = '''repo = "eagle"
helper_dirs = ["docs/content/_shared"]
image_budget = 1000
nb_roots = ["docs/content"]
fresh = ["python tools/gen.py"]

[helper_needs]
"docs/content/_shared/nb_helpers.py" = ["matplotlib"]
'''
#: a generator that is fresh when docs/out.txt holds ``ok`` (exit 0), else stale (1); ``--write`` mints it
GEN = '''import pathlib, sys
p = pathlib.Path("docs/out.txt")
if "--check" not in sys.argv:
    p.write_text("ok")
elif not p.is_file() or p.read_text() != "ok":
    sys.exit(1)
'''


def notebook(source, outputs=(), count=1, tags=()):
    cell = {"cell_type": "code", "id": "c1", "metadata": {"tags": list(tags)}, "source": source, "outputs": list(outputs),
            "execution_count": count}
    return {"cells": [cell], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def make_repo(tmp, source="import numpy as np\nimport eagle\nfrom nb_helpers import plot\n", **nb_kwargs) -> pathlib.Path:
    root = pathlib.Path(tmp)
    files = {"docs/raptor_docs.toml": TOML, "tools/gen.py": GEN,
             "docs/content/_shared/nb_helpers.py": "def plot():\n    import matplotlib\n",
             "docs/content/nb1.ipynb": json.dumps(notebook(source, **nb_kwargs))}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root
