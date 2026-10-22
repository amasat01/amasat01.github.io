# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""Every docs notebook opens on Colab with its packages installed and its helper files in place.

``raptor_docs.nb.colab_setup`` writes the setup cell (tag ``colab-setup``) that, on Colab only, ``pip install``s what the notebook
imports and downloads the helper files it needs. These tests run it on a fixture repo and fail when

* a notebook lacks the current generated cell (re-run the generator, do not hand-edit it);
* a notebook, or a helper it uses, imports a third-party module the cell does not install;
* the cell names a repository file that does not exist.

RED: delete the cell from a notebook, add ``import scipy`` to one, or rename the helper and the matching test fails.
"""
import ast
import json
import tempfile
import unittest

from raptor_docs_fixture import make_repo
from raptor_docs.nb import colab_setup as gen


def load(root):
    path = root / "docs" / "content" / "nb1.ipynb"
    return path, json.loads(path.read_text(encoding="utf-8"))


def regenerate(root):
    """Write the setup cell into every notebook, as ``colab_setup`` without ``--check`` does."""
    gen.configure(root)
    path, nb = load(root)
    gen.apply(nb, path)
    path.write_text(json.dumps(nb, indent=1), encoding="utf-8")


def setup_cell(nb):
    cells = [c for c in nb["cells"] if gen.TAG in c.get("metadata", {}).get("tags", []) and c["cell_type"] == "code"]
    return "".join(cells[0]["source"]) if len(cells) == 1 else None


class ColabSetup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo(self._tmp.name)
        regenerate(self.root)
        self.path, self.nb = load(self.root)
        self.cell = setup_cell(self.nb)

    def test_setup_cell_is_current(self):
        self.assertIsNotNone(self.cell, "no Colab setup cell")
        self.assertFalse(gen.apply(self.nb, self.path), "the cell is stale")

    def test_deleting_the_cell_makes_it_stale(self):
        self.nb["cells"] = [c for c in self.nb["cells"] if gen.TAG not in c.get("metadata", {}).get("tags", [])]
        self.assertTrue(gen.apply(self.nb, self.path))

    def test_every_third_party_import_is_installed_by_the_cell(self):
        helpers = gen.helper_modules()
        imported = set()
        for src in gen.code_sources(self.nb):
            imported |= gen._imports(src, "all")
        for mod in sorted(imported & set(helpers)):  # a helper's own third-party needs count too
            rel = helpers[mod]
            imported |= gen._imports((self.root / rel).read_text(encoding="utf-8"), "top") | set(gen.HELPER_NEEDS.get(rel, ()))
        missing = [m for m in sorted(imported) if m not in gen.STDLIB and m not in gen.PREINSTALLED and m not in helpers
                   and f'"{gen.PYPI.get(m)}' not in self.cell.replace('f"', '"')]
        self.assertEqual(missing, [])
        self.assertIn('"raptor-eagle', self.cell.replace('f"', '"'))
        self.assertIn('"matplotlib', self.cell)  # the helper's own need, from helper_needs

    def test_a_module_with_no_pypi_name_stops_the_generator(self):
        _, nb = load(self.root)
        user = next(c for c in nb["cells"] if c["cell_type"] == "code" and gen.TAG not in c["metadata"]["tags"])
        user["source"] = "import scipy\n"
        with self.assertRaises(SystemExit) as why:
            gen.apply(nb, self.path)
        self.assertIn("scipy", str(why.exception))

    def test_every_helper_the_notebook_imports_is_downloaded_and_exists(self):
        import re
        downloaded = re.findall(r'^\s+"([\w./-]+)",$', self.cell, re.M)
        self.assertIn("docs/content/_shared/nb_helpers.py", downloaded)
        for rel in downloaded:
            self.assertTrue((self.root / rel).is_file(), f"the setup cell names {rel}, which is not in the repository")
        (self.root / "docs/content/_shared/nb_helpers.py").rename(self.root / "docs/content/_shared/renamed.py")
        gen.configure(self.root)
        self.assertNotIn("docs/content/_shared/nb_helpers.py", [h for h in gen.helper_modules().values()])

    def test_the_cell_matches_the_cuda_major_and_says_plainly_when_it_runs_on_the_cpu(self):
        self.assertIn("Running on the CPU (no GPU in this runtime). For a GPU: ", self.cell)
        self.assertIn("Runtime → Change runtime type → T4 GPU.", self.cell)
        self.assertIn("Settings → Accelerator → GPU T4 x2.", self.cell)
        self.assertNotIn('extra = "[cuda12]"', self.cell)
        for needle in ('"cupy-cuda{m}x"', "torch.version.cuda", "CUDA Version: (", 'extra = f"[cuda{major}]"'):
            self.assertIn(needle, self.cell)

    def test_the_cell_has_the_release_candidate_and_branch_switches(self):
        self.assertIn('os.environ.get("RAPTOR_PRE")', self.cell)
        self.assertIn('os.environ.get("RAPTOR_REF", "main")', self.cell)
        self.assertIn("Pre-release test: installing with --pre, helper files from {ref}.", self.cell)
        self.assertIn("/{ref}/", self.cell)
        self.assertNotIn("/main/", self.cell)
        self.assertIn('os.environ.get("RAPTOR_RAW_BASE", "https://raw.githubusercontent.com")', self.cell)
        self.assertIn('os.environ.get("RAPTOR_WORKDIR")', self.cell)

    def test_the_generated_cell_is_valid_python(self):
        ast.parse(self.cell)

    def test_the_cell_names_no_repo_tool_path(self):
        self.assertIn("raptor_docs.nb colab_setup", self.cell)


if __name__ == "__main__":
    unittest.main()
