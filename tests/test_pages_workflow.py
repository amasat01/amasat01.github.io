# Copyright 2026 Alessandro Masat
# SPDX-License-Identifier: Apache-2.0

"""pages.yml's docs-fresh job tells a failed generator from a stale page.

The generator step and the diff step are separate, and "out of date" is said
only by the diff step.
"""

import pathlib
import unittest

_WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows" / "pages.yml"


class PagesWorkflow(unittest.TestCase):
    def test_out_of_date_is_said_only_by_the_diff_step(self):
        text = _WORKFLOW.read_text()
        self.assertEqual(text.count("out of date"), 1)
        diff_step = text[text.index("generated pages match the committed ones"):]
        self.assertIn("out of date", diff_step.split("\n  build:")[0])

    def test_generator_step_does_not_run_the_diff(self):
        text = _WORKFLOW.read_text()
        gen = text[text.index("regenerate the pages from the cards"):
                   text.index("generated pages match the committed ones")]
        self.assertNotIn("git diff", gen)
        self.assertIn("generator crashed", gen)
        self.assertIn("generator or companion missing", gen)


if __name__ == "__main__":
    unittest.main()
