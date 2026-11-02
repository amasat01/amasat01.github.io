# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""``nb same``: two notebooks match in cell types and sources, whatever the Colab setup cell, outputs and ids say."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from raptor_docs_fixture import SITE_ROOT  # noqa: F401  (puts the site root on sys.path)
from raptor_docs.nb import same


def cell(kind, source, cell_id):
    c = {"cell_type": kind, "id": cell_id, "metadata": {}, "source": source.splitlines(True)}
    if kind == "code":
        c.update(execution_count=None, outputs=[])
    return c


def notebook(setup, *sources):
    cells = [cell("code", setup, "colabsetup")] + [cell(k, s, f"c{i}") for i, (k, s) in enumerate(sources)]
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


class Same(unittest.TestCase):
    def run_same(self, a, b):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = []
        for name, nb in (("a", a), ("b", b)):
            p = pathlib.Path(tmp.name) / f"{name}.ipynb"
            p.write_text(json.dumps(nb), encoding="utf-8")
            paths.append(str(p))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = same.main(["same", *paths])
        return rc, out.getvalue()

    BODY = (("markdown", "# One kernel\n"), ("code", "import hawk\nprint(1)\n"))

    def test_only_the_colab_setup_cell_may_differ(self):
        rc, text = self.run_same(notebook("root = 'hawk'\n", *self.BODY), notebook("root = 'eagle'\n", *self.BODY))
        self.assertEqual(rc, 0, text)

    def test_an_edited_code_cell_is_refused(self):
        edited = (self.BODY[0], ("code", "import hawk\nprint(2)\n"))
        rc, text = self.run_same(notebook("x\n", *self.BODY), notebook("x\n", *edited))
        self.assertEqual(rc, 1)
        self.assertIn("cell 1: the source differs", text)

    def test_a_changed_cell_type_or_count_is_refused(self):
        retyped = (("code", "# One kernel\n"), self.BODY[1])
        self.assertEqual(self.run_same(notebook("x\n", *self.BODY), notebook("x\n", *retyped))[0], 1)
        self.assertEqual(self.run_same(notebook("x\n", *self.BODY), notebook("x\n", self.BODY[0]))[0], 1)


if __name__ == "__main__":
    unittest.main()
