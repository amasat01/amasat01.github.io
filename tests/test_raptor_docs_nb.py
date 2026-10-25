# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""The notebook gates: ``check`` (filled, no error output, no local path, image budget from the repo's toml) and ``run_gate --list``."""
import contextlib
import io
import os
import tempfile
import unittest

from raptor_docs_fixture import make_repo
from raptor_docs.nb import check, discover, run_gate


def run(module, root, *args):
    out, here = io.StringIO(), os.getcwd()
    os.chdir(root)
    try:
        with contextlib.redirect_stdout(out):
            rc = module.main([module.__name__, *args])
    finally:
        os.chdir(here)
    return rc, out.getvalue()


def stream(text):
    return {"output_type": "stream", "name": "stdout", "text": text}


class Check(unittest.TestCase):
    def check(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return run(check, make_repo(tmp.name, **kwargs))

    def test_a_filled_clean_notebook_passes_with_the_toml_roots(self):
        rc, text = self.check(outputs=[stream("fine\n")])
        self.assertEqual(rc, 0, text)
        self.assertIn("1/1 notebooks fully executed, no errors", text)

    def test_unexecuted_cell_is_refused(self):
        rc, text = self.check(count=None)
        self.assertEqual(rc, 1)
        self.assertIn("UNEXECUTED", text)

    def test_error_output_is_refused(self):
        rc, text = self.check(outputs=[{"output_type": "error", "ename": "E", "evalue": "v", "traceback": ["tb"]}])
        self.assertEqual(rc, 1)
        self.assertIn("ERROR OUTPUT", text)

    def test_local_path_and_warning_are_refused(self):
        self.assertIn("LEAKED OUTPUT", self.check(outputs=[stream("/home/someone/x\n")])[1])
        self.assertIn("LEAKED OUTPUT", self.check(outputs=[stream("UserWarning: hmm\n")])[1])

    def test_image_over_the_toml_budget_is_refused(self):
        def pair(n):
            tag = '<img class="only-%s" src="data:image/png;base64,' + "A" * n + '">'
            return {"output_type": "display_data", "metadata": {}, "data": {"text/html": tag % "light" + tag % "dark"}}
        self.assertIn("IMAGE OVER BUDGET", self.check(outputs=[pair(1001)])[1])
        self.assertEqual(self.check(outputs=[pair(900)])[0], 0)

    def test_a_bare_image_output_has_no_dark_partner(self):
        png = {"output_type": "display_data", "metadata": {}, "data": {"image/png": "A" * 10}}
        rc, text = self.check(outputs=[png])
        self.assertEqual(rc, 1)
        self.assertIn("NO DARK PARTNER", text)


class Discovery(unittest.TestCase):
    def test_list_names_every_notebook_with_its_gate_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            rc, text = run(run_gate, root, "--list", "docs/content")
            self.assertEqual(rc, 0)
            self.assertIn("plain", text)
            self.assertIn("1 notebooks", text)
            self.assertEqual([p.name for p in discover({"eagle": root})["eagle"]], ["nb1.ipynb"])


if __name__ == "__main__":
    unittest.main()
