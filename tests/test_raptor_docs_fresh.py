# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""``python -m raptor_docs.fresh`` says which failure it is, by exit code, and refuses a second copy of a shipped file.

Generator exit codes: 0 fresh, 1 stale, 3 a card the docs cite is missing, 4 a tool or companion missing, anything else a crash.
Delete-the-check: with ``SHADOWS`` emptied the planted copy passes (the RED the check exists to give), see below.
"""
import contextlib
import io
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from raptor_docs_fixture import SITE_ROOT, make_repo
from raptor_docs import fresh


def run(root, *flags):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fresh.main([*flags, "--root", str(root), "--site", str(SITE_ROOT)])
    return rc, out.getvalue() + err.getvalue()


def set_generators(root, *cmds):
    toml = root / "docs" / "raptor_docs.toml"
    lines = [ln for ln in toml.read_text().splitlines() if not ln.startswith("fresh")]
    toml.write_text(f"fresh = {list(cmds)!r}\n".replace("'", '"') + "\n".join(lines) + "\n")


class Fresh(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(self._tmp.name)

    def test_write_mints_then_check_is_fresh_and_a_stale_page_exits_1(self):
        self.assertEqual(run(self.root, "--check")[0], 1)
        self.assertEqual(run(self.root, "--write")[0], 0)
        self.assertEqual(run(self.root, "--check")[0], 0)
        (self.root / "docs" / "out.txt").write_text("hand edit")
        rc, text = run(self.root, "--check")
        self.assertEqual(rc, 1)
        self.assertIn("out of date", text)

    def test_each_generator_exit_code_gets_its_own_message(self):
        for code, needle in ((3, "card the docs cite is missing"), (4, "generator or companion missing"), (7, "crashed (rc 7)")):
            (self.root / "tools" / "gen.py").write_text(f"import sys\nprint('why', file=sys.stderr)\nsys.exit({code})\n")
            rc, text = run(self.root, "--check")
            self.assertEqual(rc, code if code in (3, 4) else 1, text)
            self.assertIn(needle, text)
            self.assertNotIn("out of date", text)

    def test_an_uncaught_exception_is_a_crash_not_a_stale_page(self):
        (self.root / "tools" / "gen.py").write_text("raise RuntimeError('boom')\n")
        rc, text = run(self.root, "--check")
        self.assertEqual(rc, 1)
        self.assertIn("generator crashed", text)
        self.assertNotIn("out of date", text)

    def test_a_missing_generator_is_a_missing_companion(self):
        set_generators(self.root, "python tools/not_there.py")
        rc, text = run(self.root, "--check")
        self.assertEqual(rc, 4)
        self.assertIn("not_there.py", text)

    def test_out_of_date_is_said_only_for_a_stale_generator(self):
        text = pathlib.Path(fresh.__file__).read_text()
        self.assertEqual(text.count("out of date:"), 1)
        self.assertIn("1: \"out of date", text)


class Shadows(unittest.TestCase):
    """A planted second copy exits 1 naming it; with the shadow list removed it passes (RED expected)."""

    #: (planted file, the path the error names: a whole directory is named once)
    PLANTS = (("docs/_tools/nb_check_filled.py",) * 2, ("docs/_static/raptor-theme.css",) * 2,
              ("docs/_static/family_visuals/map.html", "docs/_static/family_visuals"),
              ("docs/_static/fonts/recursive-full.woff2", "docs/_static/fonts"), ("tools/docs_fresh.sh",) * 2)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(self._tmp.name)
        run(self.root, "--write")

    def test_the_clean_repo_is_fresh(self):
        self.assertEqual(run(self.root, "--check")[0], 0)

    def test_each_planted_copy_exits_1_naming_it(self):
        for rel, named in self.PLANTS:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
            rc, text = run(self.root, "--check")
            self.assertEqual(rc, 1, rel)
            self.assertIn(named, text)
            path.unlink()

    def test_delete_the_check_the_planted_copy_passes(self):
        plant = self.root / "docs/_tools/nb_check_filled.py"
        plant.parent.mkdir(parents=True)
        plant.write_text("x")
        with mock.patch.object(fresh, "SHADOWS", ()):
            self.assertEqual(run(self.root, "--check")[0], 0)  # the check is gone: this is the RED a reviewer must see
        self.assertEqual(run(self.root, "--check")[0], 1)  # restored


class CapmapGenerator(unittest.TestCase):
    """A stale capability-map SVG reds; dropping ``capmap`` from the generators lets it pass (RED expected)."""

    CMD = "python -m raptor_docs.capmap -o docs/capmap.svg"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(self._tmp.name)
        set_generators(self.root, self.CMD)
        patch = mock.patch.dict(os.environ, {"PYTHONPATH": str(SITE_ROOT)})  # the generator is a subprocess in the fixture repo
        patch.start()
        self.addCleanup(patch.stop)

    def test_fresh_stale_and_delete_the_check(self):
        self.assertEqual(run(self.root, "--write")[0], 0)
        self.assertEqual(run(self.root, "--check")[0], 0)
        svg = self.root / "docs" / "capmap.svg"
        svg.write_text(svg.read_text().replace("Capability map", "Stale map"))
        self.assertEqual(run(self.root, "--check")[0], 1)
        set_generators(self.root)  # the generator dropped from the TOML
        self.assertEqual(run(self.root, "--check")[0], 0)  # RED expected: the stale svg passes
        set_generators(self.root, self.CMD)  # restored
        self.assertEqual(run(self.root, "--check")[0], 1)


if __name__ == "__main__":
    unittest.main()
