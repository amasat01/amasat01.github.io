# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0
"""tools/sync_family_visuals.py: the bundle every docs repo vendors. Deterministic, inside the transfer budget, each
fragment carries the data tables behind its charts, ids never clash with a page's own switch, and --check finds a changed byte."""
import pathlib
import re
import sys
import tempfile
import unittest

SITE_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SITE_ROOT / "tools"))

import sync_family_visuals as S  # noqa: E402


class FamilyVisualsBundle(unittest.TestCase):
    def test_build_is_deterministic_and_within_budget(self):
        for profile in S.PROFILES:
            a, b = S.build(SITE_ROOT, profile), S.build(SITE_ROOT, profile)
            self.assertEqual(a, b, profile)
            raw, total, page = S.sizes(a)
            self.assertLessEqual(page, S.BUDGET_GZIP, f"{profile}: heaviest page {page} bytes gzipped")

    def test_fragments_have_tables_and_namespaced_ids(self):
        for profile, prof in S.PROFILES.items():
            files = S.build(SITE_ROOT, profile)
            for name in prof["fragments"]:
                html = files["fragments/" + name].decode()
                self.assertTrue("<table" in html or 'class="val"' in html, f"{profile}/{name}: no data table or printed bar values")
                self.assertNotRegex(html, r'\b(id|for)="perf-', f"{profile}/{name}: un-namespaced radio id")
                self.assertEqual(len(re.findall(r'<div class="perf-switch', html)), 1, f"{profile}/{name}: one switch per fragment")

    def test_bundle_text_is_clean_of_internal_names(self):
        banned = re.compile(r"\b(nowl|cudaj\w*|feta|parm|brie|ravenn)\b", re.I)
        for profile in S.PROFILES:
            for name, data in S.build(SITE_ROOT, profile).items():
                if name.endswith(".json") or name.endswith(".html") or name.endswith(".js") or name.endswith(".css"):
                    self.assertIsNone(banned.search(data.decode()), f"{profile}/{name}")

    def test_check_finds_a_changed_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "docs").mkdir()
            self.assertEqual(S.main(["--site-root", str(SITE_ROOT), "--target", f"raptor={repo}"]), 0)
            self.assertEqual(S.main(["--check", "--site-root", str(SITE_ROOT), "--target", f"raptor={repo}"]), 0)
            victim = S.target_dir(repo) / "visuals.js"
            victim.write_bytes(victim.read_bytes() + b" ")
            self.assertEqual(S.main(["--check", "--site-root", str(SITE_ROOT), "--target", f"raptor={repo}"]), 1)


if __name__ == "__main__":
    unittest.main()
