# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""``python -m raptor_docs.inventory`` passes when every public name has a Python-domain page, and names the ones that don't."""
import contextlib
import io
import pathlib
import sys
import tempfile
import unittest
import zlib

from raptor_docs import inventory


def write_inventory(path, entries):
    """A Sphinx v2 objects.inv: four header lines, then zlib lines `name domain:role priority uri dispname`."""
    header = b"# Sphinx inventory version 2\n# Project: demo\n# Version: 0\n# The remainder of this file is compressed using zlib.\n"
    body = "".join(f"{name} {role} 1 {name}.html -\n" for name, role in entries).encode()
    path.write_bytes(header + zlib.compress(body))


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        pkg = self.tmp / "demo_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('__all__ = ["Array", "launch", "glossed"]\n')
        sys.path.insert(0, str(self.tmp))
        self.addCleanup(sys.path.remove, str(self.tmp))
        self.addCleanup(sys.modules.pop, "demo_pkg", None)
        self.inv = self.tmp / "objects.inv"

    def run_check(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = inventory.main([str(self.inv), "demo_pkg", *extra])
        return rc, out.getvalue()

    def test_every_name_documented_passes(self):
        write_inventory(self.inv, [("demo_pkg.Array", "py:class"), ("demo_pkg.core.launch", "py:function"),
                                   ("demo_pkg.glossed", "py:data")])
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)

    def test_a_glossary_term_is_not_a_page(self):
        write_inventory(self.inv, [("demo_pkg.Array", "py:class"), ("demo_pkg.launch", "py:function"),
                                   ("glossed", "std:term")])
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("demo_pkg.glossed", out)
        self.assertNotIn("demo_pkg.Array", out)

    def test_allow_skips_a_name(self):
        write_inventory(self.inv, [("demo_pkg.Array", "py:class"), ("demo_pkg.launch", "py:function")])
        rc, out = self.run_check("--allow", "glossed")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
